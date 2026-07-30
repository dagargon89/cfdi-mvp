# Especificación de diseño — Guía de uso por roles

Sistema visual para maquetar `guia-roles-hub-cfdi.md`. Tratamiento: **manual de referencia** — pulido y sobrio, no editorial. La estructura que manda es el **rol**, así que se convierte en el sistema visual: tres hues semánticos distinguen quién puede usar cada función.

**Principio rector:** gasta la audacia en un solo lugar (el sistema de chips de rol + la matriz de permisos). Todo lo demás, callado.

---

## 1. Paleta de color

Neutros con leve sesgo hacia el azul-tinta (elegidos, no un gris plano). Ground papel frío, no crema. El acento de marca es un navy-slate; los tres colores de rol son distintos en temperatura para leerse de un vistazo (azul / verde / ciruela = sistema de semáforo de privilegio).

### Tema claro

| Token | Hex | Uso |
| --- | --- | --- |
| `--paper` | `#f3f5f7` | Fondo de página (off-white frío) |
| `--surface` | `#ffffff` | Tarjetas, tablas |
| `--surface-2` | `#eef1f5` | Fondos sutiles, cabecera de tabla, badges de paso |
| `--ink` | `#17202e` | Texto principal (near-black con sesgo azul) |
| `--ink-soft` | `#4c5a6d` | Texto secundario / cuerpo atenuado |
| `--ink-faint` | `#7a8698` | Texto terciario, numeración, metadatos |
| `--border` | `#dce2ea` | Bordes por defecto |
| `--border-strong` | `#c6cfdb` | Bordes de énfasis (divisor de cabecera de tabla) |
| `--brand` | `#26364d` | Acento de marca (navy-slate), estructura |
| `--brand-link` | `#1f4f6e` | Enlaces |

### Tema oscuro

| Token | Hex | Uso |
| --- | --- | --- |
| `--paper` | `#0f141b` | Fondo de página |
| `--surface` | `#161d27` | Tarjetas, tablas |
| `--surface-2` | `#1c2531` | Fondos sutiles |
| `--ink` | `#e7edf4` | Texto principal |
| `--ink-soft` | `#a3b0c0` | Texto secundario |
| `--ink-faint` | `#74829a` | Texto terciario |
| `--border` | `#29333f` | Bordes por defecto |
| `--border-strong` | `#384555` | Bordes de énfasis |
| `--brand` | `#c7d3e4` | Acento de marca |
| `--brand-link` | `#7fb0d8` | Enlaces |

### Colores de rol (semánticos)

Son un sistema aparte del acento de marca. Cada rol tiene una sola variable de hue; los fondos suaves se derivan con transparencia (`color-mix`) para que funcionen en ambos temas.

| Rol | Claro | Oscuro | Significado |
| --- | --- | --- | --- |
| `--r-consulta` | `#2f6fb0` (azul) | `#62a0dc` | Lectura / descarga |
| `--r-operador` | `#167f5c` (verde-teal) | `#45c396` | Operación frente al SAT |
| `--r-admin` | `#8a4baf` (ciruela) | `#c093df` | Gobierno del sistema |

**Derivados** (mismo hue, con transparencia):
- Fondo del chip: `color-mix(in srgb, <hue> 12-13%, transparent)`
- Borde del chip: `color-mix(in srgb, <hue> 26-28%, transparent)`
- Texto del chip: el hue puro.

### Color por estado (recuadros / callouts)

- **Nota estándar (◆):** fondo `color-mix(in srgb, var(--r-admin) 8%, var(--surface))`, borde `color-mix(in srgb, var(--r-admin) 26%, transparent)`.
- **Nota legal (§):** fondo `color-mix(in srgb, var(--r-operador) 9%, var(--surface))`, borde `color-mix(in srgb, var(--r-operador) 28%, transparent)`.

### Sombra

