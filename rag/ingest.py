"""Читает каталог из Postgres, чистит, режет на чанки, строит индекс в data/.
Запуск: python -m rag.ingest
"""
import html
import json
import os
import re
from pathlib import Path

import numpy as np
import psycopg
from fastembed import TextEmbedding

DB_URL = os.environ["DATABASE_URL"]          # postgresql://user:pass@host:5432/courses_for_bu
OUT = Path(os.getenv("DATA_DIR", "data"))
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_WORDS, OVERLAP = 180, 30

# (тип, таблица основной сущности, таблица блоков, FK в блоках, SQL-условие платности)
# ВНИМАНИЕ: имена колонок взяты из описания схемы, сверь с реальным DDL.
SOURCES = [
    ("article",   "Articles",   "ArticleEmbedItems",   "ArticleId",   'COALESCE(t."IsClosed", false)'),
    ("document",  "Documents",  "DocumentEmbedItems",  "DocumentId",  "false"),
    ("glossary",  "Glossary",   "GlossaryEmbedItems",  "GlossaryId",  "false"),
    ("calculator","Calculators",None,                  None,          "false"),
    ("webinar",   "Webinars",   None,                  None,          'COALESCE(t."IsClosed", false)'),
    ("podcast",   "Podcasts",   None,                  None,          'COALESCE(t."Cost", 0) > 0'),
    # Курсы: Cost IS NULL = бесплатный. Только название/описание, уроки НЕ индексируем.
    ("course",    "Courses",    None,                  None,          't."Cost" IS NOT NULL'),
]

TAG_RE = re.compile(r"<[^>]+>")


def clean(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(TAG_RE.sub(" ", raw))
    return re.sub(r"\s+", " ", text).strip()


def chunk(text: str) -> list[str]:
    words = text.split()
    if len(words) <= CHUNK_WORDS:
        return [text] if text else []
    step = CHUNK_WORDS - OVERLAP
    return [" ".join(words[i:i + CHUNK_WORDS]) for i in range(0, len(words), step)]


def fetch(conn, etype, table, blocks, fk, paid_sql):
    q = f'''
        SELECT t."Id"::text, t."Title"::text, t."Description"::text, t."Url"::text,
               ({paid_sql}) AS is_paid
        FROM "{table}" t
        WHERE t."IsDeleted" = false
    '''
    for row in conn.execute(q).fetchall():
        eid, title, desc, url, is_paid = row
        parts = [clean(desc)]
        # Тело берём только у бесплатного контента
        if blocks and not is_paid:
            bq = f'SELECT "HtmlContent" FROM "{blocks}" WHERE "{fk}" = %s ORDER BY "Order"'
            parts += [clean(b[0]) for b in conn.execute(bq, (eid,)).fetchall()]
        body = " ".join(p for p in parts if p)
        yield dict(id=eid, type=etype, title=title or "", url=url, is_paid=bool(is_paid), body=body)


def main():
    OUT.mkdir(exist_ok=True)
    chunks = []
    with psycopg.connect(DB_URL) as conn:
        for src in SOURCES:
            n_before = len(chunks)
            for doc in fetch(conn, *src):
                pieces = chunk(doc["body"]) or [doc["title"]]
                for i, piece in enumerate(pieces):
                    chunks.append({
                        "chunk_id": f'{doc["id"]}:{i}',
                        "doc_id": doc["id"], "type": doc["type"], "title": doc["title"],
                        "url": doc["url"], "is_paid": doc["is_paid"],
                        # заголовок в тексте чанка улучшает поиск
                        "text": f'{doc["title"]}. {piece}',
                    })
            print(f"{src[0]}: {len(chunks) - n_before} чанков")

    with open(OUT / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    model = TextEmbedding(EMBED_MODEL)
    emb = np.array(list(model.embed([c["text"] for c in chunks])), dtype="float32")
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    np.save(OUT / "embeddings.npy", emb)
    print(f"Готово: {len(chunks)} чанков, эмбеддинги {emb.shape}")


if __name__ == "__main__":
    main()