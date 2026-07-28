/** Dispara la descarga de un `Blob` en el navegador (PDF/zip que llegan como respuesta binaria
 * autenticada — a diferencia de `xml_path`, que ya es una URL firmada abrible directo). */
export function descargarBlob(blob: Blob, nombreArchivo: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = nombreArchivo;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
