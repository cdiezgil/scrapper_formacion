"""Deterministic rendering of cached recipes into a Markdown collection."""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .validate import cuisine_from_slug, normalize_cuisine

MARKER = ".scoolinary-md"
LABEL = "Recetario Scoolinary"
_NONE = "Sin clasificar"


class UnsafeOutputDir(Exception):
    """Refusing to wipe a directory that is not managed by this tool."""


def _fold(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _fold(text).lower()).strip("-")
    s = s[:max_len].strip("-")
    return s or "receta"


def humanize_course(slug: str) -> str:
    words = slug.replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def _q(value) -> str:
    """YAML scalar: JSON-style double-quoted strings are valid YAML."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def _yaml_list(key: str, items: list[str]) -> str:
    if not items:
        return f"{key}: []"
    return key + ":\n" + "\n".join(f"  - {_q(i)}" for i in items)


@dataclass
class Note:
    num: int
    recipe: dict
    course: str
    source_pdf: str
    translated: bool
    cuisine: str = ""
    slug: str = ""
    folder: str = ""
    filename: str = ""
    path: str = field(default="")  # relative to out: recipes/<folder>/<filename>
    photo: str | None = None  # relative to the media root, e.g. media/<course>/<slug>.jpg

    @property
    def title(self) -> str:
        return self.recipe.get("titulo") or "Receta sin título"

    @property
    def num_str(self) -> str:
        return f"{self.num:04d}"


def _rel(frm: Note, to: Note) -> str:
    if frm.folder == to.folder:
        return f"./{to.filename}"
    return f"../{to.folder}/{to.filename}"


def _build_notes(caches: list[dict], media_dir: Path | None = None) -> list[Note]:
    entries = []
    for c in sorted((c for c in caches if "error" not in c and c.get("recipes")),
                    key=lambda c: c.get("course", "")):
        for order, r in enumerate(c["recipes"]):
            cuisine = normalize_cuisine(r.get("cocina", "")) or cuisine_from_slug(c["course"])
            entries.append((slugify(cuisine), c["course"], order, cuisine, r, c))
    entries.sort(key=lambda e: (e[0], e[1], e[2]))
    notes = []
    for i, (cslug, _, _, cuisine, r, c) in enumerate(entries, 1):
        n = Note(i, r, c["course"], c.get("source_pdf", ""), bool(c.get("translated")), cuisine)
        n.slug = slugify(r.get("titulo", ""))
        n.folder = cslug
        n.filename = f"{n.num_str}-{n.slug}.md"
        n.path = f"recipes/{n.folder}/{n.filename}"
        foto = r.get("foto")
        if foto and media_dir is not None and (media_dir / foto).is_file():
            n.photo = foto
        notes.append(n)
    return notes


def _nav(n: Note, prev: Note | None, nxt: Note | None, up: str) -> str:
    parts = []
    if prev:
        parts.append(f"[⬅ Receta {prev.num_str}: {prev.title}]({_rel(n, prev)})")
    parts.append(f"[📖 {LABEL}]({up})")
    if nxt:
        parts.append(f"[Receta {nxt.num_str}: {nxt.title} ➡]({_rel(n, nxt)})")
    return " | ".join(parts)


def _render_note(n: Note, prev: Note | None, nxt: Note | None) -> str:
    r = n.recipe
    course_title = humanize_course(n.course)
    plato = r.get("tipo_plato") or ""
    reasons = r.get("review_reasons") or []
    photo_rel = f"../../{n.photo}" if n.photo else None
    fm = [
        "---",
        f"id: {n.num}",
        f"recipe_num: {_q(n.num_str)}",
        f"title: {_q(n.title)}",
        "year: null",
        'period: "Scoolinary"',
        f"cuisine: {_q(n.cuisine)}",
        f"family: {_q(plato or None)}",
        _yaml_list("course", [plato] if plato else []),
        _yaml_list("ingredients_tags", r.get("tags_ingredientes") or []),
        _yaml_list("apparatus", r.get("aparato") or []),
        f"servings: {_q(r.get('raciones') or None)}",
        "prep_time: null",
        "cook_time: null",
        f"source: {_q('Scoolinary — ' + course_title)}",
        "url: null",
        'origin: "Scoolinary"',
        f"images:\n  complete: {_q(photo_rel)}\n  detail: null",
        f"previous_recipe: {_q(_rel(n, prev) if prev else None)}",
        f"next_recipe: {_q(_rel(n, nxt) if nxt else None)}",
        f"chef: {_q(r.get('chef') or None)}",
        f"scoolinary_course: {_q(n.course)}",
        f"source_pdf: {_q(n.source_pdf)}",
        _yaml_list("diet", r.get("dieta") or []),
        f"needs_review: {_q(bool(r.get('needs_review')))}",
        _yaml_list("review_reasons", reasons),
        "---",
    ]
    nav = _nav(n, prev, nxt, "../../README.md")
    dash = "-"
    body = [
        "", nav, "", "---", "", f"# {n.num_str} · {n.title}", "",
        f"**Cocina:** {n.cuisine} · **Familia / Plato:** {plato or dash}  ",
        f"**Raciones:** {r.get('raciones') or dash}  ",
        f"**Ingrediente principal:** {r.get('ingrediente_principal') or dash} · "
        f"**Aparato:** {', '.join(r.get('aparato') or []) or dash}  ",
        "", "---", "",
    ]
    if photo_rel:
        body += ["## Galería", "", "| Fotografía |", "| :---: |",
                 f"| ![{n.title} - Fotografía]({photo_rel}) |", ""]
    body += ["## Elaboraciones", ""]
    elabs = r.get("elaboraciones") or []
    unnamed = 0
    for e in elabs:
        name = e.get("nombre") or ""
        if not name:
            unnamed += 1
            name = "Elaboración" if len([x for x in elabs if not x.get("nombre")]) == 1 \
                else f"Elaboración {unnamed}"
        body += [f"### {name}", "", "**Ingredientes**", ""]
        body += [f"- {i}" for i in e.get("ingredientes") or []] or ["- _(sin datos)_"]
        body += ["", "**Preparación**", ""]
        body += [f"{k}. {s}" for k, s in enumerate(e.get("pasos") or [], 1)] or ["_(sin datos)_"]
        body.append("")
    body += ["## Procedencia y Notas", ""]
    if r.get("chef"):
        body.append(f"- **Chef:** {r['chef']}")
    body.append(f"- **Curso:** {course_title}")
    body.append(f"- **PDF:** {n.source_pdf}")
    if r.get("dieta"):
        body.append(f"- **Dieta:** {', '.join(r['dieta'])}")
    if r.get("notas"):
        body.append(f"- **Notas:** {r['notas']}")
    if n.translated:
        body.append("- **Traducida:** sí, el PDF original no está en español")
    body.append("- **Origen de datos:** Scoolinary")
    if reasons:
        body += ["", f"> ⚠️ Revisar: {'; '.join(reasons)}"]
    body += ["", "", "---", "", nav, ""]
    return "\n".join(fm + body)


def _group_index(title: str, intro: str, groups: dict[str, list[Note]], extra: str,
                 extra_val) -> str:
    lines = [f"# {title}", "", f"[📖 Volver al {LABEL}](../README.md)", "", intro, "", "---", ""]
    for key in sorted(groups, key=lambda k: (k == _NONE, _fold(k).lower())):
        items = groups[key]
        lines += [f"## {key} ({len(items)} recetas)", "",
                  f"| # | Receta | Cocina | {extra} |", "| :--- | :--- | :--- | :--- |"]
        for n in items:
            lines.append(f"| {n.num_str} | [{n.title}](../{n.path}) | {n.cuisine} | "
                         f"{extra_val(n) or '-'} |")
        lines.append("")
    return "\n".join(lines)


def _indices(notes: list[Note]) -> dict[str, str]:
    def group(keyfn) -> dict[str, list[Note]]:
        g: dict[str, list[Note]] = {}
        for n in notes:
            for k in keyfn(n):
                g.setdefault(k, []).append(n)
        return g

    def one(field_name: str):
        return lambda n: [n.recipe.get(field_name) or _NONE]

    def many(field_name: str):
        return lambda n: n.recipe.get(field_name) or []

    plato = lambda n: n.recipe.get("tipo_plato") or "-"  # noqa: E731
    return {
        "por-cocina": _group_index("Índice de Recetas por Cocina y País",
                                   "Distribución geográfica y cultural.", group(lambda n: [n.cuisine]),
                                   "Plato", plato),
        "por-plato": _group_index("Índice de Recetas por Tipo de Plato",
                                  "Categorización por tipo de plato.", group(one("tipo_plato")),
                                  "Raciones", lambda n: n.recipe.get("raciones")),
        "por-ingrediente": _group_index("Índice de Recetas por Ingrediente Principal",
                                        "Clasificación según el ingrediente central.",
                                        group(one("ingrediente_principal")), "Plato", plato),
        "por-aparato": _group_index("Índice de Recetas por Aparato Culinario",
                                    "Electrodomésticos o métodos técnicos de cocción.",
                                    group(many("aparato")), "Plato", plato),
        "por-dieta": _group_index("Índice de Recetas por Tipo de Dieta",
                                  "Opciones vegetarianas, veganas, sin gluten, etc.",
                                  group(many("dieta")), "Plato", plato),
        "por-chef": _group_index("Índice de Recetas por Chef", "Chefs de los cursos.",
                                 group(one("chef")), "Plato", plato),
        "por-curso": _group_index("Índice de Recetas por Curso", "Cursos de Scoolinary.",
                                  group(lambda n: [humanize_course(n.course)]), "Plato", plato),
    }


def _readme(notes: list[Note]) -> str:
    with_photo = sum(1 for n in notes if n.photo)
    lines = [
        f"# Scoolinary · Recetario ({len(notes)} recetas)", "",
        f"📷 {with_photo} de {len(notes)} recetas con foto.", "",
        "> Recetas extraídas de los recetarios PDF de los cursos de Scoolinary, normalizadas "
        "con el estándar del Recetario Personal.", "", "---", "", "## 🧭 Índices Temáticos", "",
        "- [🌍 **Índice por Cocina / País**](./indices/por-cocina.md)",
        "- [🍽 **Índice por Tipo de Plato**](./indices/por-plato.md)",
        "- [🥩 **Índice por Ingrediente Principal**](./indices/por-ingrediente.md)",
        "- [⚡ **Índice por Aparato Culinario**](./indices/por-aparato.md)",
        "- [🥗 **Índice por Dieta**](./indices/por-dieta.md)",
        "- [👨‍🍳 **Índice por Chef**](./indices/por-chef.md)",
        "- [🎓 **Índice por Curso**](./indices/por-curso.md)", "", "---", "",
        "## 📊 Resumen por Cocinas", "",
        "| Cocina | Rango de Recetas | Total | Carpeta |", "| :--- | :---: | :---: | :--- |",
    ]
    by_folder: dict[str, list[Note]] = {}
    for n in notes:
        by_folder.setdefault(n.folder, []).append(n)
    for folder, items in by_folder.items():
        lines.append(f"| **{items[0].cuisine}** | Recetas {items[0].num_str} a "
                     f"{items[-1].num_str} | {len(items)} | [`recipes/{folder}/`]"
                     f"(./recipes/{folder}/) |")
    pending = [n for n in notes if n.recipe.get("needs_review")]
    lines += ["", "---", "", f"## ⚠️ Pendientes de revisión ({len(pending)})", ""]
    if pending:
        for n in pending:
            why = "; ".join(n.recipe.get("review_reasons") or [])
            lines.append(f"- [{n.num_str} · {n.title}](./{n.path}) — {why}")
    else:
        lines.append("Ninguna.")
    lines += ["", "---", "", f"## 📑 Catálogo Completo ({len(notes)} Recetas)", "",
              "| # | Receta | Cocina | Plato | Curso |", "| :--- | :--- | :--- | :--- | :--- |"]
    for n in notes:
        lines.append(f"| {n.num_str} | [{n.title}](./{n.path}) | {n.cuisine} | "
                     f"{n.recipe.get('tipo_plato') or '-'} | {humanize_course(n.course)} |")
    return "\n".join(lines) + "\n"


def _prepare_out(out: Path) -> None:
    if out.exists():
        if not out.is_dir():
            raise UnsafeOutputDir(f"{out} is not a directory")
        entries = list(out.iterdir())
        if entries and not (out / MARKER).exists():
            raise UnsafeOutputDir(
                f"{out} is not empty and has no {MARKER} marker; refusing to wipe it")
        for p in entries:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Managed by `scoolinary md`. Contents are regenerated.\n",
                              encoding="utf-8")


def render_collection(caches: list[dict], out: Path, media_dir: Path | None = None) -> int:
    """Wipe and regenerate ``out``. Returns the number of notes written.

    ``media_dir`` is the cache root holding ``media/<course>/*.jpg``; photos used by notes are
    copied to ``out/media/<course>/``.
    """
    notes = _build_notes(caches, media_dir)
    _prepare_out(out)
    for n in notes:
        if n.photo:
            dest = out / n.photo
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(media_dir / n.photo, dest)
    for i, n in enumerate(notes):
        prev = notes[i - 1] if i > 0 else None
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        target = out / n.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_note(n, prev, nxt), encoding="utf-8")
    (out / "indices").mkdir(exist_ok=True)
    for name, content in _indices(notes).items():
        (out / "indices" / f"{name}.md").write_text(content, encoding="utf-8")
    (out / "README.md").write_text(_readme(notes), encoding="utf-8")
    return len(notes)
