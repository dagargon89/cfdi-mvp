// Registro único de las secciones que todavía NO están listas. Cada entrada pinta una leyenda
// roja (`<SeccionIncompleta id="…" />`) en su pantalla. Cuando una sección quede lista, se borra
// su entrada aquí y la leyenda desaparece de todas partes: no hay que tocar ninguna página.
//
// Criterio de entrada (2026-10-06): la sección no puede cumplir hoy su propósito —por código que
// falta, por configuración pendiente o por el SAT— o nunca se ha comprobado de punta a punta con
// datos reales. Cada entrada dice cuándo se puede quitar.
//
// Lo que ya se avisa de forma DINÁMICA no entra aquí (p. ej. la sincronización con Banxico: la
// pantalla de Configuración fiscal muestra su alerta y la retira sola cuando se pone el token).
// Una leyenda fija sobre algo que cambia solo terminaría mintiendo.

export interface SeccionIncompleta {
  /** Encabezado corto de la leyenda. */
  titulo: string;
  /** Qué no funciona hoy, en términos de quien usa la pantalla. */
  motivo: string;
  /** Qué falta para que quede lista. */
  falta: string;
}

export const SECCIONES_INCOMPLETAS = {
  // Quitar cuando las solicitudes de Metadata terminen de forma confiable. Historial al
  // 2026-10-06: 6 descargadas de 48 solicitadas; 36 en error, casi todas por agotar 180 sondeos
  // con el SAT en "aceptada".
  'descargas-metadata': {
    titulo: 'La descarga de Metadata todavía no es confiable',
    motivo: 'El SAT acepta estas solicitudes pero casi nunca las termina: la mayoría se agotan después de una hora de espera y quedan en error.',
    falta: 'Una estrategia distinta para Metadata. Mientras tanto, usa CFDI (XML), que sí descarga con normalidad.',
  },
  // Quitar cuando haya una tarifa del ISR confirmada y las marcas de percepción confirmadas.
  'informe-B-09': {
    titulo: 'Este informe todavía no genera resultados',
    motivo: 'Necesita la tarifa del ISR (Anexo 8) importada y las marcas de percepción confirmadas. Sin ellas no produce ninguna fila.',
    falta: 'Importar el Anexo 8 y confirmar las marcas en Configuración → Fiscal.',
  },
  // Quitar cuando las marcas de percepción que usa la nómina estén confirmadas.
  'informe-B-03': {
    titulo: 'Resultados parciales',
    motivo: 'Las columnas de base, tope y exceso de exención salen vacías mientras las marcas de percepción no estén confirmadas.',
    falta: 'Confirmar las marcas de percepción en Configuración → Fiscal.',
  },
  // Quitar cuando estén confirmadas las marcas de percepción y la tarifa del ISR.
  'informe-B-05': {
    titulo: 'Resultados parciales',
    motivo: '«Gravado ordinario» y las columnas anuales del ISR salen vacías mientras falten las marcas de percepción confirmadas y la tarifa del ISR.',
    falta: 'Confirmar las marcas e importar el Anexo 8 en Configuración → Fiscal.',
  },
  // Quitar cuando la empresa tenga su mapeo de departamentos a centros de costo.
  'informe-B-06': {
    titulo: 'Resultados parciales',
    motivo: 'Sin el mapeo de departamentos a centros de costo, el informe agrupa por el texto del departamento tal como viene en cada CFDI.',
    falta: 'Capturar el mapeo de departamentos en la Configuración de la empresa.',
  },
  // Quitar cuando exista el evento `error_descarga` y se haya visto llegar un aviso real.
  notificaciones: {
    titulo: 'Los avisos por correo están incompletos',
    motivo: 'El aviso de «error en una descarga» no está implementado: ningún proceso genera ese evento, así que suscribirse a él no envía nada. Además, esta instalación todavía no ha enviado ningún aviso real.',
    falta: 'Implementar el evento de error de descarga y comprobar el envío de un correo real.',
  },
  // Quitar después de una prueba completa con una cuenta real: registrarse, aprobar y entrar.
  registro: {
    titulo: 'El registro de cuentas no está verificado',
    motivo: 'El auto-registro pasa sus pruebas automáticas, pero no se ha comprobado de punta a punta con una cuenta real.',
    falta: 'Una prueba completa: crear la cuenta, que un administrador la apruebe y entrar con ella.',
  },
  // Se muestra en el LOGIN: la pantalla de recuperación existe (`features/auth/RecuperarPage.tsx`)
  // pero no tiene ruta desde el commit 085001c, así que quien olvida su contraseña solo ve esto.
  // Quitar cuando haya un restablecimiento que resista a los escáneres de correo y vuelva su ruta.
  recuperar: {
    titulo: 'La recuperación de contraseña está deshabilitada',
    motivo: 'El enlace de restablecimiento es de un solo uso, y los filtros de seguridad del correo lo abrían antes que la persona: llegaba ya vencido.',
    falta: 'Un restablecimiento que resista a esos filtros. Mientras tanto, si olvidaste tu contraseña, pide a un administrador que restablezca tu acceso.',
  },
} satisfies Record<string, SeccionIncompleta>;

export type SeccionIncompletaId = keyof typeof SECCIONES_INCOMPLETAS;

/** Para claves dinámicas (p. ej. `informe-${clave}`): `null` si la sección no está registrada. */
export function seccionIncompleta(id: string): SeccionIncompleta | null {
  return (SECCIONES_INCOMPLETAS as Record<string, SeccionIncompleta>)[id] ?? null;
}
