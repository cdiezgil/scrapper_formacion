import json
from pathlib import Path

import pytest

from src.sites.scoolinary_md import photos
from src.sites.scoolinary_md.photos import ImageInfo

LIST_SAMPLE = """\
page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
   1     0 image    1365  2048  rgb     3   8  jpeg   yes       12  0  1029  1029  205K 2.5%
   1     1 image    2347   500  rgb     3   8  jpeg   yes       15  0   927   927 48.2K 1.4%
   1     2 smask    2347   500  gray    1   8  image  no        15  0   927   927 15.9K 1.4%
   2     3 image    1365  2048  rgb     3   8  jpeg   yes       12  0  1029  1029  205K 2.5%
   2     4 image    2500  1667  rgb     3   8  jpeg   yes       27  0   326   326  262K 2.1%
   2     5 smask    2500  1667  gray    1   8  image  no        27  0   326   326  22.3K 2.0%
"""


def img(page, obj, w, h, index=0, kind="image"):
    return ImageInfo(page=page, num=0, obj=obj, width=w, height=h, kind=kind, index=index)


def test_parse_image_list():
    rows = photos.parse_image_list(LIST_SAMPLE)
    assert len(rows) == 6
    assert rows[4] == ImageInfo(page=2, num=4, obj=27, width=2500, height=1667,
                                kind="image", index=1)
    assert rows[5].kind == "smask"
    assert [r.index for r in rows if r.page == 1] == [0, 1, 2]


def test_parse_ignores_garbage():
    assert photos.parse_image_list("") == []
    assert photos.parse_image_list("Syntax Error: bad\n") == []


def test_candidates_drop_repeated_small_and_smask():
    rows = [
        img(1, 12, 1365, 2048), img(2, 12, 1365, 2048),      # repeated background
        img(2, 27, 2500, 1667, index=1),                      # unique photo
        img(2, 30, 200, 200, index=2),                        # unique but tiny
        img(3, 40, 1000, 900), img(3, 41, 1600, 1200, index=1),  # largest wins
        img(4, 50, 2000, 2000, kind="smask"),                 # smask ignored
    ]
    c = photos.photo_candidates(rows)
    assert set(c) == {2, 3}
    assert c[2].obj == 27
    assert c[3].obj == 41


def test_candidates_same_object_twice_on_one_page_counts_as_one_page():
    rows = [img(2, 27, 2500, 1667), img(2, 27, 2500, 1667, index=1)]
    assert photos.photo_candidates(rows)[2].obj == 27


PAGES = [
    "Índice\nFocaccia Genovese ........ 2\nFocaccia con Uva .... 3\nPizza Romana ..... 4\n"
    + "\n".join(["x"] * 12),
    "\n\n  FOCACCIA  GENOVESE\nIngredientes\n harina",
    "Focaccia con uvas\nIngredientes",
    "otra cosa\n" * 12 + "Pizza Romana",
]


def test_find_recipe_page_accent_case_punct_insensitive():
    assert photos.find_recipe_page("Focaccia Genovésé", PAGES) == 2


def test_find_recipe_page_ignores_index_pages_and_deep_lines():
    # page 1 is an index (dot-leader lines) and page 4 has the title at line 13
    assert photos.find_recipe_page("Pizza Romana", PAGES) is None


def test_find_recipe_page_fuzzy_and_contained():
    assert photos.find_recipe_page("Focaccia con Uva", PAGES) == 3
    assert photos.find_recipe_page("Cosa inexistente", PAGES) is None


def test_find_recipe_page_prefers_first_occurrence():
    pages = ["Tarta\nx", "Tarta\ny"]
    assert photos.find_recipe_page("Tarta", pages) == 1


def test_pick_photo_page_fallbacks():
    cands = {5: img(5, 1, 500, 500)}
    used: set[int] = set()
    assert photos.pick_photo_page(5, cands, used, 10) == 5
    assert photos.pick_photo_page(4, cands, set(), 10) == 5   # page+1
    assert photos.pick_photo_page(6, cands, set(), 10) == 5   # page-1
    assert photos.pick_photo_page(8, cands, set(), 10) is None
    assert photos.pick_photo_page(5, cands, {1}, 10) == 5     # own page may reuse
    assert photos.pick_photo_page(4, cands, {1}, 10) is None  # fallback never reuses


def test_pick_photo_page_prefers_own_then_next_then_previous():
    cands = {3: img(3, 1, 500, 500), 5: img(5, 2, 500, 500), 4: img(4, 3, 500, 500)}
    assert photos.pick_photo_page(4, cands, set(), 9) == 4
    assert photos.pick_photo_page(4, {k: v for k, v in cands.items() if k != 4}, {2}, 9) == 3


