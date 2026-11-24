"""Cada prueba usa una base SQLite nueva en una carpeta temporal."""
from datetime import date, timedelta

import pytest

from app import auth, config, db

LUNES = date(2026, 11, 16)


def d(n: int) -> date:
    """Día n a partir del lunes 16/11/2026."""
    return LUNES + timedelta(days=n)


@pytest.fixture(autouse=True)
def _base_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pizarra.db")
    monkeypatch.setattr(config, "ADJUNTOS_DIR", tmp_path / "adjuntos")
    monkeypatch.setattr(config, "RESPALDOS_DIR", tmp_path / "respaldos")
    db.inicializar_esquema()


@pytest.fixture()
def conn():
    c = db.conectar()
    yield c
    c.close()


@pytest.fixture()
def datos(conn):
    """Tres despachos con los cuatro cargos. Devuelve ids útiles."""
    ids = {}
    with db.escritura(conn):
        ids["uid"] = conn.execute("""INSERT INTO usuarios (usuario, nombre, rol, hash_clave)
                                     VALUES ('admin', 'Admin', 'ADMIN', ?)""",
                                  (auth.hash_clave("clave1234"),)).lastrowid
        conn.execute("""INSERT INTO usuarios (usuario, nombre, rol, hash_clave)
                        VALUES ('oper', 'Operador', 'OPERADOR', ?)""", (auth.hash_clave("clave1234"),))
        for n in (1, 2, 3):
            did = conn.execute("INSERT INTO despachos (nombre, fuero, localidad) VALUES (?, 'Civil', 'Caacupé')",
                               (f"J{n}",)).lastrowid
            for c in ("JUEZ", "ACTUARIO", "SECRETARIO", "UJIER"):
                ids[f"{c.lower()}{n}"] = conn.execute(
                    "INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES (?, ?, ?)",
                    (f"{c.title()} {n}", c, did)).lastrowid
    return ids
