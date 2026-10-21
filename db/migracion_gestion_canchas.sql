-- ============================================================
-- MIGRACIÓN: Gestión de canchas
-- - Estados: disponible | mantenimiento | inactivo
--   ("ocupada" se calcula en el backend a partir de reservas activas)
-- - Tabla cancha_imagen: galería de fotos guardada en la base de datos
-- Ejecutar sobre la base proyectoCanchas (psql -f ...)
-- ============================================================

BEGIN;

-- 1) Nuevos estados de cancha ----------------------------------
ALTER TABLE public.cancha DROP CONSTRAINT IF EXISTS chk_cancha_estado;

-- El viejo "fuera_servicio" pasa a ser "inactivo".
UPDATE public.cancha SET estado = 'inactivo' WHERE estado = 'fuera_servicio';

ALTER TABLE public.cancha
    ADD CONSTRAINT chk_cancha_estado CHECK (
        (estado)::text = ANY (
            (ARRAY['disponible'::character varying,
                   'mantenimiento'::character varying,
                   'inactivo'::character varying])::text[]
        )
    );

-- 2) Galería de fotos en la BD ---------------------------------
CREATE TABLE IF NOT EXISTS public.cancha_imagen (
    id_imagen     integer NOT NULL,
    id_cancha     integer NOT NULL,
    orden         integer DEFAULT 1 NOT NULL,
    mime_type     character varying(20) NOT NULL,
    nombre_archivo character varying(150),
    tamano_bytes  integer NOT NULL,
    data          bytea NOT NULL,
    fecha_subida  timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT cancha_imagen_pkey PRIMARY KEY (id_imagen),
    CONSTRAINT cancha_imagen_orden_check CHECK (orden > 0),
    CONSTRAINT cancha_imagen_id_cancha_fkey FOREIGN KEY (id_cancha)
        REFERENCES public.cancha (id_cancha)
        ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE SEQUENCE IF NOT EXISTS public.cancha_imagen_id_imagen_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

ALTER SEQUENCE public.cancha_imagen_id_imagen_seq OWNED BY public.cancha_imagen.id_imagen;

ALTER TABLE ONLY public.cancha_imagen
    ALTER COLUMN id_imagen SET DEFAULT nextval('public.cancha_imagen_id_imagen_seq'::regclass);

CREATE INDEX IF NOT EXISTS ix_cancha_imagen_id_cancha
    ON public.cancha_imagen (id_cancha);

-- 3) Bitácoras de cambios de estado y de precio ----------------
-- (los modelos ya las usaban pero nunca se crearon en la BD:
--  todo cambio de estado o de precio terminaba en error 500)
CREATE TABLE IF NOT EXISTS public.historial_estado_cancha (
    id_historial    integer NOT NULL,
    id_cancha       integer NOT NULL,
    estado_anterior character varying(20) NOT NULL,
    estado_nuevo    character varying(20) NOT NULL,
    motivo          character varying(300),
    id_usuario      integer,
    fecha           timestamp without time zone NOT NULL,
    CONSTRAINT historial_estado_cancha_pkey PRIMARY KEY (id_historial),
    CONSTRAINT historial_estado_cancha_id_cancha_fkey FOREIGN KEY (id_cancha)
        REFERENCES public.cancha (id_cancha)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT historial_estado_cancha_id_usuario_fkey FOREIGN KEY (id_usuario)
        REFERENCES public.usuario (id_usuario)
        ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE SEQUENCE IF NOT EXISTS public.historial_estado_cancha_id_historial_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

ALTER SEQUENCE public.historial_estado_cancha_id_historial_seq
    OWNED BY public.historial_estado_cancha.id_historial;

ALTER TABLE ONLY public.historial_estado_cancha
    ALTER COLUMN id_historial SET DEFAULT
        nextval('public.historial_estado_cancha_id_historial_seq'::regclass);

CREATE TABLE IF NOT EXISTS public.historial_precio_cancha (
    id_historial    integer NOT NULL,
    id_cancha       integer NOT NULL,
    precio_anterior numeric(10,2) NOT NULL,
    precio_nuevo    numeric(10,2) NOT NULL,
    id_usuario      integer,
    fecha           timestamp without time zone NOT NULL,
    CONSTRAINT historial_precio_cancha_pkey PRIMARY KEY (id_historial),
    CONSTRAINT historial_precio_cancha_id_cancha_fkey FOREIGN KEY (id_cancha)
        REFERENCES public.cancha (id_cancha)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT historial_precio_cancha_id_usuario_fkey FOREIGN KEY (id_usuario)
        REFERENCES public.usuario (id_usuario)
        ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE SEQUENCE IF NOT EXISTS public.historial_precio_cancha_id_historial_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

ALTER SEQUENCE public.historial_precio_cancha_id_historial_seq
    OWNED BY public.historial_precio_cancha.id_historial;

ALTER TABLE ONLY public.historial_precio_cancha
    ALTER COLUMN id_historial SET DEFAULT
        nextval('public.historial_precio_cancha_id_historial_seq'::regclass);

-- 4) Columnas de reserva que el modelo ya usaba pero faltaban en la BD
-- (sin ellas, contar/borrar canchas y el flujo de pagos daban error 500)
ALTER TABLE public.reserva ADD COLUMN IF NOT EXISTS monto_total numeric(10,2);
ALTER TABLE public.reserva ADD COLUMN IF NOT EXISTS expira_en timestamp without time zone;
ALTER TABLE public.reserva ADD COLUMN IF NOT EXISTS canal_origen character varying(20) DEFAULT 'web' NOT NULL;

-- 5) Tarifas por franja y horarios por día (los modelos ya los usaban)
CREATE TABLE IF NOT EXISTS public.tarifa_cancha (
    id_tarifa    integer NOT NULL,
    id_cancha    integer NOT NULL,
    tipo_tarifa  character varying(20) NOT NULL,
    dia_semana    smallint,
    hora_inicio  time without time zone NOT NULL,
    hora_fin     time without time zone NOT NULL,
    precio_hora  numeric(10,2) NOT NULL,
    activo       boolean DEFAULT true NOT NULL,
    id_usuario   integer,
    fecha        timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT tarifa_cancha_pkey PRIMARY KEY (id_tarifa),
    CONSTRAINT tarifa_cancha_id_cancha_fkey FOREIGN KEY (id_cancha)
        REFERENCES public.cancha (id_cancha)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT tarifa_cancha_id_usuario_fkey FOREIGN KEY (id_usuario)
        REFERENCES public.usuario (id_usuario)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_tarifa_horas CHECK (hora_fin > hora_inicio),
    CONSTRAINT chk_tarifa_precio CHECK (precio_hora > 0)
);

