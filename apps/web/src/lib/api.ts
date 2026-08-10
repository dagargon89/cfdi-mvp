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
  /** Añadido post-freeze (2026-08-06, informes fase 3): la tarea diaria `revisar_vigencia_fiscal`
   * —la alarma de calendario de doc 05 §8bis y la sincronización del tipo de cambio con Banxico—.
   * Es el único interruptor con default en el cuerpo del `PUT` del backend (llegó después del
   * contrato congelado), pero la pantalla manda siempre los cinco: `{...autos, [clave]: valor}`
   * sobre lo que devolvió el `GET`, para que el default no reencienda lo que alguien apagó. */
  vigencia_fiscal: boolean;
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

/** Por qué una alerta necesita seis motivos y no tres (doc 05 §8bis).
 *
 * Los tres primeros describen **un valor** y piden acciones distintas: `AUSENTE` = hay que ir a
 * capturarlo; `SIN_CONFIRMAR` = ya hay una propuesta y es **un clic**; `CADUCADO` = lo que hay es
 * de un ejercicio anterior a una fecha de actualización que ya pasó (la UMA cambia el 1 de febrero
 * y el salario mínimo el 1 de enero), así que confirmar lo que hay no lo arregla.
 *
 * Los tres últimos no hablan de ningún valor sino de **la maquinaria**: el catálogo de `satcfdi`
 * no se puede leer, la versión instalada de la librería lleva más de un año, o el último intento
 * de sincronizar con Banxico falló. Presentarlas como si fueran valores haría que la alerta
 * mintiera —un catálogo que no abre no es un valor "ausente" ni pide capturar nada—, y por eso la
 * pantalla las separa en dos bloques. */
export type MotivoAlertaVigencia =
  | 'AUSENTE'
  | 'SIN_CONFIRMAR'
  | 'CADUCADO'
  | 'CATALOGO_ILEGIBLE'
  | 'LIBRERIA_DESACTUALIZADA'
  | 'SINCRONIZACION_FALLIDA';

/** Una alerta de la alarma de vigencia. Se recalcula en cada `GET` (depende de la fecha de hoy) y
 * no hace ninguna llamada de red. `detalle` es **la frase lista para mostrar**: `motivo` es una
 * etiqueta de máquina y las de maquinaria no se explican solas. `vigencia_desde` y
 * `fecha_esperada` son nulas en las de maquinaria y `clave` es entonces una clave sintética
 * (`CATALOGO_SAT_PERCEPCIONES`, `VERSION_SATCFDI`, `SINCRONIZACION_BANXICO`). */
export interface AlertaVigencia {
  clave: string;
  motivo: MotivoAlertaVigencia;
  vigencia_desde: string | null;
  fecha_esperada: string | null;
  detalle: string;
}

/** `claves_sin_valor` es el tercer estado: claves conocidas de las que no hay **ni propuesta**.
 * `alertas` es lo que `claves_sin_valor` **no puede decir: que un valor confirmado ya caducó**. */
