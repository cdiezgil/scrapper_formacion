import json

import pytest

from src.sites.scoolinary_md.llm import (
    LlmError,
    OllamaClient,
    SCHEMA,
    build_prompt,
    extract_recipes,
    normalize_recipe,
)

GOOD = {"recetas": [{"titulo": "Focaccia", "chef": "Luigi", "cocina": "Italia",
                     "tipo_plato": "Pan", "elaboraciones": [
                         {"nombre": "Masa", "ingredientes": ["● 1000 gr harina"],
                          "pasos": ["1. Amasar"]}]}]}


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, payload, timeout):
        self.calls.append((url, payload, timeout))
        return {"response": self.responses.pop(0)}


def test_payload_shape():
    t = FakeTransport([json.dumps(GOOD)])
    c = OllamaClient("http://x:1/", "gemma4:26b", transport=t)
    c.generate("hola", SCHEMA)
    url, payload, timeout = t.calls[0]
    assert url == "http://x:1/api/generate"
    assert payload["model"] == "gemma4:26b"
    assert payload["stream"] is False and payload["think"] is False
    assert payload["format"] == SCHEMA
    assert payload["options"] == {"temperature": 0.2, "num_ctx": 16384,
                                  "num_predict": 10000, "repeat_penalty": 1.1}
    assert timeout >= 1200


def test_schema_requires_all_fields():
    item = SCHEMA["properties"]["recetas"]["items"]
    for key in ("titulo", "chef", "cocina", "tipo_plato", "ingrediente_principal", "dieta",
                "raciones", "notas", "elaboraciones", "aparato", "tags_ingredientes"):
        assert key in item["required"]
    assert item["properties"]["dieta"]["type"] == "array"


def test_prompt_mentions_key_rules():
    p = build_prompt("TEXTO", translate=False)
    assert "dos columnas" in p and "TEXTO" in p and "traduc" not in p.lower()
    assert "traduce" in build_prompt("T", translate=True).lower()


def test_extract_recipes_cleans_markers():
    t = FakeTransport([json.dumps(GOOD)])
    c = OllamaClient("http://x", "m", transport=t)
    recs = extract_recipes(c, "texto", translate=False)
    e = recs[0]["elaboraciones"][0]
    assert e["ingredientes"] == ["1000 gr harina"] and e["pasos"] == ["Amasar"]
    assert recs[0]["dieta"] == [] and recs[0]["notas"] == ""


def test_extract_recipes_invalid_json():
    c = OllamaClient("http://x", "m", transport=FakeTransport(["{not json"]))
    with pytest.raises(LlmError):
        extract_recipes(c, "texto", translate=False)


def test_extract_recipes_missing_key():
    c = OllamaClient("http://x", "m", transport=FakeTransport(['{"otro": 1}']))
    with pytest.raises(LlmError):
        extract_recipes(c, "texto", translate=False)


def test_normalize_recipe_defaults():
    r = normalize_recipe({"titulo": " A "})
    assert r["titulo"] == "A" and r["elaboraciones"] == [] and r["aparato"] == []
