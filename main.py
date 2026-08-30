"""
main.py — FastAPI app de Mundolimp_calle.

Un solo archivo para todas las rutas (son ~15, no vale la pena routers).
El pool se abre en lifespan (no al importar) para que Railway no crashee
si la base todavía no está lista al desplegar.
"""
import csv
import io
import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Cargar .env local si existe
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import db
from logica import (
    AL_DIA,
    ATRASADO,
    ESTADO_CSS,
    HOY as HOY_ESTADO,
    PROXIMO,
    SIN_VISITAR,
    badge_texto,
    calcular_estado,
    calcular_stats,
    hoy_arg,
    normalizar_nombre,
)

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
APP_PIN = os.environ.get("APP_PIN", "")

# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
app = FastAPI(lifespan=db.lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Filtros Jinja2 útiles
def fmt_pesos(valor) -> str:
    if valor is None:
        return "$0"
    try:
        return f"${Decimal(str(valor)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor)

templates.env.filters["pesos"] = fmt_pesos
templates.env.globals["hoy_arg"] = hoy_arg


# ---------------------------------------------------------------------------
# Middleware de PIN
# ---------------------------------------------------------------------------
COOKIE_NAME = "ml_auth"
RUTAS_PUBLICAS = {"/health", "/static"}


@app.middleware("http")
async def pin_middleware(request: Request, call_next):
    """Pide el PIN una vez y guarda una cookie firmada de larga duración."""
    path = request.url.path

    # Rutas siempre públicas
    if path == "/health" or path.startswith("/static"):
        return await call_next(request)

    # Si no hay PIN configurado, dejar pasar todo
    if not APP_PIN:
        return await call_next(request)

    # Verificar cookie
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie == APP_PIN:
        return await call_next(request)

    # Procesar formulario de login
    if request.method == "POST" and path == "/login":
        return await call_next(request)

    # Mostrar form de login
    if path != "/login":
        return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": False})


@app.post("/login")
async def login_post(request: Request, pin: str = Form(...)):
    if pin == APP_PIN:
        resp = RedirectResponse(url="/", status_code=302)
        # 90 días
        resp.set_cookie(COOKIE_NAME, APP_PIN, max_age=60 * 60 * 24 * 90, httponly=True)
        return resp
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": True}, status_code=401
    )


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------------------------------------------------------------------------
# Health check (Railway)
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# HOY — pantalla principal
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def hoy(request: Request, zona: str = ""):
    hoy = hoy_arg()
    dias_aviso = int(db.get_ajuste("dias_aviso", "2"))

    clientes = db.fetchall(
        """
        SELECT id, nombre, zona, frecuencia_dias, ultima_visita, nota_fija, activo
        FROM clientes
        WHERE activo = TRUE
        ORDER BY zona, nombre
        """
    )

    # Calcular estado para cada cliente
    resultado = []
    for c in clientes:
        estado, dias = calcular_estado(c["ultima_visita"], c["frecuencia_dias"], dias_aviso, hoy)
        if estado in (ATRASADO, HOY_ESTADO, PROXIMO, SIN_VISITAR):
            resultado.append({
                **c,
                "estado": estado,
                "dias_restantes": dias,
                "badge": badge_texto(estado, dias),
                "css_clase": ESTADO_CSS[estado],
            })

    # Ordenar: primero ATRASADO (días más negativos primero), luego HOY, PROXIMO, SIN_VISITAR
    orden = {ATRASADO: 0, HOY_ESTADO: 1, PROXIMO: 2, SIN_VISITAR: 3}
    resultado.sort(key=lambda c: (
        orden.get(c["estado"], 9),
        c["dias_restantes"] if c["dias_restantes"] is not None else 9999,
    ))

    # Filtrar por zona si viene el parámetro
    if zona:
        resultado = [c for c in resultado if c["zona"] == zona]

    # Agrupar por zona
    zonas_dict: dict[str, list] = {}
    for c in resultado:
        zonas_dict.setdefault(c["zona"] or "Sin zona", []).append(c)

    # Zonas disponibles para el filtro de chips
    todas_zonas = sorted({c["zona"] for c in resultado if c["zona"]})

    return templates.TemplateResponse("hoy.html", {
        "request": request,
        "zonas_dict": zonas_dict,
        "todas_zonas": todas_zonas,
        "zona_activa": zona,
        "hoy": hoy,
        "total": len(resultado),
    })


