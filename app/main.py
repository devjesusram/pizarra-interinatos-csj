"""API y servidor web de la Pizarra digital de interinatos y licencias."""
import json
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import __version__, auth, config, db, ics, servicios
from .auth import requiere_admin, usuario_actual
from .db import booleanos, escritura, iso, todos, uno
from .validaciones import Bloqueado, ConflictoVersion, RequiereConfirmacion, validar_interinato

STATIC = Path(__file__).parent / "static"
EXT_ADJUNTOS = {".pdf", ".eml", ".msg", ".png", ".jpg", ".jpeg", ".txt", ".docx", ".doc"}


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.inicializar_esquema()
    config.ADJUNTOS_DIR.mkdir(parents=True, exist_ok=True)
    yield


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
    titular_id: Optional[int] = None        # persona ausente…
    vacante_id: Optional[int] = None        # …o puesto vacante (uno de los dos)
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
    secretaria: Optional[str] = None        # p. ej. "Nº 1"
    email: Optional[str] = None
    activo: bool = True

    _limpiar = field_validator("email", "secretaria", mode="before")(_vacio_a_none)


class VacanteIn(BaseModel):
    despacho_id: int
    cargo_codigo: Literal["JUEZ", "ACTUARIO", "SECRETARIO", "UJIER"]
    secretaria: Optional[str] = None
    fecha_desde: date
    fecha_hasta: Optional[date] = None      # vacío = sigue vacante
    observaciones: Optional[str] = None
    version: Optional[int] = None

    _limpiar = field_validator("secretaria", "fecha_hasta", "observaciones", mode="before")(_vacio_a_none)


class DespachoIn(BaseModel):
    nombre: str = Field(min_length=3)
    fuero: str = Field(min_length=2)
    localidad: str = Field(min_length=2)
    turno: Optional[str] = None
    activo: bool = True

    _limpiar = field_validator("turno", mode="before")(_vacio_a_none)


class CargoIn(BaseModel):
    # None = sin límite de despachos cubiertos a la vez
    max_interinatos_simultaneos: Optional[int] = Field(default=None, ge=1, le=50)


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
    return {**u, "hoy": hoy(), "circunscripcion": config.NOMBRE_CIRCUNSCRIPCION, "version": __version__}


@app.post("/api/yo/clave")
def cambiar_mi_clave(body: ClaveIn, u=Depends(usuario_actual)):
    auth.validar_clave_nueva(body.clave_nueva)
    with db.conexion() as conn:
        r = uno(conn, "SELECT hash_clave FROM usuarios WHERE id = ?", (u["id"],))
        if not auth.verificar_clave(body.clave_actual or "", r["hash_clave"]):
            raise HTTPException(400, "La contraseña actual no es correcta.")
        with escritura(conn):
            conn.execute("UPDATE usuarios SET hash_clave = ? WHERE id = ?",
                         (auth.hash_clave(body.clave_nueva), u["id"]))
    return {"ok": True}


# ── Catálogos y datos maestros ─────────────────────────────────────────

@app.get("/api/catalogos")
def catalogos(u=Depends(usuario_actual)):
    with db.conexion() as conn:
        return {
            "cargos": todos(conn, "SELECT * FROM cargos ORDER BY orden_pizarra"),
            "tipos_licencia": booleanos(todos(conn, "SELECT * FROM tipos_licencia WHERE activo = 1 ORDER BY nombre"), "activo"),
            "despachos": booleanos(todos(conn, "SELECT * FROM despachos ORDER BY localidad, nombre, turno"), "activo"),
        }


SQL_PERSONAL = """SELECT p.id, p.nombre_completo, p.cargo_codigo, p.despacho_id, p.secretaria, p.email, p.activo,
                         p.ics_token, c.nombre AS cargo, c.orden_pizarra, d.nombre AS despacho,
                         d.fuero, d.localidad, d.turno
                  FROM personal p JOIN cargos c ON c.codigo = p.cargo_codigo
                  JOIN despachos d ON d.id = p.despacho_id"""


SQL_REGISTROS_PERSONA = """(SELECT count(*) FROM licencias l WHERE l.personal_id = p.id)
                           + (SELECT count(*) FROM interinatos i WHERE i.titular_id = p.id OR i.interino_id = p.id)"""


