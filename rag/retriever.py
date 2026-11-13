"""Гибридный поиск: BM25 + косинус по эмбеддингам, объединение через RRF."""
import json
import os
import re
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from .ingest import EMBED_MODEL

DATA = Path(os.getenv("DATA_DIR", "data"))
MIN_COSINE = float(os.getenv("MIN_COSINE", "0.45"))  # порог «в базе нет», подбираем на eval


STOPWORDS = {"как", "что", "для", "это", "или", "при", "про", "чем", "где", "когда",
             "какой", "какая", "какие", "можно", "нужно", "мне", "помогите", "будет"}

def tokenize(text: str) -> list[str]:
    return [w[:5] for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS]


class Retriever:
    def __init__(self):
        self.chunks = [json.loads(l) for l in open(DATA / "chunks.jsonl", encoding="utf-8")]
        self.emb = np.load(DATA / "embeddings.npy")
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks])
        self.model = TextEmbedding(EMBED_MODEL)

    def search(self, query: str, k: int = 5, types: set[str] | None = None) -> list[dict]:
        qv = np.array(next(iter(self.model.embed([query]))), dtype="float32")
        qv /= np.linalg.norm(qv) + 1e-9
        cos = self.emb @ qv
        bm = self.bm25.get_scores(tokenize(query))

        rrf = np.zeros(len(self.chunks))
        for scores in (cos, bm):
            for rank, idx in enumerate(np.argsort(-scores)[:50]):
                rrf[idx] += 1.0 / (60 + rank)

        hits = []
        for idx in np.argsort(-rrf):
            c = self.chunks[idx]
            if types and c["type"] not in types:
                continue
            hits.append({**c, "cosine": float(cos[idx]), "bm25": float(bm[idx]), "rrf": float(rrf[idx])})
            if len(hits) == k:
                break
        return hits

    def is_confident(self, hits: list[dict]) -> bool:
        return bool(hits) and max(h["cosine"] for h in hits) >= MIN_COSINE