CREATE SEQUENCE IF NOT EXISTS public.tarifa_cancha_id_tarifa_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.tarifa_cancha_id_tarifa_seq
    OWNED BY public.tarifa_cancha.id_tarifa;
ALTER TABLE ONLY public.tarifa_cancha
    ALTER COLUMN id_tarifa SET DEFAULT nextval('public.tarifa_cancha_id_tarifa_seq'::regclass);

CREATE TABLE IF NOT EXISTS public.horario_cancha (
    id_horario     integer NOT NULL,
    id_cancha      integer NOT NULL,
    dia_semana     smallint NOT NULL,
    hora_apertura  time without time zone NOT NULL,
    hora_cierre    time without time zone NOT NULL,
    activo         boolean DEFAULT true NOT NULL,
    CONSTRAINT horario_cancha_pkey PRIMARY KEY (id_horario),
    CONSTRAINT horario_cancha_id_cancha_fkey FOREIGN KEY (id_cancha)
        REFERENCES public.cancha (id_cancha)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_horario_cancha_horas CHECK (hora_cierre > hora_apertura),
    CONSTRAINT uq_horario_cancha_dia UNIQUE (id_cancha, dia_semana)
);

CREATE SEQUENCE IF NOT EXISTS public.horario_cancha_id_horario_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.horario_cancha_id_horario_seq
    OWNED BY public.horario_cancha.id_horario;
ALTER TABLE ONLY public.horario_cancha
    ALTER COLUMN id_horario SET DEFAULT nextval('public.horario_cancha_id_horario_seq'::regclass);

