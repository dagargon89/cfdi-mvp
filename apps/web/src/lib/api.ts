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

export interface MetadataPreview {
  headers: string[];
  filas: string[][];
  total: number;
  page: number;
  per_page: number;
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
  aprobado: boolean;
  permisos: { empresa_id: number; empresa_nombre: string; rol: Rol }[];
}

export interface ConfiguracionItem {
  clave: string;
  ejercicio_fiscal: string;
  valor: string;
  descripcion: string;
}

export interface Automatizaciones {
  sync_diaria: boolean;
  lista_69b: boolean;
  re_verificar: boolean;
  limpieza: boolean;
}

/** Añadido tras el freeze (2026-07-28) — RF-NOT-01: correo saliente configurable desde la UI
 * (Configuración → Correo), no por variable de entorno. `configurado=false` cuando nadie lo
 * ha guardado todavía; la contraseña de aplicación nunca viaja de vuelta desde el backend. */
export interface ConfigSmtp {
  configurado: boolean;
  host: string | null;
  port: number | null;
  usuario: string | null;
  remitente: string | null;
  tls: boolean | null;
}

export interface ConfigSmtpIn {
  host: string;
  port: number;
  usuario: string;
  /** vacío/omitido conserva la contraseña ya guardada (editar host/remitente sin reteclearla). */
  password?: string;
  remitente: string;
  tls: boolean;
}

export interface BitacoraEntrada {
  bitacora_id: number;
  actor: string;
  accion: string;
  entidad: string;
  detalle: Record<string, unknown>;
  created_at: string;
}

/* ------------------------------------------------------------------------------------------
 * Configuración fiscal (doc 05 §8bis) — añadido post-freeze (2026-08-06, informes CFDI fase 3).
 *
 * Invariante que gobierna todo este bloque: **un valor sin confirmar no calcula.** Sembrar o
 * sincronizar *proponen*; solo una persona confirma, y los informes leen solo lo confirmado.
 *
 * **Los importes viajan como cadena, jamás como número.** El backend rechaza con 422 un importe
 * que llegue como número JSON: se convierte pasando por `float` y pierde precisión antes de que
 * el servidor pueda revisarlo (`12345678901.123456` llega ya redondeado). Por eso `valor`,
 * `factor_prima_vacacional` e `importe` son `string` en las dos direcciones — no los conviertas
 * a `number` ni para mostrarlos: la escala con la que vuelven ("117.310000") es la que está
 * almacenada, y `Number()` la perdería.
 * ---------------------------------------------------------------------------------------- */

/** Procedencia de un valor: quién lo puso ahí. Ninguna de las tres confirma por sí sola. */
export type OrigenValor = 'SEMILLA' | 'MANUAL' | 'SINCRONIZADO';

/** Un tramo de `param_fiscal` con su vigencia, su procedencia y su estado de confirmación. */
export interface ParametroFiscal {
  clave: string;
  ejercicio: number;
  /** Cadena, nunca número — ver la nota de arriba. */
  valor: string;
  vigencia_desde: string;
  vigencia_hasta: string | null;
  origen: OrigenValor;
  /** Texto libre; las semillas incluyen la URL del boletín/DOF dentro del propio texto. */
  fuente: string;
  sincronizado_en: string | null;
  confirmado: boolean;
  confirmado_por: string | null;
  confirmado_en: string | null;
}

/** `claves_sin_valor` es el tercer estado: claves conocidas de las que no hay **ni propuesta**. */
export interface ConfiguracionFiscal {
  parametros: ParametroFiscal[];
  claves_sin_valor: string[];
}

/** Captura o corrección manual. Guarda con `origen: MANUAL` y **sin** confirmar. */
export interface ParametroFiscalIn {
  valor: string;
  vigencia_desde: string;
  vigencia_hasta?: string | null;
  fuente: string;
  /** Nulo/omitido = el año de `vigencia_desde`. */
  ejercicio?: number | null;
}

export type ZonaSalarial = 'GENERAL' | 'ZLFN';

/** Política laboral de una organización. Los tres campos viajan siempre, incluso nulos: "no
 * configurado" es un estado que la pantalla tiene que mostrar (degrada B-10), no una ausencia. */
export interface ConfiguracionEmpresa {
  empresa_id: number;
  zona_salarial: ZonaSalarial | null;
  dias_aguinaldo: number | null;
  factor_prima_vacacional: string | null;
}

export type ConfiguracionEmpresaIn = Omit<ConfiguracionEmpresa, 'empresa_id'>;

export type CategoriaProvision = 'AGUINALDO' | 'VACACIONES' | 'PRIMA_VACACIONAL' | 'NO_APLICA';

