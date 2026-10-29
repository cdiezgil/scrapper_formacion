"""
Scrapper para escueladebajistas.com
  - Auth: NextAuth credentials
  - API: GraphQL en api.escueladebajistas.com/graphql
  - Vídeos: HLS (hlsResourcePath) o Vimeo (streamId)
  - Materiales: ficheros descargables vía httpx
"""
from __future__ import annotations
import json
import re
from pathlib import Path
import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn

from ..core.auth import JWTSession, AuthError
from ..core.graphql import GraphQLClient
from ..core.models import Course, Video
from ..core.downloader import download_video, download_file

console = Console()

BASE_URL = "https://escueladebajistas.com"
API_URL  = "https://api.escueladebajistas.com/graphql"
SITE_ID  = "edb"


class EscuelaDeBajistas:
    def __init__(self, email: str, password: str, download_dir: Path,
                 quality: str = "best"):
        self.email = email
        self.password = password
        self.download_dir = download_dir / SITE_ID
        self.quality = quality
        self._session: JWTSession | None = None
        self._gql: GraphQLClient | None = None

    # ------------------------------------------------------------------
    def login(self) -> None:
        self._session = JWTSession()
        self._session.login(self.email, self.password)
        self._gql = GraphQLClient(API_URL, self._session)

    # ------------------------------------------------------------------
    def list_courses(self) -> list[Course]:
        assert self._gql, "Llama a login() primero"
        courses = self._gql.list_courses()
        console.print(f"\n[bold]📚 {len(courses)} cursos disponibles:[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=5)
        table.add_column("Curso", style="bold")
        table.add_column("Slug (--curso)", style="green")
        table.add_column("Vídeos", justify="right")
        table.add_column("Duración total", justify="right")
        for c in sorted(courses, key=lambda x: int(x.id) if x.id.isdigit() else 999):
            total_s = sum(v.duration for v in c.videos)
            h, rem = divmod(total_s, 3600)
            m = rem // 60
            table.add_row(c.id, c.name, c.slug, str(len(c.videos)), f"{h}h {m:02d}m")
        console.print(table)
        return courses

    # ------------------------------------------------------------------
    def _get_section_videos(self, section: str) -> list[Video]:
        """Obtiene la lista de vídeos de una sección SSG (ejercicios, repertorio, etc.)."""
        client = self._session.client if self._session else httpx.Client(verify=False)
        r = client.get(f"{BASE_URL}/{section}")
        r.raise_for_status()
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>', r.text)
        if not m:
            raise RuntimeError(f"No se pudo extraer __NEXT_DATA__ de /{section}")
        data = json.loads(m.group(1))
        raw_videos = data.get("props", {}).get("pageProps", {}).get("videos", [])
        return [
            Video(
                id=str(v["id"]),
                name=v["name"],
                slug=v["slug"],
                duration=v.get("duration", 0),
                level=v.get("level"),
                is_public=v.get("isPublic", False),
                resource_path=v.get("resourcePath") or f"/{section}/{v['slug']}",
                image_url=v.get("imageUrl"),
                description=v.get("description"),
            )
            for v in raw_videos
        ]

    # ------------------------------------------------------------------
    def list_repertorio(self) -> list[Video]:
        """Lista las canciones del repertorio disponibles."""
        videos = self._get_section_videos("repertorio")
        console.print(f"\n[bold]🎸 Repertorio ({len(videos)} canciones disponibles):[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=5)
        table.add_column("Canción", style="bold")
        table.add_column("Slug (--cancion)", style="green")
        table.add_column("Nivel", justify="center")
        table.add_column("Duración", justify="right")
        for v in videos:
            table.add_row(v.id, v.name, v.slug, v.level or "-", v.duration_str)
        console.print(table)
        return videos

    # ------------------------------------------------------------------
    def list_ejercicios(self) -> list[Video]:
        """Lista los ejercicios disponibles."""
        videos = self._get_section_videos("ejercicios")
        console.print(f"\n[bold]🏋️ Ejercicios ({len(videos)} lecciones disponibles):[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim", width=5)
        table.add_column("Ejercicio", style="bold")
        table.add_column("Slug (--ejercicio)", style="green")
        table.add_column("Nivel", justify="center")
        table.add_column("Duración", justify="right")
        for v in videos:
            table.add_row(v.id, v.name, v.slug, v.level or "-", v.duration_str)
        console.print(table)
        return videos

    # ------------------------------------------------------------------
    def _download_video_list(
        self,
        videos: list[Video],
        target_dir: Path,
        title: str,
        limit: int | None = None,
        video_slug: str | None = None,
    ) -> None:
        """Descarga una lista de vídeos en target_dir creando una carpeta por lección."""
        assert self._session and self._gql
        target_dir.mkdir(parents=True, exist_ok=True)

        videos_to_process = list(videos)
        if video_slug:
            videos_to_process = [v for v in videos_to_process if v.slug == video_slug]
            if not videos_to_process:
                console.print(f"[red]Vídeo no encontrado en {title}: {video_slug}[/red]")
                return
        elif limit and limit > 0:
            videos_to_process = videos_to_process[:limit]

        console.print(f"\n[bold cyan]📥 Descargando:[/bold cyan] {title}")
        console.print(f"   Destino: {target_dir}")
        console.print(f"   Vídeos a descargar: {len(videos_to_process)} (de {len(videos)})")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Vídeos", total=len(videos_to_process))

            for idx, video in enumerate(videos_to_process, 1):
                orig_idx = next((i for i, v in enumerate(videos, 1) if v.id == video.id), idx)
                prefix = f"{orig_idx:03d}"
                progress.update(task, description=f"[{idx}/{len(videos_to_process)}] {video.name[:40]}")

                # Obtener stream URL y ficheros actualizados para este vídeo
                detail = self._gql.get_video_stream(video.id)
                if detail:
                    video = detail

                stream_url = self._resolve_stream_url(video)

                lesson_dir = target_dir / f"{prefix}_{video.safe_name}"
                lesson_dir.mkdir(parents=True, exist_ok=True)

                if stream_url:
                    out = lesson_dir / f"{prefix}_{video.safe_name}"
                    success = download_video(
                        url=stream_url,
                        output_path=out,
                        bearer_token=None,  # Hetzner S3 rechaza Authorization header
                        referer=f"{BASE_URL}/",
                        quality=self.quality,
                    )
                    if not success:
                        console.print(f"[yellow]  ⚠ No se pudo descargar: {video.name}[/yellow]")
                else:
                    console.print(f"[yellow]  ⚠ Sin stream disponible: {video.name} (¿acceso restringido?)[/yellow]")

                # Descargar materiales adjuntos en la carpeta de la lección
                if video.files:
                    for f in video.files:
                        download_file(
                            url=f.url,
                            output_dir=lesson_dir,
                            filename=f.name,
                            prefix=None,
                            http_client=self._session.client,
                        )

                progress.advance(task)

        console.print(f"[green]✓ Completado:[/green] {title}")

    # ------------------------------------------------------------------
    def download_course(
        self,
        course: Course,
        limit: int | None = None,
        video_slug: str | None = None,
    ) -> None:
        """Descarga todos los vídeos y materiales de un curso."""
        course_dir = self.download_dir / f"{course.id:>03}_{course.safe_name}"
        self._download_video_list(
            videos=course.videos,
            target_dir=course_dir,
            title=course.name,
            limit=limit,
            video_slug=video_slug,
        )

    # ------------------------------------------------------------------
    def download_repertorio(
        self,
        limit: int | None = None,
        song_slug: str | None = None,
    ) -> None:
        """Descarga canciones del repertorio con tabs y backing tracks."""
        rep_dir = self.download_dir / "repertorio"
        videos = self._get_section_videos("repertorio")
        self._download_video_list(
            videos=videos,
            target_dir=rep_dir,
            title="Repertorio",
            limit=limit,
            video_slug=song_slug,
        )

    # ------------------------------------------------------------------
    def download_ejercicios(
        self,
        limit: int | None = None,
        exercise_slug: str | None = None,
    ) -> None:
        """Descarga lecciones de ejercicios con partituras y bases de audio."""
        ej_dir = self.download_dir / "ejercicios"
        videos = self._get_section_videos("ejercicios")
        self._download_video_list(
            videos=videos,
            target_dir=ej_dir,
            title="Ejercicios",
            limit=limit,
            video_slug=exercise_slug,
        )

    # ------------------------------------------------------------------
    def download_all(self, limit: int | None = None) -> None:
        courses = self.list_courses()
        for course in courses:
            self.download_course(course, limit=limit)

    # ------------------------------------------------------------------
    def download_by_slug(
        self,
        slug: str,
        limit: int | None = None,
        video_slug: str | None = None,
    ) -> None:
        courses = self._gql.list_courses()  # type: ignore
        match = next((c for c in courses if c.slug == slug), None)
        if not match:
            console.print(f"[red]Curso no encontrado: {slug}[/red]")
            console.print(f"Slugs disponibles: {', '.join(c.slug for c in courses)}")
            return
        self.download_course(match, limit=limit, video_slug=video_slug)

    # ------------------------------------------------------------------
    def _resolve_stream_url(self, video: Video) -> str | None:
        """
        Estrategia de resolución de URL de stream:
          1. hlsResourcePath (URL directa de HLS m3u8)
          2. streamId:
             - URL completa (http/https)
             - ID numérico -> Vimeo
             - ID alfanumérico -> Cloudflare Stream
          3. Si isPublic -> intentar URL de la página
        """
        if video.hls_resource_path:
            return video.hls_resource_path

        if video.stream_id:
            if video.stream_id.startswith(("http://", "https://")):
                return video.stream_id
            if video.stream_id.isdigit():
                return f"https://vimeo.com/{video.stream_id}"
            # Cloudflare Stream ID usado por escueladebajistas.com
            return f"https://customer-ghofqolwkgllimz8.cloudflarestream.com/{video.stream_id}/manifest/video.m3u8"

        if video.is_public:
            return f"{BASE_URL}{video.resource_path}"

        return None

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._session:
            self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