CREATE TABLE IF NOT EXISTS public.historial_tarifa_cancha (
    id_historial     integer NOT NULL,
    id_tarifa        integer,
    id_cancha        integer NOT NULL,
    tipo_anterior    character varying(20),
    tipo_nuevo       character varying(20),
    dia_anterior     smallint,
    dia_nuevo        smallint,
    precio_anterior  numeric(10,2),
    precio_nuevo     numeric(10,2),
    motivo           text,
    id_usuario       integer,
    fecha            timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT historial_tarifa_cancha_pkey PRIMARY KEY (id_historial),
    CONSTRAINT historial_tarifa_cancha_id_cancha_fkey FOREIGN KEY (id_cancha)
        REFERENCES public.cancha (id_cancha)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT historial_tarifa_cancha_id_usuario_fkey FOREIGN KEY (id_usuario)
        REFERENCES public.usuario (id_usuario)
        ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE SEQUENCE IF NOT EXISTS public.historial_tarifa_cancha_id_historial_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.historial_tarifa_cancha_id_historial_seq
    OWNED BY public.historial_tarifa_cancha.id_historial;
ALTER TABLE ONLY public.historial_tarifa_cancha
    ALTER COLUMN id_historial SET DEFAULT
        nextval('public.historial_tarifa_cancha_id_historial_seq'::regclass);

-- 6) Horario general de las canchas --------------------------------
-- Sin horario_apertura/horario_cierre la cancha no tiene ningun slot
-- reservable ("La cancha no opera ese dia") y el administrador ve la
-- pantalla de horarios por dia con los campos vacios y deshabilitados.
UPDATE public.cancha
   SET horario_apertura = '06:00',
       horario_cierre   = '23:00'
 WHERE horario_apertura IS NULL
    OR horario_cierre   IS NULL;

-- 7) Fecha de creación de la reserva ---------------------------------
-- La columna es NOT NULL: si el INSERT llega sin valor (porque el modelo
-- no lo envía) la creación de reservas falla con error 500.
ALTER TABLE public.reserva
    ALTER COLUMN fecha_creacion SET DEFAULT CURRENT_TIMESTAMP;

-- 8) Historial de reservas: el modelo usa "tipo_cambio" ---------------
-- La tabla se había creado con la columna "accion": al insertar el
-- historial (creación, cancelación, pago) la BD rechazaba la columna.
ALTER TABLE public.historial_reserva
    ADD COLUMN IF NOT EXISTS tipo_cambio character varying(30);

UPDATE public.historial_reserva
   SET tipo_cambio = accion
 WHERE tipo_cambio IS NULL
   AND accion IS NOT NULL;

ALTER TABLE public.historial_reserva
    ALTER COLUMN tipo_cambio SET NOT NULL;

-- La columna vieja "accion" ya no la usa nadie: se copia y se elimina.
ALTER TABLE public.historial_reserva
    DROP COLUMN IF EXISTS accion;

-- 9) Tablas que quedaron con la estructura anterior -------------------
-- Los modelos se reescribieron (pagos, devoluciones, caja, reportes,
-- notificaciones y analítica) pero estas tablas seguian con el esquema
-- viejo: cualquier INSERT de esos modulos fallaba y abortaba la
-- transaccion (por eso "crear reserva" devolvia 500).
-- Todas estaban vacias, asi que se recrean con la estructura del modelo.
DROP TABLE IF EXISTS public.pago_auditoria;
CREATE TABLE public.pago_auditoria (
    id_auditoria SERIAL NOT NULL,
    id_pago INTEGER NOT NULL,
    id_usuario INTEGER,
    resultado VARCHAR(20) NOT NULL,
    monto_comprobante NUMERIC(10, 2),
    fecha_comprobante DATE,
    metodo_comprobante VARCHAR(50),
    referencia_comprobante VARCHAR(100),
    observaciones TEXT,
    fecha TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id_auditoria),
    FOREIGN KEY (id_pago) REFERENCES public.pago (id_pago) ON DELETE CASCADE,
    FOREIGN KEY (id_usuario) REFERENCES public.usuario (id_usuario) ON DELETE SET NULL
);

DROP TABLE IF EXISTS public.devolucion_solicitud;
CREATE TABLE public.devolucion_solicitud (
    id_solicitud SERIAL NOT NULL,
    id_pago INTEGER NOT NULL,
    id_cliente INTEGER,
    id_usuario_solicitante INTEGER,
    id_usuario_decision INTEGER,
    monto NUMERIC(10, 2) NOT NULL,
    motivo TEXT NOT NULL,
    estado VARCHAR(20) NOT NULL,
    motivo_decision TEXT,
    monto_devuelto NUMERIC(10, 2),
    fecha_devolucion TIMESTAMP WITHOUT TIME ZONE,
    fecha_solicitud TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    fecha_decision TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id_solicitud),
    FOREIGN KEY (id_pago) REFERENCES public.pago (id_pago) ON DELETE CASCADE,
    FOREIGN KEY (id_cliente) REFERENCES public.cliente (id_cliente) ON DELETE SET NULL,
    FOREIGN KEY (id_usuario_solicitante) REFERENCES public.usuario (id_usuario) ON DELETE SET NULL,
    FOREIGN KEY (id_usuario_decision) REFERENCES public.usuario (id_usuario) ON DELETE SET NULL
);

