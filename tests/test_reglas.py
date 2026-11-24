"""Pruebas de las reglas de control de fechas (R1–R10, L1–L2)."""
import json
import sqlite3
import threading

import pytest

from app import db, servicios
from app.validaciones import Bloqueado, ConflictoVersion, RequiereConfirmacion

from .conftest import d


def lic(conn, ids, quien, ini, fin, tipo=1):
    return servicios.crear_licencia(conn, {"personal_id": ids[quien], "tipo_licencia_id": tipo,
                                           "fecha_inicio": d(ini), "fecha_fin": d(fin),
                                           "organo_aprobador": "RRHH"}, ids["uid"])


def inter(conn, ids, titular, interino, ini, fin, confirmar=True):
    return servicios.crear_interinato(conn, {"titular_id": ids[titular], "interino_id": ids[interino],
                                             "fecha_inicio": d(ini), "fecha_fin": d(fin)},
                                      ids["uid"], confirmar_advertencias=confirmar)


def reglas(exc):
    return {h.regla for h in exc.value.hallazgos}


def test_r1_fechas_invertidas(conn, datos):
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "juez1", "juez2", 5, 2)
    assert reglas(e) == {"R1"}


def test_r2_misma_persona(conn, datos):
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "juez1", "juez1", 0, 2)
    assert reglas(e) == {"R2"}


def test_r3_inactivo(conn, datos):
    conn.execute("UPDATE personal SET activo = 0 WHERE id = ?", (datos["juez2"],))
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "juez1", "juez2", 0, 2)
    assert "R3" in reglas(e)


def test_r4_interino_de_licencia(conn, datos):
    lic(conn, datos, "juez2", 3, 6)
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "juez1", "juez2", 0, 4)
    assert "R4" in reglas(e)
    assert "de licencia" in e.value.hallazgos[0].mensaje


def test_r5_ujier_no_puede_cubrir_dos(conn, datos):
    inter(conn, datos, "ujier1", "ujier3", 0, 4)
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "ujier2", "ujier3", 4, 8)
    assert reglas(e) == {"R5"}


def test_r5_juez_puede_acumular_despachos(conn, datos):
    inter(conn, datos, "juez1", "juez3", 0, 4)
    _, infos = inter(conn, datos, "juez2", "juez3", 2, 8)
    assert [h.regla for h in infos] == ["R5-info"]
    assert "2 despachos" in infos[0].mensaje


def test_r5_sin_solape_no_bloquea(conn, datos):
    inter(conn, datos, "ujier1", "ujier3", 0, 4)
    inter(conn, datos, "ujier2", "ujier3", 5, 8)   # empieza al día siguiente: válido


def test_r6_titular_ya_cubierto(conn, datos):
    inter(conn, datos, "juez1", "juez2", 0, 4)
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "juez1", "juez3", 3, 6)
    assert reglas(e) == {"R6"}


def test_r7_interino_ausente_y_cubierto(conn, datos):
    inter(conn, datos, "juez2", "juez3", 0, 4)     # juez2 está ausente
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "juez1", "juez2", 2, 3)
    assert "R7" in reglas(e)


def test_r8_requiere_confirmacion_si_titular_sin_licencia(conn, datos):
    with pytest.raises(RequiereConfirmacion) as e:
        inter(conn, datos, "juez1", "juez2", 0, 4, confirmar=False)
    assert reglas(e) == {"R8"}
    inter(conn, datos, "juez1", "juez2", 0, 4, confirmar=True)   # confirmado: se guarda


def test_r8_no_avisa_si_licencia_cubre_el_periodo(conn, datos):
    lic(conn, datos, "juez1", 0, 9)
    inter(conn, datos, "juez1", "juez2", 0, 4, confirmar=False)


def test_r9_solo_entre_pares(conn, datos):
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "secretario1", "actuario2", 0, 4)
    assert reglas(e) == {"R9"}


def test_r9_tambien_lo_garantiza_la_base_de_datos(conn, datos):
    with pytest.raises(sqlite3.IntegrityError, match="INT_PARES"):
        conn.execute("INSERT INTO interinatos (titular_id, interino_id, cargo_codigo, fecha_inicio, fecha_fin) "
                     "VALUES (?, ?, 'JUEZ', '2026-11-16', '2026-11-17')", (datos["juez1"], datos["ujier2"]))


