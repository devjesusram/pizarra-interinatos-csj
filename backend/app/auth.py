"""Usuarios propios del sistema (sin Active Directory) y sesiones."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

from . import config, db

COOKIE = "pizarra_sesion"
_N, _R, _P = 2 ** 14, 8, 1


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${h.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calc = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r),
                              p=int(p), dklen=len(bytes.fromhex(h)))
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def validar_clave_nueva(clave: str) -> None:
    if len(clave or "") < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres.")


def iniciar_sesion(conn, usuario: str, clave: str) -> str | None:
    r = conn.execute("SELECT id, hash_clave FROM usuarios WHERE usuario = %s AND activo",
                     (usuario.strip().lower(),)).fetchone()
    if not r or not verificar_clave(clave, r["hash_clave"]):
        return None
    token = secrets.token_urlsafe(32)
    with conn.transaction():
        conn.execute("DELETE FROM sesiones WHERE expira < now()")
        conn.execute("INSERT INTO sesiones (token, usuario_id, expira) VALUES (%s, %s, %s)",
                     (token, r["id"], datetime.now(timezone.utc) + timedelta(hours=config.SESION_HORAS)))
    return token


def cerrar_sesion(conn, token: str) -> None:
    with conn.transaction():
        conn.execute("DELETE FROM sesiones WHERE token = %s", (token,))


def usuario_actual(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Debe iniciar sesión.")
    with db.conexion() as conn:
        u = conn.execute("""SELECT u.id, u.usuario, u.nombre, u.rol
                            FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id
                            WHERE s.token = %s AND s.expira > now() AND u.activo""",
                         (token,)).fetchone()
    if not u:
        raise HTTPException(401, "La sesión expiró. Vuelva a iniciar sesión.")
    return u


def requiere_admin(u: dict = Depends(usuario_actual)) -> dict:
    if u["rol"] != "ADMIN":
        raise HTTPException(403, "Solo un administrador puede hacer esto.")
    return u