DROP TABLE IF EXISTS public.turno_caja;
CREATE TABLE public.turno_caja (
    id_turno SERIAL NOT NULL,
    id_empleado INTEGER NOT NULL,
    id_usuario_cierre INTEGER,
    fecha DATE NOT NULL,
    hora_apertura TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    hora_cierre TIMESTAMP WITHOUT TIME ZONE,
    monto_esperado_efectivo NUMERIC(12, 2) NOT NULL,
    monto_fisico NUMERIC(12, 2),
    diferencia NUMERIC(12, 2),
    total_qr NUMERIC(12, 2) NOT NULL,
    total_transferencia NUMERIC(12, 2) NOT NULL,
    total_tarjeta NUMERIC(12, 2) NOT NULL,
    cantidad_pagos INTEGER NOT NULL,
    cantidad_devoluciones INTEGER NOT NULL,
    estado VARCHAR(20) NOT NULL,
    observaciones TEXT,
    PRIMARY KEY (id_turno),
    FOREIGN KEY (id_empleado) REFERENCES public.empleado (id_empleado) ON DELETE RESTRICT,
    FOREIGN KEY (id_usuario_cierre) REFERENCES public.usuario (id_usuario) ON DELETE SET NULL
);

DROP TABLE IF EXISTS public.reporte;
CREATE TABLE public.reporte (
    id_reporte SERIAL NOT NULL,
    tipo VARCHAR(30) NOT NULL,
    fecha_generado DATE NOT NULL,
    descripcion TEXT,
    id_administrador INTEGER NOT NULL,
    PRIMARY KEY (id_reporte),
    FOREIGN KEY (id_administrador) REFERENCES public.administrador (id_administrador)
);

-- La notificacion apunta a la plantilla: se suelta la llave antes de
-- recrear la tabla y se vuelve a poner despues.
ALTER TABLE public.notificacion
    DROP CONSTRAINT IF EXISTS notificacion_id_plantilla_fkey;

DROP TABLE IF EXISTS public.plantilla_notificacion;
CREATE TABLE public.plantilla_notificacion (    id_plantilla SERIAL NOT NULL,
    codigo VARCHAR(40) NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    tipo_evento VARCHAR(40) NOT NULL,
    canal VARCHAR(20) NOT NULL,
    asunto VARCHAR(200) NOT NULL,
    cuerpo TEXT NOT NULL,
    activa BOOLEAN NOT NULL,
    id_administrador INTEGER,
    fecha_creacion TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id_plantilla),
    UNIQUE (codigo),
    FOREIGN KEY (id_administrador) REFERENCES public.administrador (id_administrador)
        ON DELETE SET NULL ON UPDATE CASCADE
);

ALTER TABLE public.notificacion
    ADD CONSTRAINT notificacion_id_plantilla_fkey
    FOREIGN KEY (id_plantilla) REFERENCES public.plantilla_notificacion (id_plantilla)
        ON DELETE SET NULL ON UPDATE CASCADE;

DROP TABLE IF EXISTS public.notificacion_intento;
CREATE TABLE public.notificacion_intento (
    id_intento SERIAL NOT NULL,
    id_notificacion INTEGER NOT NULL,
    numero_intento INTEGER NOT NULL,
    canal VARCHAR(20) NOT NULL,
    estado VARCHAR(20) NOT NULL,
    detalle TEXT,
    fecha TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id_intento),
    FOREIGN KEY (id_notificacion) REFERENCES public.notificacion (id_notificacion)
        ON DELETE CASCADE ON UPDATE CASCADE
);

DROP TABLE IF EXISTS public.analisis_generado;
CREATE TABLE public.analisis_generado (
    id_analisis SERIAL NOT NULL,
    tipo_analisis VARCHAR(30) NOT NULL,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    parametros JSON NOT NULL,
    resultado JSON,
    metricas JSON,
    total_registros INTEGER NOT NULL,
    fecha_generado TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    id_administrador INTEGER NOT NULL,
    PRIMARY KEY (id_analisis),
    FOREIGN KEY (id_administrador) REFERENCES public.administrador (id_administrador) ON DELETE CASCADE
);

-- 10) El tipo de deporte sale de la categoría ---------------------------
-- Se normalizan las canchas que ya estaban cargadas con un deporte y una
-- categoría que no coincidían (p.ej. "Fútbol" con categoría "Vóley").
UPDATE public.cancha c
   SET tipo_deporte = COALESCE(
           NULLIF(btrim(regexp_replace(cat.nombre, '[0-9]+$', '')), ''),
           cat.nombre
       )
  FROM public.categoria cat
 WHERE cat.id_categoria = c.id_categoria;

COMMIT;