def test_reglas_en_bd_aunque_se_saltee_el_backend(conn, datos):
    q = ("INSERT INTO interinatos (titular_id, interino_id, cargo_codigo, fecha_inicio, fecha_fin) "
         "VALUES (?, ?, ?, '2026-11-16', '2026-11-20')")
    conn.execute(q, (datos["ujier1"], datos["ujier3"], "UJIER"))
    with pytest.raises(sqlite3.IntegrityError, match="INT_INTERINO_UNICO"):
        conn.execute(q, (datos["ujier2"], datos["ujier3"], "UJIER"))
    with pytest.raises(sqlite3.IntegrityError, match="INT_TITULAR_UNICO"):
        conn.execute(q, (datos["ujier1"], datos["ujier2"], "UJIER"))
    conn.execute(q, (datos["juez1"], datos["juez3"], "JUEZ"))
    conn.execute(q, (datos["juez2"], datos["juez3"], "JUEZ"))      # jueces: se permite acumular
    lq = ("INSERT INTO licencias (personal_id, tipo_licencia_id, fecha_inicio, fecha_fin, organo_aprobador) "
          "VALUES (?, 1, ?, ?, 'RRHH')")
    conn.execute(lq, (datos["actuario1"], "2026-11-16", "2026-11-20"))
    with pytest.raises(sqlite3.IntegrityError, match="LIC_SOLAPE"):
        conn.execute(lq, (datos["actuario1"], "2026-11-20", "2026-11-25"))


def test_r10_version_desactualizada(conn, datos):
    iid, _ = inter(conn, datos, "juez1", "juez2", 0, 4)
    base = {"titular_id": datos["juez1"], "interino_id": datos["juez2"],
            "fecha_inicio": d(0), "fecha_fin": d(5)}
    servicios.editar_interinato(conn, iid, base, 1, datos["uid"], True)       # pasa a versión 2
    with pytest.raises(ConflictoVersion) as e:
        servicios.editar_interinato(conn, iid, base, 1, datos["uid"], True)   # otro operador con v1
    assert "modificado por Admin" in str(e.value)


def test_l1_licencias_solapadas(conn, datos):
    lic(conn, datos, "actuario1", 0, 4)
    with pytest.raises(Bloqueado) as e:
        lic(conn, datos, "actuario1", 4, 6)
    assert reglas(e) == {"L1"}


def test_l2_licencia_del_interino_marca_conflicto_y_anular_lo_revierte(conn, datos):
    lic(conn, datos, "ujier1", 0, 9)
    iid, _ = inter(conn, datos, "ujier1", "ujier2", 0, 9)
    lid, avisos = lic(conn, datos, "ujier2", 5, 6)        # la licencia NO se bloquea
    assert [a.regla for a in avisos] == ["L2"]
    estado = lambda: conn.execute("SELECT estado FROM interinatos WHERE id = ?", (iid,)).fetchone()["estado"]
    assert estado() == "EN_CONFLICTO"
    servicios.anular_licencia(conn, lid, "Cargada por error", 1, datos["uid"])
    assert estado() == "VIGENTE"


def test_editar_interinato_resuelve_conflicto(conn, datos):
    lic(conn, datos, "ujier1", 0, 9)
    iid, _ = inter(conn, datos, "ujier1", "ujier2", 0, 9)
    lic(conn, datos, "ujier2", 5, 6)
    v = conn.execute("SELECT version FROM interinatos WHERE id = ?", (iid,)).fetchone()["version"]
    servicios.editar_interinato(conn, iid, {"titular_id": datos["ujier1"], "interino_id": datos["ujier3"],
                                            "fecha_inicio": d(0), "fecha_fin": d(9)}, v, datos["uid"])
    assert conn.execute("SELECT estado FROM interinatos WHERE id = ?", (iid,)).fetchone()["estado"] == "VIGENTE"


