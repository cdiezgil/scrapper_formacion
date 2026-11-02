"""Ollama client and recipe-extraction prompt/schema."""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Callable

TIMEOUT = 1200
OPTIONS = {"temperature": 0.2, "num_ctx": 16384, "num_predict": 10000, "repeat_penalty": 1.1}


class LlmError(Exception):
    """The model call failed or returned unusable output."""


def _str():
    return {"type": "string"}


def _strs():
    return {"type": "array", "items": {"type": "string"}}


_ELAB = {
    "type": "object",
    "properties": {"nombre": _str(), "ingredientes": _strs(), "pasos": _strs()},
    "required": ["nombre", "ingredientes", "pasos"],
}
_RECIPE_PROPS = {
    "titulo": _str(), "chef": _str(), "cocina": _str(), "tipo_plato": _str(),
    "ingrediente_principal": _str(), "dieta": _strs(), "raciones": _str(), "notas": _str(),
    "aparato": _strs(), "tags_ingredientes": _strs(),
    "elaboraciones": {"type": "array", "items": _ELAB},
}
SCHEMA = {
    "type": "object",
    "properties": {"recetas": {"type": "array", "items": {
        "type": "object", "properties": _RECIPE_PROPS, "required": list(_RECIPE_PROPS)}}},
    "required": ["recetas"],
}

_STR_KEYS = ("titulo", "chef", "cocina", "tipo_plato", "ingrediente_principal", "raciones",
             "notas")
_LIST_KEYS = ("dieta", "aparato", "tags_ingredientes")
_LEAD = re.compile(r"^\s*(?:\d+\s*[.)]|[●•\-–*])\s+")


def build_prompt(text: str, translate: bool) -> str:
    parts = [
        "Eres un editor culinario. El texto viene de un PDF maquetado a dos columnas "
        "(extraído con pdftotext -layout): las columnas laterales suelen ser elaboraciones "
        "distintas (p.ej. una salsa o salmuera). Extrae TODAS las recetas. Cada receta puede "
        "tener varias elaboraciones (masa, relleno, salsa...), cada una con sus ingredientes "
        "y pasos. Copia cantidades y pasos literalmente, sin inventar. Cada paso va en la "
        "elaboración a la que pertenece (no pongas los pasos de la salmuera o la salsa bajo la "
        "masa). cocina = país/tradición (p.ej. \"Italia\"). tipo_plato = p.ej. \"Pan\", "
        "\"Postre\", \"Principal\". aparato = horno, sartén, freidora, Thermomix... "
        "tags_ingredientes = ingredientes clave. Usa \"\" o [] si no consta.",
        "Ignora portadas, biografías del chef, índices y páginas de alérgenos sin receta. "
        "Marcadores como \"[Página N]\" solo indican la página; no son contenido.",
    ]
    if translate:
        parts.append("El texto NO está en español: traduce todo el contenido (título, "
                     "ingredientes, pasos, notas) al español.")
    else:
        parts.append("Si el texto es bilingüe, conserva solo la parte en español.")
    parts.append("TEXTO:\n" + text)
    return "\n\n".join(parts)


def _clean_item(s: str) -> str:
    return _LEAD.sub("", str(s)).strip()


def normalize_recipe(raw: dict) -> dict:
    out: dict = {}
    for k in _STR_KEYS:
        v = raw.get(k, "")
        out[k] = str(v).strip() if v is not None else ""
    for k in _LIST_KEYS:
        out[k] = [str(x).strip() for x in (raw.get(k) or []) if str(x).strip()]
    elabs = []
    for e in raw.get("elaboraciones") or []:
        elabs.append({
            "nombre": str(e.get("nombre") or "").strip(),
            "ingredientes": [c for c in map(_clean_item, e.get("ingredientes") or []) if c],
            "pasos": [c for c in map(_clean_item, e.get("pasos") or []) if c],
        })
    out["elaboraciones"] = elabs
    return out


def _urllib_transport(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class OllamaClient:
    def __init__(self, base_url: str, model: str,
                 transport: Callable[[str, dict, float], dict] | None = None,
                 timeout: float = TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.transport = transport or _urllib_transport
        self.timeout = timeout

    def generate(self, prompt: str, schema: dict) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False, "think": False,
                   "format": schema, "options": dict(OPTIONS)}
        try:
            data = self.transport(f"{self.base_url}/api/generate", payload, self.timeout)
        except Exception as exc:  # network, HTTP, timeout
            raise LlmError(f"Ollama request failed: {exc}") from exc
        return data.get("response", "")


def extract_recipes(client: OllamaClient, text: str, translate: bool) -> list[dict]:
    raw = client.generate(build_prompt(text, translate), SCHEMA)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmError(f"Invalid JSON from model: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("recetas"), list):
        raise LlmError("Model JSON lacks 'recetas' list")
    return [normalize_recipe(r) for r in data["recetas"] if isinstance(r, dict)]
