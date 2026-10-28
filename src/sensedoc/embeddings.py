"""Turn text into vectors (lists of numbers) that capture its meaning, so similar meanings are close together.

Used by the knowledge assistant (find passages that answer a question) and by product matching
(tell that 'Coke Light' means the 'Diet' SKU when the spelling alone can't).
"""

import numpy as np

from sensedoc import config

_cache: dict[tuple[str, str], list[float]] = {}  # (text, task) -> vector; product names repeat a lot
CACHE_LIMIT = 5000


def embed(texts: list[str], task: str) -> list[list[float]] | None:
    """Vectors for the texts, or None when embedding is off or unavailable (callers fall back gracefully)."""
    if not config.EMBEDDINGS_ENABLED or not texts:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        vectors = []
        for start in range(0, len(texts), 100):  # the API takes up to 100 texts per call
            result = client.models.embed_content(
                model=config.EMBEDDING_MODEL,
                contents=texts[start : start + 100],
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=config.EMBED_DIMS),
            )
            vectors += [e.values for e in result.embeddings]
        return vectors
    except Exception:
        return None


def similarity_by_meaning(query: str, options: list[str]) -> list[float] | None:
    """Cosine similarity (about 0.7 = unrelated, 1.0 = same meaning) between a query and each option."""
    task = "RETRIEVAL_QUERY"  # measured: separates 'Light'→'Diet' from look-alikes far better than SEMANTIC_SIMILARITY
    needed = [t for t in dict.fromkeys([query, *options]) if (t, task) not in _cache]
    if needed:
        vectors = embed(needed, task)
        if vectors is None:
            return None
        if len(_cache) > CACHE_LIMIT:
            _cache.clear()
        _cache.update({(t, task): v for t, v in zip(needed, vectors)})

    q = np.array(_cache[(query, task)])
    sims = []
    for option in options:
        v = np.array(_cache[(option, task)])
        sims.append(float(q @ v / (np.linalg.norm(q) * np.linalg.norm(v))))
    return sims
