from datetime import datetime

from extensions import db


class Reserva(db.Model):
    __tablename__ = "reserva"

    id_reserva = db.Column(db.Integer, primary_key=True)
    fecha_reserva = db.Column(db.Date, nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    duracion = db.Column(db.Interval)
    # Sin este valor el INSERT manda NULL y la columna (NOT NULL) revienta:
    # el modelo debe enviar la fecha, no confiar en el default de la BD.
    fecha_creacion = db.Column(db.DateTime, nullable=False, default=datetime.now)
    estado_reserva = db.Column(db.String(20), nullable=False)
    motivo_cancelacion = db.Column(db.Text)
    id_cliente = db.Column(
        db.Integer,
        db.ForeignKey("cliente.id_cliente"),
        nullable=False,
    )
    id_cancha = db.Column(
        db.Integer,
        db.ForeignKey("cancha.id_cancha"),
        nullable=False,
    )
    monto_total = db.Column(db.Numeric(10, 2))
    expira_en = db.Column(db.DateTime)
    canal_origen = db.Column(db.String(20), nullable=False, default="web")

    def to_dict(self):
        return {
            "id_reserva": self.id_reserva,
            "fecha_reserva": (
                self.fecha_reserva.isoformat() if self.fecha_reserva else None
            ),
            "hora_inicio": (
                self.hora_inicio.strftime("%H:%M") if self.hora_inicio else None
            ),
            "hora_fin": self.hora_fin.strftime("%H:%M") if self.hora_fin else None,
            "estado_reserva": self.estado_reserva,
            "id_cliente": self.id_cliente,
            "id_cancha": self.id_cancha,
            "monto_total": (
                float(self.monto_total) if self.monto_total is not None else None
            ),
            "expira_en": self.expira_en.isoformat() if self.expira_en else None,
            "canal_origen": self.canal_origen,
        }