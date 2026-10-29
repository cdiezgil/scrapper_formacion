"""
CLI principal del scrapper de formación.

Uso:
  python -m src.cli edb cursos
  python -m src.cli edb descargar --curso fundamentos
  python -m src.cli edb descargar --todo
"""
from __future__ import annotations
import os
from pathlib import Path
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()
app = typer.Typer(help="Scrapper de plataformas de formación", no_args_is_help=True)
edb_app = typer.Typer(help="Escuela de Bajistas (escueladebajistas.com)", no_args_is_help=True)
app.add_typer(edb_app, name="edb")

console = Console()

# --------------------------------------------------------------------------
# Helpers comunes
# --------------------------------------------------------------------------
def _get_download_dir() -> Path:
    d = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_quality() -> str:
    return os.getenv("VIDEO_QUALITY", "best")


def _edb_credentials() -> tuple[str, str]:
    email = os.getenv("EDB_EMAIL", "")
    password = os.getenv("EDB_PASSWORD", "")
    if not email or not password:
        console.print(
            "[red]Faltan credenciales.[/red] "
            "Define EDB_EMAIL y EDB_PASSWORD en el fichero .env"
        )
        raise typer.Exit(1)
    return email, password


# --------------------------------------------------------------------------
# edb cursos — lista los cursos disponibles
# --------------------------------------------------------------------------
@edb_app.command("cursos", help="Lista todos los cursos disponibles")
def edb_cursos():
    from .sites.escueladebajistas import EscuelaDeBajistas
    email, password = _edb_credentials()
    with EscuelaDeBajistas(email, password, _get_download_dir(), _get_quality()) as scrapper:
        try:
            scrapper.login()
            scrapper.list_courses()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# edb descargar — descarga uno o todos los cursos
# --------------------------------------------------------------------------
@edb_app.command("descargar", help="Descarga vídeos y materiales")
def edb_descargar(
    curso: str | None = typer.Option(None, "--curso", "-c",
        help="Slug del curso (ej: 'fundamentos'). Sin este flag, descarga todo."),
    video: str | None = typer.Option(None, "--video", "-v",
        help="Slug del vídeo concreto a descargar dentro del curso (ej: 'mano-derecha')."),
    limite: int | None = typer.Option(None, "--limite", "-l",
        help="Límite máximo de vídeos a descargar por curso (ideal para pruebas)."),
    todo: bool = typer.Option(False, "--todo", "-a",
        help="Descargar todos los cursos"),
    calidad: str = typer.Option("", "--calidad", "-q",
        help="Calidad de vídeo: best | 1080 | 720 | 480 (sobreescribe .env)"),
):
    from .sites.escueladebajistas import EscuelaDeBajistas

    if not curso and not todo:
        console.print(
            Panel(
                "Indica [bold]--curso SLUG[/bold] o [bold]--todo[/bold]\n\n"
                "Ejemplos:\n"
                "  python -m src.cli edb descargar --curso fundamentos --limite 1\n"
                "  python -m src.cli edb descargar --curso fundamentos --video mano-derecha\n"
                "  python -m src.cli edb descargar --todo",
                title="¿Qué descargar?",
                border_style="yellow",
            )
        )
        raise typer.Exit(0)

    email, password = _edb_credentials()
    quality = calidad or _get_quality()

    with EscuelaDeBajistas(email, password, _get_download_dir(), quality) as scrapper:
        try:
            scrapper.login()
            if todo:
                scrapper.download_all(limit=limite)
            else:
                scrapper.download_by_slug(curso, limit=limite, video_slug=video)  # type: ignore
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
if __name__ == "__main__":
    app()
