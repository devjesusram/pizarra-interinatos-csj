-- Pizarra digital de interinatos y licencias
-- Circunscripción Judicial de Cordillera
-- Esquema versión 1

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- EXCLUDE con columnas "="

-- ── Catálogos ──────────────────────────────────────────────────────────
CREATE TABLE cargos (
  codigo            TEXT PRIMARY KEY,                 -- JUEZ | ACTUARIO | SECRETARIO | UJIER
  nombre            TEXT NOT NULL,
  orden_pizarra     SMALLINT NOT NULL,
  organo_aprobador  TEXT NOT NULL CHECK (organo_aprobador IN ('CONSEJO','RRHH')),
  -- Cuántos despachos puede cubrir a la vez una misma persona. NULL = sin límite.
  max_interinatos_simultaneos SMALLINT CHECK (max_interinatos_simultaneos > 0)
);

CREATE TABLE despachos (
  id        SERIAL PRIMARY KEY,
  nombre    TEXT NOT NULL UNIQUE,
  fuero     TEXT NOT NULL,
  localidad TEXT NOT NULL,
  activo    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE personal (
  id              SERIAL PRIMARY KEY,
  nombre_completo TEXT NOT NULL,
  cargo_codigo    TEXT NOT NULL REFERENCES cargos(codigo),
  despacho_id     INT  NOT NULL REFERENCES despachos(id),
  email           TEXT UNIQUE,
  ics_token       UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  activo          BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX personal_cargo_idx ON personal (cargo_codigo);

CREATE TABLE tipos_licencia (
  id     SMALLSERIAL PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE,
  activo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE dias_inhabiles (
  fecha       DATE PRIMARY KEY,
  descripcion TEXT NOT NULL
);

-- ── Usuarios del sistema (independiente de Active Directory) ───────────
CREATE TABLE usuarios (
  id         SERIAL PRIMARY KEY,
  usuario    TEXT NOT NULL UNIQUE,
  nombre     TEXT NOT NULL,
  rol        TEXT NOT NULL CHECK (rol IN ('ADMIN','OPERADOR')),
  hash_clave TEXT NOT NULL,
  activo     BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sesiones (
  token      TEXT PRIMARY KEY,
  usuario_id INT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  expira     TIMESTAMPTZ NOT NULL
);

-- ── Licencias ──────────────────────────────────────────────────────────
CREATE TABLE licencias (
  id               SERIAL PRIMARY KEY,
  personal_id      INT NOT NULL REFERENCES personal(id),
  tipo_licencia_id SMALLINT NOT NULL REFERENCES tipos_licencia(id),
  fecha_inicio     DATE NOT NULL,
  fecha_fin        DATE NOT NULL,                     -- inclusiva
  organo_aprobador TEXT NOT NULL CHECK (organo_aprobador IN ('CONSEJO','RRHH')),
  nro_resolucion   TEXT,
  correo_remitente TEXT,
  correo_asunto    TEXT,
  correo_fecha     TIMESTAMPTZ,
  adjunto_nombre   TEXT,                              -- nombre original del archivo
  adjunto_ruta     TEXT,                              -- nombre en disco
  enlace_externo   TEXT,
  observaciones    TEXT,
  estado           TEXT NOT NULL DEFAULT 'VIGENTE' CHECK (estado IN ('VIGENTE','ANULADA')),
  motivo_anulacion TEXT,
  version          INT  NOT NULL DEFAULT 1,
  creado_por       INT  REFERENCES usuarios(id),
  creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
  modificado_por   INT  REFERENCES usuarios(id),
  modificado_en    TIMESTAMPTZ,
  periodo          DATERANGE GENERATED ALWAYS AS (daterange(fecha_inicio, fecha_fin, '[]')) STORED,

  CHECK (fecha_fin >= fecha_inicio),
  CONSTRAINT lic_sin_solape EXCLUDE USING gist
    (personal_id WITH =, periodo WITH &&) WHERE (estado = 'VIGENTE')
);
CREATE INDEX licencias_periodo_idx ON licencias USING gist (periodo);

-- ── Interinatos manuales ───────────────────────────────────────────────
CREATE TABLE interinatos (
  id               SERIAL PRIMARY KEY,
  titular_id       INT  NOT NULL REFERENCES personal(id),   -- el ausente
  interino_id      INT  NOT NULL REFERENCES personal(id),   -- quien cubre
  cargo_codigo     TEXT NOT NULL REFERENCES cargos(codigo), -- lo completa el trigger
  licencia_id      INT  REFERENCES licencias(id),
  fecha_inicio     DATE NOT NULL,
  fecha_fin        DATE NOT NULL,
  acto_designacion TEXT,
  observaciones    TEXT,
  estado           TEXT NOT NULL DEFAULT 'VIGENTE'
                   CHECK (estado IN ('VIGENTE','EN_CONFLICTO','ANULADO')),
  motivo_anulacion TEXT,
  version          INT  NOT NULL DEFAULT 1,
  creado_por       INT  REFERENCES usuarios(id),
  creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
  modificado_por   INT  REFERENCES usuarios(id),
  modificado_en    TIMESTAMPTZ,
  periodo          DATERANGE GENERATED ALWAYS AS (daterange(fecha_inicio, fecha_fin, '[]')) STORED,

  CHECK (fecha_fin >= fecha_inicio),
  CHECK (titular_id <> interino_id),
  -- Un titular tiene como máximo un interino por día
  CONSTRAINT int_titular_unico EXCLUDE USING gist
    (titular_id WITH =, periodo WITH &&) WHERE (estado <> 'ANULADO'),
  -- Exclusividad para todos los cargos salvo jueces (que pueden acumular despachos)
  CONSTRAINT int_interino_unico_no_juez EXCLUDE USING gist
    (interino_id WITH =, periodo WITH &&) WHERE (estado <> 'ANULADO' AND cargo_codigo <> 'JUEZ')
);
CREATE INDEX interinatos_periodo_idx ON interinatos USING gist (periodo);

-- Regla "solo entre pares" (Juez-Juez, Actuario-Actuario, ...) garantizada por la BD
CREATE FUNCTION interinato_entre_pares() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c_tit TEXT; c_int TEXT;
BEGIN
  SELECT cargo_codigo INTO c_tit FROM personal WHERE id = NEW.titular_id;
  SELECT cargo_codigo INTO c_int FROM personal WHERE id = NEW.interino_id;
  IF c_tit IS DISTINCT FROM c_int THEN
    RAISE EXCEPTION 'Interinato entre cargos distintos (% / %)', c_tit, c_int
      USING HINT = 'Solo entre pares: Juez-Juez, Actuario-Actuario, etc.';
  END IF;
  NEW.cargo_codigo := c_tit;
  RETURN NEW;
END $$;

CREATE TRIGGER trg_interinato_entre_pares
  BEFORE INSERT OR UPDATE OF titular_id, interino_id ON interinatos
  FOR EACH ROW EXECUTE FUNCTION interinato_entre_pares();

-- ── Auditoría ──────────────────────────────────────────────────────────
CREATE TABLE auditoria (
  id                       BIGSERIAL PRIMARY KEY,
  tabla                    TEXT NOT NULL,
  registro_id              INT  NOT NULL,
  accion                   TEXT NOT NULL,              -- CREAR | MODIFICAR | ANULAR
  datos                    JSONB NOT NULL,
  advertencias_confirmadas JSONB,
  usuario_id               INT REFERENCES usuarios(id),
  ts                       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX auditoria_ts_idx ON auditoria (ts DESC);

CREATE TABLE version_esquema (
  version    INT PRIMARY KEY,
  aplicado_en TIMESTAMPTZ NOT NULL DEFAULT now()
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
