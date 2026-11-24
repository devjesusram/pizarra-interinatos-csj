"""Operaciones de escritura: licencias e interinatos (con validación y auditoría).

Cada operación corre dentro de db.escritura() (BEGIN IMMEDIATE): la validación y el
guardado ocurren sin que otro operador pueda escribir en el medio.
"""
import json
import sqlite3
from datetime import date, timedelta

from . import config
from .db import a_fecha, ahora_utc, escritura, iso, todos, uno
from .validaciones import (Bloqueado, ConflictoVersion, Hallazgo, Nivel, RequiereConfirmacion,
                           dias, f, validar_interinato, validar_licencia)

CAMPOS_LICENCIA = ("personal_id", "tipo_licencia_id", "fecha_inicio", "fecha_fin",
                   "organo_aprobador", "nro_resolucion", "correo_remitente", "correo_asunto",
                   "correo_fecha", "enlace_externo", "observaciones")
CAMPOS_INTERINATO = ("titular_id", "interino_id", "licencia_id", "fecha_inicio", "fecha_fin",
                     "acto_designacion", "observaciones")


def _json(o) -> str:
    return json.dumps(o, default=str, ensure_ascii=False)


def _normalizar(d: dict, campos) -> dict:
    return {k: iso(d.get(k)) if k in ("fecha_inicio", "fecha_fin", "correo_fecha") else d.get(k)
            for k in campos}