```
--shadow (claro): 0 1px 2px rgba(23,32,46,.04), 0 6px 24px rgba(23,32,46,.05);
--shadow (oscuro): 0 1px 2px rgba(0,0,0,.3), 0 8px 28px rgba(0,0,0,.35);
```

---

## 2. Tipografía

Tres roles tipográficos. La serif tipo Palatino da aire de documento oficial; la sans del sistema para lectura; la monoespaciada para identificadores fiscales (RFC, UUID, tokens, `.cer`/`.key`, `69-B`) — que es el vernáculo del tema.

| Rol | Familia (stack) |
| --- | --- |
| **Display / títulos** (`--serif`) | `"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif` |
| **Cuerpo** (`--sans`) | `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` |
| **Utilitaria / datos** (`--mono`) | `ui-monospace, "SF Mono", "Cascadia Code", "JetBrains Mono", Menlo, Consolas, monospace` |

> Nota: se usan stacks del sistema a propósito (sin webfonts) para evitar fallbacks silenciosos. Si en tu herramienta cargas fuentes reales, mantén la intención: serif con carácter para títulos, sans neutra para cuerpo, mono para datos.

### Escala de tipo

| Elemento | Tamaño | Peso | Familia | Notas |
| --- | --- | --- | --- | --- |
| H1 masthead | `clamp(2.1rem, 4.4vw, 3.1rem)` | 600 | serif | `line-height: 1.08`, `letter-spacing: -.01em`, `text-wrap: balance` |
| H2 sección | `1.72rem` | 600 | serif | `letter-spacing: -.01em`, `text-wrap: balance` |
| H3 función | `1.06rem` | 650 | sans | `letter-spacing: -.005em` |
| Cuerpo | `1rem` (16px) | 400 | sans | `line-height: 1.65`, ancho máx. ~68ch |
| Lede / intro | `1.06–1.12rem` | 400 | sans | color `--ink-soft`, `text-wrap: pretty` |
| Eyebrow / scope | `11–12px` | 600 | mono | `text-transform: uppercase`, `letter-spacing: .16em` |
| Chip | `12–13px` | 650 | sans | — |
| Numeración de paso | `11px` | 600 | mono | — |

**Medida de línea:** el texto de lectura se mantiene cerca de **65–68ch** de ancho.

---

## 3. Layout

Manual con **índice lateral fijo** (sticky) + **columna de lectura** de ancho controlado.

- Rejilla principal: `grid-template-columns: 244px minmax(0, 1fr)` con `gap: 56px`, `max-width: 1180px`, centrada.
- **Índice (TOC):** `position: sticky; top: 24px`. Lista numerada con `counter(decimal-leading-zero)` en mono. Se **oculta bajo 880px** (el contenido pasa a una sola columna).
- **Masthead:** ocupa ambas columnas; abajo un divisor de 1px y la leyenda de los tres chips de rol.
- **Secciones:** separadas con `margin-top: 52px`; cada una con número de sección en mono (color `--r-operador`) + título serif.
- **Espaciado:** deja que el layout (flex/grid + `gap`) haga el espaciado entre grupos; evita márgenes por elemento que se colapsen o dupliquen.
- **Scroll:** `scroll-behavior: smooth` en `html` y `scroll-margin-top` en las secciones para el salto del índice.

### Responsivo

- **≤ 880px:** una sola columna, TOC oculto.
- **Tablas anchas:** contenedor propio con `overflow-x: auto`; la página nunca hace scroll horizontal.

### Impresión (`@media print`)

Fondo blanco, TOC oculto, una columna, sin sombras, y `break-inside: avoid` en tarjetas / tabla / secciones para exportar a PDF limpio.

---

## 4. Componentes

### Chip de rol
Píldora con punto de color a la izquierda. Indica el **rol mínimo** que habilita la función.

- Forma: `border-radius: 999px`, `padding: 6px 11px 6px 9px`, borde de 1px.
- Punto (`::before`): círculo de 8px con el hue del rol.
- Variantes: `.chip--consulta`, `.chip--operador`, `.chip--admin` (fondo/borde/texto derivados del hue como en §1).

