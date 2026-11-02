"""Choose which PDF of each Scoolinary course holds the Spanish recipe book."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_RECIPE_BOOK = re.compile(r"recetario|recipe[-_ ]?book", re.IGNORECASE)
_CODE = re.compile(r"(?:^|[_\-\s])(ES|EN|FR|DE)-")  # uppercase only: "-de-" is Spanish
_KEYWORDS = (
    ("de", re.compile(r"rezeptbuch", re.IGNORECASE)),
    ("fr", re.compile(r"livre", re.IGNORECASE)),
    ("en", re.compile(r"recipe[-_ ]?book", re.IGNORECASE)),
)
# Preference when only foreign-language books exist (English first).
_FOREIGN_ORDER = ("en", "fr", "de")


@dataclass(frozen=True)
class Selection:
    course: str
    pdf: Path
    translate: bool


def is_recipe_book(filename: str) -> bool:
    return bool(_RECIPE_BOOK.search(filename))


def detect_language(filename: str) -> str:
    """Return 'es', 'en', 'fr' or 'de'. Names without any marker are Spanish."""
    stem = filename.rsplit(".", 1)[0] if filename.lower().endswith(".pdf") else filename
    m = _CODE.search(stem)
    if m:
        return m.group(1).lower()
    for lang, rx in _KEYWORDS:
        if rx.search(stem):
            return lang
    return "es"


def select_pdf(filenames: list[str]) -> tuple[str, bool] | None:
    """Pick the single recipe-book filename of a course, as (filename, translate)."""
    books = sorted(f for f in filenames if is_recipe_book(f))
    if not books:
        return None
    spanish = [f for f in books if detect_language(f) == "es"]
    if spanish:
        return spanish[0], False
    for lang in _FOREIGN_ORDER:
        for f in books:
            if detect_language(f) == lang:
                return f, True
    return books[0], True


def select_all(src: Path) -> tuple[list[Selection], list[str]]:
    """Scan ``src/<course>/*.pdf``. Returns (selections, excluded course slugs)."""
    selections: list[Selection] = []
    excluded: list[str] = []
    for course_dir in sorted(p for p in src.iterdir() if p.is_dir()):
        names = [p.name for p in course_dir.iterdir() if p.suffix.lower() == ".pdf"]
        chosen = select_pdf(names)
        if chosen is None:
            excluded.append(course_dir.name)
        else:
            selections.append(Selection(course_dir.name, course_dir / chosen[0], chosen[1]))
    return selections, excluded
