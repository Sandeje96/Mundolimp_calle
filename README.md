# Mundolimp_calle

App web móvil para control de visitas y ventas en calle (MUNDOLIMP).

## Stack

- **Python + FastAPI** — un solo proceso, arranca en 1s
- **Jinja2** — HTML server-side, el celular recibe la página ya armada
- **HTMX** — búsqueda en vivo y formularios sin SPA
- **PostgreSQL + psycopg 3** — SQL directo, sin ORM
- **CSS mobile-first** — escrito a mano, ~6 KB, sin Tailwind ni Node

**Objetivo de peso:** < 100 KB por página.

## Arrancar en local

```bash
# 1. Crear entorno virtual
py -3 -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Linux / Mac

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
copy .env.example .env
# editar .env con tu DATABASE_URL

# 4. Iniciar la app
uvicorn main:app --reload

# 5. Cargar datos iniciales (solo una vez)
python seed.py
```

## Despliegue en Railway

Ver sección 9 de `ESPECIFICACION_Mundolimp_calle.md`.

Variables de entorno necesarias:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `TZ` | `America/Argentina/Buenos_Aires` |
| `APP_PIN` | el PIN que elijas |

## Tests

```bash
pytest tests/ -v
```

## Estructura

```
main.py          # rutas FastAPI
db.py            # pool psycopg3
logica.py        # regla del semáforo
seed.py          # importación inicial de datos
schema.sql       # DDL de la base
templates/       # HTML (Jinja2)
static/          # CSS, HTMX, manifest PWA
datos/           # CSVs de carga inicial
tests/           # tests unitarios
```
