"""Recipe photos: locate each recipe's dish photo in its PDF and cache a small JPEG.

Photos live in the cache (``<cache>/media/<course>/<slug>.jpg``), never in the vault, because
``render_collection`` wipes the output directory; render copies the ones the notes use.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import extract as ex
from .render import slugify

PDFIMAGES = "/opt/homebrew/bin/pdfimages"
SIPS = "/usr/bin/sips"
MIN_SIDE = 300       # smaller images are icons / decorations
MAX_ASPECT = 3       # wider/taller images are banners
MAX_SECTION_SHARE = 0.3  # a section photo spans at most this share of the pages
MAX_SIDE = 800       # output JPEG max side
JPEG_QUALITY = 80
TOP_LINES = 10       # a recipe title must appear among the first non-empty lines of a page
FUZZY = 0.8
_LEADER = re.compile(r"(\.{2,}|\s)\d{1,3}\s*$")  # "Title ..... 12": a table-of-contents line


@dataclass(frozen=True)
class ImageInfo:
    page: int    # 1-based
    num: int     # global row number in `pdfimages -list`
    obj: int     # PDF object id (repeated decorations share it)
    width: int
    height: int
    kind: str = "image"   # "image" | "smask" | ...
    index: int = 0        # position among ALL rows of its page (matches `pdfimages -png` order)

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class Assignment:
    title_page: int | None
    photo_page: int | None
    reason: str  # "ok" | "no_title_match" | "no_candidate"


def parse_image_list(text: str) -> list[ImageInfo]:
    rows: list[ImageInfo] = []
    seen: Counter[int] = Counter()
    for line in text.splitlines():
        f = line.split()
        if len(f) < 11 or not (f[0].isdigit() and f[1].isdigit() and f[3].isdigit()
                               and f[4].isdigit() and f[10].isdigit()):
            continue
        page = int(f[0])
        rows.append(ImageInfo(page=page, num=int(f[1]), obj=int(f[10]), width=int(f[3]),
                              height=int(f[4]), kind=f[2], index=seen[page]))
        seen[page] += 1
    return rows


def list_images(pdf: Path) -> list[ImageInfo]:
    exe = shutil.which("pdfimages") or PDFIMAGES
    res = subprocess.run([exe, "-list", str(pdf)], capture_output=True, check=True)
    return parse_image_list(res.stdout.decode("utf-8", errors="replace"))


def _is_section_photo(pages: set[int], n_pages: int) -> bool:
    """A dish photo repeated on the consecutive pages of its own section (one page per
    elaboration). Objects spread over the document or on most pages are decorations."""
    run = max(pages) - min(pages) + 1 == len(pages)
    return run and len(pages) <= max(1, int(n_pages * MAX_SECTION_SHARE))


def photo_candidates(images: list[ImageInfo], min_side: int = MIN_SIDE) -> dict[int, ImageInfo]:
    """Per page, the largest photo: an image unique to that page or, failing that, a section
    photo. Small images, banners and repeated decorations are skipped."""
    pages_of: dict[int, set[int]] = {}
    for i in images:
        if i.kind == "image":
            pages_of.setdefault(i.obj, set()).add(i.page)
    n_pages = max((i.page for i in images), default=0)
    best: dict[int, tuple[int, int, ImageInfo]] = {}
    for i in images:
        if i.kind != "image" or min(i.width, i.height) < min_side:
            continue
        if max(i.width, i.height) > MAX_ASPECT * min(i.width, i.height):
            continue
        pages = pages_of[i.obj]
        if len(pages) == 1:
            tier = 1
        elif _is_section_photo(pages, n_pages):
            tier = 0
        else:
            continue
        key = (tier, i.area)
        if i.page not in best or key > best[i.page][:2]:
            best[i.page] = (tier, i.area, i)
    return {page: entry[2] for page, entry in best.items()}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", slugify(text, 200).replace("-", " ")).strip()


def _top_lines(page: str) -> list[str]:
    return [ln for ln in page.splitlines() if ln.strip()][:TOP_LINES]


def _is_index(lines: list[str]) -> bool:
    return sum(1 for ln in lines if _LEADER.search(ln.strip())) >= 3


def find_recipe_page(title: str, pages: list[str]) -> int | None:
    """1-based page whose top lines carry ``title`` (accent/case/punctuation-insensitive)."""
    want = _norm(title)
    if not want:
        return None
    for n, page in enumerate(pages, 1):
        lines = _top_lines(page)
        if _is_index(lines):
            continue
        wrapped = [f"{x} {y}" for x, y in zip(lines, lines[1:])]  # titles wrapped over 2 lines
        for ln in lines + wrapped:
            got = _norm(ln)
            if not got:
                continue
            if got == want or (len(want) >= 4 and want in got and len(got) <= len(want) + 12):
                return n
            if difflib.SequenceMatcher(None, want, got).ratio() >= FUZZY:
                return n
    return None


def pick_photo_page(page: int, candidates: dict[int, ImageInfo], used: set[int],
                    n_pages: int) -> int | None:
    """The recipe's own page, else the next, else the previous. ``used`` holds object ids
    already assigned: the own page may reuse one (recipes of a section share its photo), a
    neighbouring page may not."""
    if page in candidates:
        return page
    for p in (page + 1, page - 1):
        if 1 <= p <= n_pages and p in candidates and candidates[p].obj not in used:
            return p
    return None


def assign_photos(titles: list[str], pages: list[str],
                  candidates: dict[int, ImageInfo]) -> list[Assignment]:
    n_pages = max([len(pages), *candidates] or [0])
    used: set[int] = set()
    out: list[Assignment] = []
    for t in titles:
        tp = find_recipe_page(t, pages)
        if tp is None:
            out.append(Assignment(None, None, "no_title_match"))
            continue
        pp = pick_photo_page(tp, candidates, used, n_pages)
        if pp is None:
            out.append(Assignment(tp, None, "no_candidate"))
            continue
        used.add(candidates[pp].obj)
        out.append(Assignment(tp, pp, "ok"))
    return out


def unique_slugs(titles: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for t in titles:
        s = slugify(t)
        seen[s] += 1
        out.append(s if seen[s] == 1 else f"{s}-{seen[s]}")
    return out


def extract_photo(pdf: Path, page: int, index: int, dest: Path) -> None:
    """Extract the ``index``-th image (smask rows counted) of ``page`` as a small JPEG."""
    exe = shutil.which("pdfimages") or PDFIMAGES
    with tempfile.TemporaryDirectory(prefix="scoolinary-photo-") as tmp:
        subprocess.run([exe, "-f", str(page), "-l", str(page), "-png", str(pdf),
                        str(Path(tmp) / "p")], capture_output=True, check=True)
        src = Path(tmp) / f"p-{index:03d}.png"
        if not src.exists():
            raise FileNotFoundError(f"image {index} of page {page} not extracted")
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part.jpg")
        subprocess.run([SIPS, "-Z", str(MAX_SIDE), "-s", "format", "jpeg",
                        "-s", "formatOptions", str(JPEG_QUALITY), str(src), "--out", str(part)],
                       capture_output=True, check=True)
        part.replace(dest)


def process_course(course: str, pdf: Path, cache_dir: Path, force: bool = False,
                   list_images: Callable[[Path], list[ImageInfo]] = list_images,
                   pdf_text: Callable[[Path], str] = ex.pdf_text,
                   extract_photo: Callable[[Path, int, int, Path], None] = extract_photo) -> str:
    """Find and cache the photos of one course. Returns 'ok', 'skipped' or 'error'."""
    from .pipeline import _atomic_write

    path = cache_dir / f"{course}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "skipped"
    if "error" in data or not data.get("recipes"):
        return "skipped"
    if data.get("fotos_done") and not force:
        return "skipped"
    try:
        recipes = data["recipes"]
        images = list_images(pdf)
        pages = ex.split_pages(pdf_text(pdf))
        cands = photo_candidates(images)
        titles = [r.get("titulo", "") for r in recipes]
        assigned = assign_photos(titles, pages, cands)
        slugs = unique_slugs(titles)
        media = cache_dir / "media" / course
        if media.exists():
            shutil.rmtree(media)
        for r, a, slug in zip(recipes, assigned, slugs):
            for k in ("foto", "foto_page", "foto_motivo"):
                r.pop(k, None)
            r["foto"] = None
            r["foto_motivo"] = a.reason
            if a.photo_page is None:
                continue
            rel = f"media/{course}/{slug}.jpg"
            (cache_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            extract_photo(pdf, a.photo_page, cands[a.photo_page].index, cache_dir / rel)
            r["foto"], r["foto_page"] = rel, a.photo_page
            r.pop("foto_motivo")
        data["fotos_done"] = True
        _atomic_write(path, data)
        return "ok"
    except Exception:  # one course failing must not stop the batch
        return "error"
