import axiosClient from "../api/axiosClient";

// ============================================================
// Servicio de canchas: CRUD, estados y galería de imágenes.
// Todas las rutas van bajo /api (el wrapper agrega el prefijo).
// ============================================================

export type EstadoCancha = "disponible" | "ocupada" | "mantenimiento" | "inactivo";
export type OrdenCancha =
  | "nombre_asc"
  | "nombre_desc"
  | "precio_asc"
  | "precio_desc"
  | "recientes";

export interface CanchaImagen {
  id_imagen: number;
  id_cancha: number;
  orden: number;
  mime_type: string;
  nombre_archivo: string | null;
  tamano_bytes: number;
  fecha_subida: string | null;
  url: string;
}

export interface Cancha {
  id: number;
  nombre: string;
  deporte: string;
  precio_hora: number;
  ubicacion?: string | null;
  estado: string;
  estado_calculado: EstadoCancha;
  reserva_habilitada: boolean;
  techada: boolean;
  superficie?: string | null;
  id_categoria: number;
  nombre_categoria?: string | null;
  categoria?: string | null;
  id_administrador: number;
  imagen_url?: string | null;
  horario_apertura?: string | null;
  horario_cierre?: string | null;
  dias_atencion?: string | null;
  total_imagenes: number;
  imagen_preview_id: number | null;
}

export interface FiltrosCanchas {
  q?: string;
  deporte?: string;
  estado?: string;
  orden?: OrdenCancha | "";
}

export interface CanchaInput {
  nombre_cancha?: string;
  tipo_deporte?: string;
  precio_hora?: number | string;
  ubicacion?: string | null;
  superficie?: string | null;
  techada?: boolean;
  id_categoria?: number;
  estado?: string;
  motivo?: string;
  horario_apertura?: string | null;
  horario_cierre?: string | null;
  dias_atencion?: string | null;
}

const prefijo = "/api/canchas";

/** Mensaje legible del backend (o genérico si la conexión falla). */
export const mensajeError = (err: unknown): string => {
  const e = err as { response?: { data?: { detalle?: string; error?: string } }; message?: string };
  return (
    e?.response?.data?.detalle ||
    e?.response?.data?.error ||
    e?.message ||
    "No se pudo completar la operación."
  );
};

/** URL de una foto de la galería (para usar en <img src>). */
export const imagenCanchaURL = (idCancha: number, idImagen: number): string =>
  `${import.meta.env.VITE_API_URL || "http://localhost:5000"}${prefijo}/${idCancha}/imagenes/${idImagen}`;

export const canchasService = {
  listar: (filtros: FiltrosCanchas = {}) => {
    const params = new URLSearchParams();
    if (filtros.q?.trim()) params.set("q", filtros.q.trim());
    if (filtros.deporte?.trim()) params.set("deporte", filtros.deporte.trim());
    if (filtros.estado) params.set("estado", filtros.estado);
    if (filtros.orden) params.set("orden", filtros.orden);
    const qs = params.toString();
    return axiosClient.get<Cancha[]>(`${prefijo}${qs ? `?${qs}` : ""}`);
  },

  obtener: (id: number) => axiosClient.get<Cancha>(`${prefijo}/${id}`),

  crear: (datos: CanchaInput) =>
    axiosClient.post<{ mensaje: string; cancha: Cancha }>(`${prefijo}`, datos),

  editar: (id: number, datos: CanchaInput) =>
    axiosClient.patch<{ mensaje: string; cancha: Cancha }>(`${prefijo}/${id}`, datos),

  cambiarEstado: (id: number, estado: string, motivo?: string) =>
    axiosClient.patch<{ mensaje: string; cancha: Cancha }>(`${prefijo}/${id}/estado`, {
      estado,
      motivo: motivo || undefined,
    }),

  eliminar: (id: number) => axiosClient.delete<{ mensaje: string }>(`${prefijo}/${id}`),

  listarImagenes: (id: number) =>
    axiosClient.get<CanchaImagen[]>(`${prefijo}/${id}/imagenes`),

  /** Sube fotos reales (multipart) que quedan guardadas en la base de datos. */
  subirImagenes: (id: number, archivos: FileList | File[]) => {
    const formData = new FormData();
    Array.from(archivos).forEach((archivo) => formData.append("imagenes", archivo));
    return axiosClient.post<{ mensaje: string; imagenes: CanchaImagen[] }>(
      `${prefijo}/${id}/imagenes`,
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
  },

  eliminarImagen: (idCancha: number, idImagen: number) =>
    axiosClient.delete<{ mensaje: string; imagenes: CanchaImagen[] }>(
      `${prefijo}/${idCancha}/imagenes/${idImagen}`,
    ),
};
