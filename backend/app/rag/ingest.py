"""
Corpus ingestion: parse the protocol corpus into atomic, metadata-tagged chunks.

Format: each chunk is a `### CHUNK` block with a small key: value header,
a `---` separator, then the chunk body. Danger-sign rows are authored as their
own atomic chunks (never split), per the spec.

PDFs/markdown dropped into the corpus dir without `### CHUNK` markers are also
ingested via a simple paragraph splitter, so real IMNCI PDFs can be added later.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from app.config import CORPUS_DIR

_CHUNK_RE = re.compile(r"^###\s+CHUNK\s*$", re.MULTILINE)


@dataclass
class Chunk:
    id: str
    source: str
    section: str
    condition: str
    age_group: str          # neonate | child | adult | maternal | general
    urgency_tag: str        # emergency | urgent | home | routine
    is_danger_sign: bool
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_header(raw: str) -> tuple[dict, str]:
    """Split a chunk block into (header dict, body text)."""
    if "---" in raw:
        header_part, _, body = raw.partition("---")
    else:
        header_part, body = "", raw
    meta: dict[str, str] = {}
    for line in header_part.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip()
    return meta, body.strip()


def _chunk_from_block(block: str, source_file: str, idx: int) -> Chunk | None:
    meta, body = _parse_header(block)
    if not body:
        return None
    text = " ".join(body.split())
    cid = hashlib.sha1(f"{source_file}:{idx}:{text[:80]}".encode()).hexdigest()[:16]
    return Chunk(
        id=cid,
        source=meta.get("source", source_file),
        section=meta.get("section", ""),
        condition=meta.get("condition", "general"),
        age_group=meta.get("age_group", "general").lower(),
        urgency_tag=meta.get("urgency_tag", "urgent").lower(),
        is_danger_sign=str(meta.get("is_danger_sign", "false")).lower() == "true",
        text=text,
    )


def _ingest_markdown(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    parts = _CHUNK_RE.split(raw)
    chunks: list[Chunk] = []
    if len(parts) > 1:
        # Structured corpus with explicit CHUNK markers.
        for i, block in enumerate(parts[1:]):
            c = _chunk_from_block(block, path.stem, i)
            if c:
                chunks.append(c)
    else:
        # Fallback: split unstructured markdown into paragraph chunks.
        for i, para in enumerate(p for p in re.split(r"\n\s*\n", raw) if p.strip()):
            text = " ".join(para.split())
            if len(text) < 40:
                continue
            cid = hashlib.sha1(f"{path.stem}:{i}:{text[:80]}".encode()).hexdigest()[:16]
            chunks.append(Chunk(cid, path.stem, "", "general", "general", "urgent", False, text))
    return chunks


def _ingest_pdf(path: Path) -> list[Chunk]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []
    reader = PdfReader(str(path))
    chunks: list[Chunk] = []
    for pno, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        for j, para in enumerate(p for p in re.split(r"\n\s*\n", text) if p.strip()):
            t = " ".join(para.split())
            if len(t) < 60:
                continue
            cid = hashlib.sha1(f"{path.stem}:{pno}:{j}:{t[:80]}".encode()).hexdigest()[:16]
            chunks.append(Chunk(cid, f"{path.stem} (p{pno + 1})", "", "general",
                                "general", "urgent", False, t))
    return chunks


def load_chunks(corpus_dir: Path | None = None) -> list[Chunk]:
    corpus_dir = corpus_dir or CORPUS_DIR
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.glob("**/*")):
        if path.suffix.lower() in (".md", ".markdown", ".txt"):
            chunks.extend(_ingest_markdown(path))
        elif path.suffix.lower() == ".pdf":
            chunks.extend(_ingest_pdf(path))
    # de-dup by id
    seen: dict[str, Chunk] = {}
    for c in chunks:
        seen[c.id] = c
    return list(seen.values())


def corpus_fingerprint(chunks: Iterable[Chunk]) -> str:
    h = hashlib.sha1()
    for c in sorted(chunks, key=lambda x: x.id):
        h.update(c.id.encode())
        h.update(c.text.encode())
    return h.hexdigest()[:16]


if __name__ == "__main__":
    cs = load_chunks()
    danger = sum(1 for c in cs if c.is_danger_sign)
    print(f"Loaded {len(cs)} chunks ({danger} danger-sign) from {CORPUS_DIR}")
    for c in cs[:3]:
        print(f"  [{c.age_group}/{c.urgency_tag}] {c.source} — {c.section}")
