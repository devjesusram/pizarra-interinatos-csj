"""Conexión a PostgreSQL e inicialización del esquema."""
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None


def abrir() -> None:
    global _pool
    if _pool is None or _pool.closed:
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, open=False,
                               kwargs={"row_factory": dict_row, "autocommit": True,
                                       "options": f"-c TimeZone={config.ZONA.key}"})
        _pool.open(wait=True, timeout=60)


def cerrar() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def conexion():
    abrir()
    with _pool.connection() as conn:
        yield conn


def inicializar_esquema(conn) -> bool:
    """Crea las tablas si la base está vacía. Devuelve True si las creó."""
    existe = conn.execute("SELECT to_regclass('public.version_esquema') AS t").fetchone()["t"]
    if existe:
        return False
    sql = (Path(__file__).parent / "esquema.sql").read_text(encoding="utf-8")
    with conn.transaction():
        conn.execute(sql)
    return True
