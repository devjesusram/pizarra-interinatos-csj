"""Comandos de administración.

  python -m app.cli crear-admin [usuario] ["Nombre completo"]   (pide los datos que falten)
  python -m app.cli demo                                        (carga datos de ejemplo)
  python -m app.cli respaldo [carpeta]                          (respaldo de base y adjuntos)
  python -m app.cli restaurar <archivo .db> [archivo de adjuntos .zip]
"""
import getpass
import re
import shutil
import sqlite3
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import auth, config, db, servicios


def crear_admin(usuario: str | None, nombre: str | None) -> None:
    usuario = (usuario or input("Usuario del administrador (ej.: admin): ")).strip().lower()
    nombre = (nombre or input("Nombre y apellido: ")).strip()
    if len(usuario) < 3 or len(nombre) < 3:
        sys.exit("El usuario y el nombre deben tener al menos 3 caracteres.")
    clave = getpass.getpass("Contraseña (mínimo 8 caracteres, no se ve al escribir): ")
    if len(clave) < 8 or clave != getpass.getpass("Repita la contraseña: "):
        sys.exit("Las contraseñas no coinciden o son demasiado cortas.")
    with db.conexion() as conn, db.escritura(conn):
        conn.execute("""INSERT INTO usuarios (usuario, nombre, rol, hash_clave) VALUES (?, ?, 'ADMIN', ?)
                        ON CONFLICT (usuario) DO UPDATE SET hash_clave = excluded.hash_clave,
                                                             rol = 'ADMIN', activo = 1""",
                     (usuario, nombre, auth.hash_clave(clave)))
    print(f"Administrador '{usuario}' listo.")


# ── Respaldo y restauración ────────────────────────────────────────────

def respaldo(destino: str | None = None) -> Path:
    """Copia segura de la base (aunque el sistema esté en uso) y de los adjuntos."""
    carpeta = Path(destino) if destino else config.RESPALDOS_DIR
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(config.ZONA).strftime("%Y%m%d-%H%M")
    archivo_db = carpeta / f"pizarra-db-{marca}.db"
    origen = db.conectar()
    copia = sqlite3.connect(archivo_db)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    archivo_adj = carpeta / f"pizarra-adjuntos-{marca}.zip"
    with zipfile.ZipFile(archivo_adj, "w", zipfile.ZIP_DEFLATED) as z:
        if config.ADJUNTOS_DIR.exists():
            for f in sorted(config.ADJUNTOS_DIR.iterdir()):
                if f.is_file():
                    z.write(f, f.name)
    # Borra solo respaldos de la Pizarra más viejos que DIAS_RESPALDO
    limite = time.time() - config.DIAS_RESPALDO * 86400
    for f in list(carpeta.glob("pizarra-db-*.db")) + list(carpeta.glob("pizarra-adjuntos-*.zip")):
        if f.stat().st_mtime < limite:
            f.unlink()
    print(f"Respaldo listo:\n  {archivo_db}\n  {archivo_adj}")
    return archivo_db


