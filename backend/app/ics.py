"""Exportación a iCalendar (.ics): Google Calendar, Outlook, iPhone, Android."""
from datetime import date, datetime, timedelta, timezone

from icalendar import Calendar, Event

SQL_LICENCIAS = """
  SELECT l.id, l.fecha_inicio, l.fecha_fin, l.estado, l.version, l.nro_resolucion,
         p.nombre_completo, t.nombre AS tipo, d.nombre AS despacho,
         (SELECT string_agg(x.nombre_completo, ', ') FROM interinatos i
            JOIN personal x ON x.id = i.interino_id
           WHERE i.titular_id = l.personal_id AND i.estado <> 'ANULADO'
             AND i.periodo && l.periodo) AS cubierto_por
  FROM licencias l
  JOIN personal p ON p.id = l.personal_id
  JOIN despachos d ON d.id = p.despacho_id
  JOIN tipos_licencia t ON t.id = l.tipo_licencia_id
  WHERE l.periodo && daterange(%(desde)s::date, %(hasta)s::date, '[]') {filtro}"""

SQL_INTERINATOS = """
  SELECT i.id, i.fecha_inicio, i.fecha_fin, i.estado, i.version, i.acto_designacion,
         t.nombre_completo AS titular, x.nombre_completo AS interino, d.nombre AS despacho
  FROM interinatos i
  JOIN personal t ON t.id = i.titular_id
  JOIN personal x ON x.id = i.interino_id
  JOIN despachos d ON d.id = t.despacho_id
  WHERE i.periodo && daterange(%(desde)s::date, %(hasta)s::date, '[]') {filtro}"""


def _evento(uid, resumen, ini: date, fin: date, anulado: bool, version: int, descripcion: str):
    e = Event()
    e.add("uid", uid)
    e.add("summary", resumen)
    e.add("dtstart", ini)                       # date -> evento de día completo
    e.add("dtend", fin + timedelta(days=1))     # DTEND es EXCLUSIVO en iCalendar
    e.add("dtstamp", datetime.now(timezone.utc))
    e.add("sequence", version)
    e.add("status", "CANCELLED" if anulado else "CONFIRMED")
    e.add("transp", "TRANSPARENT")
    if descripcion:
        e.add("description", descripcion)
    return e


def generar(cur, desde: date, hasta: date, personal_id: int | None, nombre: str) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Pizarra de Interinatos//ES")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", nombre)
    p = {"desde": desde, "hasta": hasta, "per": personal_id}

    filtro = "AND l.personal_id = %(per)s" if personal_id else ""
    cur.execute(SQL_LICENCIAS.format(filtro=filtro), p)
    for r in cur.fetchall():
        quien = "" if personal_id else f"{r['nombre_completo']} – "
        desc = [f"Despacho: {r['despacho']}"]
        if r["nro_resolucion"]:
            desc.append(f"Resolución: {r['nro_resolucion']}")
        desc.append(f"Cubierto por: {r['cubierto_por'] or 'SIN INTERINO ASIGNADO'}")
        cal.add_component(_evento(f"lic-{r['id']}@pizarra-interinatos", f"{quien}Licencia ({r['tipo']})",
                                  r["fecha_inicio"], r["fecha_fin"], r["estado"] == "ANULADA",
                                  r["version"], "\n".join(desc)))

    filtro = "AND i.interino_id = %(per)s" if personal_id else ""
    cur.execute(SQL_INTERINATOS.format(filtro=filtro), p)
    for r in cur.fetchall():
        quien = "" if personal_id else f"{r['interino']} – "
        desc = f"Acto de designación: {r['acto_designacion']}" if r["acto_designacion"] else ""
        cal.add_component(_evento(f"int-{r['id']}@pizarra-interinatos",
                                  f"{quien}Interino de {r['titular']} ({r['despacho']})",
                                  r["fecha_inicio"], r["fecha_fin"], r["estado"] == "ANULADO",
                                  r["version"], desc))
    return cal.to_ical()
