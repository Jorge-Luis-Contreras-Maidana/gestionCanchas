from decimal import Decimal, InvalidOperation

#: Estados que el administrador puede elegir a mano. "ocupada" NO está porque
#: se calcula solo: existe una reserva activa en este mismo momento.
ESTADOS_VALIDOS = {
    "disponible",
    "mantenimiento",
    "inactivo",
}

#: Alias aceptados por compatibilidad con datos viejos/formularios antiguos.
ESTADOS_ALIAS = {
    "fuera_servicio": "inactivo",
    "activo": "disponible",
}

#: El filtro del listado también acepta "ocupada" (estado calculado).
ESTADOS_FILTRO = ESTADOS_VALIDOS | {"ocupada"}

#: Fotos: límites y formatos reales admitidos (se valida la firma del archivo,
#: no la extension que mande el navegador).
MAX_IMAGENES_CANCHA = 8
MAX_IMAGEN_BYTES = 4 * 1024 * 1024  # 4 MB por imagen
MIME_IMAGENES = ("image/jpeg", "image/png", "image/webp")


def convertir_precio(valor):
    if valor is None or valor == "":
        raise ValueError("El precio_hora es obligatorio.")

    try:
        precio = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        raise ValueError("precio_hora debe ser un número válido.")

    if not precio.is_finite():
        raise ValueError("precio_hora debe ser un número finito.")

    if precio <= 0:
        raise ValueError("precio_hora debe ser mayor que 0.")

    return precio


def convertir_id_entero(valor, nombre):
    if valor is None or valor == "":
        raise ValueError(f"{nombre} es obligatorio.")

    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"{nombre} debe ser un número entero.")

    if valor <= 0:
        raise ValueError(f"{nombre} debe ser mayor que 0.")

    return valor


def convertir_hora(valor, nombre="horario"):
    """Convierte 'HH:MM' a datetime.time. Acepta datetime.time sin cambios."""
    from datetime import time as _time

    if valor is None or valor == "":
        return None
    if isinstance(valor, _time):
        return valor
    if not isinstance(valor, str):
        raise ValueError(f"{nombre} debe tener el formato HH:MM.")
    try:
        horas, minutos = valor.strip().split(":")
        h, m = int(horas), int(minutos)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return _time(h, m)
    except (ValueError, AttributeError):
        raise ValueError(f"{nombre} debe tener el formato HH:MM (ej. 06:00).")


def convertir_bool(valor, nombre="techada"):
    if isinstance(valor, bool):
        return valor

    if isinstance(valor, str):
        valor_limpio = valor.strip().lower()

        if valor_limpio in {"true", "1", "si", "sí"}:
            return True

        if valor_limpio in {"false", "0", "no"}:
            return False

    if isinstance(valor, int) and valor in (0, 1):
        return bool(valor)

    raise ValueError(f"{nombre} debe ser true o false.")


def validar_estado(estado):
    if not isinstance(estado, str):
        raise ValueError("El estado debe ser un texto válido.")

    estado = estado.strip().lower()
    estado = ESTADOS_ALIAS.get(estado, estado)

    if estado == "ocupada":
        raise ValueError(
            "'ocupada' no se puede asignar manualmente: se calcula automáticamente "
            "cuando la cancha tiene una reserva activa en este momento."
        )

    if estado not in ESTADOS_VALIDOS:
        raise ValueError(
            "Estado no válido. Use: disponible, mantenimiento o inactivo."
        )

    return estado


def validar_filtro_estado(estado):
    """Filtro del listado: además de los estados manuales acepta 'ocupada'."""
    if not isinstance(estado, str):
        raise ValueError("El estado debe ser un texto válido.")
    estado = estado.strip().lower()
    estado = ESTADOS_ALIAS.get(estado, estado)
    if estado not in ESTADOS_FILTRO:
        raise ValueError(
            "Filtro de estado no válido. Use: disponible, ocupada, "
            "mantenimiento o inactivo."
        )
    return estado


# ============================================================
# IMÁGENES
# ============================================================
def _detectar_mime_imagen(primeros_bytes):
    """Devuelve el MIME real del archivo según su firma binaria."""
    if primeros_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if primeros_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if primeros_bytes.startswith(b"RIFF") and primeros_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


def validar_archivo_imagen(archivo):
    """Lee y valida una foto subida. Devuelve (bytes, mime, nombre_original)."""
    if archivo is None or not getattr(archivo, "filename", ""):
        raise ValueError("Una de las imágenes enviada está vacía.")

    datos = archivo.read()
    if not datos:
        raise ValueError(f"El archivo '{archivo.filename}' está vacío.")
    if len(datos) > MAX_IMAGEN_BYTES:
        raise ValueError(
            f"'{archivo.filename}' supera el máximo de "
            f"{MAX_IMAGEN_BYTES // (1024 * 1024)} MB."
        )

    mime = _detectar_mime_imagen(datos[:16])
    if not mime:
        raise ValueError(
            f"'{archivo.filename}' no es una imagen válida. "
            "Formatos admitidos: JPG, PNG o WEBP."
        )

    return datos, mime, archivo.filename.strip()[:150]


def validar_datos_cancha(data, parcial=False):
    """
    Valida y limpia los campos de texto simples de una cancha
    (nombre_cancha, tipo_deporte, ubicacion, superficie).

    Los campos numéricos/relacionales (precio_hora, id_categoria,
    id_administrador, estado, techada) se validan aparte con las
    funciones de arriba, porque el service necesita consultarlos
    contra la base de datos antes de aceptarlos.
    """
    if not isinstance(data, dict):
        raise ValueError("El cuerpo de la solicitud debe ser un objeto JSON válido.")

    if not data:
        raise ValueError("El cuerpo de la solicitud no puede estar vacío.")

    resultado = {}

    if not parcial or "nombre_cancha" in data:
        nombre = data.get("nombre_cancha")
        if not isinstance(nombre, str):
            raise ValueError("nombre_cancha debe ser texto válido.")
        nombre = nombre.strip()
        if not nombre:
            raise ValueError("nombre_cancha es obligatorio.")
        if len(nombre) > 80:
            raise ValueError("El nombre de la cancha no puede superar 80 caracteres.")
        resultado["nombre_cancha"] = nombre

    if not parcial or "tipo_deporte" in data:
        deporte = data.get("tipo_deporte")
        if not isinstance(deporte, str):
            raise ValueError("tipo_deporte debe ser texto válido.")
        deporte = deporte.strip()
        if not deporte:
            raise ValueError("tipo_deporte es obligatorio.")
        if len(deporte) > 50:
            raise ValueError("El tipo de deporte no puede superar 50 caracteres.")
        resultado["tipo_deporte"] = deporte

    if "ubicacion" in data:
        ubicacion = data.get("ubicacion")
        if ubicacion is not None and not isinstance(ubicacion, str):
            raise ValueError("La ubicación debe ser un texto válido o null.")
        if ubicacion is not None and len(ubicacion.strip()) > 150:
            raise ValueError("La ubicación no puede superar 150 caracteres.")
        resultado["ubicacion"] = (
            ubicacion.strip() if ubicacion and ubicacion.strip() else None
        )

    if "superficie" in data:
        superficie = data.get("superficie")
        if superficie is not None and not isinstance(superficie, str):
            raise ValueError("La superficie debe ser un texto válido o null.")
        if superficie is not None and len(superficie.strip()) > 50:
            raise ValueError("La superficie no puede superar 50 caracteres.")
        resultado["superficie"] = (
            superficie.strip() if superficie and superficie.strip() else None
        )

    return resultado
