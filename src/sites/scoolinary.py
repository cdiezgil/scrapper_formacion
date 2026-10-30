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
                self.user_id = data.get("user_id")
                self.user_name = data.get("user_display_name", self.email)
                self._client.headers["Authorization"] = f"Bearer {self.token}"
                console.print(f"[green]✓ Sesión JWT iniciada en Scoolinary como {self.user_name} (ID: {self.user_id})[/green]")
            else:
                msg = data.get("message") or f"Status {r.status_code}"
                console.print(f"[yellow]⚠ Aviso de login ({msg}). Continuando con acceso estándar.[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠ Error conectando a login de Scoolinary: {e}. Continuando.[/yellow]")

    # ------------------------------------------------------------------
    # Catálogo y Área Privada
    # ------------------------------------------------------------------
    def get_my_profile(self) -> dict | None:
        """Obtiene el perfil del usuario autenticado."""
        if not self.token:
            return None
        try:
            r = self._client.get(f"{BASE_URL}/wp-json/buddyboss/v1/members/me")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def list_my_courses(self) -> list[ScoolinaryCourse]:
        """Obtiene los cursos favoritos y guardados del usuario autenticado (área privada)."""
        if not self.token or not self.user_id:
            console.print("[yellow]Faltan credenciales en .env (SCOOLINARY_EMAIL y SCOOLINARY_PASSWORD) para ver tu área privada.[/yellow]")
            return []

        console.print(f"[bold]👤 Alumno:[/bold] {self.user_name} (ID: {self.user_id})")

        # 1. Obtener cursos favoritos de la cuenta
        fav_courses = []
        try:
            r_fav = self._client.get(f"{API_BASE}/mixed-content/favorites")
            if r_fav.status_code == 200:
                items = r_fav.json().get("items", [])
                for item in items:
                    if item.get("content_type") == "course":
                        t = item.get("title", {}).get("rendered", "")
                        t = re.sub(r"<[^>]+>", "", t).strip()
                        fav_courses.append(
                            ScoolinaryCourse(
                                id=item["id"],
                                title=t,
                                slug=item.get("slug", str(item["id"])),
                                link=item.get("link", ""),
                            )
                        )
        except Exception:
            pass

        if fav_courses:
            console.print(f"\n[bold]⭐ Tus cursos favoritos guardados ({len(fav_courses)} cursos):[/bold]")
            table_fav = Table(show_header=True, header_style="bold cyan")
            table_fav.add_column("ID", style="dim", width=8)
            table_fav.add_column("Curso Favorito", style="bold")
            table_fav.add_column("Slug (--curso)", style="green")
            for c in fav_courses:
                table_fav.add_row(str(c.id), c.title, c.slug)
            console.print(table_fav)

        # 2. Obtener catálogo general asignado a su suscripción
        try:
            r_all = self._client.get(
                f"{BASE_URL}/wp-json/buddyboss-app/learndash/v1/courses?user_id={self.user_id}&wpml_language={self.lang}&per_page=20"
            )
            if r_all.status_code == 200:
                total_avail = r_all.headers.get("x-wp-total", "460+")
                console.print(f"\n[bold green]✓ Suscripción activa:[/bold green] Acceso completo a los [bold]{total_avail} cursos[/bold] de Scoolinary.")
        except Exception:
            pass

        return fav_courses

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
                    # Primero buscar en content_native (más fiable para lecciones sin contenido renderizado)
                    raw_html = rendered
                    for cn in l_data.get("content_native", []):
                        if isinstance(cn, dict):
                            raw_html += " " + cn.get("render", "") + " " + str(cn.get("data", {}))

                    seen_urls = set()
                    for f_match in re.findall(r'<a[^>]*href=[\"\'](https://media\.scoolinary\.app/[^\"\'\s]+\.pdf)[\"\'][^>]*>(.*?)</a>', raw_html, re.I):
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

                    # Si hay múltiples PDFs en un solo idioma (ej: ES), filtrar los de otros idiomas
                    if len(files) > 1:
                        es_files = [(n, u) for n, u in files if re.search(r"[-_/]ES[-_.]|ES[-_.]|espa[nñ]ol", u, re.I)]
                        if es_files:
                            files = es_files
                        else:
                            # Excluir EN, DE, FR, IT, PT si no hay ES
                            non_other = [(n, u) for n, u in files if not re.search(r"[-_/](EN|DE|FR|IT|PT)[-_.]", u, re.I)]
                            if non_other:
                                files = non_other

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

    def download_top_courses(self, count: int = 50, per_course_limit: int | None = None) -> None:
        """Descarga los primeros N cursos del catálogo de Scoolinary secuencialmente."""
        console.print(f"\n[bold cyan]🍳 Obteniendo los primeros {count} cursos de Scoolinary en español...[/bold cyan]")

        all_courses: list[ScoolinaryCourse] = []
        page = 1
        while len(all_courses) < count:
            batch = self.list_courses(page=page, per_page=min(50, count - len(all_courses)))
            if not batch:
                break
            all_courses.extend(batch)
            page += 1

        all_courses = all_courses[:count]
        console.print(f"\n[bold green]✓ {len(all_courses)} cursos listados para descargar.[/bold green]")

        for idx, course in enumerate(all_courses, 1):
            console.print(f"\n[bold yellow]({idx}/{len(all_courses)}) Descargando curso:[/bold yellow] [bold]{course.title}[/bold] ({course.slug})")
            try:
                self.download_course(course.slug, limit=per_course_limit)
            except Exception as e:
                console.print(f"[red]⚠ Error descargando curso {course.title}: {e}. Continuando con el siguiente.[/red]")

    def download_from_file(self, file_path: Path | str, limit_courses: int | None = None, per_course_limit: int | None = None) -> None:
        """Descarga los cursos listados en un fichero markdown o de texto (extrae slugs de la tabla)."""
        p = Path(file_path)
        if not p.exists():
            console.print(f"[red]Fichero no encontrado: {file_path}[/red]")
            return

        text = p.read_text(encoding="utf-8")
        # Extraer slugs de la columna slug en tablas markdown
        slugs = re.findall(r"\| `([a-z0-9\-]+)` \| [^|]+ \| [^|]+ \|", text)
        if not slugs:
            slugs = re.findall(r"\| `([a-z0-9\-]+)` \|", text)

        seen = set()
        distinct_slugs = [s for s in slugs if not (s in seen or seen.add(s))]

        if limit_courses and limit_courses > 0:
            distinct_slugs = distinct_slugs[:limit_courses]

        console.print(f"\n[bold cyan]🍳 Descargando {len(distinct_slugs)} cursos seleccionados desde {p.name}...[/bold cyan]")

        for idx, slug in enumerate(distinct_slugs, 1):
            console.print(f"\n[bold yellow]({idx}/{len(distinct_slugs)}) Procesando curso:[/bold yellow] [bold]{slug}[/bold]")
            try:
                self.download_course(slug, limit=per_course_limit)
            except Exception as e:
                console.print(f"[red]⚠ Error en curso {slug}: {e}. Continuando con el siguiente.[/red]")

    def download_all_pdfs(self, file_path: Path | str) -> None:
        """Descarga exclusivamente los PDFs de los cursos listados (recetarios, guías, etc.).
        
        Si un curso tiene PDFs en varios idiomas, descarga solo los de Español.
        Si solo tiene PDFs en otro idioma, los descarga también (por compatibilidad).
        """
        p = Path(file_path)
        if not p.exists():
            console.print(f"[red]Fichero no encontrado: {file_path}[/red]")
            return

        text = p.read_text(encoding="utf-8")
        # Extraer slugs de la columna slug en tablas markdown
        slugs = re.findall(r"\| `([a-z0-9\-]+)` \|", text)
        seen = set()
        distinct_slugs = [s for s in slugs if not (s in seen or seen.add(s))]

        console.print(f"\n[bold cyan]📚 Extrayendo PDFs en español de {len(distinct_slugs)} cursos listados en {p.name}...[/bold cyan]")

        pdf_dir = self.download_dir / "_pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Procesando cursos", total=len(distinct_slugs))
            
            for idx, slug in enumerate(distinct_slugs, 1):
                progress.update(task, description=f"[{idx}/{len(distinct_slugs)}] {slug[:35]}")
                try:
                    # Obtener detalles de curso (sin imprimir tabla)
                    course_obj = None
                    r_s = self._client.get(f"{API_BASE}/courses?slug={slug}&wpml_language={self.lang}")
                    if r_s.status_code == 200 and r_s.json():
                        c_data = r_s.json()[0]
                        t = re.sub(r"<[^>]+>", "", c_data.get("title", {}).get("rendered", "")).strip()
                        course_obj = ScoolinaryCourse(id=c_data["id"], title=t, slug=c_data.get("slug", ""), link=c_data.get("link", ""))
                    
                    if not course_obj:
                        progress.advance(task)
                        continue

                    # Crear carpeta específica para este curso
                    c_dir = pdf_dir / slug
                    c_dir.mkdir(parents=True, exist_ok=True)

                    # Obtener lecciones
                    r_d = self._client.get(f"{API_BASE}/courses/{course_obj.id}/details?wpml_language={self.lang}")
                    if r_d.status_code != 200:
                        progress.advance(task)
                        continue
                    
                    raw_lessons = r_d.json().get("lessons", [])
                    found_any_pdf = False

                    # Revisar cada lección en busca de PDFs
                    for rl in raw_lessons:
                        lid = rl.get("id")
                        r_l = self._client.get(f"{API_BASE}/lessons/{lid}?wpml_language={self.lang}")
                        if r_l.status_code != 200:
                            continue
                        
                        l_data = r_l.json()
                        raw_html = l_data.get("content", {}).get("rendered", "")
                        for cn in l_data.get("content_native", []):
                            if isinstance(cn, dict):
                                raw_html += " " + cn.get("render", "") + " " + str(cn.get("data", {}))
                        
                        urls = list(set(re.findall(r"https?://media\.scoolinary\.app/[^\s\"'<>]+\.pdf", raw_html, re.I)))
                        
                        if len(urls) > 1:
                            es_urls = [u for u in urls if re.search(r"[-_/]ES[-_.]|ES[-_.]|espa[nñ]ol", u, re.I)]
                            if es_urls:
                                urls = es_urls
                            else:
                                non_other = [u for u in urls if not re.search(r"[-_/](EN|DE|FR|IT|PT)[-_.]", u, re.I)]
                                if non_other:
                                    urls = non_other

                        for pdf_url in urls:
                            found_any_pdf = True
                            # Nombre base: usar el título de la lección
                            lt = rl.get("title", "Documento")
                            lt_clean = re.sub(r"[^\w\s-]", "", lt).strip().replace(" ", "_")
                            ext = unquote(pdf_url.split("/")[-1]).split("/")[-1]
                            fname = f"{lt_clean}_{ext}" if len(urls) > 1 else f"{lt_clean}.pdf"
                            if not fname.lower().endswith(".pdf"):
                                fname += ".pdf"

                            # Eliminar duplicados de extensión
                            if ext.lower().endswith(".pdf"):
                                fname = fname.replace(f"_{ext}.pdf", ".pdf")

                            target_path = c_dir / fname
                            if target_path.exists() and target_path.stat().st_size > 0:
                                continue

                            download_file(
                                url=pdf_url,
                                output_dir=c_dir,
                                filename=fname,
                                prefix=None,
                                http_client=self._client,
                            )

                    if not found_any_pdf:
                        c_dir.rmdir()  # Eliminar carpeta vacía si no se encontró nada

                except Exception as e:
                    console.print(f"[yellow]⚠ Error procesando curso {slug}: {e}[/yellow]")

                progress.advance(task)

        console.print(f"\n[green]✓ Todos los PDFs extraídos y guardados en:[/green] {pdf_dir}")

    def close(self) -> None:
        if self._client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
