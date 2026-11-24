"""Inicia el servidor web.

    python -m app.servidor

Escucha en todas las interfaces (HOST=0.0.0.0) y en el puerto PUERTO (8080 por
defecto), para que otras PCs de la red entren con http://IP-DEL-SERVIDOR:8080.
Los mensajes se guardan también en datos/registros/pizarra.log (útil cuando corre
oculto como tarea de Windows).
"""
import logging
import logging.handlers
import socket
import sys

import uvicorn

from . import config, db


def _configurar_registro() -> None:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    archivo = logging.handlers.RotatingFileHandler(config.LOGS_DIR / "pizarra.log", maxBytes=2_000_000,
                                                   backupCount=5, encoding="utf-8")
    archivo.setFormatter(formato)
    handlers = [archivo]
    if sys.stdout is not None:
        consola = logging.StreamHandler(sys.stdout)
        consola.setFormatter(formato)
        handlers.append(consola)
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    for h in handlers:
        raiz.addHandler(h)
    for nombre in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(nombre)
        lg.handlers.clear()
        lg.propagate = True


def _ips_locales() -> list[str]:
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def main() -> None:
    _configurar_registro()
    log = logging.getLogger("pizarra")
    if db.inicializar_esquema():
        log.info("Base de datos creada en %s", config.DB_PATH)
    with db.conexion() as conn:
        log.info("Versión de la base de datos: %s", db.version_de(conn))
    log.info("Pizarra iniciada. Datos en %s", config.DATOS_DIR)
    log.info("Abra en esta PC: http://localhost:%s", config.PUERTO)
    for ip in _ips_locales():
        log.info("Desde otras PCs de la red: http://%s:%s", ip, config.PUERTO)
    uvicorn.run("app.main:app", host=config.HOST, port=config.PUERTO, workers=1,
                log_config=None, proxy_headers=False)


if __name__ == "__main__":
    main()
