"""Base de datos SQLite (un solo archivo, sin servidor aparte).

Concurrencia: cada escritura usa BEGIN IMMEDIATE, que toma el permiso de escritura
al empezar. Así dos operadores que guardan a la vez se atienden de a uno y la
validación ve siempre los datos actualizados (no hay cruces por simultaneidad).
"""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from . import config


def _dict(cursor, fila):
    return {d[0]: v for d, v in zip(cursor.description, fila)}


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = ruta or config.DB_PATH
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = _dict
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def conexion():
    conn = conectar()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def escritura(conn: sqlite3.Connection):
    """Transacción de escritura exclusiva (serializa a los operadores)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def todos(conn, sql: str, params=()) -> list[dict]:
    return conn.execute(sql, params).fetchall()


def uno(conn, sql: str, params=()) -> dict | None:
    return conn.execute(sql, params).fetchone()


def ahora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def a_fecha(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(s)


def booleanos(filas, *campos):
    """SQLite guarda 0/1: los devuelve como true/false para la interfaz."""
    lista = filas if isinstance(filas, list) else [filas]
    for f in lista:
        if f is None:
            continue
        for c in campos:
            if c in f and f[c] is not None:
                f[c] = bool(f[c])
    return filas


def inicializar_esquema(conn=None) -> bool:
    """Crea las tablas si la base está vacía. Devuelve True si las creó."""
    propia = conn is None
    conn = conn or conectar()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        existe = uno(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='version_esquema'")
        if existe:
            return False
        sql = (Path(__file__).parent / "esquema.sql").read_text(encoding="utf-8")
        conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        return True
    finally:
        if propia:
            conn.close()
