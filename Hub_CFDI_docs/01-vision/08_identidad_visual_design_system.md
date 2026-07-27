# 08 — Identidad Visual y Design System

| Campo | Valor |
|---|---|
| Documento | 08 — Identidad Visual y Design System |
| Versión | 2.0 |
| Fecha | 2026-07-27 |
| Origen | Paleta conceptual heredada de v1.0 (escritorio), reimplementada para web |
| Dirección | Herramienta profesional densa en información, para contadores; el color comunica estado |
| Stack de UI | React 19 + Tailwind CSS 4 + lucide-react |
| Depende de | [`01_SRS`](01_SRS_especificacion_requisitos.md) · [`ADR-003`](../02-arquitectura/ADR/ADR-003_pivote_web.md) |

---

## 1. Identidad de marca

| Atributo | Valor |
|---|---|
| Nombre | Hub CFDI |
| Subtítulo | Descarga masiva y cumplimiento CFDI |
| Propósito visual | Que un contador vea de un vistazo el estado de sus empresas: qué se descargó, qué está vigente, qué exige atención |
| Personalidad | Sobria, precisa, confiable — maneja identidades legales ajenas |
| Antipatrones | Nada decorativo ni degradados; el color **nunca** es el único indicador de estado (siempre chip con ícono + texto); nada de densidad que sacrifique contraste AA |

| Color primordial | Hex | Rol |
|---|---|---|
| Azul primario | `#1F5FA6` | Acciones, foco, navegación activa |
| Gris pizarra | `#1E2733` | Texto fuerte |
| Superficie base | `#F4F6F9` | Fondo de la app |

## 2. Paleta de color

### 2.1 Tokens base
| Token | Hex | Uso |
|---|---|---|
| `--bg` | `#F4F6F9` | Fondo de la app |
| `--surface` | `#FFFFFF` | Tarjetas, tablas, modales |
| `--surface-alt` | `#EDF1F6` | Encabezados de tabla, filas alternas |
| `--border` | `#D3DAE3` | Bordes y divisores |
| `--text-strong` | `#1E2733` | Texto principal |
| `--text-muted` | `#556070` | Texto secundario (AA sobre surface) |

### 2.2 Marca / acento
| Token | Hex | Uso |
|---|---|---|
| `--primary` | `#1F5FA6` | Botón primario, links, foco, item activo del sidebar |
| `--primary-hover` | `#184C85` | Hover |
| `--primary-soft` | `#E4EDF7` | Selección, fondos activos |

### 2.3 Semánticos (mapeados al dominio)
| Dominio | Token | Hex | Fondo suave |
|---|---|---|---|
| DESCARGADO · vigente · éxito | `--success` | `#1E7A46` | `#E4F2EA` |
| SOLICITADO/EN_PROCESO · info | `--info` | `#0B6E99` | `#E1F0F6` |
| TERMINADA · por vencer · atención | `--warning` | `#9A5B00` | `#F7EEDD` |
| ERROR · cancelado · EFOS | `--danger` | `#B4283A` | `#F7E3E6` |
| NUEVO · no_verificado | `--neutral` | `#556070` | `#EDF1F6` |

### 2.4 Accesibilidad (WCAG 2.1 AA)
| Fondo | Texto | Ratio | Resultado |
|---|---|---|---|
| `surface` | `text-strong` | 13.6:1 | AAA |
| `surface` | `text-muted` | 5.0:1 | AA |
| `primary` | blanco | 5.3:1 | AA |
| `success` | blanco | 4.8:1 | AA |
| `danger` | blanco | 5.6:1 | AA |
| soft de cada semántico | su color pleno | ≥ 4.5:1 | AA |
| **Evitar** | `text-muted` sobre `surface-alt` < 16px | 3.8:1 | ❌ |

## 3. Tipografía