export interface MapeoDepartamento {
  departamento_texto: string;
  centro_costo: string;
}

export interface MapeoConceptoProvision {
  naturaleza: string;
  tipo: string;
  clave: string;
  categoria: CategoriaProvision;
}

/** El `PUT` **reemplaza las dos listas completas**: lo que no venga deja de existir. */
export interface MapeosEmpresa {
  departamentos: MapeoDepartamento[];
  conceptos_provision: MapeoConceptoProvision[];
}

/** Un concepto que la nómina de la empresa **emitió de verdad**. Existe para que configurar sea
 * reconocer y elegir: nadie conoce de memoria las claves internas de su sistema de nómina. */
export interface ConceptoObservado {
  naturaleza: string;
  tipo: string;
  /** Nula cuando el complemento no la trae: entonces el concepto no se puede clasificar. */
  clave: string | null;
  /** El texto libre que escribió el patrón — es lo que la persona reconoce. */
  concepto: string | null;
  descripcion_sat: string | null;
  comprobantes: number;
  /** Cadena, nunca número — ver la nota de arriba. */
  importe: string;
  categoria: CategoriaProvision | null;
}

export interface DepartamentoObservado {
  departamento_texto: string;
  comprobantes: number;
  centro_costo: string | null;
}

/** `sin_clasificar` es el marcador que la pantalla necesita para decir "te faltan N": mientras
 * no sea cero, B-08 no puede distinguir "no se pagó aguinaldo" de "sí se pagó y no sé dónde". */
export interface ObservadosEmpresa {
  conceptos: ConceptoObservado[];
  departamentos: DepartamentoObservado[];
  sin_clasificar: number;
  sin_mapear: number;
}

/** Entrada del catálogo de informes (doc: spec §7.2). `parametros` es un JSON Schema — la pantalla
 * de Informes construye el formulario a partir de `parametros.properties`/`required`, sin conocer
 * de antemano qué informe es (B-02 hoy, ocho más en fases 2-3, ninguno hardcodeado en la UI). */
export interface InformeCatalogo {
  clave: string;
  nombre: string;
  grupo: string;
  descripcion: string;
  parametros: Record<string, unknown>;
}

