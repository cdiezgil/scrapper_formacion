"""
Scrapper para Scoolinary (scoolinary.com)
  - Stack: WordPress + LearnDash LMS + BuddyBoss App REST API
  - Catálogo: 460+ cursos en español vía /wp-json/scoolinary-app/v1/courses
  - Lecciones y detalles: /wp-json/scoolinary-app/v1/courses/<id>/details y /lessons/<id>
  - Vídeos: Streams adaptativos HLS de Vimeo Pro (hasta 4K UHD con audio multilingüe)
  - Materiales: Recetarios y manuales oficiales en PDF (media.scoolinary.app)
  - Auth: Opcional vía JWT (/wp-json/buddyboss-app/auth/v2/jwt/login)
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from urllib.parse import unquote

import httpx
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn

from ..core.downloader import download_video, download_file

console = Console()

BASE_URL = "https://www.scoolinary.com"
API_BASE = f"{BASE_URL}/wp-json/scoolinary-app/v1"
AUTH_API = f"{BASE_URL}/wp-json/buddyboss-app/auth/v2/jwt/login"
SITE_ID = "scoolinary"


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
class ScoolinaryCourse(BaseModel):
    id: int
    title: str
    slug: str
    link: str
    total_lessons: int = 0

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')
        return clean or self.slug


class ScoolinaryLesson(BaseModel):
    id: int
    title: str
    slug: str
    menu_order: int = 0
    stream_url: str | None = None
    files: list[tuple[str, str]] = []  # (filename, url)

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')
        return clean or self.slug


# --------------------------------------------------------------------------
# Clase principal
# --------------------------------------------------------------------------
class Scoolinary:
    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        download_dir: Path | None = None,
        quality: str = "best",
        lang: str = "es",
    ):
        self.email = email or os.getenv("SCOOLINARY_EMAIL")
        self.password = password or os.getenv("SCOOLINARY_PASSWORD")
        self.download_dir = (download_dir or Path("./downloads")) / SITE_ID
        self.quality = quality
        self.lang = lang
        self.token: str | None = None

        self._client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"{BASE_URL}/",
            },
            follow_redirects=True,
            timeout=30,
        )

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------
    def login(self) -> None:
        """Inicia sesión con JWT si hay credenciales configuradas."""
        if not self.email or not self.password:
            console.print("[dim]Accediendo a Scoolinary sin credenciales (catálogo abierto)…[/dim]")
            return

        console.print(f"[dim]Autenticando {self.email} en Scoolinary…[/dim]")
        try:
            r = self._client.post(
                AUTH_API,
                json={"username": self.email, "password": self.password, "wpml_language": self.lang},
            )
            data = r.json()
            if r.status_code == 200 and "access_token" in data:
                self.token = data["access_token"]
                self._client.headers["Authorization"] = f"Bearer {self.token}"
                console.print(f"[green]✓ Sesión JWT iniciada en Scoolinary como {self.email}[/green]")
            else:
                msg = data.get("message") or f"Status {r.status_code}"
                console.print(f"[yellow]⚠ Aviso de login ({msg}). Continuando con acceso estándar.[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠ Error conectando a login de Scoolinary: {e}. Continuando.[/yellow]")

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    def list_courses(
        self,
        search: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[ScoolinaryCourse]:
        """Obtiene y lista los cursos disponibles en Scoolinary."""
        params = {
            "per_page": per_page,
            "page": page,
            "wpml_language": self.lang,
        }
        if search:
            params["search"] = search

        r = self._client.get(f"{API_BASE}/courses", params=params)
        r.raise_for_status()

        total = r.headers.get("x-wp-total", "?")
        courses = []
        for c in r.json():
            title = c.get("title", {}).get("rendered", "")
            title = re.sub(r"<[^>]+>", "", title).strip()
            courses.append(
                ScoolinaryCourse(
                    id=c["id"],
                    title=title,
                    slug=c.get("slug", ""),
                    link=c.get("link", ""),
                )
            )

        console.print(f"\n[bold]🍳 Cursos de Scoolinary ({len(courses)} mostrados de {total} totales):[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=8)
        table.add_column("Curso", style="bold")
        table.add_column("Slug (--curso)", style="green")

        for c in courses:
            table.add_row(str(c.id), c.title, c.slug)

        console.print(table)
        return courses

    # ------------------------------------------------------------------
    # Detalles del curso
    # ------------------------------------------------------------------
    def get_course_detail(self, slug_or_id: str | int) -> tuple[ScoolinaryCourse, list[ScoolinaryLesson]]:
        """Resuelve el curso y todas sus lecciones con URLs de stream y recetarios."""
        # 1. Obtener objeto del curso
        course_obj = None
        if str(slug_or_id).isdigit():
            r_c = self._client.get(f"{API_BASE}/courses/{slug_or_id}?wpml_language={self.lang}")
            if r_c.status_code == 200:
                c_data = r_c.json()
                t = re.sub(r"<[^>]+>", "", c_data.get("title", {}).get("rendered", "")).strip()
                course_obj = ScoolinaryCourse(id=c_data["id"], title=t, slug=c_data.get("slug", ""), link=c_data.get("link", ""))
        else:
            # Buscar por slug
            r_s = self._client.get(f"{API_BASE}/courses?slug={slug_or_id}&wpml_language={self.lang}")
            if r_s.status_code == 200 and r_s.json():
                c_data = r_s.json()[0]
                t = re.sub(r"<[^>]+>", "", c_data.get("title", {}).get("rendered", "")).strip()
                course_obj = ScoolinaryCourse(id=c_data["id"], title=t, slug=c_data.get("slug", ""), link=c_data.get("link", ""))

        if not course_obj:
            raise RuntimeError(f"Curso no encontrado en Scoolinary: {slug_or_id}")

        # 2. Obtener lecciones desde details
        r_d = self._client.get(f"{API_BASE}/courses/{course_obj.id}/details?wpml_language={self.lang}")
        r_d.raise_for_status()
        details = r_d.json()
        raw_lessons = details.get("lessons", [])
        course_obj.total_lessons = len(raw_lessons)

        lessons = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Inspeccionando lecciones", total=len(raw_lessons))

            for idx, rl in enumerate(raw_lessons, 1):
                lid = rl.get("id")
                ltitle = rl.get("title") or f"Lección {idx}"
                progress.update(task, description=f"[{idx}/{len(raw_lessons)}] {ltitle[:35]}")

                # Obtener detalles completos de la lección
                r_l = self._client.get(f"{API_BASE}/lessons/{lid}?wpml_language={self.lang}")
                stream_url = None
                files = []

                if r_l.status_code == 200:
                    l_data = r_l.json()
                    rendered = l_data.get("content", {}).get("rendered", "")

                    # Extraer vídeo de Vimeo/Scoolinary player
                    vm = re.search(r"player\.scoolinary\.com/playv\.html\?vid=(\d+)&(?:amp;)?s=([a-f0-9]+)", rendered)
                    if vm:
                        vid, s = vm.group(1), vm.group(2)
                        stream_url = f"https://player.vimeo.com/external/{vid}.m3u8?s={s}"

                    # Extraer PDFs (recetarios y documentos adjuntos sin duplicados)
                    seen_urls = set()
                    for f_match in re.findall(r'<a[^>]*href=[\"\'](https://media\.scoolinary\.app/[^\"\'\s]+\.pdf)[\"\'][^>]*>(.*?)</a>', rendered, re.I):
                        pdf_url, pdf_txt = f_match
                        if pdf_url in seen_urls:
                            continue
                        pdf_name = re.sub(r"<[^>]+>", "", pdf_txt).strip()
                        if not pdf_name or "Descarga" in pdf_name:
                            pdf_name = unquote(pdf_url.split("/")[-1])
                        if not pdf_name.lower().endswith(".pdf"):
                            pdf_name += ".pdf"
                        files.append((pdf_name, pdf_url))
                        seen_urls.add(pdf_url)

                lessons.append(
                    ScoolinaryLesson(
                        id=lid,
                        title=ltitle,
                        slug=rl.get("slug") or str(lid),
                        menu_order=idx,
                        stream_url=stream_url,
                        files=files,
                    )
                )
                progress.advance(task)

        return course_obj, lessons

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------
    def download_course(
        self,
        course_slug_or_id: str | int,
        limit: int | None = None,
        leccion_slug: str | None = None,
    ) -> None:
        """Descarga todos los vídeos y recetarios de un curso de Scoolinary."""
        course, lessons = self.get_course_detail(course_slug_or_id)
        course_dir = self.download_dir / course.slug
        course_dir.mkdir(parents=True, exist_ok=True)

        lessons_to_process = lessons
        if leccion_slug:
            lessons_to_process = [l for l in lessons if l.slug == leccion_slug or str(l.id) == leccion_slug]
            if not lessons_to_process:
                console.print(f"[red]Lección no encontrada en {course.title}: {leccion_slug}[/red]")
                return
        elif limit and limit > 0:
            lessons_to_process = lessons_to_process[:limit]

        console.print(f"\n[bold cyan]📥 Descargando curso:[/bold cyan] {course.title}")
        console.print(f"   Destino: {course_dir}")
        console.print(f"   Lecciones a descargar: {len(lessons_to_process)} (de {len(lessons)})")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Lecciones", total=len(lessons_to_process))

            for idx, lesson in enumerate(lessons_to_process, 1):
                orig_idx = lesson.menu_order or idx
                prefix = f"{orig_idx:03d}"
                progress.update(task, description=f"[{idx}/{len(lessons_to_process)}] {lesson.title[:40]}")

                # Carpeta de la lección (plana: vídeo y materiales juntos)
                lesson_dir = course_dir / f"{prefix}_{lesson.safe_name}"
                lesson_dir.mkdir(parents=True, exist_ok=True)

                # 1. Descargar vídeo si existe
                if lesson.stream_url:
                    out = lesson_dir / f"{prefix}_{lesson.safe_name}"
                    success = download_video(
                        url=lesson.stream_url,
                        output_path=out,
                        bearer_token=None,
                        referer=f"{BASE_URL}/",
                        quality=self.quality,
                    )
                    if not success:
                        console.print(f"[yellow]  ⚠ No se pudo descargar vídeo: {lesson.title}[/yellow]")
                else:
                    console.print(f"[dim]  ℹ Sin vídeo: {lesson.title}[/dim]")

                # 2. Descargar recetarios y materiales adjuntos
                for fname, furl in lesson.files:
                    download_file(
                        url=furl,
                        output_dir=lesson_dir,
                        filename=fname,
                        prefix=None,
                        http_client=self._client,
                    )

                progress.advance(task)

        console.print(f"[green]✓ Curso completado:[/green] {course.title}")

    def close(self) -> None:
        if self._client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
