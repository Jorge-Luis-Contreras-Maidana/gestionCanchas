from datetime import datetime, timedelta

from extensions import db
from models.administrador import Administrador
from models.bloqueo import Bloqueo
from models.cancha import Cancha
from models.categoria import Categoria
from models.cliente import Cliente
from models.empleado import Empleado
from models.evento import Evento
from models.historial_estado_cancha import HistorialEstadoCancha
from models.historial_precio_cancha import HistorialPrecioCancha
from models.historial_reserva import HistorialReserva
from models.pago import (
    ESTADO_APROBADO,
    ESTADO_PENDIENTE,
    ESTADO_PENDIENTE_VALIDACION,
    METODOS_DIGITALES,
    METODOS_PAGO_VALIDOS,
    Pago,
)
from models.persona import Persona
from models.reserva import Reserva
from models.usuario import Usuario
from services.auth_service import hash_password
from validators.auth_validator import validar_password, validar_ci, validar_celular

HORA_APERTURA = datetime.strptime("06:00", "%H:%M").time()
HORA_CIERRE = datetime.strptime("23:00", "%H:%M").time()
#: Estados que el administrador puede elegir en una cancha. "ocupada" se
#: calcula sola y por eso no figura. El alias fuera_servicio se acepta por
#: compatibilidad y se guarda como inactivo.
ESTADOS_VALIDOS_CANCHA = ("disponible", "mantenimiento", "inactivo")
ESTADOS_ALIAS_CANCHA = {"fuera_servicio": "inactivo", "activo": "disponible"}
ESTADOS_TERMINALES = ("cancelada", "completada", "expirada")
ESTADOS_ACTIVOS = ("pendiente", "confirmada")
MINUTOS_PARA_PAGAR = 15
HORAS_MAX_RESERVA = 4
DIAS_MAX_ANTICIPACION = 15

# Politica de devolucion por cancelacion. El documento de requisitos no define
# los porcentajes, asi que quedan en constantes para ajustarlos en un solo punto.
HORAS_MINIMAS_REEMBOLSO = 1
PORCENTAJE_REEMBOLSO_FUERA_DE_PLAZO = 1.0
PORCENTAJE_REEMBOLSO_DENTRO_DE_PLAZO = 0.0


# ============================================================
# HELPERS
# ============================================================
def _notificar(funcion, *args, **kwargs):
    """Encola los avisos del modulo de Notificaciones.

    Un aviso nunca debe tumbar la operacion que lo dispara: si falla, se
    avisa por consola y la reserva sigue su curso.
    """
    try:
        from services import notificaciones_service

        return getattr(notificaciones_service, funcion)(*args, **kwargs)
    except Exception as ex:  # noqa: BLE001
        print(f"[NOTIFICACION OMITIDA] {ex}")
        return None


