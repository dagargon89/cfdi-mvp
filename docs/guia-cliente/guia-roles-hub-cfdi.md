# Hub CFDI: qué hace cada función y quién puede usarla

> **Guía de uso · Plataforma de cumplimiento CFDI**

Hub CFDI centraliza la descarga, resguardo y vigilancia de tus comprobantes fiscales frente al SAT. Lo que puedes hacer depende de tu **rol**. Esta guía recorre cada función y marca, en cada una, el rol mínimo que la habilita.

**Roles:** `Consulta` · `Operador` · `Administrador`

---

## Contenido

1. [Los tres roles](#1-los-tres-roles)
2. [Matriz de permisos](#2-matriz-de-permisos)
3. [Acceso y cuenta](#3-acceso-y-cuenta)
4. [Empresas](#4-empresas)
5. [Bóveda e.firma](#5-bóveda-efirma)
6. [Descargas del SAT](#6-descargas-del-sat)
7. [Comprobantes](#7-comprobantes)
8. [Alertas y notificaciones](#8-alertas-y-notificaciones)
9. [Administración](#9-administración)

---

## 1. Los tres roles

Un mismo usuario puede tener un **rol global** en el sistema y, además, un rol distinto **por cada empresa** a la que se le da acceso. La regla de fondo es sencilla:

**Consulta** lee y descarga lo que ya existe. **Operador** además opera la empresa frente al SAT. **Administrador** gestiona todo el sistema y todas las empresas.

### Consulta
`Por empresa · solo lectura`

Consulta comprobantes y descargas, y baja los documentos que ya se obtuvieron (XML, PDF, detalle y paquetes .zip). No dispara acciones sobre el SAT ni cambia configuración.

### Operador
`Por empresa · opera`

Todo lo de Consulta y, además, da de alta la e.firma, solicita descargas al SAT, valida comprobantes y administra las notificaciones de esa empresa.

### Administrador
`Global · todo el sistema`

Opera cualquier empresa como operador y, además, da de alta empresas, gestiona usuarios y permisos, configura el sistema y consulta la bitácora.

> **◆ Los permisos son acumulativos.** Quien puede operar también puede consultar. Cuando una función indica el rol **Operador**, significa "operador o superior"; el administrador siempre puede.

---

## 2. Matriz de permisos

Resumen de un vistazo. Los roles por empresa (Consulta / Operador) aplican a la empresa a la que tienes acceso; el Administrador aplica a todo el sistema.

| Función | Consulta | Operador | Administrador |
| --- | :---: | :---: | :---: |
| Ver mis empresas y su tablero | ✓ | ✓ | ✓ |
| Ver comprobantes y descargas | ✓ | ✓ | ✓ |
| Descargar XML / PDF / Detalle | ✓ | ✓ | ✓ |
| Descarga masiva (.zip) y exportar metadata | ✓ | ✓ | ✓ |
| Ver estado de la e.firma | ✓ | ✓ | ✓ |
| Dar de alta / reemplazar e.firma | — | ✓ | ✓ |
| Solicitar descargas al SAT / reintentar | — | ✓ | ✓ |
| Validar comprobantes ante el SAT | — | ✓ | ✓ |
| Alertas y notificaciones | — | ✓ | ✓ |
| Alta / baja de empresas | — | — | ✓ |
| Usuarios, roles y accesos | — | — | ✓ |
| Configuración, automatizaciones y bitácora | — | — | ✓ |

---

## 3. Acceso y cuenta

Todo usuario entra con su correo. Las cuentas nuevas requieren aprobación antes de poder trabajar.

### Iniciar sesión
**Rol mínimo:** Consulta

Accede con tu correo y contraseña. Verás únicamente las empresas que un administrador te haya asignado.

### Registrarse (cuenta nueva)
**Rol mínimo:** cualquiera

Un usuario nuevo puede registrarse por su cuenta, pero queda **pendiente de aprobación**: no tiene acceso hasta que un administrador lo aprueba y le asigna rol y empresas.

1. Desde la pantalla de acceso, elige **Crear cuenta** e ingresa tus datos.
2. Tu cuenta queda en espera; el administrador recibe la solicitud.
3. Al ser aprobada y asignada, ya puedes entrar y ver tus empresas.

---

## 4. Empresas

La pantalla **Empresas** es tu punto de partida: reúne las empresas a las que tienes acceso. Cada tarjeta muestra el estado de la e.firma y las alertas activas.

### Ver, buscar y abrir empresas
**Rol mínimo:** Consulta

Busca por nombre o RFC y filtra por estado (activas / inactivas) o por vigencia de la e.firma. Pulsa **Abrir** para entrar al tablero de una empresa.

### Alta, activación y baja de empresas
**Rol mínimo:** Administrador

Solo el administrador crea empresas nuevas, las activa o desactiva, o las elimina. Desactivar conserva el historial; eliminar solo es posible si la empresa nunca tuvo e.firma, descargas ni comprobantes, y pide reescribir el RFC para confirmar.

---

## 5. Bóveda e.firma

La e.firma (certificado `.cer` + llave `.key` + contraseña) es lo que permite consultar al SAT en nombre de la empresa. Se resguarda cifrada.

### Ver estado y vigencia
**Rol mínimo:** Consulta

Cualquiera con acceso a la empresa ve si hay e.firma cargada y cuántos días faltan para que venza.

### Dar de alta o reemplazar la e.firma
**Rol mínimo:** Operador

Necesario antes de descargar del SAT. Se sube el certificado, la llave y su contraseña.

1. Abre la empresa y entra a **Bóveda e.firma**.
2. Carga el archivo `.cer`, el `.key` y escribe la contraseña de la llave.
3. El sistema valida la vigencia y guarda las credenciales cifradas.

---

## 6. Descargas del SAT

Aquí se solicitan y se siguen las descargas de comprobantes directamente desde el SAT. Cada solicitud queda registrada como un trabajo con su estado.

### Solicitar una descarga al SAT
**Rol mínimo:** Operador

Define el rango de fechas y el tipo (emitidos / recibidos) y el sistema consulta al SAT usando la e.firma de la empresa.

1. En **Descargas**, pulsa **Nueva descarga**.
2. Elige el periodo y la dirección de los comprobantes.
3. El trabajo se procesa en segundo plano; su estado se actualiza solo.

> **◆ Aviso.** Solicitar una descarga hace una **consulta real al SAT** y consume cuota de la e.firma. Por eso está reservada a operador o superior.

### Seguir trabajos, reintentar y exportar metadata
**Rol mínimo:** Consulta — *reintentar requiere Operador*

Consulta el historial de descargas, su detalle y descarga la metadata en CSV. **Reintentar** un trabajo fallido —porque vuelve a llamar al SAT— requiere operador.

---

## 7. Comprobantes

El acervo de CFDI ya descargados. Se listan con paginación, se filtran por dirección (emitido / recibido) y se descargan en varios formatos.

### Consultar y previsualizar
**Rol mínimo:** Consulta

Cada comprobante ofrece botones de descarga con una pestaña de **vista previa** (ícono de ojo) para revisar el documento antes de bajarlo.

### Descargar XML, PDF y Detalle
**Rol mínimo:** Consulta

Baja el XML original, la representación impresa (PDF) o el detalle en formato horizontal, para uno o varios comprobantes.

### Descarga masiva en .zip
**Rol mínimo:** Consulta

Genera un paquete ordenado por **Emitidos / Recibidos → año-mes → tipo de comprobante**, listo para archivar o entregar a tu contador.

### Validar ante el SAT
**Rol mínimo:** Operador

Vuelve a verificar el estatus de los comprobantes (vigente / cancelado) contra el SAT. Como implica consultar al SAT, requiere operador.

---

## 8. Alertas y notificaciones

La vigilancia fiscal de la empresa: avisos de riesgo y los correos que se envían cuando algo ocurre. Estas secciones son de trabajo operativo y **no aparecen para el rol Consulta**.

### Alertas
**Rol mínimo:** Operador

Reúne los avisos relevantes: proveedores en lista `69-B` (EFOS), cancelaciones tardías, e.firma por vencer, errores de descarga y el resumen de sincronización. El tablero muestra un contador de alertas pendientes.

### Notificaciones por correo
**Rol mínimo:** Operador

Define a qué correos avisar y a qué eventos se suscribe cada destino. Gestionar estos destinos es tarea de operador o administrador.

---

## 9. Administración

Reservada al administrador. Reúne el gobierno del sistema: personas, configuración y auditoría.

### Usuarios, roles y accesos
**Rol mínimo:** Administrador

Aprueba las cuentas nuevas, asigna el rol global y el rol por empresa, y activa o desactiva usuarios.

> **◆ Protección.** El sistema **no permite degradar ni desactivar al último administrador activo**, para que la cuenta nunca quede sin gobierno.

### Configuración y automatizaciones
**Rol mínimo:** Administrador

Activa o desactiva las tareas automáticas —sincronización diaria, actualización de la lista 69-B, re-verificación de vigentes y limpieza de almacenamiento— y configura el correo de salida (SMTP). Al desactivar una automatización, el sistema explica la consecuencia y pide confirmar.

### Bitácora
**Rol mínimo:** Administrador

Registro de auditoría: quién hizo qué y cuándo, con paginación para revisar el historial completo.

> **§ Resguardo legal.** Los XML de tus comprobantes se conservan durante ~5 años y **nunca se borran automáticamente**. La limpieza periódica de almacenamiento solo elimina archivos temporales de exportación y paquetes .zip ya descargados, para liberar espacio sin tocar tu acervo fiscal.

---

*Hub CFDI · Guía de uso por roles — Consulta lee · Operador opera · Administrador gobierna*
