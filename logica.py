"""
logica.py — Reglas de negocio de Mundolimp_calle.

Toda la lógica de fechas usa ZoneInfo("America/Argentina/Buenos_Aires"),
nunca date.today() ni CURRENT_DATE de Postgres (que responde en UTC).
"""
import unicodedata
from datetime import date
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Argentina/Buenos_Aires")

# ---------------------------------------------------------------------------
# Constantes de estado (evitar strings sueltos por toda la app)
# ---------------------------------------------------------------------------
ATRASADO  = "ATRASADO"
HOY       = "HOY"
PROXIMO   = "PROXIMO"
AL_DIA    = "AL_DIA"
SIN_VISITAR = "SIN_VISITAR"

# Mapeo estado → clase CSS (se calcula en servidor, viaja en el HTML)
ESTADO_CSS = {
    ATRASADO:    "semaforo-rojo",
    HOY:         "semaforo-verde",
    PROXIMO:     "semaforo-amarillo",
    AL_DIA:      "semaforo-gris",
    SIN_VISITAR: "semaforo-azul",
}


def hoy_arg() -> date:
    """Fecha de hoy en Argentina. Usar siempre esta función, nunca date.today()."""
    from datetime import datetime
    return datetime.now(TZ).date()


# ---------------------------------------------------------------------------
# calcular_estado — corazón de la app
# ---------------------------------------------------------------------------
def calcular_estado(
    ultima_visita: date | None,
    frecuencia_dias: int,
    dias_aviso: int,
    hoy: date,
) -> tuple[str, int | None]:
    """
    Devuelve (estado, dias_restantes).

    dias_restantes puede ser:
      - negativo → atrasado
      - 0        → visitar hoy
      - positivo → días que faltan
      - None     → cliente sin visitas (SIN_VISITAR)

    Parámetros
    ----------
    ultima_visita   : última fecha de visita registrada, o None si nunca se visitó
    frecuencia_dias : cada cuántos días hay que visitar al cliente
    dias_aviso      : umbral para considerar "próximo" (global, default 2)
    hoy             : fecha de referencia (siempre Argentina)
    """
    if ultima_visita is None:
        return SIN_VISITAR, None

    proxima = ultima_visita + __import__("datetime").timedelta(days=frecuencia_dias)
    dias_restantes = (proxima - hoy).days

    if dias_restantes < 0:
        return ATRASADO, dias_restantes
    if dias_restantes == 0:
        return HOY, 0
    if dias_restantes <= dias_aviso:
        return PROXIMO, dias_restantes
    return AL_DIA, dias_restantes


def badge_texto(estado: str, dias_restantes: int | None) -> str:
    """
    Texto corto para el badge de días en las listas.
    Ejemplos: '−3 días', 'HOY', 'en 2 días', '🆕 Sin visitar'
    """
    if estado == SIN_VISITAR:
        return "🆕 Sin visitar"
    if dias_restantes == 0:
        return "HOY"
    if dias_restantes < 0:
        return f"−{abs(dias_restantes)} días"
    return f"en {dias_restantes} día{'s' if dias_restantes != 1 else ''}"


# ---------------------------------------------------------------------------
# normalizar_nombre — para nombre_norm (índice único en clientes)
# ---------------------------------------------------------------------------
def normalizar_nombre(nombre: str) -> str:
    """
    Convierte a mayúsculas, elimina acentos y colapsa espacios múltiples.
    Ejemplo: 'Gómez  Juan' → 'GOMEZ JUAN'
    """
    # Quitar acentos (NFD → filtrar diacríticos)
    nfd = unicodedata.normalize("NFD", nombre)
    sin_acentos = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # Mayúsculas + colapsar espacios
    return " ".join(sin_acentos.upper().split())


# ---------------------------------------------------------------------------
# stats del resumen mensual
# ---------------------------------------------------------------------------
def calcular_stats(visitas: list[dict]) -> dict:
    """
    Recibe una lista de dicts de visitas del mes y devuelve las estadísticas
    del panel Resumen.
    """
    from decimal import Decimal

    total_visitados = len({v["cliente_id"] for v in visitas})
    compradores = {v["cliente_id"] for v in visitas if v["compro"]}
    total_compraron = len(compradores)
    conversion = (
        round(total_compraron / total_visitados * 100, 1) if total_visitados else 0.0
    )
    total_vendido = sum(v["monto"] for v in visitas if v["compro"])
    saldos_pendientes = sum(v["saldo_pendiente"] for v in visitas)

    return {
        "total_visitados": total_visitados,
        "total_compraron": total_compraron,
        "conversion": conversion,
        "total_vendido": total_vendido,
        "saldos_pendientes": saldos_pendientes,
    }