@app.get("/api/personal")
def listar_personal(u=Depends(usuario_actual)):
    with db.conexion() as conn:
        filas = todos(conn, SQL_PERSONAL.replace("SELECT p.id,", f"SELECT ({SQL_REGISTROS_PERSONA}) AS registros, p.id,", 1)
                      + " ORDER BY c.orden_pizarra, p.nombre_completo")
        return booleanos(filas, "activo")


@app.delete("/api/personal/{pid}")
def eliminar_personal(pid: int, u=Depends(requiere_admin)):
    """Borra un funcionario SOLO si no tiene ningún registro asociado (pensado para duplicados
    creados por error). Con historial, hay que desactivarlo."""
    with db.conexion() as conn, escritura(conn):
        p = uno(conn, f"SELECT p.*, ({SQL_REGISTROS_PERSONA}) AS registros FROM personal p WHERE p.id = ?", (pid,))
        if not p:
            raise HTTPException(404, "Funcionario inexistente")
        if p["registros"]:
            raise HTTPException(409, f"No se puede eliminar a {p['nombre_completo']}: tiene {p['registros']} "
                                     "licencia(s) o interinato(s) registrados. Desactívelo en su lugar.")
        try:
            conn.execute("DELETE FROM personal WHERE id = ?", (pid,))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "No se puede eliminar: tiene registros asociados. Desactívelo en su lugar.")
        p.pop("registros")
        servicios.auditar(conn, "personal", pid, "ELIMINAR", p, u["id"])
    return {"ok": True}


def _guardar(conn, sql, params, tabla, accion, uid, registro_id=None):
    """Alta o modificación simple con auditoría. Devuelve {"id": ...}."""
    try:
        with escritura(conn):
            cur = conn.execute(sql, params)
            if cur.rowcount == 0:
                raise LookupError("Registro inexistente")
            rid = registro_id or cur.lastrowid
            servicios.auditar(conn, tabla, rid, accion, {k: v for k, v in params.items() if k != "h"}, uid)
            return {"id": rid}
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise HTTPException(409, "Ya existe un registro con esos datos.")
        raise HTTPException(400, f"Datos inválidos: {e}")


def _bool01(d: dict) -> dict:
    return {k: (int(v) if isinstance(v, bool) else v) for k, v in d.items()}


