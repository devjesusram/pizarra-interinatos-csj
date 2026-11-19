"""API y servidor web de la Pizarra digital de interinatos y licencias."""
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import auth, config, db, ics, servicios
from .auth import requiere_admin, usuario_actual
from .validaciones import Bloqueado, ConflictoVersion, RequiereConfirmacion, validar_interinato

STATIC = Path(__file__).parent / "static"
EXT_ADJUNTOS = {".pdf", ".eml", ".msg", ".png", ".jpg", ".jpeg", ".txt", ".docx", ".doc"}


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.abrir()
    with db.conexion() as conn:
        db.inicializar_esquema(conn)
    config.ADJUNTOS_DIR.mkdir(parents=True, exist_ok=True)
    yield
    db.cerrar()


app = FastAPI(title="Pizarra de Interinatos y Licencias", lifespan=ciclo_de_vida,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")


def hoy() -> date:
    return datetime.now(config.ZONA).date()


# ── Manejo de errores de validación ────────────────────────────────────

@app.exception_handler(Bloqueado)
def _h_bloqueado(_, e: Bloqueado):
    return JSONResponse({"tipo": "BLOQUEO", "hallazgos": [h.a_dict() for h in e.hallazgos]}, 409)


@app.exception_handler(RequiereConfirmacion)
def _h_confirmar(_, e: RequiereConfirmacion):
    return JSONResponse({"tipo": "CONFIRMAR", "hallazgos": [h.a_dict() for h in e.hallazgos]}, 428)


@app.exception_handler(ConflictoVersion)
def _h_version(_, e: ConflictoVersion):
    return JSONResponse({"tipo": "VERSION", "hallazgos": [
        {"nivel": "BLOQUEO", "regla": "R10", "mensaje": str(e)}]}, 409)


@app.exception_handler(LookupError)
def _h_no_existe(_, e: LookupError):
    return JSONResponse({"detail": str(e)}, 404)


# ── Modelos ────────────────────────────────────────────────────────────

def _vacio_a_none(v):
    return None if isinstance(v, str) and not v.strip() else v


class LicenciaIn(BaseModel):
    personal_id: int
    tipo_licencia_id: int
    fecha_inicio: date
    fecha_fin: date
    organo_aprobador: Literal["CONSEJO", "RRHH"]
    nro_resolucion: Optional[str] = None
    correo_remitente: Optional[str] = None
    correo_asunto: Optional[str] = None
    correo_fecha: Optional[datetime] = None
    enlace_externo: Optional[str] = None
    observaciones: Optional[str] = None
    version: Optional[int] = None

    _limpiar = field_validator("nro_resolucion", "correo_remitente", "correo_asunto", "correo_fecha",
                               "enlace_externo", "observaciones", mode="before")(_vacio_a_none)


class InterinatoIn(BaseModel):
    titular_id: int
    interino_id: int
    licencia_id: Optional[int] = None
    fecha_inicio: date
    fecha_fin: date
    acto_designacion: Optional[str] = None
    observaciones: Optional[str] = None
    confirmar_advertencias: bool = False
    version: Optional[int] = None

    _limpiar = field_validator("acto_designacion", "observaciones", mode="before")(_vacio_a_none)


class AnularIn(BaseModel):
    motivo: str = Field(min_length=3)
    version: int


class LoginIn(BaseModel):
    usuario: str
    clave: str


class UsuarioIn(BaseModel):
    usuario: str = Field(min_length=3, max_length=40)
    nombre: str = Field(min_length=3)
    rol: Literal["ADMIN", "OPERADOR"]
    activo: bool = True
    clave: Optional[str] = None


class ClaveIn(BaseModel):
    clave_actual: Optional[str] = None
    clave_nueva: str


class PersonalIn(BaseModel):
    nombre_completo: str = Field(min_length=3)
    cargo_codigo: Literal["JUEZ", "ACTUARIO", "SECRETARIO", "UJIER"]
    despacho_id: int
    email: Optional[str] = None
    activo: bool = True

    _limpiar = field_validator("email", mode="before")(_vacio_a_none)


class DespachoIn(BaseModel):
    nombre: str = Field(min_length=3)
    fuero: str = Field(min_length=2)
    localidad: str = Field(min_length=2)
    activo: bool = True


class DiaInhabilIn(BaseModel):
    fecha: date
    descripcion: str = Field(min_length=2)


# ── Sesión ─────────────────────────────────────────────────────────────

@app.post("/api/login")
def login(body: LoginIn, response: Response):
    with db.conexion() as conn:
        token = auth.iniciar_sesion(conn, body.usuario, body.clave)
    if not token:
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict",
                        secure=config.COOKIE_SEGURA, max_age=config.SESION_HORAS * 3600)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE)
    if token:
        with db.conexion() as conn:
            auth.cerrar_sesion(conn, token)
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/yo")
def yo(u=Depends(usuario_actual)):
    return {**u, "hoy": hoy(), "circunscripcion": config.NOMBRE_CIRCUNSCRIPCION}


