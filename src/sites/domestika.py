"""
Scrapper para Domestika (domestika.org)
  - Stack: Ruby on Rails + React/Next + CloudFront/Wistia HLS
  - Auth: Cookie-based (_domestika_session y _credentials)
  - Vídeos: HLS m3u8 directos en 1080p vía window.__INITIAL_PROPS__
  - Materiales: Recursos adjuntos y proyectos finales
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn

from ..core.downloader import download_video, download_file

console = Console()

BASE_URL = "https://www.domestika.org"
SITE_ID = "domestika"


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
class DomestikaVideo(BaseModel):
    title: str
    playback_url: str
    section: str = ""

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')
        return clean or "video"


class DomestikaUnit(BaseModel):
    title: str
    url: str
    videos: list[DomestikaVideo] = []
    materials: list[tuple[str, str]] = []  # (name, url)

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')
        return clean or "unidad"


class DomestikaCourse(BaseModel):
    title: str
    url: str
    units: list[DomestikaUnit] = []

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')
        return clean or "curso"


# --------------------------------------------------------------------------
# Clase principal
# --------------------------------------------------------------------------
class Domestika:
    def __init__(
        self,
        session_cookie: str | None = None,
        credentials_cookie: str | None = None,
        download_dir: Path | None = None,
        quality: str = "best",
    ):
        self.session_cookie = session_cookie or os.getenv("DOMESTIKA_SESSION", "")
        self.credentials_cookie = credentials_cookie or os.getenv("DOMESTIKA_CREDENTIALS", "")
        self.download_dir = (download_dir or Path("./downloads")) / SITE_ID
        self.quality = quality
        self._access_token: str | None = None

        if self.credentials_cookie:
            m = re.search(r'accessToken["\']?\s*:\s*["\']([^"\']+)["\']', unquote(self.credentials_cookie))
            if m:
                self._access_token = m.group(1)

    # ------------------------------------------------------------------
    # Autenticación / Verificación
    # ------------------------------------------------------------------
    def check_credentials(self) -> bool:
        if not self.session_cookie:
            console.print(
                "[red]Faltan credenciales de Domestika.[/red]\n"
                "Para descargar cursos de Domestika que hayas comprado:\n"
                "  1. Inicia sesión en [underline]https://www.domestika.org[/underline] desde tu navegador.\n"
                "  2. Abre F12 -> Almacenamiento/Storage -> Cookies -> domestika.org.\n"
                "  3. Copia el valor de [bold]_domestika_session[/bold] y [bold]_credentials[/bold].\n"
                "  4. Pégalos en tu fichero [bold].env[/bold]:\n"
                "     [green]DOMESTIKA_SESSION=tu_cookie_aqui[/green]\n"
                "     [green]DOMESTIKA_CREDENTIALS=tu_cookie_aqui[/green]"
            )
            return False
        return True

    def _get_browser_context(self, playwright_instance):
        browser = playwright_instance.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="es-ES",
        )
        # Inyectar cookies de sesión
        cookies = [
            {"name": "_domestika_session", "value": self.session_cookie, "domain": ".domestika.org", "path": "/"},
            {"name": "_domestika_session", "value": self.session_cookie, "domain": "www.domestika.org", "path": "/"},
        ]
        if self.credentials_cookie:
            cookies.append({"name": "_credentials", "value": self.credentials_cookie, "domain": ".domestika.org", "path": "/"})
            cookies.append({"name": "_credentials", "value": self.credentials_cookie, "domain": "www.domestika.org", "path": "/"})

        context.add_cookies(cookies)
        return browser, context

    # ------------------------------------------------------------------
    # Mapeo de curso
    # ------------------------------------------------------------------
    def get_course_detail(self, course_url_or_slug: str) -> DomestikaCourse:
        """Obtiene unidades, vídeos HLS y recursos de un curso."""
        from playwright.sync_api import sync_playwright

        if not course_url_or_slug.startswith("http"):
            course_url = f"{BASE_URL}/es/courses/{course_url_or_slug}"
        else:
            course_url = course_url_or_slug

        console.print(f"[dim]Analizando curso en Domestika: {course_url}…[/dim]")

        with sync_playwright() as p:
            browser, context = self._get_browser_context(p)
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            page.goto(course_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)

            title = page.title().split("|")[0].replace("Cursos online para creativos", "").strip()
            if not title or "ERROR" in title:
                h1 = page.locator("h1").all_text_contents()
                title = h1[0].strip() if h1 else course_url.split("/")[-1]

            # Buscar enlaces de unidades / lecciones
            unit_links = page.locator("h4.h2.unit-item__title a, a[href*='/units/'], a[href*='/lessons/']").evaluate_all("""
                els => els.map(e => ({
                    title: e.innerText.replace(/\\s+/g, ' ').trim(),
                    href: e.href
                })).filter(x => x.href && !x.href.includes('#'))
            """)

            # Deduplicar enlaces
            seen = set()
            units_data = []
            for u in unit_links:
                if u["href"] not in seen:
                    seen.add(u["href"])
                    units_data.append(u)

            if not units_data:
                # Comprobar si el curso mismo es una unidad directa
                units_data = [{"title": title, "href": course_url}]

            console.print(f"[green]✓ Encontradas {len(units_data)} unidades[/green]")

            course = DomestikaCourse(title=title, url=course_url)

            # Extraer vídeos y recursos de cada unidad
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Mapeando unidades", total=len(units_data))

                for u_idx, u_info in enumerate(units_data, 1):
                    progress.update(task, description=f"[{u_idx}/{len(units_data)}] {u_info['title'][:35]}")
                    page.goto(u_info["href"], wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    # 1. Extraer vídeos de __INITIAL_PROPS__
                    v_data = page.evaluate("""() => {
                        const props = window.__INITIAL_PROPS__ || {};
                        const videos = [];
                        if (props.videos && Array.isArray(props.videos)) {
                            for (const item of props.videos) {
                                if (item.video && item.video.playbackURL) {
                                    videos.push({
                                        title: item.video.title || item.title || 'Video',
                                        playback_url: item.video.playbackURL,
                                        section: item.section || ''
                                    });
                                }
                            }
                        }
                        return videos;
                    }""")

                    videos = [DomestikaVideo(**v) for v in v_data]

                    # 2. Extraer enlaces de descarga/recursos de la lección
                    materials = page.locator("a[href*='download'], a[href*='attachments'], a[href*='resources'], a[download]").evaluate_all("""
                        els => els.map(e => ({
                            name: e.innerText.replace(/\\s+/g, ' ').trim() || e.download || 'Recurso',
                            url: e.href
                        })).filter(x => x.url && !x.url.startsWith('javascript:'))
                    """)

                    unit = DomestikaUnit(
                        title=u_info["title"],
                        url=u_info["href"],
                        videos=videos,
                        materials=[(m["name"], m["url"]) for m in materials],
                    )
                    course.units.append(unit)
                    progress.advance(task)

            browser.close()
            return course

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------
    def download_course(
        self,
        course_url_or_slug: str,
        limit: int | None = None,
    ) -> None:
        """Descarga todas las unidades, vídeos en 1080p y materiales del curso."""
        if not self.check_credentials():
            return

        course = self.get_course_detail(course_url_or_slug)
        course_dir = self.download_dir / course.safe_name
        course_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[bold cyan]📥 Descargando curso Domestika:[/bold cyan] {course.title}")
        console.print(f"   Destino: {course_dir}")

        total_videos = sum(len(u.videos) for u in course.units)
        console.print(f"   Total vídeos: {total_videos} en {len(course.units)} unidades")

        downloaded_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Descargando", total=total_videos or 1)

            for u_idx, unit in enumerate(course.units, 1):
                unit_dir = course_dir / f"{u_idx:02d}_{unit.safe_name}"
                unit_dir.mkdir(parents=True, exist_ok=True)

                # Descargar vídeos
                for v_idx, video in enumerate(unit.videos, 1):
                    if limit and downloaded_count >= limit:
                        console.print(f"[dim]Límite alcanzado ({limit} vídeos).[/dim]")
                        return

                    progress.update(task, description=f"[{downloaded_count+1}/{total_videos}] {video.title[:35]}")
                    v_out = unit_dir / f"{v_idx:02d}_{video.safe_name}"

                    success = download_video(
                        url=video.playback_url,
                        output_path=v_out,
                        bearer_token=None,
                        referer=f"{BASE_URL}/",
                        quality=self.quality,
                    )
                    if success:
                        downloaded_count += 1
                    else:
                        console.print(f"[yellow]  ⚠ No se pudo descargar vídeo: {video.title}[/yellow]")

                    progress.advance(task)

                # Descargar materiales
                for m_name, m_url in unit.materials:
                    clean_m = re.sub(r'[^\w\s.-]', '', m_name).strip().replace(' ', '_')
                    download_file(
                        url=m_url,
                        output_dir=unit_dir,
                        filename=clean_m,
                    )

        console.print(f"\n[green]✓ Curso completado:[/green] {course.title}")
