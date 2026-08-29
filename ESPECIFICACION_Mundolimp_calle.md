# Mundolimp_calle — Especificación del proyecto

App web móvil para control de visitas y ventas en calle (MUNDOLIMP).
Documento para pasarle a Claude Code / Antigravity como brief inicial.

---

## 1. Qué resuelve

Hoy el control se lleva en un Excel (`CONTROL_DE_VENTAS.xlsx`) con una hoja por mes y una fila por
visita. Funciona para registrar, pero no sirve para lo importante en la calle: **saber a quién
tengo que visitar hoy y qué clientes ya se me están venciendo.**

La app reemplaza eso con dos ideas centrales:

1. Cada cliente tiene una **frecuencia de visita en días** (configurable, uno por uno).
2. Al registrar una visita, la próxima fecha se calcula sola: `última visita + frecuencia`.
   Con eso, la pantalla principal es una lista ordenada por urgencia y pintada con semáforo.

En el Excel actual la próxima visita siempre está a 10 días de la anterior, así que **10 días es
el valor por defecto** de la frecuencia, pero editable por cliente.

---

## 2. Regla del semáforo (el corazón de la app)

```
dias_restantes = (ultima_visita + frecuencia_dias) - hoy
```

| Estado      | Condición                          | Color            | Dónde aparece                |
|-------------|------------------------------------|------------------|------------------------------|
| ATRASADO    | `dias_restantes < 0`               | Rojo             | Arriba de todo en "Hoy"      |
| HOY         | `dias_restantes == 0`              | Verde            | En "Hoy"                     |
| PRÓXIMO     | `0 < dias_restantes <= aviso`      | Amarillo/ámbar   | En "Hoy" y en "Agenda"       |
| AL DÍA      | `dias_restantes > aviso`           | Gris / neutro    | Solo en "Clientes"           |
| SIN VISITAR | cliente nuevo, sin `ultima_visita` | Azul             | En "Hoy" (prospecto a captar)|

`aviso` es un ajuste global (default **2 días**) editable desde Ajustes.

El color se calcula **en el servidor** y viaja como una clase CSS. Nada de recalcular fechas en
JavaScript en el celular.

---

## 3. Stack (elegido por liviano, no por moderno)

| Capa       | Elección                            | Por qué                                              |
|------------|-------------------------------------|------------------------------------------------------|
| Backend    | **Python + FastAPI**                | Un solo proceso, arranca en 1s, Railway lo detecta solo |
| Vistas     | **Jinja2 (HTML server-side)**       | El celular recibe HTML ya armado, no un bundle de JS  |
| Interacción| **HTMX** (~14 KB, por CDN o local)  | Formularios y filtros sin escribir una SPA            |
| CSS        | Un solo `styles.css` escrito a mano (~6 KB) | Sin Tailwind, sin build step, sin Node          |
| Base       | **PostgreSQL** (servicio de Railway) | Persistente, con backups, sin volumen que configurar |
| Driver     | **psycopg 3** (`psycopg[binary,pool]`) | SQL directo, sin ORM; pool de conexiones incluido   |
| Deploy     | Railway + `Procfile`                | `git push` y listo                                    |

**Peso objetivo de la página principal: menos de 100 KB en total.** Cualquier celular de gama baja
con 3G la abre. Esto es un requisito, no una aspiración: si el proyecto empieza a necesitar `npm`,
algo se desvió.

**No usar:** React, Next.js, Vue, Tailwind, ningún bundler, ningún framework de componentes.
Tampoco ORM (SQLAlchemy, SQLModel): son ~15 consultas SQL en total, escritas a mano se leen mejor
y no agregan una capa más para depurar.

---

## 4. Modelo de datos

```sql
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
-- ajustes: dias_aviso=2, frecuencia_default=10

CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_norm ON clientes(nombre_norm);
CREATE INDEX IF NOT EXISTS idx_visitas_cliente ON visitas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_visitas_fecha   ON visitas(fecha);
CREATE INDEX IF NOT EXISTS idx_clientes_zona   ON clientes(zona);
```

