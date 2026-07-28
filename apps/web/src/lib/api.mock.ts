// Implementación mock de ApiClient — porta el `db` en memoria y las reglas de negocio del prototipo
// (Component.db / Component.api / Component.renderVals() en demo.html:945-1129,1339-1404). El día que
// exista el backend real (Fase 2 backend), esta es la única pieza que se sustituye por api.http.ts;
// las pantallas consumen datos siempre vía lib/client.ts (nunca este archivo). Única excepción: el
// evento `mockEvents` ('job-completed'), plomería exclusiva del mock que un backend real reemplazaría
// por WebSocket/polling — ver src/hooks/useJobCompletedToast.ts.
import { firebaseConfigured, getFirebaseAuth } from './firebase';
import { ApiError } from './api';
import type {
  ApiClient,
  BitacoraEntrada,
  Comprobante,
  ConfigSmtp,
  ConfigSmtpIn,
  ConfiguracionItem,
  EmpresaResumen,
  EstadoJob,
  EstatusCfdi,
  Evento,
  Job,
  NotificacionDestino,
  Page,
  Rol,
  TipoEvento,
  UsuarioAdmin,
} from './api';
import { maxMesesVentana, ventanasDe } from './domain';

// --- fixtures (db.json espejo del DDL, doc 03 — mismos datos que demo.html:945-996) -----------------

interface DbUsuario { usuario_id: number; correo: string; nombre: string; rol_global: Rol; activo: 0 | 1 }
interface DbEmpresa { empresa_id: number; nombre: string; rfc: string; activo: 0 | 1 }
interface DbUsuarioEmpresa { usuario_id: number; empresa_id: number; rol: Rol }
interface DbEfirma { efirma_id: number; empresa_id: number; num_serie: string; not_before: string; not_after: string }
interface DbJob {
  job_id: number; empresa_id: number; tipo: 'emitido' | 'recibido'; solicitud: 'CFDI' | 'METADATA';
  origen: 'manual' | 'sync'; fecha_inicial: string; fecha_final: string; id_solicitud: string | null;
  estado: EstadoJob; intentos: number; paquetes: number; mensaje: string | null; created_at: string; updated_at: string;
}
interface DbComprobante {
  comprobante_id: number; empresa_id: number; job_id: number; uuid: string; folio: string | null;
  rfc_emisor: string; rfc_receptor: string; razon_social_emisor: string; total: number; fecha_emision: string;
  tipo_comprobante: string; estatus: EstatusCfdi; estatus_verificado_at: string; xml_path: string;
}
interface DbEvento { evento_id: number; empresa_id: number; tipo: TipoEvento; detalle: Record<string, unknown>; created_at: string }
interface DbDestino { destino_id: number; empresa_id: number; correo: string; eventos_suscritos: TipoEvento[]; activo: 0 | 1 }
interface DbBitacora { bitacora_id: number; actor: string; accion: string; entidad: string; detalle: Record<string, unknown>; created_at: string }
interface DbConfigSmtp { host: string; port: number; usuario: string; password: string; remitente: string; tls: boolean }
interface DbConfig { clave: string; ejercicio_fiscal: string; valor: string | number }

