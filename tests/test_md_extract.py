from src.sites.scoolinary_md.extract import chunk_pages, merge_recipes, split_pages


def rec(title, ings, steps=(), name="Masa"):
    return {"titulo": title, "elaboraciones": [
        {"nombre": name, "ingredientes": list(ings), "pasos": list(steps)}]}


def test_split_pages():
    assert split_pages("a\fb\fc\f") == ["a", "b", "c"]
    assert split_pages("solo") == ["solo"]


def test_chunk_single():
    pages = ["uno dos"] * 3
    chunks = chunk_pages(pages, max_words=100)
    assert len(chunks) == 1
    assert (chunks[0].start, chunks[0].end) == (1, 3)
    assert "[Página 1]" in chunks[0].text and "[Página 3]" in chunks[0].text


def test_chunk_overlap_and_progress():
    pages = ["w " * 10] * 6  # 10 words each
    chunks = chunk_pages(pages, max_words=30, overlap=1)
    spans = [(c.start, c.end) for c in chunks]
    assert spans == [(1, 3), (3, 5), (5, 6)]


def test_chunk_oversize_page_alone():
    pages = ["w " * 50, "w " * 5]
    chunks = chunk_pages(pages, max_words=10, overlap=1)
    assert [(c.start, c.end) for c in chunks] == [(1, 1), (2, 2)]


def test_merge_dedupes_keeping_richer():
    a = rec("Focaccia Genovese", ["harina"], ["amasar"])
    b = rec("focaccia  genovese", ["harina", "agua"], ["amasar", "hornear"])
    out = merge_recipes([a, b])
    assert len(out) == 1
    assert out[0]["elaboraciones"][0]["ingredientes"] == ["harina", "agua"]


def test_merge_complementary_elaborations():
    a = rec("Pan", ["harina"], ["amasar"], name="Masa")
    b = rec("Pan", ["agua"], ["bañar"], name="Salmuera")
    out = merge_recipes([a, b])
    assert len(out) == 1
    names = [e["nombre"] for e in out[0]["elaboraciones"]]
    assert names == ["Masa", "Salmuera"]


def test_merge_preserves_order_of_distinct():
    out = merge_recipes([rec("B", ["x"]), rec("A", ["y"]), rec("B", ["x", "z"])])
    assert [r["titulo"] for r in out] == ["B", "A"]
