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


def test_eliminar_funcionario_duplicado(cliente, datos, conn):
    entrar(cliente)
    despacho = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["juez1"],)).fetchone()["despacho_id"]
    dup = cliente.post("/api/personal", json={"nombre_completo": "Juez 1 (duplicado)", "cargo_codigo": "JUEZ",
                                              "despacho_id": despacho}).json()["id"]
    fila = [p for p in cliente.get("/api/personal").json() if p["id"] == dup][0]
    assert fila["registros"] == 0                                     # el botón Eliminar se muestra
    entrar(cliente, "oper")
    assert cliente.delete(f"/api/personal/{dup}").status_code == 403  # solo ADMIN
    entrar(cliente)
    assert cliente.delete(f"/api/personal/{dup}").status_code == 200
    assert not [p for p in cliente.get("/api/personal").json() if p["id"] == dup]
    aud = conn.execute("SELECT datos FROM auditoria WHERE tabla = 'personal' AND registro_id = ? AND accion = 'ELIMINAR'",
                       (dup,)).fetchone()
    assert "Juez 1 (duplicado)" in aud["datos"]                       # queda constancia de lo borrado
    assert cliente.delete(f"/api/personal/{dup}").status_code == 404


def test_no_se_elimina_funcionario_con_historial(cliente, datos):
    entrar(cliente)
    cliente.post("/api/licencias", json={"personal_id": datos["ujier1"], "tipo_licencia_id": 1,
                                         "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-17", "organo_aprobador": "RRHH"})
    cliente.post("/api/interinatos", json={"titular_id": datos["ujier2"], "interino_id": datos["ujier3"],
                                           "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-17",
                                           "confirmar_advertencias": True})
    registros = {p["id"]: p["registros"] for p in cliente.get("/api/personal").json()}
    assert registros[datos["ujier1"]] == 1 and registros[datos["ujier3"]] == 1 and registros[datos["ujier2"]] == 1
    for quien in ("ujier1", "ujier2", "ujier3"):                    # licencia, titular e interino
        r = cliente.delete(f"/api/personal/{datos[quien]}")
        assert r.status_code == 409 and "Desactívelo" in r.json()["detail"]


def test_version_y_cache_de_la_pagina(cliente, datos):
    from app import __version__
    entrar(cliente)
    assert cliente.get("/api/yo").json()["version"] == __version__
    for ruta in ("/", "/static/app.js", "/static/estilos.css"):
        assert cliente.get(ruta).headers["cache-control"] == "no-cache"


def test_manual_sin_internet_ni_sesion(cliente):
    r = cliente.get("/manual")
    assert r.status_code == 200 and "Manual de usuario" in r.text
    import re
    imagenes = re.findall(r'src="(/static/manual/[^"]+)"', r.text)
    assert len(imagenes) == 19
    for src in imagenes:                                  # todas las capturas están incluidas
        assert cliente.get(src).status_code == 200
    assert "http" not in "".join(re.findall(r'(?:src|href)="([^"]+)"', r.text)).replace("http://172.31.60.254:8090", "")


def test_eliminar_despacho_solo_si_vacio(cliente, datos, conn):
    entrar(cliente)
    nuevo = cliente.post("/api/despachos", json={"nombre": "Juzgado cargado por error", "fuero": "Civil",
                                                 "localidad": "Caacupé"}).json()["id"]
    desp = {d["id"]: d for d in cliente.get("/api/catalogos").json()["despachos"]}
    assert desp[nuevo]["registros"] == 0
    con_gente = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["juez1"],)).fetchone()["despacho_id"]
    assert desp[con_gente]["registros"] == 4
    r = cliente.delete(f"/api/despachos/{con_gente}")
    assert r.status_code == 409 and "muévalos" in r.json()["detail"]
    entrar(cliente, "oper")
    assert cliente.delete(f"/api/despachos/{nuevo}").status_code == 403
    entrar(cliente)
    assert cliente.delete(f"/api/despachos/{nuevo}").status_code == 200
    assert nuevo not in {d["id"] for d in cliente.get("/api/catalogos").json()["despachos"]}


def test_eliminar_vacante_solo_si_nunca_tuvo_a_cargo(cliente, datos, conn):
    entrar(cliente)
    despacho = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["actuario1"],)).fetchone()["despacho_id"]
    v1 = cliente.post("/api/vacantes", json={"despacho_id": despacho, "cargo_codigo": "ACTUARIO", "secretaria": "Nº 2",
                                             "fecha_desde": "2026-11-16"}).json()["id"]
    v2 = cliente.post("/api/vacantes", json={"despacho_id": despacho, "cargo_codigo": "UJIER",
                                             "fecha_desde": "2026-11-16"}).json()["id"]
    cliente.post("/api/interinatos", json={"vacante_id": v1, "interino_id": datos["actuario1"],
                                           "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-20"})
    regs = {v["id"]: v["registros"] for v in cliente.get("/api/vacantes").json()}
    assert regs == {v1: 1, v2: 0}
    r = cliente.delete(f"/api/vacantes/{v1}")
    assert r.status_code == 409 and "Vacante hasta" in r.json()["detail"]
    assert cliente.delete(f"/api/vacantes/{v2}").status_code == 200


def test_eliminar_usuario_solo_si_no_trabajo(cliente, datos):
    entrar(cliente)
    nuevo = cliente.post("/api/usuarios", json={"usuario": "error", "nombre": "Usuario por error",
                                                "rol": "OPERADOR", "clave": "12345678"}).json()["id"]
    us = {u["usuario"]: u for u in cliente.get("/api/usuarios").json()}
    assert us["error"]["registros"] == 0 and us["admin"]["registros"] > 0     # admin creó al nuevo (auditoría)
    assert cliente.delete(f"/api/usuarios/{us['admin']['id']}").status_code == 400   # no a sí mismo
    entrar(cliente, "oper")
    cliente.post("/api/licencias", json={"personal_id": datos["juez1"], "tipo_licencia_id": 1,
                                         "fecha_inicio": "2026-11-16", "fecha_fin": "2026-11-17", "organo_aprobador": "CONSEJO"})
    entrar(cliente)
    oper = {u["usuario"]: u for u in cliente.get("/api/usuarios").json()}["oper"]
    r = cliente.delete(f"/api/usuarios/{oper['id']}")
    assert r.status_code == 409 and "Puede ingresar" in r.json()["detail"]   # ya trabajó: se desactiva
    assert cliente.delete(f"/api/usuarios/{nuevo}").status_code == 200
    assert "error" not in {u["usuario"] for u in cliente.get("/api/usuarios").json()}


def test_mover_funcionario_al_equipo_de_otro_despacho(cliente, datos, conn):
    """Lo que hace el botón Equipo: pasar a una secretaria al despacho del juez, con su Secretaría."""
    entrar(cliente)
    despacho_juez = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["juez1"],)).fetchone()["despacho_id"]
    for quien, sria in (("secretario2", "Nº 1"), ("secretario3", "Nº 2")):
        p = [x for x in cliente.get("/api/personal").json() if x["id"] == datos[quien]][0]
        r = cliente.put(f"/api/personal/{p['id']}", json={"nombre_completo": p["nombre_completo"], "cargo_codigo": p["cargo_codigo"],
                                                          "despacho_id": despacho_juez, "secretaria": sria, "activo": True})
        assert r.status_code == 200
    equipo = [x for x in cliente.get("/api/personal").json() if x["despacho_id"] == despacho_juez and x["cargo_codigo"] == "SECRETARIO"]
    assert sorted(x["secretaria"] or "" for x in equipo) == ["", "Nº 1", "Nº 2"]   # la original + las dos nuevas
