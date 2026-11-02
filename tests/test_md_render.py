import pytest

from src.sites.scoolinary_md.render import (
    MARKER,
    UnsafeOutputDir,
    render_collection,
    slugify,
)


def recipe(title, cuisine, plato="Pan", **kw):
    r = {"titulo": title, "chef": "Luigi: \"El\" Chef", "cocina": cuisine, "tipo_plato": plato,
         "ingrediente_principal": "Harina", "dieta": ["Vegana"], "raciones": "4", "notas": "Nota",
         "aparato": ["Horno"], "tags_ingredientes": ["Harina"],
         "needs_review": False, "review_reasons": [],
         "elaboraciones": [
             {"nombre": "Masa", "ingredientes": ["1000 gr harina"], "pasos": ["Amasar", "Hornear"]},
             {"nombre": "Salmuera", "ingredientes": ["70% agua"], "pasos": ["Bañar"]}]}
    r.update(kw)
    return r


def caches():
    return [
        {"course": "focaccias", "source_pdf": "/pdf/focaccias/Recetario.pdf",
         "translated": False, "recipes": [recipe("Focaccia: Genovese", "Italia"),
                                          recipe("Focaccia con Uva", "Italia",
                                                 needs_review=True,
                                                 review_reasons=["Sin pasos"])]},
        {"course": "cocina-india", "source_pdf": "/pdf/x.pdf", "translated": True,
         "recipes": [recipe("Pollo", "India", plato="Principal")]},
        {"course": "roto", "source_pdf": "/pdf/y.pdf", "error": "boom"},
    ]


def test_slugify():
    assert slugify("Ñoquis de Patata: ¡Crujientes!") == "noquis-de-patata-crujientes"
    assert len(slugify("a" * 200)) <= 60
    assert slugify("???") == "receta"


def test_render_layout_and_numbering(tmp_path):
    out = tmp_path / "out"
    n = render_collection(caches(), out)
    assert n == 3
    assert (out / MARKER).exists()
    # India < Italia alphabetically
    assert (out / "recipes/india/0001-pollo.md").exists()
    assert (out / "recipes/italia/0002-focaccia-genovese.md").exists()
    assert (out / "recipes/italia/0003-focaccia-con-uva.md").exists()
    for idx in ("por-cocina", "por-plato", "por-ingrediente", "por-aparato", "por-dieta",
                "por-chef", "por-curso"):
        assert (out / "indices" / f"{idx}.md").exists()


def test_note_frontmatter_and_body(tmp_path):
    out = tmp_path / "out"
    render_collection(caches(), out)
    md = (out / "recipes/italia/0002-focaccia-genovese.md").read_text(encoding="utf-8")
    assert md.startswith("---\nid: 2\nrecipe_num: \"0002\"\n")
    assert 'title: "Focaccia: Genovese"' in md
    assert 'period: "Scoolinary"' in md and 'cuisine: "Italia"' in md
    assert 'source: "Scoolinary — Focaccias"' in md
    assert 'chef: "Luigi: \\"El\\" Chef"' in md
    assert 'scoolinary_course: "focaccias"' in md
    assert 'source_pdf: "/pdf/focaccias/Recetario.pdf"' in md
    assert "needs_review: false" in md and "review_reasons: []" in md
    assert 'previous_recipe: "../india/0001-pollo.md"' in md
    assert 'next_recipe: "./0003-focaccia-con-uva.md"' in md
    assert "images:\n  complete: null\n  detail: null" in md
    assert "# 0002 · Focaccia: Genovese" in md
    assert "[⬅ Receta 0001: Pollo](../india/0001-pollo.md)" in md
    assert "[Receta 0003: Focaccia con Uva ➡](./0003-focaccia-con-uva.md)" in md
    assert "## Elaboraciones" in md and "### Masa" in md and "### Salmuera" in md
    assert "**Ingredientes**\n\n- 1000 gr harina" in md
    assert "**Preparación**\n\n1. Amasar\n2. Hornear" in md
    assert "## Procedencia y Notas" in md and "Revisar" not in md


