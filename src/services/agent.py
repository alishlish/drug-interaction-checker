from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from openai import OpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .data import DataStore, normalize_drug_name
from .interactions import find_interaction
from .vector_store import make_pinecone_index, query_drug, _embed


class DrugAnalysisState(TypedDict):
    drugs: List[str]
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


def _pk_summary(meta: dict) -> dict:
    return {k: meta.get(k, "") for k in _PK_FIELDS}


def make_agent(datastore: DataStore):
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    pinecone_index = make_pinecone_index()

    # ---------- node 1: retrieve drugs (with semantic fallback) ----------
    def retrieve_drugs(state: DrugAnalysisState) -> dict:
        retrieved = {}
        for drug in state["drugs"]:
            result = query_drug(pinecone_index, openai_client, drug)

            # Semantic fallback: low-confidence name match → search by PK description
            if not result.get("found") or result.get("score", 1.0) < 0.78:
                fb_query = f"drug pharmacokinetics similar to {drug} renal hepatic enzyme metabolism"
                vec = _embed(openai_client, fb_query)
                fb = pinecone_index.query(vector=vec, top_k=1, include_metadata=True)
                if fb.matches:
                    m = fb.matches[0]
                    meta = m.metadata or {}
                    result = {
                        "found": True,
                        "_approximate": True,
                        "_queried_as": drug,
                        "score": round(m.score, 3),
                        **meta,
                    }

            retrieved[drug] = result
        return {"retrieved_drugs": retrieved}

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
                if name and name not in seen and match.score > 0.55:
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
        interactions = []
        for i in range(len(drugs)):
            for j in range(i + 1, len(drugs)):
                interactions.append(find_interaction(datastore, drugs[i], drugs[j]))
        return {"interactions": interactions}

    # ---------- node 4: organ impairment flags ----------
    def assess_organ_context(state: DrugAnalysisState) -> dict:
        renal = state["renal_impairment"]
        hepatic = state["hepatic_impairment"]
        flags = []

        for drug_name, data in state["retrieved_drugs"].items():
            if not data.get("found"):
                continue

            reasons = []

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

            if reasons:
                flags.append({
                    "drug": drug_name,
                    "approximate_match": data.get("_approximate", False),
                    "reasons": reasons,
                })

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
                if name and name not in seen and match.score > 0.75:
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
        # Flag any approximate matches so the LLM can mention them
        approximate = [
            f"{data.get('_queried_as', drug)} → closest match: {data.get('drug_name', '?')}"
            for drug, data in state["retrieved_drugs"].items()
            if data.get("_approximate")
        ]

        payload = {
            "drugs": state["drugs"],
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
            "approximate_matches": approximate,
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
            "- If approximate_matches is non-empty, note that those drugs were not found "
            "exactly and results are based on the closest pharmacokinetic match.\n"
            "- If deep_evidence is present, reference the AUC change for quantitative context.\n"
            "- If data is missing, say 'insufficient data in dataset'.\n\n"
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
