from datetime import datetime

from extensions import db


class CanchaImagen(db.Model):
    """Foto de una cancha, guardada como binario dentro de la base de datos."""

    __tablename__ = "cancha_imagen"

    id_imagen = db.Column(db.Integer, primary_key=True)
    id_cancha = db.Column(
        db.Integer,
        db.ForeignKey("cancha.id_cancha", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    orden = db.Column(db.Integer, nullable=False, default=1)
    mime_type = db.Column(db.String(20), nullable=False)
    nombre_archivo = db.Column(db.String(150))
    tamano_bytes = db.Column(db.Integer, nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    fecha_subida = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def to_dict(self):
        return {
            "id_imagen": self.id_imagen,
            "id_cancha": self.id_cancha,
            "orden": self.orden,
            "mime_type": self.mime_type,
            "nombre_archivo": self.nombre_archivo,
            "tamano_bytes": self.tamano_bytes,
            "fecha_subida": (
                self.fecha_subida.isoformat() if self.fecha_subida else None
            ),
            # La imagen en sí viaja por GET /api/canchas/<id>/imagenes/<img_id>
            "url": f"/api/canchas/{self.id_cancha}/imagenes/{self.id_imagen}",
        }
