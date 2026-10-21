import { useEffect, useState, useRef, useMemo } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import "../App.css";
import { useAuth } from '../context/AuthContext';
import { AppLayout } from '../components/layout/AppLayout';
import { imagenCanchaURL, canchasService, mensajeError, type CanchaImagen } from '../services/canchasService';
import {
  DIAS_MAX_ANTICIPACION,
  DIAS_MIN_ANTICIPACION,
  DURACION_MAX_H,
  DURACION_MIN_H,
  HORA_ATENCION_MAX,
  HORA_ATENCION_MIN,
  REQUISITOS_PASSWORD,
  aNumero,
  errorNumero,
  esNumeroValido,
  fechaReservaValida,
  horaFinPosterior,
  horasDeDuracion,
  minutosAHora,
  minutosDeHora,
  rangoFechaReserva,
  rangoFechasValido,
  textoVacio,
  validarAltaCliente,
  soloDigitos,
  soloDigitosCelular,
} from '../utils/validaciones';

// ============================================================
// INTERFACES
// ============================================================
interface Cancha {
  id: number;
  nombre: string;
  deporte: string;
  precio_hora: number;
  techada: boolean;
  estado: string;
  estado_calculado?: string;
  reserva_habilitada?: boolean;
  total_imagenes?: number;
  imagen_preview_id?: number | null;
  ubicacion?: string;
  superficie?: string;
  id_categoria?: number;
  categoria?: string;
  imagen_url?: string;
  horario_apertura?: string | null;
  horario_cierre?: string | null;
  dias_atencion?: string | null;
}

interface Reserva {
  id_reserva: number;
  cancha: string;
  id_cancha: number;
  fecha: string;
  hora_inicio: string;
  hora_fin: string;
  duracion: string;
  estado: string;
  precio_hora: number;
  monto_total?: number | null;
  expira_en?: string | null;
  canal_origen?: string;
  motivo_cancelacion: string | null;
}

interface SlotHorario {
  hora_inicio: string;
  hora_fin: string;
  disponible: boolean;
  motivo: string | null;
}

interface ReservaAdmin extends Reserva {
  cliente: string;
  id_cliente: number;
}

interface Cliente {
  id_cliente: number;
  nombre_completo: string;
  ci: string;
  email: string | null;
}

interface Bloqueo {
  id_bloqueo: number;
  cancha: string;
  id_cancha: number;
  fecha_inicio: string;
  fecha_fin: string;
  hora_inicio: string;
  hora_fin: string;
  motivo: string;
  estado: string;
}

interface Categoria {
  id_categoria: number;
  nombre: string;
  descripcion: string | null;
}

// ============================================================
// HELPERS
// ============================================================
const DURACIONES_COMUNES = [1, 1.5, 2, 2.5, 3, 4];

/** Etiquetas legibles de los estados de cancha (el backend calcula "ocupada"). */
const ETIQUETA_ESTADO_CANCHA: Record<string, string> = {
  disponible: "Disponible",
  ocupada: "Ocupada",
  mantenimiento: "Mantenimiento",
  inactivo: "Inactiva",
};

/**
 * Reglas que el backend exige en toda reserva, comprobadas antes del POST para
 * que el error caiga en el formulario y no un viaje al servidor después.
 * Regresa "" cuando todo está bien.
 */
function validaReserva(datos: { fecha: string; hora: string; duracion: unknown }): string {
  if (textoVacio(datos.fecha)) return "Selecciona la fecha de la reserva.";
  if (!fechaReservaValida(datos.fecha)) {
    return `La fecha debe estar entre ${DIAS_MIN_ANTICIPACION} y ${DIAS_MAX_ANTICIPACION} días de anticipación.`;
  }

  const duracion = aNumero(datos.duracion);
  if (!esNumeroValido(duracion, { min: DURACION_MIN_H, max: DURACION_MAX_H })) {
    return errorNumero("La duración", { min: DURACION_MIN_H, max: DURACION_MAX_H });
  }

  const inicioMin = minutosDeHora(datos.hora);
  if (!Number.isFinite(inicioMin)) return "Selecciona una hora de inicio válida.";
  if (datos.hora < HORA_ATENCION_MIN || datos.hora > HORA_ATENCION_MAX) {
    return `La hora debe estar entre las ${HORA_ATENCION_MIN} y las ${HORA_ATENCION_MAX}.`;
  }

  // hora + duración no puede pasar del cierre: el backend lo rechaza, pero solo
  // después de que el usuario llenó todo el formulario.
  const finMin = inicioMin + Math.round((duracion as number) * 60);
  if (finMin > minutosDeHora(HORA_ATENCION_MAX)) {
    return `La reserva terminaría a las ${minutosAHora(finMin)}, fuera del horario de atención (${HORA_ATENCION_MIN} a ${HORA_ATENCION_MAX}).`;
  }
  return "";
}

