"""Pruebas de la API: sesión, permisos, códigos de respuesta y exportación .ics."""
import pytest
from fastapi.testclient import TestClient

from app import db
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


def test_candidatos_del_mismo_despacho_primero(cliente, datos, conn):
    with db.escritura(conn):
        despacho = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["secretario1"],)).fetchone()
        companera = conn.execute("INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) "
                                 "VALUES ('Zulma (mismo turno)', 'SECRETARIO', ?)", (despacho["despacho_id"],)).lastrowid
    entrar(cliente)
    r = cliente.get(f"/api/disponibilidad?titular_id={datos['secretario1']}&desde=2026-11-16&hasta=2026-11-20").json()
    assert r["candidatos"][0]["id"] == companera and r["candidatos"][0]["mismo_despacho"]


def test_admin_cambia_tope_y_turno(cliente, datos):
    entrar(cliente)
    assert cliente.put("/api/cargos/UJIER", json={"max_interinatos_simultaneos": None}).status_code == 200
    assert cliente.put("/api/cargos/UJIER", json={"max_interinatos_simultaneos": 1}).status_code == 200
    r = cliente.post("/api/despachos", json={"nombre": "Juzgado Civil", "fuero": "Civil", "localidad": "Caacupé",
                                            "turno": "2º Turno"})
    assert r.status_code == 201
    desp = [x for x in cliente.get("/api/catalogos").json()["despachos"] if x["id"] == r.json()["id"]][0]
    assert desp["turno"] == "2º Turno"
    entrar(cliente, "oper")
    assert cliente.put("/api/cargos/UJIER", json={"max_interinatos_simultaneos": 3}).status_code == 403


def test_flujo_vacante_por_api(cliente, datos, conn):
    entrar(cliente, "oper")
    despacho = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["actuario1"],)).fetchone()["despacho_id"]
    cuerpo = {"despacho_id": despacho, "cargo_codigo": "ACTUARIO", "secretaria": "Nº 2", "fecha_desde": "2026-11-16"}
    assert cliente.post("/api/vacantes", json=cuerpo).status_code == 403        # solo ADMIN crea puestos
    entrar(cliente)
    vid = cliente.post("/api/vacantes", json=cuerpo).json()["id"]
    entrar(cliente, "oper")                                                   # el operador asigna
    disp = cliente.get(f"/api/disponibilidad?vacante_id={vid}&desde=2026-11-16&hasta=2026-11-30").json()
    assert disp["candidatos"][0]["id"] == datos["actuario1"] and disp["candidatos"][0]["mismo_despacho"]
    r = cliente.post("/api/interinatos", json={"vacante_id": vid, "interino_id": datos["actuario1"],
                                               "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-30"})
    assert r.status_code == 201
    iid = r.json()["id"]
    p = cliente.get("/api/pizarra?desde=2026-11-16&hasta=2026-11-29").json()
    assert [v["id"] for v in p["vacantes"]] == [vid]
    it = [i for i in p["interinatos"] if i["id"] == iid][0]
    assert it["titular"] == "Puesto vacante (Sria. Nº 2)" and it["vacante_id"] == vid
    det = cliente.get(f"/api/interinatos/{iid}").json()
    assert det["vacante_secretaria"] == "Nº 2"
    assert cliente.get(f"/api/vacantes/{vid}").json()["interinatos"][0]["id"] == iid
    ics = cliente.get(f"/api/exportar.ics?desde=2026-11-01&hasta=2026-11-30&personal_id={datos['actuario1']}").text
    assert "puesto vacante (Sria. N" in ics
    # Cerrar el puesto (llegó una actuaria titular) con la versión vigente
    entrar(cliente)
    v = cliente.get(f"/api/vacantes/{vid}").json()
    r = cliente.put(f"/api/vacantes/{vid}", json={**cuerpo, "fecha_hasta": "2026-11-30", "version": v["version"]})
    assert r.status_code == 200
    # Sin titular ni vacante -> error claro
    r = cliente.post("/api/interinatos", json={"interino_id": datos["actuario1"],
                                               "fecha_inicio": "2026-12-01", "fecha_fin": "2026-12-02"})
    assert r.status_code == 409 and r.json()["hallazgos"][0]["regla"] == "R0"


def test_personal_con_secretaria(cliente, datos, conn):
    entrar(cliente)
    despacho = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["actuario1"],)).fetchone()["despacho_id"]
    r = cliente.put(f"/api/personal/{datos['actuario1']}", json={
        "nombre_completo": "Hartelsberger, Noelia Lucina", "cargo_codigo": "ACTUARIO",
        "despacho_id": despacho, "secretaria": "Nº 1"})
    assert r.status_code == 200
    p = [x for x in cliente.get("/api/personal").json() if x["id"] == datos["actuario1"]][0]
    assert p["secretaria"] == "Nº 1"
