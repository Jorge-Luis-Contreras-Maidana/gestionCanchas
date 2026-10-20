from io import BytesIO

from flask import Blueprint, g, jsonify, request, send_file
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import cancha_imagen  # noqa: F401  (registra el mapeo CanchaImagen)
from services import canchas_service
from services.auth_service import _extract_bearer_token, decode_token, require_auth
from utils.responses import error_json
from validators.cancha_validator import validar_datos_cancha

canchas_bp = Blueprint("canchas", __name__, url_prefix="/api/canchas")


@canchas_bp.post("")
@require_auth(roles=["administrador"])
def crear_cancha():
    data = request.get_json(silent=True)

    try:
        datos_texto = validar_datos_cancha(data)
        cancha = canchas_service.crear_cancha(
            datos_texto, data, id_usuario=getattr(g, "current_user", None).id_usuario
        )

        return jsonify({
            "mensaje": "Cancha registrada con éxito.",
            "cancha": canchas_service.serializar(cancha),
        }), 201

    except ValueError as e:
        db.session.rollback()
        return error_json("Datos inválidos.", str(e))

    except IntegrityError as e:
        db.session.rollback()
        return error_json("No se pudo registrar la cancha.", str(e.orig), 409)

    except Exception as e:
        db.session.rollback()
        return error_json("Error interno al registrar la cancha.", str(e), 500)


def _rol_de_token():
    token = _extract_bearer_token()
    if not token:
        return None
    try:
        payload = decode_token(token, expected_type="access")
        return payload.get("rol")
    except Exception:
        return None


@canchas_bp.get("")
def obtener_canchas():
    """
    Listado con filtros combinables:
    ?q= (nombre/deporte/ubicación) &deporte= &estado= &orden=

    Empleado y administrador ven todo (incluidas inactivas). El cliente ve
    todas las canchas activas: disponibles, ocupadas y en mantenimiento, para
    que el estado se refleje en su vista; reserva_habilitada indica si puede
    reservar.
    """
    try:
        rol = _rol_de_token()
        es_staff = rol in ("empleado", "administrador")

        canchas = canchas_service.listar_canchas_serializado(
            estado=request.args.get("estado"),
            q=request.args.get("q"),
            deporte=request.args.get("deporte"),
            orden=request.args.get("orden"),
            solo_visibles=not es_staff,
        )
        return jsonify(canchas), 200
    except ValueError as e:
        return error_json(str(e))
    except Exception as e:
        return error_json("Error interno al obtener canchas.", str(e), 500)


@canchas_bp.get("/<int:id_cancha>")
def obtener_cancha(id_cancha):
    if id_cancha <= 0:
        return error_json("El id_cancha debe ser mayor que 0.")

    try:
        cancha = canchas_service.obtener_cancha_por_id(id_cancha)
        return jsonify(canchas_service.serializar(cancha)), 200
    except ValueError as e:
        return error_json(str(e), codigo=404)


# ============================================================
# GALERÍA DE IMÁGENES (se guardan en la base de datos)
# ============================================================
@canchas_bp.get("/<int:id_cancha>/imagenes/<int:id_imagen>")
def servir_imagen(id_cancha, id_imagen):
    """Entrega los bytes de la foto. Pública: la usa el <img> del navegador."""
    try:
        imagen = canchas_service.obtener_imagen(id_cancha, id_imagen)
        return send_file(
            BytesIO(imagen.data),
            mimetype=imagen.mime_type,
            download_name=imagen.nombre_archivo or "cancha",
            max_age=3600,
            conditional=True,
        )
    except ValueError as e:
        return error_json(str(e), codigo=404)
    except Exception as e:
        return error_json("No se pudo cargar la imagen.", str(e), 500)


@canchas_bp.get("/<int:id_cancha>/imagenes")
def listar_imagenes(id_cancha):
    try:
        imagenes = canchas_service.listar_imagenes(id_cancha)
        return jsonify([i.to_dict() for i in imagenes]), 200
    except ValueError as e:
        return error_json(str(e), codigo=404)
    except Exception as e:
        return error_json("No se pudieron listar las imágenes.", str(e), 500)


@canchas_bp.post("/<int:id_cancha>/imagenes")
@require_auth(roles=["administrador"])
def agregar_imagenes(id_cancha):
    """Recibe multipart con el campo 'imagenes' (una o varias fotos)."""
    try:
        archivos = request.files.getlist("imagenes")
        imagenes = canchas_service.agregar_imagenes(id_cancha, archivos)
        return jsonify({
            "mensaje": f"{len(imagenes)} imagen(es) guardada(s) en la base de datos.",
            "imagenes": [i.to_dict() for i in imagenes],
        }), 201
    except ValueError as e:
        db.session.rollback()
        codigo = 404 if "no existe" in str(e).lower() else 400
        return error_json("No se pudo guardar la imagen.", str(e), codigo)
    except Exception as e:
        db.session.rollback()
        return error_json("Error interno al guardar la imagen.", str(e), 500)


