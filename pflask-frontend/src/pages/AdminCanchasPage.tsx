import { useCallback, useEffect, useMemo, useState } from "react";
import { AppLayout } from "../components/layout/AppLayout";
import { api } from "../services/api";
import {
  canchasService,
  imagenCanchaURL,
  mensajeError,
  type Cancha,
  type CanchaImagen,
  type EstadoCancha,
  type OrdenCancha,
} from "../services/canchasService";
import {
  HORA_ATENCION_MAX,
  HORA_ATENCION_MIN,
  PRECIO_HORA_MAX,
  esNumeroValido,
  horaFinPosterior,
} from "../utils/validaciones";
import {
  DIAS,
  tarifasService,
  type HorarioDia,
} from "../services/tarifasService";

// ============================================================
// Etiquetas y estilos de estado
// ============================================================
const ETIQUETA_ESTADO: Record<string, string> = {
  disponible: "Disponible",
  ocupada: "Ocupada",
  mantenimiento: "En mantenimiento",
  inactivo: "Inactiva",
};

const CLASE_ESTADO: Record<string, string> = {
  disponible: "disponible",
  ocupada: "ocupada",
  mantenimiento: "mantenimiento",
  inactivo: "inactivo",
};

const ORDENES: { valor: OrdenCancha; etiqueta: string }[] = [
  { valor: "nombre_asc", etiqueta: "Nombre A → Z" },
  { valor: "nombre_desc", etiqueta: "Nombre Z → A" },
  { valor: "precio_asc", etiqueta: "Precio: menor a mayor" },
  { valor: "precio_desc", etiqueta: "Precio: mayor a menor" },
  { valor: "recientes", etiqueta: "Más recientes" },
];

const SUPERFICIES_SUGERIDAS = ["Sintética", "Césped Natural", "Cemento", "Madera"];

// ============================================================
// Formulario de cancha
// ============================================================
interface FormCancha {
  nombre_cancha: string;
  precio_hora: string;
  id_categoria: string;
  ubicacion: string;
  superficie: string;
  techada: boolean;
  estado: string;
  motivo: string;
}

const FORM_VACIO: FormCancha = {
  nombre_cancha: "",
  precio_hora: "",
  id_categoria: "",
  ubicacion: "",
  superficie: "",
  techada: false,
  estado: "disponible",
  motivo: "",
};

interface Categoria {
  id_categoria: number;
  nombre: string;
}

