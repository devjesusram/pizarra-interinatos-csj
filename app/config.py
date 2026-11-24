"""Configuración.

Orden de prioridad: variables de entorno > archivo 'configuracion.txt' en la carpeta
del sistema > valores por defecto. El archivo usa líneas CLAVE=VALOR.
"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(os.environ.get("PIZARRA_BASE", Path(__file__).resolve().parent.parent))


def _leer_archivo(ruta: Path) -> None:
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())


_leer_archivo(BASE_DIR / "configuracion.txt")

DATOS_DIR = Path(os.environ.get("DATOS_DIR", BASE_DIR / "datos"))
DB_PATH = Path(os.environ.get("DB_PATH", DATOS_DIR / "pizarra.db"))
ADJUNTOS_DIR = Path(os.environ.get("ADJUNTOS_DIR", DATOS_DIR / "adjuntos"))
LOGS_DIR = Path(os.environ.get("LOGS_DIR", DATOS_DIR / "registros"))
RESPALDOS_DIR = Path(os.environ.get("RESPALDOS_DIR", BASE_DIR / "respaldos"))

HOST = os.environ.get("HOST", "0.0.0.0")
PUERTO = int(os.environ.get("PUERTO", "8080"))
ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Asuncion"))
SESION_HORAS = int(os.environ.get("SESION_HORAS", "12"))
# Ponga "true" solo si sirve el sistema por HTTPS
COOKIE_SEGURA = os.environ.get("COOKIE_SEGURA", "false").lower() == "true"
# Token opcional para el feed .ics general de la circunscripción (vacío = desactivado)
ICS_TOKEN_GENERAL = os.environ.get("ICS_TOKEN_GENERAL", "").strip()
NOMBRE_CIRCUNSCRIPCION = os.environ.get("NOMBRE_CIRCUNSCRIPCION", "Circunscripción Judicial de Cordillera")
ADJUNTO_MAX_MB = int(os.environ.get("ADJUNTO_MAX_MB", "15"))
DIAS_RESPALDO = int(os.environ.get("DIAS_RESPALDO", "30"))