def test_alertas_sin_cubrir(conn, datos):
    lid, _ = lic(conn, datos, "secretario1", 0, 4)        # lunes a viernes
    inter(conn, datos, "secretario1", "secretario2", 0, 1)
    a = servicios.alertas(conn, d(0))
    assert len(a["sin_cubrir"]) == 1
    assert a["sin_cubrir"][0]["dias_sin_cubrir"] == 3 and a["sin_cubrir"][0]["primer_dia"] == d(2).isoformat()


def test_auditoria_guarda_advertencias_confirmadas(conn, datos):
    iid, _ = inter(conn, datos, "juez1", "juez2", 0, 4, confirmar=True)
    r = conn.execute("SELECT advertencias_confirmadas FROM auditoria WHERE tabla = 'interinatos' "
                     "AND registro_id = ?", (iid,)).fetchone()
    assert json.loads(r["advertencias_confirmadas"])[0]["regla"] == "R8"


def test_dos_operadores_a_la_vez_no_generan_cruces(datos):
    """Dos operadores asignan al mismo secretario, a la vez, para cubrir a dos titulares.
    Solo uno debe poder guardar; el otro recibe el bloqueo R5 (ujier: tope 1)."""
    resultados, barrera = [], threading.Barrier(2)

    def operador(titular):
        c = db.conectar()
        try:
            barrera.wait()
            servicios.crear_interinato(c, {"titular_id": datos[titular], "interino_id": datos["ujier3"],
                                           "fecha_inicio": d(0), "fecha_fin": d(4)},
                                       datos["uid"], confirmar_advertencias=True)
            resultados.append("ok")
        except Bloqueado as e:
            resultados.append(e.hallazgos[0].regla)
        finally:
            c.close()

    hilos = [threading.Thread(target=operador, args=(t,)) for t in ("ujier1", "ujier2")]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(resultados) == ["R5", "ok"]


def test_respaldo_y_restauracion(conn, datos, tmp_path):
    from app import cli
    lid, _ = lic(conn, datos, "juez1", 0, 4)
    copia = cli.respaldo(str(tmp_path / "resp"))
    servicios.anular_licencia(conn, lid, "Prueba de restauración", 1, datos["uid"])
    assert conn.execute("SELECT estado FROM licencias WHERE id = ?", (lid,)).fetchone()["estado"] == "ANULADA"
    cli.restaurar(str(copia))
    assert conn.execute("SELECT estado FROM licencias WHERE id = ?", (lid,)).fetchone()["estado"] == "VIGENTE"


def test_juez_cubre_tres_juzgados_ademas_del_propio(conn, datos):
    """Un juez puede interinar 3 (o más) juzgados a la vez, además de su juzgado natural."""
    with db.escritura(conn):
        did = conn.execute("INSERT INTO despachos (nombre, fuero, localidad) VALUES ('J4', 'Penal', 'Tobatí')").lastrowid
        datos["juez4"] = conn.execute("INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) "
                                      "VALUES ('Juez 4', 'JUEZ', ?)", (did,)).lastrowid
    inter(conn, datos, "juez1", "juez4", 0, 9)
    inter(conn, datos, "juez2", "juez4", 0, 9)
    _, infos = inter(conn, datos, "juez3", "juez4", 2, 6)
    assert "3 despachos" in infos[0].mensaje
    n = conn.execute("SELECT count(*) AS n FROM interinatos WHERE interino_id = ? AND estado = 'VIGENTE'",
                     (datos["juez4"],)).fetchone()["n"]
    assert n == 3


def test_dos_secretarias_del_mismo_juzgado(conn, datos):
    """Dos secretarias en el mismo juzgado (turno): una puede cubrir a la otra."""
    with db.escritura(conn):
        despacho = conn.execute("SELECT despacho_id FROM personal WHERE id = ?", (datos["secretario1"],)).fetchone()
        datos["secretaria1b"] = conn.execute(
            "INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES ('Secretaria 1B', 'SECRETARIO', ?)",
            (despacho["despacho_id"],)).lastrowid
    lic(conn, datos, "secretario1", 0, 4)
    inter(conn, datos, "secretario1", "secretaria1b", 0, 4, confirmar=False)
    # Además puede cubrir a otra secretaria al mismo tiempo (secretarios: sin límite)
    _, infos = inter(conn, datos, "secretario2", "secretaria1b", 2, 3)
    assert "2 despachos" in infos[0].mensaje


