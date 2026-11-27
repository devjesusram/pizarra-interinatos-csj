"""Operaciones de escritura: licencias e interinatos (con validación y auditoría).

Cada operación corre dentro de db.escritura() (BEGIN IMMEDIATE): la validación y el
guardado ocurren sin que otro operador pueda escribir en el medio.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta

from . import config
from .db import SIN_FIN, a_fecha, ahora_utc, escritura, iso, todos, uno
from .validaciones import (Bloqueado, ConflictoVersion, Hallazgo, Nivel, RequiereConfirmacion,
                           dias, f, validar_interinato, validar_licencia)

CAMPOS_LICENCIA = ("personal_id", "tipo_licencia_id", "fecha_inicio", "fecha_fin",
                   "organo_aprobador", "nro_resolucion", "correo_remitente", "correo_asunto",
                   "correo_fecha", "enlace_externo", "observaciones")
CAMPOS_INTERINATO = ("titular_id", "vacante_id", "interino_id", "licencia_id", "fecha_inicio", "fecha_fin",
                     "acto_designacion", "observaciones", "despacho_texto")
CAMPOS_VACANTE = ("despacho_id", "cargo_codigo", "secretaria", "fecha_desde", "fecha_hasta", "observaciones")


def _json(o) -> str:
    return json.dumps(o, default=str, ensure_ascii=False)


def _normalizar(d: dict, campos) -> dict:
    return {k: iso(d.get(k)) if k in ("fecha_inicio", "fecha_fin", "correo_fecha", "fecha_desde", "fecha_hasta")
            else d.get(k) for k in campos}


def auditar(conn, tabla, registro_id, accion, datos, usuario_id, hallazgos=None):
    conn.execute("""INSERT INTO auditoria (tabla, registro_id, accion, datos,
                                           advertencias_confirmadas, usuario_id)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 (tabla, registro_id, accion, _json(datos),
                  _json([h.a_dict() for h in hallazgos]) if hallazgos else None, usuario_id))


