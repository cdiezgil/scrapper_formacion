# scrapper-formacion

Descargador de cursos de plataformas de formación online para visualización offline.

## Plataformas soportadas

| ID | Plataforma | Contenido |
|---|---|---|
| `edb` | [escueladebajistas.com](https://escueladebajistas.com) | 22 cursos · 288 vídeos · ~55h |

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install httpx yt-dlp pydantic typer rich python-dotenv
cp .env.example .env
# Edita .env con tus credenciales
```

## Uso

```bash
# Listar cursos disponibles
python -m src.cli edb cursos

# Descargar un curso concreto (por slug)
python -m src.cli edb descargar --curso fundamentos
python -m src.cli edb descargar --curso anatomia
python -m src.cli edb descargar --curso ritmo

# Descargar todo el catálogo
python -m src.cli edb descargar --todo

# Calidad concreta (sobreescribe .env)
python -m src.cli edb descargar --curso jazz --calidad 720
```

## Estructura de descargas

```
downloads/
└── edb/
    └── 003_Fundamentos_del_bajo_1/
        ├── videos/
        │   ├── 001_Postura_corporal.mp4
        │   ├── 002_Mano_derecha.mp4
        │   └── ...
        └── materiales/
            ├── 001_Postura_corporal.pdf
            └── ...
```

## Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `EDB_EMAIL` | Email de tu cuenta | — |
| `EDB_PASSWORD` | Contraseña | — |
| `DOWNLOAD_DIR` | Carpeta de destino | `./downloads` |
| `VIDEO_QUALITY` | `best` \| `1080` \| `720` \| `480` | `best` |

## Requisitos del sistema

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) — para mezclar vídeo y audio cuando vienen separados (HLS)

```bash
brew install ffmpeg
```
