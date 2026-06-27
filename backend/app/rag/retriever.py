"""
Hybrid retriever over the protocol corpus.

- BM25 (keyword) is ALWAYS available — the app retrieves even if neural deps
  or model weights are missing.
- Dense (sentence-transformers + FAISS) is best-effort; if available the scores
  are fused with BM25 for hybrid retrieval.
- A dedicated danger-sign sub-index (is_danger_sign=True) backs the parallel
  safety-net node.

No medical content is hardcoded here — everything comes from the corpus chunks.
"""
from __future__ import annotations

import re
import threading
from typing import Optional

import numpy as np

from app.config import (
    EMBED_MODEL,
    USE_DENSE,
    RETRIEVAL_TOP_K,
    DANGER_TOP_K,
)
from app.rag.ingest import Chunk, load_chunks, corpus_fingerprint

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _minmax(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    lo, hi = float(scores.min()), float(scores.max())
    if hi - lo < 1e-9:
        return np.zeros_like(scores)
    return (scores - lo) / (hi - lo)


class Retriever:
    """Loaded once at startup, queried by the graph nodes."""

    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.fingerprint: str = ""
        self._bm25 = None
        self._dense_model = None
        self._embeddings: Optional[np.ndarray] = None
        self.dense_enabled = False
        self._lock = threading.Lock()

    # --- build ---
    def build(self) -> "Retriever":
        from rank_bm25 import BM25Okapi

        self.chunks = load_chunks()
        if not self.chunks:
            raise RuntimeError(
                "No corpus chunks found. Add protocol files to the corpus dir."
            )
        self.fingerprint = corpus_fingerprint(self.chunks)
        self._bm25 = BM25Okapi([_tok(c.text + " " + c.section + " " + c.condition)
                                for c in self.chunks])
        if USE_DENSE:
            self._try_build_dense()
        return self

    def _try_build_dense(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:  # torch / model not available -> BM25 only
            print(f"[retriever] dense retrieval disabled ({e.__class__.__name__}); using BM25 only")
            return
        try:
            self._dense_model = SentenceTransformer(EMBED_MODEL)
            embs = self._dense_model.encode(
                [c.text for c in self.chunks],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            self._embeddings = np.asarray(embs, dtype=np.float32)
            self.dense_enabled = True
            print(f"[retriever] dense retrieval enabled ({EMBED_MODEL})")
        except Exception as e:
            print(f"[retriever] dense build failed ({e}); using BM25 only")
            self._dense_model = None
            self._embeddings = None

    # --- query ---
    def _dense_scores(self, query: str) -> Optional[np.ndarray]:
        if not self.dense_enabled or self._dense_model is None:
            return None
        q = self._dense_model.encode([query], normalize_embeddings=True)
        return (self._embeddings @ np.asarray(q, dtype=np.float32).T).ravel()

    def _bm25_scores(self, query: str) -> np.ndarray:
        return np.asarray(self._bm25.get_scores(_tok(query)), dtype=np.float32)

    def _filter_idx(self, age_group: Optional[str], danger_only: bool) -> list[int]:
        idx = []
        for i, c in enumerate(self.chunks):
            if danger_only and not c.is_danger_sign:
                continue
            if age_group and age_group not in (c.age_group, "general"):
                # keep age-matched + general; everything else filtered out
                continue
            idx.append(i)
        return idx

    def search(
        self,
        query: str,
        age_group: Optional[str] = None,
        k: int = RETRIEVAL_TOP_K,
        danger_only: bool = False,
    ) -> list[dict]:
        with self._lock:
            candidates = self._filter_idx(age_group, danger_only)
            if not candidates:
                # age filter too strict -> fall back to no filter
                candidates = self._filter_idx(None, danger_only)
            if not candidates:
                return []

            bm = self._bm25_scores(query)
            fused = _minmax(bm[candidates])
            dense = self._dense_scores(query)
            if dense is not None:
                fused = 0.5 * fused + 0.5 * _minmax(dense[candidates])

            order = np.argsort(-fused)[:k]
            results = []
            for rank, j in enumerate(order):
                ci = candidates[int(j)]
                c = self.chunks[ci]
                results.append({
                    "id": c.id,
                    "source": c.source,
                    "section": c.section,
                    "condition": c.condition,
                    "age_group": c.age_group,
                    "urgency_tag": c.urgency_tag,
                    "is_danger_sign": c.is_danger_sign,
                    "text": c.text,
                    "score": float(fused[int(j)]),
                    "rank": rank + 1,
                })
            return results

    def search_danger_signs(self, query: str, age_group: Optional[str] = None,
                            k: int = DANGER_TOP_K) -> list[dict]:
        """Dedicated danger-sign sub-index query for the safety-net node."""
        return self.search(query, age_group=age_group, k=k, danger_only=True)

    def stats(self) -> dict:
        return {
            "chunks": len(self.chunks),
            "danger_sign_chunks": sum(1 for c in self.chunks if c.is_danger_sign),
            "dense_enabled": self.dense_enabled,
            "fingerprint": self.fingerprint,
        }


_retriever: Optional[Retriever] = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever().build()
    return _retriever
