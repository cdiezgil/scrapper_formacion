"""
Scrapper para Scott's Bass Lessons en Teachable (scotts-bass-lessons.teachable.com)
  - Cursos Accelerators y Masterclasses especiales (Gary Willis, Fretboard, Technique, Practice...)
  - Player: Hotmart Video Player (HLS m3u8 con descifrado AES-128 nativo vía yt-dlp)
  - Vídeos: 1080p Full HD sin DRM Widevine
  - Materiales: Workbooks en PDF y audio tracks en ZIP / MP3
  - Sesión: Cookies persistidas en .teachable_cookies.json
"""
from __future__ import annotations
import json
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

BASE_URL = "https://scotts-bass-lessons.teachable.com"
SITE_ID = "teachable"
COOKIES_FILE = Path(".teachable_cookies.json")

# Catálogo de programas Accelerator conocidos del usuario
KNOWN_COURSES = {
    "515593": "The Gary Willis Masterclass",
    "754100": "The Bass Technique Accelerator Program - Third Enrollment",
    "1320709": "The Fretboard Accelerator - Second Enrollment",
    "801764": "The Practice Accelerator - Third Enrollment",
    "416534": "The Ultimate Bass Buyers Guide",
}


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
class TeachableLecture(BaseModel):
    id: str
    title: str
    url: str
    section: str = ""
    video_url: str | None = None
    materials: list[tuple[str, str]] = []  # (filename, url)

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'\s+', ' ', self.title).strip()
        clean = re.sub(r'[^\w\s-]', '', clean).strip().replace(' ', '_')
        return clean or f"lecture_{self.id}"


class TeachableCourse(BaseModel):
    id: str
    title: str
    url: str
    lectures: list[TeachableLecture] = []

    @property
    def safe_name(self) -> str:
        clean = re.sub(r'\s+', ' ', self.title).strip()
        clean = re.sub(r'[^\w\s-]', '', clean).strip().replace(' ', '_')
        return clean or f"course_{self.id}"


