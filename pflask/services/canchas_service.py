from datetime import datetime

from extensions import db
from models.administrador import Administrador
from models.cancha import Cancha
from models.cancha_imagen import CanchaImagen
from models.categoria import Categoria
from models.evento import Evento
from models.historial_estado_cancha import HistorialEstadoCancha
from models.historial_precio_cancha import HistorialPrecioCancha
from models.reserva import Reserva
from services.tarifas_service import (
    HORA_APERTURA_UI,
    HORA_CIERRE_UI,
    dias_cerrados_por_cancha,
    horario_general,
    nombres_dias,
)
from validators.cancha_validator import (
    MAX_IMAGENES_CANCHA,
    convertir_precio,
    convertir_id_entero,
    convertir_bool,
    convertir_hora,
    validar_estado,
    validar_filtro_estado,
    validar_archivo_imagen,
)

ESTADOS_VALIDOS = ("disponible", "mantenimiento", "inactivo")

#: Reserva pendiente/confirmada que está en juego ahora mismo = cancha OCUPADA.
ESTADOS_RESERVA_ACTIVOS = ("pendiente", "confirmada")


def obtener_categoria(id_categoria):
    categoria = db.session.get(Categoria, id_categoria)
    if not categoria:
        raise ValueError("La categoría indicada no existe.")
    return categoria


def deporte_de_categoria(nombre_categoria):
    """Deporte de una cancha a partir del nombre de su categoría.

    La categoría es la única fuente de verdad del deporte: asi no se puede
    registrar una cancha con "Futbol" como deporte y "Voley" como categoría.
    El tamaño se separa del nombre ("Fútbol 11" -> "Fútbol") para que el
    filtro por deporte agrupe las canchas de la misma disciplina.
    """
    if not nombre_categoria:
        return "Deporte"
    partes = str(nombre_categoria).strip().split()
    if len(partes) > 1 and partes[-1].isdigit():
        partes = partes[:-1]
    return " ".join(partes).strip() or str(nombre_categoria).strip()


def obtener_administrador(id_administrador):
    administrador = db.session.get(Administrador, id_administrador)
    if not administrador:
        raise ValueError("El administrador indicado no existe.")
    return administrador


def administrador_del_usuario(id_usuario):
    """Perfil de administrador del usuario autenticado."""
    administrador = Administrador.query.filter_by(id_usuario=id_usuario).first()
    if not administrador:
        raise ValueError(
            "El usuario autenticado no tiene perfil de administrador; "
            "no se puede asignar la cancha."
        )
    return administrador


# ============================================================
# ESTADO CALCULADO (disponible / ocupada / mantenimiento / inactivo)
# ============================================================
def ids_canchas_ocupadas_ahora():
    """Ids de las canchas con una reserva activa en este mismo momento."""
    ahora = datetime.now()
    filas = (
        db.session.query(Reserva.id_cancha)
        .filter(
            Reserva.estado_reserva.in_(ESTADOS_RESERVA_ACTIVOS),
            Reserva.fecha_reserva == ahora.date(),
            Reserva.hora_inicio <= ahora.time(),
            Reserva.hora_fin > ahora.time(),
        )
        .distinct()
        .all()
    )
    return {f[0] for f in filas}


def estado_calculado(cancha, ocupadas=None):
    """
    Estado real que ve el usuario:
    - inactivo / mantenimiento: el que eligió el administrador.
    - ocupada: estaba disponible pero hay una reserva activa AHORA.
    - disponible: lista para reservar.
    """
    if cancha.estado != "disponible":
        return cancha.estado
    if ocupadas is None:
        ocupadas = ids_canchas_ocupadas_ahora()
    return "ocupada" if cancha.id_cancha in ocupadas else "disponible"


def serializar(cancha, ocupadas=None, dias_cerrados=None):
    """to_dict de la cancha + estado calculado e info de la galería."""
    if ocupadas is None:
        ocupadas = ids_canchas_ocupadas_ahora()
    datos = cancha.to_dict()
    calculado = estado_calculado(cancha, ocupadas)
    datos["estado_calculado"] = calculado
    datos["reserva_habilitada"] = calculado == "disponible"
    datos["total_imagenes"] = len(cancha.imagenes)
    primera = cancha.imagenes[0] if cancha.imagenes else None
    datos["imagen_preview_id"] = primera.id_imagen if primera else None

    # Días de atención: el cliente los ve en la ficha de la cancha.
    cerrados = list(dias_cerrados or [])
    datos["dias_cerrados"] = nombres_dias(cerrados)
    datos["dias_habiles"] = nombres_dias(
        d for d in range(7) if d not in cerrados
    )
    return datos


