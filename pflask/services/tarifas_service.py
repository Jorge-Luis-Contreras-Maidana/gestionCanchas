"""Tarifas por franja y horarios de atención por día.

Reglas:
- Prioridad de aplicación: fin_semana > nocturna > normal.
- Dentro de una franja gana la más específica: la que fija un dia_semana
  concreto sobre la que aplica a todos los días, y la ventana horaria más
  estrecha sobre la más amplia.
- Si la cancha no tiene filas en horario_cancha, se usa el horario general
  (cancha.horario_apertura / horario_cierre) los 7 días.
- Si no hay tarifa configurada, se cae a cancha.precio_hora.
"""
from datetime import datetime, date, time, timedelta

from extensions import db
from models.cancha import Cancha
from models.tarifa_cancha import TarifaCancha, HistorialTarifaCancha, DIAS
from models.horario_cancha import HorarioCancha

HORA_APERTURA_UI = time(6, 0)
HORA_CIERRE_UI = time(23, 0)
TIPOS_TARIFA = ("normal", "nocturna", "fin_semana")
FIN_DE_SEMANA = (5, 6)
PRIORIDAD_TIPO = {"fin_semana": 3, "nocturna": 2, "normal": 1}

#: Horario general de la cancha cuando no tiene uno configurado. Sin este
#: fallback una cancha sin horario_apertura/horario_cierre no tendria ningun
#: slot reservable y el administrador no podria corregirlo desde la pantalla
#: de horarios (los campos llegan vacios y deshabilitados).
HORARIO_GENERAL_POR_DEFECTO = (HORA_APERTURA_UI, HORA_CIERRE_UI)

# Defaults usados por la UI de administracion.
DEFAULT_FRANJAS = {
    "normal": (time(6, 0), time(18, 0)),
    "nocturna": (time(18, 0), time(23, 0)),
    "fin_semana": (HORA_APERTURA_UI, HORA_CIERRE_UI),
}


# ============================================================
# HORARIOS POR DIA
# ============================================================
def horario_general(cancha):
    """(apertura, cierre) de la cancha.

    Si la cancha no tiene horario general propio se usa el horario de
    atencion por defecto (06:00 a 23:00) para que siempre tenga slots.
    """
    if cancha is None:
        return HORARIO_GENERAL_POR_DEFECTO
    if cancha.horario_apertura and cancha.horario_cierre:
        return cancha.horario_apertura, cancha.horario_cierre
    return HORARIO_GENERAL_POR_DEFECTO


def obtener_horario_dia(id_cancha, dia_semana):
    """Horario de una cancha para un dia. None = no opera ese dia.

    El fallback al horario general solo aplica cuando el dia no tiene fila.
    Una fila existente pero inactiva significa "cancha cerrada ese dia".
    """
    fila = HorarioCancha.query.filter_by(
        id_cancha=id_cancha, dia_semana=dia_semana
    ).first()
    if fila:
        if not fila.activo:
            return None
        return fila.hora_apertura, fila.hora_cierre

    # Sin configuracion por dia -> horario general de la cancha.
    cancha = db.session.get(Cancha, id_cancha)
    return horario_general(cancha)


def listar_horarios(id_cancha):
    """Los 7 dias de la cancha, usando el general como fallback."""
    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")
    filas = {
        h.dia_semana: h
        for h in HorarioCancha.query.filter_by(id_cancha=id_cancha).all()
    }
    apertura_general, cierre_general = horario_general(cancha)
    resultado = []
    for dia in range(7):
        fila = filas.get(dia)
        if fila:
            resultado.append(fila.to_dict())
        else:
            resultado.append({
                "id_horario": None,
                "id_cancha": id_cancha,
                "dia_semana": dia,
                "dia_nombre": DIAS[dia],
                "hora_apertura": apertura_general.strftime("%H:%M"),
                "hora_cierre": cierre_general.strftime("%H:%M"),
                "activo": True,
                "por_defecto": True,
            })
    return resultado