@app.post("/api/personal", status_code=201)
def crear_personal(body: PersonalIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id, secretaria, email, activo)
                                 VALUES (:nombre_completo, :cargo_codigo, :despacho_id, :secretaria, :email, :activo)""",
                        _bool01(body.model_dump()), "personal", "CREAR", u["id"])


@app.put("/api/personal/{pid}")
def editar_personal(pid: int, body: PersonalIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """UPDATE personal SET nombre_completo = :nombre_completo,
                                   cargo_codigo = :cargo_codigo, despacho_id = :despacho_id,
                                   secretaria = :secretaria, email = :email, activo = :activo WHERE id = :id""",
                        _bool01({**body.model_dump(), "id": pid}), "personal", "MODIFICAR", u["id"], pid)


@app.post("/api/despachos", status_code=201)
def crear_despacho(body: DespachoIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """INSERT INTO despachos (nombre, fuero, localidad, turno, activo)
                                 VALUES (:nombre, :fuero, :localidad, :turno, :activo)""",
                        _bool01(body.model_dump()), "despachos", "CREAR", u["id"])


@app.put("/api/despachos/{did}")
def editar_despacho(did: int, body: DespachoIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return _guardar(conn, """UPDATE despachos SET nombre = :nombre, fuero = :fuero,
                                   localidad = :localidad, turno = :turno, activo = :activo WHERE id = :id""",
                        _bool01({**body.model_dump(), "id": did}), "despachos", "MODIFICAR", u["id"], did)


@app.put("/api/cargos/{codigo}")
def editar_cargo(codigo: str, body: CargoIn, u=Depends(requiere_admin)):
    """Cambia cuántos despachos puede cubrir a la vez una persona de ese cargo."""
    tope = body.max_interinatos_simultaneos
    with db.conexion() as conn:
        cargo = uno(conn, "SELECT * FROM cargos WHERE codigo = ?", (codigo,))
        if not cargo:
            raise HTTPException(404, "Cargo inexistente")
        if tope is not None:
            # No se puede bajar el tope por debajo de lo que ya está asignado de hoy en adelante
            excedidos = servicios.excesos_de_tope(conn, codigo, tope, hoy())
            if excedidos:
                raise HTTPException(409, "No se puede bajar el límite: " + "; ".join(excedidos)
                                    + ". Anule o ajuste esos interinatos primero.")
        with escritura(conn):
            conn.execute("UPDATE cargos SET max_interinatos_simultaneos = ? WHERE codigo = ?", (tope, codigo))
            servicios.auditar(conn, "cargos", 0, "MODIFICAR",
                              {"cargo": codigo, "max_interinatos_simultaneos": tope}, u["id"])
    return {"ok": True}


SQL_VACANTES = """SELECT v.*, c.nombre AS cargo, c.orden_pizarra, d.nombre AS despacho, d.fuero,
                         d.localidad, d.turno
                  FROM vacantes v JOIN cargos c ON c.codigo = v.cargo_codigo
                  JOIN despachos d ON d.id = v.despacho_id"""


@app.get("/api/vacantes")
def listar_vacantes(solo_vigentes: bool = False, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        if solo_vigentes:
            return todos(conn, SQL_VACANTES + " WHERE v.fecha_hasta IS NULL OR v.fecha_hasta >= ? "
                               "ORDER BY c.orden_pizarra, d.nombre", (iso(hoy()),))
        return todos(conn, SQL_VACANTES + " ORDER BY (v.fecha_hasta IS NOT NULL), c.orden_pizarra, d.nombre")


@app.get("/api/vacantes/{vid}")
def ver_vacante(vid: int, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        v = uno(conn, SQL_VACANTES + " WHERE v.id = ?", (vid,))
        if not v:
            raise HTTPException(404, "Puesto vacante inexistente")
        v["interinatos"] = todos(conn, """
            SELECT i.id, i.fecha_inicio, i.fecha_fin, i.estado, x.nombre_completo AS interino
            FROM interinatos i JOIN personal x ON x.id = i.interino_id
            WHERE i.vacante_id = ? AND i.estado <> 'ANULADO' ORDER BY i.fecha_inicio""", (vid,))
        return v


@app.post("/api/vacantes", status_code=201)
def crear_vacante(body: VacanteIn, u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return {"id": servicios.crear_vacante(conn, body.model_dump(), u["id"])}


@app.put("/api/vacantes/{vid}")
def editar_vacante(vid: int, body: VacanteIn, u=Depends(requiere_admin)):
    if body.version is None:
        raise HTTPException(400, "Falta la versión del registro.")
    with db.conexion() as conn:
        servicios.editar_vacante(conn, vid, body.model_dump(), body.version, u["id"])
    return {"id": vid}


@app.get("/api/dias-inhabiles")
def listar_inhabiles(u=Depends(usuario_actual)):
    with db.conexion() as conn:
        return todos(conn, "SELECT * FROM dias_inhabiles ORDER BY fecha")


@app.post("/api/dias-inhabiles", status_code=201)
def crear_inhabil(body: DiaInhabilIn, u=Depends(requiere_admin)):
    with db.conexion() as conn, escritura(conn):
        conn.execute("""INSERT INTO dias_inhabiles (fecha, descripcion) VALUES (?, ?)
                        ON CONFLICT (fecha) DO UPDATE SET descripcion = excluded.descripcion""",
                     (iso(body.fecha), body.descripcion))
    return {"ok": True}


@app.delete("/api/dias-inhabiles/{fecha}")
def borrar_inhabil(fecha: date, u=Depends(requiere_admin)):
    with db.conexion() as conn, escritura(conn):
        conn.execute("DELETE FROM dias_inhabiles WHERE fecha = ?", (iso(fecha),))
    return {"ok": True}


# ── Usuarios (solo ADMIN) ──────────────────────────────────────────────

@app.get("/api/usuarios")
def listar_usuarios(u=Depends(requiere_admin)):
    with db.conexion() as conn:
        return booleanos(todos(conn, "SELECT id, usuario, nombre, rol, activo, creado_en FROM usuarios "
                                     "ORDER BY nombre"), "activo")


@app.post("/api/usuarios", status_code=201)
def crear_usuario(body: UsuarioIn, u=Depends(requiere_admin)):
    auth.validar_clave_nueva(body.clave)
    datos = _bool01(body.model_dump(exclude={"clave"}))
    datos["usuario"] = datos["usuario"].strip().lower()
    with db.conexion() as conn:
        return _guardar(conn, """INSERT INTO usuarios (usuario, nombre, rol, activo, hash_clave)
                                 VALUES (:usuario, :nombre, :rol, :activo, :h)""",
                        {**datos, "h": auth.hash_clave(body.clave)}, "usuarios", "CREAR", u["id"])


@app.put("/api/usuarios/{uid}")
def editar_usuario(uid: int, body: UsuarioIn, u=Depends(requiere_admin)):
    if uid == u["id"] and (body.rol != "ADMIN" or not body.activo):
        raise HTTPException(400, "No puede quitarse a sí mismo el rol de administrador ni desactivarse.")
    if body.clave:
        auth.validar_clave_nueva(body.clave)
    datos = _bool01(body.model_dump(exclude={"clave"}))
    datos["usuario"] = datos["usuario"].strip().lower()
    with db.conexion() as conn:
        r = _guardar(conn, """UPDATE usuarios SET usuario = :usuario, nombre = :nombre,
                                rol = :rol, activo = :activo WHERE id = :id""",
                     {**datos, "id": uid}, "usuarios", "MODIFICAR", u["id"], uid)
        with escritura(conn):
            if body.clave:
                conn.execute("UPDATE usuarios SET hash_clave = ? WHERE id = ?", (auth.hash_clave(body.clave), uid))
            if body.clave or not body.activo:
                conn.execute("DELETE FROM sesiones WHERE usuario_id = ?", (uid,))
        return r


@app.get("/api/auditoria")
def ver_auditoria(limite: int = Query(200, le=1000), u=Depends(requiere_admin)):
    with db.conexion() as conn:
        filas = todos(conn, """SELECT a.*, u.nombre AS usuario FROM auditoria a
                               LEFT JOIN usuarios u ON u.id = a.usuario_id
                               ORDER BY a.id DESC LIMIT ?""", (limite,))
    for f in filas:
        f["datos"] = json.loads(f["datos"])
        f["advertencias_confirmadas"] = json.loads(f["advertencias_confirmadas"]) if f["advertencias_confirmadas"] else None
    return filas


# ── Pizarra ────────────────────────────────────────────────────────────

def _rango(desde: date, hasta: date):
    if hasta < desde:
        raise HTTPException(400, "Rango de fechas inválido.")
    if (hasta - desde).days > 400:
        raise HTTPException(400, "El rango máximo es de 400 días.")


# Interinatos con la descripción de lo que cubren: una persona o un puesto vacante
SQL_INTERINATOS_PIZARRA = """
    SELECT i.id, i.titular_id, i.vacante_id, i.interino_id, i.licencia_id, i.fecha_inicio, i.fecha_fin,
           i.estado, i.version, x.nombre_completo AS interino,
           coalesce(t.nombre_completo,
                    'Puesto vacante' || CASE WHEN v.secretaria IS NOT NULL THEN ' (Sria. ' || v.secretaria || ')' ELSE '' END)
             AS titular,
           dt.nombre AS despacho_titular
    FROM interinatos i
    LEFT JOIN personal t ON t.id = i.titular_id
    LEFT JOIN vacantes v ON v.id = i.vacante_id
    JOIN personal x ON x.id = i.interino_id
    JOIN despachos dt ON dt.id = coalesce(t.despacho_id, v.despacho_id)"""


@app.get("/api/pizarra")
def pizarra(desde: date, hasta: date, u=Depends(usuario_actual)):
    _rango(desde, hasta)
    p = {"desde": iso(desde), "hasta": iso(hasta)}
    with db.conexion() as conn:
        personal = booleanos(todos(conn, SQL_PERSONAL + " WHERE p.activo = 1 ORDER BY c.orden_pizarra, p.nombre_completo"), "activo")
        licencias = booleanos(todos(conn, """
            SELECT l.id, l.personal_id, l.tipo_licencia_id, t.nombre AS tipo, l.fecha_inicio, l.fecha_fin,
                   l.organo_aprobador, l.nro_resolucion, l.adjunto_nombre IS NOT NULL AS tiene_adjunto,
                   l.version
            FROM licencias l JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
            WHERE l.estado = 'VIGENTE' AND l.fecha_inicio <= :hasta AND l.fecha_fin >= :desde""", p), "tiene_adjunto")
        interinatos = todos(conn, SQL_INTERINATOS_PIZARRA + """
            WHERE i.estado <> 'ANULADO' AND i.fecha_inicio <= :hasta AND i.fecha_fin >= :desde""", p)
        vacantes = todos(conn, SQL_VACANTES + """
            WHERE v.fecha_desde <= :hasta AND (v.fecha_hasta IS NULL OR v.fecha_hasta >= :desde)""", p)
        inhabiles = todos(conn, "SELECT fecha, descripcion FROM dias_inhabiles WHERE fecha BETWEEN :desde AND :hasta", p)
    return {"desde": desde, "hasta": hasta, "hoy": hoy(), "personal": personal,
            "licencias": licencias, "interinatos": interinatos, "vacantes": vacantes, "inhabiles": inhabiles}


@app.get("/api/alertas")
def ver_alertas(u=Depends(usuario_actual)):
    with db.conexion() as conn:
        return servicios.alertas(conn, hoy())


@app.get("/api/disponibilidad")
def disponibilidad(desde: date, hasta: date, titular_id: Optional[int] = None,
                   vacante_id: Optional[int] = None, excluir_id: Optional[int] = None,
                   u=Depends(usuario_actual)):
    """Candidatos del mismo cargo, con su estado según las mismas reglas que al guardar.
    Se consulta para una persona ausente (titular_id) o para un puesto vacante (vacante_id)."""
    _rango(desde, hasta)
    if (titular_id is None) == (vacante_id is None):
        raise HTTPException(400, "Indique titular_id o vacante_id.")
    with db.conexion() as conn:
        if vacante_id is not None:
            tit = uno(conn, SQL_VACANTES + " WHERE v.id = ?", (vacante_id,))
        else:
            tit = uno(conn, SQL_PERSONAL + " WHERE p.id = ?", (titular_id,))
        if not tit:
            raise HTTPException(404, "Titular o puesto vacante inexistente")
        candidatos = []
        for c in todos(conn, SQL_PERSONAL + " WHERE p.activo = 1 AND p.cargo_codigo = ? AND p.id <> ?",
                       (tit["cargo_codigo"], titular_id or 0)):
            hall = validar_interinato(conn, titular_id, c["id"], desde, hasta, excluir_id, vacante_id)
            # R6 y R8 dependen del titular, no del candidato: se informan aparte
            propios = [h for h in hall if h.regla not in ("R6", "R8")]
            if any(h.nivel.value == "BLOQUEO" for h in propios):
                estado = "BLOQUEADO"
            elif any(h.nivel.value == "ADVERTENCIA" for h in propios):
                estado = "AVISO"
            else:
                estado = "DISPONIBLE"
            candidatos.append({"id": c["id"], "nombre_completo": c["nombre_completo"],
                               "despacho": c["despacho"], "turno": c["turno"], "localidad": c["localidad"],
                               "secretaria": c["secretaria"],
                               "mismo_despacho": c["despacho_id"] == tit["despacho_id"],
                               "estado": estado, "hallazgos": [h.a_dict() for h in propios]})
        # Primero los disponibles; entre ellos, los compañeros del mismo despacho (turno)
        # y después los de la misma localidad
        orden = {"DISPONIBLE": 0, "AVISO": 1, "BLOQUEADO": 2}
        candidatos.sort(key=lambda c: (orden[c["estado"]], not c["mismo_despacho"],
                                       c["localidad"] != tit["localidad"], c["nombre_completo"]))
        generales = []
        if candidatos:
            hall = validar_interinato(conn, titular_id, candidatos[0]["id"], desde, hasta, excluir_id, vacante_id)
            generales = [h.a_dict() for h in hall if h.regla in ("R6", "R8")]
    return {"titular": booleanos(tit, "activo"), "candidatos": candidatos, "generales": generales}


# ── Licencias ──────────────────────────────────────────────────────────

SQL_LICENCIA = """SELECT l.*, t.nombre AS tipo, p.nombre_completo, p.cargo_codigo, d.nombre AS despacho,
                         uc.nombre AS creado_por_nombre, um.nombre AS modificado_por_nombre
                  FROM licencias l JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
                  JOIN personal p ON p.id = l.personal_id JOIN despachos d ON d.id = p.despacho_id
                  LEFT JOIN usuarios uc ON uc.id = l.creado_por
                  LEFT JOIN usuarios um ON um.id = l.modificado_por
                  WHERE l.id = ?"""


@app.get("/api/licencias/{lid}")
def ver_licencia(lid: int, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        r = uno(conn, SQL_LICENCIA, (lid,))
        if not r:
            raise HTTPException(404, "Licencia inexistente")
        r.pop("adjunto_ruta", None)
        r["interinatos"] = todos(conn, """
            SELECT i.id, i.fecha_inicio, i.fecha_fin, i.estado, x.nombre_completo AS interino
            FROM interinatos i JOIN personal x ON x.id = i.interino_id
            WHERE i.titular_id = ? AND i.estado <> 'ANULADO'
              AND i.fecha_inicio <= ? AND i.fecha_fin >= ? ORDER BY i.fecha_inicio""",
            (r["personal_id"], r["fecha_fin"], r["fecha_inicio"]))
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
    config.ADJUNTOS_DIR.mkdir(parents=True, exist_ok=True)
    (config.ADJUNTOS_DIR / ruta).write_bytes(contenido)
    with db.conexion() as conn:
        servicios.guardar_adjunto(conn, lid, nombre, ruta, u["id"])
    return {"ok": True, "adjunto_nombre": nombre}


@app.get("/api/licencias/{lid}/adjunto")
def bajar_adjunto(lid: int, u=Depends(usuario_actual)):
    with db.conexion() as conn:
        r = uno(conn, "SELECT adjunto_nombre, adjunto_ruta FROM licencias WHERE id = ?", (lid,))
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
        r = uno(conn, """
            SELECT i.*, t.nombre_completo AS titular, x.nombre_completo AS interino,
                   v.secretaria AS vacante_secretaria, v.fecha_desde AS vacante_desde,
                   dt.nombre AS despacho_titular, dx.nombre AS despacho_interino, c.nombre AS cargo,
                   uc.nombre AS creado_por_nombre, um.nombre AS modificado_por_nombre
            FROM interinatos i
            LEFT JOIN personal t ON t.id = i.titular_id
            LEFT JOIN vacantes v ON v.id = i.vacante_id
            JOIN despachos dt ON dt.id = coalesce(t.despacho_id, v.despacho_id)
            JOIN personal x ON x.id = i.interino_id JOIN despachos dx ON dx.id = x.despacho_id
            JOIN cargos c ON c.codigo = i.cargo_codigo
            LEFT JOIN usuarios uc ON uc.id = i.creado_por
            LEFT JOIN usuarios um ON um.id = i.modificado_por
            WHERE i.id = ?""", (iid,))
    if not r:
        raise HTTPException(404, "Interinato inexistente")
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
    with db.conexion() as conn:
        nombre = config.NOMBRE_CIRCUNSCRIPCION
        if personal_id:
            r = uno(conn, "SELECT nombre_completo FROM personal WHERE id = ?", (personal_id,))
            if not r:
                raise HTTPException(404, "Funcionario inexistente")
            nombre = r["nombre_completo"]
        contenido = ics.generar(conn, desde, hasta, personal_id, nombre)
    return _ics_respuesta(contenido, f"pizarra_{desde}_{hasta}.ics")


@app.get("/ics/{token}.ics")
def feed_ics(token: str):
    """Feed de suscripción (sin inicio de sesión: el token largo es la llave)."""
    d, h = hoy() - timedelta(days=90), hoy() + timedelta(days=365)
    with db.conexion() as conn:
        if config.ICS_TOKEN_GENERAL and token == config.ICS_TOKEN_GENERAL:
            return _ics_respuesta(ics.generar(conn, d, h, None, config.NOMBRE_CIRCUNSCRIPCION), "pizarra.ics")
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise HTTPException(404)
        r = uno(conn, "SELECT id, nombre_completo FROM personal WHERE ics_token = ? AND activo = 1", (token,))
        if not r:
            raise HTTPException(404)
        return _ics_respuesta(ics.generar(conn, d, h, r["id"], r["nombre_completo"]), "mi_calendario.ics")


# ── Páginas ────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(STATIC / "index.html")


@app.get("/login", include_in_schema=False)
def pagina_login():
    return FileResponse(STATIC / "login.html")


@app.get("/manual", include_in_schema=False)
def pagina_manual():
    """Manual de usuario (no requiere sesión: no contiene datos reales)."""
    return FileResponse(STATIC / "manual.html")


@app.get("/salud", include_in_schema=False)
def salud():
    with db.conexion() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def cabeceras(request: Request, call_next):
    resp = await call_next(request)
    ruta = request.url.path
    if ruta.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    elif ruta.startswith("/static/") or ruta in ("/", "/login", "/manual"):
        # El navegador puede guardar la página, pero debe preguntar si cambió antes de usarla:
        # así, después de actualizar la Pizarra, todos ven la versión nueva sin Ctrl+F5.
        resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.exception_handler(401)
def _h_401(request: Request, e):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": e.detail}, 401)
    return RedirectResponse("/login")
