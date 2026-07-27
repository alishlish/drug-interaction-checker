from __future__ import annotations

import os
from typing import List

from openai import OpenAI
from pinecone import Pinecone

EMBED_MODEL = "text-embedding-3-small"


def make_pinecone_index():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return pc.Index(os.getenv("PINECONE_INDEX_NAME", "drug-interactions"))


def _embed(client: OpenAI, text: str) -> List[float]:  # exported for agent use
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    return resp.data[0].embedding
