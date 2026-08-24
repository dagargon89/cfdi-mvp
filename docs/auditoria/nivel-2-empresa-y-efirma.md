# Auditoría del nivel 2 — Empresa y e.firma

**Fecha:** 2026-08-20
**Sistema:** Hub CFDI · rama `main` · base real de la empresa 11
**Método:** pruebas adversariales automatizadas + lectura directa de la base + verificación en vivo
**Batería:** [`tests/auditoria/test_nivel2_efirma.py`](../../tests/auditoria/test_nivel2_efirma.py)

## Veredicto

**El nivel 2 resiste, y es el mejor construido de los dos auditados.** 19 de 19 pruebas en verde al
primer intento, y la e.firma real que hay hoy en la bóveda está correctamente cifrada — comprobado
leyendo la tabla, no confiando en el código.

**Sin hallazgos de severidad apreciable.** Una observación marginal en §6 (el tamaño del blob revela
la longitud de la contraseña) y un límite de mi propia batería en §5, ambos anotados por honestidad
más que por riesgo.

## 1. Por qué este nivel es distinto

Un fallo en el nivel 1 filtra datos. Un fallo aquí filtra **la capacidad de actuar como el
contribuyente ante el SAT**: la clave privada de su e.firma y la contraseña que la abre. No hay
forma de deshacer eso con un cambio de contraseña.

Por eso las pruebas no se conforman con lo que responde la API: **abren la base de datos y
comprueban que el material no está ahí en claro**. Es la prueba que un respaldo robado tiene que
suspender.

## 2. El diseño que se auditó

| Pieza | Cómo funciona |
|---|---|
| DEK | Clave aleatoria de 256 bits **por cada e.firma**; cifra el `.key` y la contraseña |
| KEK | Clave maestra que envuelve cada DEK; vive en un **archivo fuera de la base** |
| `cer_pem` | Se guarda en claro **a propósito**: el certificado es información pública |
| Cifrado | AES-GCM con nonce de 12 bytes prefijado al blob |

La tesis del diseño es una sola frase: **robar la base sin robar la KEK no alcanza.** Todo lo demás
son consecuencias de eso.

## 3. Pruebas automatizadas

19 pruebas, todas **PASA**.

### Confidencialidad del material

| ID | Ataque | Esperado | Resultado |
|---|---|---|---|
| N2-01 | ¿El alta devuelve la clave o la contraseña en el JSON? | solo metadatos | **PASA** |
| N2-02 | ¿El `.key` está en claro en la tabla? | cifrado, y más largo que el original | **PASA** |
| N2-03 | ¿La contraseña está en claro en la tabla? | cifrada | **PASA** |
| N2-04 | ¿La DEK sirve por sí sola, tal como está guardada? | no: hay que desenvolverla | **PASA** |
| N2-05 | ¿Una KEK ajena abre el material? | no | **PASA** |
| N2-06 | ¿El `GET` es una vía para extraer la e.firma? | solo metadatos | **PASA** |

N2-02 no se conforma con `key_cifrada != key`: comprueba también que **el blob mide más que el
original**. Un cifrado que preserva el tamaño exacto delataría un XOR o un modo sin nonce ni tag.

N2-04 lleva un control positivo dentro: tras comprobar que la DEK guardada no descifra nada,
la desenvuelve con la KEK real y confirma que **entonces sí** recupera el `.key` byte a byte. Sin esa
segunda mitad, la prueba pasaría igual si el cifrado estuviera roto de otra forma.

### Identidad del certificado

| ID | Ataque | Esperado | Resultado |
|---|---|---|---|
| N2-07 | **Subir la e.firma de otro contribuyente** | 422 `RFC_NO_COINCIDE` y nada guardado | **PASA** |
| N2-08 | Contraseña incorrecta | 422 `EFIRMA_NO_ABRE` y nada guardado | **PASA** |
| N2-09 | FIEL vencida | 422 `EFIRMA_VENCIDA` | **PASA** |
| N2-10 | `.cer` y `.key` que no son pareja | 422 y nada guardado | **PASA** |
| N2-11 | Archivos basura en lugar de certificados | 422, **nunca 500** | **PASA** |
| N2-12 | ¿El mensaje de error repite la contraseña enviada? | no aparece | **PASA** |

**N2-07 es el ataque más grave de este nivel.** Si el RFC del certificado no se comparara con el de
la empresa, un operador podría subir la FIEL de un tercero —obtenida de un respaldo, un correo, un
despacho contable— y el Hub descargaría los CFDI de ese tercero como si fueran suyos. La comparación
es lo que ata la llave a su dueño. La prueba no se conforma con el 422: confirma que **no quedó
ninguna fila** en la tabla.

N2-11 exige 422 y no 500 por una razón concreta: un 500 significa que una excepción sin traducir
llegó al manejador global, y con ella un rastro de pila en los logs **alrededor de material
criptográfico**.

### Aislamiento y permisos sobre la bóveda

| ID | Ataque | Esperado | Resultado |
|---|---|---|---|
| N2-13 | Alcanzar la bóveda de otra empresa | 404 | **PASA** |
| N2-14 | Rol `consulta` sube una e.firma | 403 | **PASA** |
| N2-15 | Rol `consulta` borra la e.firma | 403 | **PASA** |
| N2-16 | *Control positivo*: `consulta` sí ve la vigencia | 200 | **PASA** |

N2-16 existe porque el rol de consulta **debe** poder ver cuándo vence la e.firma; si no, no podría
avisar de la renovación. Sin el control positivo, cerrar el acceso por completo dejaría N2-14 y
N2-15 en verde.

