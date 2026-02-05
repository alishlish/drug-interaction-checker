from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import DrugListRequest, ExplainRequest
from .ui import mount_ui
from .services.data import load_datastore, normalize_drug_name, get_drug, search_drugs
from .services.interactions import find_interaction
from .services.llm import make_client, explain_interaction


# ----------------------------
# Config
# ----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "..", "data", "processed", "drug_interactions_simple.csv")
DATA_PATH = os.getenv("DRUG_DATA_PATH", DEFAULT_DATA_PATH)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")

cors_origins_env = os.getenv("CORS_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if cors_origins_env.strip() == "*" else [
    o.strip() for o in cors_origins_env.split(",") if o.strip()
]


# ----------------------------
# Startup: load datastore + LLM client once
# ----------------------------
datastore = load_datastore(DATA_PATH)
llm_client = make_client(OPENAI_API_KEY)


# ----------------------------
# App
# ----------------------------
app = FastAPI(title="Drug Interaction Checker API", version="1.0.0")

mount_ui(app, BASE_DIR)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def root():
    return {"message": "Drug Interaction Checker API is running"}


@app.get("/health")
def health():
    return {
        "ok": True,
        "total_drugs": len(datastore.drug_map),
        "llm_enabled": bool(llm_client),
        "data_path": datastore.data_path,
        "model": LLM_MODEL,
    }


@app.get("/drugs")
def drugs(search: str = ""):
    return {"matches": search_drugs(datastore, search, limit=50)}


@app.get("/drug/{drug_name}")
def drug_info(drug_name: str):
    info = get_drug(datastore, drug_name)
    if not info["found"]:
        raise HTTPException(status_code=404, detail=f"{drug_name} not found in the dataset")
    return info


@app.post("/check")
def check(request: DrugListRequest):
    if len(request.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs to check interactions")

    drugs = [normalize_drug_name(d) for d in request.drugs if d and d.strip()]
    if len(drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 non-empty drug names")

    results = []
    for i in range(len(drugs)):
        for j in range(i + 1, len(drugs)):
            results.append(find_interaction(datastore, drugs[i], drugs[j]))
    return {"interactions": results}


@app.post("/check/explain")
def check_explain(request: ExplainRequest):
    if len(request.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs to check interactions")

    drugs = [normalize_drug_name(d) for d in request.drugs if d and d.strip()]
    if len(drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 non-empty drug names")

    results = []
    for i in range(len(drugs)):
        for j in range(i + 1, len(drugs)):
            d1, d2 = drugs[i], drugs[j]
            interaction = find_interaction(datastore, d1, d2)

            drug1 = get_drug(datastore, d1)
            drug2 = get_drug(datastore, d2)

            interaction["llm_explanation"] = explain_interaction(
                llm_client, interaction, drug1, drug2, model=LLM_MODEL
            )
            results.append(interaction)

    return {"interactions": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
