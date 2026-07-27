// Contrato único de datos — Hub_CFDI_docs/05-api/05_especificacion_api.md §9 (congelado en el cierre de Fase 1).
// Ningún componente/hook debe leer datos de otra fuente; siempre a través de un ApiClient (mock hoy, HTTP en Fase 2 backend).

/** Forma estándar de error de la API (doc 05 §1.4) — tanto el mock como la futura implementación HTTP la lanzan. */
export class ApiError extends Error {
  status: number;
  codigo: string;

  constructor(status: number, codigo: string, mensaje: string) {
    super(mensaje);
    this.name = 'ApiError';
    this.status = status;
    this.codigo = codigo;
  }
}

export type Rol = 'admin' | 'operador' | 'consulta';
export type EstadoJob = 'NUEVO' | 'SOLICITADO' | 'EN_PROCESO' | 'TERMINADA' | 'DESCARGADO' | 'ERROR';
export type EstatusCfdi = 'vigente' | 'cancelado' | 'no_verificado';
export type TipoEvento = 'cancelacion_tardia' | 'efos' | 'efirma_por_vencer' | 'error_descarga' | 'resumen_sync';

export interface Page<T> {
  data: T[];
  page: number;
  per_page: number;
  total: number;
}

export interface EmpresaResumen {
  empresa_id: number;
  nombre: string;
  rfc: string;
  rol: Rol;
  activo: boolean;
  efirma: { presente: boolean; not_after: string | null } | null;
}

export interface Job {
  job_id: number;
  tipo: 'emitido' | 'recibido';
  solicitud: 'CFDI' | 'METADATA';
  origen: 'manual' | 'sync';
  desde: string;
  hasta: string;
  estado: EstadoJob;
  intentos: number;
  paquetes: number;
  mensaje: string | null;
  updated_at: string;
  /** Añadido en el freeze: el drawer de detalle (doc 09 P6) lo muestra y GET /jobs/{id} lo incluye (doc 05 §5). */
  id_solicitud: string | null;
}

export interface Comprobante {
  comprobante_id: number;
  uuid: string;
  folio: string | null;
  rfc_emisor: string;
  rfc_receptor: string;
  razon_social_emisor: string | null;
  total: number | null;
  fecha_emision: string | null;
  tipo_comprobante: string | null;
  estatus: EstatusCfdi;
  estatus_verificado_at: string | null;
  /** Añadido en el freeze: el drawer de comprobante (doc 09 P7) lo necesita para el enlace de descarga. */
  xml_path: string | null;
}

export interface Evento {
  evento_id: number;
  tipo: TipoEvento;
  detalle: Record<string, unknown>;
  created_at: string;
}

export interface NotificacionDestino {
  correo: string;
  eventos: TipoEvento[];
}

/**
 * Añadido en el freeze — el demo valida P10 (Usuarios) y P11 (Config·Bitácora); doc 05 §9 dejaba
 * estos módulos "se añaden al ApiClient en el freeze si el demo los valida". Las mutaciones de
 * usuarios (alta/permisos/activar) ya están descritas en doc 05 §2 pero el demo no las ejercita
 * (P10 es solo lectura) — se dejan fuera de este freeze hasta que haya una UI real que las use.
 */
export interface UsuarioAdmin {
  usuario_id: number;
  correo: string;
  nombre: string;
  rol_global: Rol;
  activo: boolean;
  permisos: { empresa_id: number; empresa_nombre: string; rol: Rol }[];
}

export interface ConfiguracionItem {
  clave: string;
  ejercicio_fiscal: string;
  valor: string;
  descripcion: string;
}

export interface BitacoraEntrada {
  bitacora_id: number;
  actor: string;
  accion: string;
  entidad: string;
  detalle: Record<string, unknown>;
  created_at: string;
}

export interface ApiClient {
  // Sesión (prioridad 1)
  me(): Promise<{ usuario_id: number; correo: string; nombre: string; rol_global: Rol; empresas: EmpresaResumen[] }>;
  // Empresas
  listarEmpresas(): Promise<EmpresaResumen[]>;
  crearEmpresa(input: { nombre: string; rfc: string }): Promise<EmpresaResumen>;
  // Bóveda (prioridad 1)
  subirEfirma(
    empresaId: number,
    files: {
      cer: File;
      key: File;
      password: string;
      /** Demo-only (VITE_DEMO_CONTROLS): fuerza la respuesta del backend simulado — no existe en el contrato real. */
      escenarioDemo?: 'exito' | 'EFIRMA_NO_ABRE' | 'RFC_NO_COINCIDE' | 'EFIRMA_VENCIDA';
    },
  ): Promise<{ num_serie: string; not_before: string; not_after: string; dias_para_vencer: number }>;
  obtenerEfirma(empresaId: number): Promise<{ num_serie: string; not_before: string; not_after: string } | null>;
  eliminarEfirma(empresaId: number): Promise<void>;
  // Descargas (prioridad 2)
  crearDescarga(
    empresaId: number,
    input: {
      tipo: 'emitido' | 'recibido';
      solicitud: 'CFDI' | 'METADATA';
      desde: string;
      hasta: string;
      /** Demo-only (VITE_DEMO_CONTROLS): fuerza 422 EFIRMA_VENCIDA — no existe en el contrato real. */
      simVencidaDemo?: boolean;
    },
  ): Promise<{ job_ids: number[]; ventanas: number }>;
  listarJobs(empresaId: number, f?: { estado?: EstadoJob; origen?: 'manual' | 'sync'; page?: number }): Promise<Page<Job>>;
  reintentarJob(empresaId: number, jobId: number): Promise<void>;
  // Comprobantes (prioridades 2–3)
  listarComprobantes(
    empresaId: number,
    f?: { desde?: string; hasta?: string; estatus?: EstatusCfdi; tipo_comprobante?: string; q?: string; page?: number },
  ): Promise<Page<Comprobante>>;
  validarLote(empresaId: number, alcance: 'no_verificados' | 'todos' | { uuids: string[] }): Promise<{ tarea_id: string }>;
  exportarExcel(empresaId: number, f?: Record<string, string>): Promise<{ tarea_id: string }>;
  estadoTarea(tareaId: string): Promise<{ estado: 'pendiente' | 'completada' | 'fallida'; descarga_url?: string }>;
  // Vigilancia y notificaciones (prioridad 3)
  listarEventos(empresaId: number, f?: { tipo?: TipoEvento; page?: number }): Promise<Page<Evento>>;
  obtenerNotificaciones(empresaId: number): Promise<{ destinos: NotificacionDestino[] }>;
  guardarNotificaciones(empresaId: number, destinos: NotificacionDestino[]): Promise<void>;
  // Administración (añadido en el freeze — doc 05 §2/§8, consumido por P10/P11)
  listarUsuarios(): Promise<UsuarioAdmin[]>;
  listarConfiguracion(): Promise<ConfiguracionItem[]>;
  listarBitacora(f?: { page?: number }): Promise<Page<BitacoraEntrada>>;
}
