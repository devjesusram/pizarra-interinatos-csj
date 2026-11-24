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


# ── Actualizaciones de la base (se aplican solas al iniciar) ───────────
# Cada entrada es (versión, descripción, SQL). Nunca se modifican las ya publicadas:
# los cambios nuevos se agregan al final con el número siguiente.
MIGRACIONES = [
    (2, "Turno en despachos; actuarios y secretarios pueden cubrir varios despachos", """
        ALTER TABLE despachos ADD COLUMN turno TEXT;

        UPDATE cargos SET max_interinatos_simultaneos = NULL
         WHERE codigo IN ('JUEZ', 'ACTUARIO', 'SECRETARIO');

        -- La exclusividad del interino ahora depende del tope configurado en "cargos":
        -- la base de datos impide cruces cuando el tope es 1. Con un tope mayor, el
        -- control lo hace la aplicación (regla R5).
        DROP TRIGGER IF EXISTS int_interino_unico_ins;
        DROP TRIGGER IF EXISTS int_interino_unico_upd;

        CREATE TRIGGER int_interino_unico_ins BEFORE INSERT ON interinatos
        WHEN NEW.estado <> 'ANULADO'
        BEGIN
          SELECT RAISE(ABORT, 'INT_INTERINO_UNICO')
          WHERE (SELECT max_interinatos_simultaneos FROM cargos WHERE codigo = NEW.cargo_codigo) = 1
            AND EXISTS (SELECT 1 FROM interinatos i
                        WHERE i.interino_id = NEW.interino_id AND i.estado <> 'ANULADO'
                          AND i.fecha_inicio <= NEW.fecha_fin AND i.fecha_fin >= NEW.fecha_inicio);
        END;

        CREATE TRIGGER int_interino_unico_upd
        BEFORE UPDATE OF interino_id, fecha_inicio, fecha_fin, estado, cargo_codigo ON interinatos
        WHEN NEW.estado <> 'ANULADO'
        BEGIN
          SELECT RAISE(ABORT, 'INT_INTERINO_UNICO')
          WHERE (SELECT max_interinatos_simultaneos FROM cargos WHERE codigo = NEW.cargo_codigo) = 1
            AND EXISTS (SELECT 1 FROM interinatos i
                        WHERE i.id <> NEW.id AND i.interino_id = NEW.interino_id AND i.estado <> 'ANULADO'
                          AND i.fecha_inicio <= NEW.fecha_fin AND i.fecha_fin >= NEW.fecha_inicio);
        END;
    """),
]
VERSION_ACTUAL = MIGRACIONES[-1][0]


def version_de(conn) -> int:
    return uno(conn, "SELECT max(version) AS v FROM version_esquema")["v"] or 0


def _respaldo_previo(conn, desde: int) -> Path:
    """Copia de seguridad automática antes de actualizar una base con datos."""
    carpeta = config.RESPALDOS_DIR / "antes-de-actualizar"
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(config.ZONA).strftime("%Y%m%d-%H%M%S")
    destino_path = carpeta / f"pizarra-db-v{desde}-{marca}.db"
    destino = sqlite3.connect(destino_path)
    try:
        conn.backup(destino)
    finally:
        destino.close()
    return destino_path


def migrar(conn) -> list[int]:
    """Aplica las actualizaciones pendientes. Devuelve las versiones aplicadas."""
    actual = version_de(conn)
    pendientes = [m for m in MIGRACIONES if m[0] > actual]
    if not pendientes:
        return []
    if uno(conn, "SELECT count(*) AS n FROM usuarios")["n"]:
        _respaldo_previo(conn, actual)
    for version, _desc, sql in pendientes:
        try:
            conn.executescript(f"BEGIN;\n{sql}\nINSERT INTO version_esquema (version) VALUES ({version});\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return [m[0] for m in pendientes]


def inicializar_esquema(conn=None) -> bool:
    """Crea las tablas si la base está vacía y aplica las actualizaciones pendientes.
    Devuelve True si creó la base."""
    propia = conn is None
    conn = conn or conectar()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        existe = uno(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='version_esquema'")
        if not existe:
            sql = (Path(__file__).parent / "esquema.sql").read_text(encoding="utf-8")
            conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        migrar(conn)
        return not existe
    finally:
        if propia:
            conn.close()
