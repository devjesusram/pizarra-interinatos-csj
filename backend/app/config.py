"""Configuración leída de variables de entorno (archivo .env en Docker)."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pizarra:pizarra@localhost:5432/pizarra")
ADJUNTOS_DIR = Path(os.environ.get("ADJUNTOS_DIR", "/data/adjuntos"))
ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Asuncion"))
SESION_HORAS = int(os.environ.get("SESION_HORAS", "12"))
# Ponga "true" solo si sirve el sistema por HTTPS
COOKIE_SEGURA = os.environ.get("COOKIE_SEGURA", "false").lower() == "true"
# Token opcional para el feed .ics general de la circunscripción (vacío = desactivado)
ICS_TOKEN_GENERAL = os.environ.get("ICS_TOKEN_GENERAL", "").strip()
NOMBRE_CIRCUNSCRIPCION = os.environ.get("NOMBRE_CIRCUNSCRIPCION", "Circunscripción Judicial de Cordillera")
ADJUNTO_MAX_MB = int(os.environ.get("ADJUNTO_MAX_MB", "15"))
