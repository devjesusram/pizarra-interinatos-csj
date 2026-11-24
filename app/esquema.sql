-- Pizarra digital de interinatos y licencias
-- Circunscripción Judicial de Cordillera
-- Esquema SQLite, versión 1
--
-- Las fechas se guardan como texto ISO 'AAAA-MM-DD' (fin inclusivo).
-- Los instantes se guardan en UTC como 'AAAA-MM-DDTHH:MM:SSZ'.

-- ── Catálogos ──────────────────────────────────────────────────────────
CREATE TABLE cargos (
  codigo            TEXT PRIMARY KEY,                 -- JUEZ | ACTUARIO | SECRETARIO | UJIER
  nombre            TEXT NOT NULL,
  orden_pizarra     INTEGER NOT NULL,
  organo_aprobador  TEXT NOT NULL CHECK (organo_aprobador IN ('CONSEJO','RRHH')),
  -- Cuántos despachos puede cubrir a la vez una misma persona. NULL = sin límite.
  max_interinatos_simultaneos INTEGER CHECK (max_interinatos_simultaneos IS NULL OR max_interinatos_simultaneos > 0)
);

CREATE TABLE despachos (
  id        INTEGER PRIMARY KEY,
  nombre    TEXT NOT NULL UNIQUE,
  fuero     TEXT NOT NULL,
  localidad TEXT NOT NULL,
  activo    INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE personal (
  id              INTEGER PRIMARY KEY,
  nombre_completo TEXT NOT NULL,
  cargo_codigo    TEXT NOT NULL REFERENCES cargos(codigo),
  despacho_id     INTEGER NOT NULL REFERENCES despachos(id),
  email           TEXT UNIQUE,
  ics_token       TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(16)))),
  activo          INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);
CREATE INDEX personal_cargo_idx ON personal (cargo_codigo);