def _fecha(valor, nombre="fecha"):
    try:
        return datetime.strptime(str(valor).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError(f"{nombre} inválida. Use el formato YYYY-MM-DD.")


def _hora(valor, nombre="hora"):
    try:
        return datetime.strptime(str(valor).strip(), "%H:%M").time()
    except (ValueError, TypeError):
        raise ValueError(f"{nombre} inválida. Use el formato HH:MM.")


def _split_nombre(nombre_completo, apellido_explicit=None):
    parts = (nombre_completo or "").strip().split()
    nombre = parts[0] if parts else nombre_completo
    if apellido_explicit and str(apellido_explicit).strip():
        apellido = str(apellido_explicit).strip()
    else:
        apellido = " ".join(parts[1:]) if len(parts) > 1 else (nombre if nombre else "")
    return (nombre or "")[:80], (apellido or "")[:80]


def validar_horario(hora_inicio, hora_fin):
    if hora_inicio < HORA_APERTURA:
        return False, f"La hora de inicio debe ser después de las {HORA_APERTURA.strftime('%H:%M')}."
    if hora_fin > HORA_CIERRE:
        return False, f"La hora de fin debe ser antes de las {HORA_CIERRE.strftime('%H:%M')}."
    return True, None


def _registrar_historial(id_reserva, tipo_cambio, detalle=None, id_usuario=None):
    db.session.add(
        HistorialReserva(
            id_reserva=id_reserva,
            tipo_cambio=tipo_cambio,
            detalle=(detalle or "").strip() or None,
            id_usuario=id_usuario,
            fecha=datetime.now(),
        )
    )


def expirar_reservas_vencidas():
    """Sin pago dentro de los 15 minutos la reserva pasa a EXPIRADA y libera la cancha."""
    ahora = datetime.now()
    # Reservas nuevas: tienen expira_en fijado al crearse.
    vencidas = Reserva.query.filter(
        Reserva.estado_reserva == "pendiente",
        Reserva.expira_en.is_not(None),
        Reserva.expira_en < ahora,
    ).all()
    # Reservas antiguas sin expira_en: se calcula por fecha_creacion.
    antiguas = Reserva.query.filter(
        Reserva.estado_reserva == "pendiente",
        Reserva.expira_en.is_(None),
        Reserva.fecha_creacion < ahora - timedelta(minutes=MINUTOS_PARA_PAGAR),
    ).all()
    for r in vencidas + antiguas:
        r.estado_reserva = "expirada"
        r.expira_en = None
        r.motivo_cancelacion = "Expirada por falta de pago (tiempo límite de 15 min)"
        _registrar_historial(
            r.id_reserva,
            "expiracion",
            "Expirada automáticamente por falta de pago en 15 minutos",
        )
    if vencidas or antiguas:
        db.session.commit()
    return len(vencidas) + len(antiguas)


def completar_reservas_pasadas():
    """Confirmada que ya pasó su hora fin -> FINALIZADA."""
    ahora = datetime.now()
    hoy = ahora.date()
    hora_actual = ahora.time()
    completadas = Reserva.query.filter(
        Reserva.estado_reserva == "confirmada"
    ).filter(
        db.or_(
            Reserva.fecha_reserva < hoy,
            db.and_(Reserva.fecha_reserva == hoy, Reserva.hora_fin < hora_actual),
        )
    ).all()
    for r in completadas:
        r.estado_reserva = "completada"
        _registrar_historial(
            r.id_reserva, "finalizacion", "Finalizada automáticamente al terminar el horario"
        )
    if completadas:
        db.session.commit()
    return len(completadas)


def _hay_bloqueo(id_cancha, fecha, hora_inicio, hora_fin):
    return Bloqueo.query.filter(
        Bloqueo.id_cancha == id_cancha,
        Bloqueo.estado == "activo",
        Bloqueo.fecha_inicio <= fecha,
        Bloqueo.fecha_fin >= fecha,
        Bloqueo.hora_inicio < hora_fin,
        Bloqueo.hora_fin > hora_inicio,
    ).first()


def _encontrar_choque(id_cancha, fecha, hora_inicio, hora_fin, excluir_id=None):
    query = Reserva.query.filter(
        Reserva.id_cancha == id_cancha,
        Reserva.fecha_reserva == fecha,
        Reserva.estado_reserva.in_(ESTADOS_ACTIVOS),
        Reserva.hora_inicio < hora_fin,
        Reserva.hora_fin > hora_inicio,
    )
    if excluir_id:
        query = query.filter(Reserva.id_reserva != excluir_id)
    return query.first()


def _encontrar_evento(id_cancha, fecha, hora_inicio, hora_fin):
    return Evento.query.filter(
        Evento.id_cancha == id_cancha,
        Evento.fecha_evento == fecha,
        Evento.hora_inicio < hora_fin,
        Evento.hora_fin > hora_inicio,
    ).first()


def _horarios_disponibles(id_cancha, fecha, duracion_h):
    """Alternativas de horario el mismo día cuando el solicitado está ocupado."""
    return [s["hora_inicio"] + "-" + s["hora_fin"] for s in listar_slots(id_cancha, fecha, duracion_h)]


def listar_slots(id_cancha, fecha, duracion_h=1):
    """Slots horarios libres de la cancha, respetando su horario de atención.

    Devuelve lista de dicts: {hora_inicio, hora_fin, disponible, motivo}.
    """
    duracion_h = float(duracion_h or 1)
    if duracion_h <= 0 or duracion_h > HORAS_MAX_RESERVA:
        raise ValueError("La duración debe ser entre 1 y 4 horas.")

    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")
    if cancha.estado != "disponible":
        raise ValueError("La cancha no está disponible.")

    # Primero se depura lo vencido/completado para no mostrar slots falsos.
    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    from services.tarifas_service import obtener_horario_dia

    horario_dia = obtener_horario_dia(id_cancha, fecha.weekday())
    if horario_dia is None:
        return []
    apertura, cierre = horario_dia
    if apertura < HORA_APERTURA:
        apertura = HORA_APERTURA
    if cierre > HORA_CIERRE:
        cierre = HORA_CIERRE

    slots = []

    actual = datetime.combine(fecha, apertura)
    limite = datetime.combine(fecha, cierre)
    while actual + timedelta(hours=duracion_h) <= limite:
        h_ini = actual.time()
        h_fin = (actual + timedelta(hours=duracion_h)).time()
        bloqueo = _hay_bloqueo(id_cancha, fecha, h_ini, h_fin)
        choque = _encontrar_choque(id_cancha, fecha, h_ini, h_fin)
        evento = _encontrar_evento(id_cancha, fecha, h_ini, h_fin)
        if bloqueo:
            motivo = f"Bloqueada: {bloqueo.motivo}"
        elif choque:
            motivo = "Reservada"
        elif evento:
            motivo = f"Evento: {evento.nombre_evento}"
        else:
            motivo = None
        monto, _partes = _desglose(cancha, fecha, h_ini, duracion_h)
        slots.append({
            "hora_inicio": h_ini.strftime("%H:%M"),
            "hora_fin": h_fin.strftime("%H:%M"),
            "disponible": motivo is None,
            "motivo": motivo,
            "precio_hora": _precio_slot(cancha, fecha, h_ini),
            "monto_estimado": monto,
        })
        actual += timedelta(hours=1)
    return slots


def _precio_slot(cancha, fecha, hora_inicio):
    from services import tarifas_service

    try:
        return tarifas_service.obtener_tarifa_hora(cancha, fecha, hora_inicio)
    except Exception:
        return float(cancha.precio_hora)


def _desglose(cancha, fecha, hora_inicio, duracion_h):
    from services import tarifas_service

    return tarifas_service.desglose_monto(cancha, fecha, hora_inicio, duracion_h)


def consultar_disponibilidad(id_cancha, fecha_valor, duracion):
    """Endpoint público de disponibilidad para una fecha y duración."""
    from services import tarifas_service

    fecha = _fecha(fecha_valor)
    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")

    horario_dia = tarifas_service.obtener_horario_dia(id_cancha, fecha.weekday())
    return {
        "id_cancha": id_cancha,
        "cancha": cancha.nombre_cancha,
        "fecha": str(fecha),
        "dia_nombre": tarifas_service.DIAS[fecha.weekday()],
        "duracion": float(duracion or 1),
        "horario_cancha": (
            {
                "hora_apertura": horario_dia[0].strftime("%H:%M"),
                "hora_cierre": horario_dia[1].strftime("%H:%M"),
            }
            if horario_dia
            else None
        ),
        "precio_hora_base": float(cancha.precio_hora),
        "horarios": listar_slots(id_cancha, fecha, duracion),
    }


def _validar_horario_cancha(cancha, fecha, hora_inicio, hora_fin):
    """El horario debe caber dentro del horario de atención de la cancha ese día."""
    from services.tarifas_service import obtener_horario_dia

    horario = obtener_horario_dia(cancha.id_cancha, fecha.weekday())
    if horario is None:
        raise ValueError("La cancha no opera ese día.")
    apertura, cierre = horario

    if hora_inicio < apertura or hora_fin > cierre:
        raise ValueError(
            f"El horario debe estar dentro del horario de la cancha "
            f"({apertura.strftime('%H:%M')}-{cierre.strftime('%H:%M')})."
        )


def _dias_habiles(cancha, fecha):
    """None = todos los días. Lista de ints (0=lunes) = días de atención."""
    from services.tarifas_service import obtener_horario_dia

    dias = []
    for dia in range(7):
        if obtener_horario_dia(cancha.id_cancha, dia) is not None:
            dias.append(dia)
    return dias or None


def _validaciones_reserva(fecha_reserva, hora_inicio, hora_fin, duracion_h=None, id_cancha=None, excluir_id=None):
    """VALIDACIONES EN ORDEN (documento de lógica de negocio).

    1. La cancha está Disponible.
    2. La fecha está entre 1 y 15 días de anticipación.
    3. La duración es de 1 a 4 horas.
    4. El horario está dentro del horario de atención y del horario de la cancha.
    5. No hay solapamiento con reservas activas, bloqueos ni eventos.
    """
    # --- 1. La cancha está DISPONIBLE ---
    if id_cancha is not None:
        cancha = db.session.get(Cancha, id_cancha)
        if not cancha:
            raise ValueError("Cancha no encontrada.")
        if cancha.estado != "disponible":
            raise ValueError(
                "La cancha no está disponible "
                f"(estado actual: {cancha.estado.replace('_', ' ')})."
            )
    else:
        cancha = None

    # --- 2. Fecha entre 1 y 15 días de anticipación ---
    hoy = datetime.now().date()
    dias = (fecha_reserva - hoy).days
    if dias < 1 or dias > DIAS_MAX_ANTICIPACION:
        raise ValueError("La fecha debe estar entre 1 y 15 días de anticipación.")

    # --- 3. Duración entre 1 y 4 horas ---
    if duracion_h is not None:
        if duracion_h <= 0 or duracion_h > HORAS_MAX_RESERVA:
            raise ValueError("La duración debe ser entre 1 y 4 horas.")
    if hora_fin <= hora_inicio:
        raise ValueError("La hora fin debe ser mayor que la hora inicio.")

    # --- 4. Horario de atención (06:00-23:00) y horario de la cancha ---
    ok, err = validar_horario(hora_inicio, hora_fin)
    if not ok:
        raise ValueError(err)
    if cancha is not None:
        _validar_horario_cancha(cancha, fecha_reserva, hora_inicio, hora_fin)

    # --- 5. Sin solapamiento con reservas activas, bloqueos ni eventos ---
    if id_cancha is not None:
        bloqueo = _hay_bloqueo(id_cancha, fecha_reserva, hora_inicio, hora_fin)
        if bloqueo:
            raise ValueError(f"La cancha está bloqueada: {bloqueo.motivo}")
        evento = _encontrar_evento(id_cancha, fecha_reserva, hora_inicio, hora_fin)
        if evento:
            raise ValueError(
                f"La cancha tiene el evento '{evento.nombre_evento}' en ese horario."
            )
        choque = _encontrar_choque(
            id_cancha, fecha_reserva, hora_inicio, hora_fin, excluir_id=excluir_id
        )
        if choque:
            alternativas = _horarios_disponibles(id_cancha, fecha_reserva, duracion_h)
            mensaje = "La cancha no está disponible en ese horario."
            if alternativas:
                mensaje += f" Horarios libres: {', '.join(alternativas[:4])}."
            raise ValueError(mensaje)
        return cancha
    return None


def _tarifa_aplicable(cancha, fecha, hora_inicio):
    """Precio por hora aplicable a esa franja.

    Prioridad: fin de semana > nocturna > normal; dentro de una franja gana la
    más específica (día concreto y ventana más estrecha). Si la cancha no tiene
    tarifas configuradas, cae a su precio_hora.
    """
    from services import tarifas_service

    return tarifas_service.obtener_tarifa_hora(cancha, fecha, hora_inicio)


def _calcular_monto(cancha, fecha, hora_inicio, duracion_h):
    """Monto = duración x tarifa aplicable (normal, nocturna o fin de semana).

    Si la reserva cruza de una franja a otra, cada hora se cobra a su tarifa.
    """
    if duracion_h is None or duracion_h <= 0:
        raise ValueError("La duración debe ser entre 1 y 4 horas.")
    from services import tarifas_service

    total, _partes = tarifas_service.desglose_monto(cancha, fecha, hora_inicio, duracion_h)
    return total


def _calcular_duracion(fecha_reserva, hora_inicio, datos, duracion_h=None, hora_fin=None):
    if hora_fin is None and datos.get("hora_fin") not in (None, ""):
        hora_fin = _hora(datos["hora_fin"])
    if hora_fin is None and duracion_h is not None:
        hora_fin = (datetime.combine(fecha_reserva, hora_inicio) + timedelta(hours=duracion_h)).time()
    elif hora_fin is not None and duracion_h is None:
        diff = datetime.combine(fecha_reserva, hora_fin) - datetime.combine(fecha_reserva, hora_inicio)
        duracion_h = diff.total_seconds() / 3600
    elif hora_fin is None and duracion_h is None:
        raise ValueError("Indica la duración o la hora fin de la reserva.")
    return hora_fin, duracion_h


# ============================================================
# RESERVAS
# ============================================================
def crear_reserva(datos, current_user=None):
    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    try:
        id_cancha = int(datos["id_cancha"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("id_cancha es obligatorio.")
    if id_cancha <= 0:
        raise ValueError("id_cancha debe ser mayor que 0.")

    fecha_reserva = _fecha(datos.get("fecha_reserva") or datos.get("fecha"))
    hora_inicio = _hora(datos.get("hora_inicio"))

    duracion_h = None
    if datos.get("duracion") not in (None, ""):
        duracion_h = float(datos["duracion"])
        if duracion_h < 1 or duracion_h > 4:
            raise ValueError("La duración debe ser entre 1 y 4 horas.")

    hora_fin, duracion_h = _calcular_duracion(fecha_reserva, hora_inicio, datos, duracion_h)
    if duracion_h <= 0 or duracion_h > 4:
        raise ValueError("La duración debe ser entre 1 y 4 horas.")

    # El cliente debe decidir como paga ANTES de reservar. Como el complejo esta
    # cerrado no hay ventanilla, asi que el efectivo queda descartado y solo se
    # aceptan metodos digitales.
    metodo_pago = (datos.get("metodo_pago") or "").strip().lower()
    if metodo_pago == "efectivo":
        raise ValueError(
            "No se puede reservar con efectivo porque el complejo de canchas está "
            "cerrado. Elige QR, transferencia o tarjeta."
        )
    if metodo_pago not in METODOS_DIGITALES:
        raise ValueError(
            "Elige un método de pago válido para reservar: QR, transferencia o tarjeta."
        )

    id_cliente = datos.get("id_cliente")
    if id_cliente in (None, ""):
        if current_user is not None:
            cliente = Cliente.query.filter_by(id_usuario=current_user.id_usuario).first()
            if not cliente:
                raise ValueError("El usuario actual no está registrado como cliente.")
            id_cliente = cliente.id_cliente
        else:
            raise ValueError("id_cliente es obligatorio.")
    try:
        id_cliente = int(id_cliente)
    except (TypeError, ValueError):
        raise ValueError("id_cliente inválido.")
    if not db.session.get(Cliente, id_cliente):
        raise ValueError("El cliente indicado no existe.")

    cancha = _validaciones_reserva(fecha_reserva, hora_inicio, hora_fin, duracion_h, id_cancha)

    # El monto se guarda COPIADO en la reserva (RNF-05): cambios futuros de
    # tarifa o precio no alteran esta reserva ni sus pagos.
    monto_total = _calcular_monto(cancha, fecha_reserva, hora_inicio, duracion_h)

    nueva = Reserva(
        fecha_reserva=fecha_reserva,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        duracion=timedelta(hours=duracion_h),
        estado_reserva="pendiente",
        id_cliente=id_cliente,
        id_cancha=id_cancha,
        monto_total=monto_total,
        expira_en=datetime.now() + timedelta(minutes=MINUTOS_PARA_PAGAR),
        canal_origen="web",
    )
    db.session.add(nueva)
    db.session.flush()

    _registrar_historial(
        nueva.id_reserva,
        "creacion",
        f"Reserva creada para {fecha_reserva} {hora_inicio.strftime('%H:%M')}-"
        f"{hora_fin.strftime('%H:%M')}, monto {monto_total}",
        id_usuario=getattr(current_user, "id_usuario", None),
    )
    db.session.commit()
    db.session.refresh(nueva)
    # Aviso al administrador de la nueva reserva.
    _notificar("avisar_administradores", "nueva_reserva", nueva)

    return {
        "mensaje": "Reserva creada. Tienes 15 minutos para pagar antes de que expire.",
        "id_reserva": nueva.id_reserva,
        "monto_total": monto_total,
        "metodo_pago": metodo_pago,
        "estado": "pendiente",
        "expira_en": nueva.expira_en.isoformat() if nueva.expira_en else None,
        "desglose": _desglose(cancha, fecha_reserva, hora_inicio, duracion_h)[1],
    }


def _cancelar_reserva_sin_pago(reserva, motivo, id_usuario=None):
    """Cancela una reserva ya confirmada cuyo pago nunca llego a registrarse.

    El modulo de Pagos trabaja con su propia transaccion, asi que un fallo ahi
    no puede deshacer el commit de la reserva. Cancelarla libera el horario y
    deja el motivo en el historial, en lugar de un pendiente sin pago.
    """
    reserva.estado_reserva = "cancelada"
    reserva.motivo_cancelacion = motivo
    _registrar_historial(
        reserva.id_reserva,
        "cancelada_pago_fallido",
        motivo,
        id_usuario=id_usuario,
    )
    db.session.commit()


def crear_reserva_presencial(datos, current_user=None):
    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    try:
        id_cancha = int(datos["id_cancha"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("id_cancha es obligatorio.")
    try:
        id_cliente = int(datos["id_cliente"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("id_cliente es obligatorio.")

    metodo = (datos.get("metodo_pago") or "efectivo").strip().lower()
    if metodo not in METODOS_PAGO_VALIDOS:
        raise ValueError("Método de pago inválido.")

    id_empleado = datos.get("id_empleado")
    if id_empleado not in (None, ""):
        if not db.session.get(Empleado, int(id_empleado)):
            raise ValueError("El empleado indicado no existe.")

    fecha_reserva = _fecha(datos.get("fecha_reserva") or datos.get("fecha"))
    hora_inicio = _hora(datos.get("hora_inicio"))

    duracion_h = None
    if datos.get("duracion") not in (None, ""):
        duracion_h = float(datos["duracion"])
        if duracion_h < 1 or duracion_h > 4:
            raise ValueError("La duración debe ser entre 1 y 4 horas.")

    hora_fin, duracion_h = _calcular_duracion(fecha_reserva, hora_inicio, datos, duracion_h)
    if duracion_h <= 0 or duracion_h > 4:
        raise ValueError("La duración debe ser entre 1 y 4 horas.")

    if not db.session.get(Cliente, id_cliente):
        raise ValueError("El cliente indicado no existe.")

    cancha = _validaciones_reserva(fecha_reserva, hora_inicio, hora_fin, duracion_h, id_cancha)

    monto_total = _calcular_monto(cancha, fecha_reserva, hora_inicio, duracion_h)

    # El pago se registra por el modulo de Pagos: aplica turno de caja, saldo,
    # idempotencia y auditoria. Se importa aca para evitar dependencia circular.
    from services import pagos_service

    # El efectivo exige turno de caja abierto. Se valida ANTES de insertar la
    # reserva: si se comprobara despues, el fallo dejaria la reserva ya
    # confirmada en la base y sin pago, porque el commit siguiente no lo puede
    # deshacer un rollback.
    turno = None
    if metodo == "efectivo":
        if id_empleado in (None, ""):
            raise ValueError("El pago en efectivo requiere el empleado que lo recibe.")
        turno = pagos_service.turno_abierto_del_empleado(int(id_empleado))
        if not turno:
            raise ValueError("El empleado no tiene un turno de caja abierto.")

    nueva = Reserva(
        fecha_reserva=fecha_reserva,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        duracion=timedelta(hours=duracion_h),
        estado_reserva="pendiente",
        id_cliente=id_cliente,
        id_cancha=id_cancha,
        monto_total=monto_total,
        canal_origen="presencial",
    )
    db.session.add(nueva)
    db.session.flush()

    _registrar_historial(
        nueva.id_reserva,
        "creacion_presencial",
        f"Reserva presencial por {monto_total}",
        id_usuario=getattr(current_user, "id_usuario", None),
    )
    db.session.commit()

    # La reserva se confirma sola si el saldo llega a 0 y el pago queda aprobado.
    datos_pago = {
        "id_reserva": nueva.id_reserva,
        "metodo_pago": metodo,
        "monto": monto_total,
        "id_empleado": int(id_empleado) if id_empleado not in (None, "") else None,
    }
    id_usuario = getattr(current_user, "id_usuario", None)

    # El modulo de Pagos confirma su propia transaccion: a partir de este punto
    # la reserva ya esta escrita en la base. Si el pago no llega a existir por
    # otra causa (saldo, comprobante repetido, idempotencia) la reserva se
    # cancela en vez de quedar pendiente y sin pago.
    try:
        if metodo == "efectivo":
            datos_pago["id_turno"] = turno.id_turno
            pago = pagos_service.registrar_pago_efectivo(datos_pago, id_usuario)["pago"]
        else:
            # El empleado esta presente: registra el comprobante y lo aprueba.
            pago = pagos_service.registrar_comprobante(datos_pago, None, id_usuario)["pago"]
            if pago["estado_pago"] == ESTADO_PENDIENTE_VALIDACION:
                pago = pagos_service.aprobar_pago(
                    pago["id_pago"], id_usuario, "Validado en ventanilla por el empleado."
                )["pago"]
    except Exception as exc:
        _cancelar_reserva_sin_pago(nueva, f"Pago no registrado: {exc}", id_usuario)
        raise

    return {
        "mensaje": (
            "Reserva presencial creada y confirmada."
            if pago["estado_pago"] == ESTADO_APROBADO
            else "Reserva presencial creada. El pago queda pendiente de validación."
        ),
        "id_reserva": nueva.id_reserva,
        "id_pago": pago["id_pago"],
        "monto_total": monto_total,
        "estado": pago.get("estado_reserva") or nueva.estado_reserva,
        "estado_pago": pago["estado_pago"],
        "metodo_pago": metodo,
    }


def _formato_cliente(reserva, cancha):
    return {
        "id_reserva": reserva.id_reserva,
        "cancha": cancha.nombre_cancha,
        "id_cancha": cancha.id_cancha,
        "fecha": str(reserva.fecha_reserva),
        "hora_inicio": str(reserva.hora_inicio)[:5],
        "hora_fin": str(reserva.hora_fin)[:5],
        "duracion": str(reserva.duracion) if reserva.duracion else None,
        "estado": reserva.estado_reserva,
        "precio_hora": float(cancha.precio_hora),
        "monto_total": float(reserva.monto_total) if reserva.monto_total is not None else None,
        "expira_en": reserva.expira_en.isoformat() if reserva.expira_en else None,
        "canal_origen": reserva.canal_origen,
        "motivo_cancelacion": reserva.motivo_cancelacion,
    }


def listar_reservas_cliente(id_cliente, vigentes=False):
    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    query = db.session.query(Reserva, Cancha).join(
        Cancha, Reserva.id_cancha == Cancha.id_cancha
    ).filter(Reserva.id_cliente == id_cliente)

    if vigentes:
        hoy = datetime.now().date()
        query = query.filter(
            Reserva.fecha_reserva >= hoy,
            Reserva.estado_reserva.in_(["pendiente", "confirmada"]),
        ).order_by(Reserva.fecha_reserva.asc(), Reserva.hora_inicio.asc())
    else:
        query = query.order_by(Reserva.fecha_reserva.desc(), Reserva.hora_inicio.desc())

    return [_formato_cliente(r, c) for r, c in query.all()]


def listar_reservas_historial(id_cliente):
    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    rows = db.session.query(Reserva, Cancha).join(
        Cancha, Reserva.id_cancha == Cancha.id_cancha
    ).filter(Reserva.id_cliente == id_cliente).order_by(
        Reserva.fecha_reserva.desc(), Reserva.hora_inicio.desc()
    ).all()

    return [
        {
            "id": r.id_reserva,
            "id_reserva": r.id_reserva,
            "fecha": str(r.fecha_reserva),
            "hora_inicio": str(r.hora_inicio)[:5],
            "hora_fin": str(r.hora_fin)[:5],
            "estado": r.estado_reserva,
            "motivo_cancelacion": r.motivo_cancelacion,
            "cancha": {
                "id": c.id_cancha,
                "id_cancha": c.id_cancha,
                "nombre": c.nombre_cancha,
                "deporte": c.tipo_deporte,
            },
        }
        for r, c in rows
    ]


def _calcular_reembolso(reserva):
    """Regla de devolucion: 100% con mas de 1h de anticipacion, 0% dentro de la hora.

    El documento deja los porcentajes open (inconsistencia #3). Se aplica la
    regla conservadora ya usada antes del modulo de Pagos y se parametriza
    aqui para poder cambiarla sin tocar el flujo.
    """
    pagos = Pago.query.filter(
        Pago.id_reserva == reserva.id_reserva,
        Pago.estado_pago == ESTADO_APROBADO,
    ).all()
    if not pagos:
        return 0.0, 0.0
    total_pagado = round(sum(float(p.monto) for p in pagos), 2)
    fecha_hora = datetime.combine(reserva.fecha_reserva, reserva.hora_inicio)
    if datetime.now() > (fecha_hora - timedelta(hours=HORAS_MINIMAS_REEMBOLSO)):
        return total_pagado, 0.0
    return total_pagado, round(total_pagado * PORCENTAJE_REEMBOLSO_FUERA_DE_PLAZO, 2)


def cancelar_reserva(id_reserva, motivo=None, id_usuario=None):
    from services import pagos_service

    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    reserva = db.session.get(Reserva, id_reserva)
    if not reserva:
        raise ValueError("Reserva no encontrada.")
    if reserva.estado_reserva in ESTADOS_TERMINALES:
        raise ValueError(f"No se puede cancelar una reserva en estado '{reserva.estado_reserva}'.")

    fecha_hora = datetime.combine(reserva.fecha_reserva, reserva.hora_inicio)
    if datetime.now() > (fecha_hora - timedelta(hours=HORAS_MINIMAS_REEMBOLSO)):
        raise ValueError(
            f"Solo se puede cancelar hasta {HORAS_MINIMAS_REEMBOLSO} hora(s) antes "
            "de la reserva."
        )

    total_pagado, a_reembolsar = _calcular_reembolso(reserva)
    pagos_aprobados = Pago.query.filter(
        Pago.id_reserva == id_reserva, Pago.estado_pago == ESTADO_APROBADO
    ).all()

    # La devolucion pasa por el modulo de Pagos: se crea la solicitud y la
    # aprueba el empleado desde la caja. No se cambia el estado del pago aqui.
    solicitudes = 0
    if a_reembolsar > 0:
        restante = a_reembolsar
        for pago in pagos_aprobados:
            if restante <= 0:
                break
            a_devolver = min(restante, float(pago.saldo_restante))
            if a_devolver <= 0:
                continue
            pagos_service._preparar_solicitud_devolucion(
                pago.id_pago,
                motivo or "Cancelación de la reserva",
                a_devolver,
            )
            pagos_service._historial_reserva(
                id_reserva,
                "devolucion_solicitada",
                f"Devolución de Bs {a_devolver} por cancelación de la reserva.",
                id_usuario,
            )
            restante = round(restante - a_devolver, 2)
            solicitudes += 1

    reserva.estado_reserva = "cancelada"
    reserva.motivo_cancelacion = motivo or "Cancelada por el cliente"

    _registrar_historial(
        id_reserva,
        "cancelacion_cliente",
        f"Cancelada por el cliente. Motivo: {reserva.motivo_cancelacion}. "
        f"Reembolso: {a_reembolsar} de {total_pagado}",
        id_usuario=id_usuario,
    )
    db.session.commit()
    # Avisos de cancelacion: al cliente y a los administradores.
    _notificar("avisar_cancelacion", reserva)
    _notificar("avisar_administradores", "nueva_cancelacion", reserva)

    if solicitudes:
        mensaje = (
            f"Reserva cancelada. Se registraron {solicitudes} solicitud(es) de "
            "devolución por Bs " + str(a_reembolsar) + ", pendientes de aprobación."
        )
    else:
        mensaje = "Reserva cancelada. No había pagos aprobados por devolver."

    return {
        "mensaje": mensaje,
        "id_reserva": reserva.id_reserva,
        "estado": "cancelada",
        "total_pagado": total_pagado,
        "monto_reembolsable": a_reembolsar,
        "solicitudes_devolucion": solicitudes,
    }


def pagar_reserva(id_reserva, metodo, id_usuario=None, referencia=None):
    """Registra el pago de una reserva pendiente.

    El flujo real vive en pagos_service (saldo, idempotencia, estados). Aqui
    solo se resuelve la reserva: efectivo se aprueba de inmediato, mientras que
    QR o transferencia quedan pendientes de validacion del empleado. La reserva
    pasa a Confirmada unicamente cuando el saldo llega a 0.
    """
    from services import pagos_service

    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    reserva = db.session.get(Reserva, id_reserva)
    if not reserva:
        raise ValueError("Reserva no encontrada.")
    if reserva.estado_reserva != "pendiente":
        raise ValueError(
            f"La reserva no está pendiente de pago (estado actual: '{reserva.estado_reserva}')."
        )
    if reserva.expira_en and datetime.now() > reserva.expira_en:
        reserva.estado_reserva = "expirada"
        reserva.motivo_cancelacion = "Expirada por falta de pago (tiempo límite de 15 min)"
        db.session.commit()
        raise ValueError("La reserva expiró por falta de pago. Vuelve a reservar el horario.")

    metodo = (metodo or "").strip().lower()
    if metodo not in METODOS_PAGO_VALIDOS:
        raise ValueError("Método de pago inválido.")

    saldo = pagos_service.saldo_reserva(id_reserva)
    if saldo <= 0:
        raise ValueError("Esta reserva ya no tiene saldo pendiente.")

    datos = {
        "id_reserva": id_reserva,
        "metodo_pago": metodo,
        "monto": saldo,
        "referencia": referencia,
    }

    if metodo == "efectivo":
        # El efectivo en ventanilla lo registra el empleado con su turno.
        from models.empleado import Empleado as _Empleado

        empleado = _Empleado.query.filter_by(id_usuario=id_usuario).first() if id_usuario else None
        if not empleado:
            raise ValueError(
                "El pago en efectivo lo registra un empleado con su turno de caja abierto."
            )
        from services.pagos_service import turno_abierto_del_empleado

        turno = turno_abierto_del_empleado(empleado.id_empleado)
        if not turno:
            raise ValueError("No tienes un turno de caja abierto para registrar efectivo.")
        datos["id_empleado"] = empleado.id_empleado
        datos["id_turno"] = turno.id_turno
        resultado = pagos_service.registrar_pago_efectivo(datos, id_usuario)
    else:
        # QR o transferencia sin comprobante: queda pendiente de validacion.
        resultado = pagos_service.registrar_comprobante(datos, None, id_usuario)

    pago = resultado["pago"]
    saldo_final = resultado.get("saldo_reserva", pagos_service.saldo_reserva(id_reserva))
    estado = resultado.get("estado_reserva") or reserva.estado_reserva

    mensajes = {
        "confirmada": "Pago registrado. Reserva confirmada.",
        "pendiente_validacion": (
            "Comprobante recibido. La reserva se confirma cuando el empleado "
            "apruebe el pago."
        ),
    }
    return {
        "mensaje": mensajes.get(pago["estado_pago"], "Pago registrado."),
        "id_pago": pago["id_pago"],
        "id_reserva": id_reserva,
        "monto_pagado": pago["monto"],
        "saldo_pendiente": saldo_final,
        "metodo_pago": metodo,
        "estado_pago": pago["estado_pago"],
        "estado_reserva": estado,
    }


# ============================================================
# ADMIN / EMPLEADO
# ============================================================
def listar_reservas_admin(fecha=None, estado=None, id_cancha=None):
    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    query = db.session.query(Reserva, Cancha, Cliente, Persona).join(
        Cancha, Reserva.id_cancha == Cancha.id_cancha
    ).join(
        Cliente, Reserva.id_cliente == Cliente.id_cliente
    ).join(
        Usuario, Cliente.id_usuario == Usuario.id_usuario
    ).join(
        Persona, Usuario.id_persona == Persona.id_persona
    )

    if fecha:
        query = query.filter(Reserva.fecha_reserva == _fecha(fecha, "fecha"))
    if estado:
        estado = str(estado).strip().lower()
        if estado not in ("pendiente", "confirmada", "cancelada", "completada", "expirada"):
            raise ValueError("Estado inválido.")
        query = query.filter(Reserva.estado_reserva == estado)
    if id_cancha:
        query = query.filter(Reserva.id_cancha == int(id_cancha))

    rows = query.order_by(Reserva.fecha_reserva.desc(), Reserva.hora_inicio.desc()).all()

    return [
        {
            "id_reserva": r.id_reserva,
            "cancha": c.nombre_cancha,
            "id_cancha": c.id_cancha,
            "cliente": f"{p.nombre} {p.apellido}",
            "id_cliente": cl.id_cliente,
            "fecha": str(r.fecha_reserva),
            "hora_inicio": str(r.hora_inicio)[:5],
            "hora_fin": str(r.hora_fin)[:5],
            "duracion": str(r.duracion) if r.duracion else None,
            "estado": r.estado_reserva,
            "monto_total": float(r.monto_total) if r.monto_total is not None else None,
            "expira_en": r.expira_en.isoformat() if r.expira_en else None,
            "canal_origen": r.canal_origen,
            "motivo_cancelacion": r.motivo_cancelacion,
        }
        for r, c, cl, p in rows
    ]


def cancelar_reserva_admin(id_reserva, motivo=None, id_usuario=None):
    """Cancelacion administrativa: genera las devoluciones por el flujo de Pagos."""
    from services import pagos_service

    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    reserva = db.session.get(Reserva, id_reserva)
    if not reserva:
        raise ValueError("Reserva no encontrada.")
    if reserva.estado_reserva in ESTADOS_TERMINALES:
        raise ValueError(f"No se puede cancelar una reserva en estado '{reserva.estado_reserva}'.")

    pagos_aprobados = Pago.query.filter(
        Pago.id_reserva == id_reserva, Pago.estado_pago == ESTADO_APROBADO
    ).all()
    total_pagado = round(sum(float(p.monto) for p in pagos_aprobados), 2)

    solicitudes = 0
    for pago in pagos_aprobados:
        a_devolver = float(pago.saldo_restante)
        if a_devolver <= 0:
            continue
        pagos_service._preparar_solicitud_devolucion(
            pago.id_pago,
            motivo or "Cancelación administrativa",
            a_devolver,
        )
        pagos_service._historial_reserva(
            id_reserva,
            "devolucion_solicitada",
            f"Devolución de Bs {a_devolver} por cancelación administrativa.",
            id_usuario,
        )
        solicitudes += 1

    reserva.estado_reserva = "cancelada"
    reserva.motivo_cancelacion = motivo or "Cancelada por administración"

    _registrar_historial(
        id_reserva,
        "cancelacion_admin",
        f"Cancelada por administración. Motivo: {reserva.motivo_cancelacion}. "
        f"Pago aprobado por devolver: {total_pagado}",
        id_usuario=id_usuario,
    )
    db.session.commit()
    # Avisos de cancelacion: al cliente y a los administradores.
    _notificar("avisar_cancelacion", reserva)
    _notificar("avisar_administradores", "nueva_cancelacion", reserva)

    return {
        "mensaje": (
            "Reserva cancelada por administración. "
            + f"Se registraron {solicitudes} solicitud(es) de devolución."
        ),
        "id_reserva": reserva.id_reserva,
        "motivo": reserva.motivo_cancelacion,
        "total_pagado": total_pagado,
        "solicitudes_devolucion": solicitudes,
    }


def modificar_reserva_admin(id_reserva, datos, id_usuario=None):
    """Modificar (empleado/admin): solo Confirmadas o Pendientes y futuras.

    Revalida todas las reglas y recalcula el monto, generando la diferencia
    a pagar o devolver.
    """
    expirar_reservas_vencidas()
    completar_reservas_pasadas()

    reserva = db.session.get(Reserva, id_reserva)
    if not reserva:
        raise ValueError("Reserva no encontrada.")
    if reserva.estado_reserva in ESTADOS_TERMINALES:
        raise ValueError(f"No se puede modificar una reserva en estado '{reserva.estado_reserva}'.")

    # Solo futuras.
    hoy = datetime.now().date()
    if reserva.fecha_reserva < hoy:
        raise ValueError("Solo se pueden modificar reservas futuras.")

    try:
        id_cancha = int(datos.get("id_cancha", reserva.id_cancha))
    except (TypeError, ValueError):
        raise ValueError("id_cancha inválido.")

    nueva_fecha = _fecha(datos.get("fecha_reserva"))
    nueva_hora = _hora(datos.get("hora_inicio"))

    duracion_h = None
    if datos.get("duracion") not in (None, ""):
        duracion_h = float(datos["duracion"])
    nueva_hora_fin, duracion_h = _calcular_duracion(nueva_fecha, nueva_hora, datos, duracion_h)
    if duracion_h <= 0 or duracion_h > HORAS_MAX_RESERVA:
        raise ValueError("La duración debe ser entre 1 y 4 horas.")

    # Revalida TODO el conjunto de reglas de negocio, excluyendo esta reserva.
    cancha_nueva = _validaciones_reserva(
        nueva_fecha, nueva_hora, nueva_hora_fin, duracion_h, id_cancha,
        excluir_id=id_reserva,
    )

    monto_anterior = float(reserva.monto_total) if reserva.monto_total is not None else 0.0
    nuevo_monto = _calcular_monto(cancha_nueva, nueva_fecha, nueva_hora, duracion_h)
    diferencia = round(nuevo_monto - monto_anterior, 2)

    # Se capturan los valores previos para el historial antes de sobrescribir.
    detalle = (
        f"Cancha {reserva.id_cancha}->{id_cancha}, "
        f"fecha {reserva.fecha_reserva}->{nueva_fecha}, "
        f"hora {str(reserva.hora_inicio)[:5]}->{nueva_hora.strftime('%H:%M')}, "
        f"monto {monto_anterior}->{nuevo_monto}"
    )

    reserva.id_cancha = id_cancha
    reserva.fecha_reserva = nueva_fecha
    reserva.hora_inicio = nueva_hora
    reserva.hora_fin = nueva_hora_fin
    reserva.duracion = timedelta(hours=duracion_h)
    reserva.monto_total = nuevo_monto
    if reserva.estado_reserva == "pendiente" and reserva.expira_en and datetime.now() > reserva.expira_en:
        reserva.estado_reserva = "expirada"
    elif reserva.estado_reserva == "pendiente":
        # La modification reactiva el límite de pago de una reserva pendiente.
        reserva.expira_en = datetime.now() + timedelta(minutes=MINUTOS_PARA_PAGAR)

    _registrar_historial(id_reserva, "modificacion", detalle, id_usuario=id_usuario)
    db.session.commit()
    # Avisos de modificacion: al cliente y a los administradores.
    if reserva.estado_reserva in ESTADOS_ACTIVOS:
        _notificar("avisar_modificacion", reserva)
        _notificar("avisar_administradores", "nueva_modificacion", reserva)

    return {
        "mensaje": "Reserva modificada exitosamente",
        "id_reserva": reserva.id_reserva,
        "monto_anterior": monto_anterior,
        "nuevo_monto": nuevo_monto,
        "diferencia": diferencia,
        "a_pagar": diferencia if diferencia > 0 else 0.0,
        "a_devolver": abs(diferencia) if diferencia < 0 else 0.0,
        "nueva_fecha": str(reserva.fecha_reserva),
        "nueva_hora_inicio": str(reserva.hora_inicio)[:5],
        "nueva_hora_fin": str(reserva.hora_fin)[:5],
        "nueva_cancha": cancha_nueva.nombre_cancha,
        "id_cancha": cancha_nueva.id_cancha,
    }


# ============================================================
# CLIENTES
# ============================================================
def listar_clientes():
    filas = db.session.query(Cliente, Persona).join(
        Usuario, Cliente.id_usuario == Usuario.id_usuario
    ).join(Persona, Usuario.id_persona == Persona.id_persona).all()

    return [
        {
            "id_cliente": c.id_cliente,
            "nombre_completo": f"{p.nombre} {p.apellido}".strip(),
            "ci": p.ci,
            "email": p.email,
        }
        for c, p in filas
    ]


def obtener_id_cliente_actual(usuario):
    if usuario is None:
        raise ValueError("No autenticado.")
    cliente = Cliente.query.filter_by(id_usuario=usuario.id_usuario).first()
    if not cliente:
        raise ValueError("El usuario actual no está registrado como cliente.")
    return cliente.id_cliente


def crear_cliente(datos):
    nombre_in = (datos.get("nombre") or "").strip()
    apellido_in = datos.get("apellido")
    ci = (datos.get("ci") or "").strip()
    celular = (datos.get("celular") or "").strip() or None
    email = (datos.get("email") or "").strip().lower() or None
    username = (datos.get("username") or "").strip()
    contrasena = datos.get("contrasena") or datos.get("password") or ""

    if not nombre_in or not ci or not username or not contrasena:
        raise ValueError("Nombre, CI, username y contraseña son obligatorios.")
    if len(contrasena) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    if email and "@" not in email:
        raise ValueError("email inválido.")

    nombre, apellido = _split_nombre(nombre_in, apellido_in)

    try:
        ci = validar_ci(ci, obligatorio=True)
        celular = validar_celular(celular)
        validar_password(contrasena)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    if Persona.query.filter(Persona.ci == ci).first():
        raise ValueError(f"Ya existe una persona con CI '{ci}'.")
    if email and Persona.query.filter(Persona.email.ilike(email)).first():
        raise ValueError("Ese email ya está registrado.")
    if Usuario.query.filter(Usuario.username.ilike(username)).first():
        raise ValueError(f"Ya existe un usuario con username '{username}'.")

    persona = Persona(
        nombre=nombre,
        apellido=apellido,
        ci=ci,
        celular=celular,
        email=email,
    )
    db.session.add(persona)
    db.session.flush()

    usuario = Usuario(
        username=username,
        contrasena=hash_password(contrasena),
        rol="cliente",
        id_persona=persona.id_persona,
    )
    db.session.add(usuario)
    db.session.flush()

    cliente = Cliente(
        id_usuario=usuario.id_usuario,
        fecha_afiliacion=datetime.now().date(),
    )
    db.session.add(cliente)
    db.session.commit()

    return {
        "mensaje": "Cliente registrado exitosamente.",
        "id_cliente": cliente.id_cliente,
        "nombre_completo": f"{persona.nombre} {persona.apellido}".strip(),
        "ci": persona.ci,
        "email": persona.email,
        "username": usuario.username,
    }


# ============================================================
# HISTORIAL DE RESERVAS
# ============================================================
def listar_historial_reserva(id_reserva):
    """Historial de auditoría de una reserva (solo staff)."""
    if not db.session.get(Reserva, id_reserva):
        raise ValueError("Reserva no encontrada.")
    registros = HistorialReserva.query.filter_by(id_reserva=id_reserva).order_by(
        HistorialReserva.id_historial.asc()
    ).all()
    return [
        {
            "id_historial": h.id_historial,
            "fecha": h.fecha.isoformat() if h.fecha else None,
            "tipo": h.tipo_cambio,
            "tipo_cambio": h.tipo_cambio,
            "detalle": h.detalle,
            "id_usuario": h.id_usuario,
        }
        for h in registros
    ]


# ============================================================
# BLOQUEOS
# ============================================================
def listar_bloqueos(activos_only=True):
    query = db.session.query(Bloqueo, Cancha).join(
        Cancha, Bloqueo.id_cancha == Cancha.id_cancha
    )
    if activos_only:
        query = query.filter(Bloqueo.estado == "activo")
    filas = query.order_by(Bloqueo.fecha_inicio.desc()).all()

    return [
        {
            "id_bloqueo": b.id_bloqueo,
            "cancha": c.nombre_cancha,
            "id_cancha": c.id_cancha,
            "fecha_inicio": str(b.fecha_inicio),
            "fecha_fin": str(b.fecha_fin),
            "hora_inicio": str(b.hora_inicio)[:5],
            "hora_fin": str(b.hora_fin)[:5],
            "motivo": b.motivo,
            "estado": b.estado,
        }
        for b, c in filas
    ]


def crear_bloqueo(datos, id_usuario=None):
    try:
        id_cancha = int(datos["id_cancha"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("id_cancha es obligatorio.")
    # El id_administrador se toma del usuario autenticado (no del body).
    if id_usuario is None:
        raise ValueError("No se pudo determinar el administrador autenticado.")
    id_administrador = int(id_usuario)

    fecha_inicio = _fecha(datos.get("fecha_inicio"), "fecha_inicio")
    fecha_fin = _fecha(datos.get("fecha_fin"), "fecha_fin")
    hora_inicio = _hora(datos.get("hora_inicio"), "hora_inicio")
    hora_fin = _hora(datos.get("hora_fin"), "hora_fin")
    motivo = str(datos.get("motivo") or "").strip()

    if fecha_fin < fecha_inicio:
        raise ValueError("La fecha fin no puede ser antes que la fecha inicio.")
    if hora_fin <= hora_inicio:
        raise ValueError("La hora fin debe ser mayor que la hora inicio.")
    if not motivo:
        raise ValueError("El motivo del bloqueo es obligatorio.")

    ok, err = validar_horario(hora_inicio, hora_fin)
    if not ok:
        raise ValueError(err)

    if not db.session.get(Cancha, id_cancha):
        raise ValueError("Cancha no encontrada.")
    if not db.session.get(Administrador, id_administrador):
        raise ValueError("El administrador indicado no existe.")

    nuevo = Bloqueo(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        motivo=motivo,
        estado="activo",
        id_cancha=id_cancha,
        id_administrador=id_administrador,
    )
    db.session.add(nuevo)
    db.session.commit()

    return {"mensaje": "Bloqueo registrado exitosamente", "id_bloqueo": nuevo.id_bloqueo}


def eliminar_bloqueo(id_bloqueo):
    bloqueo = db.session.get(Bloqueo, id_bloqueo)
    if not bloqueo:
        raise ValueError("Bloqueo no encontrado.")
    bloqueo.estado = "inactivo"
    db.session.commit()
    return {"mensaje": "Bloqueo desactivado exitosamente", "id_bloqueo": bloqueo.id_bloqueo}


# ============================================================
# CRUD CANCHAS (ADMIN)
# ============================================================
def _registrar_cambio_estado_cancha(cancha, nuevo_estado, motivo=None, id_usuario=None):
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


def _registrar_cambio_precio_cancha(cancha, nuevo_precio, id_usuario=None):
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


def admin_crear_cancha(datos, id_usuario=None):
    nombre = (datos.get("nombre_cancha") or "").strip()
    tipo_deporte = (datos.get("tipo_deporte") or "").strip()
    precio = datos.get("precio_hora")
    try:
        precio = float(precio)
    except (TypeError, ValueError):
        raise ValueError("precio_hora debe ser un número válido.")
    if precio <= 0:
        raise ValueError("El precio por hora debe ser mayor a 0.")

    if not nombre or not tipo_deporte:
        raise ValueError("Nombre y tipo de deporte son obligatorios.")

    try:
        id_categoria = int(datos["id_categoria"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("id_categoria es obligatorio.")
    if id_usuario is None:
        raise ValueError("No se pudo determinar el administrador autenticado.")
    id_administrador = int(id_usuario)

    if not db.session.get(Categoria, id_categoria):
        raise ValueError("Categoría no encontrada.")
    if not db.session.get(Administrador, id_administrador):
        raise ValueError("El administrador indicado no existe.")

    # Estado inicial SIEMPRE DISPONIBLE según la lógica de negocio.
    estado = "disponible"

    nueva = Cancha(
        nombre_cancha=nombre,
        tipo_deporte=tipo_deporte,
        precio_hora=precio,
        techada=bool(datos.get("techada", False)),
        ubicacion=(datos.get("ubicacion") or "").strip() or None,
        superficie=(datos.get("superficie") or "").strip() or None,
        estado=estado,
        id_categoria=id_categoria,
        id_administrador=id_administrador,
        imagen_url=(datos.get("imagen_url") or "").strip() or None,
        # Horario general por defecto: sin el la cancha no tendria slots.
        horario_apertura=HORA_APERTURA,
        horario_cierre=HORA_CIERRE,
    )
    db.session.add(nueva)
    db.session.commit()

    return {"mensaje": "Cancha creada exitosamente", "id_cancha": nueva.id_cancha}


def admin_editar_cancha(id_cancha, datos, id_usuario=None):
    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")

    if datos.get("nombre_cancha") is not None:
        nombre = str(datos["nombre_cancha"]).strip()
        if not nombre:
            raise ValueError("El nombre no puede estar vacío.")
        cancha.nombre_cancha = nombre

    if datos.get("tipo_deporte") is not None:
        tipo_deporte = str(datos["tipo_deporte"]).strip()
        if not tipo_deporte:
            raise ValueError("El tipo de deporte no puede estar vacío.")
        cancha.tipo_deporte = tipo_deporte

    if "precio_hora" in datos:
        precio = float(datos["precio_hora"])
        if precio <= 0:
            raise ValueError("El precio por hora debe ser mayor a 0.")
        _registrar_cambio_precio_cancha(cancha, precio, id_usuario)
        cancha.precio_hora = precio

    if "techada" in datos:
        cancha.techada = bool(datos["techada"])

    if "ubicacion" in datos:
        cancha.ubicacion = str(datos["ubicacion"]).strip() or None

    if "superficie" in datos:
        cancha.superficie = str(datos["superficie"]).strip() or None

    if "estado" in datos:
        estado = str(datos["estado"]).strip().lower()
        estado = ESTADOS_ALIAS_CANCHA.get(estado, estado)
        if estado == "ocupada":
            raise ValueError(
                "'ocupada' no se asigna a mano: se calcula cuando la cancha "
                "tiene una reserva activa ahora."
            )
        if estado not in ESTADOS_VALIDOS_CANCHA:
            raise ValueError("Estado inválido. Use: disponible, mantenimiento o inactivo.")
        _registrar_cambio_estado_cancha(cancha, estado, datos.get("motivo"), id_usuario)
        cancha.estado = estado

    if "id_categoria" in datos:
        id_categoria = int(datos["id_categoria"])
        if not db.session.get(Categoria, id_categoria):
            raise ValueError("Categoría no encontrada.")
        cancha.id_categoria = id_categoria

    if "id_administrador" in datos:
        id_administrador = int(datos["id_administrador"])
        if not db.session.get(Administrador, id_administrador):
            raise ValueError("El administrador indicado no existe.")
        cancha.id_administrador = id_administrador

    if "imagen_url" in datos:
        cancha.imagen_url = str(datos["imagen_url"]).strip() or None

    if datos.get("horario_apertura"):
        cancha.horario_apertura = _hora(datos["horario_apertura"], "horario_apertura")
    if datos.get("horario_cierre"):
        cancha.horario_cierre = _hora(datos["horario_cierre"], "horario_cierre")
    if "dias_atencion" in datos:
        dias = datos["dias_atencion"]
        cancha.dias_atencion = (dias.strip() or None) if isinstance(dias, str) else None

    if cancha.horario_apertura and cancha.horario_cierre:
        if cancha.horario_cierre <= cancha.horario_apertura:
            raise ValueError("El horario de cierre debe ser posterior al de apertura.")
    else:
        # Nunca dejar la cancha sin horario general (respaldo de los dias).
        cancha.horario_apertura = HORA_APERTURA
        cancha.horario_cierre = HORA_CIERRE

    db.session.commit()
    return {"mensaje": "Cancha actualizada", "id_cancha": cancha.id_cancha}


def admin_eliminar_cancha(id_cancha, id_usuario=None):
    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")

    reservas = Reserva.query.filter_by(id_cancha=id_cancha).count()
    eventos = Evento.query.filter_by(id_cancha=id_cancha).count()

    # Si tiene reservas (cualquiera) o eventos, NO se borra físicamente:
    # se sugiere/ejecuta la desactivación (inactivo) con bitácora.
    if reservas > 0 or eventos > 0:
        motivo = f"Eliminación rechazada: {reservas} reserva(s) y {eventos} evento(s). Se desactiva."
        if cancha.estado != "inactivo":
            _registrar_cambio_estado_cancha(cancha, "inactivo", motivo, id_usuario)
            cancha.estado = "inactivo"
            db.session.commit()
        return {
            "mensaje": (
                "La cancha tiene reservas o eventos asociados. No se puede borrar; "
                "se desactivó (inactiva) para no afectar el historial."
            ),
            "desactivada": True,
        }

    db.session.delete(cancha)
    db.session.commit()
    return {"mensaje": "Cancha eliminada", "desactivada": False}


# ============================================================
# CRUD CATEGORÍAS (ADMIN)
# ============================================================
def admin_crear_categoria(datos):
    nombre = (datos.get("nombre") or "").strip()
    descripcion = (datos.get("descripcion") or "").strip() or None
    if not nombre:
        raise ValueError("El nombre es obligatorio.")
    if Categoria.query.filter(Categoria.nombre.ilike(nombre)).first():
        raise ValueError(f"Ya existe una categoría '{nombre}'.")

    nueva = Categoria(nombre=nombre, descripcion=descripcion)
    db.session.add(nueva)
    db.session.commit()
    return {"mensaje": "Categoría creada exitosamente", "id_categoria": nueva.id_categoria}


def admin_editar_categoria(id_categoria, datos):
    cat = db.session.get(Categoria, id_categoria)
    if not cat:
        raise ValueError("Categoría no encontrada.")

    nombre = (datos.get("nombre") or "").strip()
    descripcion = (datos.get("descripcion") or "").strip() or None
    if not nombre:
        raise ValueError("El nombre es obligatorio.")

    existente = Categoria.query.filter(Categoria.nombre.ilike(nombre)).first()
    if existente and existente.id_categoria != id_categoria:
        raise ValueError("Ya existe otra categoría con ese nombre.")

    cat.nombre = nombre
    cat.descripcion = descripcion
    db.session.commit()
    return {"mensaje": "Categoría actualizada", "id_categoria": cat.id_categoria}


def admin_eliminar_categoria(id_categoria):
    cat = db.session.get(Categoria, id_categoria)
    if not cat:
        raise ValueError("Categoría no encontrada.")
    if Cancha.query.filter_by(id_categoria=id_categoria).count() > 0:
        raise ValueError("No se puede eliminar: hay canchas con esta categoría.")

    db.session.delete(cat)
    db.session.commit()
    return {"mensaje": "Categoría eliminada"}