export interface ApiClient {
  // Sesión (prioridad 1)
  me(): Promise<{ usuario_id: number; correo: string; nombre: string; rol_global: Rol; empresas: EmpresaResumen[] }>;
  estadoBootstrap(): Promise<{ needs_bootstrap: boolean }>;
  crearAdminBootstrap(body: { correo: string; nombre: string; password: string; token: string }): Promise<void>;
  // Empresas
  listarEmpresas(): Promise<EmpresaResumen[]>;
  crearEmpresa(input: { nombre: string; rfc: string }): Promise<EmpresaResumen>;
  /** Añadido tras el freeze — RF-EMP-02 (baja lógica), doc 05 §3 PATCH /v1/empresas/{id}. Solo admin. */
  actualizarEmpresa(empresaId: number, input: { activo: boolean }): Promise<EmpresaResumen>;
  /** Añadido tras el freeze (2026-07-28) — borrado real, solo si la empresa nunca tuvo e.firma/jobs/
   * comprobantes (doc 04 §4.4: el historial fiscal nunca se borra vía API). 409 EMPRESA_CON_HISTORIAL si no. */
  eliminarEmpresa(empresaId: number): Promise<void>;
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
  listarJobs(empresaId: number, f?: { estado?: EstadoJob; origen?: 'manual' | 'sync'; solicitud?: 'CFDI' | 'METADATA'; page?: number; per_page?: number }): Promise<Page<Job>>;
  reintentarJob(empresaId: number, jobId: number): Promise<void>;
  // Comprobantes (prioridades 2–3)
  listarComprobantes(
    empresaId: number,
    /** `direccion` añadido tras el freeze (2026-07-28) — relativo al RFC de la propia
     * empresa, no de la contraparte (distinto de `rfc_contraparte`, que no forma parte de
     * este contrato). */
    f?: { desde?: string; hasta?: string; estatus?: EstatusCfdi; tipo_comprobante?: string; direccion?: 'emitido' | 'recibido'; q?: string; page?: number; per_page?: number },
  ): Promise<Page<Comprobante>>;
  validarLote(empresaId: number, alcance: 'no_verificados' | 'todos' | { uuids: string[] }): Promise<{ tarea_id: string }>;
  exportarExcel(empresaId: number, f?: Record<string, string>): Promise<{ tarea_id: string }>;
  estadoTarea(tareaId: string): Promise<{ estado: 'pendiente' | 'completada' | 'fallida'; descarga_url?: string }>;
  /** Añadidos tras el freeze (2026-07-28) — RF-RES-03/D2: además del XML, el PDF (representación
   * impresa) y el "Detalle del CFDI" (constancia de validación) también deben poder descargarse,
   * individuales, juntos en un `.zip` por comprobante, o por lote desde la tabla. */
  descargarComprobantePdf(empresaId: number, comprobanteId: number): Promise<Blob>;
  descargarComprobanteDetalle(empresaId: number, comprobanteId: number): Promise<Blob>;
  descargarComprobanteZip(empresaId: number, comprobanteId: number): Promise<Blob>;
  descargarLoteZip(empresaId: number, comprobanteIds: number[]): Promise<{ tarea_id: string }>;
  obtenerMetadata(empresaId: number, jobId: number, page?: number): Promise<MetadataPreview>;
  descargarMetadataCsv(empresaId: number, jobId: number): Promise<Blob>;
  // Informes (doc spec §7.2): catálogo + generación asíncrona, misma tarea que exportarExcel/validarLote.
  listarInformes(): Promise<InformeCatalogo[]>;
  generarInforme(empresaId: number, clave: string, parametros: Record<string, unknown>): Promise<{ tarea_id: string }>;
  // Vigilancia y notificaciones (prioridad 3)
  listarEventos(empresaId: number, f?: { tipo?: TipoEvento; page?: number }): Promise<Page<Evento>>;
  obtenerNotificaciones(empresaId: number): Promise<{ destinos: NotificacionDestino[] }>;
  guardarNotificaciones(empresaId: number, destinos: NotificacionDestino[]): Promise<void>;
  // Administración (añadido en el freeze — doc 05 §2/§8, consumido por P10/P11)
  listarUsuarios(): Promise<UsuarioAdmin[]>;
  registrarUsuario(body: { nombre: string }): Promise<void>;
  actualizarUsuario(id: number, body: { activo?: boolean; rol_global?: Rol; aprobado?: boolean }): Promise<void>;
  guardarPermisos(id: number, permisos: { empresa_id: number; rol: Rol }[]): Promise<void>;
  eliminarUsuario(id: number): Promise<void>;
  listarConfiguracion(): Promise<ConfiguracionItem[]>;
  listarBitacora(f?: { page?: number; per_page?: number }): Promise<Page<BitacoraEntrada>>;
  /** Añadidos tras el freeze (2026-07-28) — RF-NOT-01, Configuración → Correo. */
  obtenerConfigSmtp(): Promise<ConfigSmtp>;
  guardarConfigSmtp(input: ConfigSmtpIn): Promise<void>;
  obtenerAutomatizaciones(): Promise<Automatizaciones>;
  guardarAutomatizaciones(input: Automatizaciones): Promise<Automatizaciones>;
  probarConfigSmtp(input: ConfigSmtpIn & { correo_destino: string }): Promise<void>;
  /* Configuración fiscal (doc 05 §8bis) — añadido post-freeze (2026-08-06, informes fase 3).
   * Los tres primeros son **solo administrador**: la configuración fiscal es política federal
   * y aplica a todas las empresas. Los de empresa son política laboral suya: leer pide
   * consulta, escribir pide operador — el mismo reparto que el resto de la API. */
  listarConfiguracionFiscal(): Promise<ConfiguracionFiscal>;
  /** Captura o corrige un tramo. **No confirma**: queda `MANUAL` y sin confirmar, a propósito. */
  capturarParametroFiscal(clave: string, input: ParametroFiscalIn): Promise<ParametroFiscal>;
  /** Confirma **el valor que se está confirmando**: si no coincide con el almacenado el servidor
   * responde 409 `VALOR_CAMBIO` (la propuesta cambió entre que se pintó la pantalla y el clic). */
  confirmarParametroFiscal(clave: string, input: { vigencia_desde: string; valor: string }): Promise<ParametroFiscal>;
  obtenerConfiguracionEmpresa(empresaId: number): Promise<ConfiguracionEmpresa>;
  guardarConfiguracionEmpresa(empresaId: number, input: ConfiguracionEmpresaIn): Promise<ConfiguracionEmpresa>;
  obtenerMapeosEmpresa(empresaId: number): Promise<MapeosEmpresa>;
  /** Reemplaza las dos listas completas: hay que mandar también la que no se está editando. */
  guardarMapeosEmpresa(empresaId: number, input: MapeosEmpresa): Promise<MapeosEmpresa>;
  obtenerConceptosObservados(empresaId: number): Promise<ObservadosEmpresa>;
}
