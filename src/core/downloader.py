"""
Descarga de vídeos con yt-dlp.
Soporta:
  - Streams HLS directos (hlsResourcePath)
  - URLs de Vimeo embedded (streamId como fallback)
  - Ficheros de material (PDFs, etc.) via httpx
"""
from __future__ import annotations
import os
import httpx
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

import yt_dlp
try:
    import imageio_ffmpeg
    _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    _FFMPEG_PATH = None

console = Console()


# Silenciar los warnings de yt-dlp salvo errores
class _YTDLPLogger:
    def debug(self, msg):
        if msg.startswith("[debug]"):
            return
        if msg.startswith("[info]"):
            console.print(f"[dim]{msg}[/dim]")

    def info(self, msg):
        console.print(f"[dim]{msg}[/dim]")

    def warning(self, msg):
        console.print(f"[yellow]⚠ {msg}[/yellow]")

    def error(self, msg):
        console.print(f"[red]✗ {msg}[/red]")


def _progress_hook(progress_bar: dict):
    """Hook de progreso para yt-dlp."""
    pass  # La barra de Rich se gestiona externamente


def download_video(
    url: str,
    output_path: Path,
    bearer_token: str | None = None,
    quality: str = "best",
    verify_ssl: bool = False,
) -> bool:
    """
    Descarga un vídeo desde `url` a `output_path`.
    Devuelve True si tuvo éxito.

    - url: HLS m3u8, Vimeo embed URL, o cualquier URL soportada por yt-dlp
    - output_path: ruta de destino SIN extensión (yt-dlp añade la suya)
    - cookies: dict de cookies de sesión para autenticación
    - quality: 'best', '1080', '720', '480'
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Formato de calidad
    if quality == "best":
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    else:
        fmt = (
            f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        )

    ydl_opts: dict = {
        "format": fmt,
        "outtmpl": str(output_path) + ".%(ext)s",
        "logger": _YTDLPLogger(),
        "quiet": True,
        "no_warnings": False,
        "merge_output_format": "mp4",
        "nocheckcertificate": not verify_ssl,
        **(({"ffmpeg_location": _FFMPEG_PATH}) if _FFMPEG_PATH else {}),
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 5,
    }

    # Inyectar Bearer token si lo hay
    headers: dict = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://escueladebajistas.com/",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    ydl_opts["http_headers"] = headers

    # Si ya existe el fichero, skip
    existing = list(output_path.parent.glob(output_path.name + ".*"))
    if existing:
        console.print(f"[dim]  ↩ Ya existe: {existing[0].name}[/dim]")
        return True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except yt_dlp.utils.DownloadError as e:
        console.print(f"[red]  ✗ Error descargando: {e}[/red]")
        return False


def download_file(
    url: str,
    output_path: Path,
    http_client: httpx.Client | None = None,
) -> bool:
    """
    Descarga un fichero binario (PDF, etc.) con httpx.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        console.print(f"[dim]  ↩ Ya existe: {output_path.name}[/dim]")
        return True

    client = http_client or httpx.Client(verify=False, follow_redirects=True, timeout=60)
    try:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        console.print(f"[red]  ✗ Error descargando {url}: {e}[/red]")
        return False
    finally:
        if http_client is None:
            client.close()