@app.post("/api/yo/clave")
def cambiar_mi_clave(body: ClaveIn, u=Depends(usuario_actual)):
    auth.validar_clave_nueva(body.clave_nueva)
    with db.conexion() as conn:
        r = conn.execute("SELECT hash_clave FROM usuarios WHERE id = %s", (u["id"],)).fetchone()
        if not auth.verificar_clave(body.clave_actual or "", r["hash_clave"]):
            raise HTTPException(400, "La contraseña actual no es correcta.")
        with conn.transaction():
            conn.execute("UPDATE usuarios SET hash_clave = %s WHERE id = %s",
                         (auth.hash_clave(body.clave_nueva), u["id"]))
    return {"ok": True}


# ── Catálogos y datos maestros ─────────────────────────────────────────

@app.get("/api/catalogos")
def catalogos(u=Depends(usuario_actual)):
    with db.conexion() as conn:
        return {
            "cargos": conn.execute("SELECT * FROM cargos ORDER BY orden_pizarra").fetchall(),
            "tipos_licencia": conn.execute(
                "SELECT * FROM tipos_licencia WHERE activo ORDER BY nombre").fetchall(),
            "despachos": conn.execute("SELECT * FROM despachos ORDER BY localidad, nombre").fetchall(),
        }


SQL_PERSONAL = """SELECT p.id, p.nombre_completo, p.cargo_codigo, p.despacho_id, p.email, p.activo,
                         p.ics_token, c.nombre AS cargo, c.orden_pizarra, d.nombre AS despacho,
                         d.fuero, d.localidad
                  FROM personal p JOIN cargos c ON c.codigo = p.cargo_codigo
                  JOIN despachos d ON d.id = p.despacho_id"""


@app.get("/api/personal")
def listar_personal(u=Depends(usuario_actual)):
    with db.conexion() as conn:
        return conn.execute(SQL_PERSONAL + " ORDER BY c.orden_pizarra, p.nombre_completo").fetchall()


def _guardar(conn, sql, params, tabla, accion, uid):
    try:
        with conn.transaction():
            r = conn.execute(sql, params).fetchone()
            if not r:
                raise LookupError("Registro inexistente")
            servicios.auditar(conn.cursor(), tabla, r["id"], accion,
                              {k: v for k, v in params.items() if k != "h"}, uid)
            return r
    except Exception as e:  # unicidad, claves foráneas, etc.
        import psycopg
        if isinstance(e, psycopg.errors.UniqueViolation):
            raise HTTPException(409, "Ya existe un registro con esos datos.")
        if isinstance(e, psycopg.errors.IntegrityError):
            raise HTTPException(400, "Datos inválidos: " + (e.diag.message_primary or ""))
        raise