**Tipos, con motivo:**

- `NUMERIC(12,2)` para plata, nunca `REAL` ni `FLOAT`. Con float, sumar montos da errores de
  centavos que aparecen en el resumen del mes. En Python llega como `Decimal`.
- `TIMESTAMPTZ` (no `TIMESTAMP`): Postgres guarda el instante con zona horaria, así no importa que
  el servidor esté en UTC.
- `nombre_norm` con índice único es lo que hace idempotente al seed y lo que evita cargar dos veces
  el mismo cliente desde el celular. Se calcula en Python al guardar, no en la base.
- Todos los `TEXT` son `NOT NULL DEFAULT ''` para no tener que chequear `None` en cada template.

`ultima_visita` se guarda en `clientes` a propósito (aunque se pueda derivar de `visitas`): evita
un GROUP BY en cada carga de la pantalla principal. Se actualiza dentro de la **misma transacción**
que inserta la visita — el INSERT y el UPDATE van juntos o no va ninguno.

**Zonas:** texto libre con autocompletado desde las zonas ya existentes. No hace falta una tabla
aparte; sí un `<datalist>` con las zonas actuales para no generar variantes nuevas
("AV.ITUZAINGO" vs "AV ITUZAINGO").

---

## 5. Pantallas

Barra de navegación fija abajo, 4 íconos, apta para el pulgar: **Hoy · Agenda · Clientes · Resumen**

### 5.1 HOY (`/`) — pantalla de arranque
- Lista de clientes con estado ATRASADO, HOY o PRÓXIMO, ordenados por `dias_restantes` ascendente.
- Agrupados por **zona** con encabezado, porque la recorrida es por barrio.
- Cada fila: nombre grande, zona chica, badge de días ("−3 días", "HOY", "en 2 días"), y la
  `nota_fija` si existe. Fondo pintado según el semáforo.
- Toque en la fila → ficha del cliente.
- Botón flotante en cada fila: **✓ Registrar visita** (abre el formulario ya con ese cliente).
- Filtro rápido arriba: chips de zona (`Todas | Quaranta | San Martín | ...`).

### 5.2 AGENDA (`/agenda`)
- Próximos 15 días, agrupado por fecha. Cuántos clientes caen cada día y en qué zonas.
- Sirve para planificar la recorrida de mañana.

### 5.3 CLIENTES (`/clientes`)
- Buscador por nombre (filtra mientras se escribe, con HTMX).
- Filtro por zona y por estado.
- Botón **+ Nuevo cliente**.
- Ficha (`/clientes/{id}`): datos editables, **frecuencia en días** bien visible, historial de
  visitas ordenado de más nueva a más vieja, total comprado, saldo pendiente,
  botón de WhatsApp si hay teléfono (`https://wa.me/549...`).

### 5.4 REGISTRAR VISITA (`/visitas/nueva?cliente_id=X`)
Formulario corto, pensado para llenarlo parado en la vereda:
- Fecha (default hoy)
- ¿Compró? — dos botones grandes SÍ / NO
- Si SÍ: artículos (texto libre), forma de pago (select), monto (teclado numérico:
  `inputmode="numeric"`), saldo pendiente (opcional)
- Observaciones — con **botones de atajo** para las frases que más se repiten:
  `Visitar próxima vuelta` · `Pidió lista de precios` · `Todavía con stock` ·
  `Sin interés` · `No estaba el encargado` · `Cerrado` · `Saldo pendiente`
- Al guardar: inserta la visita, actualiza `ultima_visita`, vuelve a HOY con un aviso de
  confirmación.

### 5.5 RESUMEN (`/resumen`)
Reproduce los números que ya se llevaban en el Excel, por mes:
- Clientes visitados
- Clientes que compraron
- % de conversión
- Total vendido en el mes
- Saldos pendientes (lista de quién debe y cuánto)
- Ranking de zonas por monto vendido

