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

from .db import a_fecha, iso, todos, uno


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
    return a_fecha(d).strftime("%d/%m/%Y")


def dias(ini: date, fin: date):
    d = ini
    while d <= fin:
        yield d
        d += timedelta(days=1)


def _contiene(periodos, d: date) -> bool:
    s = d.isoformat()
    return any(p["fecha_inicio"] <= s <= p["fecha_fin"] for p in periodos)


def validar_interinato(conn, titular_id: int, interino_id: int, ini, fin,
                       excluir_id: int | None = None) -> list[Hallazgo]:
    B, A, I = Nivel.BLOQUEO, Nivel.ADVERTENCIA, Nivel.INFO
    ini, fin = a_fecha(ini), a_fecha(fin)

    # R1, R2
    if fin < ini:
        return [Hallazgo(B, "R1", "La fecha de fin es anterior a la fecha de inicio.")]
    if titular_id == interino_id:
        return [Hallazgo(B, "R2", "Un funcionario no puede cubrirse a sí mismo.")]

    p = {"tit": titular_id, "int": interino_id, "ini": iso(ini), "fin": iso(fin), "exc": excluir_id}

    per = {r["id"]: r for r in todos(conn, """
        SELECT p.id, p.nombre_completo, p.activo, p.cargo_codigo, c.nombre AS cargo,
               c.max_interinatos_simultaneos AS tope
        FROM personal p JOIN cargos c ON c.codigo = p.cargo_codigo
        WHERE p.id IN (:tit, :int)""", p)}
    if titular_id not in per or interino_id not in per:
        return [Hallazgo(B, "R0", "Funcionario inexistente.")]
    tit, inte = per[titular_id], per[interino_id]
    nom, nom_tit = inte["nombre_completo"], tit["nombre_completo"]

    # R9: solo entre pares
    if tit["cargo_codigo"] != inte["cargo_codigo"]:
        return [Hallazgo(B, "R9", f"Los interinatos son solo entre pares: {nom} es {inte['cargo']} "
                                  f"y el titular es {tit['cargo']}.")]

    h: list[Hallazgo] = []

    # R3: personal inactivo
    for r in (tit, inte):
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
        SELECT i.fecha_inicio, i.fecha_fin, t.nombre_completo AS titular, d.nombre AS despacho
        FROM interinatos i
        JOIN personal t  ON t.id = i.titular_id
        JOIN despachos d ON d.id = t.despacho_id
        WHERE i.interino_id = :int AND i.estado <> 'ANULADO'
          AND i.fecha_inicio <= :fin AND i.fecha_fin >= :ini
          AND (:exc IS NULL OR i.id <> :exc)
        ORDER BY i.fecha_inicio""", p)
    pico, dia_pico = 0, None
    for d in dias(ini, fin):
        n = sum(1 for c in cubre if c["fecha_inicio"] <= d.isoformat() <= c["fecha_fin"])
        if n > pico:
            pico, dia_pico = n, d
    tope = inte["tope"]
    if tope is not None and pico + 1 > tope:
        for r in cubre:
            h.append(Hallazgo(B, "R5", f"{nom} ya es interino de {r['titular']} ({r['despacho']}) "
                                       f"del {f(r['fecha_inicio'])} al {f(r['fecha_fin'])}."))
    elif pico >= 1:
        h.append(Hallazgo(I, "R5-info", f"{nom} cubrirá {pico + 1} despachos simultáneamente "
                                        f"(desde el {f(dia_pico)}), además del propio."))

    # R6: el titular ya tiene interino
    for r in todos(conn, """
            SELECT i.fecha_inicio, i.fecha_fin, x.nombre_completo AS interino
            FROM interinatos i JOIN personal x ON x.id = i.interino_id
            WHERE i.titular_id = :tit AND i.estado <> 'ANULADO'
              AND i.fecha_inicio <= :fin AND i.fecha_fin >= :ini
              AND (:exc IS NULL OR i.id <> :exc)
            ORDER BY i.fecha_inicio""", p):
        h.append(Hallazgo(B, "R6", f"{nom_tit} ya está cubierto por {r['interino']} "
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

    # R8 (advertencia): días del período sin licencia registrada del titular
    lic_tit = todos(conn, """SELECT fecha_inicio, fecha_fin FROM licencias
                             WHERE personal_id = :tit AND estado = 'VIGENTE'
                               AND fecha_inicio <= :fin AND fecha_fin >= :ini""", p)
    n = sum(1 for d in dias(ini, fin) if not _contiene(lic_tit, d))
    if n > 0:
        h.append(Hallazgo(A, "R8", f"{nom_tit} no tiene licencia registrada en {n} día(s) "
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
