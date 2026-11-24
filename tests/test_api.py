"""Pruebas de la API: sesión, permisos, códigos de respuesta y exportación .ics."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def cliente(datos):
    with TestClient(app) as c:
        yield c


def entrar(c, usuario="admin"):
    r = c.post("/api/login", json={"usuario": usuario, "clave": "clave1234"})
    assert r.status_code == 200


def test_sin_sesion_401(cliente):
    assert cliente.get("/api/pizarra?desde=2026-11-16&hasta=2026-11-29").status_code == 401


def test_clave_incorrecta(cliente):
    assert cliente.post("/api/login", json={"usuario": "admin", "clave": "mal"}).status_code == 401


def test_operador_no_administra_usuarios(cliente):
    entrar(cliente, "oper")
    r = cliente.post("/api/usuarios", json={"usuario": "x", "nombre": "Xxx", "rol": "ADMIN", "clave": "12345678"})
    assert r.status_code == 403


def test_flujo_licencia_interinato_y_codigos(cliente, datos):
    entrar(cliente, "oper")
    r = cliente.post("/api/licencias", json={"personal_id": datos["juez1"], "tipo_licencia_id": 1,
                                             "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-20",
                                             "organo_aprobador": "CONSEJO", "nro_resolucion": ""})
    assert r.status_code == 201
    lid = r.json()["id"]
    body = {"titular_id": datos["juez1"], "interino_id": datos["juez2"], "licencia_id": lid,
            "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-22"}
    r = cliente.post("/api/interinatos", json=body)               # 2 días sin licencia -> R8
    assert r.status_code == 428 and r.json()["hallazgos"][0]["regla"] == "R8"
    r = cliente.post("/api/interinatos", json={**body, "confirmar_advertencias": True})
    assert r.status_code == 201
    r = cliente.post("/api/interinatos", json={**body, "titular_id": datos["juez3"],
                                               "confirmar_advertencias": True})
    assert r.status_code == 201                                   # jueces pueden acumular
    r = cliente.post("/api/interinatos", json={**body, "titular_id": datos["actuario1"],
                                               "interino_id": datos["juez2"]})
    assert r.status_code == 409 and r.json()["hallazgos"][0]["regla"] == "R9"

    p = cliente.get("/api/pizarra?desde=2026-11-16&hasta=2026-11-29").json()
    assert len(p["licencias"]) == 1 and len(p["interinatos"]) == 2

    disp = cliente.get(f"/api/disponibilidad?titular_id={datos['secretario1']}"
                       "&desde=2026-11-16&hasta=2026-11-20").json()
    assert {c["estado"] for c in disp["candidatos"]} == {"DISPONIBLE"}
    assert len(disp["candidatos"]) == 2                           # solo secretarios


def test_adjunto(cliente, datos):
    entrar(cliente)
    lid = cliente.post("/api/licencias", json={"personal_id": datos["ujier1"], "tipo_licencia_id": 1,
                                               "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-17",
                                               "organo_aprobador": "RRHH"}).json()["id"]
    r = cliente.post(f"/api/licencias/{lid}/adjunto", files={"archivo": ("nota.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200
    r = cliente.get(f"/api/licencias/{lid}/adjunto")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 x"
    r = cliente.post(f"/api/licencias/{lid}/adjunto", files={"archivo": ("virus.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


def test_ics_dtend_exclusivo(cliente, datos, conn):
    entrar(cliente)
    cliente.post("/api/licencias", json={"personal_id": datos["juez1"], "tipo_licencia_id": 1,
                                         "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-20",
                                         "organo_aprobador": "CONSEJO"})
    r = cliente.get(f"/api/exportar.ics?desde=2026-11-01&hasta=2026-11-30&personal_id={datos['juez1']}")
    texto = r.text
    assert "BEGIN:VEVENT" in texto
    assert "DTSTART;VALUE=DATE:20261116" in texto
    assert "DTEND;VALUE=DATE:20261121" in texto                   # fin 20/11 inclusivo -> 21 exclusivo
    token = conn.execute("SELECT ics_token FROM personal WHERE id = ?", (datos["juez1"],)).fetchone()["ics_token"]
    assert cliente.get(f"/ics/{token}.ics").status_code == 200
    assert cliente.get("/ics/no-existe.ics").status_code == 404


def test_detalles_devuelven_json(cliente, datos):
    entrar(cliente)
    lid = cliente.post("/api/licencias", json={"personal_id": datos["juez1"], "tipo_licencia_id": 1,
                                               "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-20",
                                               "organo_aprobador": "CONSEJO"}).json()["id"]
    iid = cliente.post("/api/interinatos", json={"titular_id": datos["juez1"], "interino_id": datos["juez2"],
                                                 "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-20"}).json()["id"]
    assert cliente.get(f"/api/licencias/{lid}").status_code == 200
    assert cliente.get(f"/api/interinatos/{iid}").status_code == 200
