"""Reglas de control de fechas.

El sistema NO decide reemplazos: solo verifica que lo que carga el operador sea posible.

Niveles:
  BLOQUEO      -> no se guarda.
  ADVERTENCIA  -> se guarda solo si el operador confirma (queda en auditoría).
  INFO         -> se muestra y se guarda en auditoría; no requiere confirmación.

Todas las fechas son inclusivas. Dos períodos [a1, a2] y [b1, b2] se cruzan si
a1 <= b2 y b1 <= a2.
"""
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import Enum

from .db import SIN_FIN, a_fecha, iso, todos, uno


class Nivel(str, Enum):
    BLOQUEO = "BLOQUEO"
    ADVERTENCIA = "ADVERTENCIA"
    INFO = "INFO"


@dataclass
class Hallazgo:
    nivel: Nivel
    regla: str
    mensaje: str

    def a_dict(self):
        d = asdict(self)
        d["nivel"] = self.nivel.value
        return d


class Bloqueado(Exception):
    def __init__(self, hallazgos: list[Hallazgo]):
        super().__init__("; ".join(h.mensaje for h in hallazgos))
        self.hallazgos = hallazgos


class RequiereConfirmacion(Exception):
    def __init__(self, hallazgos: list[Hallazgo]):
        super().__init__("; ".join(h.mensaje for h in hallazgos))
        self.hallazgos = hallazgos


class ConflictoVersion(Exception):
    """Otro operador modificó el registro mientras se editaba (R10)."""


def f(d) -> str:
    if iso(d) == SIN_FIN:
        return "(sin fecha de desvinculación)"
    return a_fecha(d).strftime("%d/%m/%Y")


def pico_simultaneo(periodos, ini: date, fin: date):
    """Máximo de períodos que se superponen en un mismo día dentro de [ini, fin], y ese día.
    Basta con mirar el inicio del rango y el inicio de cada período (no recorre día por día,
    así funciona también con períodos sin fecha de fin)."""
    candidatos = {iso(ini)} | {p["fecha_inicio"] for p in periodos if iso(ini) <= p["fecha_inicio"] <= iso(fin)}
    pico, dia = 0, None
    for d in sorted(candidatos):
        n = sum(1 for p in periodos if p["fecha_inicio"] <= d <= p["fecha_fin"])
        if n > pico:
            pico, dia = n, d
    return pico, dia


def dias(ini: date, fin: date):
    d = ini
    while d <= fin:
        yield d
        d += timedelta(days=1)


def _contiene(periodos, d: date) -> bool:
    s = d.isoformat()
    return any(p["fecha_inicio"] <= s <= p["fecha_fin"] for p in periodos)


def etiqueta_vacante(v: dict) -> str:
    """'el puesto vacante de Actuario/a Judicial (Sria. Nº 2) en Juzgado ...'"""
    sria = f" (Sria. {v['secretaria']})" if v.get("secretaria") else ""
    return f"el puesto vacante de {v['cargo']}{sria} en {v['despacho']}"