# ============================================================
# LISTADO CON FILTROS
# ============================================================
def _orden_por(nombre_orden):
    ordenes = {
        "nombre_asc": Cancha.nombre_cancha.asc(),
        "nombre_desc": Cancha.nombre_cancha.desc(),
        "precio_asc": Cancha.precio_hora.asc(),
        "precio_desc": Cancha.precio_hora.desc(),
        "recientes": Cancha.id_cancha.desc(),
    }
    return ordenes.get(nombre_orden, ordenes["nombre_asc"])


def listar_canchas(estado=None, q=None, deporte=None, orden=None, solo_visibles=False):
    """
    Listado con filtros combinables:
    - q: busca por nombre, deporte o ubicación (parcial, sin distinción de mayúsculas).
    - deporte: nombre del deporte (parcial).
    - estado: disponible | ocupada (calculado) | mantenimiento | inactivo.
    - orden: nombre_asc | nombre_desc | precio_asc | precio_desc | recientes.
    - solo_visibles: oculta las canchas inactivas (vista del cliente).
    """
    query = Cancha.query

    if solo_visibles:
        query = query.filter(Cancha.estado != "inactivo")

    if q and str(q).strip():
        like = f"%{str(q).strip()}%"
        query = query.filter(
            db.or_(
                Cancha.nombre_cancha.ilike(like),
                Cancha.tipo_deporte.ilike(like),
                Cancha.ubicacion.ilike(like),
            )
        )

    if deporte and str(deporte).strip():
        query = query.filter(Cancha.tipo_deporte.ilike(f"%{str(deporte).strip()}%"))

    if estado and str(estado).strip():
        estado = validar_filtro_estado(estado)
        if estado == "ocupada":
            ocupadas = ids_canchas_ocupadas_ahora()
            query = query.filter(
                Cancha.estado == "disponible",
                Cancha.id_cancha.in_(ocupadas) if ocupadas else db.false(),
            )
        else:
            query = query.filter(Cancha.estado == estado)

    return query.order_by(_orden_por(orden)).all()


def listar_canchas_serializado(ocupadas=None, **kwargs):
    canchas = listar_canchas(**kwargs)
    if ocupadas is None:
        ocupadas = ids_canchas_ocupadas_ahora()
    cerrados = dias_cerrados_por_cancha([c.id_cancha for c in canchas])
    return [
        serializar(c, ocupadas, cerrados.get(c.id_cancha, [])) for c in canchas
    ]


def obtener_cancha_por_id(id_cancha):
    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("La cancha no existe.")
    return cancha


def registrar_cambio_estado(cancha, nuevo_estado, motivo=None, id_usuario=None):
    anterior = cancha.estado
    if anterior == nuevo_estado:
        return
    db.session.add(
        HistorialEstadoCancha(
            id_cancha=cancha.id_cancha,
            estado_anterior=anterior,
            estado_nuevo=nuevo_estado,
            motivo=(motivo or "").strip()[:300] or None,
            id_usuario=id_usuario,
            fecha=datetime.now(),
        )
    )


def registrar_cambio_precio(cancha, nuevo_precio, id_usuario=None):
    anterior = float(cancha.precio_hora)
    nuevo = float(nuevo_precio)
    if anterior == nuevo:
        return
    db.session.add(
        HistorialPrecioCancha(
            id_cancha=cancha.id_cancha,
            precio_anterior=anterior,
            precio_nuevo=nuevo,
            id_usuario=id_usuario,
            fecha=datetime.now(),
        )
    )