const db = {
  usuarios: [
    { usuario_id: 1, correo: 'dgarcia@planjuarez.org', nombre: 'David García', rol_global: 'admin', activo: 1 },
    { usuario_id: 2, correo: 'ana@demo.test', nombre: 'Ana Torres', rol_global: 'operador', activo: 1 },
    { usuario_id: 3, correo: 'beto@demo.test', nombre: 'Beto Ruiz', rol_global: 'consulta', activo: 1 },
  ] as DbUsuario[],
  empresas: [
    { empresa_id: 7, nombre: 'Comercializadora Demo Norte', rfc: 'EKU9003173C9', activo: 1 },
    { empresa_id: 8, nombre: 'Servicios Empresariales Demo', rfc: 'XAXX010101000', activo: 1 },
    { empresa_id: 9, nombre: 'Empresa Inactiva Demo', rfc: 'XEXX010101000', activo: 0 },
  ] as DbEmpresa[],
  usuario_empresa: [
    { usuario_id: 2, empresa_id: 7, rol: 'operador' },
    { usuario_id: 2, empresa_id: 8, rol: 'operador' },
    { usuario_id: 3, empresa_id: 7, rol: 'consulta' },
  ] as DbUsuarioEmpresa[],
  efirmas: [
    { efirma_id: 1, empresa_id: 7, num_serie: '30001000000400002325', not_before: '2024-08-01 00:00:00', not_after: '2028-08-01 00:00:00' },
    { efirma_id: 2, empresa_id: 8, num_serie: '30001000000400009911', not_before: '2022-08-10 00:00:00', not_after: '2026-08-10 00:00:00' },
  ] as DbEfirma[],
  jobs: [
    { job_id: 41, empresa_id: 7, tipo: 'recibido', solicitud: 'CFDI', origen: 'manual', fecha_inicial: '2025-01-01', fecha_final: '2025-12-31', id_solicitud: 'd4e5f6a7-0001', estado: 'DESCARGADO', intentos: 3, paquetes: 2, mensaje: null, created_at: '2026-07-20 09:00:00', updated_at: '2026-07-20 11:42:00' },
    { job_id: 42, empresa_id: 7, tipo: 'recibido', solicitud: 'CFDI', origen: 'sync', fecha_inicial: '2026-07-01', fecha_final: '2026-07-26', id_solicitud: 'd4e5f6a7-0002', estado: 'EN_PROCESO', intentos: 5, paquetes: 0, mensaje: null, created_at: '2026-07-27 02:00:00', updated_at: '2026-07-27 08:15:00' },
    { job_id: 43, empresa_id: 7, tipo: 'emitido', solicitud: 'CFDI', origen: 'manual', fecha_inicial: '2024-01-01', fecha_final: '2024-12-31', id_solicitud: null, estado: 'ERROR', intentos: 8, paquetes: 0, mensaje: 'Rechazo del SAT: límite de solicitudes en proceso', created_at: '2026-07-25 10:00:00', updated_at: '2026-07-25 16:20:00' },
    { job_id: 44, empresa_id: 8, tipo: 'recibido', solicitud: 'METADATA', origen: 'sync', fecha_inicial: '2026-07-01', fecha_final: '2026-07-26', id_solicitud: 'a1b2c3-0044', estado: 'TERMINADA', intentos: 2, paquetes: 1, mensaje: null, created_at: '2026-07-27 02:00:00', updated_at: '2026-07-27 03:05:00' },
  ] as DbJob[],
  comprobantes: [
    { comprobante_id: 1001, empresa_id: 7, job_id: 41, uuid: 'AAAA1111-BBBB-2222-CCCC-3333DDDD4444', folio: '4589', rfc_emisor: 'AAA010101AAA', rfc_receptor: 'EKU9003173C9', razon_social_emisor: 'Proveedora del Norte Demo', total: 15080.0, fecha_emision: '2025-03-12 10:30:00', tipo_comprobante: 'I', estatus: 'vigente', estatus_verificado_at: '2026-07-26 02:10:00', xml_path: 'e7/2025/AAAA1111.xml' },
    { comprobante_id: 1002, empresa_id: 7, job_id: 41, uuid: 'EEEE5555-FFFF-6666-AAAA-7777BBBB8888', folio: '1234', rfc_emisor: 'BBB020202BB2', rfc_receptor: 'EKU9003173C9', razon_social_emisor: 'Insumos Fronterizos Demo', total: 8920.5, fecha_emision: '2025-05-08 16:05:00', tipo_comprobante: 'I', estatus: 'cancelado', estatus_verificado_at: '2026-07-26 02:10:00', xml_path: 'e7/2025/EEEE5555.xml' },
    { comprobante_id: 1003, empresa_id: 7, job_id: 41, uuid: '9999AAAA-1111-2222-3333-4444BBBB5555', folio: null, rfc_emisor: 'CCC030303CC3', rfc_receptor: 'EKU9003173C9', razon_social_emisor: 'Comercial EFOS Demo', total: 45000.0, fecha_emision: '2024-11-20 12:00:00', tipo_comprobante: 'I', estatus: 'vigente', estatus_verificado_at: '2026-07-26 02:10:00', xml_path: 'e7/2024/9999AAAA.xml' },
  ] as DbComprobante[],
  lista69b: [{ rfc: 'CCC030303CC3', situacion: 'definitivo' }],
  eventos: [
    { evento_id: 501, empresa_id: 7, tipo: 'efos', detalle: { rfc: 'CCC030303CC3', situacion: 'definitivo', uuids: ['9999AAAA-1111-2222-3333-4444BBBB5555'], total_afectado: 45000.0 }, created_at: '2026-07-26 03:00:00' },
    { evento_id: 502, empresa_id: 7, tipo: 'cancelacion_tardia', detalle: { uuid: 'EEEE5555-FFFF-6666-AAAA-7777BBBB8888', mes_emision: '2025-05', detectado: '2026-07-26' }, created_at: '2026-07-26 03:00:00' },
    { evento_id: 503, empresa_id: 8, tipo: 'efirma_por_vencer', detalle: { not_after: '2026-08-10', dias_restantes: 14 }, created_at: '2026-07-27 02:05:00' },
  ] as DbEvento[],
  destinos: [
    { destino_id: 1, empresa_id: 7, correo: 'conta@demo.test', eventos_suscritos: ['efos', 'cancelacion_tardia', 'error_descarga'], activo: 1 },
  ] as DbDestino[],
  bitacora: [
    { bitacora_id: 9001, actor: 'ana@demo.test', accion: 'alta_efirma', entidad: 'empresa:7', detalle: { num_serie: '30001000000400002325' }, created_at: '2026-07-19 12:00:00' },
    { bitacora_id: 9002, actor: 'worker', accion: 'uso_boveda', entidad: 'job:41', detalle: { empresa_id: 7 }, created_at: '2026-07-20 09:01:00' },
  ] as DbBitacora[],
  configuracion: [
    { clave: 'max_meses_ventana', ejercicio_fiscal: '2026', valor: 12 },
    { clave: 'umbral_vigencia_dias', ejercicio_fiscal: 'vigente', valor: 15 },
    { clave: 'hora_sync', ejercicio_fiscal: 'vigente', valor: '02:00' },
  ] as DbConfig[],
  configSmtp: null as DbConfigSmtp | null,
};