### Tarjeta de rol (sección "Los tres roles")
Tarjeta con **borde superior de 3px** del color del rol.

- `background: --surface`, `border: 1px --border`, `border-top: 3px solid <hue>`, `border-radius: 12px`, `box-shadow: --shadow`.
- Título serif + línea de alcance (`scope`) en mono/uppercase/`--ink-faint`.
- Se disponen en `grid` con `repeat(auto-fit, minmax(220px, 1fr))`.

### Tarjeta de función
Contenedor de cada función.

- `background: --surface`, `border: 1px --border`, `border-radius: 12px`, `padding: 20px 22px`, `box-shadow: --shadow`.
- **Cabecera** (`.fn-top`): flex con el H3 a la izquierda y los chips de rol a la derecha (`justify-content: space-between`, `flex-wrap: wrap`).
- Descripción en `--ink-soft`, `.96rem`.

### Lista de pasos
Pasos numerados con badge circular.

- Sin viñeta nativa; `counter-reset: step` y numeración con `counter(step)`.
- Badge (`::before`): círculo de 21px, `background: --surface-2`, borde `--border-strong`, número en mono 11px, color `--ink-soft`.
- Ítems en `flex` con `gap: 12px`.

### Matriz de permisos
Tabla de resumen — pieza central de diseño de información.

- Contenedor con `overflow-x: auto`, `border-radius: 12px`, borde y sombra; `min-width: 560px` en la tabla.
- **Cabecera:** fondo `--surface-2`, borde inferior `--border-strong`. La primera columna alineada a la izquierda; las demás centradas. Cada encabezado de rol coloreado con su hue (`.h-consulta`, `.h-operador`, `.h-admin`).
- **Celdas:** `✓` en el color del rol de la columna (consulta/operador/admin); `—` en `--ink-faint`. Usa `font-variant-numeric: tabular-nums`.
- **Hover de fila:** fondo `color-mix(in srgb, var(--surface-2) 55%, transparent)`.

### Callout / nota
Recuadro con marcador a la izquierda.

- Flex con `gap: 13px`; icono/marcador (`◆` estándar, `§` legal) como glifo, no emoji.
- Colores según §1 (estándar = ciruela/admin; legal = verde/operador).

### Etiqueta de teclado / inline
- `.kbd`: fondo `--surface-2`, borde `--border-strong`, `border-radius: 5px`, `padding: 1px 6px`, familia mono. Para nombres de botones (**Crear cuenta**, **Nueva descarga**).
- `code` / `.mono`: familia mono a `.88em` para RFC, UUID, extensiones y códigos (`69-B`).

---

## 5. Detalles de acabado (quality floor)

- **Ambos temas** con el mismo cuidado: define los tokens en `:root`, redefínelos bajo `@media (prefers-color-scheme: dark)` y también bajo `:root[data-theme="dark"]` / `:root[data-theme="light"]` para que el toggle del visor gane en ambas direcciones. Estiliza siempre vía tokens, nunca dentro del media query.
- **Foco visible:** `outline: 2px solid var(--r-operador); outline-offset: 2px` en enlaces y elementos del índice.
- **`prefers-reduced-motion`:** desactiva `scroll-behavior` y transiciones.
- **Marcadores como glifos** (◆, §, ✓, —), no emoji, para conservar el tono institucional.
- **`text-wrap: balance`** en títulos y **`pretty`** en párrafos de intro.

---

## 6. Mapa rápido rol → color

| Rol | Hue (claro) | Rol en el sistema |
| --- | --- | --- |
| Consulta | `#2f6fb0` azul | Lee y descarga lo que ya existe |
| Operador | `#167f5c` verde-teal | Opera la empresa frente al SAT |
| Administrador | `#8a4baf` ciruela | Gobierna todo el sistema |

*Consulta lee · Operador opera · Administrador gobierna.*
