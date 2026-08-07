// `c_TipoPercepcion` del SAT — las 44 claves con su descripción oficial.
//
// **Por qué vive en el cliente y no llega en la respuesta.** `GET /v1/configuracion/percepciones`
// (doc 05 §8bis) devuelve las *marcas* de cada tipo, no su descripción: el servidor valida la clave
// contra el catálogo embebido de `satcfdi` pero no la enuncia. Y una pantalla que pidiera confirmar
// marcas de exención mostrando solo `015` estaría pidiendo confirmar sobre una clave que nadie se
// sabe de memoria; la descripción es parte de lo que hay que tener delante para responder por la
// revisión. Mientras la descripción no viaje en el contrato, esta tabla es el único lugar donde
// puede estar.
//
// **De dónde salieron estas 44 líneas:** enumeradas del propio catálogo de la versión pinada de
// `satcfdi` (`app.informes.catalogos.tipos_de_estricto('P')`, el mismo que usa
// `exige_tipo_percepcion_conocido` en el servidor), no tecleadas de memoria. Si el SAT publica un
// tipo nuevo, el servidor lo aceptará y la pantalla mostrará su clave sin descripción — degradado,
// no roto: ver `descripcionTipoPercepcion`.
export const TIPO_PERCEPCION_SAT: Record<string, string> = {
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

export const TIPOS_PERCEPCION_SAT = Object.keys(TIPO_PERCEPCION_SAT);

/** La descripción del SAT, o un texto honesto cuando la clave no está en esta copia del catálogo
 * (tipo nuevo publicado después de la versión pinada de `satcfdi`): decir "tipo desconocido" es
 * mejor que inventarle un nombre, y la marca se sigue pudiendo revisar. */
export function descripcionTipoPercepcion(tipo: string): string {
  return TIPO_PERCEPCION_SAT[tipo] ?? 'Tipo de percepción que no está en la copia del catálogo del SAT de esta versión.';
}