const CONFIG_DESC: Record<string, string> = {
  max_meses_ventana: 'Meses máximos por ventana de solicitud al SAT',
  umbral_vigencia_dias: 'Días de anticipación para avisar que la e.firma vence',
  hora_sync: 'Hora del sync diario automático',
};

const EFIRMA_ERRORES: Record<string, string> = {
  EFIRMA_NO_ABRE: 'La contraseña no abre la llave privada. Verifica que corresponda al archivo .key seleccionado.',
  RFC_NO_COINCIDE: 'El RFC del certificado no coincide con el RFC de la empresa. Revisa que sea la e.firma correcta.',
  EFIRMA_VENCIDA: 'El certificado está vencido. Renueva la e.firma en el SAT antes de registrarla.',
};

let nextJobId = 45;
let nextEfirmaId = 90;
let nextDestinoId = 100;
let nextBitacoraId = 9003;
const tareas = new Map<string, { estado: 'pendiente' | 'completada' | 'fallida'; descarga_url?: string }>();

/** Emite 'job-completed' cuando avanzarJob() llega a DESCARGADO — ver src/hooks/useJobCompletedToast.ts. */
export const mockEvents = new EventTarget();

function paginate<T>(rows: T[], page = 1, perPage = 50): Page<T> {
  const start = (page - 1) * perPage;
  return { data: rows.slice(start, start + perPage), page, per_page: perPage, total: rows.length };
}

function usuarioActual(): DbUsuario | null {
  if (!firebaseConfigured) return null;
  const email = getFirebaseAuth()?.currentUser?.email ?? null;
  if (!email) return null;
  return db.usuarios.find((u) => u.correo === email) ?? null;
}

function esAdmin(u: DbUsuario | null): boolean {
  return !!u && u.rol_global === 'admin';
}

function rolEn(u: DbUsuario | null, empresaId: number): Rol | null {
  if (esAdmin(u)) return 'admin';
  if (!u) return null;
  return db.usuario_empresa.find((x) => x.usuario_id === u.usuario_id && x.empresa_id === empresaId)?.rol ?? null;
}

function requireUsuario(): DbUsuario {
  const u = usuarioActual();
  if (!u) throw new ApiError(401, 'SIN_SESION', 'No hay una sesión activa.');
  return u;
}

function requireRol(empresaId: number, minimo: Rol): DbUsuario {
  const u = requireUsuario();
  const rol = rolEn(u, empresaId);
  const orden: Record<Rol, number> = { consulta: 0, operador: 1, admin: 2 };
  if (rol === null || orden[rol] < orden[minimo]) {
    throw new ApiError(403, 'SIN_PERMISO', 'Tu cuenta no tiene permisos asignados sobre esta empresa.');
  }
  return u;
}

