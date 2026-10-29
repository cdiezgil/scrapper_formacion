# scrapper-formacion

Descargador de cursos de plataformas de formación online para visualización offline.

## Plataformas soportadas

| ID | Plataforma | Contenido | Estado |
|---|---|---|---|
| `edb` | [escueladebajistas.com](https://escueladebajistas.com) | 22 cursos · 40 canciones de repertorio · 170 ejercicios | ✅ Listo |
| `atarcabos` | [atarcabos.com](https://atarcabos.com) | Cursos náuticos (PER, PNB...) · 11 módulos · 59 lecciones · 121 vídeos · Manuales PDF | ✅ Listo |
| `scoolinary` | [scoolinary.com](https://scoolinary.com) | Gastronomía y cocina · 460+ cursos · vídeos 1080p/4K Vimeo Pro · Recetarios PDF | ✅ Listo |

## Plataformas pendientes de implementar

| Plataforma | Notas |
|---|---|
| [scottsbasslessons.com](https://scottsbasslessons.com) | Clases de bajo online |
| [domestika.com](https://domestika.com) | Creatividad y diseño |

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install httpx yt-dlp pydantic typer rich python-dotenv
cp .env.example .env
# Edita .env con tus credenciales
```

## Uso

### Cursos

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

# Descargar todo el catálogo de cursos
python -m src.cli edb descargar --todo
```

### Repertorio (40 canciones)

```bash
# Listar canciones disponibles
python -m src.cli edb repertorio

# Descargar una canción concreta (con tabs y backing tracks)
python -m src.cli edb descargar-repertorio --cancion queen-another-one-bites-the-dust

# Descargar con límite
python -m src.cli edb descargar-repertorio --limite 3

# Descargar todo el repertorio
python -m src.cli edb descargar-repertorio --todo
```

### Ejercicios (170 lecciones de técnica/groove)

```bash
# Listar ejercicios disponibles
python -m src.cli edb ejercicios

# Descargar un ejercicio concreto (con partituras y bases de audio)
python -m src.cli edb descargar-ejercicios --ejercicio 170-groove-disco-funk-con-octavas-am

# Descargar con límite
python -m src.cli edb descargar-ejercicios --limite 5

# Descargar todos los ejercicios
python -m src.cli edb descargar-ejercicios --todo
```

### Atar Cabos (`atarcabos`)

```bash
# Listar cursos matriculados
python -m src.cli atarcabos cursos

# Descargar curso completo (por defecto: curso-per-online)
python -m src.cli atarcabos descargar --curso curso-per-online

# Descargar solo un módulo concreto (1 a 11)
python -m src.cli atarcabos descargar --curso curso-per-online --modulo 2

# Descargar solo una lección concreta
python -m src.cli atarcabos descargar --curso curso-per-online --modulo 2 --leccion nomenclatura-basica

# Descargar con límite de vídeos (para pruebas)
python -m src.cli atarcabos descargar --curso curso-per-online --limite 3
```

### Scoolinary (`scoolinary`)

```bash
# Listar cursos (catálogo abierto de 460+ cursos en español)
python -m src.cli scoolinary cursos

# Buscar cursos por término (ej: pan, pizza, fermentacion, ramen, pasteleria)
python -m src.cli scoolinary cursos --buscar pizza
python -m src.cli scoolinary cursos --buscar masa

# Descargar curso completo (por slug o ID)
python -m src.cli scoolinary descargar --curso pizza-napolitana
python -m src.cli scoolinary descargar --curso roscones-clasicos-creativos

# Descargar con límite de lecciones (para pruebas)
python -m src.cli scoolinary descargar --curso pizza-napolitana --limite 2
```

### Opciones comunes

```bash
# Calidad concreta (sobreescribe .env)
python -m src.cli edb descargar --curso ritmo --calidad 720
```

## Estructura de descargas

```
downloads/
└── edb/
    ├── 003_Fundamentos_del_bajo_1/
    │   ├── 001_Postura_corporal/
    │   │   └── 001_Postura_corporal.mp4
    │   └── 003_Ejercicios_básicos_de_mano_derecha/
    │       ├── 003_Ejercicios_básicos_de_mano_derecha.mp4
    │       ├── Ejercicios básicos de mano derecha - Base de batería a 80 BPM - EDB.mp3
    │       ├── Ejercicios básicos de mano derecha - Ejercicios - EDB.pdf
    │       └── Ejercicios básicos de mano derecha - Guitar Pro - EDB.gp
    ├── repertorio/
    │   └── 001_Queen_-_Another_One_Bites_The_Dust/
    │       ├── 001_Queen_-_Another_One_Bites_The_Dust.mp4
    │       └── Queen - Another One Bites The Dust - Tabs - EDB.pdf
    └── ejercicios/
        └── 001_170_-_Groove_disco-funk_con_Octavas_en_Am/
            ├── 001_170_-_Groove_disco-funk_con_Octavas_en_Am.mp4
            ├── #170 - Groove disco-funk con Octavas en Am - Base 90bpm - EDB.mp3
            ├── #170 - Groove disco-funk con Octavas en Am - Guitar Pro - EDB.gp
            └── #170 - Groove disco-funk con Octavas en Am - Tabs - EDB.pdf
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