| Nivel | Fuente | Tamaño/peso | Uso |
|---|---|---|---|
| Display | Inter | 22/700 | Título de pantalla |
| H2 | Inter | 18/600 | Secciones y modales |
| Body | Inter | 14/400 | General, celdas |
| Body-strong | Inter | 14/600 | Encabezados de tabla, KPIs |
| **Mono** | JetBrains Mono | 13/400 | **RFC, UUID, folios, series — siempre** |
| Caption | Inter | 12/400 | Timestamps, ayudas |

Inter y JetBrains Mono vía Google Fonts con fallback de sistema. Jerarquía: una sola Display por pantalla; los números de totales alinean a la derecha en tablas.

## 4. Espaciado y layout

- **Escala:** 4/8/12/16/24/32 px. **Radios:** 8px tarjetas, 6px botones/chips, 4px inputs. **Sombras:** solo elevación de modales y menús (`shadow-md`); las tarjetas usan borde, no sombra.
- **Layout:** sidebar colapsable (264px ↔ 72px, patrón de casa) con navegación por módulo + selector de empresa fijo arriba; contenido con tabla densa y panel/drawer de detalle.
- **Breakpoints:** `sm` 640 (móvil: tablas → tarjetas apiladas), `md` 768, `lg` 1024 (sidebar expandido por defecto), `xl` 1280 (panel de detalle lateral persistente).
- **Densidad de tabla:** filas 40px, padding-x 12px, encabezado `surface-alt` sticky.

## 5. Componentes

### 5.1 Botón
Variantes: primario, secundario (contorno), peligro (borrar e.firma), texto. Estados: default/hover/focus-visible/disabled/loading.

```tsx
export function Button({ variant = 'primary', loading, children, ...rest }: BtnProps) {
  const base = 'inline-flex items-center gap-2 rounded-md px-4 h-9 text-sm font-semibold ' +
               'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ' +
               'focus-visible:outline-primary disabled:opacity-50 disabled:pointer-events-none';
  const variants = {
    primary:   'bg-primary text-white hover:bg-primary-hover',
    secondary: 'border border-border bg-surface text-text-strong hover:bg-surface-alt',
    danger:    'bg-danger text-white hover:opacity-90',
    ghost:     'text-primary hover:bg-primary-soft',
  };
  return (
    <button className={`${base} ${variants[variant]}`} aria-busy={loading} {...rest}>
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}
```

### 5.2 Chip de estado (job / CFDI / EFOS)
Color + ícono + **texto**, nunca solo color.