# ---------------------------------------------------------------------------
# AGENDA — próximos 15 días
# ---------------------------------------------------------------------------
@app.get("/agenda", response_class=HTMLResponse)
async def agenda(request: Request):
    from datetime import timedelta
    hoy = hoy_arg()
    dias_aviso = int(db.get_ajuste("dias_aviso", "2"))

    clientes = db.fetchall(
        """
        SELECT id, nombre, zona, frecuencia_dias, ultima_visita, nota_fija
        FROM clientes
        WHERE activo = TRUE
        """
    )

    # Calcular próxima visita para cada cliente
    agenda_dict: dict = {}  # fecha → lista de clientes
    for c in clientes:
        estado, dias = calcular_estado(c["ultima_visita"], c["frecuencia_dias"], dias_aviso, hoy)
        if c["ultima_visita"] is None:
            continue
        from datetime import timedelta as td
        proxima = c["ultima_visita"] + td(days=c["frecuencia_dias"])
        # Solo mostrar los próximos 15 días
        if hoy <= proxima <= hoy + td(days=15):
            dia_str = proxima.isoformat()
            agenda_dict.setdefault(dia_str, []).append({
                **c,
                "estado": estado,
                "dias_restantes": dias,
                "badge": badge_texto(estado, dias),
                "css_clase": ESTADO_CSS[estado],
            })

    # Ordenar por fecha
    dias_ordenados = sorted(agenda_dict.keys())

    return templates.TemplateResponse("agenda.html", {
        "request": request,
        "agenda_dict": agenda_dict,
        "dias_ordenados": dias_ordenados,
        "hoy": hoy,
    })


# ---------------------------------------------------------------------------
# CLIENTES — listado + búsqueda
# ---------------------------------------------------------------------------
@app.get("/clientes", response_class=HTMLResponse)
async def clientes_lista(request: Request, q: str = "", zona: str = "", estado: str = ""):
    hoy = hoy_arg()
    dias_aviso = int(db.get_ajuste("dias_aviso", "2"))

    sql = """
        SELECT id, nombre, zona, frecuencia_dias, ultima_visita, activo
        FROM clientes
        WHERE activo = TRUE
    """
    params: list = []

    if q:
        # Dividir el query en palabras: cada palabra debe aparecer
        # en el nombre O en la zona. Así "GOM QUAR" encuentra
        # "GOMERIA..." de la zona Quaranta.
        palabras = normalizar_nombre(q).split()
        for palabra in palabras:
            sql += " AND (nombre_norm ILIKE %s OR UPPER(zona) ILIKE %s)"
            params.extend([f"%{palabra}%", f"%{palabra}%"])

    if zona:
        sql += " AND zona = %s"
        params.append(zona)

    sql += " ORDER BY nombre"

    todos = db.fetchall(sql, tuple(params))

    # Calcular estado para filtro y badge
    resultado = []
    for c in todos:
        est, dias = calcular_estado(c["ultima_visita"], c["frecuencia_dias"], dias_aviso, hoy)
        if estado and est != estado:
            continue
        resultado.append({
            **c,
            "estado": est,
            "dias_restantes": dias,
            "badge": badge_texto(est, dias),
            "css_clase": ESTADO_CSS[est],
        })

    # Zonas para filtro
    zonas = [r["zona"] for r in db.fetchall("SELECT DISTINCT zona FROM clientes WHERE activo=TRUE AND zona != '' ORDER BY zona")]

    # Si es request HTMX, devolver solo la lista parcial
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("_clientes_lista.html", {
            "request": request,
            "clientes": resultado,
        })

    return templates.TemplateResponse("clientes.html", {
        "request": request,
        "clientes": resultado,
        "zonas": zonas,
        "q": q,
        "zona_activa": zona,
        "estado_activo": estado,
        "total": len(resultado),
    })