// ============================================================
// COMPONENTE
// ============================================================
function ReservasPage() {
  const { user } = useAuth();

  // Mapeamos el usuario del AuthContext al formato que usaba el componente
  const usuario = useMemo(() => {
  if (!user) return null;
  return {
    id_usuario: user.id_usuario || user.id || 0,
    username: user.username || '',
    rol: user.rol || user.role || '',
    id_cliente: user.id_cliente ?? null,
    id_administrador: user.id_administrador ?? null,
    id_empleado: user.id_empleado ?? null,
    nombre_completo:
      user.nombre_completo ||
      `${user.nombre || ''} ${user.apellido || ''}`.trim() ||
      user.username ||
      'Usuario',
  };
}, [user]);

  // Banderas de roles (unificadas)
  const esCliente = usuario?.rol === 'cliente';
  const esEmpleado = usuario?.rol === 'empleado';
  const esAdmin = usuario?.rol === 'admin' || usuario?.rol === 'administrador';
  const esStaff = esEmpleado || esAdmin;

  // REFS para scroll automático
  const gestionCanchasRef = useRef<HTMLDivElement>(null);
  const gestionCategoriasRef = useRef<HTMLDivElement>(null);
  const bloqueosRef = useRef<HTMLDivElement>(null);

  // GENERALES
  const [canchas, setCanchas] = useState<Cancha[]>([]);
  const [categorias, setCategorias] = useState<Categoria[]>([]);
  const [slots, setSlots] = useState<SlotHorario[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  // CLIENTE
  const [idCancha, setIdCancha] = useState("");
  const [fecha, setFecha] = useState("");
  const [hora, setHora] = useState("");
  const [duracion, setDuracion] = useState("1");
  const [mensajeReserva, setMensajeReserva] = useState<{
    texto: string;
    tipo: "success" | "error" | "info";
  } | null>(null);
  const [, setReservas] = useState<Reserva[]>([]);
  const [filtroReservas] = useState<"todas" | "vigentes">("todas");
  const [reservaPagando, setReservaPagando] = useState<Reserva | null>(null);
  const [metodoPago, setMetodoPago] = useState("efectivo");
  const [metodoReserva, setMetodoReserva] = useState("qr");
  const [modalReserva, setModalReserva] = useState(false);

  // FILTROS DEL CATÁLOGO DE CANCHAS (vista cliente)
  const [busquedaCancha, setBusquedaCancha] = useState("");
  const [filtroDeporteCancha, setFiltroDeporteCancha] = useState("");
  const [filtroEstadoCancha, setFiltroEstadoCancha] = useState("");
  const [ordenCancha, setOrdenCancha] = useState("nombre_asc");

  // EMPLEADO / ADMIN
  const [reservasAdmin, setReservasAdmin] = useState<ReservaAdmin[]>([]);
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [filtroFecha, setFiltroFecha] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("");
  const [reservaCancelandoAdmin, setReservaCancelandoAdmin] = useState<ReservaAdmin | null>(null);
  const [motivoCancelacion, setMotivoCancelacion] = useState("");

  // MODIFICAR RESERVA DESDE ADMIN/EMPLEADO
  const [reservaModificandoAdmin, setReservaModificandoAdmin] = useState<ReservaAdmin | null>(null);
  const [modAdminFecha, setModAdminFecha] = useState("");
  const [modAdminHora, setModAdminHora] = useState("");
  const [modAdminDuracion, setModAdminDuracion] = useState("1");
  const [modAdminIdCancha, setModAdminIdCancha] = useState("");

  // RESERVA PRESENCIAL
  const [modalReservaPresencial, setModalReservaPresencial] = useState(false);
  const [busquedaCliente, setBusquedaCliente] = useState("");
  const [presIdCliente, setPresIdCliente] = useState("");
  const [presIdCancha, setPresIdCancha] = useState("");
  const [presFecha, setPresFecha] = useState("");
  const [presHora, setPresHora] = useState("");
  const [presDuracion, setPresDuracion] = useState("1");
  const [presMetodoPago, setPresMetodoPago] = useState("efectivo");
  const [presMensaje, setPresMensaje] = useState<{
    texto: string;
    tipo: "success" | "error" | "info";
  } | null>(null);

  // REGISTRAR CLIENTE
  const [modalRegistrarCliente, setModalRegistrarCliente] = useState(false);
  const [regNombre, setRegNombre] = useState("");
  const [regApellido, setRegApellido] = useState("");
  const [regCi, setRegCi] = useState("");
  const [regCelular, setRegCelular] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regUsername, setRegUsername] = useState("");
  const [regContrasena, setRegContrasena] = useState("");
  const [regMensaje, setRegMensaje] = useState<{
    texto: string;
    tipo: "success" | "error" | "info";
  } | null>(null);

  // BLOQUEOS
  const [bloqueos, setBloqueos] = useState<Bloqueo[]>([]);
  const [modalBloqueo, setModalBloqueo] = useState(false);
  const [bloIdCancha, setBloIdCancha] = useState("");
  const [bloFechaInicio, setBloFechaInicio] = useState("");
  const [bloFechaFin, setBloFechaFin] = useState("");
  const [bloHoraInicio, setBloHoraInicio] = useState("");
  const [bloHoraFin, setBloHoraFin] = useState("");
  const [bloMotivo, setBloMotivo] = useState("");
  const [bloMensaje, setBloMensaje] = useState<{
    texto: string;
    tipo: "success" | "error" | "info";
  } | null>(null);

  // GESTIÓN CANCHAS
  const [verGestionCanchas, setVerGestionCanchas] = useState(false);
  const [modalCancha, setModalCancha] = useState(false);
  const [canchaEditando, setCanchaEditando] = useState<Cancha | null>(null);
  const [canFormNombre, setCanFormNombre] = useState("");
  const [canFormDeporte, setCanFormDeporte] = useState("");
  const [canFormPrecio, setCanFormPrecio] = useState("");
  const [canFormTechada, setCanFormTechada] = useState(false);
  const [canFormUbicacion, setCanFormUbicacion] = useState("");
  const [canFormSuperficie, setCanFormSuperficie] = useState("");
  const [canFormCategoria, setCanFormCategoria] = useState("");
  const [canFormEstado, setCanFormEstado] = useState("disponible");
  const [canFormMotivo, setCanFormMotivo] = useState("");
  const [canImagenes, setCanImagenes] = useState<CanchaImagen[]>([]);
  const [canFotosNuevas, setCanFotosNuevas] = useState<File[]>([]);
  const [canMensaje, setCanMensaje] = useState<{
    texto: string;
    tipo: "success" | "error" | "info";
  } | null>(null);

  // GESTIÓN CATEGORÍAS
  const [verGestionCategorias, setVerGestionCategorias] = useState(false);
  const [modalCategoria, setModalCategoria] = useState(false);
  const [catEditando, setCatEditando] = useState<Categoria | null>(null);
  const [catFormNombre, setCatFormNombre] = useState("");
  const [catFormDescripcion, setCatFormDescripcion] = useState("");
  const [catMensaje, setCatMensaje] = useState<{
    texto: string;
    tipo: "success" | "error" | "info";
  } | null>(null);

  // ============================================================
  // SCROLL AUTOMÁTICO
  // ============================================================
  useEffect(() => {
    if (verGestionCanchas && gestionCanchasRef.current) {
      setTimeout(() => gestionCanchasRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
    }
  }, [verGestionCanchas]);

  useEffect(() => {
    if (verGestionCategorias && gestionCategoriasRef.current) {
      setTimeout(() => gestionCategoriasRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
    }
  }, [verGestionCategorias]);

  // ============================================================
  // INTERCEPTOR JWT
  // ============================================================
  useEffect(() => {
    const interceptor = axios.interceptors.request.use((config) => {
      const token = localStorage.getItem('token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });
    return () => axios.interceptors.request.eject(interceptor);
  }, []);

  // ============================================================
  // CARGA INICIAL
  // ============================================================
  const cargarCanchas = () => {
    axios.get<Cancha[]>("http://127.0.0.1:5000/api/canchas")
      .then((res) => setCanchas(res.data))
      .catch(() => setError("No se pudo conectar con el backend."));
  };

  const cargarCategorias = () => {
    axios.get<Categoria[]>("http://127.0.0.1:5000/api/categorias")
      .then((res) => setCategorias(res.data))
      .catch((err) => console.error(err));
  };

  useEffect(() => {
    axios.get<Cancha[]>("http://127.0.0.1:5000/api/canchas")
      .then((res) => setCanchas(res.data))
      .catch(() => setError("No se pudo conectar con el backend. ¿Está corriendo flask run?"))
      .finally(() => setCargando(false));
    cargarCategorias();
  }, []);

  const cargarReservas = (filtro: "todas" | "vigentes" = filtroReservas) => {
    if (!usuario || !esCliente || !usuario.id_cliente) return;
    const url = filtro === "vigentes"
      ? `http://127.0.0.1:5000/api/reservas/${usuario.id_cliente}/vigentes`
      : `http://127.0.0.1:5000/api/reservas/${usuario.id_cliente}`;
    axios.get<Reserva[]>(url)
      .then((res) => setReservas(res.data))
      .catch((err) => console.error(err));
  };

  useEffect(() => {
    if (usuario && esCliente) cargarReservas(filtroReservas);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroReservas, usuario?.id_cliente]);

  // ============================================================
  // DISPONIBILIDAD DE HORARIOS
  // ============================================================
  const cargarDisponibilidad = (
    idCancha: number,
    fecha: string,
    duracion: number
  ) => {
    if (!idCancha || !fecha || !duracion) {
      setSlots([]);
      return;
    }
    axios
      .get<{ horarios: SlotHorario[] }>(
        `http://127.0.0.1:5000/api/canchas/${idCancha}/disponibilidad` +
          `?fecha=${fecha}&duracion=${duracion}`
      )
      .then((res) => setSlots(res.data.horarios || []))
      .catch(() => setSlots([]));
  };

  useEffect(() => {
    cargarDisponibilidad(
      parseInt(idCancha) || 0,
      fecha,
      parseFloat(duracion) || 1
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idCancha, fecha, duracion]);

  const cargarReservasAdmin = () => {
    const params = new URLSearchParams();
    if (filtroFecha) params.append("fecha", filtroFecha);
    if (filtroEstado) params.append("estado", filtroEstado);
    axios.get<ReservaAdmin[]>(`http://127.0.0.1:5000/api/admin/reservas?${params.toString()}`)
      .then((res) => setReservasAdmin(res.data))
      .catch((err) => console.error(err));
  };

  const cargarClientes = () => {
    axios.get<Cliente[]>("http://127.0.0.1:5000/api/clientes")
      .then((res) => setClientes(res.data))
      .catch((err) => console.error(err));
  };

  const cargarBloqueos = () => {
    axios.get<Bloqueo[]>("http://127.0.0.1:5000/api/bloqueos")
      .then((res) => setBloqueos(res.data))
      .catch((err) => console.error(err));
  };

  useEffect(() => {
    if (esStaff) {
      cargarReservasAdmin();
      cargarClientes();
    }
    cargarBloqueos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usuario?.rol, filtroFecha, filtroEstado]);

  // ============================================================
  // HELPERS
  // ============================================================
  const abrirModalReserva = (canchaId?: number) => {
    if (canchaId !== undefined) setIdCancha(String(canchaId));
    setMetodoReserva("qr");
    setMensajeReserva(null);
    setModalReserva(true);
  };

  const cerrarModalReserva = () => {
    setModalReserva(false);
    setMetodoReserva("qr");
    setMensajeReserva(null);
  };

  // ============================================================
  // ACCIONES CLIENTE
  // ============================================================
  const handleReserva = async (e: any) => {
  e.preventDefault();
  if (!usuario || !usuario.id_cliente) return;

  const falla = validaReserva({ fecha, hora, duracion });
  if (falla) {
    setMensajeReserva({ texto: `❌ ${falla}`, tipo: "error" });
    return;
  }

  if (metodoReserva === "efectivo") {
    setMensajeReserva({
      texto: "❌ No se puede reservar con efectivo: el complejo de canchas está cerrado. Elige QR, transferencia o tarjeta.",
      tipo: "error",
    });
    return;
  }

  // ✅ VALIDACIÓN PREVIA: Verificar si la cancha está bloqueada en esa fecha
  const bloqueoConflicto = bloqueos.find(
    (b) =>
      b.id_cancha === parseInt(idCancha) &&
      b.estado === 'activo' &&
      fecha >= b.fecha_inicio &&
      fecha <= b.fecha_fin
  );

  if (bloqueoConflicto) {
    setMensajeReserva({
      texto: `❌ La cancha está bloqueada por "${bloqueoConflicto.motivo}" del ${bloqueoConflicto.fecha_inicio} al ${bloqueoConflicto.fecha_fin}. Puedes reservar después del ${bloqueoConflicto.fecha_fin}.`,
      tipo: "error",
    });
    return;
  }

  // ✅ VALIDACIÓN PREVIA: el slot debe estar libre según el backend.
  if (slots.length > 0) {
    const slot = slots.find((s) => s.hora_inicio === hora);
    if (slot && !slot.disponible) {
      setMensajeReserva({
        texto: `❌ El horario ${hora} no está disponible: ${slot.motivo}. Elige otro.`,
        tipo: "error",
      });
      return;
    }
  }

  setMensajeReserva({ texto: "Procesando...", tipo: "info" });

  try {
    const response = await axios.post("http://127.0.0.1:5000/api/reservas", {
      id_cancha: parseInt(idCancha),
      id_cliente: usuario.id_cliente,
      fecha_reserva: fecha,
      hora_inicio: hora,
      duracion: parseFloat(duracion),
      metodo_pago: metodoReserva,
    });
    setMensajeReserva({
      texto: `✅ ${response.data.mensaje} Monto a pagar: Bs ${response.data.monto_total}.`,
      tipo: "success",
    });
    setMetodoPago(response.data.metodo_pago || metodoReserva);
    cargarReservas();
  } catch (err: any) {
    const msg =
      err.response?.data?.error ||
      (err.request ? "Error de red." : "Error inesperado.");
    setMensajeReserva({ texto: `❌ ${msg}`, tipo: "error" });
  }
};

  const cancelarReserva = async (id: number) => {
    if (!confirm("¿Seguro que deseas cancelar esta reserva?")) return;
    try {
      const r = await axios.put(`http://127.0.0.1:5000/api/reservas/${id}/cancelar`);
      alert(`✅ ${r.data.mensaje}`);
      cargarReservas();
    } catch (err: any) {
      alert(`❌ ${err.response?.data?.error || "Error al cancelar."}`);
    }
  };
  void cancelarReserva;

  const handlePagar = async (e: any) => {
    e.preventDefault();
    if (!reservaPagando) return;
    try {
      const r = await axios.post(`http://127.0.0.1:5000/api/reservas/${reservaPagando.id_reserva}/pagar`, {
        metodo_pago: metodoPago,
      });
      alert(`✅ ${r.data.mensaje}\nMonto pagado: Bs ${r.data.monto_pagado}`);
      setReservaPagando(null);
      cargarReservas();
    } catch (err: any) {
      alert(`❌ ${err.response?.data?.error || "Error al procesar el pago."}`);
    }
  };

  // ============================================================
  // ACCIONES ADMIN/EMPLEADO
  // ============================================================
  const handleCancelarAdmin = async (e: any) => {
    e.preventDefault();
    if (!reservaCancelandoAdmin) return;
    try {
      const r = await axios.put(`http://127.0.0.1:5000/api/admin/reservas/${reservaCancelandoAdmin.id_reserva}/cancelar-admin`, { motivo: motivoCancelacion });
      alert(`✅ ${r.data.mensaje}`);
      setReservaCancelandoAdmin(null);
      setMotivoCancelacion("");
      cargarReservasAdmin();
    } catch (err: any) {
      alert(`❌ ${err.response?.data?.error || "Error al cancelar."}`);
    }
  };

  const abrirModalModificarAdmin = (r: ReservaAdmin) => {
    setReservaModificandoAdmin(r);
    setModAdminFecha(r.fecha);
    setModAdminHora(r.hora_inicio);
    // Antes ponía "1" fijo: al abrir el modal y guardar sin tocar nada, el
    // admin acortaba la reserva a una hora y se recalculaba el monto.
    const horas = horasDeDuracion(r.duracion);
    setModAdminDuracion(String(horas ?? DURACION_MIN_H));
    setModAdminIdCancha(String(r.id_cancha));
  };

  const handleModificarAdmin = async (e: any) => {
    e.preventDefault();
    if (!reservaModificandoAdmin) return;

    const falla = validaReserva({
      fecha: modAdminFecha,
      hora: modAdminHora,
      duracion: modAdminDuracion,
    });
    if (falla) {
      alert(`❌ ${falla}`);
      return;
    }

    try {
      const r = await axios.put(`http://127.0.0.1:5000/api/admin/reservas/${reservaModificandoAdmin.id_reserva}/modificar-admin`, {
        id_cancha: parseInt(modAdminIdCancha),
        fecha_reserva: modAdminFecha,
        hora_inicio: modAdminHora,
        duracion: parseFloat(modAdminDuracion),
      });
      alert(`✅ ${r.data.mensaje}\nCancha: #${r.data.id_cancha} ${r.data.nueva_cancha}\nNuevo monto: Bs ${r.data.nuevo_monto}`);
      setReservaModificandoAdmin(null);
      cargarReservasAdmin();
    } catch (err: any) {
      alert(`❌ ${err.response?.data?.error || "Error al modificar."}`);
    }
  };

  // ---------- RESERVA PRESENCIAL ----------
  const abrirModalReservaPresencial = () => {
    setModalReservaPresencial(true);
    setPresIdCliente("");
    setPresIdCancha("");
    setPresFecha("");
    setPresHora("");
    setPresDuracion("1");
    setPresMetodoPago("efectivo");
    setBusquedaCliente("");
    setPresMensaje(null);
  };

  const handleReservaPresencial = async (e: any) => {
    e.preventDefault();
    setPresMensaje({ texto: "Procesando...", tipo: "info" });

    const fallaReserva = validaReserva({
      fecha: presFecha,
      hora: presHora,
      duracion: presDuracion,
    });
    if (fallaReserva) {
      setPresMensaje({ texto: `❌ ${fallaReserva}`, tipo: "error" });
      return;
    }
    if (textoVacio(presIdCliente)) {
      setPresMensaje({ texto: "❌ Selecciona el cliente.", tipo: "error" });
      return;
    }
    if (textoVacio(presIdCancha)) {
      setPresMensaje({ texto: "❌ Selecciona la cancha.", tipo: "error" });
      return;
    }

    try {
      const r = await axios.post("http://127.0.0.1:5000/api/empleado/reservas", {
        id_cancha: parseInt(presIdCancha),
        id_cliente: parseInt(presIdCliente),
        fecha_reserva: presFecha,
        hora_inicio: presHora,
        duracion: parseFloat(presDuracion),
        metodo_pago: presMetodoPago,
        id_empleado: usuario?.id_empleado || null,
      });
      setPresMensaje({
        texto: `✅ ${r.data.mensaje} Monto: Bs ${r.data.monto_total}. Estado: ${r.data.estado}.`,
        tipo: "success",
      });
      cargarReservasAdmin();
    } catch (err: any) {
      setPresMensaje({
        texto: `❌ ${err.response?.data?.error || "Error al crear la reserva."}`,
        tipo: "error",
      });
    }
  };

  const clientesFiltrados = clientes.filter((c) => {
    const q = busquedaCliente.toLowerCase().trim();
    if (!q) return false;
    return c.nombre_completo.toLowerCase().includes(q) || c.ci.toLowerCase().includes(q);
  });

  // ---------- REGISTRAR CLIENTE ----------
  const abrirModalRegistrarCliente = () => {
    setModalRegistrarCliente(true);
    setRegNombre("");
    setRegApellido("");
    setRegCi("");
    setRegCelular("");
    setRegEmail("");
    setRegUsername("");
    setRegContrasena("");
    setRegMensaje(null);
  };

  const handleRegistrarCliente = async (e: any) => {
    e.preventDefault();
    setRegMensaje({ texto: "Procesando...", tipo: "info" });

    // Antes se mandaba tal cual: una CI de letras o una contrasena de un
    // caracter llegaban al backend, que solo revisa el largo de la clave.
    const falla = validarAltaCliente({
      nombre: regNombre,
      apellido: regApellido,
      ci: regCi,
      celular: regCelular,
      email: regEmail,
      username: regUsername,
      password: regContrasena,
    });
    if (falla) {
      setRegMensaje({ texto: `❌ ${falla}`, tipo: "error" });
      return;
    }

    try {
      const r = await axios.post("http://127.0.0.1:5000/api/admin/clientes", {
        nombre: regNombre.trim(),
        apellido: regApellido.trim(),
        ci: regCi.trim(),
        celular: regCelular.trim(),
        email: regEmail.trim(),
        username: regUsername.trim(),
        contrasena: regContrasena,
      });
      setRegMensaje({ texto: `✅ ${r.data.mensaje}`, tipo: "success" });
      cargarClientes();
      setTimeout(() => {
        setModalRegistrarCliente(false);
        setRegMensaje(null);
      }, 1800);
    } catch (err: any) {
      setRegMensaje({
        texto: `❌ ${err.response?.data?.error || "Error al registrar cliente."}`,
        tipo: "error",
      });
    }
  };

  // ---------- BLOQUEOS ----------
  const abrirModalBloqueo = () => {
    setModalBloqueo(true);
    setBloIdCancha("");
    setBloFechaInicio("");
    setBloFechaFin("");
    setBloHoraInicio("");
    setBloHoraFin("");
    setBloMotivo("");
    setBloMensaje(null);
  };

  const handleCrearBloqueo = async (e: any) => {
    e.preventDefault();
    if (!usuario?.id_administrador) {
      setBloMensaje({ texto: "❌ Solo el administrador puede crear bloqueos.", tipo: "error" });
      return;
    }
    setBloMensaje({ texto: "Procesando...", tipo: "info" });

    // Sin esto se guardaba un bloqueo con el rango invertido: queda activo en la
    // base pero nunca coincide con ninguna fecha, así que la cancha sigue libre
    // y el admin cree lo contrario.
    if (textoVacio(bloIdCancha)) {
      setBloMensaje({ texto: "❌ Selecciona la cancha.", tipo: "error" });
      return;
    }
    if (!rangoFechasValido(bloFechaInicio, bloFechaFin)) {
      setBloMensaje({
        texto: "❌ La fecha de fin debe ser igual o posterior a la de inicio.",
        tipo: "error",
      });
      return;
    }
    if (!horaFinPosterior(bloHoraInicio, bloHoraFin)) {
      setBloMensaje({
        texto: "❌ La hora de fin debe ser posterior a la de inicio.",
        tipo: "error",
      });
      return;
    }
    if (textoVacio(bloMotivo)) {
      setBloMensaje({ texto: "❌ Escribe el motivo del bloqueo.", tipo: "error" });
      return;
    }

    try {
      const r = await axios.post("http://127.0.0.1:5000/api/admin/bloqueos", {
        id_cancha: parseInt(bloIdCancha),
        id_administrador: usuario.id_administrador,
        fecha_inicio: bloFechaInicio,
        fecha_fin: bloFechaFin,
        hora_inicio: bloHoraInicio,
        hora_fin: bloHoraFin,
        motivo: bloMotivo,
      });
      setBloMensaje({ texto: `✅ ${r.data.mensaje}`, tipo: "success" });
      cargarBloqueos();
      setTimeout(() => {
        setModalBloqueo(false);
        setBloMensaje(null);
      }, 1500);
    } catch (err: any) {
      setBloMensaje({
        texto: `❌ ${err.response?.data?.error || "Error al crear bloqueo."}`,
        tipo: "error",
      });
    }
  };

  const handleEliminarBloqueo = async (id: number) => {
    if (!confirm("¿Seguro que deseas eliminar este bloqueo?")) return;
    try {
      await axios.delete(`http://127.0.0.1:5000/api/admin/bloqueos/${id}`);
      alert("✅ Bloqueo eliminado.");
      cargarBloqueos();
    } catch (err: any) {
      alert(`❌ ${err.response?.data?.error || "Error al eliminar."}`);
    }
  };

  // ---------- GESTIÓN CANCHAS ----------
  const abrirModalCancha = async (cancha?: Cancha) => {
    setCanMensaje(null);
    setCanFotosNuevas([]);
    setCanImagenes([]);
    if (cancha) {
      setCanchaEditando(cancha);
      setCanFormNombre(cancha.nombre);
      setCanFormDeporte(cancha.deporte);
      setCanFormPrecio(String(cancha.precio_hora));
      setCanFormTechada(cancha.techada);
      setCanFormUbicacion(cancha.ubicacion || "");
      setCanFormSuperficie(cancha.superficie || "");
      setCanFormCategoria(String(cancha.id_categoria || ""));
      setCanFormEstado(cancha.estado);
      setCanFormMotivo("");
      // Fotos ya guardadas: se muestran para poder quitarlas o agregar más.
      try {
        const { data } = await canchasService.listarImagenes(cancha.id);
        setCanImagenes(data);
      } catch {
        setCanImagenes([]);
      }
    } else {
      setCanchaEditando(null);
      setCanFormNombre("");
      setCanFormDeporte("Fútbol");
      setCanFormPrecio("");
      setCanFormTechada(false);
      setCanFormUbicacion("");
      setCanFormSuperficie("");
      setCanFormCategoria(categorias[0]?.id_categoria.toString() || "");
      setCanFormEstado("disponible");
      setCanFormMotivo("");
    }
    setModalCancha(true);
  };

  const seleccionarFotosCancha = (e: React.ChangeEvent<HTMLInputElement>) => {
    const archivos = Array.from(e.target.files || []);
    setCanFotosNuevas((prev) => [...prev, ...archivos].slice(0, 8));
    e.target.value = "";
  };

  const quitarFotoNueva = (indice: number) => {
    setCanFotosNuevas((prev) => prev.filter((_, i) => i !== indice));
  };

  const borrarFotoCancha = async (imagen: CanchaImagen) => {
    if (!canchaEditando) return;
    if (!window.confirm("¿Eliminar esta foto de la cancha?")) return;
    try {
      const { data } = await canchasService.eliminarImagen(canchaEditando.id, imagen.id_imagen);
      setCanImagenes(data.imagenes);
      cargarCanchas();
    } catch (err) {
      setCanMensaje({ texto: `❌ ${mensajeError(err)}`, tipo: "error" });
    }
  };

  const handleGuardarCancha = async (e: any) => {
    e.preventDefault();
    if (!usuario?.id_administrador) {
      setCanMensaje({ texto: "❌ Solo admin.", tipo: "error" });
      return;
    }
    setCanMensaje({ texto: "Guardando...", tipo: "info" });
    const datos = {
      nombre_cancha: canFormNombre,
      tipo_deporte: canFormDeporte,
      precio_hora: parseFloat(canFormPrecio),
      techada: canFormTechada,
      ubicacion: canFormUbicacion,
      superficie: canFormSuperficie,
      id_categoria: parseInt(canFormCategoria),
      id_administrador: usuario.id_administrador,
      estado: canFormEstado,
      motivo: canFormMotivo,
    };
    try {
      let idCancha: number;
      if (canchaEditando) {
        await axios.put(`http://127.0.0.1:5000/api/admin/canchas/${canchaEditando.id}`, datos);
        idCancha = canchaEditando.id;
        setCanMensaje({ texto: "✅ Cancha actualizada", tipo: "success" });
      } else {
        const r = await axios.post("http://127.0.0.1:5000/api/admin/canchas", datos);
        idCancha = r.data.id_cancha;
        setCanMensaje({ texto: "✅ Cancha creada", tipo: "success" });
      }

      // Las fotos se suben a la galería de la base de datos (no hace falta
      // pegar ningún enlace).
      if (canFotosNuevas.length > 0) {
        const { data } = await canchasService.subirImagenes(idCancha, canFotosNuevas);
        setCanImagenes(data.imagenes);
        setCanFotosNuevas([]);
        setCanMensaje({
          texto: `✅ Cancha guardada con ${data.imagenes.length} foto(s)`,
          tipo: "success",
        });
      }
      cargarCanchas();
      setTimeout(() => {
        setModalCancha(false);
        setCanMensaje(null);
      }, 1200);
    } catch (err: any) {
      setCanMensaje({
        texto: `❌ ${err.response?.data?.error || "Error al guardar."}`,
        tipo: "error",
      });
    }
  };

  const handleEliminarCancha = async (id: number, nombre: string) => {
    if (!confirm(`¿Desactivar la cancha "${nombre}"?`)) return;
    try {
      const res = await axios.delete(`http://127.0.0.1:5000/api/admin/canchas/${id}`);
      alert(`✅ ${res.data?.mensaje || "Operación completada."}`);
      cargarCanchas();
    } catch (err: any) {
      alert(`❌ ${err.response?.data?.error || "Error."}`);
    }
  };

  // ---------- GESTIÓN CATEGORÍAS ----------
  const abrirModalCategoria = (cat?: Categoria) => {
    if (cat) {
      setCatEditando(cat);
      setCatFormNombre(cat.nombre);
      setCatFormDescripcion(cat.descripcion || "");
    } else {
      setCatEditando(null);
      setCatFormNombre("");
      setCatFormDescripcion("");
    }
    setCatMensaje(null);
    setModalCategoria(true);
  };

  const handleGuardarCategoria = async (e: any) => {
    e.preventDefault();
    setCatMensaje({ texto: "Guardando...", tipo: "info" });
    try {
      if (catEditando) {
        await axios.put(`http://127.0.0.1:5000/api/admin/categorias/${catEditando.id_categoria}`, {
          nombre: catFormNombre,
          descripcion: catFormDescripcion,
        });
        setCatMensaje({ texto: "✅ Categoría actualizada", tipo: "success" });
      } else {
        await axios.post("http://127.0.0.1:5000/api/admin/categorias", {
          nombre: catFormNombre,
          descripcion: catFormDescripcion,
        });
        setCatMensaje({ texto: "✅ Categoría creada", tipo: "success" });
      }
      cargarCategorias();
      setTimeout(() => {
        setModalCategoria(false);
        setCatMensaje(null);
      }, 1200);
    } catch (err: any) {
      setCatMensaje({
        texto: `❌ ${err.response?.data?.error || "Error."}`,
        tipo: "error",
      });
    }
  };

  const handleEliminarCategoria = async (id: number, nombre: string) => {
    if (!confirm(`¿Eliminar la categoría "${nombre}"?`)) return;
    try {
      await axios.delete(`http://127.0.0.1:5000/api/admin/categorias/${id}`);
      alert("✅ Categoría eliminada.");
      cargarCategorias();
    } catch (err: any) {
      alert(`❌ ${err.response?.data?.error || "Error."}`);
    }
  };

  // ============================================================
  // CATÁLOGO FILTRADO (vista cliente)
  // ============================================================
  const canchasVisibles = useMemo(() => {
    const texto = busquedaCancha.trim().toLowerCase();
    const lista = canchas.filter((c) => {
      const estado = c.estado_calculado || c.estado;
      if (estado === "inactivo") return false; // dadas de baja no se muestran
      const coincideTexto =
        !texto ||
        c.nombre.toLowerCase().includes(texto) ||
        c.deporte.toLowerCase().includes(texto) ||
        (c.ubicacion || "").toLowerCase().includes(texto);
      const coincideDeporte = !filtroDeporteCancha || c.deporte === filtroDeporteCancha;
      const coincideEstado = !filtroEstadoCancha || estado === filtroEstadoCancha;
      return coincideTexto && coincideDeporte && coincideEstado;
    });
    return [...lista].sort((a, b) => {
      switch (ordenCancha) {
        case "nombre_desc":
          return b.nombre.localeCompare(a.nombre, "es");
        case "precio_asc":
          return Number(a.precio_hora) - Number(b.precio_hora);
        case "precio_desc":
          return Number(b.precio_hora) - Number(a.precio_hora);
        case "recientes":
          return b.id - a.id;
        default:
          return a.nombre.localeCompare(b.nombre, "es");
      }
    });
  }, [canchas, busquedaCancha, filtroDeporteCancha, filtroEstadoCancha, ordenCancha]);

  const deportesCanchas = useMemo(
    () => Array.from(new Set(canchas.map((c) => c.deporte))).sort((a, b) => a.localeCompare(b, "es")),
    [canchas],
  );

  // ============================================================
  // RENDER
  // ============================================================
  if (cargando) return <AppLayout title="Reservas"><div className="cargando">Cargando canchas...</div></AppLayout>;
  if (error) return <AppLayout title="Reservas"><div className="app-container"><p className="mensaje error">{error}</p></div></AppLayout>;

  return (
    <AppLayout title="Reservas">
      <div className="app-container">


      {/* ===================== VISTA: CLIENTE ===================== */}
      {esCliente && (
        <>
          <h2 className="section-title">Canchas</h2>

          {/* BÚSQUEDA Y FILTROS */}
          <div className="barra-filtros">
            <div className="campo-busqueda">
              <span className="lupa">🔍</span>
              <input
                type="search"
                placeholder="Buscar cancha por nombre, deporte o zona…"
                value={busquedaCancha}
                onChange={(e) => setBusquedaCancha(e.target.value)}
              />
            </div>
            <select
              value={filtroDeporteCancha}
              onChange={(e) => setFiltroDeporteCancha(e.target.value)}
            >
              <option value="">Todos los deportes</option>
              {deportesCanchas.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
            <select
              value={filtroEstadoCancha}
              onChange={(e) => setFiltroEstadoCancha(e.target.value)}
            >
              <option value="">Todos los estados</option>
              <option value="disponible">Disponibles</option>
              <option value="ocupada">Ocupadas</option>
              <option value="mantenimiento">En mantenimiento</option>
            </select>
            <select value={ordenCancha} onChange={(e) => setOrdenCancha(e.target.value)}>
              <option value="nombre_asc">Nombre A → Z</option>
              <option value="nombre_desc">Nombre Z → A</option>
              <option value="precio_asc">Precio: menor a mayor</option>
              <option value="precio_desc">Precio: mayor a menor</option>
              <option value="recientes">Más recientes</option>
            </select>
          </div>

          {canchasVisibles.length === 0 ? (
            <div className="estado-vacio">
              {canchas.length === 0
                ? "No hay canchas registradas por el momento."
                : "Ninguna cancha coincide con tu búsqueda o filtros."}
            </div>
          ) : (
          <div className="canchas-grid">
            {canchasVisibles.map((c) => {
              // Estado que ve el cliente: disponible / ocupada / mantenimiento.
              const estado = c.estado_calculado || c.estado;
              // Bloqueo puntual (mantenimiento programado, evento, etc.)
              const bloqueoActivo = bloqueos.find(
                (b) => b.id_cancha === c.id && b.estado === 'activo'
              );
              const noReservable = c.reserva_habilitada === false || estado !== 'disponible';

              const etiquetaEstado: Record<string, string> = {
                disponible: 'DISPONIBLE',
                ocupada: 'OCUPADA AHORA',
                mantenimiento: 'EN MANTENIMIENTO',
              };

              return (
                <div
                  key={c.id}
                  className="cancha-card"
                  style={{
                    opacity: noReservable ? 0.85 : 1,
                    borderColor:
                      estado === 'mantenimiento'
                        ? '#ff9800'
                        : estado === 'ocupada'
                          ? '#7c3aed'
                          : undefined
                  }}
                >
                  {c.imagen_preview_id ? (
                    <img
                      className="cancha-imagen"
                      src={imagenCanchaURL(c.id, c.imagen_preview_id)}
                      alt={c.nombre}
                    />
                  ) : c.imagen_url ? (
                    <img className="cancha-imagen" src={c.imagen_url} alt={c.nombre} />
                  ) : (
                    <div className="cancha-imagen cancha-imagen-placeholder">🏟️</div>
                  )}
                  <div className="cancha-card-header">
                    <span className="cancha-id">#{c.id}</span>
                    <h3>{c.nombre}</h3>
                  </div>
                  <p className="deporte">⚽ {c.deporte} {c.techada && "• Techada"}</p>
                  {c.categoria && <p className="deporte">🏷️ {c.categoria}</p>}
                  {c.ubicacion && <p className="deporte">📍 {c.ubicacion}</p>}
                  {c.superficie && <p className="deporte">🏟️ {c.superficie}</p>}
                  <div className="precio">Bs {c.precio_hora} <span>/ hora</span></div>

                  {/* Estado + motivo del bloqueo puntual, si existe */}
                  {bloqueoActivo ? (
                    <div style={{
                      marginTop: '10px',
                      padding: '10px',
                      background: 'rgba(255, 152, 0, 0.15)',
                      border: '1px solid rgba(255, 152, 0, 0.4)',
                      borderRadius: '8px',
                      fontSize: '0.85rem',
                      color: '#ff9800'
                    }}>
                      <strong>🔒 {bloqueoActivo.motivo}</strong>
                      <br />
                      📅 Del <strong>{bloqueoActivo.fecha_inicio}</strong> al <strong>{bloqueoActivo.fecha_fin}</strong>
                      <br />
                      🕐 Horario: {bloqueoActivo.hora_inicio} - {bloqueoActivo.hora_fin}
                      <br />
                      <em style={{ fontSize: '0.8rem' }}>Disponible para reservar después del {bloqueoActivo.fecha_fin}</em>
                    </div>
                  ) : (
                    <>
                      <span className={`badge ${estado}`}>
                        {etiquetaEstado[estado] || estado.toUpperCase()}
                      </span>
                      {estado === 'ocupada' && (
                        <p className="deporte" style={{ marginTop: '6px' }}>
                          ⏳ Tiene una reserva en curso ahora mismo; libérese al finalizar.
                        </p>
                      )}
                      {estado === 'mantenimiento' && (
                        <p className="deporte" style={{ marginTop: '6px' }}>
                          🛠️ En reparación: no disponible para reservar hasta que vuelva a estar activa.
                        </p>
                      )}
                      {noReservable ? (
                        <button
                          type="button"
                          className="btn-secondary"
                          style={{ width: "100%", marginTop: "12px" }}
                          disabled
                          title={
                            estado === 'ocupada'
                              ? 'La cancha está ocupada en este momento'
                              : 'La cancha no está disponible para reservar'
                          }
                        >
                          {estado === 'ocupada' ? '⛔ Ocupada — no reservable' : '⛔ No reservable'}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn-primary"
                          style={{ width: "100%", marginTop: "12px" }}
                          onClick={() => abrirModalReserva(c.id)}
                        >
                          📅 Reservar
                        </button>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
          )}
        </>
      )}

      {/* ===================== VISTA: EMPLEADO ===================== */}
      {esEmpleado && (
        <>
          <h2 className="section-title">📋 Gestión de Reservas</h2>
          <div style={{ marginBottom: "15px", display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <button className="btn-primary" onClick={abrirModalReservaPresencial}>➕ Registrar Reserva Presencial</button>
            <button className="btn-success" onClick={abrirModalRegistrarCliente}>👤 Registrar Cliente Nuevo</button>
          </div>
          <div className="filtros">
            <input type="date" value={filtroFecha} onChange={(e) => setFiltroFecha(e.target.value)} style={{ maxWidth: "200px" }} />
            <select value={filtroEstado} onChange={(e) => setFiltroEstado(e.target.value)} style={{ maxWidth: "180px" }}>
              <option value="">Todos los estados</option>
              <option value="pendiente">Pendiente</option>
              <option value="confirmada">Confirmada</option>
              <option value="cancelada">Cancelada</option>
              <option value="completada">Completada</option>
              <option value="expirada">Expirada</option>
            </select>
            <button className="btn-secondary" onClick={() => { setFiltroFecha(""); setFiltroEstado(""); }}>Limpiar filtros</button>
          </div>
          {reservasAdmin.length === 0 ? (
            <div className="estado-vacio">No hay reservas que coincidan con los filtros.</div>
          ) : (
            <div className="tabla-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Cliente</th><th>Cancha</th><th>Fecha</th><th>Horario</th><th>Estado</th><th>Motivo</th><th style={{ textAlign: "center" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {reservasAdmin.map((r) => (
                    <tr key={r.id_reserva}>
                      <td><strong>{r.cliente}</strong></td>
                      <td>#{r.id_cancha} {r.cancha}</td>
                      <td>{r.fecha}</td>
                      <td>{r.hora_inicio} - {r.hora_fin}</td>
                      <td><span className={`estado ${r.estado}`}>{r.estado}</span></td>
                      <td style={{ fontSize: "0.85rem", color: "var(--color-text-dim)", maxWidth: "200px" }}>{r.motivo_cancelacion || "—"}</td>
                      <td>
                        <div className="acciones">
                          {(r.estado === "pendiente" || r.estado === "confirmada") && (
                            <>
                              <button className="btn-warning btn-sm" onClick={() => abrirModalModificarAdmin(r)}>✏️ Modificar</button>
                              <button className="btn-danger btn-sm" onClick={() => { setReservaCancelandoAdmin(r); setMotivoCancelacion(""); }}>⚠️ Cancelar</button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ===================== VISTA: ADMINISTRADOR ===================== */}
      {esAdmin && (
        <>
          <h2 className="section-title">📋 Gestión de Reservas</h2>
          <div style={{ marginBottom: "15px", display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <button className="btn-primary" onClick={abrirModalReservaPresencial}>➕ Reserva Presencial</button>
            <button className="btn-success" onClick={abrirModalRegistrarCliente}>👤 Registrar Cliente</button>
            <button className="btn-warning" onClick={abrirModalBloqueo}>🔒 Bloquear Cancha</button>
            <button className={verGestionCanchas ? "btn-secondary" : "btn-primary"} onClick={() => setVerGestionCanchas(!verGestionCanchas)} style={{ background: verGestionCanchas ? "#6b7280" : "#0F7F82" }}>
              🏟️ {verGestionCanchas ? "Ocultar Canchas" : "Gestionar Canchas"}
            </button>
            <button className={verGestionCategorias ? "btn-secondary" : "btn-primary"} onClick={() => setVerGestionCategorias(!verGestionCategorias)} style={{ background: verGestionCategorias ? "#6b7280" : "#0F7F82" }}>
              🏷️ {verGestionCategorias ? "Ocultar Categorías" : "Categorías"}
            </button>
          </div>

          <div className="filtros">
            <input type="date" value={filtroFecha} onChange={(e) => setFiltroFecha(e.target.value)} style={{ maxWidth: "200px" }} />
            <select value={filtroEstado} onChange={(e) => setFiltroEstado(e.target.value)} style={{ maxWidth: "180px" }}>
              <option value="">Todos los estados</option>
              <option value="pendiente">Pendiente</option>
              <option value="confirmada">Confirmada</option>
              <option value="cancelada">Cancelada</option>
              <option value="completada">Completada</option>
              <option value="expirada">Expirada</option>
            </select>
            <button className="btn-secondary" onClick={() => { setFiltroFecha(""); setFiltroEstado(""); }}>Limpiar filtros</button>
          </div>

          {reservasAdmin.length === 0 ? (
            <div className="estado-vacio">No hay reservas que coincidan con los filtros.</div>
          ) : (
            <div className="tabla-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Cliente</th><th>Cancha</th><th>Fecha</th><th>Horario</th><th>Estado</th><th>Motivo</th><th style={{ textAlign: "center" }}>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {reservasAdmin.map((r) => (
                    <tr key={r.id_reserva}>
                      <td><strong>{r.cliente}</strong></td>
                      <td>#{r.id_cancha} {r.cancha}</td>
                      <td>{r.fecha}</td>
                      <td>{r.hora_inicio} - {r.hora_fin}</td>
                      <td><span className={`estado ${r.estado}`}>{r.estado}</span></td>
                      <td style={{ fontSize: "0.85rem", color: "var(--color-text-dim)", maxWidth: "200px" }}>{r.motivo_cancelacion || "—"}</td>
                      <td>
                        <div className="acciones">
                          {(r.estado === "pendiente" || r.estado === "confirmada") && (
                            <>
                              <button className="btn-warning btn-sm" onClick={() => abrirModalModificarAdmin(r)}>✏️ Modificar</button>
                              <button className="btn-danger btn-sm" onClick={() => { setReservaCancelandoAdmin(r); setMotivoCancelacion(""); }}>⚠️ Cancelar</button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* GESTIÓN DE CANCHAS */}
          {verGestionCanchas && (
            <div ref={gestionCanchasRef}>
              <hr className="divider" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px", gap: "10px", flexWrap: "wrap" }}>
                <h2 className="section-title" style={{ marginBottom: 0 }}>🏟️ Gestión de Canchas</h2>
                <div style={{ display: "flex", gap: "10px" }}>
                  <Link className="btn-secondary btn-sm" to="/admin/canchas" style={{ textDecoration: "none" }}>
                    ⚙️ Gestión completa (fotos, filtros y estados)
                  </Link>
                  <button className="btn-primary" onClick={() => abrirModalCancha()}>➕ Nueva Cancha</button>
                </div>
              </div>
              <div className="tabla-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th><th>Foto</th><th>Nombre</th><th>Deporte</th><th>Categoría</th><th>Ubicación</th><th>Superficie</th><th>Precio/h</th><th>Techada</th><th>Estado</th><th className="col-acciones" style={{ textAlign: "center" }}>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {canchas.map((c) => (
                      <tr key={c.id}>
                        <td><strong style={{ color: "var(--color-primary)" }}>#{c.id}</strong></td>
                        <td>
                          {c.imagen_preview_id ? (
                            <img
                              className="cancha-thumb"
                              src={imagenCanchaURL(c.id, c.imagen_preview_id)}
                              alt={c.nombre}
                            />
                          ) : c.imagen_url ? (
                            <img className="cancha-thumb" src={c.imagen_url} alt={c.nombre} />
                          ) : (
                            <span className="cancha-thumb cancha-thumb-placeholder">🏟️</span>
                          )}
                        </td>
                        <td><strong>{c.nombre}</strong></td>
                        <td>{c.deporte}</td>
                        <td>{c.categoria || "—"}</td>
                        <td style={{ fontSize: "0.85rem" }}>{c.ubicacion || "—"}</td>
                        <td style={{ fontSize: "0.85rem" }}>{c.superficie || "—"}</td>
                        <td>Bs {c.precio_hora}</td>
                        <td>{c.techada ? "✅" : "❌"}</td>
                        <td><span className={`badge ${c.estado_calculado || c.estado}`}>{ETIQUETA_ESTADO_CANCHA[c.estado_calculado || c.estado] || c.estado}</span></td>
                        <td className="col-acciones">
                          <div className="acciones">
                            <button className="btn-warning btn-sm btn-icono" title="Editar cancha" aria-label={`Editar ${c.nombre}`} onClick={() => abrirModalCancha(c)}>✏️</button>
                            <button className="btn-danger btn-sm btn-icono" title="Eliminar cancha" aria-label={`Eliminar ${c.nombre}`} onClick={() => handleEliminarCancha(c.id, c.nombre)}>🗑️</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* GESTIÓN DE CATEGORÍAS */}
          {verGestionCategorias && (
            <div ref={gestionCategoriasRef}>
              <hr className="divider" />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" }}>
                <h2 className="section-title" style={{ marginBottom: 0 }}>🏷️ Gestión de Categorías</h2>
                <button className="btn-primary" onClick={() => abrirModalCategoria()}>➕ Nueva Categoría</button>
              </div>
              <div className="tabla-wrapper">
                <table>
                  <thead>
                    <tr><th>ID</th><th>Nombre</th><th>Descripción</th><th style={{ textAlign: "center" }}>Acciones</th></tr>
                  </thead>
                  <tbody>
                    {categorias.map((c) => (
                      <tr key={c.id_categoria}>
                        <td><strong style={{ color: "var(--color-primary)" }}>#{c.id_categoria}</strong></td>
                        <td><strong>{c.nombre}</strong></td>
                        <td style={{ fontSize: "0.9rem" }}>{c.descripcion || "—"}</td>
                        <td>
                          <div className="acciones">
                            <button className="btn-warning btn-sm" onClick={() => abrirModalCategoria(c)}>✏️</button>
                            <button className="btn-danger btn-sm" onClick={() => handleEliminarCategoria(c.id_categoria, c.nombre)}>🗑️</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* BLOQUEOS */}
          <div ref={bloqueosRef}>
  <hr className="divider" />
  <h2 className="section-title">🔒 Canchas Bloqueadas / No Disponibles</h2>

  {/* Bloqueos programados (tabla bloqueo) */}
  <h3 style={{ marginBottom: "10px", color: "var(--color-text-dim)", fontSize: "1rem" }}>
    📅 Bloqueos programados
  </h3>
  {bloqueos.length === 0 ? (
    <div className="estado-vacio">No hay bloqueos programados.</div>
  ) : (
    <div className="tabla-wrapper">
      <table>
        <thead>
          <tr>
            <th>Cancha</th>
            <th>Desde</th>
            <th>Hasta</th>
            <th>Horario</th>
            <th>Motivo</th>
            <th style={{ textAlign: "center" }}>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {bloqueos.map((b) => (
            <tr key={b.id_bloqueo}>
              <td><strong>#{b.id_cancha} {b.cancha}</strong></td>
              <td>{b.fecha_inicio}</td>
              <td>{b.fecha_fin}</td>
              <td>{b.hora_inicio} - {b.hora_fin}</td>
              <td style={{ fontSize: "0.85rem", maxWidth: "250px" }}>{b.motivo}</td>
              <td>
                <div className="acciones">
                  <button className="btn-danger btn-sm" onClick={() => handleEliminarBloqueo(b.id_bloqueo)}>🗑️</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )}

  {/* Canchas en mantenimiento o fuera de servicio */}
  <h3 style={{ marginTop: "25px", marginBottom: "10px", color: "var(--color-text-dim)", fontSize: "1rem" }}>
    🚧 Canchas en mantenimiento o fuera de servicio
  </h3>
  {canchas.filter(c => c.estado !== 'disponible').length === 0 ? (
    <div className="estado-vacio">Todas las canchas están disponibles.</div>
  ) : (
    <div className="tabla-wrapper">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Cancha</th>
            <th>Deporte</th>
            <th>Estado</th>
            <th style={{ textAlign: "center" }}>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {canchas.filter(c => (c.estado_calculado || c.estado) !== 'disponible').map((c) => (
            <tr key={c.id}>
              <td><strong style={{ color: "var(--color-primary)" }}>#{c.id}</strong></td>
              <td><strong>{c.nombre}</strong></td>
              <td>{c.deporte}</td>
              <td>
                <span className={`badge ${c.estado_calculado || c.estado}`}>{ETIQUETA_ESTADO_CANCHA[c.estado_calculado || c.estado] || c.estado}</span>
              </td>
              <td>
                <div className="acciones">
                  <button
                    className="btn-warning btn-sm"
                    onClick={() => abrirModalCancha(c)}
                    title="Editar cancha para cambiar su estado"
                  >
                    ✏️ Cambiar estado
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )}
</div>
        </>
      )}

      {/* ===================== MODALES ===================== */}

      {/* MODAL: HACER RESERVA */}
      {esCliente && modalReserva && (
        <div className="modal-overlay" onClick={cerrarModalReserva}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "520px" }}>
            <h3>📅 Hacer una Reserva</h3>
            <form onSubmit={handleReserva}>
              <div className="form-group">
                <label>Cancha</label>
                <select value={idCancha} onChange={(e) => setIdCancha(e.target.value)} required>
                  <option value="">Seleccione una cancha</option>
                  {canchas
                    .filter(c => c.estado !== 'fuera_servicio')
                    .map((c) => {
                      const bloqueoActivo = bloqueos.find(
                        (b) => b.id_cancha === c.id && b.estado === 'activo'
                      );
                      return (
                        <option key={c.id} value={c.id}>
                          #{c.id} - {c.nombre} - Bs {c.precio_hora}/h
                          {bloqueoActivo ? ` (🔒 ${bloqueoActivo.motivo} hasta ${bloqueoActivo.fecha_fin})` : ''}
                        </option>
                      );
                    })}
                </select>
              </div>
              <div className="form-group">
                <label>Fecha</label>
                <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} required min={rangoFechaReserva().min} max={rangoFechaReserva().max} title={`Entre ${DIAS_MIN_ANTICIPACION} y ${DIAS_MAX_ANTICIPACION} días de anticipación.`} />
              </div>
              <div className="form-group">
                <label>Hora de inicio</label>
                <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} min="06:00" max="23:00" required />
                <small className="hora-hint">🕐 Horario de atención: 06:00 a 23:00</small>
              </div>
              {slots.length > 0 && (
                <div className="form-group">
                  <label>Horarios disponibles</label>
                  <div className="slots-grid">
                    {slots.map((s) => (
                      <button
                        key={s.hora_inicio}
                        type="button"
                        className={`slot ${s.disponible ? "libre" : "ocupado"} ${hora === s.hora_inicio ? "sel" : ""}`}
                        disabled={!s.disponible}
                        title={s.motivo || "Disponible"}
                        onClick={() => setHora(s.hora_inicio)}
                      >
                        {s.hora_inicio}
                        <span className="slot-sub">
                          {s.disponible ? "libre" : s.motivo}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="form-group">
                <label>Duración (horas)</label>
                <input type="number" step="0.5" min="1" max="4" value={duracion} onChange={(e) => setDuracion(e.target.value)} required />
                <div className="quick-selects">
                  {DURACIONES_COMUNES.map((d) => (
                    <button key={d} type="button" onClick={() => setDuracion(String(d))}>{d}h</button>
                  ))}
                </div>
              </div>
              <div className="form-group">
                <label>¿Con cómo vas a pagar?</label>
                <select value={metodoReserva} onChange={(e) => setMetodoReserva(e.target.value)} required>
                  <option value="qr">📱 QR</option>
                  <option value="transferencia">🏦 Transferencia</option>
                  <option value="tarjeta">💳 Tarjeta</option>
                  <option value="efectivo" disabled>💵 Efectivo — no disponible (complejo cerrado)</option>
                </select>
                <small className="hint">
                  El complejo está cerrado, por eso no se puede pagar en efectivo. Tenés 15 minutos
                  para completar el pago o la reserva expira.
                </small>
              </div>
              {mensajeReserva && (
                <div className={`mensaje ${mensajeReserva.tipo}`}>
                  {mensajeReserva.texto}
                </div>
              )}
              <div className="modal-actions">
                <button type="submit" className="btn-primary">Reservar</button>
                <button type="button" className="btn-secondary" onClick={cerrarModalReserva}>Cerrar</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: PAGAR */}
      {esCliente && reservaPagando && (
        <div className="modal-overlay" onClick={() => setReservaPagando(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>💳 Pagar Reserva #{reservaPagando.id_reserva}</h3>
            <div className="modal-info">
              <div><strong>Cancha:</strong> #{reservaPagando.id_cancha} {reservaPagando.cancha}</div>
              <div><strong>Fecha:</strong> {reservaPagando.fecha}</div>
              <div><strong>Horario:</strong> {reservaPagando.hora_inicio} - {reservaPagando.hora_fin}</div>
            </div>
            <form onSubmit={handlePagar}>
              <div className="form-group">
                <label>Método de pago</label>
                <select value={metodoPago} onChange={(e) => setMetodoPago(e.target.value)} required>
                  <option value="efectivo">💵 Efectivo</option>
                  <option value="tarjeta">💳 Tarjeta</option>
                  <option value="transferencia">🏦 Transferencia</option>
                  <option value="qr">📱 QR</option>
                </select>
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-success">Confirmar pago</button>
                <button type="button" className="btn-secondary" onClick={() => setReservaPagando(null)}>Cancelar</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: CANCELAR ADMIN */}
      {esStaff && reservaCancelandoAdmin && (
        <div className="modal-overlay" onClick={() => setReservaCancelandoAdmin(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>⚠️ Cancelar Reserva #{reservaCancelandoAdmin.id_reserva}</h3>
            <div className="modal-info">
              <div><strong>Cliente:</strong> {reservaCancelandoAdmin.cliente}</div>
              <div><strong>Cancha:</strong> #{reservaCancelandoAdmin.id_cancha} {reservaCancelandoAdmin.cancha}</div>
              <div><strong>Fecha:</strong> {reservaCancelandoAdmin.fecha}</div>
              <div><strong>Horario:</strong> {reservaCancelandoAdmin.hora_inicio} - {reservaCancelandoAdmin.hora_fin}</div>
            </div>
            <form onSubmit={handleCancelarAdmin}>
              <div className="form-group">
                <label>Motivo (fuerza mayor)</label>
                <textarea value={motivoCancelacion} onChange={(e) => setMotivoCancelacion(e.target.value)} placeholder="Ej: Daños en la cancha..." required
                  style={{ background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)", borderRadius: "8px", padding: "10px 12px", color: "var(--color-text)", fontFamily: "inherit", fontSize: "0.95rem", minHeight: "80px", resize: "vertical" }}
                />
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-danger">Confirmar cancelación</button>
                <button type="button" className="btn-secondary" onClick={() => setReservaCancelandoAdmin(null)}>Cerrar</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: MODIFICAR RESERVA (Admin/Empleado) */}
      {esStaff && reservaModificandoAdmin && (
        <div className="modal-overlay" onClick={() => setReservaModificandoAdmin(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "550px" }}>
            <h3>✏️ Modificar Reserva #{reservaModificandoAdmin.id_reserva}</h3>
            <div className="modal-info">
              <div><strong>Cliente:</strong> {reservaModificandoAdmin.cliente}</div>
              <div><strong>Cancha actual:</strong> #{reservaModificandoAdmin.id_cancha} {reservaModificandoAdmin.cancha}</div>
              <div><strong>Fecha actual:</strong> {reservaModificandoAdmin.fecha}</div>
              <div><strong>Horario actual:</strong> {reservaModificandoAdmin.hora_inicio} - {reservaModificandoAdmin.hora_fin}</div>
            </div>
            <form onSubmit={handleModificarAdmin}>
              <div className="form-group">
                <label>Cancha</label>
                <select value={modAdminIdCancha} onChange={(e) => setModAdminIdCancha(e.target.value)} required>
                  <option value="">Seleccione una cancha</option>
                  {canchas.map((c) => <option key={c.id} value={c.id}>#{c.id} - {c.nombre} - Bs {c.precio_hora}/h</option>)}
                </select>
                {modAdminIdCancha && (() => {
                  const mc = canchas.find((x) => x.id === parseInt(modAdminIdCancha));
                  if (!mc?.imagen_url) return null;
                  return (
                    <img className="cancha-imagen-preview"
                      src={mc.imagen_url}
                      alt={mc.nombre}
                      style={{ marginTop: "10px", width: "100%", height: "140px", objectFit: "cover", borderRadius: "8px", border: "1px solid var(--color-border)" }}
                    />
                  );
                })()}
              </div>
              <div className="form-group">
                <label>Nueva fecha</label>
                <input type="date" value={modAdminFecha} onChange={(e) => setModAdminFecha(e.target.value)} required min={rangoFechaReserva().min} max={rangoFechaReserva().max} title={`Entre ${DIAS_MIN_ANTICIPACION} y ${DIAS_MAX_ANTICIPACION} días de anticipación.`} />
              </div>
              <div className="form-group">
                <label>Nueva hora de inicio</label>
                <input type="time" value={modAdminHora} onChange={(e) => setModAdminHora(e.target.value)} min="06:00" max="23:00" required />
                <small className="hora-hint">🕐 Horario: 06:00 a 23:00</small>
              </div>
              <div className="form-group">
                <label>Nueva duración (h)</label>
                <input type="number" step="0.5" min="1" max="4" value={modAdminDuracion} onChange={(e) => setModAdminDuracion(e.target.value)} required />
                <div className="quick-selects">
                  {DURACIONES_COMUNES.map((d) => <button key={d} type="button" onClick={() => setModAdminDuracion(String(d))}>{d}h</button>)}
                </div>
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-success">Guardar cambios</button>
                <button type="button" className="btn-secondary" onClick={() => setReservaModificandoAdmin(null)}>Cancelar</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: RESERVA PRESENCIAL */}
      {esStaff && modalReservaPresencial && (
        <div className="modal-overlay" onClick={() => setModalReservaPresencial(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "600px" }}>
            <h3>➕ Registrar Reserva Presencial</h3>
            <form onSubmit={handleReservaPresencial}>
              <div className="form-group">
                <label>Buscar cliente (nombre o CI)</label>
                <input type="text" value={busquedaCliente} onChange={(e) => setBusquedaCliente(e.target.value)} placeholder="Escriba nombre o CI..." />
                <div className="quick-selects" style={{ marginTop: "5px" }}>
                  <button type="button" onClick={() => { setModalReservaPresencial(false); abrirModalRegistrarCliente(); }}>👤 Cliente nuevo (sin cuenta)</button>
                </div>
              </div>
              {busquedaCliente.trim() !== "" && (
                <div style={{ maxHeight: "150px", overflowY: "auto", background: "var(--color-bg-elevated)", borderRadius: "8px", border: "1px solid var(--color-border)", marginBottom: "15px" }}>
                  {clientesFiltrados.length === 0 ? (
                    <p style={{ padding: "10px", color: "var(--color-text-dim)", fontSize: "0.9rem" }}>No se encontraron clientes.</p>
                  ) : (
                    clientesFiltrados.map((c) => (
                      <div key={c.id_cliente} onClick={() => { setPresIdCliente(String(c.id_cliente)); setBusquedaCliente(`${c.nombre_completo} (CI: ${c.ci})`); }}
                        style={{ padding: "10px 12px", cursor: "pointer", borderBottom: "1px solid var(--color-border)", fontSize: "0.9rem" }}>
                        <strong>{c.nombre_completo}</strong> — CI: {c.ci}
                      </div>
                    ))
                  )}
                </div>
              )}
              {presIdCliente && <div style={{ marginBottom: "15px", fontSize: "0.85rem", color: "var(--color-success)" }}>✓ Cliente seleccionado (ID: {presIdCliente})</div>}
              <div className="form-group">
                <label>Cancha</label>
                <select value={presIdCancha} onChange={(e) => setPresIdCancha(e.target.value)} required>
                  <option value="">Seleccione una cancha</option>
                  {canchas.map((c) => <option key={c.id} value={c.id}>#{c.id} - {c.nombre} - Bs {c.precio_hora}/h</option>)}
                </select>
                {presIdCancha && (() => {
                  const pc = canchas.find((x) => x.id === parseInt(presIdCancha));
                  if (!pc?.imagen_url) return null;
                  return (
                    <img className="cancha-imagen-preview"
                      src={pc.imagen_url}
                      alt={pc.nombre}
                      style={{ marginTop: "10px", width: "100%", height: "140px", objectFit: "cover", borderRadius: "8px", border: "1px solid var(--color-border)" }}
                    />
                  );
                })()}
              </div>
              <div className="form-group">
                <label>Fecha</label>
                <input type="date" value={presFecha} onChange={(e) => setPresFecha(e.target.value)} required min={rangoFechaReserva().min} max={rangoFechaReserva().max} title={`Entre ${DIAS_MIN_ANTICIPACION} y ${DIAS_MAX_ANTICIPACION} días de anticipación.`} />
              </div>
              <div className="form-group">
                <label>Hora de inicio</label>
                <input type="time" value={presHora} onChange={(e) => setPresHora(e.target.value)} min="06:00" max="23:00" required />
                <small className="hora-hint">🕐 Horario: 06:00 a 23:00</small>
              </div>
              <div className="form-group">
                <label>Duración (h)</label>
                <input type="number" step="0.5" min="1" max="4" value={presDuracion} onChange={(e) => setPresDuracion(e.target.value)} required />
                <div className="quick-selects">
                  {DURACIONES_COMUNES.map((d) => <button key={d} type="button" onClick={() => setPresDuracion(String(d))}>{d}h</button>)}
                </div>
              </div>
              <div className="form-group">
                <label>Método de pago</label>
                <select value={presMetodoPago} onChange={(e) => setPresMetodoPago(e.target.value)} required>
                  <option value="efectivo">💵 Efectivo</option>
                  <option value="tarjeta">💳 Tarjeta</option>
                  <option value="transferencia">🏦 Transferencia</option>
                  <option value="qr">📱 QR</option>
                </select>
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-success" disabled={!presIdCliente}>Confirmar y Cobrar</button>
                <button type="button" className="btn-secondary" onClick={() => setModalReservaPresencial(false)}>Cerrar</button>
              </div>
            </form>
            {presMensaje && <div className={`mensaje ${presMensaje.tipo}`}>{presMensaje.texto}</div>}
          </div>
        </div>
      )}

      {/* MODAL: REGISTRAR CLIENTE NUEVO */}
      {esStaff && modalRegistrarCliente && (
        <div className="modal-overlay" onClick={() => setModalRegistrarCliente(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "550px" }}>
            <h3>👤 Registrar Cliente Nuevo</h3>
            <p style={{ fontSize: "0.85rem", color: "var(--color-text-dim)", marginBottom: "15px" }}>El cliente podrá iniciar sesión con el usuario y contraseña que le asignes.</p>
            <form onSubmit={handleRegistrarCliente}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div className="form-group"><label>Nombre *</label><input type="text" value={regNombre} onChange={(e) => setRegNombre(e.target.value)} required minLength={2} maxLength={60} /></div>
                <div className="form-group"><label>Apellido *</label><input type="text" value={regApellido} onChange={(e) => setRegApellido(e.target.value)} required minLength={2} maxLength={60} /></div>
              </div>
              <div className="form-group"><label>CI *</label><input type="text" value={regCi} onChange={(e) => setRegCi(soloDigitos(e.target.value))} required inputMode="numeric" pattern="[0-9]{4,10}" maxLength={10} title="Entre 4 y 10 dígitos, sin letras." /></div>
              <div className="form-group"><label>Celular</label><input type="tel" value={regCelular} onChange={(e) => setRegCelular(soloDigitosCelular(e.target.value))} inputMode="tel" pattern="\+?[0-9]{7,15}" maxLength={16} title="Entre 7 y 15 dígitos, con prefijo internacional opcional." /></div>
              <div className="form-group"><label>Email</label><input type="email" value={regEmail} onChange={(e) => setRegEmail(e.target.value)} maxLength={120} /></div>
              <hr style={{ border: "none", borderTop: "1px solid var(--color-border)", margin: "15px 0" }} />
              <div className="form-group"><label>Usuario *</label><input type="text" value={regUsername} onChange={(e) => setRegUsername(e.target.value)} required minLength={4} maxLength={30} pattern="[A-Za-z0-9._\-]{4,30}" title="Entre 4 y 30 caracteres: letras, números, punto, guion o guion bajo." /></div>
              <div className="form-group">
                <label>Contraseña *</label>
                {/* Era type="text": la clave se ve en pantalla mientras el
                    empleado la dicta y queda expuesta en capturas. */}
                <input type="password" autoComplete="new-password" value={regContrasena} onChange={(e) => setRegContrasena(e.target.value)} required minLength={8} maxLength={128} />
                <small className="hint">{REQUISITOS_PASSWORD}</small>
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-success">Registrar Cliente</button>
                <button type="button" className="btn-secondary" onClick={() => setModalRegistrarCliente(false)}>Cerrar</button>
              </div>
            </form>
            {regMensaje && <div className={`mensaje ${regMensaje.tipo}`}>{regMensaje.texto}</div>}
          </div>
        </div>
      )}

      {/* MODAL: CREAR BLOQUEO */}
      {esAdmin && modalBloqueo && (
        <div className="modal-overlay" onClick={() => setModalBloqueo(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>🔒 Bloquear Cancha</h3>
            <form onSubmit={handleCrearBloqueo}>
              <div className="form-group">
                <label>Cancha</label>
                <select value={bloIdCancha} onChange={(e) => setBloIdCancha(e.target.value)} required>
                  <option value="">Seleccione una cancha</option>
                  {canchas.map((c) => <option key={c.id} value={c.id}>#{c.id} - {c.nombre}</option>)}
                </select>
              </div>
              <div className="form-group"><label>Fecha de inicio</label><input type="date" value={bloFechaInicio} onChange={(e) => { setBloFechaInicio(e.target.value); if (!bloFechaFin) setBloFechaFin(e.target.value); }} required /></div>
              <div className="form-group"><label>Fecha de fin</label><input type="date" value={bloFechaFin} min={bloFechaInicio || undefined} onChange={(e) => setBloFechaFin(e.target.value)} required /></div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div className="form-group"><label>Hora inicio</label><input type="time" value={bloHoraInicio} onChange={(e) => setBloHoraInicio(e.target.value)} min={HORA_ATENCION_MIN} max={HORA_ATENCION_MAX} required /></div>
                <div className="form-group"><label>Hora fin</label><input type="time" value={bloHoraFin} min={bloHoraInicio || HORA_ATENCION_MIN} max={HORA_ATENCION_MAX} onChange={(e) => setBloHoraFin(e.target.value)} required /></div>
              </div>
              <small className="hora-hint">🕐 Horario permitido: 06:00 a 23:00</small>
              <div className="form-group" style={{ marginTop: "10px" }}>
                <label>Motivo del bloqueo</label>
                <textarea value={bloMotivo} onChange={(e) => setBloMotivo(e.target.value)} placeholder="Ej: Mantenimiento del césped..." required
                  style={{ background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)", borderRadius: "8px", padding: "10px 12px", color: "var(--color-text)", fontFamily: "inherit", fontSize: "0.95rem", minHeight: "70px", resize: "vertical" }}
                />
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-warning">Confirmar bloqueo</button>
                <button type="button" className="btn-secondary" onClick={() => setModalBloqueo(false)}>Cancelar</button>
              </div>
            </form>
            {bloMensaje && <div className={`mensaje ${bloMensaje.tipo}`}>{bloMensaje.texto}</div>}
          </div>
        </div>
      )}

      {/* MODAL: CREAR/EDITAR CANCHA */}
      {esAdmin && modalCancha && (
        <div className="modal-overlay" onClick={() => setModalCancha(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "550px" }}>
            <h3>{canchaEditando ? `✏️ Editar Cancha #${canchaEditando.id}` : "➕ Nueva Cancha"}</h3>
            <form onSubmit={handleGuardarCancha}>
              <div className="form-group"><label>Nombre *</label><input type="text" value={canFormNombre} onChange={(e) => setCanFormNombre(e.target.value)} required minLength={2} maxLength={80} /></div>
              <div className="form-group">
                <label>Tipo de deporte *</label>
                <input type="text" value={canFormDeporte} onChange={(e) => setCanFormDeporte(e.target.value)} required minLength={2} maxLength={60} />
                <div className="quick-selects">
                  {["Fútbol", "Básquet", "Vóley", "Tenis", "Futsal"].map((d) => <button key={d} type="button" onClick={() => setCanFormDeporte(d)}>{d}</button>)}
                </div>
              </div>
              <div className="form-group"><label>Precio por hora (Bs) *</label><input type="number" step="0.01" min="0.01" value={canFormPrecio} onChange={(e) => setCanFormPrecio(e.target.value)} required /></div>
              <div className="form-group">
                <label>Categoría *</label>
                <select value={canFormCategoria} onChange={(e) => setCanFormCategoria(e.target.value)} required>
                  <option value="">Seleccione una categoría</option>
                  {categorias.map((cat) => <option key={cat.id_categoria} value={cat.id_categoria}>{cat.nombre}</option>)}
                </select>
              </div>
              <div className="form-group"><label>Ubicación</label><input type="text" value={canFormUbicacion} onChange={(e) => setCanFormUbicacion(e.target.value)} placeholder="Ej: Zona Norte" /></div>
              <div className="form-group">
                <label>Superficie</label>
                <input type="text" value={canFormSuperficie} onChange={(e) => setCanFormSuperficie(e.target.value)} placeholder="Ej: Sintética, Césped natural" />
                <div className="quick-selects">
                  {["Sintética", "Césped Natural", "Cemento", "Madera"].map((s) => <button key={s} type="button" onClick={() => setCanFormSuperficie(s)}>{s}</button>)}
                </div>
              </div>
              <div className="form-group" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
                <input type="checkbox" id="techada" checked={canFormTechada} onChange={(e) => setCanFormTechada(e.target.checked)} style={{ width: "auto" }} />
                <label htmlFor="techada" style={{ marginBottom: 0 }}>Techada</label>
              </div>
              {canchaEditando && (
                <div className="form-group">
                  <label>Estado</label>
                  <select value={canFormEstado === "ocupada" ? "disponible" : canFormEstado} onChange={(e) => setCanFormEstado(e.target.value)} disabled={canchaEditando.estado_calculado === "ocupada"}>
                    <option value="disponible">Disponible</option>
                    <option value="mantenimiento">Mantenimiento</option>
                    <option value="inactivo">Inactiva (oculta para clientes)</option>
                  </select>
                  {canchaEditando.estado_calculado === "ocupada" && (
                    <small className="hora-hint">🔒 Cancha ocupada ahora (reserva en curso); se libera sola al terminar.</small>
                  )}
                </div>
              )}
              {canchaEditando && canFormEstado !== canchaEditando.estado && (
                <div className="form-group">
                  <label>Motivo del cambio *</label>
                  <input type="text" value={canFormMotivo} onChange={(e) => setCanFormMotivo(e.target.value)} placeholder="Ej: mantenimiento de césped" required />
                </div>
              )}
              <div className="form-group">
                <label>📷 Fotos ({canImagenes.length + canFotosNuevas.length} de 8)</label>
                <small className="hora-hint">
                  JPG, PNG o WEBP de hasta 4 MB. Se guardan en la base de datos: no hace
                  falta pegar ningún enlace.
                </small>

                {canImagenes.length > 0 && (
                  <div className="galeria-mini">
                    {canImagenes.map((img) => (
                      <div key={img.id_imagen} className="galeria-mini-item">
                        <img
                          src={imagenCanchaURL(canchaEditando!.id, img.id_imagen)}
                          alt={img.nombre_archivo || "Foto de la cancha"}
                        />
                        <button
                          type="button"
                          className="galeria-quitar"
                          title="Eliminar esta foto"
                          onClick={() => borrarFotoCancha(img)}
                        >
                          ✖
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {canFotosNuevas.length > 0 && (
                  <div className="galeria-mini">
                    {canFotosNuevas.map((archivo, i) => (
                      <div key={`${archivo.name}-${i}`} className="galeria-mini-item">
                        <img src={URL.createObjectURL(archivo)} alt={archivo.name} />
                        <button
                          type="button"
                          className="galeria-quitar"
                          title="Quitar de la selección"
                          onClick={() => quitarFotoNueva(i)}
                        >
                          ✖
                        </button>
                        <span className="galeria-nueva-tag">Nueva</span>
                      </div>
                    ))}
                  </div>
                )}

                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  onChange={seleccionarFotosCancha}
                  disabled={canImagenes.length + canFotosNuevas.length >= 8}
                />
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-success">Guardar</button>
                <button type="button" className="btn-secondary" onClick={() => setModalCancha(false)}>Cancelar</button>
              </div>
            </form>
            {canMensaje && <div className={`mensaje ${canMensaje.tipo}`}>{canMensaje.texto}</div>}
          </div>
        </div>
      )}

      {/* MODAL: CREAR/EDITAR CATEGORÍA */}
      {esAdmin && modalCategoria && (
        <div className="modal-overlay" onClick={() => setModalCategoria(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{catEditando ? "✏️ Editar Categoría" : "➕ Nueva Categoría"}</h3>
            <form onSubmit={handleGuardarCategoria}>
              <div className="form-group">
                <label>Nombre *</label>
                <input type="text" value={catFormNombre} onChange={(e) => setCatFormNombre(e.target.value)} required minLength={2} maxLength={60} />
                <div className="quick-selects">
                  {["Fútbol", "Básquet", "Vóley", "Tenis"].map((n) => <button key={n} type="button" onClick={() => setCatFormNombre(n)}>{n}</button>)}
                </div>
              </div>
              <div className="form-group">
                <label>Descripción</label>
                <textarea value={catFormDescripcion} onChange={(e) => setCatFormDescripcion(e.target.value)} placeholder="Descripción de la categoría..."
                  style={{ background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)", borderRadius: "8px", padding: "10px 12px", color: "var(--color-text)", fontFamily: "inherit", fontSize: "0.95rem", minHeight: "70px", resize: "vertical" }}
                />
              </div>
              <div className="modal-actions">
                <button type="submit" className="btn-success">Guardar</button>
                <button type="button" className="btn-secondary" onClick={() => setModalCategoria(false)}>Cancelar</button>
              </div>
            </form>
            {catMensaje && <div className={`mensaje ${catMensaje.tipo}`}>{catMensaje.texto}</div>}
          </div>
        </div>
      )}
      </div>
    </AppLayout>
  );
}

export default ReservasPage;