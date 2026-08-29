"""
db.py — Pool de conexiones psycopg3 y helpers de consulta.

El pool se abre en el lifespan de FastAPI (no al importar el módulo).
Si se abriera al importar y la base no está lista, el contenedor crashea
en loop al desplegar en Railway.
"""
import os
import pathlib
from contextlib import asynccontextmanager
from typing import Any

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

# ---------------------------------------------------------------------------
# Pool — se configura aquí, se abre en lifespan()
# ---------------------------------------------------------------------------
POOL: ConnectionPool | None = None


def _make_pool() -> ConnectionPool:
    """Crea el pool usando DATABASE_URL del entorno. Nunca hardcodear la cadena."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "La variable de entorno DATABASE_URL no está definida.\n"
            "En Railway: Variables → agregar DATABASE_URL = ${{Postgres.DATABASE_URL}}\n"
            "En local: copiá .env.example a .env y completá los valores."
        )
    return ConnectionPool(
        conninfo=db_url,
        min_size=1,
        max_size=5,          # el plan gratuito de Railway acepta pocas conexiones
        kwargs={"row_factory": dict_row},
        open=False,          # se abre explícitamente en lifespan
    )


# ---------------------------------------------------------------------------
# init_db — corre el DDL al arrancar (IF NOT EXISTS → idempotente)
# ---------------------------------------------------------------------------
def init_db(pool: ConnectionPool) -> None:
    """Lee schema.sql y lo ejecuta. Seguro de correr en cada deploy."""
    schema_path = pathlib.Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with pool.connection() as conn:
        conn.execute(sql)
        conn.commit()


# ---------------------------------------------------------------------------
# lifespan — para usar en main.py con @asynccontextmanager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: Any):
    """Abre el pool y corre el DDL al arrancar; cierra el pool al apagar."""
    global POOL
    POOL = _make_pool()
    POOL.open()
    init_db(POOL)
    yield
    POOL.close()


# ---------------------------------------------------------------------------
# Helpers de consulta
# ---------------------------------------------------------------------------
def fetchall(sql: str, params: tuple = ()) -> list[dict]:
    """Ejecuta una SELECT y devuelve todas las filas como lista de dicts."""
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    """Ejecuta una SELECT y devuelve una fila como dict, o None."""
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def execute(sql: str, params: tuple = ()) -> None:
    """Ejecuta un INSERT/UPDATE/DELETE sin devolver resultados."""
    with POOL.connection() as conn:
        conn.execute(sql, params)
        conn.commit()


def fetchval(sql: str, params: tuple = ()) -> Any:
    """Devuelve el primer campo de la primera fila (útil para COUNT, MAX, etc.)."""
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            # dict_row → tomamos el primer valor
            return next(iter(row.values()))


def get_ajuste(clave: str, default: str = "") -> str:
    """Devuelve el valor de un ajuste de la tabla ajustes."""
    row = fetchone("SELECT valor FROM ajustes WHERE clave = %s", (clave,))
    return row["valor"] if row else default
