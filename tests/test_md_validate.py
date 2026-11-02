from src.sites.scoolinary_md.validate import (
    count_source_items,
    cuisine_from_slug,
    normalize_cuisine,
    strip_garbage,
    validate_recipes,
)


def recipe(ings=("a",), steps=("b",), **kw):
    base = {"titulo": "T", "cocina": "", "elaboraciones": [
        {"nombre": "X", "ingredientes": list(ings), "pasos": list(steps)}]}
    base.update(kw)
    return base


def test_count_source_items():
    text = "● 1000 gr harina             ● otra\n- paso\n1. uno\n2) dos\nTexto suelto\n"
    assert count_source_items(text) == 5


def test_strip_garbage_removes_cjk_not_in_source():
    assert strip_garbage("su䣫tamaño", "su tamaño") == "su tamaño"
    assert strip_garbage("harina °C ½ cucharada", "") == "harina °C ½ cucharada"
    assert strip_garbage("日本 ok", "日本 ok") == "日本 ok"  # present in source: kept


def test_cuisine_from_slug():
    assert cuisine_from_slug("cocina-peruana-ceviches") == "Perú"
    assert cuisine_from_slug("cocina-nikkei") == "Perú"
    assert cuisine_from_slug("cocina-californiana-con-tecnicas-japonesas") == "Estados Unidos"
    assert cuisine_from_slug("focaccias") == "Italia"
    assert cuisine_from_slug("pate-en-croute") == "Francia"
    assert cuisine_from_slug("cocina-libanesa") == "Oriente Medio"
    assert cuisine_from_slug("gin-tonics-perfectos") == "Internacional"
    assert cuisine_from_slug("nueva-cocina-mexicana") == "México"


def test_normalize_cuisine():
    assert normalize_cuisine("Italy") == "Italia"
    assert normalize_cuisine("italiana") == "Italia"
    assert normalize_cuisine("  Mexico ") == "México"
    assert normalize_cuisine("Japan") == "Japón"
    assert normalize_cuisine("Peruvian") == "Perú"
    assert normalize_cuisine("") == ""
    assert normalize_cuisine("tailandia") == "Tailandia"


def test_normalize_cuisine_collapses_variants_and_places():
    cases = {
        "Perú Asia": "Perú", "Nikkei/Peruana": "Perú", "Nikkei (Perú/Japón)": "Perú",
        "Peruana (Arequipa)": "Perú", "Coreana Moderna": "Corea", "Japonesa Vegana": "Japón",
        "Japón/Francia": "Japón", "Italia/Fusión": "Italia", "Italoamericana": "Italia",
        "Francesa/Moderna": "Francia", "India / Indo-China": "India",
        "Andaluza Moderna": "España", "País Vasco": "España", "Londres": "Reino Unido",
        "Escocia": "Reino Unido", "París": "Francia", "Filadelfia": "Estados Unidos",
        "Alpes": "Italia", "<0xC2>  Italia": "Italia", "Internacional/Fusión": "Internacional",
        "Mediterránea": "Internacional", "Grecia": "Grecia", "Vietnam": "Vietnam",
        "Cuba": "Cuba", "Portugal": "Portugal", "Indonesia": "Indonesia",
    }
    for raw, expected in cases.items():
        assert normalize_cuisine(raw) == expected, raw


def test_unresolvable_cuisine_is_empty_so_course_fallback_applies():
    assert normalize_cuisine("[]") == ""
    assert normalize_cuisine("Receta") == ""


def test_validate_complete():
    src = "\n".join(["● a"] * 4 + ["● b"] * 4)
    r = recipe(ings=["a"] * 4, steps=["b"] * 4)
    out = validate_recipes([r], src, translated=False, course="focaccias")
    assert out["ratio"] == 1.0
    assert out["needs_review"] == 0
    assert r["needs_review"] is False


def test_validate_low_ratio_flags_all():
    src = "\n".join(["● x"] * 20)
    r = recipe(ings=["a"] * 2, steps=["b"] * 2)
    out = validate_recipes([r], src, translated=False, course="focaccias")
    assert out["ratio"] == 0.2
    assert r["needs_review"] is True
    assert any("incompleta" in x for x in r["review_reasons"])


def test_validate_relaxed_when_translated():
    src = "\n".join(["● x"] * 20)
    r = recipe(ings=["a"] * 2, steps=["b"] * 2)
    validate_recipes([r], src, translated=True, course="gnocchi")
    assert r["needs_review"] is False


def test_validate_empty_recipe_and_cuisine_and_garbage():
    r = recipe(ings=[], steps=["su䣫tamaño"], cocina="")
    validate_recipes([r], "", translated=False, course="cocina-india-festiva")
    assert r["needs_review"] is True
    assert r["cocina"] == "India"
    assert r["elaboraciones"][0]["pasos"] == ["su tamaño"]
