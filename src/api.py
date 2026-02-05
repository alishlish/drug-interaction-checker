from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .ui import mount_ui
from .models import DrugListRequest, ExplainRequest
from .services.data import load_datastore, normalize_drug_name, get_drug, search_drugs
from .services.interactions import find_interaction
from .services.llm import make_client, explain


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
    if not info["found"]:
        raise HTTPException(status_code=404, detail=f"{drug_name} not found in the dataset")
    return info


@app.post("/check")
def check(req: DrugListRequest):
    if len(req.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs")

    drugs = [normalize_drug_name(d) for d in req.drugs if d and d.strip()]
    if len(drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 non-empty drug names")

    results = []
    for i in range(len(drugs)):
        for j in range(i + 1, len(drugs)):
            results.append(find_interaction(datastore, drugs[i], drugs[j]))

    return {"interactions": results}


@app.post("/check/explain")
def check_explain(req: ExplainRequest):
    if len(req.drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 drugs")

    drugs = [normalize_drug_name(d) for d in req.drugs if d and d.strip()]
    if len(drugs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 non-empty drug names")

    results = []
    for i in range(len(drugs)):
        for j in range(i + 1, len(drugs)):
            d1, d2 = drugs[i], drugs[j]
            inter = find_interaction(datastore, d1, d2)

            drug1 = get_drug(datastore, d1)
            drug2 = get_drug(datastore, d2)

            inter["llm_explanation"] = explain(
                llm_client, inter, drug1, drug2, model=LLM_MODEL
            )
            results.append(inter)

    return {"interactions": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