def test_review_callout_and_first_last_nav(tmp_path):
    out = tmp_path / "out"
    render_collection(caches(), out)
    last = (out / "recipes/italia/0003-focaccia-con-uva.md").read_text(encoding="utf-8")
    assert "needs_review: true" in last and "> ⚠️ Revisar: Sin pasos" in last
    assert 'next_recipe: null' in last
    first = (out / "recipes/india/0001-pollo.md").read_text(encoding="utf-8")
    assert 'previous_recipe: null' in first
    assert "Traducida" in first or "traducid" in first.lower()


def test_readme_and_indices(tmp_path):
    out = tmp_path / "out"
    render_collection(caches(), out)
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "# Scoolinary · Recetario (3 recetas)" in readme
    assert "[`recipes/italia/`](./recipes/italia/)" in readme
    assert "Pendientes de revisión" in readme and "Focaccia con Uva" in readme
    por_cocina = (out / "indices/por-cocina.md").read_text(encoding="utf-8")
    assert "## Italia (2 recetas)" in por_cocina
    assert "[Focaccia con Uva](../recipes/italia/0003-focaccia-con-uva.md)" in por_cocina


def test_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    render_collection(caches(), a)
    render_collection(caches(), b)
    for p in a.rglob("*.md"):
        assert p.read_text(encoding="utf-8") == (b / p.relative_to(a)).read_text(encoding="utf-8")


def test_wipes_managed_dir_only(tmp_path):
    out = tmp_path / "out"
    render_collection(caches(), out)
    (out / "recipes/stale.md").write_text("x")
    render_collection(caches()[:1], out)
    assert not (out / "recipes/stale.md").exists()
    assert not (out / "recipes/india").exists()


def test_refuses_unmarked_nonempty_dir(tmp_path):
    out = tmp_path / "vault"
    out.mkdir()
    (out / "mi-nota.md").write_text("importante")
    with pytest.raises(UnsafeOutputDir):
        render_collection(caches(), out)
    assert (out / "mi-nota.md").read_text() == "importante"


def test_accepts_existing_empty_dir(tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    assert render_collection(caches(), out) == 3


def test_cached_cuisines_are_normalized_at_render(tmp_path):
    out = tmp_path / "out"
    render_collection([{"course": "focaccias", "source_pdf": "/p.pdf", "translated": False,
                        "recipes": [recipe("A", "Perú Asia"), recipe("B", "[]"),
                                    recipe("C", "<0xC2>  Italia")]}], out)
    folders = sorted(p.name for p in (out / "recipes").iterdir())
    assert folders == ["italia", "peru"]
    assert 'cuisine: "Perú"' in next((out / "recipes" / "peru").glob("*.md")).read_text()


def test_render_with_photo(tmp_path):
    cache = tmp_path / "cache"
    (cache / "media/focaccias").mkdir(parents=True)
    (cache / "media/focaccias/focaccia-genovese.jpg").write_bytes(b"JPG")
    cs = caches()
    cs[0]["recipes"][0]["foto"] = "media/focaccias/focaccia-genovese.jpg"
    out = tmp_path / "out"
    render_collection(cs, out, media_dir=cache)
    md = (out / "recipes/italia/0002-focaccia-genovese.md").read_text(encoding="utf-8")
    rel = "../../media/focaccias/focaccia-genovese.jpg"
    assert f'  complete: "{rel}"\n  detail: null' in md
    assert f"| ![Focaccia: Genovese - Fotografía]({rel}) |" in md
    assert md.index("## Galería") < md.index("## Elaboraciones")
    assert (out / "media/focaccias/focaccia-genovese.jpg").read_bytes() == b"JPG"
    assert "con foto" in (out / "README.md").read_text(encoding="utf-8")
    # recipe without photo keeps the old output
    other = (out / "recipes/italia/0003-focaccia-con-uva.md").read_text(encoding="utf-8")
    assert "complete: null" in other and "Galería" not in other


def test_render_photo_missing_file_degrades_to_no_photo(tmp_path):
    cs = caches()
    cs[0]["recipes"][0]["foto"] = "media/focaccias/nope.jpg"
    out = tmp_path / "out"
    render_collection(cs, out, media_dir=tmp_path / "cache")
    md = (out / "recipes/italia/0002-focaccia-genovese.md").read_text(encoding="utf-8")
    assert "complete: null" in md and "Galería" not in md


def test_render_without_media_dir_is_unchanged(tmp_path):
    out = tmp_path / "out"
    render_collection(caches(), out)
    assert not (out / "media").exists()