@app.post("/api/personal", status_code=201)
def crear_personal(body: PersonalIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id, email, activo)
                                 VALUES (%(nombre_completo)s, %(cargo_codigo)s, %(despacho_id)s, %(email)s, %(activo)s)
                                 RETURNING id""", body.model_dump(), "personal", "CREAR", u["id"])


@app.put("/api/personal/{pid}")
def editar_personal(pid: int, body: PersonalIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """UPDATE personal SET nombre_completo = %(nombre_completo)s,
                                   cargo_codigo = %(cargo_codigo)s, despacho_id = %(despacho_id)s,
                                   email = %(email)s, activo = %(activo)s
                                 WHERE id = %(id)s RETURNING id""",
                        {**body.model_dump(), "id": pid}, "personal", "MODIFICAR", u["id"])


@app.post("/api/despachos", status_code=201)
def crear_despacho(body: DespachoIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """INSERT INTO despachos (nombre, fuero, localidad, activo)
                                 VALUES (%(nombre)s, %(fuero)s, %(localidad)s, %(activo)s) RETURNING id""",
                        body.model_dump(), "despachos", "CREAR", u["id"])


@app.put("/api/despachos/{did}")
def editar_despacho(did: int, body: DespachoIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """UPDATE despachos SET nombre = %(nombre)s, fuero = %(fuero)s,
                                   localidad = %(localidad)s, activo = %(activo)s
                                 WHERE id = %(id)s RETURNING id""",
                        {**body.model_dump(), "id": did}, "despachos", "MODIFICAR", u["id"])


@app.get("/api/dias-inhabiles")
def listar_inhabiles(u=Depends(usuario_actual)):
    with db.conexion() as conn:
        return conn.execute("SELECT * FROM dias_inhabiles ORDER BY fecha").fetchall()


@app.post("/api/dias-inhabiles", status_code=201)
def crear_inhabil(body: DiaInhabilIn, u=Depends(requiere_admin)):
    with db.conexion() as conn, conn.transaction():
        conn.execute("""INSERT INTO dias_inhabiles (fecha, descripcion) VALUES (%s, %s)
                        ON CONFLICT (fecha) DO UPDATE SET descripcion = EXCLUDED.descripcion""",
                     (body.fecha, body.descripcion))
    return {"ok": True}


@app.delete("/api/dias-inhabiles/{fecha}")
def borrar_inhabil(fecha: date, u=Depends(requiere_admin)):
    with db.conexion() as conn, conn.transaction():
        conn.execute("DELETE FROM dias_inhabiles WHERE fecha = %s", (fecha,))
    return {"ok": True}


# ── Usuarios (solo ADMIN) ──────────────────────────────────────────────

@app.get("/api/usuarios")
def listar_usuarios(u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return conn.execute("SELECT id, usuario, nombre, rol, activo, creado_en FROM usuarios "
                            "ORDER BY nombre").fetchall()


@app.post("/api/usuarios", status_code=201)
def crear_usuario(body: UsuarioIn, u=Depends(requiere_admin)):
    auth.validar_clave_nueva(body.clave)
    datos = body.model_dump(exclude={"clave"})
    datos["usuario"] = datos["usuario"].strip().lower()
    with db.conexion() as conn:
        return _guardar(conn, """INSERT INTO usuarios (usuario, nombre, rol, activo, hash_clave)
                                 VALUES (%(usuario)s, %(nombre)s, %(rol)s, %(activo)s, %(h)s) RETURNING id""",
                        {**datos, "h": auth.hash_clave(body.clave)}, "usuarios", "CREAR", u["id"])


@app.put("/api/usuarios/{uid}")
def editar_usuario(uid: int, body: UsuarioIn, u=Depends(requiere_admin)):
    if uid == u["id"] and (body.rol != "ADMIN" or not body.activo):
        raise HTTPException(400, "No puede quitarse a sí mismo el rol de administrador ni desactivarse.")
    datos = body.model_dump(exclude={"clave"})
    datos["usuario"] = datos["usuario"].strip().lower()
    with db.conexion() as conn:
        r = _guardar(conn, """UPDATE usuarios SET usuario = %(usuario)s, nombre = %(nombre)s,
                                rol = %(rol)s, activo = %(activo)s WHERE id = %(id)s RETURNING id""",
                     {**datos, "id": uid}, "usuarios", "MODIFICAR", u["id"])
        if body.clave:
            auth.validar_clave_nueva(body.clave)
            with conn.transaction():
                conn.execute("UPDATE usuarios SET hash_clave = %s WHERE id = %s",
                             (auth.hash_clave(body.clave), uid))
                conn.execute("DELETE FROM sesiones WHERE usuario_id = %s", (uid,))
        if not body.activo:
            with conn.transaction():
                conn.execute("DELETE FROM sesiones WHERE usuario_id = %s", (uid,))
        return r


@app.get("/api/auditoria")
def ver_auditoria(limite: int = Query(200, le=1000), u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return conn.execute("""SELECT a.*, u.nombre AS usuario FROM auditoria a
                               LEFT JOIN usuarios u ON u.id = a.usuario_id
                               ORDER BY a.ts DESC LIMIT %s""", (limite,)).fetchall()


# ── Pizarra ────────────────────────────────────────────────────────────

def _rango(desde: date, hasta: date):
    if hasta < desde:
        raise HTTPException(400, "Rango de fechas inválido.")
    if (hasta - desde).days > 400:
        raise HTTPException(400, "El rango máximo es de 400 días.")


@app.get("/api/pizarra")
def pizarra(desde: date, hasta: date, u=Depends(usuario_actual)):
    _rango(desde, hasta)
    p = {"desde": desde, "hasta": hasta}
    with db.conexion() as conn:
        personal = conn.execute(SQL_PERSONAL + " WHERE p.activo ORDER BY c.orden_pizarra, p.nombre_completo").fetchall()
        licencias = conn.execute("""
            SELECT l.id, l.personal_id, l.tipo_licencia_id, t.nombre AS tipo, l.fecha_inicio, l.fecha_fin,
                   l.organo_aprobador, l.nro_resolucion, l.adjunto_nombre IS NOT NULL AS tiene_adjunto,
                   l.version
            FROM licencias l JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
            WHERE l.estado = 'VIGENTE' AND l.periodo && daterange(%(desde)s, %(hasta)s, '[]')""", p).fetchall()
        interinatos = conn.execute("""
            SELECT i.id, i.titular_id, i.interino_id, i.licencia_id, i.fecha_inicio, i.fecha_fin,
                   i.estado, i.version, t.nombre_completo AS titular, x.nombre_completo AS interino,
                   dt.nombre AS despacho_titular
            FROM interinatos i
            JOIN personal t ON t.id = i.titular_id
            JOIN personal x ON x.id = i.interino_id
            JOIN despachos dt ON dt.id = t.despacho_id
            WHERE i.estado <> 'ANULADO' AND i.periodo && daterange(%(desde)s, %(hasta)s, '[]')""", p).fetchall()
        inhabiles = conn.execute("SELECT fecha, descripcion FROM dias_inhabiles WHERE fecha BETWEEN %(desde)s AND %(hasta)s",
                                 p).fetchall()
    return {"desde": desde, "hasta": hasta, "hoy": hoy(), "personal": personal,
            "licencias": licencias, "interinatos": interinatos, "inhabiles": inhabiles}


@app.get("/api/alertas")
def ver_alertas(u=Depends(usuario_actual)):
    with db.conexion() as conn, conn.cursor() as cur:
        return servicios.alertas(cur, hoy())


@app.get("/api/disponibilidad")
def disponibilidad(titular_id: int, desde: date, hasta: date, excluir_id: Optional[int] = None,
                   u=Depends(usuario_actual)):
    """Candidatos del mismo cargo, con su estado según las mismas reglas que al guardar."""
    _rango(desde, hasta)
    with db.conexion() as conn, conn.cursor() as cur:
        cur.execute(SQL_PERSONAL + " WHERE p.id = %s", (titular_id,))
        tit = cur.fetchone()
        if not tit:
            raise HTTPException(404, "Titular inexistente")
        cur.execute(SQL_PERSONAL + " WHERE p.activo AND p.cargo_codigo = %s AND p.id <> %s",
                    (tit["cargo_codigo"], titular_id))
        candidatos = []
        for c in cur.fetchall():
            hall = validar_interinato(cur, titular_id, c["id"], desde, hasta, excluir_id)
            # R6 y R8 dependen del titular, no del candidato: se informan aparte
            propios = [h for h in hall if h.regla not in ("R6", "R8")]
            if any(h.nivel.value == "BLOQUEO" for h in propios):
                estado = "BLOQUEADO"
            elif any(h.nivel.value == "ADVERTENCIA" for h in propios):
                estado = "AVISO"
            else:
                estado = "DISPONIBLE"
            candidatos.append({"id": c["id"], "nombre_completo": c["nombre_completo"],
                               "despacho": c["despacho"], "localidad": c["localidad"],
                               "estado": estado, "hallazgos": [h.a_dict() for h in propios]})
        orden = {"DISPONIBLE": 0, "AVISO": 1, "BLOQUEADO": 2}
        candidatos.sort(key=lambda c: (orden[c["estado"]], c["localidad"] != tit["localidad"],
                                       c["nombre_completo"]))
        # Hallazgos del titular (independientes del candidato)
        generales = []
        if candidatos:
            hall = validar_interinato(cur, titular_id, candidatos[0]["id"], desde, hasta, excluir_id)
            generales = [h.a_dict() for h in hall if h.regla in ("R6", "R8")]
    return {"titular": tit, "candidatos": candidatos, "generales": generales}


# ── Licencias ──────────────────────────────────────────────────────────

SQL_LICENCIA = """SELECT l.*, t.nombre AS tipo, p.nombre_completo, p.cargo_codigo, d.nombre AS despacho,
                         uc.nombre AS creado_por_nombre, um.nombre AS modificado_por_nombre
                  FROM licencias l JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
                  JOIN personal p ON p.id = l.personal_id JOIN despachos d ON d.id = p.despacho_id
                  LEFT JOIN usuarios uc ON uc.id = l.creado_por
                  LEFT JOIN usuarios um ON um.id = l.modificado_por
                  WHERE l.id = %s"""


@app.get("/api/licencias/{lid}")
def ver_licencia(lid: int, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        r = conn.execute(SQL_LICENCIA, (lid,)).fetchone()
        if not r:
            raise HTTPException(404, "Licencia inexistente")
        r.pop("adjunto_ruta", None)
        r.pop("periodo", None)
        r["interinatos"] = conn.execute("""
            SELECT i.id, i.fecha_inicio, i.fecha_fin, i.estado, x.nombre_completo AS interino
            FROM interinatos i JOIN personal x ON x.id = i.interino_id
            WHERE i.titular_id = %s AND i.estado <> 'ANULADO'
              AND i.periodo && daterange(%s, %s, '[]') ORDER BY i.fecha_inicio""",
            (r["personal_id"], r["fecha_inicio"], r["fecha_fin"])).fetchall()
        return r


@app.post("/api/licencias", status_code=201)
def crear_licencia(body: LicenciaIn, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        lid, avisos = servicios.crear_licencia(conn, body.model_dump(), u["id"])
    return {"id": lid, "avisos": [a.a_dict() for a in avisos]}


@app.put("/api/licencias/{lid}")
def editar_licencia(lid: int, body: LicenciaIn, u=Depends(usuario_actual)):
    if body.version is None:
        raise HTTPException(400, "Falta la versión del registro.")
    with db.conexion() as conn:
        avisos = servicios.editar_licencia(conn, lid, body.model_dump(), body.version, u["id"])
    return {"id": lid, "avisos": [a.a_dict() for a in avisos]}


@app.post("/api/licencias/{lid}/anular")
def anular_licencia(lid: int, body: AnularIn, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        servicios.anular_licencia(conn, lid, body.motivo, body.version, u["id"])
    return {"ok": True}


@app.post("/api/licencias/{lid}/adjunto")
async def subir_adjunto(lid: int, archivo: UploadFile = File(...), u=Depends(usuario_actual)):
    nombre = Path(archivo.filename or "adjunto").name
    ext = Path(nombre).suffix.lower()
    if ext not in EXT_ADJUNTOS:
        raise HTTPException(400, f"Tipo de archivo no permitido ({ext}). Use: {', '.join(sorted(EXT_ADJUNTOS))}")
    contenido = await archivo.read(config.ADJUNTO_MAX_MB * 1024 * 1024 + 1)
    if len(contenido) > config.ADJUNTO_MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera {config.ADJUNTO_MAX_MB} MB.")
    ruta = f"{uuid.uuid4().hex}{ext}"
    (config.ADJUNTOS_DIR / ruta).write_bytes(contenido)
    with db.conexion() as conn:
        servicios.guardar_adjunto(conn, lid, nombre, ruta, u["id"])
    return {"ok": True, "adjunto_nombre": nombre}


@app.get("/api/licencias/{lid}/adjunto")
def bajar_adjunto(lid: int, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        r = conn.execute("SELECT adjunto_nombre, adjunto_ruta FROM licencias WHERE id = %s", (lid,)).fetchone()
    if not r or not r["adjunto_ruta"]:
        raise HTTPException(404, "La licencia no tiene adjunto.")
    ruta = config.ADJUNTOS_DIR / Path(r["adjunto_ruta"]).name
    if not ruta.exists():
        raise HTTPException(404, "El archivo adjunto no se encuentra en el servidor.")
    return FileResponse(ruta, filename=r["adjunto_nombre"])


# ── Interinatos ────────────────────────────────────────────────────────

@app.get("/api/interinatos/{iid}")
def ver_interinato(iid: int, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        r = conn.execute("""
            SELECT i.*, t.nombre_completo AS titular, x.nombre_completo AS interino,
                   dt.nombre AS despacho_titular, dx.nombre AS despacho_interino, c.nombre AS cargo,
                   uc.nombre AS creado_por_nombre, um.nombre AS modificado_por_nombre
            FROM interinatos i
            JOIN personal t ON t.id = i.titular_id JOIN despachos dt ON dt.id = t.despacho_id
            JOIN personal x ON x.id = i.interino_id JOIN despachos dx ON dx.id = x.despacho_id
            JOIN cargos c ON c.codigo = i.cargo_codigo
            LEFT JOIN usuarios uc ON uc.id = i.creado_por
            LEFT JOIN usuarios um ON um.id = i.modificado_por
            WHERE i.id = %s""", (iid,)).fetchone()
    if not r:
        raise HTTPException(404, "Interinato inexistente")
    r.pop("periodo", None)
    return r


@app.post("/api/interinatos", status_code=201)
def crear_interinato(body: InterinatoIn, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        iid, infos = servicios.crear_interinato(conn, body.model_dump(), u["id"], body.confirmar_advertencias)
    return {"id": iid, "avisos": [a.a_dict() for a in infos]}


@app.put("/api/interinatos/{iid}")
def editar_interinato(iid: int, body: InterinatoIn, u=Depends(usuario_actual)):
    if body.version is None:
        raise HTTPException(400, "Falta la versión del registro.")
    with db.conexion() as conn:
        infos = servicios.editar_interinato(conn, iid, body.model_dump(), body.version, u["id"],
                                            body.confirmar_advertencias)
    return {"id": iid, "avisos": [a.a_dict() for a in infos]}


@app.post("/api/interinatos/{iid}/anular")
def anular_interinato(iid: int, body: AnularIn, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        servicios.anular_interinato(conn, iid, body.motivo, body.version, u["id"])
    return {"ok": True}


# ── Exportación .ics ───────────────────────────────────────────────────

def _ics_respuesta(contenido: bytes, nombre: str):
    nombre = re.sub(r"[^A-Za-z0-9_.-]+", "_", nombre)
    return Response(contenido, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.get("/api/exportar.ics")
def exportar_ics(desde: date, hasta: date, personal_id: Optional[int] = None, u=Depends(usuario_actual)):
    _rango(desde, hasta)
    with db.conexion() as conn, conn.cursor() as cur:
        nombre = config.NOMBRE_CIRCUNSCRIPCION
        if personal_id:
            r = conn.execute("SELECT nombre_completo FROM personal WHERE id = %s", (personal_id,)).fetchone()
            if not r:
                raise HTTPException(404, "Funcionario inexistente")
            nombre = r["nombre_completo"]
        contenido = ics.generar(cur, desde, hasta, personal_id, nombre)
    return _ics_respuesta(contenido, f"pizarra_{desde}_{hasta}.ics")


@app.get("/ics/{token}.ics")
def feed_ics(token: str):
    """Feed de suscripción (sin inicio de sesión: el token largo es la llave)."""
    d, h = hoy() - timedelta(days=90), hoy() + timedelta(days=365)
    with db.conexion() as conn, conn.cursor() as cur:
        if config.ICS_TOKEN_GENERAL and token == config.ICS_TOKEN_GENERAL:
            return _ics_respuesta(ics.generar(cur, d, h, None, config.NOMBRE_CIRCUNSCRIPCION), "pizarra.ics")
        try:
            uuid.UUID(token)
        except ValueError:
            raise HTTPException(404)
        r = conn.execute("SELECT id, nombre_completo FROM personal WHERE ics_token = %s AND activo",
                         (token,)).fetchone()
        if not r:
            raise HTTPException(404)
        return _ics_respuesta(ics.generar(cur, d, h, r["id"], r["nombre_completo"]), "mi_calendario.ics")


# ── Páginas ────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(STATIC / "index.html")


@app.get("/login", include_in_schema=False)
def pagina_login():
    return FileResponse(STATIC / "login.html")


@app.get("/salud", include_in_schema=False)
def salud():
    with db.conexion() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def sin_cache_api(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.exception_handler(401)
def _h_401(request: Request, e):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": e.detail}, 401)
    return RedirectResponse("/login")
