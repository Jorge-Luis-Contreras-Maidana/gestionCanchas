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

COMMIT;
