"""Pure validation / cleanup of LLM-extracted recipes."""
from __future__ import annotations

import re
import unicodedata

MIN_RATIO = 0.85
SEVERE_RATIO = 0.5

_GARBAGE = re.compile("[　-￿]")
_BULLET_CHARS = ("●", "•")
_LINE_ITEM = re.compile(r"^\s*(?:[-–]\s|\d+[.)]\s)")


def _fold(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower().strip())
    return "".join(c for c in nfd if not unicodedata.combining(c))


def count_source_items(text: str) -> int:
    """Count bullet / numbered items in the raw PDF text (columns may hold several per line)."""
    total = 0
    for line in text.splitlines():
        bullets = sum(line.count(b) for b in _BULLET_CHARS)
        if bullets:
            total += bullets
        elif _LINE_ITEM.match(line):
            total += 1
    return total


def count_returned_items(recipes: list[dict]) -> int:
    return sum(
        len(e.get("ingredientes", [])) + len(e.get("pasos", []))
        for r in recipes for e in r.get("elaboraciones", [])
    )


def completeness_ratio(source_text: str, recipes: list[dict]) -> float:
    src = count_source_items(source_text)
    if src == 0:
        return 1.0
    return round(count_returned_items(recipes) / src, 3)


def strip_garbage(text: str, source: str) -> str:
    """Drop CJK/unusual codepoints that are absent from the source text."""
    def repl(m: re.Match) -> str:
        return m.group(0) if m.group(0) in source else " "
    cleaned = _GARBAGE.sub(repl, text)
    if cleaned == text:
        return text
    return re.sub(r" {2,}", " ", cleaned).strip()


# --- cuisine ---------------------------------------------------------------
_CUISINE_ALIASES = {
    "italia": "Italia", "italy": "Italia", "italiana": "Italia", "italiano": "Italia",
    "italian": "Italia",
    "mexico": "México", "mexicana": "México", "mexicano": "México", "mexican": "México",
    "peru": "Perú", "peruana": "Perú", "peruano": "Perú", "peruvian": "Perú",
    "nikkei": "Perú",
    "japon": "Japón", "japonesa": "Japón", "japones": "Japón", "japan": "Japón",
    "japanese": "Japón",
    "espana": "España", "espanola": "España", "espanol": "España", "spain": "España",
    "spanish": "España",
    "francia": "Francia", "francesa": "Francia", "frances": "Francia", "france": "Francia",
    "french": "Francia",
    "india": "India", "indian": "India", "hindu": "India",
    "china": "China", "chinese": "China", "china sichuan": "China",
    "corea": "Corea", "coreana": "Corea", "korea": "Corea", "korean": "Corea",
    "corea del sur": "Corea",
    "brasil": "Brasil", "brasilena": "Brasil", "brazil": "Brasil", "brazilian": "Brasil",
    "colombia": "Colombia", "colombiana": "Colombia", "colombian": "Colombia",
    "marruecos": "Marruecos", "marroqui": "Marruecos", "morocco": "Marruecos",
    "moroccan": "Marruecos",
    "libano": "Oriente Medio", "libanesa": "Oriente Medio", "lebanon": "Oriente Medio",
    "lebanese": "Oriente Medio", "oriente medio": "Oriente Medio",
    "medio oriente": "Oriente Medio", "middle east": "Oriente Medio",
    "middle eastern": "Oriente Medio",
    "sudeste asiatico": "Sudeste Asiático", "southeast asia": "Sudeste Asiático",
    "southeast asian": "Sudeste Asiático",
    "argelia": "Argelia", "argelina": "Argelia", "algeria": "Argelia",
    "estados unidos": "Estados Unidos", "eeuu": "Estados Unidos", "ee uu": "Estados Unidos",
    "usa": "Estados Unidos", "us": "Estados Unidos", "americana": "Estados Unidos",
    "californiana": "Estados Unidos", "american": "Estados Unidos",
    "internacional": "Internacional", "international": "Internacional",
}


_CUISINE_ALIASES.update({
    "italoamericana": "Italia", "italoamericano": "Italia", "alpes": "Italia",
    "andaluza": "España", "andalucia": "España", "pais vasco": "España", "vasca": "España",
    "catalana": "España",
    "londres": "Reino Unido", "escocia": "Reino Unido", "inglesa": "Reino Unido",
    "reino unido": "Reino Unido", "british": "Reino Unido",
    "paris": "Francia", "filadelfia": "Estados Unidos", "mediterranea": "Internacional",
    "fusion": "Internacional",
    "grecia": "Grecia", "griega": "Grecia", "vietnam": "Vietnam", "vietnamita": "Vietnam",
    "cuba": "Cuba", "cubana": "Cuba", "portugal": "Portugal", "portuguesa": "Portugal",
    "indonesia": "Indonesia", "tailandia": "Tailandia", "tailandesa": "Tailandia",
})