MENSAJES_BD = {
    "LIC_SOLAPE": ("L1", "Ya existe una licencia vigente que se cruza con esas fechas."),
    "INT_TITULAR_UNICO": ("R6", "El titular ya tiene un interino asignado en esas fechas."),
    "INT_VACANTE_UNICA": ("R6", "El puesto vacante ya tiene a alguien a cargo en esas fechas."),
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
            SELECT i.id, i.estado, i.fecha_inicio, i.fecha_fin,
                   coalesce(t.nombre_completo, 'un puesto vacante') AS titular,
                   EXISTS (SELECT 1 FROM licencias l
                           WHERE l.personal_id = i.interino_id AND l.estado = 'VIGENTE'
                             AND l.fecha_inicio <= i.fecha_fin AND l.fecha_fin >= i.fecha_inicio) AS choca
            FROM interinatos i LEFT JOIN personal t ON t.id = i.titular_id
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


def _cargo_cubierto(conn, datos: dict):
    """Cargo de la persona ausente o del puesto vacante que se cubre."""
    if datos.get("vacante_id") is not None:
        r = uno(conn, "SELECT cargo_codigo FROM vacantes WHERE id = ?", (datos["vacante_id"],))
    else:
        r = uno(conn, "SELECT cargo_codigo FROM personal WHERE id = ?", (datos.get("titular_id"),))
    return r["cargo_codigo"] if r else None


def _datos_interinato(d: dict) -> dict:
    datos = _normalizar(d, CAMPOS_INTERINATO)
    datos["fecha_fin"] = datos["fecha_fin"] or SIN_FIN          # en blanco = sin fecha de desvinculación
    datos["despacho_texto"] = (datos["despacho_texto"] or "").strip() or None
    return datos


def crear_interinato(conn, d: dict, usuario_id: int,
                     confirmar_advertencias: bool = False) -> tuple[int, list[Hallazgo]]:
    datos = _datos_interinato(d)
    with escritura(conn):
        bloqueos, avisos, infos = _separar(validar_interinato(
            conn, datos["titular_id"], datos["interino_id"], datos["fecha_inicio"], datos["fecha_fin"],
            vacante_id=datos["vacante_id"]))
        if bloqueos:
            raise Bloqueado(bloqueos)
        if avisos and not confirmar_advertencias:
            raise RequiereConfirmacion(avisos + infos)
        try:
            cur = conn.execute(f"""INSERT INTO interinatos ({', '.join(CAMPOS_INTERINATO)}, cargo_codigo, creado_por)
                                   VALUES ({', '.join(':' + c for c in CAMPOS_INTERINATO)}, :cargo, :u)""",
                               {**datos, "cargo": _cargo_cubierto(conn, datos), "u": usuario_id})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        nuevo = cur.lastrowid
        auditar(conn, "interinatos", nuevo, "CREAR", datos, usuario_id, avisos + infos)
        return nuevo, infos


def editar_interinato(conn, int_id: int, d: dict, version: int, usuario_id: int,
                      confirmar_advertencias: bool = False) -> list[Hallazgo]:
    datos = _datos_interinato(d)
    with escritura(conn):
        actual = uno(conn, "SELECT estado, interino_id FROM interinatos WHERE id = ?", (int_id,))
        if not actual:
            raise LookupError("Interinato inexistente")
        if actual["estado"] == "ANULADO":
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "E1", "No se puede editar un interinato anulado.")])
        cambia_interino = actual["interino_id"] != datos["interino_id"]
        bloqueos, avisos, infos = _separar(validar_interinato(
            conn, datos["titular_id"], datos["interino_id"], datos["fecha_inicio"],
            datos["fecha_fin"], excluir_id=int_id, vacante_id=datos["vacante_id"]))
        if bloqueos:
            raise Bloqueado(bloqueos)
        if avisos and not confirmar_advertencias:
            raise RequiereConfirmacion(avisos + infos)
        try:
            # Si pasó la validación (R4), deja de estar en conflicto
            cur = conn.execute(f"""UPDATE interinatos SET {', '.join(c + ' = :' + c for c in CAMPOS_INTERINATO)},
                                          cargo_codigo = :cargo, estado = 'VIGENTE', version = version + 1,
                                          -- si cambia la persona, la vinculación anterior ya no vale
                                          vinculado = CASE WHEN :cambia THEN 0 ELSE vinculado END,
                                          vinculado_fecha = CASE WHEN :cambia THEN NULL ELSE vinculado_fecha END,
                                          vinculado_por = CASE WHEN :cambia THEN NULL ELSE vinculado_por END,
                                          vinculado_en = CASE WHEN :cambia THEN NULL ELSE vinculado_en END,
                                          vinculado_obs = CASE WHEN :cambia THEN NULL ELSE vinculado_obs END,
                                          desvinculado = CASE WHEN :fecha_fin >= :hoy THEN 0 ELSE desvinculado END,   -- el último día es hoy o después: todavía no se desvinculó
                                          desvinculado_por = CASE WHEN :fecha_fin >= :hoy THEN NULL ELSE desvinculado_por END,
                                          desvinculado_en = CASE WHEN :fecha_fin >= :hoy THEN NULL ELSE desvinculado_en END,
                                          modificado_por = :u, modificado_en = :ahora
                                   WHERE id = :id AND version = :v""",
                               {**datos, "cargo": _cargo_cubierto(conn, datos), "u": usuario_id,
                                "id": int_id, "v": version, "ahora": ahora_utc(), "cambia": int(cambia_interino),
                                "hoy": iso(datetime.now(config.ZONA).date())})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        if cur.rowcount == 0:
            raise ConflictoVersion(_quien_modifico(conn, "interinatos", int_id))
        auditar(conn, "interinatos", int_id, "MODIFICAR", datos, usuario_id, avisos + infos)
        return infos