@canchas_bp.delete("/<int:id_cancha>/imagenes/<int:id_imagen>")
@require_auth(roles=["administrador"])
def eliminar_imagen(id_cancha, id_imagen):
    try:
        imagenes = canchas_service.eliminar_imagen(id_cancha, id_imagen)
        return jsonify({
            "mensaje": "Imagen eliminada.",
            "imagenes": [i.to_dict() for i in imagenes],
        }), 200
    except ValueError as e:
        db.session.rollback()
        codigo = 404 if "no existe" in str(e).lower() else 400
        return error_json("No se pudo eliminar la imagen.", str(e), codigo)
    except Exception as e:
        db.session.rollback()
        return error_json("Error interno al eliminar la imagen.", str(e), 500)


# ============================================================
@canchas_bp.get("/<int:id_cancha>/disponibilidad")
def obtener_disponibilidad(id_cancha):
    """Slots libres de una cancha en una fecha, con la duración pedida."""
    fecha = request.args.get("fecha")
    duracion = request.args.get("duracion", 1)
    try:
        if not fecha:
            return error_json("El parámetro 'fecha' es obligatorio.")
        return jsonify(
            canchas_service.consultar_disponibilidad(id_cancha, fecha, duracion)
        ), 200
    except ValueError as e:
        return error_json(str(e), codigo=400)
    except Exception as e:
        return error_json("Error interno al obtener disponibilidad.", str(e), 500)


@canchas_bp.patch("/<int:id_cancha>")
@require_auth(roles=["administrador"])
def modificar_cancha(id_cancha):
    if id_cancha <= 0:
        return error_json("El id_cancha debe ser mayor que 0.")

    data = request.get_json(silent=True)

    try:
        datos_texto = validar_datos_cancha(data, parcial=True)
        cancha = canchas_service.modificar_cancha(
            id_cancha, datos_texto, data, id_usuario=getattr(g, "current_user", None).id_usuario
        )

        return jsonify({
            "mensaje": "Cancha modificada con éxito.",
            "cancha": canchas_service.serializar(cancha),
        }), 200

    except ValueError as e:
        db.session.rollback()
        mensaje = str(e)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        return error_json(mensaje, codigo=codigo)

    except IntegrityError as e:
        db.session.rollback()
        return error_json("No se pudo modificar la cancha.", str(e.orig), 409)

    except Exception as e:
        db.session.rollback()
        return error_json("Error interno al modificar la cancha.", str(e), 500)


@canchas_bp.delete("/<int:id_cancha>")
@require_auth(roles=["administrador"])
def eliminar_cancha(id_cancha):
    if id_cancha <= 0:
        return error_json("El id_cancha debe ser mayor que 0.")

    try:
        canchas_service.eliminar_cancha(id_cancha)
        return jsonify({"mensaje": "Cancha retirada con éxito."}), 200

    except ValueError as e:
        db.session.rollback()
        mensaje = str(e)
        codigo = 404 if "no existe" in mensaje.lower() else 409
        return error_json(mensaje, codigo=codigo)

    except IntegrityError:
        db.session.rollback()
        return error_json(
            "No se puede retirar físicamente la cancha porque tiene reservas o "
            "eventos asociados. Use PATCH /api/canchas/<id>/estado para "
            "colocarla como inactivo.",
            codigo=409,
        )

    except Exception as e:
        db.session.rollback()
        return error_json("No se pudo retirar la cancha.", str(e), 409)


@canchas_bp.patch("/<int:id_cancha>/estado")
@require_auth(roles=["administrador"])
def cambiar_estado_cancha(id_cancha):
    if id_cancha <= 0:
        return error_json("El id_cancha debe ser mayor que 0.")

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return error_json("El cuerpo de la solicitud debe ser un objeto JSON válido.")

    try:
        cancha = canchas_service.cambiar_estado_cancha(
            id_cancha,
            data.get("estado"),
            motivo=data.get("motivo"),
            id_usuario=getattr(g, "current_user", None).id_usuario,
        )

        return jsonify({
            "mensaje": f"Estado actualizado a {cancha.estado}.",
            "cancha": canchas_service.serializar(cancha),
        }), 200

    except ValueError as e:
        db.session.rollback()
        mensaje = str(e)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        return error_json(mensaje, codigo=codigo)

    except Exception as e:
        db.session.rollback()
        return error_json("Error interno al cambiar el estado.", str(e), 500)