def normalize_cuisine(name: str) -> str:
    """Canonical cuisine for a model-given name, or "" when it names no known cuisine
    (the caller then falls back to the course slug). Compound names such as
    "Nikkei (Perú/Japón)" or "Perú Asia" resolve to their first known part."""
    key = re.sub(r"[^a-z ]", " ", _fold(name or ""))
    key = re.sub(r"\s+", " ", key).strip()
    if key in _CUISINE_ALIASES:
        return _CUISINE_ALIASES[key]
    words = key.split()
    for size in (2, 1):
        for i in range(len(words) - size + 1):
            part = " ".join(words[i:i + size])
            if part in _CUISINE_ALIASES:
                return _CUISINE_ALIASES[part]
    return ""


# (token prefixes, cuisine) in priority order
_SLUG_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("californian",), "Estados Unidos"),
    (("peru", "nikkei"), "Perú"),
    (("mexic", "taco", "chiles"), "México"),
    (("ital", "pasta", "gnocchi", "risotto", "focaccia", "pizza", "panettone", "gelato"),
     "Italia"),
    (("japon", "ramen", "sake", "sushi"), "Japón"),
    (("espan", "paella", "tapas", "pincho", "tortilla"), "España"),
    (("franc", "eclairs", "croissant", "croute"), "Francia"),
    (("india",), "India"),
    (("chin", "sichuan"), "China"),
    (("corean",), "Corea"),
    (("brasil",), "Brasil"),
    (("colombian",), "Colombia"),
    (("marroqu",), "Marruecos"),
    (("libanes",), "Oriente Medio"),
    (("argelin",), "Argelia"),
)


def cuisine_from_slug(slug: str) -> str:
    s = _fold(slug)
    if "oriente-medio" in s:
        return "Oriente Medio"
    if "sudeste-asiatico" in s:
        return "Sudeste Asiático"
    if "dim-sum" in s:
        return "China"
    tokens = s.split("-")
    for prefixes, cuisine in _SLUG_RULES:
        if any(t.startswith(p) for t in tokens for p in prefixes):
            return cuisine
    return "Internacional"


# --- recipe validation -----------------------------------------------------
def validate_recipes(recipes: list[dict], source_text: str, translated: bool, course: str,
                     relaxed: bool = False) -> dict:
    """Clean recipes in place, set needs_review/review_reasons, return a summary."""
    ratio = completeness_ratio(source_text, recipes)
    skip_ratio = translated or relaxed
    for r in recipes:
        reasons: list[str] = []
        for e in r.get("elaboraciones", []):
            e["ingredientes"] = [strip_garbage(x, source_text) for x in e.get("ingredientes", [])]
            e["pasos"] = [strip_garbage(x, source_text) for x in e.get("pasos", [])]
            e["nombre"] = strip_garbage(e.get("nombre", ""), source_text)
        for key in ("titulo", "chef", "notas", "tipo_plato", "ingrediente_principal"):
            if key in r:
                r[key] = strip_garbage(r[key], source_text)
        cuisine = normalize_cuisine(r.get("cocina", "")) or cuisine_from_slug(course)
        r["cocina"] = cuisine
        ings = sum(len(e["ingredientes"]) for e in r.get("elaboraciones", []))
        steps = sum(len(e["pasos"]) for e in r.get("elaboraciones", []))
        if ings == 0:
            reasons.append("Sin ingredientes")
        if steps == 0:
            reasons.append("Sin pasos de preparación")
        if not skip_ratio and ratio < MIN_RATIO:
            reasons.append(
                f"Extracción posiblemente incompleta ({count_returned_items(recipes)} de "
                f"{count_source_items(source_text)} elementos del PDF)")
        r["review_reasons"] = reasons
        r["needs_review"] = bool(reasons)
    return {
        "ratio": ratio,
        "source_items": count_source_items(source_text),
        "returned_items": count_returned_items(recipes),
        "recipes": len(recipes),
        "needs_review": sum(1 for r in recipes if r["needs_review"]),
        "relaxed": skip_ratio,
    }
