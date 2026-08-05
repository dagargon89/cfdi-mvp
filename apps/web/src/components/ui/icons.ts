// Mapeo semántico de iconos — Hub_CFDI_docs/01-vision/08_identidad_visual_design_system.md §8.
// Sustituye los `path` SVG crudos del prototipo (demo.html:904-931, objeto ICON) por lucide-react.
import {
  AlertCircle,
  AlertTriangle,
  Bell,
  Building2,
  CheckCircle2,
  CirclePlus,
  Clock,
  Download,
  FileSpreadsheet,
  KeyRound,
  LayoutDashboard,
  List,
  Loader2,
  LogOut,
  PackageCheck,
  PanelLeftClose,
  RefreshCw,
  ScrollText,
  Send,
  Settings,
  ShieldCheck,
  ShieldX,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react';

export const NAV_ICON = {
  edificio: Building2,
  tablero: LayoutDashboard,
  llave: KeyRound,
  descarga: Download,
  lista: List,
  triangulo: AlertTriangle,
  campana: Bell,
  usuarios: Users,
  engrane: Settings,
  pergamino: ScrollText,
  informes: FileSpreadsheet,
} satisfies Record<string, LucideIcon>;

export const CHIP_ICON = {
  DESCARGADO: CheckCircle2,
  TERMINADA: PackageCheck,
  EN_PROCESO: RefreshCw,
  SOLICITADO: Send,
  ERROR: AlertCircle,
  NUEVO: CirclePlus,
  vigente: ShieldCheck,
  cancelado: ShieldX,
  no_verificado: Clock,
} satisfies Record<string, LucideIcon>;

export const UI_ICON = {
  cerrar: X,
  salir: LogOut,
  colapsar: PanelLeftClose,
  spinner: Loader2,
  export: FileSpreadsheet,
  alerta: AlertCircle,
  escudoOk: ShieldCheck,
  escudoX: ShieldX,
  reloj: Clock,
  refrescar: RefreshCw,
} satisfies Record<string, LucideIcon>;