# --------------------------------------------------------------------------
# Clase principal
# --------------------------------------------------------------------------
class Teachable:
    def __init__(self, download_dir: Path | None = None, quality: str = "best"):
        self.download_dir = (download_dir or Path("./downloads")) / SITE_ID
        self.quality = quality
        self.cookies_list: list[dict] = []
        self._load_cookies()

    def _load_cookies(self) -> None:
        if COOKIES_FILE.exists():
            try:
                self.cookies_list = json.loads(COOKIES_FILE.read_text())
            except Exception:
                pass

    def check_auth(self) -> bool:
        if not self.cookies_list:
            console.print(
                "[red]Faltan cookies de Teachable.[/red]\n"
                "Inicia sesión en https://scotts-bass-lessons.teachable.com y copia la cookie a .teachable_cookies.json"
            )
            return False
        return True

    def _get_http_client(self) -> httpx.Client:
        cookies = {c["name"]: c["value"] for c in self.cookies_list}
        return httpx.Client(
            cookies=cookies,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Referer": f"{BASE_URL}/",
            },
            follow_redirects=True,
            timeout=30,
        )

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    def list_courses(self) -> list[TeachableCourse]:
        """Lista los cursos aceleradores matriculados."""
        if not self.check_auth():
            return []

        client = self._get_http_client()
        courses = []

        console.print(f"\n[bold]🎸 Programas Accelerator en Scott's Bass Lessons (Teachable):[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID / Slug", style="green", width=10)
        table.add_column("Programa / Masterclass", style="bold")
        table.add_column("Estado", justify="center")

        for cid, known_name in KNOWN_COURSES.items():
            url = f"{BASE_URL}/courses/enrolled/{cid}"
            try:
                r = client.get(url)
                if r.status_code == 200:
                    m_title = re.search(r"class=[\"']course-sidebar[\"'][^>]*>.*?<h2[^>]*>(.*?)</h2>", r.text, re.S)
                    title = re.sub(r"<[^>]+>", "", m_title.group(1)).strip() if m_title else known_name
                    courses.append(TeachableCourse(id=cid, title=title, url=url))
                    table.add_row(cid, title, "[green]Matriculado[/green]")
                else:
                    table.add_row(cid, known_name, "[dim]No disponible[/dim]")
            except Exception:
                table.add_row(cid, known_name, "[yellow]Error[/yellow]")

        client.close()
        console.print(table)
        return courses

    # ------------------------------------------------------------------
    # Detalles del curso
    # ------------------------------------------------------------------
    def get_course_detail(self, course_id: str) -> TeachableCourse:
        """Obtiene la lista completa de lecciones y secciones de un curso."""
        client = self._get_http_client()
        url = f"{BASE_URL}/courses/enrolled/{course_id}"
        r = client.get(url)
        client.close()

        if r.status_code != 200:
            raise RuntimeError(f"Error accediendo al curso {course_id} (Status {r.status_code})")

        m_title = re.search(r"class=[\"']course-sidebar[\"'][^>]*>.*?<h2[^>]*>(.*?)</h2>", r.text, re.S)
        title = re.sub(r"<[^>]+>", "", m_title.group(1)).strip() if m_title else KNOWN_COURSES.get(course_id, course_id)

        course = TeachableCourse(id=course_id, title=title, url=url)

        # Parsear secciones y lecciones desde el HTML
        raw_sections = re.findall(
            r"<div class=[\"']section-title[\"'][^>]*>(.*?)</div>\s*<ul[^>]*>(.*?)</ul>",
            r.text,
            re.S,
        )

        lectures = []
        for s_idx, (s_title_html, s_list_html) in enumerate(raw_sections, 1):
            sec_text = re.sub(r"<[^>]+>", "", s_title_html).strip()
            sec_clean = re.sub(r"Available in.*", "", sec_text, flags=re.S | re.I)
            sec_clean = sec_clean.replace("&nbsp;", "").replace("nbsp", "")
            sec_clean = re.sub(r"\s+", " ", sec_clean).strip()
            sec_folder = f"{s_idx:02d}_{re.sub(r'[^\w\s-]', '', sec_clean).strip().replace(' ', '_')}" if sec_clean else ""

            lecture_matches = re.findall(
                r"<a[^>]*href=[\"'](/courses/\d+/lectures/(\d+))[\"'][^>]*>.*?<span class=[\"']lecture-name[\"'][^>]*>(.*?)</span>",
                s_list_html,
                re.S,
            )
            for l_href, lid, l_title_html in lecture_matches:
                lt = re.sub(r"<[^>]+>", "", l_title_html).strip()
                lt = re.sub(r"\s+\d+:\d+\s*$", "", lt)
                lt = re.sub(r"\s+", " ", lt).strip()
                lectures.append(
                    TeachableLecture(
                        id=lid,
                        title=lt,
                        url=urljoin(BASE_URL, l_href),
                        section=sec_folder,
                    )
                )

        if not lectures:
            # Fallback simple para plantillas distintas
            all_links = re.findall(r"href=[\"'](/courses/\d+/lectures/(\d+))[\"']", r.text)
            seen = set()
            for l_href, lid in all_links:
                if lid not in seen:
                    seen.add(lid)
                    lectures.append(
                        TeachableLecture(
                            id=lid,
                            title=f"Lección {lid}",
                            url=urljoin(BASE_URL, l_href),
                        )
                    )

        course.lectures = lectures
        return course

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------
    def download_course(self, course_id: str, limit: int | None = None) -> None:
        """Descarga todas las lecciones (vídeos 1080p y materiales) de un curso de Teachable."""
        if not self.check_auth():
            return

        course = self.get_course_detail(course_id)
        course_dir = self.download_dir / course.safe_name
        course_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[bold cyan]📥 Descargando programa:[/bold cyan] {course.title}")
        console.print(f"   Destino: {course_dir}")
        console.print(f"   Lecciones: {len(course.lectures)}")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="es-ES",
            )
            context.add_cookies([
                {"name": c["name"], "value": c["value"], "domain": c.get("domain", "scotts-bass-lessons.teachable.com"), "path": "/"}
                for c in self.cookies_list
            ])
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            # Interceptar stream m3u8
            captured_m3u8 = []
            def handle_request(req):
                if any(k in req.url for k in ["master-pkg", "hls/master", "hls/video"]):
                    captured_m3u8.append(req.url)

            page.on("request", handle_request)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Lecciones", total=len(course.lectures))

                for idx, lecture in enumerate(course.lectures, 1):
                    if limit and idx > limit:
                        break

                    prefix = f"{idx:03d}"
                    progress.update(task, description=f"[{idx}/{len(course.lectures)}] {lecture.title[:35]}")

                    sec_prefix = f"{lecture.section}/" if lecture.section else ""
                    lesson_dir = course_dir / sec_prefix / f"{prefix}_{lecture.safe_name}"
                    lesson_dir.mkdir(parents=True, exist_ok=True)

                    # Navegar a la lección
                    captured_m3u8.clear()
                    try:
                        page.goto(lecture.url, wait_until="domcontentloaded")
                        page.wait_for_timeout(3500)
                    except Exception as e:
                        console.print(f"[yellow]  ⚠ Error abriendo {lecture.title}: {e}[/yellow]")
                        progress.advance(task)
                        continue

                    # 1. Descargar vídeo HLS en 1080p
                    if captured_m3u8:
                        video_m3u8 = captured_m3u8[0]
                        v_out = lesson_dir / f"{prefix}_{lecture.safe_name}"
                        success = download_video(
                            url=video_m3u8,
                            output_path=v_out,
                            bearer_token=None,
                            referer="https://player.hotmart.com/",
                            quality=self.quality,
                        )
                        if not success:
                            console.print(f"[yellow]  ⚠ No se pudo descargar vídeo: {lecture.title}[/yellow]")

                    # 2. Descargar materiales adjuntos (workbooks, ZIPs, audios)
                    materials = page.locator("a[href*='download'], a[href*='attachments'], a[href*='file_embeds'], a[href*='.pdf'], a[href*='.zip'], a[href*='.mp3']").evaluate_all("""
                        els => els.map(e => ({
                            name: e.innerText.replace(/\\s+/g, ' ').trim() || 'Material',
                            url: e.href
                        })).filter(x => x.url && !x.url.startsWith('javascript:'))
                    """)

                    for m in materials:
                        fname = unquote(m["url"].split("/")[-1].split("?")[0])
                        clean_fname = re.sub(r'[^\w\s.-]', '', fname).strip().replace(' ', '_')
                        if clean_fname:
                            download_file(
                                url=m["url"],
                                output_dir=lesson_dir,
                                filename=clean_fname,
                            )

                    progress.advance(task)

            browser.close()

        console.print(f"\n[green]✓ Programa completado:[/green] {course.title}")

    def download_all(self, limit: int | None = None) -> None:
        """Descarga todos los cursos matriculados en Teachable."""
        courses = self.list_courses()
        for c in courses:
            try:
                self.download_course(c.id, limit=limit)
            except Exception as e:
                console.print(f"[red]Error en curso {c.title}: {e}[/red]")