def validar_interinato(conn, titular_id: int | None, interino_id: int, ini, fin,
                       excluir_id: int | None = None, vacante_id: int | None = None) -> list[Hallazgo]:
    """Valida que 'interino_id' pueda cubrir a una persona ausente (titular_id) o a un
    puesto vacante (vacante_id) entre 'ini' y 'fin'."""
    B, A, I = Nivel.BLOQUEO, Nivel.ADVERTENCIA, Nivel.INFO
    ini, fin = a_fecha(ini), a_fecha(fin)

    if (titular_id is None) == (vacante_id is None):
        return [Hallazgo(B, "R0", "Indique a quién cubre: una persona ausente o un puesto vacante.")]
    # R1, R2
    if fin < ini:
        return [Hallazgo(B, "R1", "La fecha de fin es anterior a la fecha de inicio.")]
    if titular_id is not None and titular_id == interino_id:
        return [Hallazgo(B, "R2", "Un funcionario no puede cubrirse a sí mismo.")]

    p = {"tit": titular_id, "vac": vacante_id, "int": interino_id, "ini": iso(ini), "fin": iso(fin),
         "exc": excluir_id}

    per = {r["id"]: r for r in todos(conn, """
        SELECT p.id, p.nombre_completo, p.activo, p.cargo_codigo, c.nombre AS cargo,
               c.max_interinatos_simultaneos AS tope
        FROM personal p JOIN cargos c ON c.codigo = p.cargo_codigo
        WHERE p.id IN (:tit, :int)""", p)}
    if interino_id not in per or (titular_id is not None and titular_id not in per):
        return [Hallazgo(B, "R0", "Funcionario inexistente.")]
    inte = per[interino_id]
    nom = inte["nombre_completo"]

    if vacante_id is not None:
        vac = uno(conn, """SELECT v.*, c.nombre AS cargo, d.nombre AS despacho
                           FROM vacantes v JOIN cargos c ON c.codigo = v.cargo_codigo
                           JOIN despachos d ON d.id = v.despacho_id WHERE v.id = :vac""", p)
        if not vac:
            return [Hallazgo(B, "R0", "Puesto vacante inexistente.")]
        cargo_cubierto, nombre_cargo_cubierto = vac["cargo_codigo"], vac["cargo"]
        cubierto = etiqueta_vacante(vac)
    else:
        tit = per[titular_id]
        cargo_cubierto, nombre_cargo_cubierto = tit["cargo_codigo"], tit["cargo"]
        cubierto = tit["nombre_completo"]

    # R9: solo entre pares
    if inte["cargo_codigo"] != cargo_cubierto:
        return [Hallazgo(B, "R9", f"Los interinatos son solo entre pares: {nom} es {inte['cargo']} "
                                  f"y se quiere cubrir un cargo de {nombre_cargo_cubierto}.")]

    h: list[Hallazgo] = []

    # R3: personal inactivo
    for r in ([inte] if titular_id is None else [per[titular_id], inte]):
        if not r["activo"]:
            h.append(Hallazgo(B, "R3", f"{r['nombre_completo']} está dado de baja."))

    # R4: el interino está de licencia
    for r in todos(conn, """
            SELECT l.fecha_inicio, l.fecha_fin, t.nombre AS tipo
            FROM licencias l JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
            WHERE l.personal_id = :int AND l.estado = 'VIGENTE'
              AND l.fecha_inicio <= :fin AND l.fecha_fin >= :ini
            ORDER BY l.fecha_inicio""", p):
        h.append(Hallazgo(B, "R4", f"{nom} está de licencia ({r['tipo']}) del "
                                   f"{f(r['fecha_inicio'])} al {f(r['fecha_fin'])}."))

    # R5: tope de cobertura simultánea según el cargo (NULL = sin límite)
    cubre = todos(conn, """
        SELECT i.fecha_inicio, i.fecha_fin, d.nombre AS despacho,
               coalesce(t.nombre_completo, 'un puesto vacante') AS titular
        FROM interinatos i
        LEFT JOIN personal t ON t.id = i.titular_id
        LEFT JOIN vacantes v ON v.id = i.vacante_id
        JOIN despachos d ON d.id = coalesce(t.despacho_id, v.despacho_id)
        WHERE i.interino_id = :int AND i.estado <> 'ANULADO'
          AND i.fecha_inicio <= :fin AND i.fecha_fin >= :ini
          AND (:exc IS NULL OR i.id <> :exc)
        ORDER BY i.fecha_inicio""", p)
    pico, dia_pico = pico_simultaneo(cubre, ini, fin)
    tope = inte["tope"]
    if tope is not None and pico + 1 > tope:
        for r in cubre:
            h.append(Hallazgo(B, "R5", f"{nom} ya es interino de {r['titular']} ({r['despacho']}) "
                                       f"del {f(r['fecha_inicio'])} al {f(r['fecha_fin'])}."))
    elif pico >= 1:
        h.append(Hallazgo(I, "R5-info", f"{nom} cubrirá {pico + 1} despachos simultáneamente "
                                        f"(desde el {f(dia_pico)}), además del propio."))

    # R6: lo cubierto ya tiene a alguien a cargo
    if vacante_id is not None:
        for r in todos(conn, """
                SELECT i.fecha_inicio, i.fecha_fin, x.nombre_completo AS interino
                FROM interinatos i JOIN personal x ON x.id = i.interino_id
                WHERE i.vacante_id = :vac AND i.estado <> 'ANULADO'
                  AND i.fecha_inicio <= :fin AND i.fecha_fin >= :ini
                  AND (:exc IS NULL OR i.id <> :exc)
                ORDER BY i.fecha_inicio""", p):
            h.append(Hallazgo(B, "R6", f"{cubierto[0].upper() + cubierto[1:]} ya está a cargo de {r['interino']} "
                                       f"del {f(r['fecha_inicio'])} al {f(r['fecha_fin'])}."))
    else:
        for r in todos(conn, """
                SELECT i.fecha_inicio, i.fecha_fin, x.nombre_completo AS interino
                FROM interinatos i JOIN personal x ON x.id = i.interino_id
                WHERE i.titular_id = :tit AND i.estado <> 'ANULADO'
                  AND i.fecha_inicio <= :fin AND i.fecha_fin >= :ini
                  AND (:exc IS NULL OR i.id <> :exc)
                ORDER BY i.fecha_inicio""", p):
            h.append(Hallazgo(B, "R6", f"{cubierto} ya está cubierto por {r['interino']} "
                                       f"del {f(r['fecha_inicio'])} al {f(r['fecha_fin'])}."))

    # R7: el interino está ausente y cubierto por otra persona
    for r in todos(conn, """
            SELECT i.fecha_inicio, i.fecha_fin, x.nombre_completo AS quien
            FROM interinatos i JOIN personal x ON x.id = i.interino_id
            WHERE i.titular_id = :int AND i.estado <> 'ANULADO'
              AND i.fecha_inicio <= :fin AND i.fecha_fin >= :ini
              AND (:exc IS NULL OR i.id <> :exc)""", p):
        h.append(Hallazgo(B, "R7", f"{nom} figura ausente (lo cubre {r['quien']}) del "
                                   f"{f(r['fecha_inicio'])} al {f(r['fecha_fin'])}."))

    # R8 (advertencia): días del período en que no corresponde cubrir.
    # Sin fecha de desvinculación se revisa solo el comienzo (no hay un final contra el cual contar).
    abierto = iso(fin) == SIN_FIN
    fin_conteo = min(fin, ini + timedelta(days=730))
    if vacante_id is not None:
        periodo = [{"fecha_inicio": vac["fecha_desde"], "fecha_fin": vac["fecha_hasta"] or SIN_FIN}]
        hasta_vac = a_fecha(vac["fecha_hasta"]) if vac["fecha_hasta"] else None
        n = sum(1 for d in dias(ini, min(fin_conteo, hasta_vac or fin_conteo) if abierto else fin_conteo)
                if not _contiene(periodo, d))
        if n > 0:
            hasta = f" hasta el {f(vac['fecha_hasta'])}" if vac["fecha_hasta"] else ""
            h.append(Hallazgo(A, "R8", f"{n} día(s) de este período quedan fuera de la vacancia "
                                       f"(vacante desde el {f(vac['fecha_desde'])}{hasta})."))
    else:
        lic_tit = todos(conn, """SELECT fecha_inicio, fecha_fin FROM licencias
                                 WHERE personal_id = :tit AND estado = 'VIGENTE'
                                   AND fecha_inicio <= :fin AND fecha_fin >= :ini""", p)
        if abierto:
            if not _contiene(lic_tit, ini):
                h.append(Hallazgo(A, "R8", f"{cubierto} no tiene licencia registrada al comienzo del interinazgo "
                                           f"({f(ini)})."))
        else:
            n = sum(1 for d in dias(ini, fin_conteo) if not _contiene(lic_tit, d))
            if n > 0:
                h.append(Hallazgo(A, "R8", f"{cubierto} no tiene licencia registrada en {n} día(s) "
                                           f"de este período."))
    return h


