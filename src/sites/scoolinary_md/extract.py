"""PDF text extraction, page chunking and recipe merging."""
from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_WORDS = 2500
OVERLAP = 1
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"


@dataclass(frozen=True)
class Chunk:
    start: int  # 1-based first page
    end: int    # 1-based last page (inclusive)
    text: str


def pdf_text(pdf: Path) -> str:
    import shutil
    exe = shutil.which("pdftotext") or PDFTOTEXT
    res = subprocess.run([exe, "-layout", str(pdf), "-"], capture_output=True, check=True)
    return res.stdout.decode("utf-8", errors="replace")


def split_pages(text: str) -> list[str]:
    pages = text.split("\f")
    if len(pages) > 1 and not pages[-1].strip():
        pages.pop()
    return pages


def make_chunk(pages: list[str], start: int, end: int) -> Chunk:
    """Chunk for 1-based pages ``start..end`` (inclusive)."""
    text = "\n\n".join(f"[Página {k}]\n{pages[k - 1]}" for k in range(start, end + 1))
    return Chunk(start, end, text)


def chunk_pages(pages: list[str], max_words: int = MAX_WORDS, overlap: int = OVERLAP) -> list[Chunk]:
    counts = [len(p.split()) for p in pages]
    chunks: list[Chunk] = []
    i = 0
    n = len(pages)
    while i < n:
        j = i
        words = counts[i]
        while j + 1 < n and words + counts[j + 1] <= max_words:
            j += 1
            words += counts[j]
        chunks.append(make_chunk(pages, i + 1, j + 1))
        if j + 1 >= n:
            break
        i = max(j + 1 - overlap, i + 1)
    return chunks


def _norm_title(title: str) -> str:
    nfd = unicodedata.normalize("NFD", title.lower())
    s = "".join(c for c in nfd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _size(items: dict | list) -> int:
    elabs = items["elaboraciones"] if isinstance(items, dict) else items
    return sum(len(e.get("ingredientes", [])) + len(e.get("pasos", [])) for e in elabs)


def _merge_two(a: dict, b: dict) -> dict:
    base, other = (a, b) if _size(a) >= _size(b) else (b, a)
    merged = dict(base)
    elabs = [dict(e) for e in base.get("elaboraciones", [])]
    index = {_norm_title(e.get("nombre", "")): k for k, e in enumerate(elabs)}
    for e in other.get("elaboraciones", []):
        key = _norm_title(e.get("nombre", ""))
        if key in index and (key or len(elabs) == 1):
            k = index[key]
            if _size([e]) > _size([elabs[k]]):
                elabs[k] = dict(e)
        elif key not in index:
            elabs.append(dict(e))
            index[key] = len(elabs) - 1
    merged["elaboraciones"] = elabs
    return merged


def merge_recipes(recipes: list[dict]) -> list[dict]:
    """Dedupe by normalized title; keep the richest, adding complementary elaborations."""
    order: list[str] = []
    by_key: dict[str, dict] = {}
    for r in recipes:
        key = _norm_title(r.get("titulo", ""))
        if key in by_key:
            by_key[key] = _merge_two(by_key[key], r)
        else:
            by_key[key] = r
            order.append(key)
    return [by_key[k] for k in order]
