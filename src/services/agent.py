from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from openai import OpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .data import DataStore, normalize_drug_name
from .interactions import find_interaction, unique_pairs
from .vector_store import make_pinecone_index, _embed


class DrugAnalysisState(TypedDict):
    drugs: List[str]
    resolutions: List[Dict[str, Any]]  # brand/synonym -> dataset drug (via RxNorm)
    question: str                # optional free-text question from the user
    renal_impairment: str        # "none" | "mild" | "moderate" | "severe"
    hepatic_impairment: str      # "none" | "mild" | "moderate" | "severe"
    retrieved_drugs: Dict[str, Any]
    pk_context: List[Dict[str, Any]]   # patient-context-aware semantic retrieval
    interactions: List[Dict[str, Any]]
    impairment_flags: List[Dict[str, Any]]
    deep_evidence: List[Dict[str, Any]]
    key_flags: List[str]
    synthesis: str


_PK_FIELDS = ("drug_name", "fe", "renal", "non_renal", "enzymes", "transporters")

# Pinecone cosine-similarity floors for the two RAG nodes (tuning constants, not
# secrets — kept named so they're greppable and adjustable in one place).
_CONTEXT_MIN_SCORE = 0.55       # retrieve_context: PK-landscape relevance floor
_DEEP_EVIDENCE_MIN_SCORE = 0.75  # deep_evidence: same-pathway similarity floor


def _pk_summary(meta: dict) -> dict:
    return {k: meta.get(k, "") for k in _PK_FIELDS}


def resolve_drug(datastore: DataStore, name: str) -> Dict[str, Any]:
    """Exact-membership drug resolution — the core of the no-silent-substitution
    guarantee. Returns the dataset row if the name is an exact entry, otherwise
    a not-found marker. Never substitutes a pharmacokinetically-similar drug."""
    key = normalize_drug_name(name)
    row = datastore.drug_map.get(key)
    if row is None:
        return {"found": False, "_queried_as": name, "drug_name": key}
    return {"found": True, **row}


def organ_impairment_reasons(data: Dict[str, Any], renal: str, hepatic: str) -> List[str]:
    """PK reasons a drug may be affected by the given organ impairment. Pure
    function over one resolved drug row + the impairment levels."""
    reasons: List[str] = []
    if renal != "none":
        try:
            fe = float(data.get("fe", ""))
            if fe >= 0.3:
                reasons.append(
                    f"fe={fe:.2f} — high renal excretion; "
                    f"may accumulate with {renal} renal impairment"
                )
        except (ValueError, TypeError):
            pass
        if str(data.get("renal", "")).strip().upper() == "YES":
            reasons.append("marked as renally cleared in dataset")
    if hepatic != "none":
        enzymes = str(data.get("enzymes", "")).strip()
        if enzymes and enzymes.lower() not in ("", "none", "nan", "not specified pl"):
            reasons.append(
                f"metabolized by {enzymes}; "
                f"{hepatic} hepatic impairment may alter clearance"
            )
    return reasons


