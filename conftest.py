"""Pytest configuration — set env vars before any test imports."""

import os

# Force hash-bow embedding backend in tests to avoid slow SentenceTransformer
# model downloads in multiprocessing workers.
os.environ.setdefault("SPECTRA_EMBEDDING_BACKEND", "hash_bow")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