def restaurar(archivo_db: str, archivo_adj: str | None = None) -> None:
    """Reemplaza los datos actuales por los del respaldo. El servidor debe estar detenido."""
    origen_path = Path(archivo_db)
    if not origen_path.is_file():
        sys.exit(f"No existe el archivo {origen_path}")
    prueba = sqlite3.connect(origen_path)
    try:
        if prueba.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            sys.exit("El archivo de respaldo está dañado.")
    finally:
        prueba.close()
    # Antes de reemplazar, guarda una copia de lo que hay ahora (por si acaso)
    if config.DB_PATH.exists():
        print("Guardando una copia de los datos actuales antes de restaurar…")
        respaldo(str(config.RESPALDOS_DIR / "antes-de-restaurar"))
    origen = sqlite3.connect(origen_path)
    destino = db.conectar()
    try:
        origen.backup(destino)
    finally:
        destino.close()
        origen.close()
    if not archivo_adj:
        # Busca el archivo de adjuntos del mismo respaldo (misma fecha y hora)
        candidato = origen_path.with_name(origen_path.name.replace("pizarra-db-", "pizarra-adjuntos-")).with_suffix(".zip")
        if candidato.is_file():
            archivo_adj = str(candidato)
            print(f"Restaurando también los adjuntos de {candidato.name}")
    if archivo_adj:
        config.ADJUNTOS_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archivo_adj) as z:
            for nombre in z.namelist():
                limpio = Path(nombre).name           # evita rutas fuera de la carpeta
                if limpio:
                    with z.open(nombre) as src, open(config.ADJUNTOS_DIR / limpio, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    print("Restauración terminada.")


# ── Datos de ejemplo ───────────────────────────────────────────────────

DESPACHOS = [
    ("Juzgado Civil y Comercial 1º Turno - Caacupé", "Civil y Comercial", "Caacupé"),
    ("Juzgado Civil y Comercial 2º Turno - Caacupé", "Civil y Comercial", "Caacupé"),
    ("Juzgado Penal de Garantías 1º Turno - Caacupé", "Penal", "Caacupé"),
    ("Juzgado Penal de Garantías 2º Turno - Caacupé", "Penal", "Caacupé"),
    ("Juzgado Laboral - Caacupé", "Laboral", "Caacupé"),
    ("Juzgado de la Niñez y la Adolescencia - Caacupé", "Niñez y Adolescencia", "Caacupé"),
    ("Juzgado Penal de Garantías - Tobatí", "Penal", "Tobatí"),
    ("Juzgado Civil y Comercial - Eusebio Ayala", "Civil y Comercial", "Eusebio Ayala"),
    ("Juzgado de Paz - Caacupé", "Paz", "Caacupé"),
    ("Juzgado de Paz - Piribebuy", "Paz", "Piribebuy"),
]
NOMBRES = ["Ana", "Carlos", "María", "José", "Lucía", "Andrés", "Rosa", "Miguel", "Laura", "Diego",
           "Sofía", "Raúl", "Elena", "Hugo", "Patricia", "Óscar", "Silvia", "Jorge", "Mónica", "Fernando"]
APELLIDOS = ["Benítez", "González", "Ramírez", "Martínez", "Ortiz", "Giménez", "Villalba", "Rojas",
             "Duarte", "Cáceres", "Acosta", "Figueredo", "Insfrán", "Ayala", "Ferreira", "Núñez",
             "Sanabria", "Espínola", "Báez", "Galeano"]
CARGOS = ["JUEZ", "ACTUARIO", "SECRETARIO", "UJIER"]


def demo() -> None:
    with db.conexion() as conn:
        if db.uno(conn, "SELECT count(*) AS n FROM personal")["n"]:
            sys.exit("Ya hay personal cargado: el demo solo se carga en una base vacía.")
        adm = db.uno(conn, "SELECT id FROM usuarios WHERE rol = 'ADMIN' ORDER BY id LIMIT 1")
        if not adm:
            sys.exit("Primero cree un administrador (crear-administrador.bat).")
        uid = adm["id"]
        ids: dict[tuple[int, str], int] = {}
        hoy = datetime.now(config.ZONA).date()
        with db.escritura(conn):
            k = 0
            for i, (nom, fuero, loc) in enumerate(DESPACHOS):
                turno = re.search(r"\dº Turno", nom)
                did = conn.execute("INSERT INTO despachos (nombre, fuero, localidad, turno) VALUES (?, ?, ?, ?)",
                                   (nom, fuero, loc, turno.group(0) if turno else None)).lastrowid
                for c in CARGOS:
                    n = f"{APELLIDOS[k % 20]}, {NOMBRES[(k * 7 + k // 20) % 20]}"
                    k += 1
                    ids[(i, c)] = conn.execute(
                        "INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES (?, ?, ?)",
                        (n, c, did)).lastrowid
            # Segunda secretaria en el 1º Turno civil (los turnos suelen tener dos)
            ids[(0, "SECRETARIO2")] = conn.execute(
                "INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES (?, 'SECRETARIO', 1)",
                ("Rojas, Mónica",)).lastrowid
            for fecha, desc in [(date(hoy.year, 12, 8), "Día de la Virgen de Caacupé"),
                                (date(hoy.year, 12, 25), "Navidad")]:
                conn.execute("INSERT OR IGNORE INTO dias_inhabiles VALUES (?, ?)", (fecha.isoformat(), desc))
        tipos = {r["nombre"]: r["id"] for r in db.todos(conn, "SELECT id, nombre FROM tipos_licencia")}
        lunes = hoy - timedelta(days=hoy.weekday())

        def lic(desp, cargo, tipo, ini, dias):
            return servicios.crear_licencia(conn, {
                "personal_id": ids[(desp, cargo)], "tipo_licencia_id": tipos[tipo],
                "fecha_inicio": ini, "fecha_fin": ini + timedelta(days=dias - 1),
                "organo_aprobador": "CONSEJO" if cargo == "JUEZ" else "RRHH",
                "nro_resolucion": f"DEMO-{ini:%Y}-{desp:02d}{CARGOS.index(cargo)}",
                "correo_remitente": "rrhh@ejemplo.demo" if cargo != "JUEZ" else "consejo@ejemplo.demo",
                "correo_asunto": f"Licencia {tipo.lower()} (dato de ejemplo)"}, uid)[0]

        def inter(desp_t, desp_i, cargo, ini, dias, lic_id=None):
            """dias=None: sin fecha de desvinculación. DESPACHO = el del titular, abreviado."""
            return servicios.crear_interinato(conn, {
                "titular_id": ids[(desp_t, cargo)], "interino_id": ids[(desp_i, cargo)],
                "licencia_id": lic_id, "fecha_inicio": ini,
                "fecha_fin": ini + timedelta(days=dias - 1) if dias else None,
                "despacho_texto": DESPACHOS[desp_t][0],
                "acto_designacion": "DEMO"}, uid, confirmar_advertencias=True)[0]

        # Un juez (despacho 4) cubre a dos jueces a la vez
        l1 = lic(0, "JUEZ", "Vacaciones", lunes, 12)
        inter(0, 4, "JUEZ", lunes, 12, l1)
        l2 = lic(2, "JUEZ", "Médica", lunes + timedelta(days=3), 5)
        inter(2, 4, "JUEZ", lunes + timedelta(days=3), 5, l2)
        # Secretario de licencia SIN interino
        lic(1, "SECRETARIO", "Médica", lunes + timedelta(days=2), 3)
        # Actuario cubierto
        l3 = lic(6, "ACTUARIO", "Estudio / Capacitación", lunes + timedelta(days=7), 5)
        inter(6, 3, "ACTUARIO", lunes + timedelta(days=7), 5, l3)
        # Ujier cubierto, y luego el interino recibe una licencia -> EN_CONFLICTO
        l4 = lic(8, "UJIER", "Vacaciones", lunes + timedelta(days=7), 10)
        inter(8, 9, "UJIER", lunes + timedelta(days=7), 10, l4)
        lic(9, "UJIER", "Particular", lunes + timedelta(days=9), 2)
        # Licencia futura sin cubrir
        lic(5, "JUEZ", "Maternidad", lunes + timedelta(days=14), 30)
        # Para el tablero: uno sin fecha de desvinculación, uno a desvincular en 2 días,
        # uno ya desvinculado y uno que empieza la semana próxima
        inter(7, 9, "JUEZ", lunes - timedelta(days=7), None)
        sin_vincular = inter(8, 3, "JUEZ", hoy - timedelta(days=5), 8)     # queda «Falta vincular»
        ya = inter(1, 3, "JUEZ", lunes - timedelta(days=40), 10)
        servicios.desvincular_interinato(conn, ya, lunes - timedelta(days=31), "Reasumió la titular (dato de ejemplo)",
                                         1, uid, hoy)
        inter(4, 5, "ACTUARIO", hoy - timedelta(days=12), 9)      # vencido y sin desvincular: queda pendiente
        inter(6, 1, "JUEZ", lunes + timedelta(days=8), 5)
        # Actuaria de la Sria. Nº 1 que además está a cargo de la Sria. Nº 2 (vacante)
        # del Juzgado Penal de Garantías 1º Turno
        with db.escritura(conn):
            conn.execute("UPDATE personal SET secretaria = 'Nº 1' WHERE id = ?", (ids[(2, "ACTUARIO")],))
        despacho_penal = db.uno(conn, "SELECT despacho_id FROM personal WHERE id = ?", (ids[(2, "ACTUARIO")],))["despacho_id"]
        vac = servicios.crear_vacante(conn, {"despacho_id": despacho_penal, "cargo_codigo": "ACTUARIO",
                                             "secretaria": "Nº 2", "fecha_desde": lunes - timedelta(days=30),
                                             "observaciones": "Dato de ejemplo"}, uid)
        servicios.crear_interinato(conn, {"vacante_id": vac, "interino_id": ids[(2, "ACTUARIO")],
                                          "fecha_inicio": lunes - timedelta(days=30), "fecha_fin": lunes + timedelta(days=60),
                                          "acto_designacion": "DEMO"}, uid, confirmar_advertencias=True)
        # Un puesto vacante de ujier sin nadie a cargo
        servicios.crear_vacante(conn, {"despacho_id": despacho_penal, "cargo_codigo": "UJIER",
                                       "fecha_desde": lunes + timedelta(days=2)}, uid)
        # Vinculación manual: todos los que ya empezaron figuran como vinculados, menos uno
        for r in db.todos(conn, """SELECT id, version, fecha_inicio FROM interinatos
                                   WHERE estado <> 'ANULADO' AND vinculado = 0 AND fecha_inicio <= ? AND id <> ?""",
                          (db.iso(hoy), sin_vincular)):
            servicios.vincular_interinato(conn, r["id"], r["fecha_inicio"], None, r["version"], uid, hoy)
    print("Datos de ejemplo cargados (son ficticios: reemplácelos por los reales).")


def main(argv: list[str]) -> None:
    if db.inicializar_esquema():
        print(f"Base de datos creada en {config.DB_PATH}")
    cmd = argv[0] if argv else ""
    if cmd == "crear-admin":
        crear_admin(argv[1] if len(argv) > 1 else None, argv[2] if len(argv) > 2 else None)
    elif cmd == "demo":
        demo()
    elif cmd == "respaldo":
        respaldo(argv[1] if len(argv) > 1 else None)
    elif cmd == "restaurar" and len(argv) >= 2:
        restaurar(argv[1], argv[2] if len(argv) > 2 else None)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
