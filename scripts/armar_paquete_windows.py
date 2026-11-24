"""Arma el paquete para Windows: dist/Pizarra-Windows-<version>.zip

Se ejecuta en cualquier computadora con internet y Python 3 (Linux, macOS o Windows):

    python scripts/armar_paquete_windows.py

El ZIP resultante trae TODO lo necesario (Python portátil, librerías y el sistema).
En la PC servidor no hace falta internet ni instalar nada: se descomprime en C:\\Pizarra.
"""
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app import __version__  # noqa: E402

PYTHON_VERSION = "3.13.17"   # Python oficial para Windows (x64), distribuido por NuGet
PYTHON_URL = f"https://api.nuget.org/v3-flatcontainer/python/{PYTHON_VERSION}/python.{PYTHON_VERSION}.nupkg"

BUILD = RAIZ / "build"
DESTINO = BUILD / "Pizarra"
DIST = RAIZ / "dist"


def paso(texto: str) -> None:
    print(f"\n▶ {texto}", flush=True)


def a_crlf(origen: Path, destino: Path, bom: bool = False) -> None:
    texto = origen.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    destino.write_bytes((b"\xef\xbb\xbf" if bom else b"") + texto.encode("utf-8"))


def main() -> None:
    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    DESTINO.mkdir(parents=True)

    paso(f"Descargando Python {PYTHON_VERSION} para Windows…")
    cache = BUILD / f"python-{PYTHON_VERSION}.nupkg"
    if not cache.exists():
        with urllib.request.urlopen(PYTHON_URL, timeout=300) as r:
            cache.write_bytes(r.read())
    with zipfile.ZipFile(cache) as z:
        for nombre in z.namelist():
            if nombre.startswith("tools/") and not nombre.endswith("/"):
                rel = Path(nombre[len("tools/"):])
                if rel.parts and rel.parts[0] in ("include", "libs"):
                    continue                        # solo sirven para compilar
                salida = DESTINO / "python" / rel
                salida.parent.mkdir(parents=True, exist_ok=True)
                salida.write_bytes(z.read(nombre))

    paso("Instalando las librerías para Windows…")
    site = DESTINO / "python" / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
                    "--target", str(site), "--platform", "win_amd64", "--python-version", "3.13",
                    "--implementation", "cp", "--abi", "cp313", "--only-binary=:all:",
                    "-r", str(RAIZ / "requirements.txt")], check=True)
    shutil.rmtree(site / "bin", ignore_errors=True)      # ejecutables de Linux que pip agrega
    # La carpeta del sistema (C:\Pizarra) queda en sys.path para "python -m app...."
    (site / "pizarra.pth").write_text("../../..\n", encoding="utf-8")

    paso("Copiando el sistema…")
    shutil.copytree(RAIZ / "app", DESTINO / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for bat in sorted((RAIZ / "windows").glob("*.bat")):
        a_crlf(bat, DESTINO / bat.name)
    (DESTINO / "windows").mkdir()
    for ps1 in sorted((RAIZ / "windows").glob("*.ps1")):
        a_crlf(ps1, DESTINO / "windows" / ps1.name)
    a_crlf(RAIZ / "windows" / "configuracion.txt", DESTINO / "configuracion.txt", bom=True)
    a_crlf(RAIZ / "windows" / "LEAME.txt", DESTINO / "LEAME.txt", bom=True)
    shutil.copy(RAIZ / "docs" / "INSTALACION-WINDOWS.md", DESTINO / "INSTALACION-WINDOWS.md")

    paso("Comprimiendo…")
    DIST.mkdir(exist_ok=True)
    zip_final = DIST / f"Pizarra-Windows-{__version__}.zip"
    with zipfile.ZipFile(zip_final, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(DESTINO.rglob("*")):
            if f.is_file():
                z.write(f, Path("Pizarra") / f.relative_to(DESTINO))
    mb = zip_final.stat().st_size / 1_000_000
    print(f"\n✔ Listo: {zip_final} ({mb:.0f} MB)")


if __name__ == "__main__":
    main()
