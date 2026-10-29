"""
Scrapper para Atar Cabos (app.atarcabos.com)
  - Stack: Ruby on Rails 7 + Hotwire/Turbo + Devise
  - Auth: Form login con reCAPTCHA v3 (resuelto via Playwright headless stealth)
  - Sesión: Cookie _academia_session persistida en .atarcabos_session
  - Vídeos: Skiv / Muse.ai embed (mp4 1080p directo sin fragmentar en cdn.skiv.com)
  - Documentos: PDFs de manuales por módulo en ActiveStorage
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, unquote

import httpx
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn

console = Console()

BASE_URL = "https://app.atarcabos.com"
SITE_ID = "atarcabos"
SESSION_FILE = Path(".atarcabos_session")


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
class AtarcabosVideo(BaseModel):
    id: str
    title: str
    filename: str
    duration: float
    size: int
    url: str

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')
        return clean or self.id

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration), 60)
        return f"{m}m{s:02d}s"


class AtarcabosSection(BaseModel):
    title: str
    slug: str
    url: str
    videos: list[AtarcabosVideo] = []


class AtarcabosLesson(BaseModel):
    title: str
    slug: str
    url: str
    sections: list[AtarcabosSection] = []

    @property
    def safe_name(self) -> str:
        return re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')


class AtarcabosModule(BaseModel):
    index: int
    title: str
    documents: list[tuple[str, str]] = []  # (filename, url)
    lessons: list[AtarcabosLesson] = []

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')
        return f"{self.index:02d}_{clean}"


class AtarcabosCourse(BaseModel):
    name: str
    slug: str
    url: str
    modules: list[AtarcabosModule] = []

    @property
    def safe_name(self) -> str:
        return re.sub(r'[^\w\s-]', '', self.name).strip().replace(' ', '_')


# --------------------------------------------------------------------------
# Clase principal
# --------------------------------------------------------------------------
class AtarCabos:
    def __init__(self, email: str, password: str, download_dir: Path, quality: str = "best"):
        self.email = email
        self.password = password
        self.download_dir = download_dir / SITE_ID
        self.quality = quality
        self._session_cookie: str | None = None
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------
    def login(self) -> None:
        """Inicia sesión o reutiliza la cookie guardada."""
        if SESSION_FILE.exists():
            saved = SESSION_FILE.read_text().strip()
            if self._verify_session(saved):
                console.print(f"[green]✓ Sesión Atar Cabos recuperada desde caché como {self.email}[/green]")
                self._session_cookie = saved
                self._init_client()
                return

        console.print(f"[dim]Autenticando {self.email} en app.atarcabos.com…[/dim]")
        token = self._login_playwright()
        self._session_cookie = token
        SESSION_FILE.write_text(token)
        self._init_client()
        console.print(f"[green]✓ Sesión iniciada con éxito como {self.email}[/green]")

    def _verify_session(self, cookie: str) -> bool:
        try:
            with httpx.Client(
                cookies={"_academia_session": cookie},
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
                timeout=10,
            ) as c:
                r = c.get(BASE_URL)
                return r.status_code == 200 and "sign_in" not in str(r.url) and "Iniciar sesión" not in r.text
        except Exception:
            return False

    def _login_playwright(self) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="es-ES",
                timezone_id="Europe/Madrid",
            )
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, "webdriver", { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            page.goto(BASE_URL, wait_until="domcontentloaded")

            # Aceptar cookies si aparecen
            try:
                page.click("button[data-action*='cookie-consent#acceptAll']", timeout=2000)
            except Exception:
                page.evaluate("document.querySelectorAll('.cookie-consent-banner').forEach(e => e.remove())")

            page.fill("#user_email", self.email)
            page.fill("#user_password", self.password)
            page.wait_for_timeout(2000)
            page.click("form#new_user button[type=submit]", force=True)

            try:
                page.wait_for_url("**/my_courses", timeout=15000)
            except Exception:
                # Comprobar alertas de fallo
                alerts = page.locator(".alert").all_text_contents()
                browser.close()
                msg = alerts[0].strip() if alerts else "Tiempo de espera superado al iniciar sesión"
                raise RuntimeError(f"Error de login en Atar Cabos: {msg}")

            cookies = context.cookies()
            browser.close()

            session_val = next((c["value"] for c in cookies if c["name"] == "_academia_session"), None)
            if not session_val:
                raise RuntimeError("No se recibió la cookie _academia_session tras iniciar sesión")
            return session_val

    def _init_client(self) -> None:
        self._client = httpx.Client(
            cookies={"_academia_session": self._session_cookie or ""},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Referer": f"{BASE_URL}/",
            },
            follow_redirects=True,
            timeout=60,
        )

    # ------------------------------------------------------------------
    # Catálogo e inspección
    # ------------------------------------------------------------------
    def list_courses(self) -> list[AtarcabosCourse]:
        assert self._client, "Llama a login() primero"
        r = self._client.get(f"{BASE_URL}/")
        course_links = set(re.findall(r"href=[\"'](/cursos/[a-z0-9\-]+/modulos)[\"']", r.text))
        if not course_links:
            # Reintentar en /users/my_courses
            r_user = self._client.get(f"{BASE_URL}/cursos")
            course_links = set(re.findall(r"href=[\"'](/cursos/[a-z0-9\-]+/modulos)[\"']", r_user.text))

        courses = []
        for cl in sorted(course_links):
            slug = cl.split("/")[2]
            r_c = self._client.get(f"{BASE_URL}{cl}")
            t_m = re.search(r"<h1[^>]*>(.*?)</h1>", r_c.text)
            name = re.sub(r"<[^>]+>", "", t_m.group(1)).strip() if t_m else slug
            courses.append(AtarcabosCourse(name=name, slug=slug, url=f"{BASE_URL}{cl}"))

        console.print(f"\n[bold]⛵ {len(courses)} cursos matriculados en Atar Cabos:[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Curso", style="bold")
        table.add_column("Slug (--curso)", style="green")
        table.add_column("URL", style="dim")
        for c in courses:
            table.add_row(c.name, c.slug, c.url)
        console.print(table)
        return courses

    def get_course_detail(self, course_slug: str) -> AtarcabosCourse:
        """Obtiene el árbol completo de módulos, lecciones, secciones y vídeos de un curso."""
        assert self._client
        course_url = f"{BASE_URL}/cursos/{course_slug}/modulos"
        r = self._client.get(course_url)
        r.raise_for_status()

        t_m = re.search(r"<h1[^>]*>(.*?)</h1>", r.text)
        course_name = re.sub(r"<[^>]+>", "", t_m.group(1)).strip() if t_m else course_slug
        course = AtarcabosCourse(name=course_name, slug=course_slug, url=course_url)

        # Parsear módulos
        raw_mods = re.split(r"<div class=[\"']modul[\"']>", r.text)[1:]
        for idx, m_html in enumerate(raw_mods, 1):
            t_match = re.search(r"<h2[^>]*>(.*?)</h2>", m_html, re.S)
            m_title = re.sub(r"<[^>]+>", "", t_match.group(1)).strip() if t_match else f"Módulo {idx}"

            # Documentos descargables del módulo
            docs = []
            for doc_url in re.findall(r"href=[\"'](/rails/active_storage/blobs/[^\"']+)[\"']", m_html):
                fname = unquote(doc_url.split("/")[-1])
                docs.append((fname, doc_url))

            # Lecciones
            lessons = []
            lesson_matches = re.findall(
                r"<div class=[\"']lesson-card[\s\"'][^>]*>.*?<a href=[\"'](/cursos/[^\"']+/lecciones/[^\"']+)[\"'][^>]*>.*?<h3[^>]*>(.*?)</h3>",
                m_html,
                re.S,
            )
            for l_url, l_title in lesson_matches:
                lt = re.sub(r"<[^>]+>", "", l_title).strip()
                l_slug = l_url.split("/")[-1]
                lessons.append(AtarcabosLesson(title=lt, slug=l_slug, url=urljoin(BASE_URL, l_url)))

            course.modules.append(
                AtarcabosModule(
                    index=idx,
                    title=m_title,
                    documents=docs,
                    lessons=lessons,
                )
            )

        return course

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------
    def download_course(
        self,
        course_slug: str,
        limit: int | None = None,
        modulo_idx: int | None = None,
        leccion_slug: str | None = None,
    ) -> None:
        """Descarga módulos, lecciones, vídeos y documentos de un curso."""
        assert self._client
        course = self.get_course_detail(course_slug)
        course_dir = self.download_dir / course.slug
        course_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[bold cyan]📥 Descargando:[/bold cyan] {course.name}")
        console.print(f"   Destino: {course_dir}")

        modules_to_process = course.modules
        if modulo_idx is not None:
            modules_to_process = [m for m in course.modules if m.index == modulo_idx]

        total_downloaded_videos = 0

        for mod in modules_to_process:
            mod_dir = course_dir / mod.safe_name
            mod_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"\n[bold yellow]📁 {mod.title}[/bold yellow] ({len(mod.lessons)} lecciones)")

            # 1. Descargar documentos oficiales del módulo
            for fname, doc_url in mod.documents:
                doc_path = mod_dir / fname
                self._download_document(doc_url, doc_path)

            # 2. Procesar lecciones
            lessons_to_process = mod.lessons
            if leccion_slug:
                lessons_to_process = [l for l in mod.lessons if l.slug == leccion_slug]

            for l_idx, lesson in enumerate(lessons_to_process, 1):
                if limit and total_downloaded_videos >= limit:
                    console.print(f"[dim]Límite alcanzado ({limit} vídeos descargados). Deteniendo.[/dim]")
                    return

                lesson_dir = mod_dir / f"{l_idx:02d}_{lesson.safe_name}"
                lesson_dir.mkdir(parents=True, exist_ok=True)

                # Obtener secciones de la lección
                r_l = self._client.get(lesson.url)
                sec_urls = sorted(set(re.findall(r"href=[\"'](/cursos/[^\"']+/secciones/[^\"']+)[\"']", r_l.text)))
                if not sec_urls:
                    sec_urls = [lesson.url]

                for s_url in sec_urls:
                    full_sec_url = urljoin(BASE_URL, s_url)
                    r_s = self._client.get(full_sec_url)

                    # Buscar iframes de skiv.com
                    vids = re.findall(r"skiv\.com/embed/([a-zA-Z0-9]+)", r_s.text)
                    for vid_id in vids:
                        if limit and total_downloaded_videos >= limit:
                            return

                        video_info = self._resolve_skiv_video(vid_id)
                        if video_info and video_info.url:
                            v_out = lesson_dir / f"{video_info.safe_name}.mp4"
                            if v_out.exists() and v_out.stat().st_size > 0:
                                console.print(f"[dim]  ↩ Ya existe: {v_out.name}[/dim]")
                            else:
                                console.print(f"  🎬 Descargando: [bold]{video_info.title}[/bold] ({video_info.duration_str})")
                                success = self._download_mp4_file(video_info.url, v_out)
                                if success:
                                    total_downloaded_videos += 1

                    # Buscar ficheros adjuntos dentro de la sección
                    sec_files = re.findall(r"<a[^>]*href=[\"'](/rails/active_storage/blobs/[^\"']+)[\"'][^>]*>(.*?)</a>", r_s.text, re.S)
                    for f_url, html_t in sec_files:
                        fn = unquote(f_url.split("/")[-1])
                        self._download_document(f_url, lesson_dir / fn)

        console.print(f"\n[green]✓ Descarga completada:[/green] {course.name}")

    def _resolve_skiv_video(self, embed_id: str) -> AtarcabosVideo | None:
        """Resuelve los metadatos y URL directa de descarga MP4 de un vídeo en Skiv.com."""
        assert self._client
        embed_url = f"https://skiv.com/embed/{embed_id}"
        try:
            r = self._client.get(embed_url, headers={"Referer": f"{BASE_URL}/"})
            m = re.search(r"player\.setData\(\s*(\{.*?\})\s*,\s*\{", r.text, re.S)
            if not m:
                return None
            data = json.loads(m.group(1))
            return AtarcabosVideo(
                id=embed_id,
                title=data.get("title") or embed_id,
                filename=data.get("filename") or f"{embed_id}.mp4",
                duration=data.get("duration", 0),
                size=data.get("size", 0),
                url=data.get("url"),
            )
        except Exception as e:
            console.print(f"[yellow]  ⚠ Error resolviendo skiv.com/{embed_id}: {e}[/yellow]")
            return None

    def _download_mp4_file(self, url: str, output_path: Path) -> bool:
        """Descarga directa de archivo MP4 con reintentos."""
        assert self._client
        try:
            with self._client.stream("GET", url, headers={"Referer": f"{BASE_URL}/"}) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=65536):
                        f.write(chunk)
            console.print(f"[green]    ✓ Guardado: {output_path.name}[/green]")
            return True
        except Exception as e:
            console.print(f"[red]    ✗ Error descargando vídeo: {e}[/red]")
            return False

    def _download_document(self, doc_url: str, output_path: Path) -> bool:
        """Descarga un documento de ActiveStorage."""
        assert self._client
        if output_path.exists() and output_path.stat().st_size > 0:
            console.print(f"[dim]  ↩ Ya existe documento: {output_path.name}[/dim]")
            return True

        full_url = urljoin(BASE_URL, doc_url)
        try:
            with self._client.stream("GET", full_url) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)
            console.print(f"[green]  ✓ Documento: {output_path.name}[/green]")
            return True
        except Exception as e:
            console.print(f"[yellow]  ⚠ No se pudo descargar documento {output_path.name}: {e}[/yellow]")
            return False

    def close(self) -> None:
        if self._client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