def desvincular_interinato(conn, int_id: int, fecha, observacion: str | None, version: int,
                           usuario_id: int, hoy: date) -> None:
    """Acción manual: desvincula al interino en 'fecha' y registra quién lo hizo.
    El interino cubre las 24 horas de su último día y se lo desvincula al día siguiente,
    así que el último día del interinazgo (fecha_fin) queda en 'fecha' menos un día."""
    fecha = a_fecha(fecha)
    with escritura(conn):
        i = uno(conn, "SELECT fecha_inicio, estado FROM interinatos WHERE id = ?", (int_id,))
        if not i:
            raise LookupError("Interinazgo inexistente")
        if i["estado"] == "ANULADO":
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "E1", "No se puede desvincular un interinazgo anulado.")])
        if fecha > hoy:
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "D1", "La fecha de desvinculación no puede ser posterior a hoy. "
                                                           "Para una fecha futura, use «Editar» y cargue «Hasta».")])
        if fecha <= a_fecha(i["fecha_inicio"]):
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "D2", f"La desvinculación tiene que ser posterior al inicio del "
                                                           f"interinazgo ({f(i['fecha_inicio'])}): el interino cubre por lo "
                                                           f"menos ese día. Si nunca llegó a cubrir, use «Anular».")])
        ultimo = fecha - timedelta(days=1)
        cur = conn.execute("""UPDATE interinatos SET fecha_fin = ?, desvinculado = 1, desvinculado_por = ?,
                                     desvinculado_en = ?, desvinculado_obs = ?, version = version + 1,
                                     modificado_por = ?, modificado_en = ?
                              WHERE id = ? AND version = ?""",
                           (iso(ultimo), usuario_id, ahora_utc(), (observacion or "").strip() or None,
                            usuario_id, ahora_utc(), int_id, version))
        if cur.rowcount == 0:
            raise ConflictoVersion(_quien_modifico(conn, "interinatos", int_id))
        auditar(conn, "interinatos", int_id, "DESVINCULAR",
                {"fecha_desvinculacion": iso(fecha), "ultimo_dia": iso(ultimo), "observacion": observacion}, usuario_id)