def crear_cancha(datos_texto, datos_crudos, id_usuario=None):
    precio = convertir_precio(datos_crudos.get("precio_hora"))
    id_categoria = convertir_id_entero(datos_crudos.get("id_categoria"), "id_categoria")

    if id_usuario is not None:
        administrador = administrador_del_usuario(id_usuario)
        id_administrador = administrador.id_administrador
    else:
        id_administrador = convertir_id_entero(
            datos_crudos.get("id_administrador"), "id_administrador"
        )
        obtener_administrador(id_administrador)

    obtener_categoria(id_categoria)

    # Estado inicial por defecto DISPONIBLE; se puede crear ya en mantenimiento.
    estado = validar_estado(datos_crudos.get("estado") or "disponible")
    techada = convertir_bool(datos_crudos.get("techada", False))

    # El deporte sale de la categoría: es el único campo que define el tipo
    # de cancha y así no pueden contradecirse.
    categoria = obtener_categoria(id_categoria)
    tipo_deporte = (
        (datos_texto.get("tipo_deporte") or "").strip()
        or deporte_de_categoria(categoria.nombre)
    )

    nueva = Cancha(
        nombre_cancha=datos_texto["nombre_cancha"],
        tipo_deporte=tipo_deporte,
        precio_hora=precio,
        ubicacion=datos_texto.get("ubicacion"),
        estado=estado,
        techada=techada,
        superficie=datos_texto.get("superficie"),
        imagen_url=(datos_crudos.get("imagen_url") or None),
        # Horario general: sin el, la cancha no tendria slots reservables.
        horario_apertura=(
            convertir_hora(datos_crudos.get("horario_apertura"))
            or HORA_APERTURA_UI
        ),
        horario_cierre=(
            convertir_hora(datos_crudos.get("horario_cierre"))
            or HORA_CIERRE_UI
        ),
        dias_atencion=(datos_crudos.get("dias_atencion") or None),
        id_categoria=id_categoria,
        id_administrador=id_administrador,
    )
    db.session.add(nueva)
    db.session.commit()
    return nueva


def consultar_disponibilidad(id_cancha, fecha, duracion):
    """Slots libres de la cancha (import diferido para evitar ciclo)."""
    from services.reservas_service import consultar_disponibilidad as _consultar

    return _consultar(id_cancha, fecha, duracion)


def modificar_cancha(id_cancha, datos_texto, datos_crudos, id_usuario=None):
    cancha = obtener_cancha_por_id(id_cancha)

    for campo in ("nombre_cancha", "tipo_deporte", "ubicacion", "superficie"):
        if campo in datos_texto:
            setattr(cancha, campo, datos_texto[campo])

    if "precio_hora" in datos_crudos:
        nuevo_precio = convertir_precio(datos_crudos["precio_hora"])
        registrar_cambio_precio(cancha, nuevo_precio, id_usuario)
        cancha.precio_hora = nuevo_precio

    if "techada" in datos_crudos:
        cancha.techada = convertir_bool(datos_crudos["techada"])

    if "imagen_url" in datos_crudos:
        imagen = datos_crudos["imagen_url"]
        cancha.imagen_url = (imagen.strip() or None) if isinstance(imagen, str) else None

    # Horario general de la cancha: es el respaldo de los dias que no tienen
    # fila propia. Un valor vacio se ignora (no se borra el horario) para que
    # un formulario vacio no deje la cancha sin slots reservables.
    if datos_crudos.get("horario_apertura"):
        cancha.horario_apertura = convertir_hora(
            datos_crudos["horario_apertura"], "horario_apertura"
        )
    if datos_crudos.get("horario_cierre"):
        cancha.horario_cierre = convertir_hora(
            datos_crudos["horario_cierre"], "horario_cierre"
        )
    if "dias_atencion" in datos_crudos:
        dias = datos_crudos["dias_atencion"]
        cancha.dias_atencion = (dias.strip() or None) if isinstance(dias, str) else None

    if cancha.horario_apertura and cancha.horario_cierre:
        if cancha.horario_cierre <= cancha.horario_apertura:
            raise ValueError("El horario de cierre debe ser posterior al de apertura.")
    else:
        # Nunca dejar la cancha sin horario general: se usa el de atencion.
        apertura_general, cierre_general = horario_general(cancha)
        cancha.horario_apertura = apertura_general
        cancha.horario_cierre = cierre_general

    if "estado" in datos_crudos:
        nuevo_estado = validar_estado(datos_crudos["estado"])
        registrar_cambio_estado(
            cancha, nuevo_estado, datos_crudos.get("motivo"), id_usuario
        )
        cancha.estado = nuevo_estado

    if "id_categoria" in datos_crudos:
        id_categoria = convertir_id_entero(datos_crudos["id_categoria"], "id_categoria")
        categoria = obtener_categoria(id_categoria)
        cancha.id_categoria = id_categoria
        # La categoria manda sobre el deporte: si cambia, el deporte se
        # recalcula (salvo que se mande uno explicito).
        if "tipo_deporte" not in datos_texto:
            cancha.tipo_deporte = deporte_de_categoria(categoria.nombre)

    if "id_administrador" in datos_crudos:
        id_administrador = convertir_id_entero(
            datos_crudos["id_administrador"], "id_administrador"
        )
        obtener_administrador(id_administrador)
        cancha.id_administrador = id_administrador

    db.session.commit()
    return cancha


