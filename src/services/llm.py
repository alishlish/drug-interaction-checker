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


def explain(
    client: Optional["OpenAI"],
    interaction: Dict[str, Any],
    drug1: Dict[str, Any],
    drug2: Dict[str, Any],
    model: str,
) -> str:
    if client is None:
        return "LLM not configured (missing OPENAI_API_KEY)."

    # Skip explanation when there's nothing interesting (saves money + avoids weirdness)
    if interaction.get("severity") == "none":
        return (
            "No significant interaction was found based on the dataset fields for enzymes/transporters. "
            "Not medical advice; confirm with a clinician/pharmacist."
        )

    payload = {
        "drug1": drug1,
        "drug2": drug2,
        "interaction_result": interaction,
        "rules": {
            "use_only_provided_json": True,
            "no_external_medical_facts": True,
            "no_dosing": True,
            "no_outcomes_or_predictions": True,
            "no_recommendations": True,
        },
    }

    system = (
        "You are a cautious explainer for a drug checker.\n"
        "Use ONLY the JSON provided (dataset fields + deterministic interaction + evidence).\n"
        "Do NOT add external facts, clinical outcomes, dosing, or recommendations.\n"
        "If information is missing, say so.\n"
        "Output JSON only: {\"explanation\":\"...\"}\n"
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
        txt = (data.get("explanation") or "").strip()
        return txt or "No explanation returned."
    except Exception:
        return "Failed to parse LLM response safely."
