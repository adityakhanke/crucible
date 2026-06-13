"""CPU-only embedding model. Never touches the GPU.

Uses sentence-transformers with all-MiniLM-L6-v2 (384-dim).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from crucible.config import settings

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Lazy-loaded sentence-transformers model on CPU."""

    def __init__(self):
        self._model = None
        self._model_name = settings().get("vector", {}).get(
            "embedding_model", "all-MiniLM-L6-v2"
        )

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self._model_name} (CPU)")
            self._model = SentenceTransformer(self._model_name, device="cpu")

    def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        self._load()
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        self._load()
        embeddings = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [e.tolist() for e in embeddings]