def test_assign_photos_in_order_without_reuse_and_reasons():
    titles = ["Focaccia Genovese", "Focaccia con Uva", "Nada", "Otra"]
    pages = ["x", "Focaccia Genovese", "Focaccia con Uva", "y"]
    cands = {2: img(2, 1, 500, 500)}
    res = photos.assign_photos(titles, pages, cands)
    assert res[0] == photos.Assignment(title_page=2, photo_page=2, reason="ok")
    # recipe 2 -> page 3: own none, page+1 none, page-1 = 2 is used
    assert res[1].photo_page is None and res[1].reason == "no_candidate"
    assert res[2].reason == "no_title_match" and res[2].title_page is None


def test_unique_slugs_dedupe():
    assert photos.unique_slugs(["Pan", "Pan", "Otro", "Pan"]) == ["pan", "pan-2", "otro", "pan-3"]


def test_process_course_with_fakes(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    path = cache / "c1.json"
    path.write_text(json.dumps({
        "course": "c1", "source_pdf": "x", "translated": False,
        "recipes": [{"titulo": "Focaccia Genovese"}, {"titulo": "Nada"}]}), encoding="utf-8")
    calls = []

    def extract(pdf, page, index, dest):
        calls.append((page, index))
        dest.write_bytes(b"jpg")

    status = photos.process_course(
        "c1", Path("/x.pdf"), cache,
        list_images=lambda pdf: photos.parse_image_list(LIST_SAMPLE),
        pdf_text=lambda pdf: "\f\n\nFocaccia Genovese\n",
        extract_photo=extract)
    assert status == "ok"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["fotos_done"] is True
    r0, r1 = data["recipes"]
    assert r0["foto"] == "media/c1/focaccia-genovese.jpg" and r0["foto_page"] == 2
    assert r1["foto"] is None and r1["foto_motivo"] == "no_title_match"
    assert (cache / "media/c1/focaccia-genovese.jpg").read_bytes() == b"jpg"
    assert calls == [(2, 1)]
    # resumable
    assert photos.process_course("c1", Path("/x.pdf"), cache, list_images=None,
                                 pdf_text=None, extract_photo=None) == "skipped"


def test_process_course_error_does_not_raise(tmp_path):
    cache = tmp_path
    (cache / "c.json").write_text(json.dumps(
        {"course": "c", "recipes": [{"titulo": "A"}]}), encoding="utf-8")

    def boom(pdf):
        raise RuntimeError("bad pdf")

    st = photos.process_course("c", Path("/x.pdf"), cache, list_images=boom,
                               pdf_text=lambda p: "", extract_photo=None)
    assert st == "error"


REAL = Path("/Volumes/Externo/formacion/scoolinary/_pdfs/focaccias/Recetario.pdf")


@pytest.mark.skipif(not REAL.exists(), reason="real PDF not available")
def test_real_focaccias_pdf(tmp_path):
    rows = photos.list_images(REAL)
    cands = photos.photo_candidates(rows)
    assert 2 in cands and cands[2].obj == 27
    dest = tmp_path / "a.jpg"
    photos.extract_photo(REAL, 2, cands[2].index, dest)
    assert dest.exists() and 0 < dest.stat().st_size < 400_000


def test_find_recipe_page_title_wrapped_over_two_lines():
    pages = ["x", "Luigi\nReceta\nFocaccia 80%\nhidratación\nIngredientes"]
    assert photos.find_recipe_page("Focaccia 80% hidratación", pages) == 2


def section(obj, pages, w=1575, h=2362):
    return [img(p, obj, w, h) for p in pages]


def test_section_photo_repeated_on_a_contiguous_run_is_a_candidate():
    rows = (section(14, range(1, 51))                       # background on every page
            + section(68, range(6, 12))                     # dish photo of one section
            + section(33, [2, 3, 5, *range(44, 51)], 2048, 801)  # scattered -> decoration
            + section(16, [1, 2, 3, 5], 1462, 264))         # banner -> decoration
    c = photos.photo_candidates(rows)
    assert set(c) == set(range(6, 12))
    assert {i.obj for i in c.values()} == {68}


def test_contiguous_object_on_most_pages_is_decoration():
    rows = section(12, range(1, 6)) + section(30, range(2, 6), 1001, 1118)
    assert photos.photo_candidates(rows) == {}


def test_page_unique_photo_beats_larger_section_photo():
    rows = section(68, range(6, 12)) + [img(7, 99, 800, 600, index=1)] + section(1, range(1, 40))
    assert photos.photo_candidates(rows)[7].obj == 99


def test_recipes_of_one_section_share_its_photo():
    titles = ["Espirales", "Rulos", "Base"]
    pages = ["x"] * 5 + ["Espirales", "Rulos", "Base"]
    cands = {p: img(p, 68, 1575, 2362) for p in (6, 7, 8)}
    res = photos.assign_photos(titles, pages, cands)
    assert [r.photo_page for r in res] == [6, 7, 8]
