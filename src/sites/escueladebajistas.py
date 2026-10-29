"""
Scrapper para escueladebajistas.com
  - Auth: NextAuth credentials
  - API: GraphQL en api.escueladebajistas.com/graphql
  - Vídeos: HLS (hlsResourcePath) o Vimeo (streamId)
  - Materiales: ficheros descargables vía httpx
"""
from __future__ import annotations
from pathlib import Path
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
        table.add_column("Curso")
        table.add_column("Vídeos", justify="right")
        table.add_column("Duración total", justify="right")
        for c in courses:
            total_s = sum(v.duration for v in c.videos)
            h, rem = divmod(total_s, 3600)
            m = rem // 60
            table.add_row(c.id, c.name, str(len(c.videos)), f"{h}h {m}m")
        console.print(table)
        return courses

    # ------------------------------------------------------------------
    def download_course(self, course: Course) -> None:
        """Descarga todos los vídeos y materiales de un curso."""
        assert self._session and self._gql
        course_dir = self.download_dir / f"{course.id:>03}_{course.safe_name}"
        course_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[bold cyan]📥 Descargando:[/bold cyan] {course.name}")
        console.print(f"   Destino: {course_dir}")
        console.print(f"   Vídeos: {len(course.videos)}")

        # El Bearer token va en el header Authorization — yt-dlp no lo necesita
        # pero lo pasamos como cookie de sesión para firmados
        token = self._session.token

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Vídeos", total=len(course.videos))

            for idx, video in enumerate(course.videos, 1):
                prefix = f"{idx:03d}"
                progress.update(task, description=f"[{idx}/{len(course.videos)}] {video.name[:40]}")

                # Obtener stream URL para este vídeo
                detail = self._gql.get_video_stream(video.id)
                if detail:
                    video = detail  # actualizar con hlsResourcePath y streamId

                stream_url = self._resolve_stream_url(video)

                if stream_url:
                    out = course_dir / "videos" / f"{prefix}_{video.safe_name}"
                    success = download_video(
                        url=stream_url,
                        output_path=out,
                        bearer_token=token,
                        quality=self.quality,
                    )
                    if not success:
                        console.print(f"[yellow]  ⚠ No se pudo descargar: {video.name}[/yellow]")
                else:
                    console.print(f"[yellow]  ⚠ Sin stream disponible: {video.name} (¿acceso restringido?)[/yellow]")

                # Descargar materiales adjuntos
                for f in video.files:
                    ext = Path(f.url).suffix or ""
                    mat_path = course_dir / "materiales" / f"{prefix}_{video.safe_name}{ext}"
                    download_file(f.url, mat_path, self._session.client)

                progress.advance(task)

        console.print(f"[green]✓ Curso completado:[/green] {course.name}")

    # ------------------------------------------------------------------
    def download_all(self) -> None:
        courses = self.list_courses()
        for course in courses:
            self.download_course(course)

    # ------------------------------------------------------------------
    def download_by_slug(self, slug: str) -> None:
        courses = self._gql.list_courses()  # type: ignore
        match = next((c for c in courses if c.slug == slug), None)
        if not match:
            console.print(f"[red]Curso no encontrado: {slug}[/red]")
            console.print(f"Slugs disponibles: {', '.join(c.slug for c in courses)}")
            return
        self.download_course(match)

    # ------------------------------------------------------------------
    def _resolve_stream_url(self, video: Video) -> str | None:
        """
        Estrategia de resolución de URL de stream:
          1. hlsResourcePath (URL directa de HLS m3u8)
          2. streamId → URL de Vimeo embebida (yt-dlp la procesa)
          3. Si isPublic → intentar URL de la página directamente (yt-dlp extraerá el player)
        """
        if video.hls_resource_path:
            return video.hls_resource_path

        if video.stream_id:
            # streamId puede ser un ID de Vimeo o de otro proveedor
            # yt-dlp intenta Vimeo por defecto con IDs numéricos
            if video.stream_id.isdigit():
                return f"https://vimeo.com/{video.stream_id}"
            return video.stream_id

        if video.is_public:
            # Para vídeos públicos, yt-dlp puede extraer el player directamente
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