// ============================================================
const AdminCanchasPage = () => {

  // --- Gestión de canchas ---
  const [canchas, setCanchas] = useState<Cancha[]>([]);
  const [categorias, setCategorias] = useState<Categoria[]>([]);
  const [busqueda, setBusqueda] = useState("");
  const [filtroDeporte, setFiltroDeporte] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("");
  const [orden, setOrden] = useState<OrdenCancha>("nombre_asc");

  const [modalCancha, setModalCancha] = useState(false);
  const [canchaEditando, setCanchaEditando] = useState<Cancha | null>(null);
  const [form, setForm] = useState<FormCancha>(FORM_VACIO);
  const [imagenesNuevas, setImagenesNuevas] = useState<File[]>([]);
  const [imagenesActuales, setImagenesActuales] = useState<CanchaImagen[]>([]);
  const [guardandoCancha, setGuardandoCancha] = useState(false);

  const [mensaje, setMensaje] = useState("");
  const [error, setError] = useState("");

  // --- Tarifas y horarios (sección heredada) ---
  const [canchaHorariosId, setCanchaHorariosId] = useState<number | null>(null);
  const [horarios, setHorarios] = useState<HorarioDia[]>([]);
  const [borradorHorarios, setBorradorHorarios] = useState<HorarioDia[]>([]);
  const [guardando, setGuardando] = useState(false);

  // Horario general de la cancha (respaldo de los días sin fila propia).
  const [horarioGeneral, setHorarioGeneral] = useState({
    apertura: HORA_ATENCION_MIN,
    cierre: HORA_ATENCION_MAX,
  });
  const [guardandoHorarioGeneral, setGuardandoHorarioGeneral] = useState(false);

  const limpiarAvisos = () => {
    setMensaje("");
    setError("");
  };

  const avisarError = (err: unknown) => {
    setError(mensajeError(err));
    setGuardandoCancha(false);
    setGuardando(false);
  };

  // ============================================================
  // CARGA
  // ============================================================
  const cargarCanchas = useCallback(async () => {
    try {
      const { data } = await canchasService.listar();
      setCanchas(data);
    } catch (err) {
      avisarError(err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    cargarCanchas();
    api
      .get<Categoria[]>("/categorias")
      .then(({ data }) => setCategorias(data))
      .catch(() => console.error("No se pudieron cargar las categorías."));
  }, [cargarCanchas]);

  // ============================================================
  // FILTRADO Y ORDEN (en el navegador: respuesta inmediata)
  // ============================================================
  const canchasFiltradas = useMemo(() => {
    const texto = busqueda.trim().toLowerCase();
    let lista = canchas.filter((c) => {
      const coincideTexto =
        !texto ||
        c.nombre.toLowerCase().includes(texto) ||
        c.deporte.toLowerCase().includes(texto) ||
        (c.ubicacion || "").toLowerCase().includes(texto);
      const coincideDeporte = !filtroDeporte || c.deporte === filtroDeporte;
      const coincideEstado =
        !filtroEstado || (c.estado_calculado || c.estado) === filtroEstado;
      return coincideTexto && coincideDeporte && coincideEstado;
    });

    lista = [...lista].sort((a, b) => {
      switch (orden) {
        case "nombre_asc":
          return a.nombre.localeCompare(b.nombre, "es");
        case "nombre_desc":
          return b.nombre.localeCompare(a.nombre, "es");
        case "precio_asc":
          return Number(a.precio_hora) - Number(b.precio_hora);
        case "precio_desc":
          return Number(b.precio_hora) - Number(a.precio_hora);
        case "recientes":
        default:
          return b.id - a.id;
      }
    });
    return lista;
  }, [canchas, busqueda, filtroDeporte, filtroEstado, orden]);

  const deportes = useMemo(
    () => Array.from(new Set(canchas.map((c) => c.deporte))).sort((a, b) => a.localeCompare(b, "es")),
    [canchas],
  );

  const limpiarFiltros = () => {
    setBusqueda("");
    setFiltroDeporte("");
    setFiltroEstado("");
    setOrden("nombre_asc");
  };

  const hayFiltros = busqueda || filtroDeporte || filtroEstado || orden !== "nombre_asc";

  // ============================================================
  // MODAL CREAR / EDITAR CANCHA
  // ============================================================
  const abrirModalCancha = async (cancha?: Cancha) => {
    limpiarAvisos();
    setImagenesNuevas([]);
    if (cancha) {
      setCanchaEditando(cancha);
      // La cancha abierta en el modal es la que carga sus horarios.
      setCanchaHorariosId(cancha.id);
      setForm({
        nombre_cancha: cancha.nombre,
        precio_hora: String(cancha.precio_hora),
        id_categoria: String(cancha.id_categoria || ""),
        ubicacion: cancha.ubicacion || "",
        superficie: cancha.superficie || "",
        techada: cancha.techada,
        estado: cancha.estado,
        motivo: "",
      });
      try {
        const { data } = await canchasService.listarImagenes(cancha.id);
        setImagenesActuales(data);
      } catch {
        setImagenesActuales([]);
      }
    } else {
      setCanchaEditando(null);
      setForm({ ...FORM_VACIO, id_categoria: categorias[0] ? String(categorias[0].id_categoria) : "" });
      setImagenesActuales([]);
    }
    setModalCancha(true);
  };

  const seleccionarArchivos = (e: React.ChangeEvent<HTMLInputElement>) => {
    const archivos = Array.from(e.target.files || []);
    setImagenesNuevas((prev) => {
      const combinados = [...prev, ...archivos];
      return combinados.slice(0, 8);
    });
    e.target.value = "";
  };

  const quitarImagenNueva = (indice: number) => {
    setImagenesNuevas((prev) => prev.filter((_, i) => i !== indice));
  };

  const borrarImagenActual = async (imagen: CanchaImagen) => {
    if (!canchaEditando) return;
    if (!window.confirm("¿Eliminar esta foto de la cancha?")) return;
    limpiarAvisos();
    try {
      const { data } = await canchasService.eliminarImagen(canchaEditando.id, imagen.id_imagen);
      setImagenesActuales(data.imagenes);
      setMensaje("Imagen eliminada.");
      await cargarCanchas();
    } catch (err) {
      avisarError(err);
    }
  };

  const handleGuardarCancha = async (e: React.FormEvent) => {
    e.preventDefault();
    limpiarAvisos();

    if (!esNumeroValido(form.precio_hora, { min: 0.01, max: PRECIO_HORA_MAX })) {
      setError(`El precio por hora debe ser un número entre 0.01 y ${PRECIO_HORA_MAX}.`);
      return;
    }

    setGuardandoCancha(true);
    try {
      const datos = {
        nombre_cancha: form.nombre_cancha.trim(),
        precio_hora: Number(form.precio_hora),
        id_categoria: Number(form.id_categoria),
        ubicacion: form.ubicacion.trim() || null,
        superficie: form.superficie.trim() || null,
        techada: form.techada,
        ...(canchaEditando
          ? {
              estado: form.estado,
              ...(form.estado !== canchaEditando.estado ? { motivo: form.motivo.trim() || undefined } : {}),
            }
          : {}),
      };

      let idCancha: number;
      if (canchaEditando) {
        const { data } = await canchasService.editar(canchaEditando.id, datos);
        idCancha = data.cancha.id;
        setMensaje("Cancha actualizada.");
      } else {
        const { data } = await canchasService.crear(datos);
        idCancha = data.cancha.id;
        setMensaje("Cancha creada.");
      }

      if (imagenesNuevas.length > 0) {
        await canchasService.subirImagenes(idCancha, imagenesNuevas);
        setMensaje((m) => `${m} ${imagenesNuevas.length} imagen(es) guardada(s) en la base de datos.`);
      }

      setModalCancha(false);
      await cargarCanchas();
    } catch (err) {
      avisarError(err);
    } finally {
      setGuardandoCancha(false);
    }
  };

  const handleEliminarCancha = async (cancha: Cancha) => {
    if (
      !window.confirm(
        `¿Eliminar la cancha "${cancha.nombre}"? Si tiene reservas o eventos se desactiva en vez de borrarse.`,
      )
    )
      return;
    limpiarAvisos();
    try {
      const { data } = await canchasService.eliminar(cancha.id);
      setMensaje(
        data.desactivada
          ? `${data.mensaje} La cancha ya no aparece para los clientes.`
          : data.mensaje || "Cancha eliminada.",
      );
      await cargarCanchas();
    } catch (err) {
      avisarError(err);
    }
  };

  const cambiarEstadoRapido = async (cancha: Cancha, nuevoEstado: string) => {
    if (nuevoEstado === (cancha.estado_calculado || cancha.estado)) return;
    limpiarAvisos();
    const motivo = window.prompt(
      `Cambiar "${cancha.nombre}" a "${ETIQUETA_ESTADO[nuevoEstado] || nuevoEstado}".\nMotivo (opcional):`,
    );
    if (motivo === null) {
      await cargarCanchas(); // revierte el select visual
      return;
    }
    try {
      await canchasService.cambiarEstado(cancha.id, nuevoEstado, motivo);
      setMensaje(`"${cancha.nombre}" ahora está ${ETIQUETA_ESTADO[nuevoEstado] || nuevoEstado}.`);
      await cargarCanchas();
    } catch (err) {
      avisarError(err);
      await cargarCanchas();
    }
  };

  // ============================================================
  // TARIFAS Y HORARIOS (sección heredada)
  // ============================================================
  const canchaHorarios = canchas.find((c) => c.id === canchaHorariosId) || null;

  const cargarHorarios = useCallback(async (idCancha: number) => {
    const h = await tarifasService.listarHorarios(idCancha);
    setHorarios(h);
    setBorradorHorarios(h);
  }, []);

  useEffect(() => {
    if (canchaHorariosId === null) return;
    limpiarAvisos();
    cargarHorarios(canchaHorariosId).catch((e) => setError(e.message));
  }, [canchaHorariosId, cargarHorarios]);

  // El horario general se sincroniza con la cancha seleccionada: es el
  // respaldo de los días que no tienen fila propia.
  useEffect(() => {
    if (!canchaHorarios) return;
    setHorarioGeneral({
      apertura: canchaHorarios.horario_apertura || HORA_ATENCION_MIN,
      cierre: canchaHorarios.horario_cierre || HORA_ATENCION_MAX,
    });
  }, [canchaHorarios]);

  const editarBorrador = (dia: number, campo: "hora_apertura" | "hora_cierre", valor: string) => {
    setBorradorHorarios((prev) =>
      prev.map((h) => (h.dia_semana === dia ? { ...h, [campo]: valor } : h)),
    );
  };

  const alternarDia = (dia: number) => {
    setBorradorHorarios((prev) =>
      prev.map((h) => (h.dia_semana === dia ? { ...h, activo: !h.activo } : h)),
    );
  };

  const guardarHorarios = async () => {
    if (canchaHorariosId === null) return;
    limpiarAvisos();

    for (const h of borradorHorarios) {
      if (!h.activo) continue;
      if (!h.hora_apertura || !h.hora_cierre) {
        setError(`Falta la hora de apertura o de cierre de ${DIAS[h.dia_semana] ?? `el día ${h.dia_semana}`}.`);
        return;
      }
      if (!horaFinPosterior(h.hora_apertura, h.hora_cierre)) {
        setError(
          `En ${DIAS[h.dia_semana] ?? `el día ${h.dia_semana}`} la hora de cierre debe ser posterior a la de apertura.`,
        );
        return;
      }
      if (h.hora_apertura < HORA_ATENCION_MIN || h.hora_cierre > HORA_ATENCION_MAX) {
        setError(
          `${DIAS[h.dia_semana] ?? `El día ${h.dia_semana}`} debe quedar dentro del horario de atención (${HORA_ATENCION_MIN} a ${HORA_ATENCION_MAX}).`,
        );
        return;
      }
    }

    setGuardando(true);
    try {
      const datos = borradorHorarios.map((h) => ({
        dia_semana: h.dia_semana,
        hora_apertura: h.hora_apertura,
        hora_cierre: h.hora_cierre,
        activo: h.activo,
      }));
      const nuevos = await tarifasService.guardarHorarios(canchaHorariosId, datos);
      setHorarios(nuevos);
      setBorradorHorarios(nuevos);
      setMensaje("Horarios guardados.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGuardando(false);
    }
  };

  const hayCambiosHorarios =
    JSON.stringify(borradorHorarios.map((h) => [h.hora_apertura, h.hora_cierre, h.activo])) !==
    JSON.stringify(horarios.map((h) => [h.hora_apertura, h.hora_cierre, h.activo]));

  /**
   * Guarda el horario general de la cancha (apertura/cierre). Es el horario
   * que se aplica a los días que no tienen una fila propia, así que los días
   * "por defecto" de la tabla muestran estos valores.
   */
  const guardarHorarioGeneral = async () => {
    if (!canchaHorarios) return;
    limpiarAvisos();

    if (!horaFinPosterior(horarioGeneral.apertura, horarioGeneral.cierre)) {
      setError("La hora de cierre general debe ser posterior a la de apertura.");
      return;
    }

    setGuardandoHorarioGeneral(true);
    try {
      await canchasService.editar(canchaHorarios.id, {
        horario_apertura: horarioGeneral.apertura,
        horario_cierre: horarioGeneral.cierre,
      });
      setMensaje("Horario general guardado.");
      await Promise.all([cargarCanchas(), cargarHorarios(canchaHorarios.id)]);
    } catch (err) {
      avisarError(err);
    } finally {
      setGuardandoHorarioGeneral(false);
    }
  };

  // ============================================================
  // RENDER
  // ============================================================
  return (
    <AppLayout
      title="Gestión de canchas"
      subtitle="Crea canchas con fotos, cambia su estado y define sus horarios"
    >
      {error && <div className="mensaje error">{error}</div>}
      {mensaje && <div className="mensaje success">{mensaje}</div>}


      <div className="panel-card">
          <div className="gestion-header">
            <div className="section-title" style={{ marginBottom: 0 }}>
              Canchas ({canchasFiltradas.length}
              {canchasFiltradas.length !== canchas.length ? ` de ${canchas.length}` : ""})
            </div>
            <button className="btn-primary" onClick={() => abrirModalCancha()}>
              ➕ Nueva cancha
            </button>
          </div>

          {/* BARRA DE BÚSQUEDA Y FILTROS */}
          <div className="barra-filtros">
            <div className="campo-busqueda">
              <span className="lupa">🔍</span>
              <input
                type="search"
                placeholder="Buscar por nombre, deporte o ubicación…"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
              />
            </div>
            <select value={filtroDeporte} onChange={(e) => setFiltroDeporte(e.target.value)}>
              <option value="">Todos los deportes</option>
              {deportes.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <select value={filtroEstado} onChange={(e) => setFiltroEstado(e.target.value)}>
              <option value="">Todos los estados</option>
              <option value="disponible">Disponible</option>
              <option value="ocupada">Ocupada</option>
              <option value="mantenimiento">En mantenimiento</option>
              <option value="inactivo">Inactiva</option>
            </select>
            <select value={orden} onChange={(e) => setOrden(e.target.value as OrdenCancha)}>
              {ORDENES.map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.etiqueta}
                </option>
              ))}
            </select>
            {hayFiltros && (
              <button className="btn-secondary btn-sm" onClick={limpiarFiltros}>
                ✖ Limpiar
              </button>
            )}
          </div>

          {canchasFiltradas.length === 0 ? (
            <p className="estado-vacio">
              {canchas.length === 0
                ? "Aún no hay canchas registradas. Crea la primera con «Nueva cancha»."
                : "Ninguna cancha coincide con la búsqueda o los filtros."}
            </p>
          ) : (
            <div className="tabla-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Foto</th>
                    <th>Nombre</th>
                    <th>Deporte</th>
                    <th>Categoría</th>
                    <th>Precio/h</th>
                    <th>Estado</th>
                    <th>Cambiar estado</th>
                    <th>Fotos</th>
                    <th className="col-acciones" style={{ textAlign: "center" }}>
                      Acciones
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {canchasFiltradas.map((c) => {
                    const estadoActual = (c.estado_calculado || c.estado) as EstadoCancha;
                    return (
                      <tr key={c.id}>
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
                        <td>
                          <strong>{c.nombre}</strong>
                          {c.ubicacion && <div className="cancha-dato">📍 {c.ubicacion}</div>}
                        </td>
                        <td>{c.deporte}</td>
                        <td>{c.nombre_categoria || c.categoria || "—"}</td>
                        <td>Bs {c.precio_hora}</td>
                        <td>
                          <span className={`badge ${CLASE_ESTADO[estadoActual] || ""}`}>
                            {ETIQUETA_ESTADO[estadoActual] || estadoActual}
                          </span>
                          {estadoActual === "ocupada" && (
                            <div className="cancha-id">Reserva en curso ahora</div>
                          )}
                        </td>
                        <td>
                          <select
                            value={estadoActual === "ocupada" ? "disponible" : estadoActual}
                            onChange={(e) => cambiarEstadoRapido(c, e.target.value)}
                            disabled={estadoActual === "ocupada"}
                            title={
                              estadoActual === "ocupada"
                                ? "Una cancha ocupada se libera sola cuando termina la reserva en curso"
                                : undefined
                            }
                          >
                            <option value="disponible">Disponible</option>
                            <option value="mantenimiento">Mantenimiento</option>
                            <option value="inactivo">Inactiva</option>
                          </select>
                        </td>
                        <td>{c.total_imagenes}</td>
                        <td className="col-acciones">
                          <div className="acciones">
                            <button
                              className="btn-warning btn-sm btn-icono"
                              title="Editar cancha"
                              aria-label={`Editar ${c.nombre}`}
                              onClick={() => abrirModalCancha(c)}
                            >
                              ✏️
                            </button>
                            <button
                              className="btn-danger btn-sm btn-icono"
                              title="Eliminar cancha"
                              aria-label={`Eliminar ${c.nombre}`}
                              onClick={() => handleEliminarCancha(c)}
                            >
                              🗑️
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
      </div>

      {/* ============================================================
          MODAL: CREAR / EDITAR CANCHA
      ============================================================ */}
      {modalCancha && (
        <div className="modal-overlay" onClick={() => setModalCancha(false)}>
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: "720px" }}
          >
            <h3>
              {canchaEditando
                ? `✏️ Editar cancha #${canchaEditando.id}`
                : "➕ Nueva cancha"}
            </h3>

            {/* Los avisos se repiten dentro del modal: si no, el mensaje
                queda tapado por la ventana mientras se edita. */}
            {error && <div className="mensaje error">{error}</div>}
            {mensaje && <div className="mensaje success">{mensaje}</div>}

            <form onSubmit={handleGuardarCancha}>
              <div className="form-group">
                <label>Nombre *</label>
                <input
                  type="text"
                  value={form.nombre_cancha}
                  onChange={(e) => setForm({ ...form, nombre_cancha: e.target.value })}
                  required
                  minLength={2}
                  maxLength={80}
                  placeholder="Ej: Cancha Central"
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Deporte / Categoría *</label>
                  <select
                    value={form.id_categoria}
                    onChange={(e) => setForm({ ...form, id_categoria: e.target.value })}
                    required
                  >
                    <option value="">Seleccione el deporte</option>
                    {categorias.map((cat) => (
                      <option key={cat.id_categoria} value={cat.id_categoria}>
                        {cat.nombre}
                      </option>
                    ))}
                  </select>
                  <small className="hora-hint">
                    El tipo de deporte se toma de la categoría: así no puede quedar
                    una cancha con deporte y categoría que no coinciden.
                  </small>
                </div>
                <div className="form-group">
                  <label>Precio por hora (Bs) *</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    max={PRECIO_HORA_MAX}
                    value={form.precio_hora}
                    onChange={(e) => setForm({ ...form, precio_hora: e.target.value })}
                    required
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Ubicación</label>
                  <input
                    type="text"
                    maxLength={150}
                    value={form.ubicacion}
                    onChange={(e) => setForm({ ...form, ubicacion: e.target.value })}
                    placeholder="Ej: Zona Norte"
                  />
                </div>
                <div className="form-group">
                  <label>Superficie</label>
                  <input
                    type="text"
                    maxLength={50}
                    value={form.superficie}
                    onChange={(e) => setForm({ ...form, superficie: e.target.value })}
                    placeholder="Ej: Sintética"
                  />
                  <div className="quick-selects">
                    {SUPERFICIES_SUGERIDAS.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setForm({ ...form, superficie: s })}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div
                className="form-group"
                style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}
              >
                <input
                  type="checkbox"
                  id="techada"
                  checked={form.techada}
                  onChange={(e) => setForm({ ...form, techada: e.target.checked })}
                  style={{ width: "auto" }}
                />
                <label htmlFor="techada" style={{ marginBottom: 0 }}>
                  Techada
                </label>
              </div>

              {canchaEditando && (
                <>
                  <div className="form-group">
                    <label>Estado</label>
                    <select
                      value={form.estado === "ocupada" ? "disponible" : form.estado}
                      onChange={(e) => setForm({ ...form, estado: e.target.value })}
                      disabled={canchaEditando.estado_calculado === "ocupada"}
                    >
                      <option value="disponible">Disponible</option>
                      <option value="mantenimiento">En mantenimiento</option>
                      <option value="inactivo">Inactiva (oculta para clientes)</option>
                    </select>
                    {canchaEditando.estado_calculado === "ocupada" && (
                      <small className="hora-hint">
                        🔒 La cancha está ocupada ahora (reserva en curso). Se libera sola al
                        terminar; aquí puedes editar el resto de los datos.
                      </small>
                    )}
                  </div>
                  {form.estado !== canchaEditando.estado && (
                    <div className="form-group">
                      <label>Motivo del cambio</label>
                      <input
                        type="text"
                        maxLength={300}
                        value={form.motivo}
                        onChange={(e) => setForm({ ...form, motivo: e.target.value })}
                        placeholder="Ej: cambio de césped"
                      />
                    </div>
                  )}
                </>
              )}

              {/* GALERÍA DE IMÁGENES */}
              <div className="form-group">
                <label>
                  📷 Imágenes ({imagenesActuales.length + imagenesNuevas.length} de 8)
                </label>
                <small className="hora-hint">
                  JPG, PNG o WEBP de hasta 4 MB. Se guardan directamente en la base de datos y
                  las verán los clientes en la ficha de la cancha.
                </small>

                {imagenesActuales.length > 0 && (
                  <div className="galeria-mini">
                    {imagenesActuales.map((img) => (
                      <div key={img.id_imagen} className="galeria-mini-item">
                        <img
                          src={imagenCanchaURL(canchaEditando!.id, img.id_imagen)}
                          alt={img.nombre_archivo || "Imagen de la cancha"}
                        />
                        <button
                          type="button"
                          className="galeria-quitar"
                          title="Eliminar imagen guardada"
                          onClick={() => borrarImagenActual(img)}
                        >
                          ✖
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {imagenesNuevas.length > 0 && (
                  <div className="galeria-mini">
                    {imagenesNuevas.map((archivo, i) => (
                      <div key={`${archivo.name}-${i}`} className="galeria-mini-item">
                        <img src={URL.createObjectURL(archivo)} alt={archivo.name} />
                        <button
                          type="button"
                          className="galeria-quitar"
                          title="Quitar de la selección"
                          onClick={() => quitarImagenNueva(i)}
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
                  onChange={seleccionarArchivos}
                  disabled={imagenesActuales.length + imagenesNuevas.length >= 8}
                />
              </div>

              {canchaEditando && (
                <>
                  <details className="modal-seccion" open>
                    <summary>🕐 Horarios por día</summary>
                    <p className="hora-hint">
                      Si un día está desactivado la cancha no abre ese día. Un día sin
                      configuración propia usa el horario general de la cancha.
                    </p>

                    {/* HORARIO GENERAL: es el respaldo de los días que no tienen fila propia */}
                    <div className="horario-general">
                      <div className="form-group">
                        <label>Apertura general</label>
                        <input
                          type="time"
                          min={HORA_ATENCION_MIN}
                          max={HORA_ATENCION_MAX}
                          value={horarioGeneral.apertura}
                          onChange={(e) =>
                            setHorarioGeneral({ ...horarioGeneral, apertura: e.target.value })
                          }
                        />
                      </div>
                      <div className="form-group">
                        <label>Cierre general</label>
                        <input
                          type="time"
                          min={horarioGeneral.apertura || HORA_ATENCION_MIN}
                          max={HORA_ATENCION_MAX}
                          value={horarioGeneral.cierre}
                          onChange={(e) =>
                            setHorarioGeneral({ ...horarioGeneral, cierre: e.target.value })
                          }
                        />
                      </div>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={guardarHorarioGeneral}
                        disabled={guardandoHorarioGeneral}
                      >
                        {guardandoHorarioGeneral ? "Guardando…" : "💾 Guardar horario general"}
                      </button>
                    </div>

                    <div className="tabla-wrapper">
                      <table>
                        <thead>
                          <tr>
                            <th>Día</th>
                            <th>Apertura</th>
                            <th>Cierre</th>
                            <th>Abre</th>
                          </tr>
                        </thead>
                        <tbody>
                          {borradorHorarios.map((h) => (
                            <tr key={h.dia_semana}>
                              <td>
                                <strong>{h.dia_nombre}</strong>
                                {h.por_defecto && (
                                  <span className="cancha-dato">usa el horario general</span>
                                )}
                              </td>
                              <td>
                                <input
                                  type="time"
                                  min={HORA_ATENCION_MIN}
                                  max={HORA_ATENCION_MAX}
                                  value={h.hora_apertura || HORA_ATENCION_MIN}
                                  onChange={(e) =>
                                    editarBorrador(h.dia_semana, "hora_apertura", e.target.value)
                                  }
                                />
                              </td>
                              <td>
                                <input
                                  type="time"
                                  min={h.hora_apertura || HORA_ATENCION_MIN}
                                  max={HORA_ATENCION_MAX}
                                  value={h.hora_cierre || HORA_ATENCION_MAX}
                                  onChange={(e) =>
                                    editarBorrador(h.dia_semana, "hora_cierre", e.target.value)
                                  }
                                />
                              </td>
                              <td>
                                <label className="horario-activo">
                                  <input
                                    type="checkbox"
                                    checked={h.activo}
                                    onChange={() => alternarDia(h.dia_semana)}
                                  />{" "}
                                  {h.activo ? "Sí" : "Cerrado"}
                                </label>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="acciones">
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={guardarHorarios}
                        disabled={!hayCambiosHorarios || guardando}
                      >
                        {hayCambiosHorarios ? "Guardar horarios" : "Sin cambios"}
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => setBorradorHorarios(horarios)}
                        disabled={!hayCambiosHorarios || guardando}
                      >
                        Descartar cambios
                      </button>
                    </div>
                  </details>

                </>
              )}

              <div className="modal-actions">
                <button type="submit" className="btn-success" disabled={guardandoCancha}>
                  {guardandoCancha
                    ? "Guardando…"
                    : canchaEditando
                      ? "Guardar cambios"
                      : "Crear cancha"}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setModalCancha(false)}
                >
                  Cancelar
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppLayout>
  );
};

export default AdminCanchasPage;
