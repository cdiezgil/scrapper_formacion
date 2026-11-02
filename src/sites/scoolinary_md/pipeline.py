"""Extraction pipeline: PDF -> chunks -> LLM -> validated JSON cache (resumable)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import extract as ex
from .llm import LlmError, OllamaClient, extract_recipes
from .selection import Selection
from .validate import SEVERE_RATIO, completeness_ratio, validate_recipes

__all__ = ["Selection", "extract_course", "write_report", "load_caches"]

_BILINGUAL_HINT = re.compile(r"ingl[eé]s|franc[eé]s|english", re.IGNORECASE)


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _extract_chunk(client: OllamaClient, chunk: ex.Chunk, translate: bool) -> list[dict]:
    """One LLM call, retried once on invalid JSON or severe incompleteness; keep the better."""
    best: list[dict] | None = None
    last_err: Exception | None = None
    for _ in range(2):
        try:
            recipes = extract_recipes(client, chunk.text, translate)
        except LlmError as exc:
            last_err = exc
            continue
        if best is None or ex_size(recipes) > ex_size(best):
            best = recipes
        if translate or completeness_ratio(chunk.text, best) >= SEVERE_RATIO:
            break
    if best is None:
        raise last_err or LlmError("no result")
    return best


def _extract_span(client: OllamaClient, pages: list[str], chunk: ex.Chunk,
                  translate: bool) -> list[dict]:
    """Extract a chunk; if the model keeps failing (e.g. output cut by length), split it in
    halves and extract each half, down to single pages."""
    try:
        return _extract_chunk(client, chunk, translate)
    except LlmError:
        if chunk.start == chunk.end:
            raise
    mid = (chunk.start + chunk.end) // 2
    return (_extract_span(client, pages, ex.make_chunk(pages, chunk.start, mid), translate)
            + _extract_span(client, pages, ex.make_chunk(pages, mid + 1, chunk.end), translate))


def ex_size(recipes: list[dict]) -> int:
    from .validate import count_returned_items
    return count_returned_items(recipes)


def extract_course(sel: Selection, cache_dir: Path, client: OllamaClient, force: bool = False,
                   pdf_text: Callable[[Path], str] = ex.pdf_text) -> str:
    """Process one course. Returns 'ok', 'skipped' or 'error'."""
    path = cache_dir / f"{sel.course}.json"
    if path.exists() and not force:
        try:
            if "error" not in json.loads(path.read_text(encoding="utf-8")):
                return "skipped"
        except (OSError, json.JSONDecodeError):
            pass
    base = {"course": sel.course, "source_pdf": str(sel.pdf), "translated": sel.translate,
            "model": client.model,
            "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        text = pdf_text(sel.pdf)
        pages = ex.split_pages(text)
        found: list[dict] = []
        for chunk in ex.chunk_pages(pages):
            found.extend(_extract_span(client, pages, chunk, sel.translate))
        recipes = ex.merge_recipes(found)
        relaxed = bool(_BILINGUAL_HINT.search(sel.pdf.name))
        validation = validate_recipes(recipes, text, sel.translate, sel.course, relaxed)
        _atomic_write(path, {**base, "recipes": recipes, "validation": validation})
        return "ok"
    except Exception as exc:  # one course failing must not stop the batch
        _atomic_write(path, {**base, "error": f"{type(exc).__name__}: {exc}"})
        return "error"


def load_caches(cache_dir: Path) -> list[dict]:
    if not cache_dir.is_dir():
        return []
    out = []
    for p in sorted(cache_dir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def write_report(cache_dir: Path) -> Path:
    caches = load_caches(cache_dir)
    lines = ["# Informe Scoolinary MD", "",
             "| Curso | PDF | Recetas | Por revisar | Error |", "| :--- | :--- | ---: | ---: | :--- |"]
    total = review = errors = 0
    for c in caches:
        recipes = c.get("recipes", [])
        n_rev = sum(1 for r in recipes if r.get("needs_review"))
        err = str(c.get("error", "")).replace("|", "\\|").replace("\n", " ")
        total += len(recipes)
        review += n_rev
        errors += 1 if err else 0
        lines.append(f"| {c.get('course')} | {c.get('source_pdf', '')} | {len(recipes)} | "
                     f"{n_rev} | {err} |")
    lines += ["", f"Cursos: {len(caches)} · Recetas: {total} · Por revisar: {review} · "
              f"Errores: {errors}", ""]
    path = cache_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
