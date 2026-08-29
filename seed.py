"""
seed.py — Importa clientes_seed.csv y visitas_historicas.csv de forma idempotente.

Reglas:
  - Todo dentro de UNA transacción.
  - ON CONFLICT (nombre_norm) DO NOTHING para clientes → idempotente.
  - Visitas: se busca cliente_id por nombre_norm; si no existe se saltea la fila.
  - Al final, UPDATE clientes.ultima_visita con el MAX(fecha) de visitas
    para dejar consistente la columna desnormalizada.
  - Correr dos veces no duplica nada.

Uso:
  py -3 seed.py
  (o desde la shell de Railway: python seed.py)
"""
import csv
import os
import pathlib
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

# Cargar .env local si existe (en Railway las vars vienen del entorno directamente)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import psycopg
from psycopg.rows import dict_row

from logica import normalizar_nombre

BASE_DIR = pathlib.Path(__file__).parent
CLIENTES_CSV = BASE_DIR / "datos" / "clientes_seed.csv"
VISITAS_CSV  = BASE_DIR / "datos" / "visitas_historicas.csv"


def parse_date(s: str) -> date | None:
    """Parsea YYYY-MM-DD o devuelve None si está vacío/inválido."""
    s = s.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_decimal(s: str, default: str = "0") -> Decimal:
    """Parsea un string a Decimal. Devuelve 0 si está vacío o inválido."""
    s = s.strip()
    if not s:
        return Decimal(default)
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(default)


def parse_bool(s: str) -> bool:
    """Parsea '1'/'0', 'true'/'false', 'yes'/'no', etc."""
    return s.strip().lower() in ("1", "true", "yes", "si", "sí")


def seed(conn: psycopg.Connection) -> None:
    """
    Ejecuta el seed completo dentro de la conexión dada.
    El caller es responsable de commit/rollback.
    """
    # -----------------------------------------------------------------------
    # 1. Clientes
    # -----------------------------------------------------------------------
    print(f"📂 Leyendo {CLIENTES_CSV}...")
    clientes_insertados = 0
    clientes_saltados = 0

    with open(CLIENTES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nombre = row["nombre"].strip()
            if not nombre:
                continue

            nombre_norm = normalizar_nombre(nombre)
            zona = row.get("zona", "").strip()
            frecuencia_dias = int(row.get("frecuencia_dias", "10") or "10")
            ultima_visita = parse_date(row.get("ultima_visita", ""))
            activo = parse_bool(row.get("activo", "1"))
            nota_fija = row.get("ultima_observacion", "").strip()

            # Usar ON CONFLICT DO NOTHING: idempotente por nombre_norm
            cur = conn.execute(
                """
                INSERT INTO clientes
                    (nombre, nombre_norm, zona, frecuencia_dias, ultima_visita, activo, nota_fija)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (nombre_norm) DO NOTHING
                RETURNING id
                """,
                (nombre, nombre_norm, zona, frecuencia_dias, ultima_visita, activo, nota_fija),
            )
            row_ret = cur.fetchone()
            if row_ret:
                clientes_insertados += 1
            else:
                clientes_saltados += 1

    print(f"  ✅ Clientes insertados: {clientes_insertados}  |  ya existían (saltados): {clientes_saltados}")

    # -----------------------------------------------------------------------
    # 2. Visitas históricas
    # -----------------------------------------------------------------------
    print(f"📂 Leyendo {VISITAS_CSV}...")
    visitas_insertadas = 0
    visitas_sin_cliente = 0
    visitas_sin_fecha = 0

    with open(VISITAS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nombre_cliente = row.get("cliente", "").strip()
            fecha = parse_date(row.get("fecha", ""))

            if not nombre_cliente:
                visitas_sin_cliente += 1
                continue
            if fecha is None:
                visitas_sin_fecha += 1
                continue

            nombre_norm = normalizar_nombre(nombre_cliente)

            # Buscar el cliente por nombre_norm
            cur = conn.execute(
                "SELECT id FROM clientes WHERE nombre_norm = %s",
                (nombre_norm,),
            )
            cliente_row = cur.fetchone()
            if not cliente_row:
                # El cliente no existe en la base → saltear
                visitas_sin_cliente += 1
                continue

            cliente_id = cliente_row["id"]
            compro = parse_bool(row.get("compro", "0"))
            articulos = row.get("articulos", "").strip()
            forma_pago = row.get("forma_pago", "").strip()
            monto = parse_decimal(row.get("monto", "0"))
            saldo_pendiente = parse_decimal(row.get("saldo_pendiente", "0"))
            observaciones = row.get("observaciones", "").strip()

            conn.execute(
                """
                INSERT INTO visitas
                    (cliente_id, fecha, compro, articulos, forma_pago,
                     monto, saldo_pendiente, observaciones)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (cliente_id, fecha, compro, articulos, forma_pago,
                 monto, saldo_pendiente, observaciones),
            )
            visitas_insertadas += 1

    print(f"  ✅ Visitas insertadas: {visitas_insertadas}  |  sin cliente en base: {visitas_sin_cliente}  |  sin fecha: {visitas_sin_fecha}")

    # -----------------------------------------------------------------------
    # 3. Actualizar ultima_visita desnormalizada
    # -----------------------------------------------------------------------
    print("🔄 Actualizando ultima_visita en clientes...")
    conn.execute(
        """
        UPDATE clientes c
        SET ultima_visita = sub.max_fecha
        FROM (
            SELECT cliente_id, MAX(fecha) AS max_fecha
            FROM visitas
            GROUP BY cliente_id
        ) sub
        WHERE c.id = sub.cliente_id
        AND (c.ultima_visita IS NULL OR sub.max_fecha > c.ultima_visita)
        """
    )
    print("  ✅ ultima_visita actualizada.")


def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("❌ ERROR: la variable de entorno DATABASE_URL no está definida.", file=sys.stderr)
        print("   Copiá .env.example a .env y completá los valores.", file=sys.stderr)
        sys.exit(1)

    print(f"🔌 Conectando a la base de datos...")
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        print("✅ Conexión establecida. Iniciando transacción...")
        try:
            seed(conn)
            conn.commit()
            print("\n🎉 Seed completado exitosamente.")
        except Exception as e:
            conn.rollback()
            print(f"\n❌ Error durante el seed, se hizo rollback: {e}", file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