def test_actuario_y_secretario_cubren_mas_de_tres_a_la_vez(conn, datos):
    with db.escritura(conn):
        for n in (4, 5):
            did = conn.execute("INSERT INTO despachos (nombre, fuero, localidad) VALUES (?, 'Civil', 'Caacupé')",
                               (f"J{n}",)).lastrowid
            for c in ("ACTUARIO", "SECRETARIO"):
                datos[f"{c.lower()}{n}"] = conn.execute(
                    "INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES (?, ?, ?)",
                    (f"{c.title()} {n}", c, did)).lastrowid
    for cargo in ("actuario", "secretario"):
        for titular in (1, 2, 3, 4):
            _, infos = inter(conn, datos, f"{cargo}{titular}", f"{cargo}5", 0, 9)
        assert "4 despachos" in infos[0].mensaje


def test_tope_configurable_por_cargo(conn, datos):
    conn.execute("UPDATE cargos SET max_interinatos_simultaneos = 2 WHERE codigo = 'SECRETARIO'")
    inter(conn, datos, "secretario1", "secretario3", 0, 4)
    inter(conn, datos, "secretario2", "secretario3", 0, 4)
    with db.escritura(conn):
        did = conn.execute("INSERT INTO despachos (nombre, fuero, localidad) VALUES ('J9', 'Civil', 'Caacupé')").lastrowid
        datos["secretario9"] = conn.execute("INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) "
                                            "VALUES ('Secretario 9', 'SECRETARIO', ?)", (did,)).lastrowid
    with pytest.raises(Bloqueado) as e:
        inter(conn, datos, "secretario9", "secretario3", 1, 2)       # sería el tercero
    assert reglas(e) == {"R5"}
    assert servicios.excesos_de_tope(conn, "SECRETARIO", 1, d(0))    # no se puede bajar a 1


def test_actualiza_una_base_version_1_sin_perder_datos(tmp_path, monkeypatch):
    """Simula la base que ya está en uso (versión 1) y la actualiza."""
    from pathlib import Path
    from app import config
    vieja = tmp_path / "vieja.db"
    monkeypatch.setattr(config, "DB_PATH", vieja)
    c = db.conectar()
    c.executescript("BEGIN;" + (Path(db.__file__).parent / "esquema.sql").read_text(encoding="utf-8") + "COMMIT;")
    c.execute("INSERT INTO usuarios (usuario, nombre, rol, hash_clave) VALUES ('admin', 'Admin', 'ADMIN', 'x')")
    did = c.execute("INSERT INTO despachos (nombre, fuero, localidad) VALUES ('Juzgado A', 'Civil', 'Caacupé')").lastrowid
    s1 = c.execute("INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES ('S1', 'SECRETARIO', ?)", (did,)).lastrowid
    s2 = c.execute("INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES ('S2', 'SECRETARIO', ?)", (did,)).lastrowid
    s3 = c.execute("INSERT INTO personal (nombre_completo, cargo_codigo, despacho_id) VALUES ('S3', 'SECRETARIO', ?)", (did,)).lastrowid
    q = ("INSERT INTO interinatos (titular_id, interino_id, cargo_codigo, fecha_inicio, fecha_fin) "
         "VALUES (?, ?, 'SECRETARIO', '2026-11-16', '2026-11-20')")
    c.execute(q, (s1, s3))
    with pytest.raises(sqlite3.IntegrityError):          # versión 1: secretario de a uno
        c.execute(q, (s2, s3))
    assert db.version_de(c) == 1

    db.inicializar_esquema(c)                            # aplica la actualización

    assert db.version_de(c) == db.VERSION_ACTUAL
    assert c.execute("SELECT count(*) AS n FROM interinatos").fetchone()["n"] == 1   # datos intactos
    c.execute("UPDATE despachos SET turno = '1º Turno' WHERE id = ?", (did,))         # columna nueva
    c.execute(q, (s2, s3))                               # ahora sí puede cubrir a dos
    respaldos = list((config.RESPALDOS_DIR / "antes-de-actualizar").glob("pizarra-db-v1-*.db"))
    assert len(respaldos) == 1                           # respaldo automático previo
    c.close()
