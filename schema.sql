-- Mundolimp_calle — DDL
-- Todos los objetos usan IF NOT EXISTS → se puede correr en cada deploy sin romper nada.

CREATE TABLE IF NOT EXISTS clientes (
    id                SERIAL PRIMARY KEY,
    nombre            TEXT NOT NULL,
    nombre_norm       TEXT NOT NULL,          -- nombre en mayúsculas, sin acentos, sin espacios dobles
    zona              TEXT NOT NULL DEFAULT '',
    direccion         TEXT NOT NULL DEFAULT '',
    telefono          TEXT NOT NULL DEFAULT '',
    contacto          TEXT NOT NULL DEFAULT '',   -- nombre del encargado
    frecuencia_dias   INTEGER NOT NULL DEFAULT 10 CHECK (frecuencia_dias > 0),
    nota_fija         TEXT NOT NULL DEFAULT '',   -- "visitar por la mañana", "hablar con Horacio"
    ultima_visita     DATE,                       -- desnormalizado, se actualiza al registrar visita
    activo            BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS visitas (
    id              SERIAL PRIMARY KEY,
    cliente_id      INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha           DATE NOT NULL,
    compro          BOOLEAN NOT NULL DEFAULT FALSE,
    articulos       TEXT NOT NULL DEFAULT '',
    forma_pago      TEXT NOT NULL DEFAULT '',   -- EFECTIVO | TRANSFERENCIA | MIXTO | PENDIENTE
    monto           NUMERIC(12,2) NOT NULL DEFAULT 0,
    saldo_pendiente NUMERIC(12,2) NOT NULL DEFAULT 0,
    observaciones   TEXT NOT NULL DEFAULT '',
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- Valores por defecto de los ajustes (idempotente)
INSERT INTO ajustes (clave, valor) VALUES ('dias_aviso', '2')
    ON CONFLICT (clave) DO NOTHING;
INSERT INTO ajustes (clave, valor) VALUES ('frecuencia_default', '10')
    ON CONFLICT (clave) DO NOTHING;

-- Índices
CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_norm ON clientes(nombre_norm);
CREATE INDEX IF NOT EXISTS idx_visitas_cliente ON visitas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_visitas_fecha   ON visitas(fecha);
CREATE INDEX IF NOT EXISTS idx_clientes_zona   ON clientes(zona);

-- Migración v2: columnas de facturación en visitas
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS es idempotente → seguro en cada deploy
ALTER TABLE visitas ADD COLUMN IF NOT EXISTS facturado    BOOLEAN    NOT NULL DEFAULT FALSE;
ALTER TABLE visitas ADD COLUMN IF NOT EXISTS facturado_en TIMESTAMPTZ;