---

## 6. Endpoints

```
GET  /                          → Hoy (atrasados + hoy + próximos)
GET  /agenda                    → próximos 15 días
GET  /clientes                  → listado + búsqueda (?q=&zona=&estado=)
GET  /clientes/nuevo            → form alta
POST /clientes                  → crear
GET  /clientes/{id}             → ficha + historial
POST /clientes/{id}             → editar
POST /clientes/{id}/baja        → activo = 0
GET  /visitas/nueva             → form (?cliente_id=)
POST /visitas                   → crear visita + actualizar ultima_visita
GET  /resumen                   → estadísticas (?mes=YYYY-MM)
GET  /ajustes                   → dias_aviso, frecuencia_default
POST /ajustes                   → guardar
GET  /exportar.csv              → backup descargable de clientes + visitas
GET  /health                    → 200 OK (healthcheck de Railway)
```

`/exportar.csv` no es opcional: es el seguro contra perder la base.

---

## 7. Estructura de archivos

```
Mundolimp_calle/
├── main.py                 # app FastAPI, todas las rutas
├── db.py                   # pool psycopg, init_db(), helpers de consulta
├── schema.sql              # el DDL de la sección 4, con IF NOT EXISTS
├── logica.py               # calcular_estado(), dias_restantes(), stats del resumen
├── seed.py                 # importa clientes_seed.csv y visitas_historicas.csv (idempotente)
├── templates/
│   ├── base.html           # layout + nav inferior
│   ├── hoy.html
│   ├── agenda.html
│   ├── clientes.html
│   ├── cliente_detalle.html
│   ├── visita_form.html
│   └── resumen.html
├── static/
│   ├── styles.css
│   ├── htmx.min.js
│   ├── manifest.json       # PWA: "agregar a pantalla de inicio"
│   └── icon-192.png
├── datos/
│   ├── clientes_seed.csv
│   └── visitas_historicas.csv
├── requirements.txt        # fastapi, uvicorn[standard], jinja2, python-multipart, psycopg[binary,pool]
├── .env.example            # DATABASE_URL, APP_PIN, TZ (el .env real NO se sube)
├── Procfile
└── README.md
```

Un solo `main.py` para todas las rutas. El proyecto es chico; partirlo en routers agrega archivos
sin agregar claridad.

### 7.1 Conexión a Postgres (`db.py`)

```python
import os
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

# Railway inyecta DATABASE_URL solo. No hardcodear nunca la cadena de conexión.
POOL = ConnectionPool(
    conninfo=os.environ["DATABASE_URL"],
    min_size=1,
    max_size=5,          # el plan gratuito de Postgres tiene pocas conexiones: no abrir 20
    kwargs={"row_factory": dict_row},
    open=False,
)
```

Puntos que importan:

- **Abrir el pool en el `lifespan` de FastAPI**, no al importar el módulo. Si se abre al importar y
  la base todavía no está lista, el contenedor crashea en loop al desplegar.
- **`max_size` chico.** El Postgres de Railway acepta pocas conexiones simultáneas; un pool grande
  las agota y la app empieza a tirar `too many connections`.
- **Placeholders `%s`**, nunca f-strings ni concatenación:
  `cur.execute("SELECT * FROM clientes WHERE zona = %s", (zona,))`. Es la única defensa contra
  inyección SQL y es gratis.
- `dict_row` hace que las filas lleguen como diccionarios, para usarlas directo en los templates.
- `init_db()` lee `schema.sql` y lo ejecuta al arrancar. Como todo el DDL tiene `IF NOT EXISTS`, se
  puede correr en cada deploy sin romper nada.

---

## 8. Detalles móviles obligatorios

- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
- Área táctil mínima **44×44 px** en todo lo que se toca.
- Tipografía base **16px** (menos que eso hace que iOS haga zoom al enfocar un input).
- `inputmode="numeric"` en monto y frecuencia; `inputmode="tel"` en teléfono.
- Fuente del sistema (`system-ui`), **cero webfonts**.
- Sin animaciones, sin librerías de íconos: emojis o SVG inline.
- PWA mínima (`manifest.json` + `display: standalone`) para instalarla en el escritorio del
  celular y que abra como app.
- **Modo claro con buen contraste** — se usa al sol, en la calle. Nada de gris claro sobre blanco.

---

## 9. Despliegue en Railway

**`Procfile`:**
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

`init_db()` corre dentro del `lifespan` de la app, así que no hace falta un comando de release
aparte.

**Variables de entorno:**

| Variable | Valor | De dónde sale |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | **Referencia** al servicio Postgres, no pegar el texto |
| `TZ` | `America/Argentina/Buenos_Aires` | A mano |
| `APP_PIN` | el PIN que elijas | A mano |

Sobre `DATABASE_URL`: en Railway, en las variables del servicio web, se escribe literalmente
`${{Postgres.DATABASE_URL}}`. Eso crea una **referencia** al servicio de base. Si en cambio copiás
y pegás la cadena de conexión, el día que Railway rote la contraseña la app deja de conectar sin
aviso. Railway también expone `DATABASE_PUBLIC_URL`: esa es para conectarte desde tu PC, la app
desplegada debe usar la interna (más rápida y no consume tráfico de salida).

**Pasos:**

1. Subir el repo a GitHub.
2. En Railway: *New Project → Deploy from GitHub repo*.
3. En el mismo proyecto: *New → Database → Add PostgreSQL*.
4. En el servicio web, *Variables*: agregar las tres de la tabla de arriba.
5. *Settings → Deploy → Healthcheck Path*: `/health`.
6. *Settings → Networking → Generate Domain*.
7. Abrir esa URL en el celular → menú del navegador → "Agregar a pantalla de inicio".
8. Correr el seed **una sola vez**: desde la pestaña de tu servicio en Railway, abrir una shell y
   ejecutar `python seed.py`. Alternativa sin shell: dejar una ruta `POST /admin/seed` protegida
   por el PIN y llamarla una vez desde el navegador.

Al usar Postgres como servicio, **no hace falta crear ningún Volume**: la base vive aparte del
contenedor y sobrevive a cada deploy por sí sola.

**Sobre la zona horaria:** aunque `TZ` esté seteada, calculá "hoy" siempre de forma explícita con
`datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()`, nunca con `date.today()` ni con
`CURRENT_DATE` de Postgres (que responde en UTC). Sin esto, después de las 21:00 hora argentina la
app cree que ya es el día siguiente y el semáforo se corre un día entero.

**Acceso:** la app queda en una URL pública con datos de tus clientes. Alcanza con un PIN: un
middleware que lo pida una vez y guarde una cookie firmada de larga duración. No hace falta sistema
de usuarios — sos el único que la usa.

**Backup:** Railway hace backups del Postgres, pero igual dejá andando `/exportar.csv` y bajate el
archivo de vez en cuando. Un backup que no depende del proveedor vale el rato que cuesta hacerlo.

**Para desarrollar en tu PC** (Antigravity / Claude Code): copiá `DATABASE_PUBLIC_URL` de Railway a
un `.env` local y trabajá contra esa misma base, o levantá un Postgres local con Docker. Lo segundo
es más prolijo: probar contra la base de producción significa que un `DELETE` mal escrito te borra
los datos reales. **Agregá `.env` al `.gitignore` antes del primer commit.**

## 10. Datos iniciales

Del Excel salieron tres archivos listos para importar:

| Archivo | Contenido |
|---|---|
| `clientes_seed.csv` | **275 clientes** únicos, con zona normalizada, última visita real, frecuencia 10, historial resumido y saldo pendiente |
| `visitas_historicas.csv` | **382 visitas** de julio y agosto, con monto, forma de pago y observaciones |
| `posibles_duplicados.csv` | **31 pares** de nombres parecidos para revisar a mano (ej. `GYM DOMINUS` / `GYM DOMINIUS`) |

El Excel se usa **una sola vez**, como carga inicial. Desde ahí en adelante la fuente de verdad es
Postgres y el Excel queda archivado.

`seed.py` debe ser **idempotente** apoyándose en el índice único de `nombre_norm`:

```sql
INSERT INTO clientes (nombre, nombre_norm, zona, frecuencia_dias, ultima_visita)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (nombre_norm) DO NOTHING
RETURNING id;
```

Para las visitas históricas, buscar el `cliente_id` por `nombre_norm` y saltar la fila si el cliente
no existe. Correrlo dos veces no debe duplicar nada.

Importar en este orden y dentro de **una transacción**: primero los 275 clientes, después las 382
visitas, y al final un `UPDATE clientes SET ultima_visita = (SELECT MAX(fecha) ...)` para dejar
consistente la columna desnormalizada.

Las zonas ya vienen canonizadas: de 92 variantes de escritura quedaron **63 zonas**, con las
grandes bien agrupadas (Quaranta 20 clientes, San Martín 19, Cocomarola 12, Itaembé Guazú 11,
Villa Cabello 10). Las que quedaron sueltas conviene unificarlas desde la app cuando aparezcan.

---

## 11. Fuera de alcance (versión 1)

Dejar afuera a propósito, para que el proyecto salga rápido y liviano:
mapa/GPS · notificaciones push · fotos de productos · catálogo con precios ·
multiusuario · sincronización offline · gráficos.

Si más adelante hace falta, lo más útil probablemente sea el catálogo con precios (para armar el
pedido en el momento) y las notificaciones. Pero no en la v1.

---

## 12. Prompt inicial para Claude Code

> Creá el proyecto **Mundolimp_calle** siguiendo exactamente la especificación del archivo
> `ESPECIFICACION_Mundolimp_calle.md` que está en la raíz.
>
> Stack: Python + FastAPI + Jinja2 + HTMX + **PostgreSQL con psycopg 3**. Sin Node, sin bundler,
> sin frameworks de JS, sin ORM. El objetivo de peso es menos de 100 KB por página.
>
> La conexión sale de la variable de entorno `DATABASE_URL` — nunca hardcodeada. Usá siempre
> placeholders `%s` en las consultas, nunca f-strings.
>
> Empezá en este orden:
> 1. `requirements.txt`, `Procfile`, `.env.example`, `.gitignore` (que incluya `.env`),
>    `schema.sql` con el DDL de la sección 4, y `db.py` con el pool de psycopg abierto en el
>    `lifespan` de FastAPI más `init_db()`.
> 2. `logica.py` con `calcular_estado(ultima_visita, frecuencia_dias, dias_aviso, hoy)` que
>    devuelva `(estado, dias_restantes)`. **Escribí tests para esta función antes de seguir** —
>    es la regla de negocio central y tiene que estar bien en los bordes (día exacto, atrasado,
>    cliente sin visitas).
> 3. `seed.py` que importe `datos/clientes_seed.csv` y `datos/visitas_historicas.csv` de forma
>    idempotente, usando `ON CONFLICT (nombre_norm) DO NOTHING` y una sola transacción.
> 4. `main.py` con las rutas de la sección 6, `base.html` con la nav inferior, y la pantalla HOY.
> 5. El resto de las pantallas.
> 6. `styles.css` a mano, mobile-first, alto contraste, área táctil de 44px.
>
> Usá la zona horaria `America/Argentina/Buenos_Aires` para todo cálculo de fechas.
> Después de cada paso, mostrame qué archivos creaste y por qué, antes de seguir con el siguiente.