def vincular_interinato(conn, int_id: int, fecha, observacion: str | None, version: int,
                        usuario_id: int, hoy: date) -> None:
    """Acción manual: confirma que el interino asumió y registra quién lo hizo y cuándo.
    No cambia las fechas del interinazgo; 'fecha' es el día en que quedó vinculado."""
    fecha = a_fecha(fecha)
    with escritura(conn):
        i = uno(conn, "SELECT fecha_inicio, fecha_fin, estado, vinculado FROM interinatos WHERE id = ?", (int_id,))
        if not i:
            raise LookupError("Interinazgo inexistente")
        if i["estado"] == "ANULADO":
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "E1", "No se puede vincular un interinazgo anulado.")])
        if i["vinculado"]:
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "V1", "Este interino ya figura como vinculado.")])
        if fecha > hoy:
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "V2", "La fecha de vinculación no puede ser posterior a hoy.")])
        if fecha > a_fecha(i["fecha_fin"]):
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "V3", f"La vinculación no puede ser posterior al último día del "
                                                           f"interinazgo ({f(i['fecha_fin'])}).")])
        cur = conn.execute("""UPDATE interinatos SET vinculado = 1, vinculado_fecha = ?, vinculado_por = ?,
                                     vinculado_en = ?, vinculado_obs = ?, version = version + 1,
                                     modificado_por = ?, modificado_en = ?
                              WHERE id = ? AND version = ?""",
                           (iso(fecha), usuario_id, ahora_utc(), (observacion or "").strip() or None,
                            usuario_id, ahora_utc(), int_id, version))
        if cur.rowcount == 0:
            raise ConflictoVersion(_quien_modifico(conn, "interinatos", int_id))
        auditar(conn, "interinatos", int_id, "VINCULAR",
                {"fecha_vinculacion": iso(fecha), "observacion": observacion}, usuario_id)


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
        from .validaciones import pico_simultaneo
        n, dia = pico_simultaneo(lista, hoy, a_fecha(SIN_FIN))
        if n > tope:
            excedidos.append(f"{lista[0]['nombre_completo']} cubre {n} despachos el {f(dia)}")
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
               coalesce(t.nombre_completo, 'un puesto vacante') AS titular, x.nombre_completo AS interino
        FROM interinatos i
        LEFT JOIN personal t ON t.id = i.titular_id
        JOIN personal x ON x.id = i.interino_id
        WHERE i.estado = 'EN_CONFLICTO' AND i.fecha_fin >= ?
        ORDER BY i.fecha_inicio""", (iso(hoy),))

    vacantes_sin_cubrir = []
    for v in todos(conn, """
            SELECT v.id AS vacante_id, v.cargo_codigo, v.secretaria, v.fecha_desde, v.fecha_hasta,
                   c.nombre AS cargo, c.orden_pizarra, d.nombre AS despacho
            FROM vacantes v JOIN cargos c ON c.codigo = v.cargo_codigo
            JOIN despachos d ON d.id = v.despacho_id
            WHERE v.fecha_desde <= ? AND (v.fecha_hasta IS NULL OR v.fecha_hasta >= ?)""",
                   (iso(limite), iso(hoy))):
        cobertura = todos(conn, """SELECT fecha_inicio, fecha_fin FROM interinatos
                                   WHERE vacante_id = ? AND estado <> 'ANULADO'""", (v["vacante_id"],))
        fin_v = min(a_fecha(v["fecha_hasta"]), limite) if v["fecha_hasta"] else limite
        faltan = [d for d in dias(max(a_fecha(v["fecha_desde"]), hoy), fin_v)
                  if d.weekday() < 5 and d.isoformat() not in inhabiles
                  and not any(c["fecha_inicio"] <= d.isoformat() <= c["fecha_fin"] for c in cobertura)]
        if faltan:
            vacantes_sin_cubrir.append({**v, "primer_dia": iso(faltan[0]), "ultimo_dia": iso(faltan[-1]),
                                        "dias_sin_cubrir": len(faltan)})
    vacantes_sin_cubrir.sort(key=lambda x: (x["primer_dia"], x["orden_pizarra"]))
    por_desvincular = todos(conn, """
        SELECT i.id, i.fecha_inicio, i.fecha_fin, x.nombre_completo AS interino,
               coalesce(t.nombre_completo, 'un puesto vacante') AS titular
        FROM interinatos i JOIN personal x ON x.id = i.interino_id
        LEFT JOIN personal t ON t.id = i.titular_id
        WHERE i.estado <> 'ANULADO' AND i.desvinculado = 0 AND i.fecha_fin < ?
        ORDER BY i.fecha_fin""", (iso(hoy),))
    return {"sin_cubrir": sin_cubrir, "en_conflicto": en_conflicto, "vacantes_sin_cubrir": vacantes_sin_cubrir,
            "por_desvincular": por_desvincular}


# ── Puestos vacantes ───────────────────────────────────────────────────

def _validar_vacante(datos: dict):
    if datos["fecha_hasta"] and datos["fecha_hasta"] < datos["fecha_desde"]:
        raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "R1", "La fecha de fin es anterior a la fecha de inicio.")])


def crear_vacante(conn, d: dict, usuario_id: int) -> int:
    datos = _normalizar(d, CAMPOS_VACANTE)
    _validar_vacante(datos)
    with escritura(conn):
        try:
            cur = conn.execute(f"""INSERT INTO vacantes ({', '.join(CAMPOS_VACANTE)}, creado_por)
                                   VALUES ({', '.join(':' + c for c in CAMPOS_VACANTE)}, :u)""",
                               {**datos, "u": usuario_id})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        auditar(conn, "vacantes", cur.lastrowid, "CREAR", datos, usuario_id)
        return cur.lastrowid


def editar_vacante(conn, vac_id: int, d: dict, version: int, usuario_id: int) -> None:
    datos = _normalizar(d, CAMPOS_VACANTE)
    _validar_vacante(datos)
    with escritura(conn):
        actual = uno(conn, "SELECT cargo_codigo FROM vacantes WHERE id = ?", (vac_id,))
        if not actual:
            raise LookupError("Puesto vacante inexistente")
        if actual["cargo_codigo"] != datos["cargo_codigo"] and uno(
                conn, "SELECT 1 AS x FROM interinatos WHERE vacante_id = ? AND estado <> 'ANULADO'", (vac_id,)):
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "R9", "No se puede cambiar el cargo: el puesto ya tiene "
                                                           "interinatos. Anúlelos primero o cree otro puesto.")])
        try:
            cur = conn.execute(f"""UPDATE vacantes SET {', '.join(c + ' = :' + c for c in CAMPOS_VACANTE)},
                                          version = version + 1
                                   WHERE id = :id AND version = :v""", {**datos, "id": vac_id, "v": version})
        except sqlite3.IntegrityError as e:
            raise traducir_error_bd(e)
        if cur.rowcount == 0:
            raise ConflictoVersion("Otro usuario modificó este puesto vacante. Recargue y vuelva a intentar.")
        auditar(conn, "vacantes", vac_id, "MODIFICAR", datos, usuario_id)