### Identidad fiscal de la empresa

| ID | Ataque | Esperado | Resultado |
|---|---|---|---|
| N2-17 | Dos empresas con el mismo RFC | 409 `RFC_DUPLICADO` | **PASA** |
| N2-18 | RFC malformado | 400 `RFC_MALFORMADO` | **PASA** |
| N2-19 | Un operador crea una empresa | 403 | **PASA** |

N2-17 importa más de lo que parece: dos empresas con el mismo RFC partirían el acervo del mismo
contribuyente en dos, y los informes discreparían según cuál se abriera.

## 4. Verificación en vivo sobre la bóveda real

Lectura directa de la tabla `efirmas` en la base de producción. **Solo lectura, sin efectos.**

| Comprobación | Resultado |
|---|---|
| e.firma en bóveda | 1 (empresa 11), serie `…349243440`, vigente **2025-10-29 → 2029-10-29** |
| `cer_pem` | 1 644 bytes en claro — **correcto**, el certificado es público |
| `key_cifrada` con PEM legible (`BEGIN`, `PRIVATE KEY`) | **0 filas** |
| `password_cifrada` legible como texto ASCII | **0 filas** |
| `dek_envuelta` | **60 bytes** |

**Los 60 bytes de `dek_envuelta` son la prueba aritmética de que la DEK está envuelta:** 12 (nonce) +
32 (DEK de 256 bits) + 16 (tag de AES-GCM) = 60. Si estuviera en claro medirían 32. No hace falta
creerle al código: el tamaño ya lo dice.

### Protección de la KEK

| Comprobación | Resultado |
|---|---|
| Tamaño | 32 bytes = 256 bits |
| Permisos | `-rw-------` (600), propietario `appuser` |
| ¿Fuera de la base? | Sí, archivo en `/srv/secrets/` |
| ¿Versionada en git? | **No** — `secrets/` está en `.gitignore:15` y `git ls-files secrets/` sale vacío |

La credencial de servicio de Firebase está igualmente en 600.

## 5. ¿Protegen algo estas pruebas?

Se rompió `app/services/boveda.py` tres veces a propósito.

| Mutación | Pruebas que deben caer | Resultado |
|---|---|---|
| **A** — se elimina `validar_rfc(signer, rfc_empresa)` | N2-07 | **1 de 1 falló** ✓ |
| **B** — `key_cifrada=key_bytes` (clave privada en claro) | N2-02 | **2 fallaron** (N2-02 y N2-04) ✓ |
| **C** — `dek_envuelta=dek` (DEK sin envolver) | N2-04, N2-05 | **1 de 2 falló** |

**El límite de mi propia batería, dicho claro.** En la mutación C, **N2-05 sobrevive**: comprueba
que una KEK *ajena* no abre el material, y eso sigue siendo cierto aunque la DEK esté guardada sin
envolver. El vector "DEK en claro junto al blob" lo detecta **N2-04**, no N2-05. Están cubriendo
cosas distintas, así que la cobertura del vector existe — pero si alguien borrara N2-04, N2-05 no lo
notaría. Queda anotado para quien mantenga estas pruebas.

## 6. Observación marginal — el tamaño del blob revela la longitud de la contraseña

**Severidad: mínima. Sin acción recomendada.**

AES-GCM no rellena, así que el tamaño del blob es el del texto claro más 28 bytes fijos. En la
bóveda real, `password_cifrada` mide 36 bytes: **la contraseña de la FIEL tiene 8 caracteres**, y eso
se deduce sin descifrar nada.

Lo mismo aplica a `key_cifrada` (1 326 bytes → un `.key` de 1 298).

**Por qué no recomiendo cambiarlo:** quien puede leer esa columna ya tiene la base de datos, y para
aprovechar la longitud necesitaría además la KEK; con la KEK ya tendría la contraseña completa y la
longitud sería irrelevante. Añadir relleno complicaría la bóveda sin cerrar ningún ataque real.
Se documenta porque una auditoría debe registrar lo que observó, no solo lo que va a arreglar.

## 7. Lo que NO se probó

| No cubierto | Por qué | Cómo se cubriría |
|---|---|---|
| Rotación de la KEK | No hay procedimiento de rotación implementado | Diseñarlo antes de producción (Sprint 5) |
| Material descifrado en **volcados de memoria** | Requiere instrumentar el proceso | Análisis de memoria del worker |
| ¿Queda la clave descifrada en logs? | No se auditaron los logs a fondo en este nivel | `grep` de patrones PEM sobre logs de producción |
| Un **CSD** (sello digital) en lugar de una FIEL | El SAT exige FIEL para descarga masiva; no se probó que el sistema distinga | Certificado CSD real de prueba |
| Respaldo y restauración de la bóveda | Sprint 5, no empezado | Ensayo de restauración completo |
| Concurrencia en el alta (dos altas simultáneas) | `upsert` sobre `unique(empresa_id)`; no se probó la carrera | Prueba concurrente como la del nivel 3 |

La pregunta del **CSD** es la más interesante de las pendientes: si alguien sube un sello digital en
lugar de la e.firma, hoy no sé si el sistema lo detecta en el alta o si el error aparece más tarde,
al primer job. Vale una prueba cuando haya un CSD de prueba a mano.

## 8. Cómo reproducir

```bash
.venv/bin/python -m pytest tests/auditoria/test_nivel2_efirma.py -q
```

Las comprobaciones de §4 son consultas de solo lectura sobre `efirmas` y un `ls -l` del directorio de
secretos; están transcritas en sus tablas.
