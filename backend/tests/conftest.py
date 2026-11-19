"""Las pruebas usan una base PostgreSQL real (descartable): TEST_DATABASE_URL.
¡Se borra por completo en cada prueba! Nunca apunte a la base de producción."""
import os
from datetime import date, timedelta

import pytest

URL = os.environ.get("TEST_DATABASE_URL", "postgresql://pizarra:pizarra@localhost:5432/pizarra_test")
os.environ["DATABASE_URL"] = URL
os.environ.setdefault("ADJUNTOS_DIR", "/tmp/pizarra-test-adjuntos")

from app import auth, db  # noqa: E402

LUNES = date(2026, 11, 16)


def d(n: int) -> date:
    """Día n a partir del lunes 16/11/2026."""
    return LUNES + timedelta(days=n)


@pytest.fixture(scope="session", autouse=True)
def _pool():
    db.abrir()
    yield
    db.cerrar()


@pytest.fixture()
def conn():
    with db.conexion() as c:
        with c.transaction():
            c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        db.inicializar_esquema(c)
        yield c


@pytest.fixture()
def datos(conn):
    """Dos despachos con los cuatro cargos y un tercer juez. Devuelve ids útiles."""
    with conn.transaction():
        uid = conn.execute("""INSERT INTO usuarios (usuario, nombre, rol, hash_clave)
                              VALUES ('admin', 'Admin', 'ADMIN', %s) RETURNING id""",
                           (auth.hash_clave("clave1234"),)).fetchone()["id"]
        conn.execute("""INSERT INTO usuarios (usuario, nombre, rol, hash_clave)
                        VALUES ('oper', 'Operador', 'OPERADOR', %s)""", (auth.hash_clave("clave1234"),))
        ids = {"uid": uid}
        for n in (1, 2, 3):
            did = conn.execute("INSERT INTO despachos (nombre, fuero, localidad) VALUES (%s,'Civil','Caacupé') RETURNING id",
                               (f"J{n}",)).fetchone()["id"]
            for c in ("JUEZ", "ACTUARIO", "SECRETARIO", "UJIER"):
                ids[f"{c.lower()}{n}"] = conn.execute(
                    "INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES (%s,%s,%s) RETURNING id",
                    (f"{c.title()} {n}", c, did)).fetchone()["id"]
    return ids
