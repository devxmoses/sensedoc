"""Knowledge assistant: answer questions from the uploaded documents, citing document and page.

1. Index:    each processed document's text is cut into page-sized chunks and embedded.
2. Retrieve: a question is matched to the most relevant chunks (meaning + keywords).
3. Answer:   the LLM answers only from those chunks and the verified extracted values,
             cites them, and says so when the answer is not there.
"""

import re

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sensedoc import config
from sensedoc.db import ChunkRow, DocumentRow
from sensedoc.embeddings import embed
from sensedoc.export import document_values
from sensedoc.readers import ParsedDocument

CHUNK_CHARS = 1500
TOP_K = 6
STOPWORDS = {"the", "and", "for", "what", "which", "who", "how", "was", "were", "are", "did", "does", "with", "from",
             "this", "that", "our", "all", "any", "much", "many", "have", "has", "on", "in", "of", "to", "is"}

ANSWER_PROMPT = (
    "You answer questions about a company's documents. Use ONLY the numbered sources and the verified "
    "extracted data below. Cite every source you used by its number. For totals, prices and dates, prefer the "
    "verified extracted data. If the sources do not contain the answer, set found to false and say plainly "
    "that the documents don't say. Never use outside knowledge."
)


class Answer(BaseModel):
    found: bool = Field(description="True only if the sources contain the answer")
    answer: str = Field(description="A short, direct answer in plain language")
    sources: list[int] = Field(default_factory=list, description="Numbers of the sources used")


# ---------- 1. Index ----------
def page_texts(parsed: ParsedDocument) -> list[tuple[int, str]]:
    pages: dict[int, list[str]] = {}
    for line in parsed.lines:
        pages.setdefault(line.page, []).append(line.text)
    if pages:
        return [(page, "\n".join(lines)) for page, lines in sorted(pages.items())]
    return [(1, parsed.text)] if parsed.text.strip() else []


def split(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Cut at line breaks so a table row is never split in half."""
    chunks, current = [], ""
    for line in text.splitlines():
        if current and len(current) + len(line) > size:
            chunks.append(current)
            current = ""
        current += line + "\n"
    return [c.strip() for c in [*chunks, current] if c.strip()]


def index_document(db: Session, document_id: int, parsed: ParsedDocument) -> int:
    db.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
    pieces = [(page, text) for page, page_text in page_texts(parsed) for text in split(page_text)]
    vectors = embed([text for _, text in pieces], "RETRIEVAL_DOCUMENT") or [None] * len(pieces)
    for (page, text), vector in zip(pieces, vectors):
        db.add(ChunkRow(document_id=document_id, page=page, text=text, embedding=vector))
    return len(pieces)


# ---------- 2. Retrieve ----------
def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-.]+", text.lower()) if w not in STOPWORDS}


def retrieve(db: Session, question: str, document_ids: list[int] | None = None, k: int = TOP_K) -> list[ChunkRow]:
    q = embed([question], "RETRIEVAL_QUERY")
    query = select(ChunkRow)
    if document_ids:
        query = query.where(ChunkRow.document_id.in_(document_ids))

    if q and config.IS_POSTGRES:
        # pgvector: the database uses its index to find the closest chunks, without loading every chunk
        distance = ChunkRow.embedding.cosine_distance(q[0])
        rows = db.execute(
            query.add_columns(distance.label("distance")).where(ChunkRow.embedding.is_not(None)).order_by(distance).limit(k * 4)
        ).all()
        chunks = [row[0] for row in rows]
        meaning = np.array([1 - row.distance for row in rows])
    else:
        # SQLite (or no embeddings): compare in Python; fine up to tens of thousands of chunks
        chunks = db.scalars(query).all()
        meaning = None
        if q:
            qv = np.array(q[0])
            meaning = np.array([cosine(qv, c.embedding) if c.embedding is not None else 0.0 for c in chunks])
    if not chunks:
        return []

    words = keywords(question)
    keyword_scores = np.array([len(words & keywords(c.text)) / max(len(words), 1) for c in chunks])
    scores = keyword_scores if meaning is None else 0.7 * meaning + 0.3 * keyword_scores

    best = np.argsort(-scores)[:k]
    return [chunks[i] for i in best if scores[i] > 0]


def cosine(a: np.ndarray, b) -> float:
    b = np.asarray(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


# ---------- 3. Answer ----------
def ask(db: Session, question: str, document_ids: list[int] | None = None) -> dict:
    from sensedoc.extractor import get_llm

    chunks = retrieve(db, question, document_ids)
    if not chunks:
        return {"found": False, "answer": "There are no indexed documents that mention this yet.", "citations": []}

    sources = "\n\n".join(
        f"[{i}] {c.document.filename}, page {c.page}:\n{c.text}" for i, c in enumerate(chunks, start=1)
    )
    verified = []
    for doc_id in dict.fromkeys(c.document_id for c in chunks):
        fields, _ = document_values(db.get(DocumentRow, doc_id))
        if fields:
            verified.append(f"{db.get(DocumentRow, doc_id).filename}: {fields}")
    prompt = (
        f"Question: {question}\n\nSources:\n{sources}\n\n"
        f"Verified extracted data:\n" + ("\n".join(verified) or "(none)")
    )

    llm = get_llm(config.GEMINI_MODEL).with_structured_output(Answer)
    result: Answer = llm.invoke([("system", ANSWER_PROMPT), ("human", prompt)])

    cited = [i for i in dict.fromkeys(result.sources) if 1 <= i <= len(chunks)]
    return {
        "found": result.found,
        "answer": result.answer,
        "citations": [
            {
                "source": i,
                "document_id": chunks[i - 1].document_id,
                "filename": chunks[i - 1].document.filename,
                "page": chunks[i - 1].page,
                "snippet": chunks[i - 1].text[:300],
            }
            for i in cited
        ]
        if result.found
        else [],
    }