CREATE TABLE tipos_licencia (
  id     INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE,
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE dias_inhabiles (
  fecha       TEXT PRIMARY KEY CHECK (fecha GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  descripcion TEXT NOT NULL
);

-- ── Usuarios del sistema (independiente de Active Directory) ───────────
CREATE TABLE usuarios (
  id         INTEGER PRIMARY KEY,
  usuario    TEXT NOT NULL UNIQUE,
  nombre     TEXT NOT NULL,
  rol        TEXT NOT NULL CHECK (rol IN ('ADMIN','OPERADOR')),
  hash_clave TEXT NOT NULL,
  activo     INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  creado_en  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE sesiones (
  token      TEXT PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  expira     TEXT NOT NULL
);

-- ── Licencias ──────────────────────────────────────────────────────────
CREATE TABLE licencias (
  id               INTEGER PRIMARY KEY,
  personal_id      INTEGER NOT NULL REFERENCES personal(id),
  tipo_licencia_id INTEGER NOT NULL REFERENCES tipos_licencia(id),
  fecha_inicio     TEXT NOT NULL CHECK (fecha_inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  fecha_fin        TEXT NOT NULL CHECK (fecha_fin GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  organo_aprobador TEXT NOT NULL CHECK (organo_aprobador IN ('CONSEJO','RRHH')),
  nro_resolucion   TEXT,
  correo_remitente TEXT,
  correo_asunto    TEXT,
  correo_fecha     TEXT,
  adjunto_nombre   TEXT,
  adjunto_ruta     TEXT,
  enlace_externo   TEXT,
  observaciones    TEXT,
  estado           TEXT NOT NULL DEFAULT 'VIGENTE' CHECK (estado IN ('VIGENTE','ANULADA')),
  motivo_anulacion TEXT,
  version          INTEGER NOT NULL DEFAULT 1,
  creado_por       INTEGER REFERENCES usuarios(id),
  creado_en        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  modificado_por   INTEGER REFERENCES usuarios(id),
  modificado_en    TEXT,
  CHECK (fecha_fin >= fecha_inicio)
);
CREATE INDEX licencias_persona_idx ON licencias (personal_id, fecha_inicio);
CREATE INDEX licencias_fechas_idx ON licencias (fecha_inicio, fecha_fin);

-- Una persona no puede tener dos licencias vigentes que se crucen
CREATE TRIGGER lic_sin_solape_ins BEFORE INSERT ON licencias
WHEN NEW.estado = 'VIGENTE'
BEGIN
  SELECT RAISE(ABORT, 'LIC_SOLAPE')
  WHERE EXISTS (SELECT 1 FROM licencias l
                WHERE l.personal_id = NEW.personal_id AND l.estado = 'VIGENTE'
                  AND l.fecha_inicio <= NEW.fecha_fin AND l.fecha_fin >= NEW.fecha_inicio);
END;

CREATE TRIGGER lic_sin_solape_upd BEFORE UPDATE OF personal_id, fecha_inicio, fecha_fin, estado ON licencias
WHEN NEW.estado = 'VIGENTE'
BEGIN
  SELECT RAISE(ABORT, 'LIC_SOLAPE')
  WHERE EXISTS (SELECT 1 FROM licencias l
                WHERE l.id <> NEW.id AND l.personal_id = NEW.personal_id AND l.estado = 'VIGENTE'
                  AND l.fecha_inicio <= NEW.fecha_fin AND l.fecha_fin >= NEW.fecha_inicio);
END;

-- ── Interinatos manuales ───────────────────────────────────────────────
CREATE TABLE interinatos (
  id               INTEGER PRIMARY KEY,
  titular_id       INTEGER NOT NULL REFERENCES personal(id),   -- el ausente
  interino_id      INTEGER NOT NULL REFERENCES personal(id),   -- quien cubre
  cargo_codigo     TEXT NOT NULL REFERENCES cargos(codigo),    -- cargo cubierto
  licencia_id      INTEGER REFERENCES licencias(id),
  fecha_inicio     TEXT NOT NULL CHECK (fecha_inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  fecha_fin        TEXT NOT NULL CHECK (fecha_fin GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  acto_designacion TEXT,
  observaciones    TEXT,
  estado           TEXT NOT NULL DEFAULT 'VIGENTE' CHECK (estado IN ('VIGENTE','EN_CONFLICTO','ANULADO')),
  motivo_anulacion TEXT,
  version          INTEGER NOT NULL DEFAULT 1,
  creado_por       INTEGER REFERENCES usuarios(id),
  creado_en        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  modificado_por   INTEGER REFERENCES usuarios(id),
  modificado_en    TEXT,
  CHECK (fecha_fin >= fecha_inicio),
  CHECK (titular_id <> interino_id)
);
CREATE INDEX interinatos_titular_idx ON interinatos (titular_id, fecha_inicio);
CREATE INDEX interinatos_interino_idx ON interinatos (interino_id, fecha_inicio);
CREATE INDEX interinatos_fechas_idx ON interinatos (fecha_inicio, fecha_fin);

-- Solo entre pares (Juez-Juez, Actuario-Actuario, ...): el cargo cubierto
-- debe coincidir con el del titular y con el del interino.
CREATE TRIGGER int_pares_ins BEFORE INSERT ON interinatos
BEGIN
  SELECT RAISE(ABORT, 'INT_PARES')
  WHERE (SELECT cargo_codigo FROM personal WHERE id = NEW.titular_id) IS NOT NEW.cargo_codigo
     OR (SELECT cargo_codigo FROM personal WHERE id = NEW.interino_id) IS NOT NEW.cargo_codigo;
END;

CREATE TRIGGER int_pares_upd BEFORE UPDATE OF titular_id, interino_id, cargo_codigo ON interinatos
BEGIN
  SELECT RAISE(ABORT, 'INT_PARES')
  WHERE (SELECT cargo_codigo FROM personal WHERE id = NEW.titular_id) IS NOT NEW.cargo_codigo
     OR (SELECT cargo_codigo FROM personal WHERE id = NEW.interino_id) IS NOT NEW.cargo_codigo;
END;

-- Un titular tiene como máximo un interino por día
CREATE TRIGGER int_titular_unico_ins BEFORE INSERT ON interinatos
WHEN NEW.estado <> 'ANULADO'
BEGIN
  SELECT RAISE(ABORT, 'INT_TITULAR_UNICO')
  WHERE EXISTS (SELECT 1 FROM interinatos i
                WHERE i.titular_id = NEW.titular_id AND i.estado <> 'ANULADO'
                  AND i.fecha_inicio <= NEW.fecha_fin AND i.fecha_fin >= NEW.fecha_inicio);
END;

CREATE TRIGGER int_titular_unico_upd BEFORE UPDATE OF titular_id, fecha_inicio, fecha_fin, estado ON interinatos
WHEN NEW.estado <> 'ANULADO'
BEGIN
  SELECT RAISE(ABORT, 'INT_TITULAR_UNICO')
  WHERE EXISTS (SELECT 1 FROM interinatos i
                WHERE i.id <> NEW.id AND i.titular_id = NEW.titular_id AND i.estado <> 'ANULADO'
                  AND i.fecha_inicio <= NEW.fecha_fin AND i.fecha_fin >= NEW.fecha_inicio);
END;

-- Exclusividad del interino para todos los cargos salvo jueces
CREATE TRIGGER int_interino_unico_ins BEFORE INSERT ON interinatos
WHEN NEW.estado <> 'ANULADO' AND NEW.cargo_codigo <> 'JUEZ'
BEGIN
  SELECT RAISE(ABORT, 'INT_INTERINO_UNICO')
  WHERE EXISTS (SELECT 1 FROM interinatos i
                WHERE i.interino_id = NEW.interino_id AND i.estado <> 'ANULADO'
                  AND i.fecha_inicio <= NEW.fecha_fin AND i.fecha_fin >= NEW.fecha_inicio);
END;

CREATE TRIGGER int_interino_unico_upd BEFORE UPDATE OF interino_id, fecha_inicio, fecha_fin, estado, cargo_codigo ON interinatos
WHEN NEW.estado <> 'ANULADO' AND NEW.cargo_codigo <> 'JUEZ'
BEGIN
  SELECT RAISE(ABORT, 'INT_INTERINO_UNICO')
  WHERE EXISTS (SELECT 1 FROM interinatos i
                WHERE i.id <> NEW.id AND i.interino_id = NEW.interino_id AND i.estado <> 'ANULADO'
                  AND i.fecha_inicio <= NEW.fecha_fin AND i.fecha_fin >= NEW.fecha_inicio);
END;

-- ── Auditoría ──────────────────────────────────────────────────────────
CREATE TABLE auditoria (
  id                       INTEGER PRIMARY KEY,
  tabla                    TEXT NOT NULL,
  registro_id              INTEGER NOT NULL,
  accion                   TEXT NOT NULL,              -- CREAR | MODIFICAR | ANULAR
  datos                    TEXT NOT NULL,              -- JSON
  advertencias_confirmadas TEXT,                       -- JSON
  usuario_id               INTEGER REFERENCES usuarios(id),
  ts                       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX auditoria_ts_idx ON auditoria (ts DESC);

CREATE TABLE version_esquema (
  version     INTEGER PRIMARY KEY,
  aplicado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
INSERT INTO version_esquema (version) VALUES (1);

-- ── Datos base ─────────────────────────────────────────────────────────
INSERT INTO cargos (codigo, nombre, orden_pizarra, organo_aprobador, max_interinatos_simultaneos) VALUES
  ('JUEZ',       'Juez',                    1, 'CONSEJO', NULL),
  ('ACTUARIO',   'Actuario/a Judicial',     2, 'RRHH',    1),
  ('SECRETARIO', 'Secretario/a de Juzgado', 3, 'RRHH',    1),
  ('UJIER',      'Ujier Titular',           4, 'RRHH',    1);

INSERT INTO tipos_licencia (nombre) VALUES
  ('Vacaciones'), ('Médica'), ('Maternidad'), ('Paternidad'),
  ('Estudio / Capacitación'), ('Particular'), ('Duelo'),
  ('Comisión de servicio'), ('Otra');
