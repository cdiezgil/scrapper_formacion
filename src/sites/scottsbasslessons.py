"""
Scrapper para Scott's Bass Lessons (scottsbasslessons.com)
  - Stack: Craft CMS + Vue.js frontend + Gumlet video
  - Auth: Playwright (reCAPTCHA v3 + CSRF protection)
  - Vídeos: Gumlet HLS (hasta 1440p 2K)
  - Materiales: S3 (PDFs, ZIPs con audio tracks)
  - Sesión: Cookies caching (.scottsbass_cookies.json)
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

from ..core.downloader import download_video, download_file

console = Console()

BASE_URL = "https://scottsbasslessons.com"
SITE_ID = "scottsbasslessons"
COOKIES_FILE = Path(".scottsbass_cookies.json")

MOTOWN_MASTERS_FILES = [
    ("MoMashupLesson1.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson1.zip"),
    ("MoMashupLesson2.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson2.zip"),
    ("MoMashupLesson3.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson3.zip"),
    ("MoMashupLesson4.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson4.zip"),
    ("MoMashupLesson5.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson5.zip"),
    ("MoMashupLesson6.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson6.zip"),
    ("MoMashupLesson7.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson7.zip"),
    ("MoMashupLesson8.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupLesson8.zip"),
    ("MoMashupFinalThoughts.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MoMashupFinalThoughts.zip"),
    ("MotownMastersLiveSession1.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MotownMastersLiveSession1.zip"),
    ("MotownMastersLiveSession2.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MotownMastersLiveSession2.zip"),
    ("MotownMastersLiveSession3.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/MotownMastersLiveSession3.zip"),
    ("Play Alongs.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/Play+Alongs.zip"),
    ("Workbooks.zip", "https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/Workbooks.zip"),
]


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
class SBLVideo(BaseModel):
    embed_url: str
    title: str

    @property
    def safe_name(self) -> str:
        return re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')


class SBLMaterial(BaseModel):
    title: str
    url: str
    filename: str

    @property
    def safe_name(self) -> str:
        return re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')


class SBLLesson(BaseModel):
    title: str
    slug: str
    url: str
    video: SBLVideo | None = None
    materials: list[SBLMaterial] = []

    @property
    def safe_name(self) -> str:
        return re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')


class SBLCourse(BaseModel):
    title: str
    slug: str
    url: str
    lessons: list[SBLLesson] = []

    @property
    def safe_name(self) -> str:
        return re.sub(r'[^\w\s-]', '', self.title).strip().replace(' ', '_')


# --------------------------------------------------------------------------
# Clase principal
# --------------------------------------------------------------------------
class ScottsBassLessons:
    def __init__(self, email: str, password: str, download_dir: Path, quality: str = "best"):
        self.email = email
        self.password = password
        self.download_dir = download_dir / SITE_ID
        self.quality = quality
        self._cookies: dict | None = None
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------
    def login(self) -> None:
        """Inicia sesión usando Playwright y guarda las cookies."""
        if COOKIES_FILE.exists():
            try:
                with open(COOKIES_FILE) as f:
                    cookies_list = json.load(f)
                self._cookies = {c["name"]: c["value"] for c in cookies_list}
                if self._verify_session():
                    console.print(f"[green]✓ Sesión Scott's Bass Lessons recuperada como {self.email}[/green]")
                    self._init_client()
                    return
            except Exception:
                pass

        console.print(f"[dim]Autenticando {self.email} en scottsbasslessons.com…[/dim]")
        self._login_playwright()
        self._init_client()
        console.print(f"[green]✓ Sesión iniciada con éxito[/green]")

    def _verify_session(self) -> bool:
        try:
            with httpx.Client(
                cookies=self._cookies,
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
                timeout=10,
            ) as c:
                r = c.get(f"{BASE_URL}/")
                return r.status_code == 200 and "login" not in str(r.url)
        except Exception:
            return False

    def _login_playwright(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, "webdriver", { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Dismiss cookie banner
            try:
                page.click("button:has-text(\"Yeah, I\x27m cool!\")", timeout=2000)
            except Exception:
                pass

            # Fill login form using JS
            page.evaluate(f"""() => {{
                document.querySelector(\x27#loginName\x27).value = \x27{self.email}\x27;
                document.querySelector(\x27#password\x27).value = \x27{self.password}\x27;
            }}""")
            page.evaluate("""() => {
                document.querySelector(\x27#loginName\x27).dispatchEvent(new Event(\x27input\x27, { bubbles: true }));
                document.querySelector(\x27#password\x27).dispatchEvent(new Event(\x27input\x27, { bubbles: true }));
            }""")

            page.click("button:has-text(\x27Login\x27)")
            page.wait_for_timeout(5000)

            # Verify login success
            if "login" in page.url:
                body_text = page.locator("body").inner_text()
                if "locked" in body_text.lower():
                    browser.close()
                    raise RuntimeError("Cuenta bloqueada temporalmente. Espera 5 minutos.")
                browser.close()
                raise RuntimeError("Login fallido: credenciales incorrectas")

            # Save all cookies
            cookies = context.cookies()
            COOKIES_FILE.write_text(json.dumps(cookies))
            self._cookies = {c["name"]: c["value"] for c in cookies}
            browser.close()

    def _init_client(self) -> None:
        self._client = httpx.Client(
            cookies=self._cookies,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Referer": f"{BASE_URL}/",
            },
            follow_redirects=True,
            timeout=60,
        )

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    def list_courses(self) -> list[SBLCourse]:
        """Obtiene la lista de cursos disponibles."""
        assert self._client, "Llama a login() primero"
        
        # Use Playwright to get course list (Vue.js rendered)
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            # Load cookies
            with open(COOKIES_FILE) as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            
            page = context.new_page()
            page.goto(f"{BASE_URL}/courses", wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            
            # Get course links
            links = page.locator("a").evaluate_all("""
                els => els.map(e => ({text: e.innerText.replace(/\\s+/g, " ").trim(), href: e.href}))
                          .filter(x => x.href.includes("/courses/") && x.text && !x.text.includes("NEW RELEASE"))
            """)
            
            # Deduplicate and create course objects
            seen = set()
            courses = []
            for l in links:
                slug = l["href"].split("/courses/")[-1].rstrip("/")
                if slug and slug not in seen:
                    seen.add(slug)
                    courses.append(SBLCourse(
                        title=l["text"],
                        slug=slug,
                        url=l["href"]
                    ))
            
            browser.close()
        
        # Añadir curso especial Motown Masters
        courses.append(
            SBLCourse(
                title="Motown Masters: Mo's Muted Mashup (Danny Mo) [Vídeos HD + Audio + Workbooks]",
                slug="motown-masters",
                url="https://s3.amazonaws.com/bassbootcamps/MosMutedMashup/",
            )
        )
        
        console.print(f"\n[bold]🎸 {len(courses)} cursos disponibles en Scott's Bass Lessons:[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", justify="right", style="dim", width=4)
        table.add_column("Curso", style="bold")
        table.add_column("Slug (--curso)", style="green")
        
        for i, c in enumerate(courses, 1):
            table.add_row(str(i), c.title, c.slug)
        
        console.print(table)
        return courses

    # ------------------------------------------------------------------
    # Detalles del curso
    # ------------------------------------------------------------------
    def get_course_detail(self, slug: str) -> SBLCourse:
        """Obtiene las lecciones y vídeos de un curso específico."""
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            with open(COOKIES_FILE) as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            
            page = context.new_page()
            
            # Go to course page
            course_url = f"{BASE_URL}/courses/{slug}"
            page.goto(course_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            
            # Get course title
            title = page.title().replace("Courses: ", "").replace(" – Scott's Bass Lessons", "")
            
            # Get lesson links
            lesson_links = page.locator("a").evaluate_all("""
                els => els.map(e => ({text: e.innerText.replace(/\\s+/g, " ").trim(), href: e.href}))
                          .filter(x => x.href.includes("/lessons/") && x.text)
            """)
            
            # Deduplicate lessons
            seen = set()
            lessons = []
            for l in lesson_links:
                lesson_slug = l["href"].split("/lessons/")[-1].rstrip("/")
                if lesson_slug and lesson_slug not in seen:
                    seen.add(lesson_slug)
                    lessons.append(SBLLesson(
                        title=l["text"],
                        slug=lesson_slug,
                        url=l["href"]
                    ))
            
            browser.close()
            
            return SBLCourse(title=title, slug=slug, url=course_url, lessons=lessons)

    def get_lesson_detail(self, lesson: SBLLesson) -> SBLLesson:
        """Obtiene el vídeo y materiales de una lección."""
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            with open(COOKIES_FILE) as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            
            page = context.new_page()
            page.goto(lesson.url, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            
            # Find Gumlet video embed
            content = page.content()
            gumlet_match = re.search(r"https://vimeo\.gumlet\.io/embed/[^\"\s&]+", content)
            if gumlet_match:
                lesson.video = SBLVideo(
                    embed_url=gumlet_match.group(0),
                    title=lesson.title
                )
            
            # Find download links (S3)
            download_links = page.locator("a").evaluate_all("""
                els => els.map(e => ({text: e.innerText.replace(/\\s+/g, " ").trim(), href: e.href}))
                          .filter(x => x.href.includes("sblinsider.s3") || x.href.match(/\\.(pdf|zip|mp3|gp|gpx)$/i))
            """)
            
            for l in download_links:
                # Extract filename from URL
                url_path = unquote(l["href"].split("/")[-1])
                filename = re.sub(r'[^\w\s.-]', '', url_path).strip()
                lesson.materials.append(SBLMaterial(
                    title=l["text"],
                    url=l["href"],
                    filename=filename
                ))
            
            browser.close()
            
            return lesson

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------
    def download_course(self, course_slug: str, limit: int | None = None) -> None:
        """Descarga materiales o curso completo de SBL."""
        if course_slug in ["motown-masters", "motown", "danny-mo", "mos-muted-mashup"]:
            return self.download_motown_masters()

        console.print(f"\n[bold cyan]📥 Descargando materiales del curso:[/bold cyan] {course_slug}")
        
        course = self.get_course_detail(course_slug)
        course_dir = self.download_dir / course.slug
        course_dir.mkdir(parents=True, exist_ok=True)
        
        console.print(f"   Título: {course.title}")
        console.print(f"   Lecciones: {len(course.lessons)}")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Lecciones", total=len(course.lessons))
            
            for idx, lesson in enumerate(course.lessons, 1):
                if limit and idx > limit:
                    break
                
                progress.update(task, description=f"[{idx}/{len(course.lessons)}] {lesson.title[:40]}")
                
                # Get lesson details (materials only, skip video)
                lesson = self.get_lesson_detail(lesson)

                # Create lesson directory
                lesson_dir = course_dir / f"{idx:03d}_{lesson.safe_name}"
                lesson_dir.mkdir(parents=True, exist_ok=True)
                
                # Download materials only (skip DRM video)
                for mat in lesson.materials:
                    download_file(
                        url=mat.url,
                        output_dir=lesson_dir,
                        filename=mat.filename,
                        prefix=None,
                        http_client=self._client,
                    )
                
                progress.advance(task)
        
        console.print(f"[green]✓ Materiales descargados:[/green] {course.title}")

    def download_motown_masters(self) -> None:
        """Descarga y extrae el curso completo Motown Masters (Mo's Muted Mashup de Danny Mo)."""
        import zipfile
        import shutil

        course_dir = self.download_dir / "motown-masters-danny-mo"
        course_dir.mkdir(parents=True, exist_ok=True)
        zips_dir = course_dir / "_zips"
        zips_dir.mkdir(parents=True, exist_ok=True)

        console.print("\n[bold cyan]📥 Descargando curso Motown Masters (Mo's Muted Mashup - Danny Mo)...[/bold cyan]")
        console.print(f"   Destino: {course_dir}")
        console.print(f"   Ficheros: {len(MOTOWN_MASTERS_FILES)} paquetes ZIP (~5.5 GB Vídeos HD, Workbooks y Play Alongs)")

        client = httpx.Client(timeout=180, follow_redirects=True)

        # 1. Descargar ficheros ZIP
        for filename, url in MOTOWN_MASTERS_FILES:
            dest_zip = zips_dir / filename
            if dest_zip.exists() and dest_zip.stat().st_size > 0:
                console.print(f"[dim]  ↩ Ya existe paquete: {filename}[/dim]")
                continue

            console.print(f"  📦 Descargando paquete: [bold]{filename}[/bold]…")
            try:
                with client.stream("GET", url) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    dl_bytes = 0
                    with open(dest_zip, "wb") as f:
                        for chunk in r.iter_bytes(chunk_size=65536):
                            f.write(chunk)
                            dl_bytes += len(chunk)
                console.print(f"[green]    ✓ Descargado: {filename} ({dl_bytes / 1024 / 1024:.1f} MB)[/green]")
            except Exception as e:
                console.print(f"[red]    ✗ Error descargando {filename}: {e}[/red]")

        client.close()

        # 2. Descomprimir y estructurar por lecciones
        console.print("\n[bold yellow]📂 Descomprimiendo y estructurando lecciones de Motown Masters...[/bold yellow]")

        # A. Extraer lecciones de vídeo (1 a 8)
        for i in range(1, 9):
            lesson_dir = course_dir / f"00{i}_Lesson_{i}"
            lesson_dir.mkdir(parents=True, exist_ok=True)
            zip_path = zips_dir / f"MoMashupLesson{i}.zip"
            if zip_path.exists():
                try:
                    with zipfile.ZipFile(zip_path) as z:
                        for item in z.infolist():
                            if not item.filename.startswith("__MACOSX") and item.filename.endswith(".mp4"):
                                target = lesson_dir / f"00{i}_Lesson_{i}.mp4"
                                if not target.exists():
                                    with z.open(item) as src, open(target, "wb") as dst:
                                        shutil.copyfileobj(src, dst)
                                    console.print(f"[green]  ✓ Vídeo HD: {target.name}[/green]")
                except Exception as e:
                    console.print(f"[yellow]  ⚠ Error extrayendo vídeo de {zip_path.name}: {e}[/yellow]")

        # B. Final Thoughts
        ft_dir = course_dir / "009_Final_Thoughts"
        ft_dir.mkdir(parents=True, exist_ok=True)
        ft_zip = zips_dir / "MoMashupFinalThoughts.zip"
        if ft_zip.exists():
            try:
                with zipfile.ZipFile(ft_zip) as z:
                    for item in z.infolist():
                        if not item.filename.startswith("__MACOSX") and item.filename.endswith(".mp4"):
                            target = ft_dir / "009_Final_Thoughts.mp4"
                            if not target.exists():
                                with z.open(item) as src, open(target, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
                                console.print(f"[green]  ✓ Vídeo HD: {target.name}[/green]")
            except Exception as e:
                console.print(f"[yellow]  ⚠ Error extrayendo Final Thoughts: {e}[/yellow]")

        # C. Live Sessions 1, 2, 3
        for ls_idx in range(1, 4):
            ls_dir = course_dir / f"0{9+ls_idx:02d}_Live_Session_{ls_idx}"
            ls_dir.mkdir(parents=True, exist_ok=True)
            ls_zip = zips_dir / f"MotownMastersLiveSession{ls_idx}.zip"
            if ls_zip.exists():
                try:
                    with zipfile.ZipFile(ls_zip) as z:
                        for item in z.infolist():
                            if not item.filename.startswith("__MACOSX") and item.filename.endswith(".mp4"):
                                target = ls_dir / f"0{9+ls_idx:02d}_Live_Session_{ls_idx}.mp4"
                                if not target.exists():
                                    with z.open(item) as src, open(target, "wb") as dst:
                                        shutil.copyfileobj(src, dst)
                                    console.print(f"[green]  ✓ Vídeo HD: {target.name}[/green]")
                except Exception as e:
                    console.print(f"[yellow]  ⚠ Error extrayendo Live Session {ls_idx}: {e}[/yellow]")

        # D. Workbooks (PDFs correspondientes a cada lección)
        wb_zip = zips_dir / "Workbooks.zip"
        if wb_zip.exists():
            try:
                with zipfile.ZipFile(wb_zip) as z:
                    for item in z.infolist():
                        if not item.filename.startswith("__MACOSX") and item.filename.endswith(".pdf"):
                            m = re.search(r"L#(\d+)", item.filename)
                            if m:
                                l_num = int(m.group(1))
                                l_dir = course_dir / f"00{l_num}_Lesson_{l_num}"
                                l_dir.mkdir(parents=True, exist_ok=True)
                                target = l_dir / f"00{l_num}_Workbook_Lesson_{l_num}.pdf"
                                if not target.exists():
                                    with z.open(item) as src, open(target, "wb") as dst:
                                        shutil.copyfileobj(src, dst)
                                    console.print(f"[green]  ✓ Workbook PDF: {target.name}[/green]")
            except Exception as e:
                console.print(f"[yellow]  ⚠ Error extrayendo Workbooks: {e}[/yellow]")

        # E. Play Alongs (Audio tracks a cada lección)
        pa_zip = zips_dir / "Play Alongs.zip"
        if pa_zip.exists():
            try:
                with zipfile.ZipFile(pa_zip) as z:
                    for item in z.infolist():
                        if not item.filename.startswith("__MACOSX") and not item.is_dir() and (item.filename.endswith(".mp3") or item.filename.endswith(".m4a")):
                            m = re.search(r"Lesson\+(\d+)", item.filename)
                            if m:
                                l_num = int(m.group(1))
                                l_dir = course_dir / f"00{l_num}_Lesson_{l_num}"
                                l_dir.mkdir(parents=True, exist_ok=True)
                                fname = item.filename.split("/")[-1].replace("+", " ")
                                target = l_dir / fname
                                if not target.exists():
                                    with z.open(item) as src, open(target, "wb") as dst:
                                        shutil.copyfileobj(src, dst)
                                    console.print(f"[green]  ✓ Audio Track: {target.name}[/green]")
            except Exception as e:
                console.print(f"[yellow]  ⚠ Error extrayendo Play Alongs: {e}[/yellow]")

        console.print(f"\n[green]✓ Curso Motown Masters completado y organizado en:[/green] {course_dir}")

    def download_all(self, limit: int | None = None) -> None:
        """Descarga los materiales de todos los cursos disponibles secuencialmente."""
        courses = self.list_courses()
        for course in courses:
            try:
                self.download_course(course.slug, limit=limit)
            except Exception as e:
                console.print(f"[yellow]⚠ Error descargando {course.title}: {e}. Continuando.[/yellow]")

    def close(self) -> None:
        if self._client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