def eliminar_cancha(id_cancha, id_usuario=None):
    """
    Elimina la cancha. Igual que en Gestión de Reservas: si tiene reservas o
    eventos NO se borra (el historial debe quedar intacto), se desactiva
    ("inactivo") y se avisa al administrador.
    """
    cancha = obtener_cancha_por_id(id_cancha)

    reservas = Reserva.query.filter_by(id_cancha=id_cancha).count()
    eventos = Evento.query.filter_by(id_cancha=id_cancha).count()

    if reservas > 0 or eventos > 0:
        motivo = (
            f"Eliminación rechazada: {reservas} reserva(s) y {eventos} evento(s). "
            "Se desactiva."
        )
        if cancha.estado != "inactivo":
            registrar_cambio_estado(cancha, "inactivo", motivo, id_usuario)
            cancha.estado = "inactivo"
            db.session.commit()
        return {
            "mensaje": (
                "La cancha tiene reservas o eventos asociados. No se puede borrar; "
                "se desactivó (inactiva) para no afectar el historial."
            ),
            "desactivada": True,
            "reservas": reservas,
            "eventos": eventos,
        }

    db.session.delete(cancha)  # borra en cascada sus imágenes
    db.session.commit()
    return {"mensaje": "Cancha eliminada.", "desactivada": False}


def cambiar_estado_cancha(id_cancha, nuevo_estado, motivo=None, id_usuario=None):
    cancha = obtener_cancha_por_id(id_cancha)
    nuevo_estado = validar_estado(nuevo_estado)
    registrar_cambio_estado(cancha, nuevo_estado, motivo, id_usuario)
    cancha.estado = nuevo_estado
    db.session.commit()
    return cancha


# ============================================================
# GALERÍA DE IMÁGENES (se guardan en la base de datos)
# ============================================================
def listar_imagenes(id_cancha):
    cancha = obtener_cancha_por_id(id_cancha)
    return list(cancha.imagenes)


def obtener_imagen(id_cancha, id_imagen):
    imagen = CanchaImagen.query.filter_by(
        id_cancha=id_cancha, id_imagen=id_imagen
    ).first()
    if not imagen:
        raise ValueError("La imagen no existe.")
    return imagen


def agregar_imagenes(id_cancha, archivos):
    """
    Agrega fotos a la galería de la cancha. Valida que sean JPG/PNG/WEBP reales,
    de hasta 4 MB cada una, y que no se supere el máximo de fotos por cancha.
    """
    cancha = obtener_cancha_por_id(id_cancha)

    archivos = [f for f in (archivos or []) if f and getattr(f, "filename", "")]
    if not archivos:
        raise ValueError("Debes adjuntar al menos una imagen.")

    restantes = MAX_IMAGENES_CANCHA - len(cancha.imagenes)
    if restantes <= 0:
        raise ValueError(
            f"La cancha ya tiene el máximo de {MAX_IMAGENES_CANCHA} imágenes."
        )
    if len(archivos) > restantes:
        raise ValueError(
            f"Solo puedes agregar {restantes} imagen(es) más: la cancha ya tiene "
            f"{len(cancha.imagenes)} de {MAX_IMAGENES_CANCHA}."
        )

    orden = max((img.orden for img in cancha.imagenes), default=0)
    nuevas = []
    for archivo in archivos:
        datos, mime, nombre = validar_archivo_imagen(archivo)
        orden += 1
        imagen = CanchaImagen(
            id_cancha=cancha.id_cancha,
            orden=orden,
            mime_type=mime,
            nombre_archivo=nombre,
            tamano_bytes=len(datos),
            data=datos,
        )
        db.session.add(imagen)
        nuevas.append(imagen)

    db.session.commit()
    return nuevas


def eliminar_imagen(id_cancha, id_imagen):
    imagen = obtener_imagen(id_cancha, id_imagen)
    db.session.delete(imagen)
    db.session.commit()
    # Reordena para que la galería no quede con huecos.
    imagenes = listar_imagenes(id_cancha)
    for posicion, img in enumerate(imagenes, start=1):
        img.orden = posicion
    db.session.commit()
    return imagenes
