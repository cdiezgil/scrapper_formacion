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

atarcabos_app = typer.Typer(help="Atar Cabos (atarcabos.com)", no_args_is_help=True)
app.add_typer(atarcabos_app, name="atarcabos")

scoolinary_app = typer.Typer(help="Scoolinary (scoolinary.com)", no_args_is_help=True)
app.add_typer(scoolinary_app, name="scoolinary")

scottsbass_app = typer.Typer(help="Scott's Bass Lessons (scottsbasslessons.com)", no_args_is_help=True)
app.add_typer(scottsbass_app, name="scottsbass")

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


def _atarcabos_credentials() -> tuple[str, str]:
    email = os.getenv("ATARCABOS_EMAIL", "")
    password = os.getenv("ATARCABOS_PASSWORD", "")
    if not email or not password:
        console.print(
            "[red]Faltan credenciales.[/red] "
            "Define ATARCABOS_EMAIL y ATARCABOS_PASSWORD en el fichero .env"
        )
        raise typer.Exit(1)
    return email, password


def _scottsbass_credentials() -> tuple[str, str]:
    email = os.getenv("SCOTTSBASS_EMAIL", "")
    password = os.getenv("SCOTTSBASS_PASSWORD", "")
    if not email or not password:
        console.print(
            "[red]Faltan credenciales.[/red] "
            "Define SCOTTSBASS_EMAIL y SCOTTSBASS_PASSWORD en el fichero .env"
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
# edb repertorio — lista las canciones del repertorio
# --------------------------------------------------------------------------
@edb_app.command("repertorio", help="Lista todas las canciones del repertorio (40 canciones)")
def edb_repertorio():
    from .sites.escueladebajistas import EscuelaDeBajistas
    email, password = _edb_credentials()
    with EscuelaDeBajistas(email, password, _get_download_dir(), _get_quality()) as scrapper:
        try:
            scrapper.login()
            scrapper.list_repertorio()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# edb ejercicios — lista los ejercicios disponibles
# --------------------------------------------------------------------------
@edb_app.command("ejercicios", help="Lista todos los ejercicios disponibles (170 lecciones)")
def edb_ejercicios():
    from .sites.escueladebajistas import EscuelaDeBajistas
    email, password = _edb_credentials()
    with EscuelaDeBajistas(email, password, _get_download_dir(), _get_quality()) as scrapper:
        try:
            scrapper.login()
            scrapper.list_ejercicios()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# edb descargar — descarga uno o todos los cursos
# --------------------------------------------------------------------------
@edb_app.command("descargar", help="Descarga vídeos y materiales de cursos")
def edb_descargar(
    curso: str | None = typer.Option(None, "--curso", "-c",
        help="Slug del curso (ej: 'fundamentos')."),
    video: str | None = typer.Option(None, "--video", "-v",
        help="Slug del vídeo concreto a descargar dentro del curso (ej: 'mano-derecha')."),
    repertorio: bool = typer.Option(False, "--repertorio", "-r",
        help="Descargar repertorio de canciones."),
    cancion: str | None = typer.Option(None, "--cancion",
        help="Slug de canción concreta del repertorio."),
    ejercicios: bool = typer.Option(False, "--ejercicios", "-e",
        help="Descargar ejercicios."),
    ejercicio: str | None = typer.Option(None, "--ejercicio",
        help="Slug de ejercicio concreto."),
    limite: int | None = typer.Option(None, "--limite", "-l",
        help="Límite máximo de vídeos a descargar."),
    todo: bool = typer.Option(False, "--todo", "-a",
        help="Descargar todos los cursos"),
    calidad: str = typer.Option("", "--calidad", "-q",
        help="Calidad de vídeo: best | 1080 | 720 | 480 (sobreescribe .env)"),
):
    from .sites.escueladebajistas import EscuelaDeBajistas

    if not curso and not todo and not repertorio and not cancion and not ejercicios and not ejercicio:
        console.print(
            Panel(
                "Indica qué descargar:\n\n"
                "  • Un curso:      [bold]--curso SLUG[/bold] (ej: [green]--curso fundamentos[/green])\n"
                "  • Repertorio:    [bold]--repertorio[/bold] o [bold]--cancion SLUG[/bold] (ej: [green]--cancion queen-another-one-bites-the-dust[/green])\n"
                "  • Ejercicios:    [bold]--ejercicios[/bold] o [bold]--ejercicio SLUG[/bold]\n"
                "  • Todo cursos:   [bold]--todo[/bold]\n\n"
                "Ejemplos:\n"
                "  python -m src.cli edb descargar --curso fundamentos --limite 1\n"
                "  python -m src.cli edb descargar --repertorio --cancion queen-another-one-bites-the-dust\n"
                "  python -m src.cli edb descargar --ejercicios --limite 3",
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
            if repertorio or cancion:
                scrapper.download_repertorio(limit=limite, song_slug=cancion)
            elif ejercicios or ejercicio:
                scrapper.download_ejercicios(limit=limite, exercise_slug=ejercicio)
            elif todo:
                scrapper.download_all(limit=limite)
            elif curso:
                scrapper.download_by_slug(curso, limit=limite, video_slug=video)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# edb descargar-repertorio — atajo para canciones
# --------------------------------------------------------------------------
@edb_app.command("descargar-repertorio", help="Descarga canciones del repertorio con tabs y backing tracks")
def edb_descargar_repertorio(
    cancion: str | None = typer.Option(None, "--cancion", "-c",
        help="Slug de la canción (ej: 'queen-another-one-bites-the-dust')."),
    limite: int | None = typer.Option(None, "--limite", "-l",
        help="Límite máximo de canciones a descargar."),
    todo: bool = typer.Option(False, "--todo", "-a",
        help="Descargar todo el repertorio."),
    calidad: str = typer.Option("", "--calidad", "-q",
        help="Calidad de vídeo: best | 1080 | 720 | 480."),
):
    from .sites.escueladebajistas import EscuelaDeBajistas
    email, password = _edb_credentials()
    quality = calidad or _get_quality()
    with EscuelaDeBajistas(email, password, _get_download_dir(), quality) as scrapper:
        try:
            scrapper.login()
            scrapper.download_repertorio(limit=limite, song_slug=cancion)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# edb descargar-ejercicios — atajo para ejercicios
# --------------------------------------------------------------------------
@edb_app.command("descargar-ejercicios", help="Descarga lecciones de ejercicios con partituras y bases de audio")
def edb_descargar_ejercicios(
    ejercicio: str | None = typer.Option(None, "--ejercicio", "-e",
        help="Slug del ejercicio (ej: '170-groove-disco-funk-con-octavas-am')."),
    limite: int | None = typer.Option(None, "--limite", "-l",
        help="Límite máximo de ejercicios a descargar."),
    todo: bool = typer.Option(False, "--todo", "-a",
        help="Descargar todos los ejercicios."),
    calidad: str = typer.Option("", "--calidad", "-q",
        help="Calidad de vídeo: best | 1080 | 720 | 480."),
):
    from .sites.escueladebajistas import EscuelaDeBajistas
    email, password = _edb_credentials()
    quality = calidad or _get_quality()
    with EscuelaDeBajistas(email, password, _get_download_dir(), quality) as scrapper:
        try:
            scrapper.login()
            scrapper.download_ejercicios(limit=limite, exercise_slug=ejercicio)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# atarcabos cursos — lista cursos matriculados
# --------------------------------------------------------------------------
@atarcabos_app.command("cursos", help="Lista los cursos matriculados en Atar Cabos")
def atarcabos_cursos():
    from .sites.atarcabos import AtarCabos
    email, password = _atarcabos_credentials()
    with AtarCabos(email, password, _get_download_dir(), _get_quality()) as scrapper:
        try:
            scrapper.login()
            scrapper.list_courses()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# atarcabos descargar — descarga módulos, lecciones, vídeos y manuales
# --------------------------------------------------------------------------
@atarcabos_app.command("descargar", help="Descarga vídeos y manuales de un curso de Atar Cabos")
def atarcabos_descargar(
    curso: str = typer.Option("curso-per-online", "--curso", "-c",
        help="Slug del curso (ej: 'curso-per-online')."),
    modulo: int | None = typer.Option(None, "--modulo", "-m",
        help="Número de módulo concreto (1 a 11)."),
    leccion: str | None = typer.Option(None, "--leccion",
        help="Slug de la lección concreta (ej: 'nomenclatura-basica')."),
    limite: int | None = typer.Option(None, "--limite", "-l",
        help="Límite máximo de vídeos a descargar (ideal para pruebas)."),
    calidad: str = typer.Option("", "--calidad", "-q",
        help="Calidad de vídeo: best | 1080 | 720 | 480."),
):
    from .sites.atarcabos import AtarCabos
    email, password = _atarcabos_credentials()
    quality = calidad or _get_quality()
    with AtarCabos(email, password, _get_download_dir(), quality) as scrapper:
        try:
            scrapper.login()
            scrapper.download_course(
                course_slug=curso,
                limit=limite,
                modulo_idx=modulo,
                leccion_slug=leccion,
            )
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# scoolinary mis-cursos — lista cursos matriculados en tu cuenta (área privada)
# --------------------------------------------------------------------------
@scoolinary_app.command("mis-cursos", help="Lista los cursos matriculados en tu cuenta privada de Scoolinary")
def scoolinary_mis_cursos():
    from .sites.scoolinary import Scoolinary
    email = os.getenv("SCOOLINARY_EMAIL", "")
    password = os.getenv("SCOOLINARY_PASSWORD", "")
    if not email or not password:
        console.print(
            "[red]Faltan credenciales.[/red] "
            "Define SCOOLINARY_EMAIL y SCOOLINARY_PASSWORD en el fichero .env para acceder a tu área privada."
        )
        raise typer.Exit(1)
    with Scoolinary(email=email, password=password, download_dir=_get_download_dir(), quality=_get_quality()) as scrapper:
        try:
            scrapper.login()
            scrapper.list_my_courses()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# scoolinary cursos — lista cursos de gastronomía y cocina
# --------------------------------------------------------------------------
@scoolinary_app.command("cursos", help="Lista cursos de gastronomía en Scoolinary")
def scoolinary_cursos(
    buscar: str | None = typer.Option(None, "--buscar", "-b",
        help="Filtrar cursos por término de búsqueda (ej: 'pan', 'pizza', 'fermentacion')."),
    pagina: int = typer.Option(1, "--pagina", "-p",
        help="Número de página de resultados."),
    limite: int = typer.Option(30, "--limite", "-l",
        help="Cantidad de cursos a mostrar por página."),
):
    from .sites.scoolinary import Scoolinary
    with Scoolinary(download_dir=_get_download_dir(), quality=_get_quality()) as scrapper:
        try:
            scrapper.login()
            scrapper.list_courses(search=buscar, page=pagina, per_page=limite)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# scoolinary descargar — descarga lecciones, vídeos 1080p y recetarios PDF
# --------------------------------------------------------------------------
@scoolinary_app.command("descargar", help="Descarga vídeos y recetarios de un curso de Scoolinary")
def scoolinary_descargar(
    curso: str = typer.Option(..., "--curso", "-c",
        help="Slug o ID del curso (ej: 'roscones-clasicos-creativos' o 1626373)."),
    leccion: str | None = typer.Option(None, "--leccion",
        help="Slug o ID de lección concreta."),
    limite: int | None = typer.Option(None, "--limite", "-l",
        help="Límite máximo de lecciones a descargar."),
    calidad: str = typer.Option("", "--calidad", "-q",
        help="Calidad de vídeo: best | 1080 | 720 | 480."),
):
    from .sites.scoolinary import Scoolinary
    quality = calidad or _get_quality()
    with Scoolinary(download_dir=_get_download_dir(), quality=quality) as scrapper:
        try:
            scrapper.login()
            scrapper.download_course(
                course_slug_or_id=curso,
                limit=limite,
                leccion_slug=leccion,
            )
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# scottsbass cursos — lista cursos de bajo
# --------------------------------------------------------------------------
@scottsbass_app.command("cursos", help="Lista cursos disponibles en Scott's Bass Lessons")
def scottsbass_cursos():
    from .sites.scottsbasslessons import ScottsBassLessons
    email, password = _scottsbass_credentials()
    with ScottsBassLessons(email, password, _get_download_dir(), _get_quality()) as scrapper:
        try:
            scrapper.login()
            scrapper.list_courses()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# scottsbass descargar — descarga vídeos y materiales de un curso
# --------------------------------------------------------------------------
@scottsbass_app.command("descargar", help="Descarga materiales de un curso o de todo SBL")
def scottsbass_descargar(
    curso: str | None = typer.Option(None, "--curso", "-c",
        help="Slug del curso (ej: 'the-bass-players-phrasebook-learn-the-lines-steal-the-language')."),
    todo: bool = typer.Option(False, "--todo", "-a",
        help="Descargar materiales de todos los cursos disponibles."),
    limite: int | None = typer.Option(None, "--limite", "-l",
        help="Límite máximo de lecciones a descargar por curso."),
    calidad: str = typer.Option("", "--calidad", "-q",
        help="Calidad de vídeo: best | 1080 | 720 | 480."),
):
    from .sites.scottsbasslessons import ScottsBassLessons
    if not curso and not todo:
        console.print("[yellow]Indica --curso SLUG o --todo[/yellow]")
        raise typer.Exit(0)
    email, password = _scottsbass_credentials()
    quality = calidad or _get_quality()
    with ScottsBassLessons(email, password, _get_download_dir(), quality) as scrapper:
        try:
            scrapper.login()
            if todo:
                scrapper.download_all(limit=limite)
            else:
                scrapper.download_course(course_slug=curso, limit=limite)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
if __name__ == "__main__":
    app()