# ---------------------------------------------------------------------------
# CLIENTES — nuevo
# ---------------------------------------------------------------------------
@app.get("/clientes/nuevo", response_class=HTMLResponse)
async def cliente_nuevo_form(request: Request):
    zonas = [r["zona"] for r in db.fetchall(
        "SELECT DISTINCT zona FROM clientes WHERE activo=TRUE AND zona != '' ORDER BY zona"
    )]
    freq_default = db.get_ajuste("frecuencia_default", "10")
    return templates.TemplateResponse("cliente_form.html", {
        "request": request,
        "cliente": None,
        "zonas": zonas,
        "freq_default": freq_default,
        "error": None,
    })


@app.post("/clientes")
async def cliente_crear(
    request: Request,
    nombre: str = Form(...),
    zona: str = Form(""),
    direccion: str = Form(""),
    telefono: str = Form(""),
    contacto: str = Form(""),
    frecuencia_dias: int = Form(10),
    nota_fija: str = Form(""),
):
    nombre = nombre.strip()
    nombre_norm = normalizar_nombre(nombre)
    if not nombre:
        return templates.TemplateResponse("cliente_form.html", {
            "request": request,
            "cliente": None,
            "zonas": [],
            "freq_default": frecuencia_dias,
            "error": "El nombre es obligatorio.",
        }, status_code=422)

    try:
        row = db.fetchone(
            """
            INSERT INTO clientes (nombre, nombre_norm, zona, direccion, telefono,
                                  contacto, frecuencia_dias, nota_fija)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (nombre, nombre_norm, zona.strip(), direccion.strip(),
             telefono.strip(), contacto.strip(), frecuencia_dias, nota_fija.strip()),
        )
    except Exception:
        return templates.TemplateResponse("cliente_form.html", {
            "request": request,
            "cliente": None,
            "zonas": [],
            "freq_default": frecuencia_dias,
            "error": "Ya existe un cliente con ese nombre.",
        }, status_code=409)

    return RedirectResponse(url=f"/clientes/{row['id']}", status_code=303)


# ---------------------------------------------------------------------------
# CLIENTES — ficha + historial
# ---------------------------------------------------------------------------
@app.get("/clientes/{cliente_id}", response_class=HTMLResponse)
async def cliente_detalle(request: Request, cliente_id: int):
    hoy = hoy_arg()
    dias_aviso = int(db.get_ajuste("dias_aviso", "2"))

    cliente = db.fetchone(
        "SELECT * FROM clientes WHERE id = %s",
        (cliente_id,),
    )
    if not cliente:
        return HTMLResponse("Cliente no encontrado", status_code=404)

    visitas = db.fetchall(
        """
        SELECT * FROM visitas
        WHERE cliente_id = %s
        ORDER BY fecha DESC, id DESC
        """,
        (cliente_id,),
    )

    estado, dias = calcular_estado(
        cliente["ultima_visita"], cliente["frecuencia_dias"], dias_aviso, hoy
    )

    total_comprado = sum(v["monto"] for v in visitas if v["compro"])
    saldo_pendiente = sum(v["saldo_pendiente"] for v in visitas)

    zonas = [r["zona"] for r in db.fetchall(
        "SELECT DISTINCT zona FROM clientes WHERE activo=TRUE AND zona != '' ORDER BY zona"
    )]

    return templates.TemplateResponse("cliente_detalle.html", {
        "request": request,
        "cliente": cliente,
        "visitas": visitas,
        "estado": estado,
        "dias_restantes": dias,
        "badge": badge_texto(estado, dias),
        "css_clase": ESTADO_CSS[estado],
        "total_comprado": total_comprado,
        "saldo_pendiente": saldo_pendiente,
        "zonas": zonas,
        "hoy": hoy,
    })


# ---------------------------------------------------------------------------
# CLIENTES — editar
# ---------------------------------------------------------------------------
@app.post("/clientes/{cliente_id}")
async def cliente_editar(
    request: Request,
    cliente_id: int,
    nombre: str = Form(...),
    zona: str = Form(""),
    direccion: str = Form(""),
    telefono: str = Form(""),
    contacto: str = Form(""),
    frecuencia_dias: int = Form(10),
    nota_fija: str = Form(""),
    activo: str = Form("on"),
):
    nombre = nombre.strip()
    nombre_norm = normalizar_nombre(nombre)
    activo_bool = activo == "on"

    db.execute(
        """
        UPDATE clientes
        SET nombre = %s, nombre_norm = %s, zona = %s, direccion = %s,
            telefono = %s, contacto = %s, frecuencia_dias = %s,
            nota_fija = %s, activo = %s
        WHERE id = %s
        """,
        (nombre, nombre_norm, zona.strip(), direccion.strip(),
         telefono.strip(), contacto.strip(), frecuencia_dias,
         nota_fija.strip(), activo_bool, cliente_id),
    )
    return RedirectResponse(url=f"/clientes/{cliente_id}", status_code=303)


# ---------------------------------------------------------------------------
# CLIENTES — baja lógica
# ---------------------------------------------------------------------------
@app.post("/clientes/{cliente_id}/baja")
async def cliente_baja(cliente_id: int):
    db.execute(
        "UPDATE clientes SET activo = FALSE WHERE id = %s",
        (cliente_id,),
    )
    return RedirectResponse(url="/clientes", status_code=303)


# ---------------------------------------------------------------------------
# VISITAS — formulario nuevo
# ---------------------------------------------------------------------------
@app.get("/visitas/nueva", response_class=HTMLResponse)
async def visita_nueva_form(request: Request, cliente_id: int = 0):
    hoy = hoy_arg()
    cliente = None
    if cliente_id:
        cliente = db.fetchone(
            "SELECT id, nombre, zona FROM clientes WHERE id = %s",
            (cliente_id,),
        )

    # Si no se pasó cliente_id, traer lista para seleccionar
    clientes = []
    if not cliente:
        clientes = db.fetchall(
            "SELECT id, nombre, zona FROM clientes WHERE activo=TRUE ORDER BY nombre"
        )

    return templates.TemplateResponse("visita_form.html", {
        "request": request,
        "cliente": cliente,
        "clientes": clientes,
        "hoy": hoy,
        "formas_pago": ["EFECTIVO", "TRANSFERENCIA", "MIXTO", "PENDIENTE"],
        "atajos": [
            "Visitar próxima vuelta",
            "Pidió lista de precios",
            "Todavía con stock",
            "Sin interés",
            "No estaba el encargado",
            "Cerrado",
            "Saldo pendiente",
        ],
    })


# ---------------------------------------------------------------------------
# VISITAS — crear (INSERT + UPDATE ultima_visita en la misma transacción)
# ---------------------------------------------------------------------------
@app.post("/visitas")
async def visita_crear(
    request: Request,
    cliente_id: int = Form(...),
    fecha: str = Form(...),
    compro: str = Form("no"),
    articulos: str = Form(""),
    forma_pago: str = Form(""),
    monto: str = Form("0"),
    saldo_pendiente: str = Form("0"),
    observaciones: str = Form(""),
):
    from datetime import date as date_cls
    from decimal import Decimal, InvalidOperation

    try:
        fecha_date = date_cls.fromisoformat(fecha)
    except ValueError:
        fecha_date = hoy_arg()

    compro_bool = compro.lower() in ("si", "sí", "yes", "1", "on")

    try:
        monto_dec = Decimal(monto.replace(",", ".")) if monto.strip() else Decimal("0")
    except InvalidOperation:
        monto_dec = Decimal("0")

    try:
        saldo_dec = Decimal(saldo_pendiente.replace(",", ".")) if saldo_pendiente.strip() else Decimal("0")
    except InvalidOperation:
        saldo_dec = Decimal("0")

    # INSERT visita + UPDATE ultima_visita en una sola transacción
    with db.POOL.connection() as conn:
        conn.execute(
            """
            INSERT INTO visitas
                (cliente_id, fecha, compro, articulos, forma_pago,
                 monto, saldo_pendiente, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (cliente_id, fecha_date, compro_bool,
             articulos.strip(), forma_pago.strip(),
             monto_dec, saldo_dec, observaciones.strip()),
        )
        # Actualizar desnormalización solo si la fecha es >= ultima_visita actual
        conn.execute(
            """
            UPDATE clientes
            SET ultima_visita = %s
            WHERE id = %s
              AND (ultima_visita IS NULL OR ultima_visita < %s)
            """,
            (fecha_date, cliente_id, fecha_date),
        )
        conn.commit()

    # Redirigir a HOY con mensaje de confirmación
    return RedirectResponse(
        url=f"/?ok={cliente_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# RESUMEN — estadísticas mensuales
# ---------------------------------------------------------------------------
@app.get("/resumen", response_class=HTMLResponse)
async def resumen(request: Request, mes: str = ""):
    hoy = hoy_arg()
    if not mes:
        mes = hoy.strftime("%Y-%m")

    try:
        anio, month = int(mes[:4]), int(mes[5:7])
    except (ValueError, IndexError):
        anio, month = hoy.year, hoy.month

    visitas = db.fetchall(
        """
        SELECT v.*, c.nombre, c.zona, c.id AS cliente_id
        FROM visitas v
        JOIN clientes c ON c.id = v.cliente_id
        WHERE EXTRACT(YEAR FROM v.fecha) = %s
          AND EXTRACT(MONTH FROM v.fecha) = %s
        ORDER BY v.fecha DESC
        """,
        (anio, month),
    )

    stats = calcular_stats(visitas)

    # Ranking de zonas por monto vendido
    zonas_dict: dict[str, Decimal] = {}
    for v in visitas:
        if v["compro"]:
            zonas_dict[v["zona"]] = zonas_dict.get(v["zona"], Decimal("0")) + v["monto"]
    zonas_ranking = sorted(zonas_dict.items(), key=lambda x: x[1], reverse=True)

    # Saldos pendientes: quién debe y cuánto
    saldos_dict: dict[str, dict] = {}
    for v in visitas:
        if v["saldo_pendiente"] > 0:
            cid = str(v["cliente_id"])
            if cid not in saldos_dict:
                saldos_dict[cid] = {"nombre": v["nombre"], "total": Decimal("0"), "id": v["cliente_id"]}
            saldos_dict[cid]["total"] += v["saldo_pendiente"]
    saldos = sorted(saldos_dict.values(), key=lambda x: x["total"], reverse=True)

    return templates.TemplateResponse("resumen.html", {
        "request": request,
        "mes": mes,
        "anio": anio,
        "month": month,
        "stats": stats,
        "zonas_ranking": zonas_ranking,
        "saldos": saldos,
        "hoy": hoy,
    })


# ---------------------------------------------------------------------------
# AJUSTES
# ---------------------------------------------------------------------------
@app.get("/ajustes", response_class=HTMLResponse)
async def ajustes_form(request: Request):
    dias_aviso = db.get_ajuste("dias_aviso", "2")
    frecuencia_default = db.get_ajuste("frecuencia_default", "10")
    return templates.TemplateResponse("ajustes.html", {
        "request": request,
        "dias_aviso": dias_aviso,
        "frecuencia_default": frecuencia_default,
        "guardado": False,
    })


@app.post("/ajustes")
async def ajustes_guardar(
    request: Request,
    dias_aviso: int = Form(2),
    frecuencia_default: int = Form(10),
):
    db.execute(
        "INSERT INTO ajustes (clave, valor) VALUES ('dias_aviso', %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
        (str(dias_aviso),),
    )
    db.execute(
        "INSERT INTO ajustes (clave, valor) VALUES ('frecuencia_default', %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
        (str(frecuencia_default),),
    )
    return templates.TemplateResponse("ajustes.html", {
        "request": request,
        "dias_aviso": str(dias_aviso),
        "frecuencia_default": str(frecuencia_default),
        "guardado": True,
    })


# ---------------------------------------------------------------------------
# EXPORTAR CSV — backup descargable
# ---------------------------------------------------------------------------
@app.get("/exportar.csv")
async def exportar_csv():
    clientes = db.fetchall("SELECT * FROM clientes ORDER BY nombre")
    visitas = db.fetchall(
        """
        SELECT v.*, c.nombre AS cliente_nombre
        FROM visitas v JOIN clientes c ON c.id = v.cliente_id
        ORDER BY v.fecha DESC
        """
    )

    output = io.StringIO()
    output.write("=== CLIENTES ===\n")
    if clientes:
        writer = csv.DictWriter(output, fieldnames=clientes[0].keys())
        writer.writeheader()
        writer.writerows(clientes)

    output.write("\n=== VISITAS ===\n")
    if visitas:
        writer = csv.DictWriter(output, fieldnames=visitas[0].keys())
        writer.writeheader()
        writer.writerows(visitas)

    content = output.getvalue()
    filename = f"mundolimp_backup_{hoy_arg().isoformat()}.csv"

    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# ADMIN SEED — ruta protegida para correr el seed desde el navegador
# ---------------------------------------------------------------------------
@app.post("/admin/seed")
async def admin_seed(request: Request, pin: str = Form(...)):
    if pin != APP_PIN:
        return HTMLResponse("PIN incorrecto", status_code=403)

    import seed as seed_module
    import psycopg
    from psycopg.rows import dict_row

    db_url = os.environ["DATABASE_URL"]
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        seed_module.seed(conn)
        conn.commit()

    return HTMLResponse("<h2>✅ Seed ejecutado correctamente.</h2><a href='/'>Ir a Hoy</a>")


# ---------------------------------------------------------------------------
# CIERRE DEL DÍA — ventas del día pendientes de facturar
# ---------------------------------------------------------------------------
@app.get("/cierre", response_class=HTMLResponse)
async def cierre(request: Request):
    hoy = hoy_arg()

    # Todas las visitas de hoy, con datos del cliente
    todas_hoy = db.fetchall(
        """
        SELECT v.id, v.fecha, v.compro, v.articulos, v.forma_pago,
               v.monto, v.saldo_pendiente, v.observaciones,
               v.facturado, v.facturado_en,
               c.id AS cliente_id, c.nombre AS cliente_nombre, c.zona
        FROM visitas v
        JOIN clientes c ON c.id = v.cliente_id
        WHERE v.fecha = %s
        ORDER BY v.compro DESC, c.nombre
        """,
        (hoy,),
    )

    pendientes  = [v for v in todas_hoy if v["compro"] and not v["facturado"]]
    facturadas  = [v for v in todas_hoy if v["compro"] and v["facturado"]]
    sin_compra  = [v for v in todas_hoy if not v["compro"]]

    from decimal import Decimal
    total_pendiente = sum(v["monto"] for v in pendientes)
    total_facturado = sum(v["monto"] for v in facturadas)

    return templates.TemplateResponse("cierre.html", {
        "request": request,
        "pendientes": pendientes,
        "facturadas": facturadas,
        "sin_compra": sin_compra,
        "total_pendiente": total_pendiente,
        "total_facturado": total_facturado,
        "hoy": hoy,
    })


# ---------------------------------------------------------------------------
# FACTURAR una visita — llamado por HTMX, elimina la fila del listado
# ---------------------------------------------------------------------------
@app.post("/visitas/{visita_id}/facturar", response_class=HTMLResponse)
async def facturar_visita(visita_id: int):
    from datetime import datetime
    ahora = datetime.now(TZ)
    db.execute(
        "UPDATE visitas SET facturado = TRUE, facturado_en = %s WHERE id = %s",
        (ahora, visita_id),
    )
    # Devolver string vacío → HTMX reemplaza la fila con nada (desaparece)
    return HTMLResponse("")


# ---------------------------------------------------------------------------
# ADMIN RESET CLIENTES — limpia ultima_visita para reiniciar el semáforo
# ---------------------------------------------------------------------------
@app.post("/admin/reset-clientes")
async def reset_clientes(request: Request, pin: str = Form(...)):
    if pin != APP_PIN:
        return templates.TemplateResponse("ajustes.html", {
            "request": request,
            "dias_aviso": db.get_ajuste("dias_aviso", "2"),
            "frecuencia_default": db.get_ajuste("frecuencia_default", "10"),
            "guardado": False,
            "reset_error": True,
            "reset_ok": False,
        }, status_code=403)

    db.execute("UPDATE clientes SET ultima_visita = NULL")

    return templates.TemplateResponse("ajustes.html", {
        "request": request,
        "dias_aviso": db.get_ajuste("dias_aviso", "2"),
        "frecuencia_default": db.get_ajuste("frecuencia_default", "10"),
        "guardado": False,
        "reset_error": False,
        "reset_ok": True,
    })
