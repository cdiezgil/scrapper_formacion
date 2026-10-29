# scrapper-formacion

Descargador de cursos de plataformas de formación online para visualización offline.

## Plataformas soportadas

| ID | Plataforma | Contenido | Estado |
|---|---|---|---|
| `edb` | [escueladebajistas.com](https://escueladebajistas.com) | 22 cursos · 288 vídeos · ~55h | ✅ Listo |

## Plataformas pendientes de implementar

| Plataforma | Notas |
|---|---|
| [scottsbasslessons.com](https://scottsbasslessons.com) | Clases de bajo online |
| [atarcabos.com](https://atarcabos.com) | Nudos y vela |
| [scoolinary.com](https://scoolinary.com) | Gastronomía y cocina |
| [domestika.com](https://domestika.com) | Creatividad y diseño |

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

# Descargar solo un vídeo concreto de un curso (por slug)
python -m src.cli edb descargar --curso fundamentos --video mano-derecha

# Descargar con límite de lecciones (ideal para pruebas)
python -m src.cli edb descargar --curso fundamentos --limite 2

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
        ├── 001_Postura_corporal/
        │   └── 001_Postura_corporal.mp4
        └── 003_Ejercicios_básicos_de_mano_derecha/
            ├── 003_Ejercicios_básicos_de_mano_derecha.mp4
            ├── Ejercicios básicos de mano derecha - Base de batería a 80 BPM - EDB.mp3
            ├── Ejercicios básicos de mano derecha - Ejercicios - EDB.pdf
            └── Ejercicios básicos de mano derecha - Guitar Pro - EDB.gp
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
- ffmpeg — incluido vía `imageio_ffmpeg` (no requiere instalación externa)
