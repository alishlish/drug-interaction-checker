from __future__ import annotations

import os
from typing import Any, Dict, List

from openai import OpenAI
from pinecone import Pinecone

EMBED_MODEL = "text-embedding-3-small"


def make_pinecone_index():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return pc.Index(os.getenv("PINECONE_INDEX_NAME", "drug-interactions"))


def _embed(client: OpenAI, text: str) -> List[float]:  # exported for agent use
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    return resp.data[0].embedding


def query_drug(index, openai_client: OpenAI, drug_name: str) -> Dict[str, Any]:
    vec = _embed(openai_client, f"Drug: {drug_name}")
    result = index.query(vector=vec, top_k=1, include_metadata=True)

    if not result.matches:
        return {"found": False, "drug_name": drug_name}

    match = result.matches[0]
    meta = match.metadata or {}
    return {"found": True, "score": match.score, **meta}
