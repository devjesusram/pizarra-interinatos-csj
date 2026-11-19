"""Comandos de administración.

  python -m app.cli crear-admin <usuario> "<Nombre completo>"   (pide la contraseña)
  python -m app.cli demo                                        (carga datos de ejemplo)
"""
import getpass
import sys
from datetime import date, datetime, timedelta

from . import auth, config, db, servicios


def crear_admin(usuario: str, nombre: str) -> None:
    clave = getpass.getpass("Contraseña (mínimo 8 caracteres): ")
    if len(clave) < 8 or clave != getpass.getpass("Repita la contraseña: "):
        sys.exit("Las contraseñas no coinciden o son demasiado cortas.")
    with db.conexion() as conn, conn.transaction():
        conn.execute("""INSERT INTO usuarios (usuario, nombre, rol, hash_clave) VALUES (%s, %s, 'ADMIN', %s)
                        ON CONFLICT (usuario) DO UPDATE SET hash_clave = EXCLUDED.hash_clave,
                                                             rol = 'ADMIN', activo = TRUE""",
                     (usuario.strip().lower(), nombre, auth.hash_clave(clave)))
    print(f"Administrador '{usuario}' listo.")


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


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def demo() -> None:
    with db.conexion() as conn:
        if conn.execute("SELECT count(*) AS n FROM personal").fetchone()["n"]:
            sys.exit("Ya hay personal cargado: el demo solo se carga en una base vacía.")
        adm = conn.execute("SELECT id FROM usuarios WHERE rol = 'ADMIN' ORDER BY id LIMIT 1").fetchone()
        if not adm:
            sys.exit("Primero cree un administrador: python -m app.cli crear-admin ...")
        uid = adm["id"]
        ids: dict[tuple[int, str], int] = {}
        with conn.transaction():
            k = 0
            for i, (nom, fuero, loc) in enumerate(DESPACHOS):
                did = conn.execute("INSERT INTO despachos (nombre, fuero, localidad) VALUES (%s,%s,%s) RETURNING id",
                                   (nom, fuero, loc)).fetchone()["id"]
                for c in CARGOS:
                    n = f"{APELLIDOS[k % 20]}, {NOMBRES[(k * 7 + k // 20) % 20]}"
                    k += 1
                    ids[(i, c)] = conn.execute(
                        "INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES (%s,%s,%s) RETURNING id",
                        (n, c, did)).fetchone()["id"]
            hoy = datetime.now(config.ZONA).date()
            for fecha, desc in [(date(hoy.year, 12, 8), "Día de la Virgen de Caacupé"),
                                (date(hoy.year, 12, 25), "Navidad")]:
                conn.execute("INSERT INTO dias_inhabiles VALUES (%s,%s) ON CONFLICT DO NOTHING", (fecha, desc))
        tipos = {r["nombre"]: r["id"] for r in conn.execute("SELECT id, nombre FROM tipos_licencia").fetchall()}
        L = _lunes(hoy)

        def lic(desp, cargo, tipo, ini, dias):
            return servicios.crear_licencia(conn, {
                "personal_id": ids[(desp, cargo)], "tipo_licencia_id": tipos[tipo],
                "fecha_inicio": ini, "fecha_fin": ini + timedelta(days=dias - 1),
                "organo_aprobador": "CONSEJO" if cargo == "JUEZ" else "RRHH",
                "nro_resolucion": f"DEMO-{ini:%Y}-{desp:02d}{CARGOS.index(cargo)}",
                "correo_remitente": "rrhh@ejemplo.demo" if cargo != "JUEZ" else "consejo@ejemplo.demo",
                "correo_asunto": f"Licencia {tipo.lower()} (dato de ejemplo)"}, uid)[0]

        def inter(desp_t, desp_i, cargo, ini, dias, lic_id=None):
            return servicios.crear_interinato(conn, {
                "titular_id": ids[(desp_t, cargo)], "interino_id": ids[(desp_i, cargo)],
                "licencia_id": lic_id, "fecha_inicio": ini, "fecha_fin": ini + timedelta(days=dias - 1),
                "acto_designacion": "DEMO"}, uid, confirmar_advertencias=True)[0]

        # Un juez (despacho 4) cubre a dos jueces a la vez
        l1 = lic(0, "JUEZ", "Vacaciones", L, 12)
        inter(0, 4, "JUEZ", L, 12, l1)
        l2 = lic(2, "JUEZ", "Médica", L + timedelta(days=3), 5)
        inter(2, 4, "JUEZ", L + timedelta(days=3), 5, l2)
        # Secretario de licencia SIN interino
        lic(1, "SECRETARIO", "Médica", L + timedelta(days=2), 3)
        # Actuario cubierto
        l3 = lic(6, "ACTUARIO", "Estudio / Capacitación", L + timedelta(days=7), 5)
        inter(6, 3, "ACTUARIO", L + timedelta(days=7), 5, l3)
        # Ujier cubierto, y luego el interino recibe una licencia -> EN_CONFLICTO
        l4 = lic(8, "UJIER", "Vacaciones", L + timedelta(days=7), 10)
        inter(8, 9, "UJIER", L + timedelta(days=7), 10, l4)
        lic(9, "UJIER", "Particular", L + timedelta(days=9), 2)
        # Licencia futura sin cubrir
        lic(5, "JUEZ", "Maternidad", L + timedelta(days=14), 30)
    print("Datos de ejemplo cargados (son ficticios: reemplácelos por los reales).")


def main(argv: list[str]) -> None:
    db.abrir()
    try:
        with db.conexion() as conn:
            if db.inicializar_esquema(conn):
                print("Esquema creado.")
        if len(argv) >= 3 and argv[0] == "crear-admin":
            crear_admin(argv[1], argv[2])
        elif argv[:1] == ["demo"]:
            demo()
        else:
            print(__doc__)
    finally:
        db.cerrar()


if __name__ == "__main__":
    main(sys.argv[1:])
