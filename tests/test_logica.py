"""
tests/test_logica.py — Tests unitarios de calcular_estado().

Cubren todos los bordes definidos en la especificación:
  - día exacto (HOY)
  - atrasado
  - próximo (dentro del umbral de aviso)
  - al día (fuera del umbral)
  - cliente sin visitas (SIN_VISITAR)
  - umbral de aviso = 0 (edge case)
  - frecuencia de 1 día
  - atrasado varios meses

Correr con: pytest tests/test_logica.py -v
"""
from datetime import date, timedelta

import pytest

from logica import (
    AL_DIA,
    ATRASADO,
    HOY,
    PROXIMO,
    SIN_VISITAR,
    calcular_estado,
    normalizar_nombre,
    badge_texto,
)

# Fecha de referencia fija para todos los tests (evita que fallen según el día que se corran)
HOY_REF = date(2026, 8, 29)
FRECUENCIA = 10   # default según la especificación
AVISO = 2         # default según la especificación


# ---------------------------------------------------------------------------
# calcular_estado — casos del semáforo
# ---------------------------------------------------------------------------

class TestCalcularEstado:

    def test_sin_visitar_ninguna_vez(self):
        """Cliente nuevo sin última visita → SIN_VISITAR, dias_restantes=None."""
        estado, dias = calcular_estado(None, FRECUENCIA, AVISO, HOY_REF)
        assert estado == SIN_VISITAR
        assert dias is None

    def test_hoy_exacto(self):
        """Última visita hace exactamente frecuencia_dias → HOY, días=0."""
        ultima = HOY_REF - timedelta(days=FRECUENCIA)
        estado, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert estado == HOY
        assert dias == 0

    def test_atrasado_un_dia(self):
        """Venció ayer → ATRASADO, días=-1."""
        ultima = HOY_REF - timedelta(days=FRECUENCIA + 1)
        estado, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert estado == ATRASADO
        assert dias == -1

    def test_atrasado_varios_dias(self):
        """Venció hace 2 semanas → ATRASADO, días negativos."""
        ultima = HOY_REF - timedelta(days=FRECUENCIA + 14)
        estado, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert estado == ATRASADO
        assert dias == -14

    def test_proximo_justo_en_umbral(self):
        """Faltan exactamente dias_aviso días → PROXIMO."""
        ultima = HOY_REF - timedelta(days=FRECUENCIA - AVISO)
        estado, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert estado == PROXIMO
        assert dias == AVISO

    def test_proximo_un_dia_antes_del_umbral(self):
        """Falta 1 día (dentro del umbral aviso=2) → PROXIMO."""
        ultima = HOY_REF - timedelta(days=FRECUENCIA - 1)
        estado, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert estado == PROXIMO
        assert dias == 1

    def test_al_dia_un_dia_fuera_del_umbral(self):
        """Faltan aviso+1 días → AL_DIA (ya no es próximo)."""
        ultima = HOY_REF - timedelta(days=FRECUENCIA - AVISO - 1)
        estado, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert estado == AL_DIA
        assert dias == AVISO + 1

    def test_al_dia_visita_de_hoy(self):
        """Visita registrada hoy mismo → AL_DIA (vence en frecuencia días)."""
        estado, dias = calcular_estado(HOY_REF, FRECUENCIA, AVISO, HOY_REF)
        assert estado == AL_DIA
        assert dias == FRECUENCIA

    def test_frecuencia_un_dia_hoy(self):
        """Frecuencia=1, visita ayer → HOY."""
        ultima = HOY_REF - timedelta(days=1)
        estado, dias = calcular_estado(ultima, 1, AVISO, HOY_REF)
        assert estado == HOY
        assert dias == 0

    def test_frecuencia_un_dia_atrasado(self):
        """Frecuencia=1, visita hace 2 días → ATRASADO."""
        ultima = HOY_REF - timedelta(days=2)
        estado, dias = calcular_estado(ultima, 1, AVISO, HOY_REF)
        assert estado == ATRASADO
        assert dias == -1

    def test_aviso_cero_proximo_no_existe(self):
        """Con dias_aviso=0, no hay estado PROXIMO: es HOY o AL_DIA."""
        # Falta 1 día, aviso=0 → AL_DIA
        ultima = HOY_REF - timedelta(days=FRECUENCIA - 1)
        estado, dias = calcular_estado(ultima, FRECUENCIA, 0, HOY_REF)
        assert estado == AL_DIA
        assert dias == 1

    def test_atrasado_varios_meses(self):
        """Cliente sin visitar en 3 meses → ATRASADO con dias negativos grandes."""
        ultima = HOY_REF - timedelta(days=90)
        estado, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert estado == ATRASADO
        assert dias == -(90 - FRECUENCIA)  # -80

    def test_dias_restantes_es_int(self):
        """dias_restantes siempre es int cuando no es None."""
        ultima = HOY_REF - timedelta(days=5)
        _, dias = calcular_estado(ultima, FRECUENCIA, AVISO, HOY_REF)
        assert isinstance(dias, int)

    def test_estado_es_string(self):
        """estado siempre es un string."""
        estado, _ = calcular_estado(None, FRECUENCIA, AVISO, HOY_REF)
        assert isinstance(estado, str)


# ---------------------------------------------------------------------------
# normalizar_nombre
# ---------------------------------------------------------------------------

class TestNormalizarNombre:

    def test_mayusculas(self):
        assert normalizar_nombre("gomez juan") == "GOMEZ JUAN"

    def test_acentos(self):
        assert normalizar_nombre("Gómez José") == "GOMEZ JOSE"

    def test_espacios_dobles(self):
        assert normalizar_nombre("TALLER  MAZZUCHINI") == "TALLER MAZZUCHINI"

    def test_enie(self):
        assert normalizar_nombre("Ñandú") == "NANDU"

    def test_ya_normalizado(self):
        assert normalizar_nombre("LUBRICENTRO MIGUEL") == "LUBRICENTRO MIGUEL"

    def test_espacios_extremos(self):
        assert normalizar_nombre("  TALLER  ") == "TALLER"


# ---------------------------------------------------------------------------
# badge_texto
# ---------------------------------------------------------------------------

class TestBadgeTexto:

    def test_sin_visitar(self):
        assert badge_texto(SIN_VISITAR, None) == "🆕 Sin visitar"

    def test_hoy(self):
        assert badge_texto(HOY, 0) == "HOY"

    def test_atrasado_uno(self):
        assert badge_texto(ATRASADO, -1) == "−1 días"

    def test_atrasado_tres(self):
        assert badge_texto(ATRASADO, -3) == "−3 días"

    def test_en_un_dia(self):
        assert badge_texto(PROXIMO, 1) == "en 1 día"

    def test_en_dos_dias(self):
        assert badge_texto(PROXIMO, 2) == "en 2 días"

    def test_al_dia(self):
        assert badge_texto(AL_DIA, 5) == "en 5 días"