def make_agent(datastore: DataStore):
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    pinecone_index = make_pinecone_index()

    # ---------- node 1: retrieve drugs (exact membership) ----------
    def retrieve_drugs(state: DrugAnalysisState) -> dict:
        # Membership is an EXACT question and drug_map is the source of truth,
        # so resolve names against it directly. No semantic substitution: a name
        # that is not an exact dataset entry is reported not-found, never
        # silently replaced by a pharmacokinetically-"similar" drug (that
        # mapped nonsense like "asdfghjkl" onto real drugs).
        # ponytail: exact-only, matching /check. Typo tolerance via
        # difflib.get_close_matches(datastore.drug_names, cutoff~0.8) is a ready
        # fast-follow if false refusals on misspellings become a problem.
        return {"retrieved_drugs": {d: resolve_drug(datastore, d) for d in state["drugs"]}}

    # ---------- node 2: patient-context retrieval (the real RAG step) ----------
    def retrieve_context(state: DrugAnalysisState) -> dict:
        """
        Queries Pinecone using the *patient's clinical situation* as the semantic
        query — not just drug names. Finds drugs in the dataset that are most
        pharmacokinetically relevant to this patient's organ function profile.
        This is what a clinical pharmacist does mentally: understand the PK
        landscape around the patient's drugs before reasoning about risk.
        """
        renal = state["renal_impairment"]
        hepatic = state["hepatic_impairment"]
        drug_names = state["drugs"]

        queries: List[str] = []

        if renal != "none":
            queries.append(
                f"drug high fraction excreted unchanged urine renally cleared "
                f"renal impairment accumulation {renal}"
            )

        if hepatic != "none":
            queries.append(
                f"drug metabolized CYP enzyme hepatic first-pass clearance "
                f"liver impairment {hepatic}"
            )

        # Always add a query centered on the actual drug list + shared pathways
        if drug_names:
            queries.append(
                f"pharmacokinetic interaction enzyme transporter overlap "
                + " ".join(drug_names[:4])
            )

        seen = set(drug_names)
        context: Dict[str, Any] = {}

        for query in queries:
            vec = _embed(openai_client, query)
            results = pinecone_index.query(vector=vec, top_k=6, include_metadata=True)
            for match in results.matches:
                meta = match.metadata or {}
                name = meta.get("drug_name", "")
                if name and name not in seen and match.score > _CONTEXT_MIN_SCORE:
                    seen.add(name)
                    context[name] = {
                        **_pk_summary(meta),
                        "relevance_score": round(match.score, 3),
                        "retrieved_for": (
                            "renal_context" if "renal" in query
                            else "hepatic_context" if "hepatic" in query
                            else "pathway_context"
                        ),
                    }

        # Cap at 10 most relevant drugs
        ranked = sorted(context.values(), key=lambda x: -x["relevance_score"])[:10]
        return {"pk_context": ranked}

    # ---------- node 3: pairwise interactions ----------
    def check_interactions(state: DrugAnalysisState) -> dict:
        drugs = [normalize_drug_name(d) for d in state["drugs"]]
        interactions = [find_interaction(datastore, a, b) for a, b in unique_pairs(drugs)]
        return {"interactions": interactions}

    # ---------- node 4: organ impairment flags ----------
    def assess_organ_context(state: DrugAnalysisState) -> dict:
        renal = state["renal_impairment"]
        hepatic = state["hepatic_impairment"]
        flags = []

        for drug_name, data in state["retrieved_drugs"].items():
            if not data.get("found"):
                continue
            reasons = organ_impairment_reasons(data, renal, hepatic)
            if reasons:
                flags.append({"drug": drug_name, "reasons": reasons})

        return {"impairment_flags": flags}

    # ---------- node 5a: deep evidence (fires on moderate/high severity) ----------
    def deep_evidence(state: DrugAnalysisState) -> dict:
        significant = [
            it for it in state["interactions"]
            if it.get("severity") in ("moderate", "high")
        ]

        evidence_details = []
        for it in significant:
            pair = it.get("drug_pair", [])
            ev = it.get("evidence", {})

            enzymes = ev.get("shared_enzymes") or []
            transporters = ev.get("shared_transporters") or []
            pathway_query = (
                f"drug interaction via {', '.join(enzymes + transporters)}"
                if (enzymes or transporters)
                else f"interaction between {' and '.join(pair)}"
            )

            vec = _embed(openai_client, pathway_query)
            results = pinecone_index.query(vector=vec, top_k=5, include_metadata=True)

            related = []
            seen = set(pair)
            for match in results.matches:
                meta = match.metadata or {}
                name = meta.get("drug_name", "")
                if name and name not in seen and match.score > _DEEP_EVIDENCE_MIN_SCORE:
                    seen.add(name)
                    related.append({**_pk_summary(meta), "similarity": round(match.score, 3)})

            evidence_details.append({
                "pair": pair,
                "severity": it.get("severity"),
                "auc_change_pct": ev.get("delta_auc_pct", ""),
                "ref_pmid": ev.get("ref_ddi", ""),
                "direction": ev.get("direction", ""),
                "shared_enzymes": enzymes,
                "shared_transporters": transporters,
                "related_drugs_same_pathway": related[:4],
            })

        return {"deep_evidence": evidence_details}

    # ---------- node 5b: synthesize ----------
    def synthesize(state: DrugAnalysisState) -> dict:
        # Names that are not exact dataset entries — the LLM must flag these as
        # not analyzed, never substitute properties for them.
        not_found = [
            data.get("_queried_as", drug)
            for drug, data in state["retrieved_drugs"].items()
            if not data.get("found")
        ]

        payload = {
            "drugs": state["drugs"],
            "resolved_from": state.get("resolutions", []),
            "user_question": state.get("question", ""),
            "renal_impairment": state["renal_impairment"],
            "hepatic_impairment": state["hepatic_impairment"],
            "drug_profiles": {
                name: {k: v for k, v in data.items() if not k.startswith("_") and k != "score"}
                for name, data in state["retrieved_drugs"].items()
            },
            "pharmacokinetic_context": state.get("pk_context", []),
            "pairwise_interactions": state["interactions"],
            "organ_impairment_flags": state["impairment_flags"],
            "deep_evidence": state.get("deep_evidence", []),
            "drugs_not_in_dataset": not_found,
        }

        system = (
            "You are a strict summarizer for a drug interaction and organ impairment "
            "analysis tool used by clinicians.\n"
            "ABSOLUTE RULES:\n"
            "- Use ONLY the data in the provided JSON. Do NOT add external clinical facts.\n"
            "- Do NOT provide dosing guidance, management plans, or recommendations.\n"
            "- Do NOT state any drug is 'safe' or 'unsafe'.\n"
            "- pharmacokinetic_context contains drugs retrieved from a knowledge base that "
            "share PK properties relevant to this patient's organ function — use this to "
            "add nuance about the PK landscape (e.g. 'other renally cleared drugs like X "
            "share this risk profile'), but do not invent interactions.\n"
            "- If drugs_not_in_dataset is non-empty, state clearly that those drugs are "
            "NOT in the dataset and were not analyzed; do NOT substitute, guess, or infer "
            "their properties from other drugs.\n"
            "- If resolved_from is non-empty, note that the named input was interpreted as "
            "its dataset drug (e.g. a brand name mapped to its generic via RxNorm).\n"
            "- If deep_evidence is present, reference the AUC change for quantitative context.\n"
            "- A pairwise_interaction may include a `ddinter` block — an independent, "
            "curated clinical source (DDInter 2.0) with a severity Level. When it is listed, "
            "cite that clinical severity alongside the dataset's own PK evidence.\n"
            "- If data is missing, say 'insufficient data in dataset'.\n"
            "- If user_question is present, address it directly in the summary — "
            "but the ABSOLUTE RULES above still apply without exception (no dosing, "
            "no safe/unsafe verdict, no recommendation, dataset facts only).\n\n"
            "OUTPUT FORMAT — return JSON only:\n"
            '{"summary": "2-4 sentence clinical narrative.", '
            '"key_flags": ["concern 1", "concern 2", ...]}\n'
            "key_flags: up to 5 items, most critical first.\n"
            "End summary with: 'Not medical advice; confirm with a clinician/pharmacist.'"
        )

        resp = openai_client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload)},
            ],
        )

        try:
            out = json.loads(resp.choices[0].message.content)
            synthesis = str(out.get("summary", "")).strip()
            key_flags = out.get("key_flags", [])
        except Exception:
            synthesis = "Failed to generate synthesis."
            key_flags = []

        return {"synthesis": synthesis, "key_flags": key_flags}

    # ---------- routing ----------
    def route_after_organ(state: DrugAnalysisState) -> str:
        severities = {it.get("severity") for it in state["interactions"]}
        if severities & {"moderate", "high"}:
            return "deep_evidence"
        return "synthesize"

    # ---------- graph ----------
    graph = StateGraph(DrugAnalysisState)
    graph.add_node("retrieve_drugs", retrieve_drugs)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("check_interactions", check_interactions)
    graph.add_node("assess_organ_context", assess_organ_context)
    graph.add_node("deep_evidence", deep_evidence)
    graph.add_node("synthesize", synthesize)

    graph.add_edge(START, "retrieve_drugs")
    graph.add_edge("retrieve_drugs", "retrieve_context")      # PK context after name lookup
    graph.add_edge("retrieve_context", "check_interactions")
    graph.add_edge("check_interactions", "assess_organ_context")
    graph.add_conditional_edges(
        "assess_organ_context",
        route_after_organ,
        {"deep_evidence": "deep_evidence", "synthesize": "synthesize"},
    )
    graph.add_edge("deep_evidence", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()