def guardar_horario(id_cancha, dia_semana, apertura, cierre, activo=True):
    """Alta o actualizacion del horario de un dia (upsert)."""
    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")
    if not 0 <= dia_semana <= 6:
        raise ValueError("dia_semana debe estar entre 0 (lunes) y 6 (domingo).")
    if apertura >= cierre:
        raise ValueError("La hora de cierre debe ser posterior a la de apertura.")
    if apertura < HORA_APERTURA_UI or cierre > HORA_CIERRE_UI:
        raise ValueError("El horario debe estar dentro del atención (06:00 a 23:00).")

    fila = HorarioCancha.query.filter_by(
        id_cancha=id_cancha, dia_semana=dia_semana
    ).first()
    if fila is None:
        fila = HorarioCancha(
            id_cancha=id_cancha, dia_semana=dia_semana,
            hora_apertura=apertura, hora_cierre=cierre, activo=True,
        )
        db.session.add(fila)
    else:
        fila.hora_apertura = apertura
        fila.hora_cierre = cierre
        fila.activo = bool(activo)
    db.session.commit()
    return fila.to_dict()


def aplicar_horarios(id_cancha, dias, id_usuario=None):
    """Reemplaza los 7 dias de una cancha de una vez (formulario admin)."""
    if not isinstance(dias, (list, tuple)) or not dias:
        raise ValueError("Se debe enviar la lista de horarios por día.")

    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")

    for item in dias:
        try:
            dia = int(item.get("dia_semana"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Cada horario debe tener 'dia_semana' (0-6).")
        if not 0 <= dia <= 6:
            raise ValueError("'dia_semana' debe estar entre 0 (lunes) y 6 (domingo).")
        activo = bool(item.get("activo", True))
        fila = HorarioCancha.query.filter_by(
            id_cancha=id_cancha, dia_semana=dia
        ).first()

        if not activo:
            # El dia queda cerrado: se necesita una fila inactiva para que
            # obtener_horario_dia() devuelva None y no caiga al horario general.
            apertura_general, cierre_general = horario_general(cancha)
            if fila is None:
                db.session.add(HorarioCancha(
                    id_cancha=id_cancha, dia_semana=dia,
                    hora_apertura=apertura_general,
                    hora_cierre=cierre_general,
                    activo=False,
                ))
            else:
                fila.activo = False
            continue

        if not item.get("hora_apertura") or not item.get("hora_cierre"):
            raise ValueError(f"Falta la hora de apertura o cierre del {DIAS[dia]}.")
        guardar_horario(
            id_cancha, dia, _hora(item["hora_apertura"]), _hora(item["hora_cierre"])
        )
    db.session.commit()
    return listar_horarios(id_cancha)


def _hora(valor):
    if isinstance(valor, time):
        return valor
    try:
        h, m = str(valor).strip().split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        raise ValueError("Las horas deben tener el formato HH:MM.")


# ============================================================
# TARIFAS
# ============================================================
def _candidatas(id_cancha, dia_semana, hora):
    """Tarifas que podrian aplicar, ya ordenadas por prioridad."""
    tarifas = TarifaCancha.query.filter_by(id_cancha=id_cancha, activo=True).all()
    aplicables = []
    for t in tarifas:
        if t.dia_semana is not None and t.dia_semana != dia_semana:
            continue
        if not (t.hora_inicio <= hora < t.hora_fin):
            continue
        ancho = (
            datetime.combine(date(2000, 1, 1), t.hora_fin)
            - datetime.combine(date(2000, 1, 1), t.hora_inicio)
        ).seconds
        aplicables.append(
            (
                -PRIORIDAD_TIPO.get(t.tipo_tarifa, 0),  # tipo primero
                0 if t.dia_semana is not None else 1,  # dia concreto gana
                ancho,                                    # ventana estrecha gana
                t,
            )
        )
    aplicables.sort(key=lambda x: (x[0], x[1], x[2]))
    return [x[3] for x in aplicables]


def obtener_tarifa_por_hora(cancha, fecha, hora_inicio):
    """Precio/hora aplicable. Devuelve None si no hay tarifa configurada."""
    if cancha is None:
        return None
    id_cancha = getattr(cancha, "id_cancha", cancha)
    candidatas = _candidatas(id_cancha, fecha.weekday(), hora_inicio)
    if candidatas:
        return float(candidatas[0].precio_hora)
    return None


def obtener_tarifa_hora(cancha, fecha, hora_inicio):
    """Precio/hora aplicable con fallback a cancha.precio_hora."""
    precio = obtener_tarifa_por_hora(cancha, fecha, hora_inicio)
    if precio is not None:
        return precio
    return float(cancha.precio_hora)


def desglose_monto(cancha, fecha, hora_inicio, duracion_h):
    """Divide la reserva en franjas y suma cada una a su tarifa.

    Permite que una reserva que cruza de una franja a otra (p.ej. 17:00-19:00,
    donde 17-18 es normal y 18-19 es nocturna) se cobre bien.
    """
    inicio = datetime.combine(fecha, hora_inicio)
    restante = timedelta(hours=float(duracion_h))
    partes = []
    total = 0.0
    cursor = inicio
    while restante > timedelta(0):
        paso = min(restante, timedelta(hours=1))
        fin = cursor + paso
        precio = obtener_tarifa_hora(cancha, fecha, cursor.time())
        importe = round(precio * (paso.total_seconds() / 3600), 2)
        total += importe
        partes.append({
            "hora_inicio": cursor.strftime("%H:%M"),
            "hora_fin": fin.strftime("%H:%M"),
            "horas": round(paso.total_seconds() / 3600, 2),
            "precio_hora": precio,
            "importe": importe,
        })
        cursor = fin
        restante -= paso
    return round(total, 2), partes


def listar_tarifas(id_cancha, solo_activas=False):
    cancha = db.session.get(Cancha, id_cancha)
    if not cancha:
        raise ValueError("Cancha no encontrada.")
    query = TarifaCancha.query.filter_by(id_cancha=id_cancha)
    if solo_activas:
        query = query.filter_by(activo=True)
    filas = query.order_by(
        TarifaCancha.tipo_tarifa.asc(),
        TarifaCancha.dia_semana.asc().nullsfirst(),
        TarifaCancha.hora_inicio.asc(),
    ).all()
    return [t.to_dict() for t in filas]


def listar_todas_tarifas(solo_activas=False):
    """Vista publica: canchas disponibles con su tarifa vigente."""
    canchas = Cancha.query.filter_by(estado="disponible").order_by(Cancha.id_cancha).all()
    resultado = []
    for cancha in canchas:
        hoy = date.today()
        tarifas = TarifaCancha.query.filter_by(id_cancha= cancha.id_cancha, activo=True).all()
        if solo_activas and not tarifas:
            continue
        resultado.append({
            "id_cancha": cancha.id_cancha,
            "nombre": cancha.nombre_cancha,
            "precio_hora": float(cancha.precio_hora),
            "tarifas": [t.to_dict() for t in tarifas],
        })
    return resultado


def _validar_tarifa(id_cancha, tipo, dia, inicio, fin, precio, excluir_id=None):
    """Reglas comunes al crear y al actualizar una tarifa."""
    if tipo not in TIPOS_TARIFA:
        raise ValueError("tipo_tarifa debe ser: normal, nocturna o fin_semana.")
    if dia is not None and not 0 <= dia <= 6:
        raise ValueError("dia_semana debe estar entre 0 (lunes) y 6 (domingo).")
    if tipo == "fin_semana" and dia is not None and dia not in FIN_DE_SEMANA:
        raise ValueError("La tarifa de fin de semana solo aplica a sábado (5) o domingo (6).")
    if fin <= inicio:
        raise ValueError("La hora de fin debe ser posterior a la de inicio.")
    if inicio < HORA_APERTURA_UI or fin > HORA_CIERRE_UI:
        raise ValueError("La tarifa debe estar dentro del horario de atención (06:00 a 23:00).")
    if precio <= 0:
        raise ValueError("El precio por hora debe ser mayor a 0.")

    # No se permite superponer tarifas del mismo tipo/dia.
    for existente in TarifaCancha.query.filter_by(
        id_cancha=id_cancha, tipo_tarifa=tipo, activo=True
    ).all():
        if excluir_id and existente.id_tarifa == excluir_id:
            continue
        if existente.dia_semana != dia:
            continue
        if inicio < existente.hora_fin and fin > existente.hora_inicio:
            raise ValueError(
                f"La franja {inicio.strftime('%H:%M')}-{fin.strftime('%H:%M')} se "
                f"solapa con otra tarifa {tipo} existente "
                f"({existente.hora_inicio.strftime('%H:%M')}-"
                f"{existente.hora_fin.strftime('%H:%M')})."
            )


def crear_tarifa(datos, id_usuario=None):
    cancha = db.session.get(Cancha, _int(datos.get("id_cancha"), "id_cancha"))
    if not cancha:
        raise ValueError("Cancha no encontrada.")

    tipo = (datos.get("tipo_tarifa") or "").strip().lower()
    dia = datos.get("dia_semana")
    dia = None if dia in (None, "", "todos") else _int(dia, "dia_semana")

    inicio = _hora(datos.get("hora_inicio") or _fmt(DEFAULT_FRANJAS[tipo][0]))
    fin = _hora(datos.get("hora_fin") or _fmt(DEFAULT_FRANJAS[tipo][1]))
    try:
        precio = float(datos.get("precio_hora"))
    except (TypeError, ValueError):
        raise ValueError("precio_hora debe ser un número válido.")

    _validar_tarifa(cancha.id_cancha, tipo, dia, inicio, fin, precio)

    tarifa = TarifaCancha(
        id_cancha=cancha.id_cancha, tipo_tarifa=tipo, dia_semana=dia,
        hora_inicio=inicio, hora_fin=fin, precio_hora=precio,
        activo=True, id_usuario=id_usuario, fecha=datetime.now(),
    )
    db.session.add(tarifa)
    db.session.flush()
    _bitacora(cancha.id_cancha, tarifa.id_tarifa, None, tipo, None, dia, None, precio,
              datos.get("motivo"), id_usuario)
    db.session.commit()
    return tarifa.to_dict()


def actualizar_tarifa(id_tarifa, datos, id_usuario=None):
    tarifa = db.session.get(TarifaCancha, id_tarifa)
    if not tarifa:
        raise ValueError("Tarifa no encontrada.")

    anterior = (tarifa.tipo_tarifa, tarifa.dia_semana, float(tarifa.precio_hora))

    # Se calculan los valores nuevos y se validan ANTES de tocar el objeto:
    # si no, una peticion rechazada dejaria la sesion con datos invalidos.
    tipo = tarifa.tipo_tarifa
    if "tipo_tarifa" in datos and datos["tipo_tarifa"]:
        tipo = str(datos["tipo_tarifa"]).strip().lower()
    if "dia_semana" in datos:
        dia = datos["dia_semana"]
        dia = None if dia in (None, "", "todos") else _int(dia, "dia_semana")
    else:
        dia = tarifa.dia_semana
    inicio = _hora(datos["hora_inicio"]) if datos.get("hora_inicio") else tarifa.hora_inicio
    fin = _hora(datos["hora_fin"]) if datos.get("hora_fin") else tarifa.hora_fin
    if "precio_hora" in datos and datos["precio_hora"] not in (None, ""):
        try:
            precio = float(datos["precio_hora"])
        except (TypeError, ValueError):
            raise ValueError("precio_hora debe ser un número válido.")
    else:
        precio = float(tarifa.precio_hora)

    # Limites, tipo, dia y solapes del resultado completo.
    _validar_tarifa(tarifa.id_cancha, tipo, dia, inicio, fin, precio,
                    excluir_id=tarifa.id_tarifa)

    tarifa.tipo_tarifa = tipo
    tarifa.dia_semana = dia
    tarifa.hora_inicio = inicio
    tarifa.hora_fin = fin
    tarifa.precio_hora = precio
    if "activo" in datos:
        tarifa.activo = bool(datos["activo"])

    nuevo = (tipo, dia, precio)
    if nuevo != anterior:
        _bitacora(
            tarifa.id_cancha, tarifa.id_tarifa, anterior[0], nuevo[0],
            anterior[1], nuevo[1], anterior[2], nuevo[2],
            datos.get("motivo"), id_usuario,
        )
    db.session.commit()
    return tarifa.to_dict()


def eliminar_tarifa(id_tarifa, id_usuario=None):
    tarifa = db.session.get(TarifaCancha, id_tarifa)
    if not tarifa:
        raise ValueError("Tarifa no encontrada.")
    _bitacora(
        tarifa.id_cancha, tarifa.id_tarifa, tarifa.tipo_tarifa, None,
        tarifa.dia_semana, None, float(tarifa.precio_hora), None,
        "Tarifa eliminada", id_usuario,
    )
    db.session.delete(tarifa)
    db.session.commit()
    return {"mensaje": "Tarifa eliminada."}


def eliminar_tarifas_cancha(id_cancha, id_usuario=None):
    """Borra todas las tarifas de una cancha (sirve para reiniciar el bloque)."""
    filas = TarifaCancha.query.filter_by(id_cancha=id_cancha).all()
    for t in filas:
        _bitacora(
            id_cancha, t.id_tarifa, t.tipo_tarifa, None, t.dia_semana, None,
            float(t.precio_hora), None, "Tarifas reiniciadas", id_usuario,
        )
        db.session.delete(t)
    db.session.commit()
    return {"mensaje": f"Se eliminaron {len(filas)} tarifa(s).", "eliminadas": len(filas)}


def _bitacora(id_cancha, id_tarifa, tipo_ant, tipo_nue, dia_ant, dia_nue,
              precio_ant, precio_nue, motivo, id_usuario):
    db.session.add(HistorialTarifaCancha(
        id_tarifa=id_tarifa, id_cancha=id_cancha,
        tipo_anterior=tipo_ant, tipo_nuevo=tipo_nue,
        dia_anterior=dia_ant, dia_nuevo=dia_nue,
        precio_anterior=precio_ant, precio_nuevo=precio_nue,
        motivo=(str(motivo).strip() or None) if motivo else None,
        id_usuario=id_usuario, fecha=datetime.now(),
    ))


def listar_historial_tarifas(id_cancha):
    filas = (
        HistorialTarifaCancha.query.filter_by(id_cancha=id_cancha)
        .order_by(HistorialTarifaCancha.id_historial.desc()).all()
    )

    def _accion(h):
        if h.tipo_nuevo is None and h.tipo_anterior is not None:
            return "eliminada"
        if h.tipo_anterior is None:
            return "creada"
        return "modificada"

    def _dia(valor):
        return DIAS[valor] if valor is not None else None

    return [
        {
            "id_historial": h.id_historial,
            "accion": _accion(h),
            "tipo_anterior": h.tipo_anterior,
            "tipo_nuevo": h.tipo_nuevo,
            "dia_anterior": h.dia_anterior,
            "dia_anterior_nombre": _dia(h.dia_anterior),
            "dia_nuevo": h.dia_nuevo,
            "dia_nuevo_nombre": _dia(h.dia_nuevo),
            "precio_anterior": float(h.precio_anterior) if h.precio_anterior is not None else None,
            "precio_nuevo": float(h.precio_nuevo) if h.precio_nuevo is not None else None,
            "motivo": h.motivo,
            "fecha": h.fecha.isoformat() if h.fecha else None,
        }
        for h in filas
    ]


def _int(valor, nombre):
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nombre} inválido.")


def _fmt(t):
    return t.strftime("%H:%M")