def auditar(conn, tabla, registro_id, accion, datos, usuario_id, hallazgos=None):
    conn.execute("""INSERT INTO auditoria (tabla, registro_id, accion, datos,
                                           advertencias_confirmadas, usuario_id)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 (tabla, registro_id, accion, _json(datos),
                  _json([h.a_dict() for h in hallazgos]) if hallazgos else None, usuario_id))


MENSAJES_BD = {
    "LIC_SOLAPE": ("L1", "Ya existe una licencia vigente que se cruza con esas fechas."),
    "INT_TITULAR_UNICO": ("R6", "El titular ya tiene un interino asignado en esas fechas."),
    "INT_INTERINO_UNICO": ("R5", "La persona ya cubre otro despacho en esas fechas."),
    "INT_PARES": ("R9", "Los interinatos son solo entre funcionarios del mismo cargo."),
}


def traducir_error_bd(e: sqlite3.Error) -> Bloqueado:
    """Última línea de defensa: errores de las reglas guardadas en la base de datos."""
    msg = str(e)
    for clave, (regla, texto) in MENSAJES_BD.items():
        if clave in msg:
            return Bloqueado([Hallazgo(Nivel.BLOQUEO, regla, texto)])
    return Bloqueado([Hallazgo(Nivel.BLOQUEO, "BD", "Datos inválidos: " + msg)])


def recalcular_conflictos(conn, personal_id: int) -> list[Hallazgo]:
    """Marca EN_CONFLICTO los interinatos donde la persona es interina y tiene licencia
    vigente en esas fechas; y vuelve a VIGENTE los que ya no están en conflicto.
    Devuelve avisos de los que pasaron a conflicto."""
    avisos = []
    for i in todos(conn, """
            SELECT i.id, i.estado, i.fecha_inicio, i.fecha_fin, t.nombre_completo AS titular,
                   EXISTS (SELECT 1 FROM licencias l
                           WHERE l.personal_id = i.interino_id AND l.estado = 'VIGENTE'
                             AND l.fecha_inicio <= i.fecha_fin AND l.fecha_fin >= i.fecha_inicio) AS choca
            FROM interinatos i JOIN personal t ON t.id = i.titular_id
            WHERE i.interino_id = ? AND i.estado IN ('VIGENTE', 'EN_CONFLICTO')""", (personal_id,)):
        nuevo = "EN_CONFLICTO" if i["choca"] else "VIGENTE"
        if nuevo != i["estado"]:
            conn.execute("UPDATE interinatos SET estado = ? WHERE id = ?", (nuevo, i["id"]))
            if nuevo == "EN_CONFLICTO":
                avisos.append(Hallazgo(Nivel.ADVERTENCIA, "L2",
                                       f"El interinato #{i['id']} (cubre a {i['titular']}, "
                                       f"{f(i['fecha_inicio'])}–{f(i['fecha_fin'])}) quedó EN CONFLICTO: "
                                       f"hay que reasignarlo o ajustarlo."))
    return avisos


def _quien_modifico(conn, tabla: str, reg_id: int) -> str:
    r = uno(conn, f"""SELECT u.nombre, coalesce(t.modificado_en, t.creado_en) AS cuando, t.estado
                      FROM {tabla} t LEFT JOIN usuarios u ON u.id = coalesce(t.modificado_por, t.creado_por)
                      WHERE t.id = ?""", (reg_id,))
    if not r:
        return "El registro ya no existe."
    from datetime import datetime
    cuando = datetime.fromisoformat(r["cuando"].replace("Z", "+00:00")).astimezone(config.ZONA)
    return (f"Este registro fue modificado por {r['nombre'] or 'otro usuario'} el "
            f"{cuando:%d/%m/%Y %H:%M} (estado actual: {r['estado']}). Recargue y vuelva a intentar.")


# ── Licencias ──────────────────────────────────────────────────────────

def crear_licencia(conn, d: dict, usuario_id: int) -> tuple[int, list[Hallazgo]]:
    datos = _normalizar(d, CAMPOS_LICENCIA)
    with escritura(conn):
        bloqueos = validar_licencia(conn, datos["personal_id"], datos["fecha_inicio"], datos["fecha_fin"])
        if bloqueos:
            raise Bloqueado(bloqueos)
        try:
            cur = conn.execute(f"""INSERT INTO licencias ({', '.join(CAMPOS_LICENCIA)}, creado_por)
                                   VALUES ({', '.join(':' + c for c in CAMPOS_LICENCIA)}, :u)""",
                               {**datos, "u": usuario_id})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        lic_id = cur.lastrowid
        avisos = recalcular_conflictos(conn, datos["personal_id"])
        auditar(conn, "licencias", lic_id, "CREAR", datos, usuario_id, avisos)
        return lic_id, avisos


def editar_licencia(conn, lic_id: int, d: dict, version: int, usuario_id: int) -> list[Hallazgo]:
    datos = _normalizar(d, CAMPOS_LICENCIA)
    with escritura(conn):
        actual = uno(conn, "SELECT personal_id, estado FROM licencias WHERE id = ?", (lic_id,))
        if not actual:
            raise LookupError("Licencia inexistente")
        if actual["estado"] != "VIGENTE":
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "E1", "No se puede editar una licencia anulada.")])
        bloqueos = validar_licencia(conn, datos["personal_id"], datos["fecha_inicio"],
                                    datos["fecha_fin"], excluir_id=lic_id)
        if bloqueos:
            raise Bloqueado(bloqueos)
        try:
            cur = conn.execute(f"""UPDATE licencias SET {', '.join(c + ' = :' + c for c in CAMPOS_LICENCIA)},
                                          version = version + 1, modificado_por = :u, modificado_en = :ahora
                                   WHERE id = :id AND version = :v""",
                               {**datos, "u": usuario_id, "id": lic_id, "v": version, "ahora": ahora_utc()})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        if cur.rowcount == 0:
            raise ConflictoVersion(_quien_modifico(conn, "licencias", lic_id))
        avisos = recalcular_conflictos(conn, datos["personal_id"])
        if actual["personal_id"] != datos["personal_id"]:
            avisos += recalcular_conflictos(conn, actual["personal_id"])
        auditar(conn, "licencias", lic_id, "MODIFICAR", datos, usuario_id, avisos)
        return avisos


def anular_licencia(conn, lic_id: int, motivo: str, version: int, usuario_id: int) -> None:
    with escritura(conn):
        actual = uno(conn, "SELECT personal_id FROM licencias WHERE id = ?", (lic_id,))
        if not actual:
            raise LookupError("Licencia inexistente")
        cur = conn.execute("""UPDATE licencias SET estado = 'ANULADA', motivo_anulacion = ?,
                                     version = version + 1, modificado_por = ?, modificado_en = ?
                              WHERE id = ? AND version = ? AND estado = 'VIGENTE'""",
                           (motivo, usuario_id, ahora_utc(), lic_id, version))
        if cur.rowcount == 0:
            raise ConflictoVersion(_quien_modifico(conn, "licencias", lic_id))
        recalcular_conflictos(conn, actual["personal_id"])
        auditar(conn, "licencias", lic_id, "ANULAR", {"motivo": motivo}, usuario_id)


def guardar_adjunto(conn, lic_id: int, nombre_original: str, ruta: str, usuario_id: int) -> None:
    with escritura(conn):
        cur = conn.execute("""UPDATE licencias SET adjunto_nombre = ?, adjunto_ruta = ?,
                                     modificado_por = ?, modificado_en = ?
                              WHERE id = ?""", (nombre_original, ruta, usuario_id, ahora_utc(), lic_id))
        if cur.rowcount == 0:
            raise LookupError("Licencia inexistente")
        auditar(conn, "licencias", lic_id, "MODIFICAR", {"adjunto": nombre_original}, usuario_id)


# ── Interinatos ────────────────────────────────────────────────────────

def _separar(h: list[Hallazgo]):
    return ([x for x in h if x.nivel == Nivel.BLOQUEO],
            [x for x in h if x.nivel == Nivel.ADVERTENCIA],
            [x for x in h if x.nivel == Nivel.INFO])


def _cargo_de(conn, personal_id):
    r = uno(conn, "SELECT cargo_codigo FROM personal WHERE id = ?", (personal_id,))
    return r["cargo_codigo"] if r else None


def crear_interinato(conn, d: dict, usuario_id: int,
                     confirmar_advertencias: bool = False) -> tuple[int, list[Hallazgo]]:
    datos = _normalizar(d, CAMPOS_INTERINATO)
    with escritura(conn):
        bloqueos, avisos, infos = _separar(validar_interinato(
            conn, datos["titular_id"], datos["interino_id"], datos["fecha_inicio"], datos["fecha_fin"]))
        if bloqueos:
            raise Bloqueado(bloqueos)
        if avisos and not confirmar_advertencias:
            raise RequiereConfirmacion(avisos + infos)
        try:
            cur = conn.execute(f"""INSERT INTO interinatos ({', '.join(CAMPOS_INTERINATO)}, cargo_codigo, creado_por)
                                   VALUES ({', '.join(':' + c for c in CAMPOS_INTERINATO)}, :cargo, :u)""",
                               {**datos, "cargo": _cargo_de(conn, datos["titular_id"]), "u": usuario_id})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        nuevo = cur.lastrowid
        auditar(conn, "interinatos", nuevo, "CREAR", datos, usuario_id, avisos + infos)
        return nuevo, infos


def editar_interinato(conn, int_id: int, d: dict, version: int, usuario_id: int,
                      confirmar_advertencias: bool = False) -> list[Hallazgo]:
    datos = _normalizar(d, CAMPOS_INTERINATO)
    with escritura(conn):
        actual = uno(conn, "SELECT estado FROM interinatos WHERE id = ?", (int_id,))
        if not actual:
            raise LookupError("Interinato inexistente")
        if actual["estado"] == "ANULADO":
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "E1", "No se puede editar un interinato anulado.")])
        bloqueos, avisos, infos = _separar(validar_interinato(
            conn, datos["titular_id"], datos["interino_id"], datos["fecha_inicio"],
            datos["fecha_fin"], excluir_id=int_id))
        if bloqueos:
            raise Bloqueado(bloqueos)
        if avisos and not confirmar_advertencias:
            raise RequiereConfirmacion(avisos + infos)
        try:
            # Si pasó la validación (R4), deja de estar en conflicto
            cur = conn.execute(f"""UPDATE interinatos SET {', '.join(c + ' = :' + c for c in CAMPOS_INTERINATO)},
                                          cargo_codigo = :cargo, estado = 'VIGENTE', version = version + 1,
                                          modificado_por = :u, modificado_en = :ahora
                                   WHERE id = :id AND version = :v""",
                               {**datos, "cargo": _cargo_de(conn, datos["titular_id"]), "u": usuario_id,
                                "id": int_id, "v": version, "ahora": ahora_utc()})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        if cur.rowcount == 0:
            raise ConflictoVersion(_quien_modifico(conn, "interinatos", int_id))
        auditar(conn, "interinatos", int_id, "MODIFICAR", datos, usuario_id, avisos + infos)
        return infos


def anular_interinato(conn, int_id: int, motivo: str, version: int, usuario_id: int) -> None:
    with escritura(conn):
        cur = conn.execute("""UPDATE interinatos SET estado = 'ANULADO', motivo_anulacion = ?,
                                     version = version + 1, modificado_por = ?, modificado_en = ?
                              WHERE id = ? AND version = ? AND estado <> 'ANULADO'""",
                           (motivo, usuario_id, ahora_utc(), int_id, version))
        if cur.rowcount == 0:
            if not uno(conn, "SELECT 1 AS x FROM interinatos WHERE id = ?", (int_id,)):
                raise LookupError("Interinato inexistente")
            raise ConflictoVersion(_quien_modifico(conn, "interinatos", int_id))
        auditar(conn, "interinatos", int_id, "ANULAR", {"motivo": motivo}, usuario_id)


def excesos_de_tope(conn, cargo: str, tope: int, hoy: date) -> list[str]:
    """Personas de ese cargo que, de hoy en adelante, cubren más despachos a la vez que 'tope'."""
    filas = todos(conn, """SELECT i.interino_id, x.nombre_completo, i.fecha_inicio, i.fecha_fin
                           FROM interinatos i JOIN personal x ON x.id = i.interino_id
                           WHERE i.cargo_codigo = ? AND i.estado <> 'ANULADO' AND i.fecha_fin >= ?""",
                  (cargo, iso(hoy)))
    por_persona: dict[int, list[dict]] = {}
    for f_ in filas:
        por_persona.setdefault(f_["interino_id"], []).append(f_)
    excedidos = []
    for lista in por_persona.values():
        if len(lista) <= tope:
            continue
        inicio = max(hoy, min(a_fecha(x["fecha_inicio"]) for x in lista))
        fin = max(a_fecha(x["fecha_fin"]) for x in lista)
        for d in dias(inicio, fin):
            n = sum(1 for x in lista if x["fecha_inicio"] <= d.isoformat() <= x["fecha_fin"])
            if n > tope:
                excedidos.append(f"{lista[0]['nombre_completo']} cubre {n} despachos el {f(d)}")
                break
    return excedidos


# ── Consultas para la pizarra ──────────────────────────────────────────

def alertas(conn, hoy: date, horizonte: int = 60) -> dict:
    """Ausentes sin cubrir en días hábiles (desde hoy) e interinatos en conflicto."""
    limite = hoy + timedelta(days=horizonte)
    inhabiles = {r["fecha"] for r in todos(conn, "SELECT fecha FROM dias_inhabiles")}
    lics = todos(conn, """
        SELECT l.id AS licencia_id, l.personal_id, p.nombre_completo, c.nombre AS cargo,
               c.orden_pizarra, d.nombre AS despacho, t.nombre AS tipo, l.fecha_inicio, l.fecha_fin
        FROM licencias l
        JOIN personal p ON p.id = l.personal_id
        JOIN cargos c ON c.codigo = p.cargo_codigo
        JOIN despachos d ON d.id = p.despacho_id
        JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
        WHERE l.estado = 'VIGENTE' AND l.fecha_fin >= ? AND l.fecha_inicio <= ?""",
                 (iso(hoy), iso(limite)))
    sin_cubrir = []
    for l in lics:
        cobertura = todos(conn, """SELECT fecha_inicio, fecha_fin FROM interinatos
                                   WHERE titular_id = ? AND estado <> 'ANULADO'
                                     AND fecha_inicio <= ? AND fecha_fin >= ?""",
                          (l["personal_id"], l["fecha_fin"], l["fecha_inicio"]))
        faltan = [d for d in dias(max(a_fecha(l["fecha_inicio"]), hoy), min(a_fecha(l["fecha_fin"]), limite))
                  if d.weekday() < 5 and d.isoformat() not in inhabiles
                  and not any(c["fecha_inicio"] <= d.isoformat() <= c["fecha_fin"] for c in cobertura)]
        if faltan:
            sin_cubrir.append({**l, "primer_dia": iso(faltan[0]), "ultimo_dia": iso(faltan[-1]),
                               "dias_sin_cubrir": len(faltan)})
    sin_cubrir.sort(key=lambda x: (x["primer_dia"], x["orden_pizarra"], x["nombre_completo"]))
    en_conflicto = todos(conn, """
        SELECT i.id, i.fecha_inicio, i.fecha_fin, i.version,
               t.nombre_completo AS titular, x.nombre_completo AS interino
        FROM interinatos i
        JOIN personal t ON t.id = i.titular_id
        JOIN personal x ON x.id = i.interino_id
        WHERE i.estado = 'EN_CONFLICTO' AND i.fecha_fin >= ?
        ORDER BY i.fecha_inicio""", (iso(hoy),))
    return {"sin_cubrir": sin_cubrir, "en_conflicto": en_conflicto}
