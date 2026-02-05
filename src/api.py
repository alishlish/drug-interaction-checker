# api.py
from dotenv import load_dotenv
load_dotenv()
import os
import json
from typing import List, Optional, Dict, Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel

# Optional GenAI (safe "explain" only)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

# ----------------------------
# Config
# ----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Prefer env var for deploy; fallback to your existing relative path
DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "..", "data", "processed", "drug_interactions_simple.csv")
DATA_PATH = os.getenv("DRUG_DATA_PATH", DEFAULT_DATA_PATH)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

# CORS: set CORS_ORIGINS="http://localhost:3000,https://your-frontend.com"
cors_origins_env = os.getenv("CORS_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if cors_origins_env.strip() == "*" else [o.strip() for o in cors_origins_env.split(",") if o.strip()]

# Canonical transporters (normalized matching)
TRANSPORTERS = ["P-GP", "BCRP", "OATP", "OAT", "OCT", "MATE"]


def _norm_text(s: Optional[str]) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    # normalize hyphens/dashes and case
    return (
        str(s)
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )


def _norm_upper(s: Optional[str]) -> str:
    return _norm_text(s).upper()


# ----------------------------
# Load data once at startup
# ----------------------------
if not os.path.exists(DATA_PATH):
    raise RuntimeError(
        f"Could not find drug interaction CSV at {DATA_PATH}. "
        f"Set DRUG_DATA_PATH env var or ensure the file exists."
    )

df = pd.read_csv(DATA_PATH)

if "drug_name" not in df.columns:
    raise RuntimeError(f"CSV missing required column 'drug_name'. Found columns: {list(df.columns)}")

# Normalize drug names to lowercase for consistent lookup
df["drug_name"] = df["drug_name"].astype(str).str.lower().str.strip()

# Build a fast lookup map: drug_name -> {enzymes, transporters}
drug_map: Dict[str, Dict[str, str]] = {}
for _, row in df.iterrows():
    name = str(row["drug_name"]).lower().strip()
    enzymes = _norm_text(row["enzymes"]) if "enzymes" in df.columns else ""
    transporters = _norm_text(row["transporters"]) if "transporters" in df.columns else ""
    drug_map[name] = {"enzymes": enzymes, "transporters": transporters}


# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI(title="Drug Interaction Checker API", version="0.2.0")

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@app.get("/ui", response_class=HTMLResponse)
def ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------
# Request models
# ----------------------------
class DrugListRequest(BaseModel):
    drugs: List[str]


class ExplainRequest(BaseModel):
    drugs: List[str]


# ----------------------------
# Helpers
# ----------------------------
def get_drug(drug_name: str) -> Dict[str, Any]:
    key = drug_name.lower().strip()
    row = drug_map.get(key)
    if not row:
        return {"name": key, "enzymes": None, "transporters": None, "found": False}
    enzymes = row.get("enzymes", "").strip() or None
    transporters = row.get("transporters", "").strip() or None
    return {"name": key, "enzymes": enzymes, "transporters": transporters, "found": True}


def find_interaction(drug1: str, drug2: str) -> Dict[str, Any]:
    """
    Deterministic rule-based interaction: flags overlap in CYP enzymes / transporters.
    Severity is a simple heuristic (you can refine later).
    """
    d1 = drug_map.get(drug1)
    d2 = drug_map.get(drug2)

    if not d1 or not d2:
        return {"drug_pair": [drug1, drug2], "interaction": "Drug not found"}

    e1 = _norm_upper(d1.get("enzymes", ""))
    e2 = _norm_upper(d2.get("enzymes", ""))
    t1 = _norm_upper(d1.get("transporters", ""))
    t2 = _norm_upper(d2.get("transporters", ""))

    # Shared CYP enzymes
    shared_cyps = []
    if e1 and e2:
        shared_cyps = [enzyme for enzyme in e1.split(" | ") if enzyme and enzyme in e2]

    # Shared transporters (canonical list)
    shared_transporters = [t for t in TRANSPORTERS if t1 and t2 and (t in t1) and (t in t2)]

    interaction = "No significant interaction found"
    severity = "none"

    if shared_cyps:
        interaction = f"Potential interaction due to shared CYP enzymes: {', '.join(shared_cyps)}"
        # Simple severity heuristic
        if len(shared_cyps) > 1:
            severity = "moderate"
        else:
            severity = "mild"

    # Transporter overlap can bump severity if something already flagged, or stand alone
    if shared_transporters and interaction == "No significant interaction found":
        interaction = f"Potential interaction due to shared transporters: {', '.join(shared_transporters)}"
        severity = "mild"
    elif shared_transporters and interaction != "No significant interaction found":
        interaction += f" and shared transporters: {', '.join(shared_transporters)}"
        if severity == "mild":
            severity = "moderate"

    return {
        "drug_pair": [drug1, drug2],
        "interaction": interaction,
        "severity": severity,
    }


def llm_explain(interaction: Dict[str, Any], drug1: Dict[str, Any], drug2: Dict[str, Any]) -> str:
    """
    Safe GenAI: only explains the deterministic result and the provided structured fields.
    No external medical claims.
    """
    if client is None:
        return "LLM not configured (missing OPENAI_API_KEY)."

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
        "Do NOT add external facts, outcomes, or dosing instructions.\n"
        "If mechanism is unclear or data missing, say 'insufficient data'.\n"
        "Output JSON only: {\"explanation\": \"...\"}\n"
        "End the explanation with: 'Not medical advice; confirm with a clinician/pharmacist.'"
    )

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
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


# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def root():
    return {"message": "Drug Interaction Checker API is running"}


@app.get("/health")
def health():
    return {"ok": True, "total_drugs": len(drug_map)}


@app.get("/drugs")
def search_drugs(search: str = ""):
    search = search.lower().strip()
    if not search:
        return {"matches": []}
    matches = [name for name in drug_map.keys() if search in name]
    return {"matches": matches[:50]}


@app.get("/drug/{drug_name}")
def get_drug_info(drug_name: str):
    info = get_drug(drug_name)
    if not info["found"]:
        raise HTTPException(status_code=404, detail=f"{drug_name} not found in the dataset")
    return info


@app.post("/check")
def check_interactions(request: DrugListRequest):
    if len(request.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs to check interactions")

    drugs = [d.lower().strip() for d in request.drugs]
    results = []

    for i in range(len(drugs)):
        for j in range(i + 1, len(drugs)):
            results.append(find_interaction(drugs[i], drugs[j]))

    return {"interactions": results}


@app.post("/check/explain")
def check_interactions_explain(request: ExplainRequest):
    if len(request.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs to check interactions")

    drugs = [d.lower().strip() for d in request.drugs]
    results = []

    for i in range(len(drugs)):
        for j in range(i + 1, len(drugs)):
            d1 = drugs[i]
            d2 = drugs[j]
            interaction = find_interaction(d1, d2)

            # Look up structured data for LLM context
            drug1 = get_drug(d1)
            drug2 = get_drug(d2)

            interaction["llm_explanation"] = llm_explain(interaction, drug1, drug2)
            results.append(interaction)

    return {"interactions": results}


# Local run
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
