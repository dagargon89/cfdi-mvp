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
  AlertaVigencia,
  Automatizaciones,
  BaseExencion,
  CatalogoPercepciones,
  BitacoraEntrada,
  CategoriaProvision,
  Comprobante,
  ComprobacionTarifa,
  ConceptoObservado,
  ConfigSmtp,
  ConfigSmtpIn,
  ConfiguracionEmpresa,
  ConfiguracionEmpresaIn,
  ConfiguracionFiscal,
  ConfiguracionItem,
  EmpresaResumen,
  EstadoJob,
  EstatusCfdi,
  Evento,
  ImportacionTarifas,
  InformeCatalogo,
  Job,
  MapeosEmpresa,
  MarcaPercepcion,
  MarcaPercepcionConfirmarIn,
  MarcaPercepcionIn,
  MarcasPercepcion,
  MetadataPreview,
  NotificacionDestino,
  ObservadosEmpresa,
  OrigenTarifaIsr,
  OrigenValor,
  Page,
  ParametroFiscal,
  ParametroFiscalIn,
  PeriodicidadTarifaIsr,
  Rol,
  TarifaIsr,
  TarifaIsrRenglon,
  TarifaIsrRenglonIn,
  TipoEvento,
  UsuarioAdmin,
  ZonaSalarial,
} from './api';
import { maxMesesVentana, ventanasDe } from './domain';

// --- fixtures (db.json espejo del DDL, doc 03 — mismos datos que demo.html:945-996) -----------------

interface DbUsuario { usuario_id: number; correo: string; nombre: string; rol_global: Rol; activo: 0 | 1; aprobado: 0 | 1 }
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
interface DbParamFiscal {
  clave: string; ejercicio: number; valor: string; vigencia_desde: string; vigencia_hasta: string | null;
  origen: OrigenValor; fuente: string; sincronizado_en: string | null;
  confirmado_por: string | null; confirmado_en: string | null;
}
interface DbMarcaPercepcion {
  tipo_percepcion: string; es_ingreso_ordinario: boolean; base_exencion: BaseExencion;
  factor_exencion: string | null; integra_sbc: boolean; es_provisionable: boolean;
  sujeto_a_tope_conjunto: boolean; multiplicador_no_derivable: boolean; nota_revision: string | null;
  confirmado_por: string | null; confirmado_en: string | null;
}
interface DbConfiguracionEmpresa { empresa_id: number; zona_salarial: ZonaSalarial | null; dias_aguinaldo: number | null; factor_prima_vacacional: string | null }
interface DbMapDepartamento { empresa_id: number; departamento_texto: string; centro_costo: string }
interface DbMapConceptoProvision { empresa_id: number; naturaleza: string; tipo: string; clave: string; categoria: CategoriaProvision }
interface DbNominaObservada {
  empresa_id: number; naturaleza: string; tipo: string; clave: string | null; concepto: string;
  descripcion_sat: string | null; comprobantes: number; importe: string; departamento: string;
}
/** El recibo real contra el que se compara una tarifa (doc 05 §8bis, tarifa ISR). Se guarda
 * aparte de la tarifa porque no cambia cuando alguien corrige un renglón — lo que cambia es el
 * ISR *calculado con* la tarifa, que `comprobacionTarifaASalida` recalcula contra los renglones
 * vigentes en cada lectura, igual que hace `app.services.comprobacion_tarifa` en el servidor. */
interface DbComprobacionInsumo {
  uuid: string; fecha_inicial_pago: string | null; fecha_final_pago: string | null;
  num_empleado: string | null; dias_pagados: string | null; gravado: string; isr_timbrado: string;
  advertencias: string[];
}
interface DbTarifaIsr {
  ejercicio: number; periodicidad: PeriodicidadTarifaIsr; periodicidad_cfdi: string | null;
  origen: OrigenTarifaIsr; fuente: string; documento_sha256: string | null; encabezado: string;
  importado_en: string; confirmado_por: string | null; confirmado_en: string | null;
  aplica_a_la_nomina: boolean; renglones: TarifaIsrRenglonIn[];
  comprobacion_insumo: DbComprobacionInsumo | null;
}

