"""Operaciones de escritura: licencias e interinatos (con validación y auditoría)."""
import json
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from .validaciones import (Bloqueado, ConflictoVersion, Hallazgo, Nivel, RequiereConfirmacion,
                           bloquear_personas, f, validar_interinato, validar_licencia)

CAMPOS_LICENCIA = ("personal_id", "tipo_licencia_id", "fecha_inicio", "fecha_fin",
                   "organo_aprobador", "nro_resolucion", "correo_remitente", "correo_asunto",
                   "correo_fecha", "enlace_externo", "observaciones")
CAMPOS_INTERINATO = ("titular_id", "interino_id", "licencia_id", "fecha_inicio", "fecha_fin",
                     "acto_designacion", "observaciones")


def _j(o):
    return Jsonb(o, dumps=lambda x: json.dumps(x, default=str, ensure_ascii=False))


def auditar(cur, tabla, registro_id, accion, datos, usuario_id, hallazgos=None):
    cur.execute("""INSERT INTO auditoria (tabla, registro_id, accion, datos,
                                          advertencias_confirmadas, usuario_id)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (tabla, registro_id, accion, _j(datos),
                 _j([h.a_dict() for h in hallazgos]) if hallazgos else None, usuario_id))


def _traducir_error_bd(e: Exception) -> Bloqueado:
    """Última línea de defensa: errores de restricciones de la base de datos."""
    if isinstance(e, psycopg.errors.ExclusionViolation):
        nombre = getattr(e.diag, "constraint_name", "") or ""
        msg = {
            "lic_sin_solape": "Ya existe una licencia vigente que se cruza con esas fechas.",
            "int_titular_unico": "El titular ya tiene un interino asignado en esas fechas.",
            "int_interino_unico_no_juez": "La persona ya cubre otro despacho en esas fechas.",
        }.get(nombre, "Las fechas se cruzan con un registro existente.")
        return Bloqueado([Hallazgo(Nivel.BLOQUEO, "BD", msg)])
    if isinstance(e, psycopg.errors.RaiseException):
        return Bloqueado([Hallazgo(Nivel.BLOQUEO, "R9", e.diag.message_primary or str(e))])
    return Bloqueado([Hallazgo(Nivel.BLOQUEO, "BD", "Datos inválidos: " + (e.diag.message_primary or str(e)))])


def recalcular_conflictos(cur, personal_id: int) -> list[Hallazgo]:
    """Marca EN_CONFLICTO los interinatos donde la persona es interina y tiene licencia
    vigente en esas fechas; y vuelve a VIGENTE los que ya no están en conflicto.
    Devuelve avisos de los que pasaron a conflicto."""
    cur.execute("""
        WITH calc AS (
          SELECT i.id, i.estado AS antes,
                 CASE WHEN EXISTS (SELECT 1 FROM licencias l
                                   WHERE l.personal_id = i.interino_id AND l.estado = 'VIGENTE'
                                     AND l.periodo && i.periodo)
                      THEN 'EN_CONFLICTO' ELSE 'VIGENTE' END AS despues
          FROM interinatos i
          WHERE i.interino_id = %s AND i.estado IN ('VIGENTE', 'EN_CONFLICTO'))
        UPDATE interinatos i SET estado = c.despues
        FROM calc c WHERE i.id = c.id AND c.antes <> c.despues
        RETURNING i.id, i.estado, i.fecha_inicio, i.fecha_fin,
                  (SELECT nombre_completo FROM personal WHERE id = i.titular_id) AS titular""",
                (personal_id,))
    return [Hallazgo(Nivel.ADVERTENCIA, "L2",
                     f"El interinato #{r['id']} (cubre a {r['titular']}, {f(r['fecha_inicio'])}–"
                     f"{f(r['fecha_fin'])}) quedó EN CONFLICTO: hay que reasignarlo o ajustarlo.")
            for r in cur.fetchall() if r["estado"] == "EN_CONFLICTO"]


# ── Licencias ──────────────────────────────────────────────────────────

def crear_licencia(conn, d: dict, usuario_id: int) -> tuple[int, list[Hallazgo]]:
    datos = {k: d.get(k) for k in CAMPOS_LICENCIA}
    with conn.transaction(), conn.cursor() as cur:
        bloquear_personas(cur, datos["personal_id"])
        bloqueos = validar_licencia(cur, datos["personal_id"], datos["fecha_inicio"], datos["fecha_fin"])
        if bloqueos:
            raise Bloqueado(bloqueos)
        try:
            with conn.transaction():
                cur.execute(f"""INSERT INTO licencias ({', '.join(CAMPOS_LICENCIA)}, creado_por)
                                VALUES ({', '.join('%(' + c + ')s' for c in CAMPOS_LICENCIA)}, %(u)s)
                                RETURNING id""", {**datos, "u": usuario_id})
        except psycopg.errors.IntegrityError as e:
            raise _traducir_error_bd(e)
        lic_id = cur.fetchone()["id"]
        avisos = recalcular_conflictos(cur, datos["personal_id"])
        auditar(cur, "licencias", lic_id, "CREAR", datos, usuario_id, avisos)
        return lic_id, avisos


def editar_licencia(conn, lic_id: int, d: dict, version: int, usuario_id: int) -> list[Hallazgo]:
    datos = {k: d.get(k) for k in CAMPOS_LICENCIA}
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT personal_id, estado FROM licencias WHERE id = %s", (lic_id,))
        actual = cur.fetchone()
        if not actual:
            raise LookupError("Licencia inexistente")
        if actual["estado"] != "VIGENTE":
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "E1", "No se puede editar una licencia anulada.")])
        bloquear_personas(cur, actual["personal_id"], datos["personal_id"])
        bloqueos = validar_licencia(cur, datos["personal_id"], datos["fecha_inicio"],
                                    datos["fecha_fin"], excluir_id=lic_id)
        if bloqueos:
            raise Bloqueado(bloqueos)
        try:
            with conn.transaction():
                cur.execute(f"""UPDATE licencias SET {', '.join(c + ' = %(' + c + ')s' for c in CAMPOS_LICENCIA)},
                                       version = version + 1, modificado_por = %(u)s, modificado_en = now()
                                WHERE id = %(id)s AND version = %(v)s RETURNING id""",
                            {**datos, "u": usuario_id, "id": lic_id, "v": version})
        except psycopg.errors.IntegrityError as e:
            raise _traducir_error_bd(e)
        if not cur.fetchone():
            raise ConflictoVersion(_quien_modifico(cur, "licencias", lic_id))
        avisos = recalcular_conflictos(cur, datos["personal_id"])
        if actual["personal_id"] != datos["personal_id"]:
            avisos += recalcular_conflictos(cur, actual["personal_id"])
        auditar(cur, "licencias", lic_id, "MODIFICAR", datos, usuario_id, avisos)
        return avisos


def anular_licencia(conn, lic_id: int, motivo: str, version: int, usuario_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT personal_id FROM licencias WHERE id = %s", (lic_id,))
        actual = cur.fetchone()
        if not actual:
            raise LookupError("Licencia inexistente")
        bloquear_personas(cur, actual["personal_id"])
        cur.execute("""UPDATE licencias SET estado = 'ANULADA', motivo_anulacion = %s,
                              version = version + 1, modificado_por = %s, modificado_en = now()
                       WHERE id = %s AND version = %s AND estado = 'VIGENTE' RETURNING id""",
                    (motivo, usuario_id, lic_id, version))
        if not cur.fetchone():
            raise ConflictoVersion(_quien_modifico(cur, "licencias", lic_id))
        recalcular_conflictos(cur, actual["personal_id"])
        auditar(cur, "licencias", lic_id, "ANULAR", {"motivo": motivo}, usuario_id)


def guardar_adjunto(conn, lic_id: int, nombre_original: str, ruta: str, usuario_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("""UPDATE licencias SET adjunto_nombre = %s, adjunto_ruta = %s,
                              modificado_por = %s, modificado_en = now()
                       WHERE id = %s RETURNING id""", (nombre_original, ruta, usuario_id, lic_id))
        if not cur.fetchone():
            raise LookupError("Licencia inexistente")
        auditar(cur, "licencias", lic_id, "MODIFICAR", {"adjunto": nombre_original}, usuario_id)


# ── Interinatos ────────────────────────────────────────────────────────

def _separar(h: list[Hallazgo]):
    return ([x for x in h if x.nivel == Nivel.BLOQUEO],
            [x for x in h if x.nivel == Nivel.ADVERTENCIA],
            [x for x in h if x.nivel == Nivel.INFO])


def crear_interinato(conn, d: dict, usuario_id: int,
                     confirmar_advertencias: bool = False) -> tuple[int, list[Hallazgo]]:
    datos = {k: d.get(k) for k in CAMPOS_INTERINATO}
    with conn.transaction(), conn.cursor() as cur:
        bloquear_personas(cur, datos["titular_id"], datos["interino_id"])
        bloqueos, avisos, infos = _separar(validar_interinato(
            cur, datos["titular_id"], datos["interino_id"], datos["fecha_inicio"], datos["fecha_fin"]))
        if bloqueos:
            raise Bloqueado(bloqueos)
        if avisos and not confirmar_advertencias:
            raise RequiereConfirmacion(avisos + infos)
        try:
            with conn.transaction():
                cur.execute(f"""INSERT INTO interinatos ({', '.join(CAMPOS_INTERINATO)}, creado_por)
                                VALUES ({', '.join('%(' + c + ')s' for c in CAMPOS_INTERINATO)}, %(u)s)
                                RETURNING id""", {**datos, "u": usuario_id})
        except psycopg.errors.IntegrityError as e:
            raise _traducir_error_bd(e)
        except psycopg.errors.RaiseException as e:
            raise _traducir_error_bd(e)
        nuevo = cur.fetchone()["id"]
        auditar(cur, "interinatos", nuevo, "CREAR", datos, usuario_id, avisos + infos)
        return nuevo, infos


def editar_interinato(conn, int_id: int, d: dict, version: int, usuario_id: int,
                      confirmar_advertencias: bool = False) -> list[Hallazgo]:
    datos = {k: d.get(k) for k in CAMPOS_INTERINATO}
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT titular_id, interino_id, estado FROM interinatos WHERE id = %s", (int_id,))
        actual = cur.fetchone()
        if not actual:
            raise LookupError("Interinato inexistente")
        if actual["estado"] == "ANULADO":
            raise Bloqueado([Hallazgo(Nivel.BLOQUEO, "E1", "No se puede editar un interinato anulado.")])
        bloquear_personas(cur, actual["titular_id"], actual["interino_id"],
                          datos["titular_id"], datos["interino_id"])
        bloqueos, avisos, infos = _separar(validar_interinato(
            cur, datos["titular_id"], datos["interino_id"], datos["fecha_inicio"],
            datos["fecha_fin"], excluir_id=int_id))
        if bloqueos:
            raise Bloqueado(bloqueos)
        if avisos and not confirmar_advertencias:
            raise RequiereConfirmacion(avisos + infos)
        try:
            with conn.transaction():
                # Si pasó la validación (R4), deja de estar en conflicto
                cur.execute(f"""UPDATE interinatos SET {', '.join(c + ' = %(' + c + ')s' for c in CAMPOS_INTERINATO)},
                                       estado = 'VIGENTE', version = version + 1,
                                       modificado_por = %(u)s, modificado_en = now()
                                WHERE id = %(id)s AND version = %(v)s RETURNING id""",
                            {**datos, "u": usuario_id, "id": int_id, "v": version})
        except (psycopg.errors.IntegrityError, psycopg.errors.RaiseException) as e:
            raise _traducir_error_bd(e)
        if not cur.fetchone():
            raise ConflictoVersion(_quien_modifico(cur, "interinatos", int_id))
        auditar(cur, "interinatos", int_id, "MODIFICAR", datos, usuario_id, avisos + infos)
        return infos


def anular_interinato(conn, int_id: int, motivo: str, version: int, usuario_id: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("""UPDATE interinatos SET estado = 'ANULADO', motivo_anulacion = %s,
                              version = version + 1, modificado_por = %s, modificado_en = now()
                       WHERE id = %s AND version = %s AND estado <> 'ANULADO' RETURNING id""",
                    (motivo, usuario_id, int_id, version))
        if not cur.fetchone():
            cur.execute("SELECT 1 FROM interinatos WHERE id = %s", (int_id,))
            if not cur.fetchone():
                raise LookupError("Interinato inexistente")
            raise ConflictoVersion(_quien_modifico(cur, "interinatos", int_id))
        auditar(cur, "interinatos", int_id, "ANULAR", {"motivo": motivo}, usuario_id)


def _quien_modifico(cur, tabla: str, reg_id: int) -> str:
    cur.execute(f"""SELECT u.nombre, coalesce(t.modificado_en, t.creado_en) AS cuando, t.estado
                    FROM {tabla} t LEFT JOIN usuarios u
                      ON u.id = coalesce(t.modificado_por, t.creado_por)
                    WHERE t.id = %s""", (reg_id,))
    r = cur.fetchone()
    if not r:
        return "El registro ya no existe."
    from . import config
    cuando = r["cuando"].astimezone(config.ZONA).strftime("%d/%m/%Y %H:%M")
    return (f"Este registro fue modificado por {r['nombre'] or 'otro usuario'} el {cuando} "
            f"(estado actual: {r['estado']}). Recargue y vuelva a intentar.")


# ── Consultas para la pizarra ──────────────────────────────────────────

def alertas(cur, hoy: date, dias: int = 60) -> dict:
    """Ausentes sin cubrir (desde hoy en adelante) e interinatos en conflicto."""
    cur.execute("""
        WITH dias AS (
          SELECT l.id AS licencia_id, g.d::date AS dia
          FROM licencias l
          CROSS JOIN LATERAL generate_series(greatest(l.fecha_inicio, %(hoy)s::date),
                                             least(l.fecha_fin, %(hoy)s::date + %(dias)s), '1 day') g(d)
          WHERE l.estado = 'VIGENTE' AND l.fecha_fin >= %(hoy)s::date
            AND extract(isodow FROM g.d) < 6
            AND NOT EXISTS (SELECT 1 FROM dias_inhabiles x WHERE x.fecha = g.d::date)
            AND NOT EXISTS (SELECT 1 FROM interinatos i
                            WHERE i.titular_id = l.personal_id AND i.estado <> 'ANULADO'
                              AND i.periodo @> g.d::date))
        SELECT l.id AS licencia_id, l.personal_id, p.nombre_completo, c.nombre AS cargo,
               d.nombre AS despacho, t.nombre AS tipo, l.fecha_inicio, l.fecha_fin,
               min(x.dia) AS primer_dia, max(x.dia) AS ultimo_dia, count(*) AS dias_sin_cubrir
        FROM dias x
        JOIN licencias l ON l.id = x.licencia_id
        JOIN personal p ON p.id = l.personal_id
        JOIN cargos c ON c.codigo = p.cargo_codigo
        JOIN despachos d ON d.id = p.despacho_id
        JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
        GROUP BY l.id, p.id, c.nombre, d.nombre, t.nombre, c.orden_pizarra
        ORDER BY min(x.dia), c.orden_pizarra, p.nombre_completo""", {"hoy": hoy, "dias": dias})
    sin_cubrir = cur.fetchall()
    cur.execute("""SELECT i.id, i.fecha_inicio, i.fecha_fin, i.version,
                          t.nombre_completo AS titular, x.nombre_completo AS interino
                   FROM interinatos i
                   JOIN personal t ON t.id = i.titular_id
                   JOIN personal x ON x.id = i.interino_id
                   WHERE i.estado = 'EN_CONFLICTO' AND i.fecha_fin >= %s
                   ORDER BY i.fecha_inicio""", (hoy,))
    return {"sin_cubrir": sin_cubrir, "en_conflicto": cur.fetchall()}