```tsx
const ESTADOS = {
  DESCARGADO:  { fg: 'text-success', bg: 'bg-success-soft', Icon: CheckCircle2 },
  EN_PROCESO:  { fg: 'text-info',    bg: 'bg-info-soft',    Icon: RefreshCw },
  SOLICITADO:  { fg: 'text-info',    bg: 'bg-info-soft',    Icon: Send },
  TERMINADA:   { fg: 'text-warning', bg: 'bg-warning-soft', Icon: PackageCheck },
  ERROR:       { fg: 'text-danger',  bg: 'bg-danger-soft',  Icon: AlertCircle },
  NUEVO:       { fg: 'text-neutral', bg: 'bg-neutral-soft', Icon: CirclePlus },
  vigente:     { fg: 'text-success', bg: 'bg-success-soft', Icon: ShieldCheck },
  cancelado:   { fg: 'text-danger',  bg: 'bg-danger-soft',  Icon: ShieldX },
} as const;

export function EstadoChip({ estado }: { estado: keyof typeof ESTADOS }) {
  const { fg, bg, Icon } = ESTADOS[estado];
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold ${fg} ${bg}`}>
      <Icon className="size-3.5" aria-hidden /> {estado}
    </span>
  );
}
```

### 5.3 Tabla de datos
Anatomía: encabezado sticky `surface-alt`, filas alternas, hover `primary-soft`, identificadores en `font-mono`, columna de estado con chip, paginador. Estados: loading (skeleton de filas), **empty** ("Sin comprobantes con estos filtros" + acción), **error** (mensaje + reintentar). Reglas: totales alineados a la derecha; máximo una acción por fila visible (resto en menú).

### 5.4 Formulario de e.firma (componente crítico)
Inputs de archivo `.cer`/`.key` + contraseña (`type=password`, sin autocompletado, `autoComplete="new-password"`); al enviar, limpia el estado local; muestra resultado con metadatos (serie, vigencia) y **nunca** re-muestra la contraseña. Errores específicos del doc 05 (§4) con texto en español claro.

### 5.5 Otros componentes mínimos
Input/Select/DateRange (filtros), Modal de confirmación (acciones destructivas exigen escribir el RFC), Drawer de detalle (job/comprobante), Toast (éxito 4s; error persistente con descarte), Banner de alerta (EFOS en cabecera de empresa afectada), Sidebar (colapsable, tooltip en colapsado, item activo `primary-soft`), Selector de empresa (buscable, muestra RFC en mono), Skeleton, Badge contador (eventos sin leer).

## 6. Tokens CSS

```css
/* apps/web/src/styles/tokens.css */
:root {
  --bg: #F4F6F9; --surface: #FFFFFF; --surface-alt: #EDF1F6; --border: #D3DAE3;
  --text-strong: #1E2733; --text-muted: #556070;
  --primary: #1F5FA6; --primary-hover: #184C85; --primary-soft: #E4EDF7;
  --success: #1E7A46; --success-soft: #E4F2EA;
  --info: #0B6E99; --info-soft: #E1F0F6;
  --warning: #9A5B00; --warning-soft: #F7EEDD;
  --danger: #B4283A; --danger-soft: #F7E3E6;
  --neutral: #556070; --neutral-soft: #EDF1F6;
  --radius-card: 8px; --radius-control: 6px;
}
```

## 7. Configuración Tailwind 4

```css
/* apps/web/src/styles/app.css */
@import "tailwindcss";
@theme {
  --color-bg: #F4F6F9; --color-surface: #FFFFFF; --color-surface-alt: #EDF1F6;
  --color-border: #D3DAE3; --color-text-strong: #1E2733; --color-text-muted: #556070;
  --color-primary: #1F5FA6; --color-primary-hover: #184C85; --color-primary-soft: #E4EDF7;
  --color-success: #1E7A46; --color-success-soft: #E4F2EA;
  --color-info: #0B6E99; --color-info-soft: #E1F0F6;
  --color-warning: #9A5B00; --color-warning-soft: #F7EEDD;
  --color-danger: #B4283A; --color-danger-soft: #F7E3E6;
  --color-neutral: #556070; --color-neutral-soft: #EDF1F6;
  --font-sans: "Inter", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}
```

## 8. Iconografía

`lucide-react`, 16–20px, `stroke-width` por defecto. Semántica fija: `ShieldCheck` vigente/bóveda ok · `ShieldX` cancelado · `KeyRound` e.firma · `Download` descargas · `RefreshCw` en proceso/sync · `AlertTriangle` EFOS · `Clock` por vencer · `FileSpreadsheet` export · `Building2` empresas · `ScrollText` bitácora.

## 9. Animaciones

150–200ms `ease-out`: hover de fila, apertura de drawer, colapso de sidebar (estado persistido). Spinner/indeterminado solo mientras hay trabajo real (polling activo). `prefers-reduced-motion` respetado. Sin animaciones decorativas.

## 10. Verificación de accesibilidad

Todas las combinaciones de §2.4 en uso cumplen AA. Adicional: foco visible en todo control (outline `primary` 2px), navegación completa por teclado (sidebar → selector de empresa → filtros → tabla → paginador → drawer), tablas con `<th scope>`, chips con texto (no solo color/ícono), formularios con labels y errores asociados por `aria-describedby`, drawer y modal con trampa de foco y `Esc`.