const db = {
  usuarios: [
    { usuario_id: 1, correo: 'dgarcia@planjuarez.org', nombre: 'David García', rol_global: 'admin', activo: 1, aprobado: 1 },
    { usuario_id: 2, correo: 'ana@demo.test', nombre: 'Ana Torres', rol_global: 'operador', activo: 1, aprobado: 1 },
    { usuario_id: 3, correo: 'beto@demo.test', nombre: 'Beto Ruiz', rol_global: 'consulta', activo: 1, aprobado: 1 },
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
  automatizaciones: { sync_diaria: true, lista_69b: true, re_verificar: true, limpieza: true, vigencia_fiscal: true } as Automatizaciones,
  // Lo que la tarea `revisar_vigencia_fiscal` dejó en `configuracion` en su último intento. El
  // mock arranca con **el estado real de hoy**: falta el token de Banxico, así que la
  // sincronización no corre y la alarma lo dice. No es una avería inventada para la demo.
  sync_banxico_estado: { fallo: 'falta BANXICO_TOKEN', cuando: '2026-08-06 13:30:04' } as { fallo: string; cuando: string } | null,
  // Configuración fiscal (doc 05 §8bis). Hay **un parámetro en cada uno de los tres estados**
  // a propósito, para poder ver la pantalla completa sin backend: UMA_DIARIA 2025 confirmada,
  // UMA_DIARIA 2026 y el salario mínimo propuestos, y cuatro claves sin ningún valor.
  param_fiscal: [
    {
      clave: 'UMA_DIARIA', ejercicio: 2025, valor: '113.140000', vigencia_desde: '2025-02-01', vigencia_hasta: '2026-01-31',
      origen: 'SEMILLA', fuente: 'INEGI, boletín UMA 2025 — https://www.inegi.org.mx/temas/uma/',
      sincronizado_en: null, confirmado_por: 'dgarcia@planjuarez.org', confirmado_en: '2025-02-03 10:12:00',
    },
    {
      clave: 'UMA_DIARIA', ejercicio: 2026, valor: '117.310000', vigencia_desde: '2026-02-01', vigencia_hasta: null,
      origen: 'SEMILLA', fuente: 'INEGI, boletín UMA 2026 — https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/uma/uma2026.pdf',
      sincronizado_en: null, confirmado_por: null, confirmado_en: null,
    },
    {
      // El caso que `claves_sin_valor` no puede contar y que la alarma existe para gritar: un
      // valor **confirmado** que ya caducó. Está en verde en su tarjeta, calcula, y es del
      // ejercicio pasado. Sin este renglón el mock no podría enseñar el motivo `CADUCADO`.
      clave: 'SALARIO_MINIMO_ZLFN', ejercicio: 2025, valor: '419.880000', vigencia_desde: '2025-01-01', vigencia_hasta: null,
      origen: 'SEMILLA', fuente: 'DOF 20-12-2024, resolución del CONASAMI (Zona Libre de la Frontera Norte 2025) — https://www.dof.gob.mx/',
      sincronizado_en: null, confirmado_por: 'dgarcia@planjuarez.org', confirmado_en: '2025-01-08 11:05:00',
    },
    {
      clave: 'SALARIO_MINIMO_GENERAL', ejercicio: 2026, valor: '315.040000', vigencia_desde: '2026-01-01', vigencia_hasta: null,
      origen: 'SEMILLA', fuente: 'DOF 09-12-2025, resolución del CONASAMI (salarios mínimos 2026) — https://www.dof.gob.mx/nota_detalle.php?codigo=5775534&fecha=09%2F12%2F2025',
      sincronizado_en: null, confirmado_por: null, confirmado_en: null,
    },
  ] as DbParamFiscal[],
  // Marcas del art. 93 (doc 05 §8bis). **Un subconjunto de los 44 tipos a propósito**: los que
  // faltan son el tercer estado —tipo del catálogo del SAT del que no hay ni marcas capturadas— y
  // sin él la pantalla no se podría ver completa sin backend. Los valores son los de la semilla
  // real (`config/fiscal/catalogo_percepcion.yaml`), incluidas sus dudas declaradas.
  //
  // Hay **una marca con nota y una sin ella** en cada estado que importa, y **una confirmada**
  // ('021') que en la base real no existe: con 0 de 44 confirmadas no habría forma de ver el chip
  // verde ni el texto de "quién respondió por esto" sin escribir en producción.
  catalogo_percepcion_marca: [
    {
      tipo_percepcion: '001', es_ingreso_ordinario: true, base_exencion: 'NINGUNA', factor_exencion: null,
      integra_sbc: true, es_provisionable: false, sujeto_a_tope_conjunto: false, multiplicador_no_derivable: false,
      nota_revision: null, confirmado_por: null, confirmado_en: null,
    },
    {
      tipo_percepcion: '002', es_ingreso_ordinario: true, base_exencion: 'UMA_DIAS', factor_exencion: '30.0000',
      integra_sbc: true, es_provisionable: true, sujeto_a_tope_conjunto: false, multiplicador_no_derivable: false,
      nota_revision: null, confirmado_por: null, confirmado_en: null,
    },
    {
      tipo_percepcion: '005', es_ingreso_ordinario: true, base_exencion: 'PORCENTAJE', factor_exencion: '100.0000',
      integra_sbc: false, es_provisionable: false, sujeto_a_tope_conjunto: false, multiplicador_no_derivable: false,
      nota_revision: 'las dos marcas son condicionales y las condiciones no vienen en el CFDI (aportación pareja, tope del 13%, número de retiros al año). Si el fondo no cumple, el concepto es gravado Y integra al SBC: las dos marcas cambian a la vez.',
      confirmado_por: null, confirmado_en: null,
    },
    {
      tipo_percepcion: '015', es_ingreso_ordinario: true, base_exencion: 'PORCENTAJE', factor_exencion: '100.0000',
      integra_sbc: false, es_provisionable: false, sujeto_a_tope_conjunto: true, multiplicador_no_derivable: false,
      nota_revision: 'está SUJETA AL TOPE CONJUNTO de previsión social del penúltimo párrafo del art. 93 (no está en la lista de exceptuados). `PORCENTAJE 100` es la exención en bruto; quien calcule tiene que aplicarle el tope de 1 UMA anual junto con los demás conceptos de previsión social del mismo trabajador, o exentará de más.',
      confirmado_por: null, confirmado_en: null,
    },
    {
      tipo_percepcion: '019', es_ingreso_ordinario: true, base_exencion: 'PORCENTAJE', factor_exencion: '50.0000',
      integra_sbc: false, es_provisionable: false, sujeto_a_tope_conjunto: false, multiplicador_no_derivable: false,
      nota_revision: 'el renglón captura SOLO el 50% del caso general y se pierden tres cosas que el modelo no puede expresar: (a) el 100% para quien gana el salario mínimo, (b) el tope de 5 UMA por semana, (c) que solo aplica dentro del límite de horas de la LFT. El `integra_sbc: false` supone que las horas extra están dentro de los márgenes legales.',
      confirmado_por: null, confirmado_en: null,
    },
    {
      tipo_percepcion: '021', es_ingreso_ordinario: true, base_exencion: 'UMA_DIAS', factor_exencion: '15.0000',
      integra_sbc: true, es_provisionable: true, sujeto_a_tope_conjunto: false, multiplicador_no_derivable: false,
      nota_revision: null, confirmado_por: 'dgarcia@planjuarez.org', confirmado_en: '2026-08-05 09:20:00',
    },
    {
      tipo_percepcion: '025', es_ingreso_ordinario: false, base_exencion: 'UMA_DIAS', factor_exencion: '90.0000',
      // Uno de los nueve: el mock lo trae en `true` a propósito, para que la pantalla se pueda
      // desarrollar contra el caso que hace que B-03 deje el tope vacío.
      integra_sbc: false, es_provisionable: false, sujeto_a_tope_conjunto: false, multiplicador_no_derivable: true,
      nota_revision: 'el factor es "90 UMA por cada AÑO DE SERVICIO" (art. 93-XIII) y los años de servicio no vienen en el CFDI de nómina.',
      confirmado_por: null, confirmado_en: null,
    },
    {
      tipo_percepcion: '029', es_ingreso_ordinario: true, base_exencion: 'PORCENTAJE', factor_exencion: '100.0000',
      integra_sbc: false, es_provisionable: false, sujeto_a_tope_conjunto: true, multiplicador_no_derivable: false,
      nota_revision: 'está SUJETA AL TOPE CONJUNTO de previsión social del penúltimo párrafo del art. 93. Además, el art. 27-VI de la LSS excluye los vales de despensa del SBC solo hasta el 40% de la UMA; el excedente sí integra, y este campo es booleano y no puede expresar un tope.',
      confirmado_por: null, confirmado_en: null,
    },
  ] as DbMarcaPercepcion[],
  configuracion_empresa: [] as DbConfiguracionEmpresa[],
  map_departamento: [] as DbMapDepartamento[],
  map_concepto_provision: [] as DbMapConceptoProvision[],
  // Lo que la nómina de la empresa emitió de verdad (lo que en el backend son cuatro consultas
  // agregadas sobre los CFDI de tipo N). El renglón sin clave está aquí a propósito: existe en
  // los datos reales, no se puede clasificar, y por eso tampoco cuenta como pendiente.
  nomina_observada: [
    { empresa_id: 7, naturaleza: 'P', tipo: '001', clave: 'P001', concepto: 'SUELDO', descripcion_sat: 'Sueldos, Salarios Rayas y Jornales', comprobantes: 48, importe: '1284500.00', departamento: 'ADMINISTRACION' },
    { empresa_id: 7, naturaleza: 'P', tipo: '002', clave: 'P020', concepto: 'AGUINALDO', descripcion_sat: 'Gratificación Anual (Aguinaldo)', comprobantes: 12, importe: '186300.00', departamento: 'ADMINISTRACION' },
    { empresa_id: 7, naturaleza: 'P', tipo: '021', clave: 'P030', concepto: 'PRIMA VACACIONAL', descripcion_sat: 'Prima Vacacional', comprobantes: 9, importe: '41200.00', departamento: 'OPERACIONES' },
    { empresa_id: 7, naturaleza: 'P', tipo: '029', clave: null, concepto: 'FONDO DE AHORRO', descripcion_sat: 'Fondo de ahorro', comprobantes: 6, importe: '30000.00', departamento: 'OPERACIONES' },
    { empresa_id: 7, naturaleza: 'D', tipo: '001', clave: 'D010', concepto: 'PRESTAMO PERSONAL', descripcion_sat: 'Seguridad social', comprobantes: 4, importe: '12800.00', departamento: 'OPERACIONES' },
  ] as DbNominaObservada[],
  // Tarifa del ISR (Anexo 8 de la RMF) — añadido post-freeze (2026-08-10, tarifa ISR). Dos
  // tarifas del mismo documento importado, en los dos estados que la pantalla necesita ver sin
  // backend: la quincenal **confirmada**, con una comprobación de diferencia de unos pesos
  // (subsidio al empleo que el CFDI no desglosa); la mensual **propuesta**, sin comprobación
  // (ningún recibo mensual elegible en este universo de prueba). Los renglones de las dos
  // cumplen las reglas del Anexo I.1: el primero arranca en 0.01 con cuota fija 0.00, cada uno
  // empieza un centavo después del límite superior del anterior, la tasa crece renglón a
  // renglón y el último se queda sin límite superior.
  tarifa_isr: [
    {
      ejercicio: 2026, periodicidad: 'DIAS_15', periodicidad_cfdi: '04', origen: 'IMPORTADA',
      fuente: 'Anexo 8 de la Resolución Miscelánea Fiscal para 2026, DOF 27-12-2025 — https://www.dof.gob.mx/',
      documento_sha256: 'a3f1c9d8e2b47650f9a1c3d5e7b9f2a4c6e8b0d2f4a6c8e0b2d4f6a8c0e2b4d6',
      encabezado: 'TARIFA APLICABLE PARA EL CÁLCULO DE LOS PAGOS PROVISIONALES QUINCENALES CORRESPONDIENTES A 2026, PERSONAS FÍSICAS QUE OBTENGAN INGRESOS POR SALARIOS',
      importado_en: '2026-08-01 09:00:00', confirmado_por: 'dgarcia@planjuarez.org', confirmado_en: '2026-08-01 09:15:00',
      aplica_a_la_nomina: true,
      renglones: [
        { renglon: 1, limite_inferior: '0.01', limite_superior: '368.10', cuota_fija: '0.00', tasa_excedente: '0.019200' },
        { renglon: 2, limite_inferior: '368.11', limite_superior: '3124.35', cuota_fija: '7.07', tasa_excedente: '0.064000' },
        { renglon: 3, limite_inferior: '3124.36', limite_superior: null, cuota_fija: '183.47', tasa_excedente: '0.108800' },
      ],
      comprobacion_insumo: {
        uuid: 'B7E1A2F4-9C3D-4E10-8B2A-6F5D9C1E4A70', fecha_inicial_pago: '2026-07-01', fecha_final_pago: '2026-07-15',
        num_empleado: '014', dias_pagados: '15', gravado: '4500.00', isr_timbrado: '331.00',
        advertencias: ['El CFDI no desglosa el subsidio para el empleo aplicado en el periodo; una diferencia de unos pesos frente al cálculo con la tarifa es normal.'],
      },
    },
    {
      ejercicio: 2026, periodicidad: 'MENSUAL', periodicidad_cfdi: '05', origen: 'IMPORTADA',
      fuente: 'Anexo 8 de la Resolución Miscelánea Fiscal para 2026, DOF 27-12-2025 — https://www.dof.gob.mx/',
      documento_sha256: 'a3f1c9d8e2b47650f9a1c3d5e7b9f2a4c6e8b0d2f4a6c8e0b2d4f6a8c0e2b4d6',
      encabezado: 'TARIFA APLICABLE PARA EL CÁLCULO DE LOS PAGOS PROVISIONALES MENSUALES CORRESPONDIENTES A 2026, PERSONAS FÍSICAS QUE OBTENGAN INGRESOS POR SALARIOS',
      importado_en: '2026-08-01 09:00:00', confirmado_por: null, confirmado_en: null,
      aplica_a_la_nomina: false,
      renglones: [
        { renglon: 1, limite_inferior: '0.01', limite_superior: '746.04', cuota_fija: '0.00', tasa_excedente: '0.019200' },
        { renglon: 2, limite_inferior: '746.05', limite_superior: '6332.05', cuota_fija: '14.32', tasa_excedente: '0.064000' },
        { renglon: 3, limite_inferior: '6332.06', limite_superior: null, cuota_fija: '371.82', tasa_excedente: '0.108800' },
      ],
      // `null`: ningún CFDI de nómina mensual elegible en este universo de prueba — el tercer
      // estado que la pantalla tiene que poder mostrar además de "hay comprobación".
      comprobacion_insumo: null,
    },
  ] as DbTarifaIsr[],
};

const CONFIG_DESC: Record<string, string> = {
  max_meses_ventana: 'Meses máximos por ventana de solicitud al SAT',
  umbral_vigencia_dias: 'Días de anticipación para avisar que la e.firma vence',
  hora_sync: 'Hora del sync diario automático',
};

/** Catálogo de informes (doc spec §7.2) — hoy solo B-02; las fases 2-3 solo agregan entradas
 * aquí, la pantalla de Informes no cambia. `parametros` es el JSON Schema real que arma el
 * formulario del lado del cliente. */
const CATALOGO_INFORMES: InformeCatalogo[] = [
  {
    clave: 'B-02',
    nombre: 'Nómina agrupada por conceptos del patrón',
    grupo: 'B',
    descripcion: 'Una fila por CFDI de nómina, con una columna por cada concepto del patrón.',
    parametros: {
      properties: {
        fecha_desde: { type: 'string', format: 'date' },
        fecha_hasta: { type: 'string', format: 'date' },
        tipo_nomina: { enum: ['O', 'E', 'AMBOS'], default: 'AMBOS' },
        incluir_cancelados: { type: 'boolean', default: false },
        enmascarar_datos_personales: { type: 'boolean', default: true },
      },
      required: ['fecha_desde', 'fecha_hasta'],
    },
  },
];

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

// --- configuración fiscal: las MISMAS reglas del backend, no una versión relajada ---------------
// En la fase 1 un mock permisivo escondió un 403 real hasta la verificación en vivo. Aquí las
// validaciones son las de `app/services/configuracion_fiscal.py` y `app/api/v1/schemas.py`: si el
// mock deja pasar algo que el backend rechaza, la pantalla se diseña contra una realidad falsa.

const CLAVES_PARAM_FISCAL = ['SALARIO_MINIMO_GENERAL', 'SALARIO_MINIMO_ZLFN', 'TIPO_CAMBIO_USD', 'UMA_ANUAL', 'UMA_DIARIA', 'UMA_MENSUAL'];
const DECIMALES_MAXIMOS = 6;
/** `Numeric(18,6)` = 18 dígitos en total, 6 decimales → 12 enteros. */
const ENTEROS_MAXIMOS = 12;
/** `Field(min_length=1, max_length=500)` del esquema `ParamFiscalGuardarIn`. */
const FUENTE_MAXIMA = 500;

/** Normaliza un importe en texto para poder compararlo sin pasar por `Number` (que es justo lo
 * que el contrato prohíbe): "117.31" y "117.310000" son el mismo valor. `null` si no es número. */
function importeNormalizado(texto: string): string | null {
  const t = texto.trim();
  if (!/^[+-]?\d+(\.\d+)?$/.test(t)) return null;
  const negativo = t.startsWith('-');
  const [enteros, decimales = ''] = t.replace(/^[+-]/, '').split('.');
  const e = enteros.replace(/^0+(?=\d)/, '');
  const d = decimales.replace(/0+$/, '');
  const cifra = `${e}${d ? `.${d}` : ''}`;
  return negativo && cifra !== '0' ? `-${cifra}` : cifra;
}

/** Un importe que llega como número JSON ya perdió precisión: el backend responde 422 y el mock
 * también, porque es un error que solo se ve si alguien lo comete. */
function exigeImporteCadena(valor: unknown): string {
  if (typeof valor === 'number') {
    throw new ApiError(422, 'CONFIGURACION_INVALIDA', 'manda el importe entre comillas ("117.31"), no como número JSON: un número se convierte pasando por float y pierde precisión antes de que el servidor pueda revisarlo.');
  }
  if (typeof valor !== 'string') throw new ApiError(422, 'CONFIGURACION_INVALIDA', '`valor` tiene que venir como cadena.');
  return valor;
}

function exigeParamFiscalValido(clave: string, body: ParametroFiscalIn): string {
  if (!CLAVES_PARAM_FISCAL.includes(clave)) {
    throw new ApiError(422, 'CONFIGURACION_INVALIDA', `\`clave\` = '${clave}' no es una clave conocida de param_fiscal. Esperadas: ${CLAVES_PARAM_FISCAL.join(', ')}.`);
  }
  const bruto = exigeImporteCadena(body.valor);
  const valor = importeNormalizado(bruto);
  if (valor === null) throw new ApiError(422, 'CONFIGURACION_INVALIDA', `\`valor\` no es un número válido (llegó '${bruto}').`);
  if (valor.startsWith('-') || valor === '0') {
    throw new ApiError(422, 'CONFIGURACION_INVALIDA', `\`valor\` debe ser positivo (llegó ${valor}). Un cero o un negativo en un tope de exención o en un salario mínimo produce cálculos falsos sin que nadie los note.`);
  }
  const decimales = valor.includes('.') ? valor.split('.')[1].length : 0;
  if (decimales > DECIMALES_MAXIMOS) {
    throw new ApiError(422, 'CONFIGURACION_INVALIDA', `\`valor\` trae ${decimales} decimales y la columna guarda ${DECIMALES_MAXIMOS} (llegó ${valor}). Redondearlo en silencio guardaría una cifra distinta de la que revisaste; recórtalo tú a 6 decimales.`);
  }
  // `Numeric(18,6)`: 12 dígitos enteros como máximo. Sin esta comprobación el mock aceptaba lo
  // que el backend rechaza, y una pantalla probada solo contra el mock se diseña creyendo que ese
  // 422 no existe (en la fase 1 un mock permisivo escondió un 403 hasta la verificación en vivo).
  const enteros = valor.replace('-', '').split('.')[0].length;
  if (enteros > ENTEROS_MAXIMOS) {
    // Mismo texto que el servidor, palabra por palabra: la pantalla lo muestra tal cual, así que
    // si el mock parafraseara, se diseñaría contra un mensaje que nadie va a leer nunca.
    throw new ApiError(422, 'CONFIGURACION_INVALIDA', `\`valor\` no cabe en la columna (llegó ${valor}; el máximo son ${ENTEROS_MAXIMOS} dígitos enteros). Sin este rechazo MySQL revienta a media escritura con un error que no dice qué renglón fue.`);
  }
  if (!body.fuente.trim()) {
    throw new ApiError(422, 'CONFIGURACION_INVALIDA', '`fuente` no puede ir vacía: sin ella nadie puede revisar de dónde salió el valor.');
  }
  if (body.fuente.length > FUENTE_MAXIMA) {
    throw new ApiError(422, 'DATOS_INVALIDOS', `fuente: String should have at most ${FUENTE_MAXIMA} characters`);
  }
  if (body.vigencia_hasta && body.vigencia_hasta < body.vigencia_desde) {
    throw new ApiError(422, 'CONFIGURACION_INVALIDA', `\`vigencia_hasta\` (${body.vigencia_hasta}) es anterior a \`vigencia_desde\` (${body.vigencia_desde}).`);
  }
  return bruto;
}

/** Dos tramos se solapan si ninguno termina antes de que empiece el otro (`vigencia_hasta` nula
 * = abierto). Misma regla que `_se_solapan` del servicio: el esquema no la puede sostener. */
function seSolapan(aDesde: string, aHasta: string | null, bDesde: string, bHasta: string | null): boolean {
  return (aHasta === null || aHasta >= bDesde) && (bHasta === null || bHasta >= aDesde);
}

// --- la alarma de vigencia (doc 05 §8bis) --------------------------------------------------------
// Mismas reglas que `app/services/sincronizacion_fiscal.py`, incluida la distinción entre los tres
// motivos que hablan de **un valor** y los tres que hablan de **la maquinaria**. Se recalcula en
// cada `GET` porque depende de la fecha de hoy: una alerta cacheada de anoche diría "al día" el 1
// de febrero por la mañana.
//
// `TIPO_CAMBIO_USD` queda **fuera** a propósito: cambia cada día hábil, no por decreto en fecha
// fija, y meterlo dejaría la alarma permanentemente encendida (que es como se aprende a
// ignorarla). Su ausencia total sigue siendo visible por `claves_sin_valor`.
const FECHAS_DE_ACTUALIZACION: Record<string, [number, number]> = {
  UMA_DIARIA: [2, 1],
  UMA_MENSUAL: [2, 1],
  UMA_ANUAL: [2, 1],
  SALARIO_MINIMO_GENERAL: [1, 1],
  SALARIO_MINIMO_ZLFN: [1, 1],
};

/** La última fecha de actualización de la clave que **ya pasó** (hoy incluido). En enero de 2026
 * la de la UMA es el 1 de febrero de *2025*: el valor de febrero de 2025 sigue vigente y no hay
 * nada que reclamar. Ese matiz separa "estás desactualizado" de "todavía no toca". */
function fechaDeActualizacionAplicable(clave: string, hoy: string): string | null {
  const calendario = FECHAS_DE_ACTUALIZACION[clave];
  if (!calendario) return null;
  const [mes, dia] = calendario;
  const anio = Number(hoy.slice(0, 4));
  const delAnio = `${anio}-${String(mes).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
  return delAnio <= hoy ? delAnio : `${anio - 1}-${String(mes).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
}

function alertaDeClave(clave: string, tramos: DbParamFiscal[], hoy: string): AlertaVigencia | null {
  const esperada = fechaDeActualizacionAplicable(clave, hoy);
  if (esperada === null) return null;
  if (tramos.length === 0) {
    return {
      clave, motivo: 'AUSENTE', vigencia_desde: null, fecha_esperada: esperada,
      detalle: `No hay ningún valor capturado para \`${clave}\`, y su fecha de actualización (${esperada}) ya pasó. Captúralo desde Configuración → Fiscal con su fuente oficial; mientras tanto los informes que dependen de él salen degradados.`,
    };
  }
  const masReciente = (lista: DbParamFiscal[]) =>
    lista.reduce<DbParamFiscal | null>((a, b) => (a === null || b.vigencia_desde > a.vigencia_desde ? b : a), null);
  const confirmado = masReciente(tramos.filter((t) => t.confirmado_en !== null));
  const propuesto = masReciente(tramos.filter((t) => t.confirmado_en === null));
  const alDia = confirmado !== null && confirmado.vigencia_desde >= esperada;

  if (!alDia) {
    // Hay una propuesta que **sí** cubre el periodo: confirmarla resuelve el problema, y eso es
    // un clic. Distinguirlo de "ve a capturar" es lo que hace la alarma accionable.
    if (propuesto !== null && propuesto.vigencia_desde >= esperada) {
      return {
        clave, motivo: 'SIN_CONFIRMAR', vigencia_desde: propuesto.vigencia_desde, fecha_esperada: esperada,
        detalle: `\`${clave}\` tiene un valor propuesto (${propuesto.valor}, vigente desde ${propuesto.vigencia_desde}, fuente: ${propuesto.fuente}) esperando confirmación. Hasta que alguien lo revise y lo confirme no entra a ningún cálculo.`,
      };
    }
    // Lo único que hay es de antes de la fecha de actualización. Aunque esté sin confirmar, el
    // motivo es la caducidad: confirmar una propuesta de 2025 no arregla que falte la de 2026.
    const actual = confirmado ?? propuesto;
    if (!actual) return null;
    const estado = confirmado !== null ? 'confirmado' : 'propuesto y sin confirmar';
    return {
      clave, motivo: 'CADUCADO', vigencia_desde: actual.vigencia_desde, fecha_esperada: esperada,
      detalle: `El valor más reciente de \`${clave}\` (${actual.valor}, ${estado}) arranca el ${actual.vigencia_desde}, antes de la fecha de actualización ${esperada}, que ya pasó. Busca el valor del ejercicio en curso en su publicación oficial y captúralo cerrando el tramo anterior.`,
    };
  }

  // Al día, pero encima hay una propuesta más nueva que nadie ha mirado (una fe de erratas, otra
  // semilla, una corrección). Sin este aviso quedaría invisible para siempre.
  if (propuesto !== null && confirmado !== null && propuesto.vigencia_desde > confirmado.vigencia_desde) {
    return {
      clave, motivo: 'SIN_CONFIRMAR', vigencia_desde: propuesto.vigencia_desde, fecha_esperada: esperada,
      detalle: `\`${clave}\` está al día, pero hay un tramo más reciente propuesto (${propuesto.valor}, desde ${propuesto.vigencia_desde}, fuente: ${propuesto.fuente}) esperando confirmación. Mientras no se confirme, los cálculos siguen usando el anterior.`,
    };
  }
  return null;
}

function alertasDeVigenciaMock(): AlertaVigencia[] {
  const hoy = stamp().slice(0, 10);
  const alertas: AlertaVigencia[] = [];
  for (const clave of Object.keys(FECHAS_DE_ACTUALIZACION).sort()) {
    const alerta = alertaDeClave(clave, db.param_fiscal.filter((p) => p.clave === clave), hoy);
    if (alerta) alertas.push(alerta);
  }
  // Maquinaria: el mock no tiene `satcfdi` que leer (su catálogo siempre es legible y su versión
  // no existe), pero sí reproduce el estado real de hoy — la sincronización con Banxico falla
  // porque falta el token, que nadie ha tramitado. Es el estado diseñado, no una avería.
  if (db.sync_banxico_estado) {
    alertas.push({
      clave: 'SINCRONIZACION_BANXICO', motivo: 'SINCRONIZACION_FALLIDA', vigencia_desde: null, fecha_esperada: null,
      detalle: `El último intento de sincronizar el tipo de cambio con Banxico falló (${db.sync_banxico_estado.fallo}, ${db.sync_banxico_estado.cuando}). Mientras dure, \`TIPO_CAMBIO_USD\` no se actualiza solo y hay que capturarlo a mano.`,
    });
  }
  return alertas;
}

function paramASalida(fila: DbParamFiscal): ParametroFiscal {
  return {
    clave: fila.clave, ejercicio: fila.ejercicio, valor: fila.valor,
    vigencia_desde: fila.vigencia_desde, vigencia_hasta: fila.vigencia_hasta,
    origen: fila.origen, fuente: fila.fuente, sincronizado_en: fila.sincronizado_en,
    confirmado: fila.confirmado_en !== null, confirmado_por: fila.confirmado_por, confirmado_en: fila.confirmado_en,
  };
}

// --- marcas del art. 93: también las reglas reales ---------------------------------------------
// El catálogo `c_TipoPercepcion` del SAT — las 44 claves con su descripción oficial.
//
// **Esto es el doble de `satcfdi`, no una copia del catálogo en el cliente.** Vive aquí porque
// aquí es donde el mock hace de servidor: es la misma lista blanca que
// `exige_tipo_percepcion_conocido` comprueba en el backend (sin ella el mock aceptaría `150` por
// `015` y la pantalla se diseñaría creyendo que el backend también lo acepta) y la misma fuente de
// la que sale `descripcion_sat` y `claves_sin_marcas`. La pantalla ya no lleva ninguna copia: la
// tenía en `features/admin/catalogoTipoPercepcion.ts` —borrada— y desde ahí decidía qué tarjetas
// existen, con lo que el denominador del "0 de 44" se quedaba viejo al subir la versión de
// `satcfdi`.
const CATALOGO_TIPO_PERCEPCION_MOCK: Record<string, string> = {
  '001': 'Sueldos, Salarios Rayas y Jornales',
  '002': 'Gratificación Anual (Aguinaldo)',
  '003': 'Participación de los Trabajadores en las Utilidades PTU',
  '004': 'Reembolso de Gastos Médicos Dentales y Hospitalarios',
  '005': 'Fondo de Ahorro',
  '006': 'Caja de ahorro',
  '009': 'Contribuciones a Cargo del Trabajador Pagadas por el Patrón',
  '010': 'Premios por puntualidad',
  '011': 'Prima de Seguro de vida',
  '012': 'Seguro de Gastos Médicos Mayores',
  '013': 'Cuotas Sindicales Pagadas por el Patrón',
  '014': 'Subsidios por incapacidad',
  '015': 'Becas para trabajadores y/o hijos',
  '019': 'Horas extra',
  '020': 'Prima dominical',
  '021': 'Prima vacacional',
  '022': 'Prima por antigüedad',
  '023': 'Pagos por separación',
  '024': 'Seguro de retiro',
  '025': 'Indemnizaciones',
  '026': 'Reembolso por funeral',
  '027': 'Cuotas de seguridad social pagadas por el patrón',
  '028': 'Comisiones',
  '029': 'Vales de despensa',
  '030': 'Vales de restaurante',
  '031': 'Vales de gasolina',
  '032': 'Vales de ropa',
  '033': 'Ayuda para renta',
  '034': 'Ayuda para artículos escolares',
  '035': 'Ayuda para anteojos',
  '036': 'Ayuda para transporte',
  '037': 'Ayuda para gastos de funeral',
  '038': 'Otros ingresos por salarios',
  '039': 'Jubilaciones, pensiones o haberes de retiro',
  '044': 'Jubilaciones, pensiones o haberes de retiro en parcialidades',
  '045': 'Ingresos en acciones o títulos valor que representan bienes',
  '046': 'Ingresos asimilados a salarios',
  '047': 'Alimentación',
  '048': 'Habitación',
  '049': 'Premios por asistencia',
  '050': 'Viáticos',
  '051': 'Pagos por gratificaciones, primas, compensaciones, recompensas u otros a extrabajadores derivados de jubilación en parcialidades',
  '052': 'Pagos que se realicen a extrabajadores que obtengan una jubilación en parcialidades derivados de la ejecución de resoluciones judicial o de un laudo',
  '053': 'Pagos que se realicen a extrabajadores que obtengan una jubilación en una sola exhibición derivados de la ejecución de resoluciones judicial o de un laudo',
};
const TIPOS_PERCEPCION_MOCK = Object.keys(CATALOGO_TIPO_PERCEPCION_MOCK);
const DECIMALES_FACTOR = 4;

function exigeTipoPercepcionMock(tipo: string): void {
  if (!TIPOS_PERCEPCION_MOCK.includes(tipo)) {
    throw new ApiError(422, 'TIPO_PERCEPCION_INVALIDO', `'${tipo}' no está en el catálogo \`c_TipoPercepcion\` del SAT (44 claves). Una marca sobre un tipo inventado se confirma sin ruido y después no la lee nadie nunca.`);
  }
}

/** Las validaciones del esquema `MarcasPercepcion` de Pydantic, incluidas **las tres que no llevan
 * default**: `sujeto_a_tope_conjunto` y `multiplicador_no_derivable` siempre, y `nota_revision` en
 * el `PUT`. Un campo omitido no
 * es "el valor de por omisión", es un 422 — y el mensaje imita el que arma `aApiError` con el
 * `detail` de FastAPI para que la pantalla se pruebe contra el texto que va a recibir de verdad. */
function exigeMarcasValidas(body: Partial<MarcasPercepcion>, conNota: boolean): void {
  const faltantes: string[] = [];
  if (typeof body.es_ingreso_ordinario !== 'boolean') faltantes.push('es_ingreso_ordinario');
  if (typeof body.base_exencion !== 'string') faltantes.push('base_exencion');
  if (typeof body.integra_sbc !== 'boolean') faltantes.push('integra_sbc');
  if (typeof body.es_provisionable !== 'boolean') faltantes.push('es_provisionable');
  // Sin default a propósito (doc 05 §8bis): con uno, capturar una marca sujeta al tope conjunto la
  // crearía en `false` en silencio y B-03 exentaría de más.
  if (typeof body.sujeto_a_tope_conjunto !== 'boolean') faltantes.push('sujeto_a_tope_conjunto');
  // Tampoco lleva default, y este SÍ calcula: con uno, capturar uno de los nueve tipos cuyo
  // multiplicador el CFDI no trae lo dejaría en `false` y B-03 publicaría un tope supuesto.
  if (typeof body.multiplicador_no_derivable !== 'boolean') faltantes.push('multiplicador_no_derivable');
  if (conNota && !('nota_revision' in body)) faltantes.push('nota_revision');
  if (faltantes.length > 0) {
    throw new ApiError(422, 'DATOS_INVALIDOS', faltantes.map((c) => `${c}: Field required`).join(' · '));
  }

  const base = body.base_exencion as BaseExencion;
  if (!['UMA_DIAS', 'SM_DIAS', 'PORCENTAJE', 'NINGUNA'].includes(base)) {
    throw new ApiError(422, 'DATOS_INVALIDOS', `base_exencion: '${base}' no es una base de exención válida.`);
  }
  const factor = body.factor_exencion ?? null;
  if (base === 'NINGUNA') {
    if (factor !== null) throw new ApiError(422, 'DATOS_INVALIDOS', 'Value error, con `base_exencion: NINGUNA` no puede haber `factor_exencion`.');
    if (body.multiplicador_no_derivable) {
      throw new ApiError(422, 'DATOS_INVALIDOS', 'Value error, `multiplicador_no_derivable: true` no tiene sentido con `base_exencion: NINGUNA` — lo que la bandera dice es que al factor le falta un multiplicador, y aquí no hay factor.');
    }
    if (body.sujeto_a_tope_conjunto) {
      throw new ApiError(422, 'DATOS_INVALIDOS', 'Value error, `sujeto_a_tope_conjunto: true` no tiene sentido con `base_exencion: NINGUNA` — o el tipo sí tiene exención y falta capturarla, o la marca del tope sobra.');
    }
    return;
  }
  if (factor === null) throw new ApiError(422, 'DATOS_INVALIDOS', `Value error, \`base_exencion: ${base}\` exige un \`factor_exencion\`.`);
  const normalizado = importeNormalizado(exigeImporteCadena(factor));
  if (normalizado === null) throw new ApiError(422, 'DATOS_INVALIDOS', `factor_exencion: '${factor}' no es un número válido.`);
  if (normalizado.startsWith('-') || normalizado === '0') {
    throw new ApiError(422, 'DATOS_INVALIDOS', 'factor_exencion: Input should be greater than 0');
  }
  if (Number(normalizado) >= 100000) throw new ApiError(422, 'DATOS_INVALIDOS', 'factor_exencion: Input should be less than 100000');
  const decimales = normalizado.includes('.') ? normalizado.split('.')[1].length : 0;
  if (decimales > DECIMALES_FACTOR) {
    throw new ApiError(422, 'DATOS_INVALIDOS', `factor_exencion: Decimal input should have no more than ${DECIMALES_FACTOR} decimal places`);
  }
}

/** `_difieren` del backend: solo las **seis marcas que calculan**. La nota queda fuera (no viaja
 * en el cuerpo de confirmar y su efecto es asimétrico — ver `dudaNuevaMock`). */
function marcasDifieren(fila: DbMarcaPercepcion, body: MarcasPercepcion): boolean {
  const factorFila = fila.factor_exencion === null ? null : importeNormalizado(fila.factor_exencion);
  const factorBody = body.factor_exencion === null ? null : importeNormalizado(body.factor_exencion);
  return (
    fila.es_ingreso_ordinario !== body.es_ingreso_ordinario ||
    fila.base_exencion !== body.base_exencion ||
    factorFila !== factorBody ||
    fila.integra_sbc !== body.integra_sbc ||
    fila.es_provisionable !== body.es_provisionable ||
    fila.sujeto_a_tope_conjunto !== body.sujeto_a_tope_conjunto ||
    // Esta sí calcula, así que entra sin discusión.
    fila.multiplicador_no_derivable !== body.multiplicador_no_derivable
  );
}

/** `_duda_nueva` del backend, con su asimetría: la duda que **aparece o cambia** limpia la
 * confirmación; la que **desaparece**, no. Quien confirmó no tenía delante la duda nueva. */
function dudaNuevaMock(fila: DbMarcaPercepcion, nota: string | null): boolean {
  return nota !== null && nota !== fila.nota_revision;
}

/** "" y "   " son la misma intención que `null` y se guardan igual, o el `GET` devolvería a veces
 * `""` y a veces `null` para el mismo estado. */
function normalizaNota(nota: string | null): string | null {
  return nota === null ? null : nota.trim() || null;
}

/** Huella **estable, opaca y distinta para textos distintos** de un texto cualquiera. El
 * servidor real usa SHA-256; para lo que el contrato promete —el cliente la copia de un `GET` y
 * la devuelve tal cual, sin calcularla ni interpretarla— basta con esto. Si el mock emitiera algo
 * que el cliente pudiera reproducir, la pantalla se diseñaría contra una garantía que el backend
 * real no da. Comparte algoritmo `huellaDeNotaMock` (nota de percepción) y `huellaDeTarifaMock`
 * (renglones de tarifa) para que las dos usen la misma promesa de opacidad. */
function huellaTextoMock(texto: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < texto.length; i++) {
    h1 = Math.imul(h1 ^ texto.charCodeAt(i), 0x01000193) >>> 0;
    h2 = Math.imul(h2 + texto.charCodeAt(i), 0x85ebca6b) >>> 0;
  }
  return `${h1.toString(16).padStart(8, '0')}${h2.toString(16).padStart(8, '0')}${texto.length.toString(16)}`;
}

/** La huella de la duda declarada. Ver `huellaTextoMock`. */
function huellaDeNotaMock(nota: string | null): string | null {
  return nota === null ? null : huellaTextoMock(nota);
}

/** `_duda_no_vista` del backend, **asimétrica igual que `dudaNuevaMock`**: si la marca tiene hoy
 * una duda y la huella que llegó no es la suya, quien confirma no la tenía delante → 409. Si la
 * duda **se resolvió** entre la pantalla y el clic, pasa: esa revisión se hizo contra *más*
 * información de la que hay hoy, y castigarla enseñaría a la gente a no resolver dudas. */
function dudaNoVistaMock(fila: DbMarcaPercepcion, huellaEnviada: string | null): boolean {
  const actual = huellaDeNotaMock(fila.nota_revision);
  return actual !== null && actual !== huellaEnviada;
}

function marcaASalida(fila: DbMarcaPercepcion): MarcaPercepcion {
  return {
    tipo_percepcion: fila.tipo_percepcion,
    // Del mismo catálogo con el que se valida la escritura, igual que en el servidor.
    descripcion_sat: CATALOGO_TIPO_PERCEPCION_MOCK[fila.tipo_percepcion] ?? null,
    nota_revision_hash: huellaDeNotaMock(fila.nota_revision),
    es_ingreso_ordinario: fila.es_ingreso_ordinario,
    base_exencion: fila.base_exencion,
    factor_exencion: fila.factor_exencion,
    integra_sbc: fila.integra_sbc,
    es_provisionable: fila.es_provisionable,
    sujeto_a_tope_conjunto: fila.sujeto_a_tope_conjunto,
    multiplicador_no_derivable: fila.multiplicador_no_derivable,
    nota_revision: fila.nota_revision,
    confirmado: fila.confirmado_en !== null,
    confirmado_por: fila.confirmado_por,
    confirmado_en: fila.confirmado_en,
  };
}

/** La columna es `Numeric(9,4)`: el servidor devuelve siempre la escala real ("15.0000"), no lo
 * que se tecleó. Sin esto, capturar "15" y volver a leer daría "15" y la pantalla se diseñaría
 * contra una escala que el backend no produce. */
function escalaFactor(valor: string | null): string | null {
  if (valor === null) return null;
  const n = importeNormalizado(valor);
  if (n === null) return valor;
  const [enteros, decimales = ''] = n.split('.');
  return `${enteros}.${decimales.padEnd(DECIMALES_FACTOR, '0').slice(0, DECIMALES_FACTOR)}`;
}

// --- tarifa del ISR (doc 05 §8bis, tarifa ISR): las MISMAS reglas estructurales del Anexo I.1,
// no una versión relajada — mismo criterio que la configuración fiscal de arriba. -------------

// Copiadas literalmente de `_ETIQUETAS_TARIFA` en `app/api/v1/configuracion.py`: el servidor es
// la autoridad de este texto (la etiqueta viaja ya traducida en `TarifaIsr.etiqueta`, el
// frontend no la construye), así que el doble no puede mejorarlas ni acortarlas por su cuenta.
const ETIQUETAS_PERIODICIDAD_TARIFA: Record<PeriodicidadTarifaIsr, string> = {
  DIARIA: 'Diaria (por día trabajado)',
  DIAS_7: 'Semanal (7 días)',
  DIAS_10: 'Decenal (10 días)',
  DIAS_15: 'Quincenal (15 días)',
  MENSUAL: 'Mensual',
  EJERCICIO: 'Anual (cálculo del ejercicio)',
};

/** Claves de `c_PeriodicidadPago` que la nómina real usa y para las que el Anexo 8 no publica
 * tarifa: catorcenal y bimestral. */
const PERIODICIDADES_SIN_TARIFA_MOCK = ['03', '06'];

/** El mismo número como lo publica el SAT ("21.36"), calculado a partir de la fracción que se
 * guarda ("0.213600") — igual que `(tasa_excedente * 100).quantize(Decimal("0.01"))` en
 * `app/api/v1/configuracion.py`. Nunca al revés: la pantalla no multiplica por su cuenta. */
function tasaPorcentajeTarifaMock(tasaExcedente: string): string {
  return (Number(tasaExcedente) * 100).toFixed(2);
}

/** Forma canónica de los renglones para la huella: ordenados por número de renglón y con los
 * importes normalizados, para que "7.07" y "7.070000" produzcan la misma huella — igual que en
 * el servidor, donde la huella se calcula sobre el `Decimal` exacto, no sobre el texto tecleado. */
function huellaDeTarifaMock(renglones: TarifaIsrRenglonIn[]): string {
  const canonico = [...renglones]
    .sort((a, b) => a.renglon - b.renglon)
    .map((r) =>
      [
        r.renglon,
        importeNormalizado(r.limite_inferior) ?? r.limite_inferior,
        r.limite_superior === null ? '' : (importeNormalizado(r.limite_superior) ?? r.limite_superior),
        importeNormalizado(r.cuota_fija) ?? r.cuota_fija,
        importeNormalizado(r.tasa_excedente) ?? r.tasa_excedente,
      ].join('|'),
    )
    .join(';');
  return huellaTextoMock(canonico);
}

/** Las cinco pruebas de continuidad/monotonía del Anexo I.1 que un renglón capturado a mano
 * puede romper (las otras del Anexo I.1 —máscara de campos, escala de columna— ya las cubren los
 * tipos). Mismo espíritu que `app.services.tarifa_isr.validar`, no una copia byte a byte: aquí
 * solo hace falta que el mock no deje pasar una tarifa que el backend real rechazaría. */
function exigeTarifaValidaMock(renglones: TarifaIsrRenglonIn[]): void {
  if (renglones.length === 0) {
    throw new ApiError(422, 'TARIFA_INVALIDA', 'la tarifa necesita al menos un renglón.');
  }
  const ordenados = [...renglones].sort((a, b) => a.renglon - b.renglon);
  const primero = ordenados[0];
  if (importeNormalizado(primero.limite_inferior) !== '0.01') {
    throw new ApiError(422, 'TARIFA_INVALIDA', `renglón ${primero.renglon}: el límite inferior tiene que empezar en 0.01, llegó ${primero.limite_inferior}.`);
  }
  if (importeNormalizado(primero.cuota_fija) !== '0') {
    throw new ApiError(422, 'TARIFA_INVALIDA', `renglón ${primero.renglon}: la cuota fija del primer renglón tiene que ser 0.00, llegó ${primero.cuota_fija}.`);
  }
  let tasaAnterior = -1;
  ordenados.forEach((r, i) => {
    const esUltimo = i === ordenados.length - 1;
    if (esUltimo && r.limite_superior !== null) {
      throw new ApiError(422, 'TARIFA_INVALIDA', `renglón ${r.renglon}: el último renglón tiene que quedar sin límite superior ("en adelante").`);
    }
    if (!esUltimo && r.limite_superior === null) {
      throw new ApiError(422, 'TARIFA_INVALIDA', `renglón ${r.renglon}: solo el último renglón puede quedar sin límite superior.`);
    }
    if (i > 0) {
      const anterior = ordenados[i - 1];
      const esperado = Number(anterior.limite_superior) + 0.01;
      if (Math.abs(Number(r.limite_inferior) - esperado) > 0.001) {
        throw new ApiError(422, 'TARIFA_INVALIDA', `renglón ${r.renglon}: el límite inferior tiene que empezar un centavo después del límite superior del renglón anterior (esperado ${esperado.toFixed(2)}, llegó ${r.limite_inferior}).`);
      }
    }
    const tasa = Number(r.tasa_excedente);
    if (tasa <= tasaAnterior) {
      throw new ApiError(422, 'TARIFA_INVALIDA', `renglón ${r.renglon}: la tasa (${r.tasa_excedente}) tiene que ser mayor que la del renglón anterior.`);
    }
    tasaAnterior = tasa;
  });
}

function renglonTarifaASalida(r: TarifaIsrRenglonIn): TarifaIsrRenglon {
  return {
    renglon: r.renglon,
    limite_inferior: r.limite_inferior,
    limite_superior: r.limite_superior,
    cuota_fija: r.cuota_fija,
    tasa_excedente: r.tasa_excedente,
    tasa_porcentaje: tasaPorcentajeTarifaMock(r.tasa_excedente),
  };
}

/** El renglón que aplica a un ingreso gravado y el ISR que resulta, contra los renglones
 * **vigentes ahora mismo** — no un valor guardado en el insumo. Así, corregir una tarifa cambia
 * de inmediato lo que la comprobación enseña, igual que en `app.services.comprobacion_tarifa`. */
function calcularIsrTarifaMock(
  renglones: TarifaIsrRenglonIn[],
  gravado: string,
): { renglon: number; limite_inferior: string; tasa_excedente: string; isr_calculado: string } {
  const g = Number(gravado);
  const ordenados = [...renglones].sort((a, b) => a.renglon - b.renglon);
  const fila = ordenados.find((r) => g >= Number(r.limite_inferior) && (r.limite_superior === null || g <= Number(r.limite_superior))) ?? ordenados[ordenados.length - 1];
  const excedente = g - Number(fila.limite_inferior);
  const isr = Number(fila.cuota_fija) + excedente * Number(fila.tasa_excedente);
  return { renglon: fila.renglon, limite_inferior: fila.limite_inferior, tasa_excedente: fila.tasa_excedente, isr_calculado: isr.toFixed(2) };
}

function comprobacionTarifaASalida(insumo: DbComprobacionInsumo | null, renglones: TarifaIsrRenglonIn[]): ComprobacionTarifa | null {
  if (!insumo) return null;
  const { renglon, limite_inferior, tasa_excedente, isr_calculado } = calcularIsrTarifaMock(renglones, insumo.gravado);
  return {
    uuid: insumo.uuid,
    fecha_inicial_pago: insumo.fecha_inicial_pago,
    fecha_final_pago: insumo.fecha_final_pago,
    num_empleado: insumo.num_empleado,
    dias_pagados: insumo.dias_pagados,
    gravado: insumo.gravado,
    renglon,
    limite_inferior,
    tasa_excedente,
    isr_calculado,
    isr_timbrado: insumo.isr_timbrado,
    diferencia: (Number(isr_calculado) - Number(insumo.isr_timbrado)).toFixed(2),
    advertencias: insumo.advertencias,
  };
}

function tarifaIsrASalida(fila: DbTarifaIsr): TarifaIsr {
  const renglones = [...fila.renglones].sort((a, b) => a.renglon - b.renglon);
  return {
    ejercicio: fila.ejercicio,
    periodicidad: fila.periodicidad,
    etiqueta: ETIQUETAS_PERIODICIDAD_TARIFA[fila.periodicidad],
    periodicidad_cfdi: fila.periodicidad_cfdi,
    origen: fila.origen,
    fuente: fila.fuente,
    documento_sha256: fila.documento_sha256,
    encabezado: fila.encabezado,
    importado_en: fila.importado_en,
    confirmado_por: fila.confirmado_por,
    confirmado_en: fila.confirmado_en,
    confirmada: fila.confirmado_en !== null,
    difiere_del_documento: fila.origen === 'MANUAL',
    aplica_a_la_nomina: fila.aplica_a_la_nomina,
    huella: huellaDeTarifaMock(renglones),
    renglones: renglones.map(renglonTarifaASalida),
    comprobacion: comprobacionTarifaASalida(fila.comprobacion_insumo, renglones),
  };
}

function requireAdminMock(accion: string): DbUsuario {
  const u = requireUsuario();
  if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', `Solo un administrador puede ${accion}.`);
  return u;
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
    if (f?.solicitud) rows = rows.filter((j) => j.solicitud === f.solicitud);
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

  async obtenerMetadata(empresaId, jobId, page): Promise<MetadataPreview> {
    requireRol(empresaId, 'consulta');
    const job = db.jobs.find((j) => j.job_id === jobId && j.empresa_id === empresaId);
    if (!job) throw new ApiError(404, 'NO_ENCONTRADO', 'El job no existe o no pertenece a esta empresa.');
    const perPage = 100;
    const pageNum = page ?? 1;
    const mockHeaders = ['RFC', 'Razon Social', 'Folios Emitidos', 'Folios Recibidos'];
    const mockFilas: string[][] = [
      ['AAA010101AAA', 'Proveedora del Norte Demo', '100', '50'],
      ['BBB020202BB2', 'Insumos Fronterizos Demo', '200', '75'],
      ['CCC030303CC3', 'Comercial EFOS Demo', '150', '60'],
    ];
    const total = mockFilas.length;
    const start = (pageNum - 1) * perPage;
    const filas = mockFilas.slice(start, start + perPage);
    return { headers: mockHeaders, filas, total, page: pageNum, per_page: perPage };
  },

  async descargarMetadataCsv(empresaId, jobId): Promise<Blob> {
    requireRol(empresaId, 'consulta');
    const job = db.jobs.find((j) => j.job_id === jobId && j.empresa_id === empresaId);
    if (!job) throw new ApiError(404, 'NO_ENCONTRADO', 'El job no existe o no pertenece a esta empresa.');
    const csv = 'RFC,Razon Social,Folios Emitidos,Folios Recibidos\nAAA010101AAA,Proveedora del Norte Demo,100,50\nBBB020202BB2,Insumos Fronterizos Demo,200,75\nCCC030303CC3,Comercial EFOS Demo,150,60\n';
    return new Blob([csv], { type: 'text/csv' });
  },

  async listarInformes(): Promise<InformeCatalogo[]> {
    requireUsuario();
    return CATALOGO_INFORMES;
  },

  async generarInforme(empresaId, clave, parametros) {
    // Espejo de app/api/v1/informes.py:generar_endpoint — CONSULTA basta para generar en general;
    // el 403 y la bitácora solo aparecen si se pide sin enmascarar (spec §8).
    const u = requireRol(empresaId, 'consulta');
    const informe = CATALOGO_INFORMES.find((i) => i.clave === clave);
    if (!informe) throw new ApiError(404, 'NO_ENCONTRADO', 'El informe no existe en el catálogo.');
    const sinEnmascarar = parametros.enmascarar_datos_personales === false;
    if (sinEnmascarar) {
      if (rolEn(u, empresaId) === 'consulta') {
        throw new ApiError(403, 'ERROR', 'Generar el informe sin enmascarar datos personales requiere rol de operador o superior.');
      }
      logBitacora(u.correo, 'generar_informe', `empresa:${empresaId}`, { clave, enmascarar_datos_personales: false, parametros });
    }
    const tarea_id = crypto.randomUUID();
    tareas.set(tarea_id, { estado: 'pendiente' });
    setTimeout(() => tareas.set(tarea_id, { estado: 'completada', descarga_url: `/mock-descargas/informe_${clave}_empresa${empresaId}.xlsx` }), 1400);
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
      aprobado: !!x.aprobado,
      permisos: db.usuario_empresa
        .filter((a) => a.usuario_id === x.usuario_id)
        .map((a) => ({ empresa_id: a.empresa_id, empresa_nombre: db.empresas.find((e) => e.empresa_id === a.empresa_id)?.nombre ?? '—', rol: a.rol })),
    }));
  },

  async registrarUsuario(body): Promise<void> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede registrar usuarios.');
    const usuario_id = Math.max(...db.usuarios.map((x) => x.usuario_id)) + 1;
    const correo = `usuario${usuario_id}@demo.test`;
    db.usuarios.push({ usuario_id, correo, nombre: body.nombre, rol_global: 'consulta', activo: 1, aprobado: 0 });
    logBitacora(u.correo, 'registrar_usuario', `usuario:${usuario_id}`, { nombre: body.nombre, correo });
  },

  async actualizarUsuario(id, body): Promise<void> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede actualizar usuarios.');
    const usuario = db.usuarios.find((x) => x.usuario_id === id);
    if (!usuario) throw new ApiError(404, 'NO_ENCONTRADO', 'El usuario no existe.');
    if (body.activo !== undefined) usuario.activo = body.activo ? 1 : 0;
    if (body.rol_global !== undefined) usuario.rol_global = body.rol_global;
    if (body.aprobado !== undefined) usuario.aprobado = body.aprobado ? 1 : 0;
    logBitacora(u.correo, 'actualizar_usuario', `usuario:${id}`, { activo: body.activo, rol_global: body.rol_global, aprobado: body.aprobado });
  },

  async guardarPermisos(id, permisos): Promise<void> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede asignar permisos.');
    const usuario = db.usuarios.find((x) => x.usuario_id === id);
    if (!usuario) throw new ApiError(404, 'NO_ENCONTRADO', 'El usuario no existe.');
    db.usuario_empresa = db.usuario_empresa.filter((x) => x.usuario_id !== id);
    db.usuario_empresa.push(...permisos.map((p) => ({ usuario_id: id, empresa_id: p.empresa_id, rol: p.rol })));
    logBitacora(u.correo, 'asignar_permisos', `usuario:${id}`, { permisos });
  },

  async eliminarUsuario(id): Promise<void> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede eliminar usuarios.');
    const usuario = db.usuarios.find((x) => x.usuario_id === id);
    if (!usuario) throw new ApiError(404, 'NO_ENCONTRADO', 'El usuario no existe.');
    db.usuarios = db.usuarios.filter((x) => x.usuario_id !== id);
    db.usuario_empresa = db.usuario_empresa.filter((x) => x.usuario_id !== id);
    logBitacora(u.correo, 'eliminar_usuario', `usuario:${id}`, { correo: usuario.correo });
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

  async obtenerAutomatizaciones(): Promise<Automatizaciones> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede ver esta pantalla.');
    return { ...db.automatizaciones };
  },

  async guardarAutomatizaciones(input: Automatizaciones): Promise<Automatizaciones> {
    const u = requireUsuario();
    if (!esAdmin(u)) throw new ApiError(403, 'SOLO_ADMIN', 'Solo un administrador puede realizar esta acción.');
    db.automatizaciones = { ...input };
    return { ...input };
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

  async estadoBootstrap(): Promise<{ needs_bootstrap: boolean }> {
    return { needs_bootstrap: false };
  },

  async crearAdminBootstrap(): Promise<void> {
    throw new ApiError(409, 'BOOTSTRAP_YA_REALIZADO', 'El mock ya tiene un administrador.');
  },

  // --- Configuración fiscal (doc 05 §8bis) -----------------------------------------------------

  async listarConfiguracionFiscal(): Promise<ConfiguracionFiscal> {
    requireAdminMock('ver la configuración fiscal');
    const parametros = [...db.param_fiscal]
      .sort((a, b) => a.clave.localeCompare(b.clave) || a.vigencia_desde.localeCompare(b.vigencia_desde))
      .map(paramASalida);
    const conValor = new Set(parametros.map((p) => p.clave));
    return {
      parametros,
      claves_sin_valor: CLAVES_PARAM_FISCAL.filter((c) => !conValor.has(c)),
      alertas: alertasDeVigenciaMock(),
    };
  },

  async capturarParametroFiscal(clave, input): Promise<ParametroFiscal> {
    const u = requireAdminMock('capturar un valor fiscal');
    const valor = exigeParamFiscalValido(clave, input);
    const hasta = input.vigencia_hasta ?? null;

    const tramos = db.param_fiscal.filter((p) => p.clave === clave);
    for (const otro of tramos) {
      if (otro.vigencia_desde === input.vigencia_desde) continue; // es la misma fila
      if (seSolapan(input.vigencia_desde, hasta, otro.vigencia_desde, otro.vigencia_hasta)) {
        throw new ApiError(409, 'VIGENCIA_SOLAPADA', `el tramo ${input.vigencia_desde}..${hasta ?? 'nuevo aviso'} de \`${clave}\` se solapa con el que ya existe (${otro.vigencia_desde}..${otro.vigencia_hasta ?? 'nuevo aviso'}, valor ${otro.valor}). Cierra el tramo anterior poniéndole \`vigencia_hasta\` el día previo, o corrige la fecha si tecleaste mal el año.`);
      }
    }

    let fila = tramos.find((p) => p.vigencia_desde === input.vigencia_desde);
    if (!fila) {
      fila = {
        clave, ejercicio: input.ejercicio ?? Number(input.vigencia_desde.slice(0, 4)), valor,
        vigencia_desde: input.vigencia_desde, vigencia_hasta: hasta, origen: 'MANUAL',
        fuente: input.fuente, sincronizado_en: null, confirmado_por: null, confirmado_en: null,
      };
      db.param_fiscal.push(fila);
    } else {
      // Si la cifra cambia, la confirmación anterior se limpia: un valor distinto es un valor
      // nuevo y necesita que alguien lo vuelva a mirar. Cambiar solo fuente o vigencia no la tira.
      if (importeNormalizado(fila.valor) !== importeNormalizado(valor)) {
        fila.confirmado_por = null;
        fila.confirmado_en = null;
      }
      fila.valor = valor;
      fila.vigencia_hasta = hasta;
      fila.fuente = input.fuente;
      fila.origen = 'MANUAL';
      fila.ejercicio = input.ejercicio ?? Number(input.vigencia_desde.slice(0, 4));
    }
    logBitacora(u.correo, 'capturar_param_fiscal', `param_fiscal:${clave}@${input.vigencia_desde}`, { clave, valor });
    return paramASalida(fila);
  },

  async confirmarParametroFiscal(clave, input): Promise<ParametroFiscal> {
    const u = requireAdminMock('confirmar un valor fiscal');
    const fila = db.param_fiscal.find((p) => p.clave === clave && p.vigencia_desde === input.vigencia_desde);
    if (!fila) throw new ApiError(404, 'NO_ENCONTRADO', 'No encontrado.');
    const enviado = importeNormalizado(exigeImporteCadena(input.valor));
    if (enviado === null || enviado !== importeNormalizado(fila.valor)) {
      throw new ApiError(409, 'VALOR_CAMBIO', `El valor de \`${clave}\` cambió mientras revisabas: está en ${fila.valor} y confirmaste ${input.valor}. Vuelve a cargar la configuración y revísalo otra vez antes de confirmar.`);
    }
    // Idempotente: reconfirmar no reescribe quién lo revisó ni deja bitácora de un no-cambio.
    if (fila.confirmado_en !== null) return paramASalida(fila);
    fila.confirmado_por = u.correo;
    fila.confirmado_en = stamp();
    logBitacora(u.correo, 'confirmar_param_fiscal', `param_fiscal:${clave}@${input.vigencia_desde}`, { clave, valor: fila.valor });
    return paramASalida(fila);
  },

  async listarMarcasPercepcion(): Promise<CatalogoPercepciones> {
    requireAdminMock('ver las marcas de exención');
    const marcas = [...db.catalogo_percepcion_marca]
      .sort((a, b) => a.tipo_percepcion.localeCompare(b.tipo_percepcion))
      .map(marcaASalida);
    // El resto del catálogo del SAT: el tercer estado ("sin marcas capturadas") y, sobre todo, el
    // **denominador autoritativo** del "0 de 44". Lo pone el servidor, no el cliente.
    const conMarcas = new Set(marcas.map((m) => m.tipo_percepcion));
    return { marcas, claves_sin_marcas: TIPOS_PERCEPCION_MOCK.filter((t) => !conMarcas.has(t)) };
  },

  async guardarMarcaPercepcion(tipo, input: MarcaPercepcionIn): Promise<MarcaPercepcion> {
    const u = requireAdminMock('capturar las marcas de un tipo de percepción');
    exigeTipoPercepcionMock(tipo);
    exigeMarcasValidas(input, true);
    const nota = normalizaNota(input.nota_revision);
    const factor = escalaFactor(input.factor_exencion);

    let fila = db.catalogo_percepcion_marca.find((m) => m.tipo_percepcion === tipo);
    if (!fila) {
      fila = {
        tipo_percepcion: tipo, es_ingreso_ordinario: input.es_ingreso_ordinario,
        base_exencion: input.base_exencion, factor_exencion: factor, integra_sbc: input.integra_sbc,
        es_provisionable: input.es_provisionable, sujeto_a_tope_conjunto: input.sujeto_a_tope_conjunto,
        multiplicador_no_derivable: input.multiplicador_no_derivable,
        nota_revision: nota, confirmado_por: null, confirmado_en: null,
      };
      db.catalogo_percepcion_marca.push(fila);
    } else {
      // Capturar no confirma, y **una duda nueva devuelve la marca a la cola de revisión aunque
      // las seis marcas no se muevan**: quien la confirmó no tenía esa duda delante.
      if (marcasDifieren(fila, { ...input, factor_exencion: factor }) || dudaNuevaMock(fila, nota)) {
        fila.confirmado_por = null;
        fila.confirmado_en = null;
      }
      fila.es_ingreso_ordinario = input.es_ingreso_ordinario;
      fila.base_exencion = input.base_exencion;
      fila.factor_exencion = factor;
      fila.integra_sbc = input.integra_sbc;
      fila.es_provisionable = input.es_provisionable;
      fila.sujeto_a_tope_conjunto = input.sujeto_a_tope_conjunto;
      fila.multiplicador_no_derivable = input.multiplicador_no_derivable;
      fila.nota_revision = nota;
    }
    logBitacora(u.correo, 'capturar_marca_percepcion', `catalogo_percepcion_marca:${tipo}`, { tipo_percepcion: tipo });
    return marcaASalida(fila);
  },

  async confirmarMarcaPercepcion(tipo, input: MarcaPercepcionConfirmarIn): Promise<MarcaPercepcion> {
    const u = requireAdminMock('confirmar las marcas de un tipo de percepción');
    exigeTipoPercepcionMock(tipo);
    exigeMarcasValidas(input, false);
    // Sin default, igual que `sujeto_a_tope_conjunto`: este es el cuerpo que activa un valor
    // fiscal, y omitir el campo sería confirmar sin decir qué duda se tenía delante. `null` sí es
    // válido — afirma "la marca que revisé no traía duda".
    if (!('nota_revision_hash' in input)) {
      throw new ApiError(422, 'DATOS_INVALIDOS', 'nota_revision_hash: Field required');
    }
    const fila = db.catalogo_percepcion_marca.find((m) => m.tipo_percepcion === tipo);
    if (!fila) throw new ApiError(404, 'NO_ENCONTRADO', 'No encontrado.');
    // Antes que las marcas: si apareció una duda, ese es el diagnóstico útil aunque además hayan
    // cambiado las marcas — "mira la advertencia nueva" dice más que "algo cambió".
    if (dudaNoVistaMock(fila, input.nota_revision_hash)) {
      throw new ApiError(409, 'DUDA_NO_VISTA', `El tipo ${tipo} tiene una duda declarada que no estaba a la vista cuando lo revisaste (la agregó otra persona o una recarga de semillas). Vuelve a cargar la configuración, lee la duda y confirma después: confirmar es responder por lo que se miró.`);
    }
    if (marcasDifieren(fila, input)) {
      throw new ApiError(409, 'MARCAS_CAMBIARON', `Las marcas del tipo ${tipo} cambiaron mientras las revisabas. Vuelve a cargar la configuración y revísalas otra vez antes de confirmarlas.`);
    }
    // Idempotente: reconfirmar no reescribe quién respondió por la revisión.
    if (fila.confirmado_en !== null) return marcaASalida(fila);
    fila.confirmado_por = u.correo;
    fila.confirmado_en = stamp();
    logBitacora(u.correo, 'confirmar_marca_percepcion', `catalogo_percepcion_marca:${tipo}`, { tipo_percepcion: tipo });
    return marcaASalida(fila);
  },

  async obtenerConfiguracionEmpresa(empresaId): Promise<ConfiguracionEmpresa> {
    // Leer pide CONSULTA y escribir OPERADOR: un usuario de consulta ya puede generar los
    // informes cuyo resultado depende de la zona salarial, así que esconderle la entrada
    // mientras se le muestra la salida no protege nada.
    requireRol(empresaId, 'consulta');
    const fila = db.configuracion_empresa.find((c) => c.empresa_id === empresaId);
    return {
      empresa_id: empresaId,
      zona_salarial: fila?.zona_salarial ?? null,
      dias_aguinaldo: fila?.dias_aguinaldo ?? null,
      factor_prima_vacacional: fila?.factor_prima_vacacional ?? null,
    };
  },

  async guardarConfiguracionEmpresa(empresaId, input: ConfiguracionEmpresaIn): Promise<ConfiguracionEmpresa> {
    const u = requireRol(empresaId, 'operador');
    if (input.dias_aguinaldo !== null && (!Number.isInteger(input.dias_aguinaldo) || input.dias_aguinaldo < 1 || input.dias_aguinaldo > 365)) {
      throw new ApiError(422, 'DATOS_INVALIDOS', 'dias_aguinaldo: el valor tiene que ser un entero entre 1 y 365.');
    }
    if (input.factor_prima_vacacional !== null) {
      const factor = importeNormalizado(exigeImporteCadena(input.factor_prima_vacacional));
      const decimales = factor && factor.includes('.') ? factor.split('.')[1].length : 0;
      if (factor === null || factor.startsWith('-') || factor === '0' || Number(factor) > 9.9999 || decimales > 4) {
        throw new ApiError(422, 'DATOS_INVALIDOS', 'factor_prima_vacacional: tiene que ser mayor que cero, máximo 9.9999, con hasta 4 decimales.');
      }
    }
    let fila = db.configuracion_empresa.find((c) => c.empresa_id === empresaId);
    if (!fila) {
      fila = { empresa_id: empresaId, zona_salarial: null, dias_aguinaldo: null, factor_prima_vacacional: null };
      db.configuracion_empresa.push(fila);
    }
    fila.zona_salarial = input.zona_salarial;
    fila.dias_aguinaldo = input.dias_aguinaldo;
    fila.factor_prima_vacacional = input.factor_prima_vacacional;
    logBitacora(u.correo, 'guardar_configuracion_empresa', `empresa:${empresaId}`, { ...input });
    return { empresa_id: empresaId, ...input };
  },

  async obtenerMapeosEmpresa(empresaId): Promise<MapeosEmpresa> {
    requireRol(empresaId, 'consulta');
    return leerMapeos(empresaId);
  },

  async guardarMapeosEmpresa(empresaId, input): Promise<MapeosEmpresa> {
    const u = requireRol(empresaId, 'operador');
    // Dos renglones con la misma clave natural se pisan entre sí: el backend los rechaza en vez
    // de guardar el último en silencio.
    exigeSinDuplicados(input.departamentos.map((d) => d.departamento_texto), 'departamentos', '`departamento_texto`');
    exigeSinDuplicados(input.conceptos_provision.map((c) => `${c.naturaleza}/${c.tipo}/${c.clave}`), 'conceptos_provision', 'la terna (`naturaleza`, `tipo`, `clave`)');
    // Y dos textos que la base considera la MISMA clave (`utf8mb4_unicode_ci`: ni mayúsculas ni
    // espacios finales) también se rechazan: el backend lo hace traduciendo el 1062 de MySQL con
    // `MAPEO_COLISION_DE_CLAVE`. Aquí se aproxima la colación, igual y por lo mismo que
    // `clave_en_la_base` en `conceptosObservados`.
    const vistas = new Map<string, string>();
    for (const d of input.departamentos) {
      const k = d.departamento_texto.trimEnd().toUpperCase();
      const antes = vistas.get(k);
      if (antes !== undefined) {
        throw new ApiError(422, 'MAPEO_COLISION_DE_CLAVE', `Dos de los renglones que mandaste son la misma clave para la base y solo cabe uno: ${JSON.stringify(antes)} y ${JSON.stringify(d.departamento_texto)}. \`map_departamento\` vive en \`utf8mb4_unicode_ci\`, que no distingue mayúsculas ni espacios al final. Deja uno solo; el que quede fuera seguirá cayendo al texto crudo en B-06, y arreglarlo de raíz exige migrar la columna (ver config/fiscal/README.md).`);
      }
      vistas.set(k, d.departamento_texto);
    }

    db.map_departamento = db.map_departamento.filter((m) => m.empresa_id !== empresaId);
    db.map_concepto_provision = db.map_concepto_provision.filter((m) => m.empresa_id !== empresaId);
    input.departamentos.forEach((d) => db.map_departamento.push({ empresa_id: empresaId, ...d }));
    input.conceptos_provision.forEach((c) => db.map_concepto_provision.push({ empresa_id: empresaId, ...c }));
    logBitacora(u.correo, 'guardar_mapeos_empresa', `empresa:${empresaId}`, { departamentos: input.departamentos.length, conceptos: input.conceptos_provision.length });
    return leerMapeos(empresaId);
  },

  async obtenerConceptosObservados(empresaId): Promise<ObservadosEmpresa> {
    requireRol(empresaId, 'consulta');
    const observados = db.nomina_observada.filter((n) => n.empresa_id === empresaId);
    const mapeos = leerMapeos(empresaId);
    const conceptos: ConceptoObservado[] = observados.map((n) => ({
      naturaleza: n.naturaleza, tipo: n.tipo, clave: n.clave, concepto: n.concepto,
      descripcion_sat: n.descripcion_sat, comprobantes: n.comprobantes, importe: n.importe,
      categoria: mapeos.conceptos_provision.find((m) => m.naturaleza === n.naturaleza && m.tipo === n.tipo && m.clave === n.clave)?.categoria ?? null,
    }));
    const textos = [...new Set(observados.map((n) => n.departamento))].sort();
    // `clave_en_la_base` la decide MySQL con la colación real de `map_departamento`
    // (`utf8mb4_unicode_ci`: ni mayúsculas ni espacios finales ni acentos). Aquí es una
    // **aproximación del mock** —recorte y mayúsculas— porque reproducir esa colación en
    // TypeScript no se puede hacer fielmente y fingirlo sería peor. Sirve para que la pantalla se
    // pueda desarrollar contra el caso; la verdad la da el backend.
    const claveAproximada = (t: string) => t.trimEnd().toUpperCase();
    const representante = new Map<string, string>();
    for (const t of textos) {
      const k = claveAproximada(t);
      if (!representante.has(k) || t < representante.get(k)!) representante.set(k, t);
    }
    const departamentos = textos.map((texto) => ({
      departamento_texto: texto,
      comprobantes: observados.filter((n) => n.departamento === texto).reduce((s, n) => s + n.comprobantes, 0),
      centro_costo: mapeos.departamentos.find((m) => m.departamento_texto === texto)?.centro_costo ?? null,
      clave_en_la_base: representante.get(claveAproximada(texto)) ?? texto,
    }));
    return {
      conceptos,
      departamentos,
      // Solo percepciones con clave. Sin clave no hay PK con la que mapear, y una deducción no
      // puede ser aguinaldo: contarlas dejaba el marcador clavado en un número que solo bajaba
      // capturando `NO_APLICA` donde no tocaba. Mismo criterio que `percepciones_sin_clasificar`
      // en el backend — el mock miente sobre el backend si se separan.
      sin_clasificar: conceptos.filter((c) => c.naturaleza === 'P' && c.categoria === null && c.clave !== null).length,
      sin_mapear: departamentos.filter((d) => d.centro_costo === null).length,
    };
  },

  // --- Tarifa del ISR (doc 05 §8bis, tarifa ISR) -----------------------------------------------

  async listarTarifasIsr(): Promise<ImportacionTarifas> {
    requireAdminMock('ver las tarifas del ISR');
    return {
      tarifas: [...db.tarifa_isr]
        .sort((a, b) => a.ejercicio - b.ejercicio || a.periodicidad.localeCompare(b.periodicidad))
        .map(tarifaIsrASalida),
      periodicidades_sin_tarifa: PERIODICIDADES_SIN_TARIFA_MOCK,
    };
  },

  // El mock **no simula el PDF**: no hay extractor de Anexo 8 en el cliente, así que
  // `importarTarifaIsr` devuelve siempre la misma lista fija — lo que el PDF real produciría es
  // exactamente lo que `listarTarifasIsr` ya expone, por diseño del propio recurso (§8bis: los
  // dos endpoints comparten helper del lado del servidor).
  async importarTarifaIsr(): Promise<ImportacionTarifas> {
    requireAdminMock('importar el Anexo 8');
    return apiMock.listarTarifasIsr();
  },

  async corregirTarifaIsr(ejercicio, periodicidad, renglones): Promise<TarifaIsr> {
    const u = requireAdminMock('corregir una tarifa del ISR');
    const fila = db.tarifa_isr.find((t) => t.ejercicio === ejercicio && t.periodicidad === periodicidad);
    if (!fila) throw new ApiError(404, 'TARIFA_NO_ENCONTRADA', `No hay tarifa ${ejercicio}/${periodicidad}.`);
    exigeTarifaValidaMock(renglones);
    fila.renglones = renglones.map((r) => ({ ...r }));
    fila.origen = 'MANUAL';
    // Corregir siempre limpia la confirmación previa, incluso si la hizo el mismo administrador.
    fila.confirmado_por = null;
    fila.confirmado_en = null;
    logBitacora(u.correo, 'corregir_tarifa_isr', `tarifa_isr:${ejercicio}/${periodicidad}`, { ejercicio, periodicidad });
    return tarifaIsrASalida(fila);
  },

  async confirmarTarifaIsr(ejercicio, periodicidad, huella): Promise<TarifaIsr> {
    const u = requireAdminMock('confirmar una tarifa del ISR');
    const fila = db.tarifa_isr.find((t) => t.ejercicio === ejercicio && t.periodicidad === periodicidad);
    if (!fila) throw new ApiError(404, 'TARIFA_NO_ENCONTRADA', `No hay tarifa ${ejercicio}/${periodicidad}.`);
    if (huellaDeTarifaMock(fila.renglones) !== huella) {
      throw new ApiError(409, 'TARIFA_CAMBIO', `La tarifa ${ejercicio}/${periodicidad} cambió mientras la revisabas. Vuelve a cargarla y revísala otra vez antes de confirmar.`);
    }
    // Idempotente: reconfirmar no reescribe quién la confirmó.
    if (fila.confirmado_en === null) {
      fila.confirmado_por = u.correo;
      fila.confirmado_en = stamp();
      logBitacora(u.correo, 'confirmar_tarifa_isr', `tarifa_isr:${ejercicio}/${periodicidad}`, { ejercicio, periodicidad });
    }
    return tarifaIsrASalida(fila);
  },

  async descartarTarifaIsr(ejercicio, periodicidad): Promise<void> {
    const u = requireAdminMock('descartar una tarifa del ISR');
    const idx = db.tarifa_isr.findIndex((t) => t.ejercicio === ejercicio && t.periodicidad === periodicidad);
    if (idx === -1) throw new ApiError(404, 'TARIFA_NO_ENCONTRADA', `No hay tarifa ${ejercicio}/${periodicidad}.`);
    if (db.tarifa_isr[idx].confirmado_en !== null) {
      throw new ApiError(409, 'TARIFA_CONFIRMADA', `La tarifa ${ejercicio}/${periodicidad} ya está confirmada. Para reemplazarla corrígela a mano o reimporta encima; no se borra una tarifa activa.`);
    }
    db.tarifa_isr.splice(idx, 1);
    logBitacora(u.correo, 'descartar_tarifa_isr', `tarifa_isr:${ejercicio}/${periodicidad}`, { ejercicio, periodicidad });
  },

  // Sin llamada de red que simular: en el mock, igual que en la implementación HTTP, es una
  // función pura que arma una URL — el endpoint real es de la Task 11 (hoja de revisión en PDF).
  urlHojaDeRevisionTarifa(ejercicio, periodicidad): string {
    return `/mock/tarifa-isr/${ejercicio}-${periodicidad}-hoja-revision.pdf`;
  },
};

function leerMapeos(empresaId: number): MapeosEmpresa {
  return {
    departamentos: db.map_departamento
      .filter((m) => m.empresa_id === empresaId)
      .map(({ departamento_texto, centro_costo }) => ({ departamento_texto, centro_costo }))
      .sort((a, b) => a.departamento_texto.localeCompare(b.departamento_texto)),
    conceptos_provision: db.map_concepto_provision
      .filter((m) => m.empresa_id === empresaId)
      .map(({ naturaleza, tipo, clave, categoria }) => ({ naturaleza, tipo, clave, categoria }))
      .sort((a, b) => `${a.naturaleza}${a.tipo}${a.clave}`.localeCompare(`${b.naturaleza}${b.tipo}${b.clave}`)),
  };
}

function exigeSinDuplicados(claves: string[], seccion: string, nombre: string): void {
  const vistas = new Set<string>();
  for (const clave of claves) {
    if (vistas.has(clave)) {
      throw new ApiError(422, 'MAPEO_DUPLICADO', `\`${seccion}\` trae ${nombre} repetida ('${clave}'). Dos renglones con la misma clave se pisan entre sí.`);
    }
    vistas.add(clave);
  }
}
