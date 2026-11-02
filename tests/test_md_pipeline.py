import json

from src.sites.scoolinary_md import pipeline
from src.sites.scoolinary_md.llm import OllamaClient

GOOD = {"recetas": [{"titulo": "Focaccia", "chef": "L", "cocina": "", "tipo_plato": "Pan",
                     "elaboraciones": [{"nombre": "Masa", "ingredientes": ["harina"],
                                        "pasos": ["Amasar"]}]}]}


class T:
    def __init__(self, responses):
        self.responses = list(responses)
        self.n = 0

    def __call__(self, url, payload, timeout):
        self.n += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return {"response": r}


def fake_text(pdf):
    return "Focaccia\n● harina\n● Amasar\f"


def client(responses):
    return OllamaClient("http://x", "m", transport=T(responses))


def sel(tmp_path):
    return pipeline.Selection("focaccias", tmp_path / "Recetario.pdf", False)


def test_extract_course_writes_cache(tmp_path):
    cache = tmp_path / "c"
    status = pipeline.extract_course(sel(tmp_path), cache, client([json.dumps(GOOD)]),
                                     force=False, pdf_text=fake_text)
    assert status == "ok"
    data = json.loads((cache / "focaccias.json").read_text())
    assert data["course"] == "focaccias" and data["translated"] is False
    assert data["recipes"][0]["cocina"] == "Italia"
    assert data["model"] == "m" and data["validation"]["ratio"] == 1.0
    assert not list(cache.glob("*.tmp"))


def test_skip_existing_unless_force(tmp_path):
    cache = tmp_path / "c"
    c1 = client([json.dumps(GOOD)])
    pipeline.extract_course(sel(tmp_path), cache, c1, force=False, pdf_text=fake_text)
    c2 = client([json.dumps(GOOD)])
    assert pipeline.extract_course(sel(tmp_path), cache, c2, force=False,
                                   pdf_text=fake_text) == "skipped"
    assert c2.transport.n == 0
    assert pipeline.extract_course(sel(tmp_path), cache, c2, force=True,
                                   pdf_text=fake_text) == "ok"


def test_failure_recorded_and_retried(tmp_path):
    cache = tmp_path / "c"
    status = pipeline.extract_course(sel(tmp_path), cache, client(["{bad", "{bad"]),
                                     force=False, pdf_text=fake_text)
    assert status == "error"
    assert "error" in json.loads((cache / "focaccias.json").read_text())
    # an errored cache is retried without --force
    assert pipeline.extract_course(sel(tmp_path), cache, client([json.dumps(GOOD)]),
                                   force=False, pdf_text=fake_text) == "ok"


def test_retry_on_severe_incompleteness_keeps_better(tmp_path):
    text = "x\n" + "\n".join(["● item"] * 20) + "\f"
    poor = {"recetas": [GOOD["recetas"][0]]}
    rich = {"recetas": [{**GOOD["recetas"][0], "elaboraciones": [
        {"nombre": "Masa", "ingredientes": ["i"] * 10, "pasos": ["p"] * 10}]}]}
    c = client([json.dumps(poor), json.dumps(rich)])
    cache = tmp_path / "c"
    pipeline.extract_course(sel(tmp_path), cache, c, force=False, pdf_text=lambda p: text)
    assert c.transport.n == 2
    data = json.loads((cache / "focaccias.json").read_text())
    assert len(data["recipes"][0]["elaboraciones"][0]["ingredientes"]) == 10


def test_write_report(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "a.json").write_text(json.dumps({"course": "a", "source_pdf": "/a.pdf", "recipes": [
        {"needs_review": True}, {"needs_review": False}]}))
    (cache / "b.json").write_text(json.dumps({"course": "b", "source_pdf": "/b.pdf",
                                              "error": "boom"}))
    pipeline.write_report(cache)
    rep = (cache / "report.md").read_text(encoding="utf-8")
    assert "| a |" in rep and "boom" in rep


def test_failing_multi_page_chunk_is_split_in_halves(tmp_path):
    def two_pages(pdf):
        return "Focaccia\n● harina\n● Amasar\fPizza\n● harina\n● Amasar\f"

    pizza = json.loads(json.dumps(GOOD))
    pizza["recetas"][0]["titulo"] = "Pizza"

    def transport(url, payload, timeout):
        prompt = payload["prompt"]
        if "[Página 1]" in prompt and "[Página 2]" in prompt:
            return {"response": '{"recetas": [{"titulo": "trunc'}
        return {"response": json.dumps(GOOD if "[Página 1]" in prompt else pizza)}

    cache = tmp_path / "c"
    c = OllamaClient("http://x", "m", transport=transport)
    assert pipeline.extract_course(sel(tmp_path), cache, c, pdf_text=two_pages) == "ok"
    data = json.loads((cache / "focaccias.json").read_text())
    assert [r["titulo"] for r in data["recipes"]] == ["Focaccia", "Pizza"]