function empresaResumen(e: DbEmpresa, rol: Rol): EmpresaResumen {
  const ef = db.efirmas.find((x) => x.empresa_id === e.empresa_id) ?? null;
  return {
    empresa_id: e.empresa_id,
    nombre: e.nombre,
    rfc: e.rfc,
    rol,
    activo: !!e.activo,
    efirma: ef ? { presente: true, not_after: ef.not_after } : { presente: false, not_after: null },
  };
}

function jobToApi(j: DbJob): Job {
  return {
    job_id: j.job_id,
    tipo: j.tipo,
    solicitud: j.solicitud,
    origen: j.origen,
    desde: j.fecha_inicial,
    hasta: j.fecha_final,
    estado: j.estado,
    intentos: j.intentos,
    paquetes: j.paquetes,
    mensaje: j.mensaje,
    updated_at: j.updated_at,
    id_solicitud: j.id_solicitud,
  };
}

function comprobanteToApi(c: DbComprobante): Comprobante {
  return {
    comprobante_id: c.comprobante_id,
    uuid: c.uuid,
    folio: c.folio,
    rfc_emisor: c.rfc_emisor,
    rfc_receptor: c.rfc_receptor,
    razon_social_emisor: c.razon_social_emisor,
    total: c.total,
    fecha_emision: c.fecha_emision,
    tipo_comprobante: c.tipo_comprobante,
    estatus: c.estatus,
    estatus_verificado_at: c.estatus_verificado_at,
    xml_path: c.xml_path,
  };
}

function stamp(): string {
  // Reloj simulado: ancla en "ahora" para que las nuevas filas ordenen después de las fixtures.
  return new Date().toISOString().slice(0, 19).replace('T', ' ');
}

function logBitacora(actor: string, accion: string, entidad: string, detalle: Record<string, unknown>) {
  db.bitacora.unshift({ bitacora_id: nextBitacoraId++, actor, accion, entidad, detalle, created_at: stamp() });
}

/**
 * Progresión simulada SOLICITADO→EN_PROCESO→TERMINADA→DESCARGADO (demo.html:1088-1097). El refresco de
 * la tabla de jobs lo hace el polling de useJobs() (refetchInterval) — aquí solo se dispara el evento
 * para el toast de "Job #id descargado", que el polling por sí solo no puede distinguir.
 */
function avanzarJob(jobId: number) {
  const paso = (estado: EstadoJob, ms: number, extra?: Partial<DbJob>) =>
    setTimeout(() => {
      const j = db.jobs.find((x) => x.job_id === jobId);
      if (!j) return;
      Object.assign(j, { estado, intentos: j.intentos + 1, updated_at: stamp(), ...extra });
    }, ms);
  paso('EN_PROCESO', 2200);
  paso('TERMINADA', 5200, { paquetes: 1 });
  setTimeout(() => {
    const j = db.jobs.find((x) => x.job_id === jobId);
    if (!j) return;
    Object.assign(j, { estado: 'DESCARGADO' as EstadoJob, mensaje: null, updated_at: stamp() });
    mockEvents.dispatchEvent(new CustomEvent('job-completed', { detail: { jobId } }));
  }, 8000);
}

