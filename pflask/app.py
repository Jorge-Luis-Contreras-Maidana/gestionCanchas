import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from extensions import db

load_dotenv()

app = Flask(__name__)

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("No se encontró DATABASE_URL en el archivo .env.")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Comprobantes de pago: se valida el tipo real del archivo y los 5 MB en el
# servicio, asi que el limite de Flask es solo una red de seguridad.
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], "comprobantes"), exist_ok=True)

db.init_app(app)
CORS(app)


# ==========================================================
# RUTA DE INICIO
# ==========================================================

@app.get("/")
def inicio():
    return jsonify({
        "mensaje": "API de Gestión de Canchas funcionando",
        "endpoints": {
            "categorias": [
                "POST /api/categorias",
                "GET /api/categorias",
                "GET /api/categorias/<id>",
                "PATCH /api/categorias/<id>",
                "DELETE /api/categorias/<id>",
            ],
            "canchas": [
                "POST /api/canchas",
                "GET /api/canchas?q=&deporte=&estado=&orden=",
                "GET /api/canchas/<id>",
                "PATCH /api/canchas/<id>",
                "DELETE /api/canchas/<id>",
                "PATCH /api/canchas/<id>/estado",
                "GET /api/canchas/<id>/imagenes",
                "GET /api/canchas/<id>/imagenes/<id_imagen>",
                "POST /api/canchas/<id>/imagenes (multipart, admin)",
                "DELETE /api/canchas/<id>/imagenes/<id_imagen> (admin)",
            ],
            "pagos": [
                "POST /api/pagos",
                "GET /api/pagos",
                "GET /api/pagos/<id>",
                "PATCH /api/pagos/<id>/estado",
                "DELETE /api/pagos/<id>",
            ],
            "reportes": [
                "POST /api/reportes",
                "GET /api/reportes",
                "GET /api/reportes/<id>",
                "DELETE /api/reportes/<id>",
            ],
            "reservas": [
                "POST /api/reservas",
                "GET /api/reservas/historial",
                "GET /api/reservas/<id_cliente>",
                "GET /api/reservas/<id_cliente>/vigentes",
                "PUT /api/reservas/<id>/cancelar",
                "POST /api/reservas/<id>/pagar",
                "GET /api/admin/reservas",
                "PUT /api/admin/reservas/<id>/cancelar-admin",
                "PUT /api/admin/reservas/<id>/modificar-admin",
                "POST /api/empleado/reservas",
                "GET /api/clientes",
                "POST /api/admin/clientes",
                "GET /api/bloqueos",
                "POST /api/admin/bloqueos",
                "DELETE /api/admin/bloqueos/<id>",
                "POST /api/admin/canchas",
                "PUT /api/admin/canchas/<id>",
                "DELETE /api/admin/canchas/<id>",
                "POST /api/admin/categorias",
                "PUT /api/admin/categorias/<id>",
                "DELETE /api/admin/categorias/<id>",
            ],
        },
    }), 200


# ==========================================================
# REGISTRO DE MÓDULOS (BLUEPRINTS)
# ==========================================================

# Módulo de autenticación y usuarios (ver controllers/auth_controller.py)
from controllers.auth_controller import register_auth
register_auth(app)

# Módulo de Eventos y Servicios Sociales
from controllers.eventos_controller import eventos_bp
app.register_blueprint(eventos_bp)

# Módulo de Categorías y Canchas
from controllers.categorias_controller import categorias_bp
from controllers.canchas_controller import canchas_bp
app.register_blueprint(categorias_bp)
app.register_blueprint(canchas_bp)

# Módulo de Pagos
from controllers.pagos_controller import pagos_bp, caja_bp
app.register_blueprint(pagos_bp)
app.register_blueprint(caja_bp)

# Módulo de Reportes
from controllers.reportes_controller import reportes_bp
app.register_blueprint(reportes_bp)

# Módulo de Notificaciones
from controllers.notificaciones_controller import notificaciones_bp
app.register_blueprint(notificaciones_bp)

# Módulo de Analítica (vistas SQL para el dashboard)
from controllers.analitica_controller import analitica_bp
app.register_blueprint(analitica_bp)

# Módulo de Reservas, Clientes y Bloqueos
from controllers.reservas_controller import reservas_bp
app.register_blueprint(reservas_bp)

# Módulo de Tarifas por franja y Horarios por día
from controllers.tarifas_controller import tarifas_bp
app.register_blueprint(tarifas_bp)


if __name__ == "__main__":
    # Worker en segundo plano: expira pagos y reservas sin pagar, y completa
    # las reservas cuya hora de juego ya paso.
    import threading

    from services import pagos_service, reservas_service, notificaciones_service


    def _background_worker():
        with app.app_context():
            while True:
                # Los pagos expiran antes que las reservas para que la reserva
                # ya no vea saldo por cobrar cuando se expira.
                for nombre, accion in (
                    ("pagos", pagos_service.expirar_pagos_vencidos),
                    ("reservas", reservas_service.expirar_reservas_vencidas),
                    ("completar", reservas_service.completar_reservas_pasadas),
                    ("recordatorios", notificaciones_service.generar_recordatorios),
                    # El envio va al final y aparte: la reserva nunca espera.
                    ("notificaciones", notificaciones_service.enviar_pendientes),
                ):
                    try:
                        accion()
                    except Exception as e:  # noqa: BLE001
                        print(f"[WORKER ERROR:{nombre}] {e}")
                import time
                time.sleep(60)


    worker = threading.Thread(target=_background_worker, daemon=True)
    worker.start()
    print("Scheduler automático iniciado (cada 60s)")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
    )