# src/services/llm.py
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

# Optional dependency (project should run without LLM)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


# ----------------------------
# Client factory
# ----------------------------
def make_client(OPEN_AI_KEY) -> Optional[Any]:
    """
    Create an OpenAI client if OPENAI_API_KEY is set and SDK is available.
    Returns None if not configured.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return None
    return OpenAI(api_key=api_key)


# ----------------------------
# Safety filters (conservative)
# ----------------------------
_BANNED_PATTERNS = [
    r"\b(dose|dosage|mg|mcg|g|ml)\b",
    r"\b(take|start|stop|increase|decrease|titrate|adjust)\b",
    r"\b(recommend|should|must|avoid|contraindicated)\b",
    r"\b(pregnan|breastfeed|lactat)\b",
    r"\b(call (a )?(doctor|physician)|seek medical|emergency)\b",
    r"\b(safe|unsafe|dangerous|fatal|death)\b",
    r"\b(risk of|causes|leads to|results in)\b",  # outcome-y
]

_BANNED_RE = re.compile("|".join(_BANNED_PATTERNS), re.IGNORECASE)


def _looks_like_medical_advice(text: str) -> bool:
    if not text:
        return False
    return bool(_BANNED_RE.search(text))


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()


def _must_end_disclaimer(text: str) -> str:
    ending = "Not medical advice; confirm with a clinician/pharmacist."
    if not text.endswith(ending):
        text = text.rstrip(". ").strip() + ". " + ending
    return text


def _allowed_evidence_type(ev_type: str) -> bool:
    return ev_type in {"reference_ddi", "mechanism_overlap"}


# ----------------------------
# Explain (summarize only)
# ----------------------------
def explain(
    client: Optional[Any],
    interaction: Dict[str, Any],
    drug1: Dict[str, Any],
    drug2: Dict[str, Any],
    model: str = "gpt-4.1-mini",
    style: str = "plain",  # "plain" | "clinical"
) -> str:
    """
    GenAI is used ONLY as a summarizer of our deterministic result + evidence.
    It must not add new claims, outcomes, dosing, or recommendations.

    - Only runs when evidence.type is reference_ddi or mechanism_overlap
    - Uses JSON-only responses
    - Post-filters potentially advisory content
    """
    if client is None:
        return "LLM not configured (missing OPENAI_API_KEY)."

    evidence = interaction.get("evidence") or {}
    ev_type = _safe_str(evidence.get("type"))

    # Don’t invite the model to "invent" explanations when we have no evidence
    if not _allowed_evidence_type(ev_type):
        return "No explainable dataset evidence for this pair."

    payload = {
        "drug_pair": interaction.get("drug_pair"),
        "severity": interaction.get("severity"),
        "interaction_message": interaction.get("interaction"),
        "evidence": evidence,
        # only pass structured fields; keep it audit-friendly
        "drug1": {
            "name": drug1.get("name"),
            "found": drug1.get("found"),
            "enzymes": drug1.get("enzymes"),
            "transporters": drug1.get("transporters"),
            "attributes": drug1.get("attributes"),
        },
        "drug2": {
            "name": drug2.get("name"),
            "found": drug2.get("found"),
            "enzymes": drug2.get("enzymes"),
            "transporters": drug2.get("transporters"),
            "attributes": drug2.get("attributes"),
        },
        "style": style,
    }

    system = (
        "You are a strict summarizer for a drug interaction dataset UI.\n"
        "ABSOLUTE RULES:\n"
        "- Use ONLY the JSON the user provides. Do NOT add external facts.\n"
        "- Do NOT infer outcomes, safety, or risk. Do NOT provide recommendations.\n"
        "- Do NOT provide dosing or management guidance.\n"
        "- Only restate what is explicitly present in: interaction_message + evidence + attributes.\n"
        "- If something is missing, say 'insufficient data in dataset'.\n\n"
        "OUTPUT FORMAT:\n"
        "Return JSON only: {\"explanation\": \"...\"}\n"
        "End the explanation with: 'Not medical advice; confirm with a clinician/pharmacist.'\n\n"
        "STYLE:\n"
        "If style == 'clinical', write in concise clinical documentation tone.\n"
        "If style == 'plain', write in clear plain-English tone."
    )

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )

    # Parse and post-check
    try:
        data = json.loads(resp.choices[0].message.content)
        explanation = _safe_str(data.get("explanation"))
    except Exception:
        return "Failed to parse LLM response safely."

    if not explanation:
        return "No explanation returned."

    # Safety post-filter: if the model tried to "advise", block it.
    if _looks_like_medical_advice(explanation):
        return _must_end_disclaimer(
            "Explanation blocked: output resembled medical advice or unsupported clinical claims."
        )

    return _must_end_disclaimer(explanation)