export const apiMock: ApiClient = {
  async me() {
    const u = requireUsuario();
    const empresas = db.empresas
      .map((e) => ({ e, rol: rolEn(u, e.empresa_id) }))
      .filter((x): x is { e: DbEmpresa; rol: Rol } => x.rol !== null)
      .map(({ e, rol }) => empresaResumen(e, rol));
    return { usuario_id: u.usuario_id, correo: u.correo, nombre: u.nombre, rol_global: u.rol_global, empresas };
  },

  async listarEmpresas() {
    const u = requireUsuario();
    return db.empresas
      .map((e) => ({ e, rol: rolEn(u, e.empresa_id) }))
      .filter((x): x is { e: DbEmpresa; rol: Rol } => x.rol !== null)
      .map(({ e, rol }) => empresaResumen(e, rol));
  },

  async crearEmpresa(input) {
    requireUsuario();
    if (db.empresas.some((e) => e.rfc === input.rfc)) throw new ApiError(409, 'RFC_DUPLICADO', 'Ya existe una empresa con ese RFC.');
    const empresa_id = Math.max(...db.empresas.map((e) => e.empresa_id)) + 1;
    db.empresas.push({ empresa_id, nombre: input.nombre, rfc: input.rfc, activo: 1 });
    return empresaResumen(db.empresas[db.empresas.length - 1], 'admin');
  },

  async actualizarEmpresa(empresaId, input) {
    const u = requireUsuario();
    const empresa = db.empresas.find((e) => e.empresa_id === empresaId);
    if (!empresa) throw new ApiError(404, 'NO_ENCONTRADO', 'No encontrado.');
    empresa.activo = input.activo ? 1 : 0;
    logBitacora(u.correo, 'editar_empresa', `empresa:${empresaId}`, { activo: input.activo });
    return empresaResumen(empresa, 'admin');
  },

  async eliminarEmpresa(empresaId) {
    const u = requireUsuario();
    const empresa = db.empresas.find((e) => e.empresa_id === empresaId);
    if (!empresa) throw new ApiError(404, 'NO_ENCONTRADO', 'No encontrado.');
    const tieneHistorial =
      db.efirmas.some((e) => e.empresa_id === empresaId) ||
      db.jobs.some((j) => j.empresa_id === empresaId) ||
      db.comprobantes.some((c) => c.empresa_id === empresaId);
    if (tieneHistorial) {
      throw new ApiError(409, 'EMPRESA_CON_HISTORIAL', "Esta empresa ya tiene e.firma, descargas o comprobantes registrados; no se puede eliminar. Usa 'Desactivar' para darla de baja sin perder el historial.");
    }
    db.empresas = db.empresas.filter((e) => e.empresa_id !== empresaId);
    logBitacora(u.correo, 'eliminar_empresa', `empresa:${empresaId}`, { rfc: empresa.rfc });
  },

  async subirEfirma(empresaId, { password, escenarioDemo }) {
    const u = requireRol(empresaId, 'operador');
    void password;
    const escenario = escenarioDemo ?? 'exito';
    if (escenario !== 'exito') {
      throw new ApiError(422, escenario, EFIRMA_ERRORES[escenario]);
    }
    const not_before = stamp();
    const notAfterDate = new Date();
    notAfterDate.setFullYear(notAfterDate.getFullYear() + 4);
    const not_after = notAfterDate.toISOString().slice(0, 19).replace('T', ' ');
    const num_serie = '3000100000040000' + String(7000 + empresaId);
    db.efirmas = db.efirmas.filter((e) => e.empresa_id !== empresaId);
    db.efirmas.push({ efirma_id: nextEfirmaId++, empresa_id: empresaId, num_serie, not_before, not_after });
    logBitacora(u.correo, 'alta_efirma', `empresa:${empresaId}`, { num_serie });
    return { num_serie, not_before, not_after, dias_para_vencer: 1460 };
  },

  async obtenerEfirma(empresaId) {
    requireRol(empresaId, 'consulta');
    const ef = db.efirmas.find((e) => e.empresa_id === empresaId);
    return ef ? { num_serie: ef.num_serie, not_before: ef.not_before, not_after: ef.not_after } : null;
  },

  async eliminarEfirma(empresaId) {
    const u = requireRol(empresaId, 'operador');
    const empresa = db.empresas.find((e) => e.empresa_id === empresaId);
    db.efirmas = db.efirmas.filter((e) => e.empresa_id !== empresaId);
    logBitacora(u.correo, 'baja_efirma', `empresa:${empresaId}`, { rfc: empresa?.rfc });
  },

  async crearDescarga(empresaId, { tipo, solicitud, desde, hasta, simVencidaDemo }) {
    const u = requireRol(empresaId, 'operador');
    if (simVencidaDemo) {
      throw new ApiError(422, 'EFIRMA_VENCIDA', 'La e.firma de esta empresa está vencida; el SAT rechazará la solicitud. Registra una vigente en la bóveda para continuar.');
    }
    if (!db.efirmas.some((e) => e.empresa_id === empresaId)) {
      throw new ApiError(422, 'EFIRMA_AUSENTE', 'Esta empresa no tiene e.firma registrada en la bóveda.');
    }
    const maxMeses = maxMesesVentana(await this.listarConfiguracion());
    const ventanas = ventanasDe(desde, hasta, maxMeses);
    const created_at = stamp();
    const nuevos: DbJob[] = ventanas.map((v, i) => ({
      job_id: nextJobId + i,
      empresa_id: empresaId,
      tipo,
      solicitud,
      origen: 'manual',
      fecha_inicial: v.desde,
      fecha_final: v.hasta,
      id_solicitud: null,
      estado: 'SOLICITADO',
      intentos: 0,
      paquetes: 0,
      mensaje: null,
      created_at,
      updated_at: created_at,
    }));
    db.jobs.unshift(...nuevos);
    const job_ids = nuevos.map((n) => n.job_id);
    nextJobId += nuevos.length;
    logBitacora(u.correo, 'crear_descarga', `empresa:${empresaId}`, { job_ids, tipo, solicitud });
    nuevos.forEach((n) => avanzarJob(n.job_id));
    return { job_ids, ventanas: ventanas.length };
  },

  async listarJobs(empresaId, f) {
    requireRol(empresaId, 'consulta');
    let rows = db.jobs.filter((j) => j.empresa_id === empresaId);
    if (f?.estado) rows = rows.filter((j) => j.estado === f.estado);
    if (f?.origen) rows = rows.filter((j) => j.origen === f.origen);
    return paginate(rows.map(jobToApi), f?.page);
  },

  async reintentarJob(empresaId, jobId) {
    const u = requireRol(empresaId, 'operador');
    const j = db.jobs.find((x) => x.job_id === jobId && x.empresa_id === empresaId);
    if (!j) throw new ApiError(404, 'NO_ENCONTRADO', 'El job no existe o no pertenece a esta empresa.');
    if (j.estado !== 'ERROR') throw new ApiError(409, 'TRANSICION_ILEGAL', 'El job no está en estado ERROR.');
    Object.assign(j, { estado: 'SOLICITADO' as EstadoJob, mensaje: null, intentos: j.intentos + 1, updated_at: stamp() });
    logBitacora(u.correo, 'reintento_job', `job:${jobId}`, { empresa_id: empresaId });
    avanzarJob(jobId);
  },

  async listarComprobantes(empresaId, f) {
    requireRol(empresaId, 'consulta');
    let rows = db.comprobantes.filter((c) => c.empresa_id === empresaId);
    if (f?.estatus) rows = rows.filter((c) => c.estatus === f.estatus);
    if (f?.tipo_comprobante) rows = rows.filter((c) => c.tipo_comprobante === f.tipo_comprobante);
    if (f?.desde) rows = rows.filter((c) => c.fecha_emision.slice(0, 10) >= f.desde!);
    if (f?.direccion) {
      const rfcEmpresa = db.empresas.find((e) => e.empresa_id === empresaId)?.rfc;
      rows = rows.filter((c) => (f.direccion === 'emitido' ? c.rfc_emisor === rfcEmpresa : c.rfc_receptor === rfcEmpresa));
    }
    const q = (f?.q ?? '').trim().toLowerCase();
    if (q) rows = rows.filter((c) => [c.uuid, c.rfc_emisor, c.razon_social_emisor, c.folio ?? ''].join(' ').toLowerCase().includes(q));
    return paginate(rows.map(comprobanteToApi), f?.page);
  },

  async validarLote(empresaId) {
    requireRol(empresaId, 'operador');
    const tarea_id = crypto.randomUUID();
    tareas.set(tarea_id, { estado: 'pendiente' });
    setTimeout(() => tareas.set(tarea_id, { estado: 'completada' }), 1200);
    return { tarea_id };
  },

  async exportarExcel(empresaId) {
    requireRol(empresaId, 'consulta');
    const tarea_id = crypto.randomUUID();
    tareas.set(tarea_id, { estado: 'pendiente' });
    setTimeout(() => tareas.set(tarea_id, { estado: 'completada', descarga_url: `/mock-descargas/comprobantes_empresa${empresaId}.xlsx` }), 1400);
    return { tarea_id };
  },

  async estadoTarea(tareaId) {
    return tareas.get(tareaId) ?? { estado: 'fallida' };
  },

  async descargarComprobantePdf(empresaId) {
    requireRol(empresaId, 'consulta');
    return new Blob(['%PDF-1.4 (mock)'], { type: 'application/pdf' });
  },

  async descargarComprobanteDetalle(empresaId) {
    requireRol(empresaId, 'consulta');
    return new Blob(['%PDF-1.4 (mock detalle)'], { type: 'application/pdf' });
  },

  async descargarComprobanteZip(empresaId) {
    requireRol(empresaId, 'consulta');
    return new Blob(['PK (mock zip)'], { type: 'application/zip' });
  },

  async descargarLoteZip(empresaId) {
    requireRol(empresaId, 'consulta');
    const tarea_id = crypto.randomUUID();
    tareas.set(tarea_id, { estado: 'pendiente' });
    setTimeout(() => tareas.set(tarea_id, { estado: 'completada', descarga_url: `/mock-descargas/lote_empresa${empresaId}.zip` }), 1200);
    return { tarea_id };
  },

  async listarEventos(empresaId, f) {
    requireRol(empresaId, 'consulta');
    let rows = db.eventos.filter((e) => e.empresa_id === empresaId);
    if (f?.tipo) rows = rows.filter((e) => e.tipo === f.tipo);
    return paginate(rows as Evento[], f?.page);
  },

  async obtenerNotificaciones(empresaId) {
    requireRol(empresaId, 'consulta');
    const destinos: NotificacionDestino[] = db.destinos
      .filter((d) => d.empresa_id === empresaId)
      .map((d) => ({ correo: d.correo, eventos: d.eventos_suscritos }));
    return { destinos };
  },

  async guardarNotificaciones(empresaId, destinos) {
    const u = requireRol(empresaId, 'operador');
    db.destinos = db.destinos.filter((d) => d.empresa_id !== empresaId);
    destinos.forEach((d) => db.destinos.push({ destino_id: nextDestinoId++, empresa_id: empresaId, correo: d.correo, eventos_suscritos: d.eventos, activo: 1 }));
    logBitacora(u.correo, 'guardar_notificaciones', `empresa:${empresaId}`, { destinos: destinos.length });
  },

  async listarUsuarios(): Promise<UsuarioAdmin[]> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede ver esta pantalla.');
    return db.usuarios.map((x) => ({
      usuario_id: x.usuario_id,
      correo: x.correo,
      nombre: x.nombre,
      rol_global: x.rol_global,
      activo: !!x.activo,
      permisos: db.usuario_empresa
        .filter((a) => a.usuario_id === x.usuario_id)
        .map((a) => ({ empresa_id: a.empresa_id, empresa_nombre: db.empresas.find((e) => e.empresa_id === a.empresa_id)?.nombre ?? '—', rol: a.rol })),
    }));
  },

  async listarConfiguracion(): Promise<ConfiguracionItem[]> {
    requireUsuario();
    return db.configuracion.map((c) => ({ clave: c.clave, ejercicio_fiscal: c.ejercicio_fiscal, valor: String(c.valor), descripcion: CONFIG_DESC[c.clave] ?? '' }));
  },

  async listarBitacora(f): Promise<Page<BitacoraEntrada>> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede ver esta pantalla.');
    return paginate(db.bitacora as BitacoraEntrada[], f?.page);
  },

  async obtenerConfigSmtp(): Promise<ConfigSmtp> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede ver esta pantalla.');
    const c = db.configSmtp;
    if (!c) return { configurado: false, host: null, port: null, usuario: null, remitente: null, tls: null };
    return { configurado: true, host: c.host, port: c.port, usuario: c.usuario, remitente: c.remitente, tls: c.tls };
  },

  async guardarConfigSmtp(input: ConfigSmtpIn): Promise<void> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede realizar esta acción.');
    const password = input.password || db.configSmtp?.password;
    if (!password) throw new ApiError(422, 'SMTP_SIN_CONTRASENA', 'Se requiere una contraseña de aplicación la primera vez que se configura el correo.');
    db.configSmtp = { host: input.host, port: input.port, usuario: input.usuario, password, remitente: input.remitente, tls: input.tls };
    logBitacora(u.correo, 'guardar_config_smtp', 'config_smtp:1', { host: input.host, usuario: input.usuario });
  },

  async probarConfigSmtp(input: ConfigSmtpIn & { correo_destino: string }): Promise<void> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede realizar esta acción.');
    const password = input.password || db.configSmtp?.password;
    if (!password) throw new ApiError(422, 'SMTP_SIN_CONTRASENA', 'Escribe la contraseña de aplicación para probar (todavía no hay ninguna guardada).');
    // Mock: no hay servidor SMTP real que probar — simula éxito siempre.
  },
};
