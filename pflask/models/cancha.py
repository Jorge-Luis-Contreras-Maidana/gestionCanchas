from extensions import db
from sqlalchemy import Time, func


class Cancha(db.Model):
    __tablename__ = "cancha"

    id_cancha = db.Column(db.Integer, primary_key=True)
    nombre_cancha = db.Column(db.String(80), nullable=False)
    tipo_deporte = db.Column(db.String(50), nullable=False)
    precio_hora = db.Column(db.Numeric(10, 2), nullable=False)
    ubicacion = db.Column(db.String(150))
    estado = db.Column(db.String(20), nullable=False, default="disponible")
    techada = db.Column(db.Boolean, nullable=False, default=False)
    superficie = db.Column(db.String(50))

    imagen_url = db.Column(db.String(500))
    horario_apertura = db.Column(Time)
    horario_cierre = db.Column(Time)
    dias_atencion = db.Column(db.String(20))

    id_categoria = db.Column(
        db.Integer,
        db.ForeignKey("categoria.id_categoria"),
        nullable=False,
    )

    id_administrador = db.Column(
        db.Integer,
        db.ForeignKey("administrador.id_administrador"),
        nullable=False,
    )

    categoria = db.relationship("Categoria", lazy=True)

    # Galería de fotos: se guardan como binario en cancha_imagen y se borran
    # junto con la cancha (cascade ORM).
    imagenes = db.relationship(
        "CanchaImagen",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="CanchaImagen.orden",
    )

    def to_dict(self):
        nombre_categoria = (
            self.categoria.nombre if self.categoria else None
        )
        return {
            "id": self.id_cancha,
            "id_cancha": self.id_cancha,
            "nombre": self.nombre_cancha,
            "nombre_cancha": self.nombre_cancha,
            "deporte": self.tipo_deporte,
            "tipo_deporte": self.tipo_deporte,
            "precio_hora": float(self.precio_hora),
            "ubicacion": self.ubicacion,
            "estado": self.estado,
            "techada": bool(self.techada),
            "superficie": self.superficie,
            "id_categoria": self.id_categoria,
            "nombre_categoria": nombre_categoria,
            "categoria": nombre_categoria,
            "id_administrador": self.id_administrador,
            "imagen_url": self.imagen_url,
            "horario_apertura": (
                self.horario_apertura.strftime("%H:%M") if self.horario_apertura else None
            ),
            "horario_cierre": (
                self.horario_cierre.strftime("%H:%M") if self.horario_cierre else None
            ),
            "dias_atencion": self.dias_atencion,
        }