export interface ConfiguracionFiscal {
  parametros: ParametroFiscal[];
  claves_sin_valor: string[];
  alertas: AlertaVigencia[];
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

/** Sobre qué se calcula el tramo exento de un tipo de percepción (doc 05 §8bis). */
export type BaseExencion = 'UMA_DIAS' | 'SM_DIAS' | 'PORCENTAJE' | 'NINGUNA';

/** Las **seis marcas que calculan** de un tipo de percepción: el cuerpo de
 * `confirmarMarcaPercepcion` y la parte de `guardarMarcaPercepcion` que provoca el 409.
 *
 * `factor_exencion` es **cadena o nula**, como todos los importes del contrato, y su unidad la
 * decide `base_exencion`:
 * - `UMA_DIAS` → número de días de UMA exentos ("15" = 15 días de UMA);
 * - `SM_DIAS` → número de días de salario mínimo exentos;
 * - `PORCENTAJE` → **porcentaje en escala 0-100, no una fracción**: "100" es el cien por ciento
 *   y "50" es la mitad. La convención la fija la semilla `config/fiscal/catalogo_percepcion.yaml`
 *   y quien consuma el campo tiene que respetarla — leer "100" como "100 veces" multiplicaría por
 *   cien la exención de seis tipos de previsión social;
 * - `NINGUNA` → **nulo obligatorio** (gravado íntegro).
 *
 * `sujeto_a_tope_conjunto` **no lleva default a propósito** (422 si se omite): es el mismo cuerpo
 * con el que se confirma, y un default de `false` dejaría activar una marca de previsión social
 * sin el tope conjunto del art. 93 a la vista. Con `base_exencion: NINGUNA` tiene que ir en
 * `false` — no hay exención que topar. */
export interface MarcasPercepcion {
  es_ingreso_ordinario: boolean;
  base_exencion: BaseExencion;
  factor_exencion: string | null;
  integra_sbc: boolean;
  es_provisionable: boolean;
  sujeto_a_tope_conjunto: boolean;
  /** Si al `factor_exencion` le falta un multiplicador que el CFDI **no trae** ("90 UMA por año de
   * servicio", "15 UMA diarias", "1 UMA por domingo"): nueve tipos. Con esto en `true`, B-03 deja
   * el tope vacío en vez de calcularlo suponiendo un multiplicador de 1.
   *
   * **Tampoco lleva default** (422 si se omite), y por un motivo más directo que el del tope: este
   * campo *sí* calcula, así que omitirlo activaría el cálculo de un tope inventado sin que nadie lo
   * hubiera mirado. */
  multiplicador_no_derivable: boolean;
}

/** Cuerpo del `PUT`: las seis marcas **más la duda declarada**. `nota_revision` es obligatoria
 * aunque admita `null` (422 si se omite): con un default, un `PUT` que corrige un factor borraría
 * en silencio una duda que alguien derivó contra la LISR. Borrarla tiene que costar mandar
 * `null`. Y si la nota **aparece o cambia**, la confirmación de la marca se limpia. */
export interface MarcaPercepcionIn extends MarcasPercepcion {
  nota_revision: string | null;
}

/** Cuerpo del `POST .../confirmar`: las seis marcas **más la huella de la duda que se tenía
 * delante**.
 *
 * `nota_revision_hash` es un **valor opaco que emite el servidor** (`MarcaPercepcion.
 * nota_revision_hash` del `GET`) y que el cliente devuelve **tal cual**: nunca se calcula, ni se
 * compara, ni se interpreta aquí. Si el cliente lo calculara tendría que reproducir byte a byte la
 * normalización del servidor, y cualquier discrepancia sería un 409 inexplicable.
 *
 * Cierra la forma **concurrente** de confirmar a ciegas: A abre `010` sin duda, B le agrega una
 * por `PUT`, A pulsa Confirmar — las seis marcas no cambiaron, así que antes eso daba 200 y la
 * marca quedaba confirmada con una duda que nadie vio. Ahora es **409 `DUDA_NO_VISTA`**.
 *
 * La comprobación es **asimétrica** a propósito, igual que la del `PUT`: si la duda aparece o
 * cambia, 409; si se **resolvió** entre que se pintó la pantalla y el clic, la confirmación pasa
 * —quien revisó lo hizo contra más información de la que hay hoy—.
 *
 * **Sin default** (422 si se omite): `null` no es una omisión, afirma "la marca que revisé no
 * tenía duda declarada", y es lo que mandan las 5 de las 44 que no traen ninguna. */
export interface MarcaPercepcionConfirmarIn extends MarcasPercepcion {
  nota_revision_hash: string | null;
}

/** Una fila de `catalogo_percepcion_marca`. `nota_revision` es **la duda declarada** de ese tipo:
 * qué la genera y qué habría que verificar antes de confirmarlo (39 de las 44 marcas sembradas
 * traen una). Viaja aquí para que se vea al lado del botón de confirmar — sin ella, confirmar
 * sería a ciegas, que es justo lo que el invariante existe para impedir. */
export interface MarcaPercepcion extends MarcasPercepcion {
  tipo_percepcion: string;
  /** La descripción de `c_TipoPercepcion` ("Becas para trabajadores y/o hijos"), resuelta del
   * **mismo** `satcfdi` que valida la escritura. Nula si la clave no está en la versión instalada
   * o si el catálogo no se pudo leer (leer falla abierto; escribir no: 503). */
  descripcion_sat: string | null;
  nota_revision: string | null;
  /** Huella **opaca** de `nota_revision`, para devolverla tal cual al confirmar. Ver
   * `MarcaPercepcionConfirmarIn`. Nula cuando no hay duda declarada. */
  nota_revision_hash: string | null;
  confirmado: boolean;
  confirmado_por: string | null;
  confirmado_en: string | null;
}

/** El `GET` de percepciones devuelve un **objeto, no una lista**.
 *
 * `claves_sin_marcas` son las claves de `c_TipoPercepcion` que todavía no tienen ninguna marca
 * capturada, y espeja `claves_sin_valor` de `/fiscal`. Existe para que **el denominador sea
 * autoritativo**: antes el cliente llevaba su propia copia del catálogo del SAT, y esa copia no
 * solo describía —decidía qué tarjetas existen, y por tanto el "0 de 44" y el tercer estado—. Al
 * subir la versión de `satcfdi` la lista del servidor crecía y la del cliente no. Con este campo
 * esa copia sobra y se borró (`catalogoTipoPercepcion.ts`).
 *
 * Llega **vacía** si el catálogo embebido no se puede leer (misma lectura que `descripcion_sat`,
 * falla abierto); la señal autoritativa de esa avería es la alerta `CATALOGO_ILEGIBLE` de
 * `/fiscal`, que la misma pantalla ya consulta. */
export interface CatalogoPercepciones {
  marcas: MarcaPercepcion[];
  claves_sin_marcas: string[];
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

/** Un texto de departamento tal como viene en los CFDI, **byte a byte**: `'EDIFICIOS'` y
 * `'Edificios '` son dos renglones. Antes colapsaban en uno (el agrupamiento iba con la colación
 * de la columna, que no distingue mayúsculas ni espacios finales) y la pantalla no podía enseñar
 * lo que B-06 luego nombraba en `DEPARTAMENTO_SIN_MAPEO`.
 *
 * `clave_en_la_base` es la clave que `map_departamento` usaría, y **la decide MySQL**. Cuando no
 * coincide con `departamento_texto`, otra variante comparte clave con esta y **solo una de las dos
 * puede llevar centro de costo** hasta que se migre la columna: hay que avisarlo antes de que
 * alguien gaste el intento, porque el segundo guardado se rechaza con `MAPEO_COLISION_DE_CLAVE`. */
export interface DepartamentoObservado {
  departamento_texto: string;
  comprobantes: number;
  centro_costo: string | null;
  clave_en_la_base: string;
}

/** `sin_clasificar` es el marcador que la pantalla necesita para decir "te faltan N": mientras
 * no sea cero, B-08 no puede distinguir "no se pagó aguinaldo" de "sí se pagó y no sé dónde".
 *
 * Cuenta **solo percepciones con clave**. Lo que B-08 concilia es cuánto se pagó ya de aguinaldo,
 * vacaciones y prima vacacional, y eso son percepciones: una deducción no puede ser aguinaldo. */
export interface ObservadosEmpresa {
  conceptos: ConceptoObservado[];
  departamentos: DepartamentoObservado[];
  sin_clasificar: number;
  sin_mapear: number;
}

/* ------------------------------------------------------------------------------------------
 * Tarifa del ISR (Anexo 8 de la RMF) — añadido post-freeze (2026-08-10, tarifa ISR). Solo
 * administrador: la tarifa es política federal, igual que `param_fiscal`, no política de una
 * empresa. Mismo invariante que el resto del recurso: **una tarifa sin confirmar no calcula**;
 * importar y corregir *proponen*, solo confirmar la activa.
 *
 * Los importes de los renglones viajan como **cadena**, en las dos direcciones: la huella se
 * calcula sobre el valor exacto y un número JSON que perdió precisión al pasar por `float` no
 * coincidiría nunca al confirmar, lo que produciría un 409 imposible de explicar.
 * ---------------------------------------------------------------------------------------- */

/** Periodicidades **como las publica el Anexo 8**, no como las nombra el CFDI: el catálogo
 * `c_PeriodicidadPago` del SAT tiene periodicidades para las que el Anexo no publica tarifa
 * (`03` catorcenal, `06` bimestral) y admitirlas aquí sugeriría que existen. */
export type PeriodicidadTarifaIsr = 'DIARIA' | 'DIAS_7' | 'DIAS_10' | 'DIAS_15' | 'MENSUAL' | 'EJERCICIO';

/** Procedencia de una tarifa. `IMPORTADA` no es una semilla: viene del documento oficial que
 * alguien subió, y su huella queda en `TarifaIsr.documento_sha256`. */
export type OrigenTarifaIsr = 'IMPORTADA' | 'MANUAL';

/** Cuerpo para corregir un renglón a mano. **Sin `tasa_porcentaje`**: ese lo calcula siempre el
 * servidor, nunca se manda. */
export interface TarifaIsrRenglonIn {
  renglon: number;
  limite_inferior: string;
  limite_superior: string | null;
  cuota_fija: string;
  /** Fracción decimal, que es como se guarda y como calcula: "0.213600". */
  tasa_excedente: string;
}

/** Un renglón de una tarifa del ISR, ya calculado. `limite_superior` nulo es el último renglón
 * ("En adelante"). */
export interface TarifaIsrRenglon {
  renglon: number;
  limite_inferior: string;
  limite_superior: string | null;
  cuota_fija: string;
  /** Fracción decimal, que es como se guarda y como calcula: "0.213600". */
  tasa_excedente: string;
  /** El mismo número como lo publica el SAT y como lo lee un contador: "21.36". Lo calcula el
   *  servidor a propósito: es el único número donde equivocar la escala cambia el resultado por
   *  cien — la pantalla **nunca** debe multiplicar `tasa_excedente` por 100 por su cuenta. */
  tasa_porcentaje: string;
}

/** Comparación de la tarifa contra un recibo real. **No es un dictamen fiscal**: sirve para detectar
 *  un error de carga (una tabla de otro año o de otra periodicidad pasa las validaciones
 *  estructurales pero aquí da una diferencia enorme). Los campos del recibo son nulos cuando el
 *  CFDI no los trae — eso no es un error de carga, es un complemento incompleto. */
export interface ComprobacionTarifa {
  uuid: string;
  fecha_inicial_pago: string | null;
  fecha_final_pago: string | null;
  num_empleado: string | null;
  dias_pagados: string | null;
  gravado: string;
  renglon: number;
  limite_inferior: string;
  /** Fracción decimal del renglón que aplicó, no el porcentaje — igual que en `TarifaIsrRenglon`. */
  tasa_excedente: string;
  isr_calculado: string;
  isr_timbrado: string;
  diferencia: string;
  /** Razones por las que la diferencia puede ser esperada, en español y listas para mostrar. */
  advertencias: string[];
}

/** Una tarifa completa del ISR, con su procedencia, su estado de confirmación y sus renglones. */
export interface TarifaIsr {
  ejercicio: number;
  periodicidad: PeriodicidadTarifaIsr;
  /** En el idioma de un recibo de nómina ("Quincenal (15 días)"), ya traducida por el servidor
   * — nunca el nombre del enum (`DIAS_15`). El frontend no traduce nombres de enum. */
  etiqueta: string;
  /** La clave de `c_PeriodicidadPago` a la que corresponde esta tarifa, o `null` para
   * `EJERCICIO`: el Anexo la publica para el ingreso de todo un año, no para un recibo. */
  periodicidad_cfdi: string | null;
  origen: OrigenTarifaIsr;
  fuente: string;
  documento_sha256: string | null;
  encabezado: string;
  importado_en: string;
  confirmado_por: string | null;
  confirmado_en: string | null;
  confirmada: boolean;
  /** `true` si `origen: MANUAL`: una tarifa corregida a mano ya no es, por definición, lo que
   * dice el último documento importado. */
  difiere_del_documento: boolean;
  /** `true` solo en la tarifa cuya periodicidad es la que de verdad timbra la nómina observada
   * (regla B-09.R1: la moda de `nomina_receptor.periodicidad_pago`), no una preferencia de la
   * pantalla. */
  aplica_a_la_nomina: boolean;
  /** Huella (SHA-256) de los renglones vigentes: se manda tal cual a `confirmarTarifaIsr`. */
  huella: string;
  renglones: TarifaIsrRenglon[];
  comprobacion: ComprobacionTarifa | null;
}

/** El `GET` y el `POST .../importar` devuelven la misma forma (mismo helper del lado del
 * servidor), para que la lista y la importación nunca puedan mostrar cosas distintas. */
export interface ImportacionTarifas {
  tarifas: TarifaIsr[];
  /** Claves de `c_PeriodicidadPago` que la nómina real usa y para las que el Anexo 8 no publica
   * tarifa (`03` catorcenal, `06` bimestral): enterarse aquí es mejor que enterarse cuando el
   * informe de nómina salga rotulado. */
  periodicidades_sin_tarifa: string[];
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
  /* Marcas de exención por tipo de percepción (art. 93 LISR) — solo administrador. `{tipo}` se
   * valida contra `c_TipoPercepcion` del catálogo embebido de `satcfdi`: **422
   * `TIPO_PERCEPCION_INVALIDO`** si no existe, y **503 `CATALOGO_SAT_ILEGIBLE`** —transitorio— si
   * el catálogo no se puede leer, en el `PUT` y en el `confirmar`: no se escribe sin poder
   * validar. */
  /** Devuelve `{marcas, claves_sin_marcas}` — un objeto, no una lista: el denominador del
   * "0 de 44" lo pone el servidor. */
  listarMarcasPercepcion(): Promise<CatalogoPercepciones>;
  /** Captura o corrige las marcas de un tipo. **No confirma**, y limpia la confirmación anterior
   * si alguna de las seis marcas cambió o si la duda declarada apareció o cambió. */
  guardarMarcaPercepcion(tipo: string, input: MarcaPercepcionIn): Promise<MarcaPercepcion>;
  /** Confirma **las marcas que se están confirmando** (las seis, sin el texto de la nota) **más la
   * huella de la duda que se tenía delante**: 409 `MARCAS_CAMBIARON` si las marcas no coinciden
   * con lo almacenado, 409 `DUDA_NO_VISTA` si la duda de hoy no es la que el cliente vio.
   * Idempotente. */
  confirmarMarcaPercepcion(tipo: string, input: MarcaPercepcionConfirmarIn): Promise<MarcaPercepcion>;
  obtenerConfiguracionEmpresa(empresaId: number): Promise<ConfiguracionEmpresa>;
  guardarConfiguracionEmpresa(empresaId: number, input: ConfiguracionEmpresaIn): Promise<ConfiguracionEmpresa>;
  obtenerMapeosEmpresa(empresaId: number): Promise<MapeosEmpresa>;
  /** Reemplaza las dos listas completas: hay que mandar también la que no se está editando. */
  guardarMapeosEmpresa(empresaId: number, input: MapeosEmpresa): Promise<MapeosEmpresa>;
  obtenerConceptosObservados(empresaId: number): Promise<ObservadosEmpresa>;
  /* Tarifa del ISR (Anexo 8 de la RMF), solo administrador — añadido post-freeze (2026-08-10,
   * tarifa ISR). Importar y corregir PROPONEN (`confirmada: false`); solo `confirmarTarifaIsr`
   * la activa, y exige la huella de los renglones que se revisó (`TarifaIsr.huella`), igual que
   * `confirmarParametroFiscal`: 409 `TARIFA_CAMBIO` si no coincide con la almacenada. */
  listarTarifasIsr(): Promise<ImportacionTarifas>;
  /** Multipart, no JSON: `archivo` es el PDF del Anexo 8 tal como lo publica el SAT (mismo
   * patrón que `subirEfirma`). Las tarifas quedan **sin confirmar** (`origen: IMPORTADA`). Todo
   * o nada por documento: si una tabla del PDF no pasa las seis pruebas del Anexo I.1, no se
   * guarda ninguna. */
  importarTarifaIsr(archivo: File): Promise<ImportacionTarifas>;
  /** Corrección manual: la lista **completa** de renglones, no un diff — se revalidan las seis
   * pruebas del Anexo I.1 sobre la tarifa entera, porque cambiar un límite puede romper la
   * continuidad con su vecino. Limpia la confirmación previa, incluso si la hizo el mismo
   * administrador que corrige. */
  corregirTarifaIsr(ejercicio: number, periodicidad: PeriodicidadTarifaIsr, renglones: TarifaIsrRenglonIn[]): Promise<TarifaIsr>;
  /** El cliente manda la huella de **lo que revisó**; 409 `TARIFA_CAMBIO` si no coincide con la
   * almacenada — la tarifa cambió entre que se pintó la pantalla y que se hizo clic.
   * Idempotente: reconfirmar no reescribe quién la confirmó. */
  confirmarTarifaIsr(ejercicio: number, periodicidad: PeriodicidadTarifaIsr, huella: string): Promise<TarifaIsr>;
  /** Solo sobre una tarifa **sin confirmar**: 409 `TARIFA_CONFIRMADA` si ya se confirmó — para
   * reemplazar una confirmada se corrige a mano o se reimporta encima, nunca se borra primero. */
  descartarTarifaIsr(ejercicio: number, periodicidad: PeriodicidadTarifaIsr): Promise<void>;
  /** URL de la hoja de revisión en PDF, para abrir o descargar (Task 11 de este mismo plan). Es
   * la única función de este bloque que no es asíncrona: no hace la petición, solo construye la
   * URL para un `<a href>`. `require_admin`; no escribe bitácora, es una lectura. */
  urlHojaDeRevisionTarifa(ejercicio: number, periodicidad: PeriodicidadTarifaIsr): string;
}
