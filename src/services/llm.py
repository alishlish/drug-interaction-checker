from __future__ import annotations

import json
from typing import Dict, Any, Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


def make_client(api_key: str) -> Optional["OpenAI"]:
    api_key = (api_key or "").strip()
    if not api_key or OpenAI is None:
        return None
    return OpenAI(api_key=api_key)


def explain_interaction(
    client: Optional["OpenAI"],
    interaction: Dict[str, Any],
    drug1: Dict[str, Any],
    drug2: Dict[str, Any],
    model: str = "gpt-4.1-mini",
) -> str:
    """
    Safe GenAI: explain deterministic result using ONLY provided structured JSON.
    """
    if client is None:
        return "LLM not configured (missing OPENAI_API_KEY)."

    # Skip LLM for "none" to save money and avoid awkward outputs.
    if interaction.get("severity") in ("none", "unknown") and "No significant" in (interaction.get("interaction") or ""):
        return (
            "No significant interaction was found based on the dataset fields for enzymes/transporters. "
            "Not medical advice; confirm with a clinician/pharmacist."
        )

    payload = {
        "drug1": drug1,
        "drug2": drug2,
        "interaction_result": interaction,
        "constraints": {
            "use_only_provided_data": True,
            "do_not_add_external_facts": True,
            "do_not_give_dosing": True,
            "do_not_claim_clinical_outcomes": True,
            "do_not_assert_safety": True,
        },
    }

    system = (
        "You are a cautious medical-data explainer.\n"
        "Use ONLY the JSON provided.\n"
        "Do NOT add external facts, outcomes, dosing instructions, or recommendations.\n"
        "If mechanism is unclear or data missing, say 'insufficient data'.\n"
        "Output JSON only: {\"explanation\": \"...\"}\n"
        "End with: 'Not medical advice; confirm with a clinician/pharmacist.'"
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

    try:
        data = json.loads(resp.choices[0].message.content)
        explanation = (data.get("explanation") or "").strip()
        return explanation or "No explanation returned."
    except Exception:
        return "Failed to parse LLM response safely."