def validar_licencia(conn, personal_id: int, ini, fin, excluir_id: int | None = None) -> list[Hallazgo]:
    """Una licencia oficial nunca se bloquea por interinatos: solo por fechas
    inválidas o por otra licencia vigente de la misma persona."""
    B = Nivel.BLOQUEO
    ini, fin = a_fecha(ini), a_fecha(fin)
    if fin < ini:
        return [Hallazgo(B, "R1", "La fecha de fin es anterior a la fecha de inicio.")]
    per = uno(conn, "SELECT nombre_completo, activo FROM personal WHERE id = ?", (personal_id,))
    if not per:
        return [Hallazgo(B, "R0", "Funcionario inexistente.")]
    h = []
    if not per["activo"]:
        h.append(Hallazgo(B, "R3", f"{per['nombre_completo']} está dado de baja."))
    for r in todos(conn, """
            SELECT l.fecha_inicio, l.fecha_fin, t.nombre AS tipo
            FROM licencias l JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
            WHERE l.personal_id = :per AND l.estado = 'VIGENTE'
              AND l.fecha_inicio <= :fin AND l.fecha_fin >= :ini
              AND (:exc IS NULL OR l.id <> :exc)""",
            {"per": personal_id, "ini": iso(ini), "fin": iso(fin), "exc": excluir_id}):
        h.append(Hallazgo(B, "L1", f"{per['nombre_completo']} ya tiene una licencia ({r['tipo']}) "
                                   f"del {f(r['fecha_inicio'])} al {f(r['fecha_fin'])}."))
    return h
