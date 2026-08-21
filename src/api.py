from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .ui import mount_ui
from .models import DrugListRequest, ExplainRequest, AnalyzeRequest
from .services.data import load_datastore, normalize_drug_name, get_drug, search_drugs
from .services.interactions import find_interaction, unique_pairs
from .services.identity import resolve_to_dataset
from .services.llm import make_client, explain
from .services.agent import make_agent


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "..", "data", "processed", "drug_interactions_clean.csv")
DATA_PATH = os.getenv("DRUG_DATA_PATH", DEFAULT_DATA_PATH)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")

cors_origins_env = os.getenv("CORS_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if cors_origins_env.strip() == "*" else [
    o.strip() for o in cors_origins_env.split(",") if o.strip()
]

datastore = load_datastore(DATA_PATH)
llm_client = make_client(OPENAI_API_KEY)

# The agent needs OpenAI + Pinecone at construction, so build it lazily on the
# first /analyze call. This lets the app boot (and /check, /drugs work) without
# those keys — needed for local dev, CI, and the deterministic endpoints.
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = make_agent(datastore)
    return _agent

app = FastAPI(title="Drug Interaction Checker API", version="1.0.0")
mount_ui(app, BASE_DIR)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Drug Interaction Checker API is running", "ui": "/ui", "docs": "/docs"}


@app.get("/health")
def health():
    return {
        "ok": True,
        "total_drugs": len(datastore.drug_map),
        "llm_enabled": bool(llm_client),
        "model": LLM_MODEL,
        "data_path": datastore.data_path,
        "attribute_cols": datastore.attribute_cols,
    }


@app.get("/drugs")
def drugs(search: str = ""):
    return {"matches": search_drugs(datastore, search, limit=50)}


@app.get("/drug/{drug_name}")
def drug_info(drug_name: str):
    info = get_drug(datastore, drug_name)
    if info["found"]:
        return info

    # Not an exact dataset entry — try RxNorm (brands/synonyms/spellings).
    res = resolve_to_dataset(datastore, drug_name)
    if res.found:
        info = get_drug(datastore, res.drug_name)
        info["resolved_from"] = {
            "input": res.input, "via": res.via,
            "rxcui": res.rxcui, "rxnorm_name": res.rxnorm_name,
        }
        return info

    detail = f"{drug_name} not found in the dataset"
    if res.suggestion:
        detail += f". Did you mean '{res.suggestion}'?"
    raise HTTPException(status_code=404, detail=detail)


@app.post("/check")
def check(req: DrugListRequest):
    if len(req.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs")

    drugs = [normalize_drug_name(d) for d in req.drugs if d and d.strip()]
    if len(drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 non-empty drug names")

    results = [find_interaction(datastore, a, b) for a, b in unique_pairs(drugs)]

    return {"interactions": results}


@app.post("/check/explain")
def check_explain(req: ExplainRequest):
    if len(req.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs")

    drugs = [normalize_drug_name(d) for d in req.drugs if d and d.strip()]
    if len(drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 non-empty drug names")

    results = []
    for d1, d2 in unique_pairs(drugs):
        inter = find_interaction(datastore, d1, d2)
        drug1 = get_drug(datastore, d1)
        drug2 = get_drug(datastore, d2)
        inter["llm_explanation"] = explain(
            llm_client, inter, drug1, drug2, model=LLM_MODEL
        )
        results.append(inter)

    return {"interactions": results}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.drugs:
        raise HTTPException(status_code=400, detail="Need at least 1 drug")

    drugs = [normalize_drug_name(d) for d in req.drugs if d and d.strip()]
    if not drugs:
        raise HTTPException(status_code=400, detail="Need at least 1 non-empty drug name")

    if not OPENAI_API_KEY or not os.getenv("PINECONE_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="Agent not configured (needs OPENAI_API_KEY and PINECONE_API_KEY)",
        )

    # Resolve brands/synonyms to dataset drugs before the agent runs, so the
    # whole pipeline operates on dataset drugs. Only confident (exact-tier)
    # RxNorm hits resolve; unresolved names pass through and are flagged.
    resolutions = []
    resolved_drugs = []
    for d in drugs:
        r = resolve_to_dataset(datastore, d)
        resolved_drugs.append(r.drug_name if r.found else r.input)
        if r.found and r.via == "rxnorm":
            resolutions.append({
                "from": r.input, "to": r.drug_name,
                "rxcui": r.rxcui, "rxnorm_name": r.rxnorm_name,
            })

    result = get_agent().invoke({
        "drugs": resolved_drugs,
        "resolutions": resolutions,
        "renal_impairment": req.renal_impairment,
        "hepatic_impairment": req.hepatic_impairment,
        "question": req.question,
        "retrieved_drugs": {},
        "pk_context": [],
        "interactions": [],
        "impairment_flags": [],
        "deep_evidence": [],
        "key_flags": [],
        "synthesis": "",
    })

    return {
        "drugs": result["drugs"],
        "resolutions": resolutions,
        "interactions": result["interactions"],
        "impairment_flags": result["impairment_flags"],
        "deep_evidence": result.get("deep_evidence", []),
        "key_flags": result["key_flags"],
        "synthesis": result["synthesis"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
