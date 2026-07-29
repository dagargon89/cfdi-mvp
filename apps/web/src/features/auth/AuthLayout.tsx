// Layout de las pantallas de acceso (login / crear cuenta): pantalla dividida — panel de marca a la
// izquierda (azul profundo con "pauta" de libro contable, la firma visual) y el formulario a la derecha.
// Mantiene el sistema de diseño (Inter, JetBrains Mono, azul --primary); el azul del panel son tonos
// más oscuros del mismo matiz, sin colores nuevos. En móvil se apila: cabecera de marca compacta + form.
import { Check } from 'lucide-react';
import type { ReactNode } from 'react';

const CAPACIDADES = [
  'Descarga masiva y reanudable ante el SAT',
  'Cruce automático con la lista 69-B (EFOS)',
  'Alertas de cancelación y vencimiento de e.firma',
];

// Azul profundo (mismo matiz que --primary #1F5FA6) + pauta de libro contable en hairlines muy sutiles.
const PANEL_BG = {
  backgroundColor: '#0f2a4d',
  backgroundImage:
    'repeating-linear-gradient(to bottom, rgba(255,255,255,0.05) 0px, rgba(255,255,255,0.05) 1px, transparent 1px, transparent 40px), ' +
    'linear-gradient(160deg, #17406f 0%, #0e2747 100%)',
};

function Monograma({ oscuro = false }: { oscuro?: boolean }) {
  return (
    <div
      className={`size-10 rounded-lg grid place-items-center font-bold text-[15px] tracking-tight shrink-0 ${
        oscuro ? 'bg-primary text-white' : 'bg-white text-[#123156]'
      }`}
      aria-hidden
    >
      HC
    </div>
  );
}

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen grid md:grid-cols-2">
      {/* Panel de marca — solo escritorio */}
      <aside className="relative hidden md:flex flex-col justify-center items-center overflow-hidden px-12 lg:px-16 text-white" style={PANEL_BG}>
        <div className="relative z-10 flex flex-col gap-10 max-w-[440px] animate-dc-fade">
          <div className="flex items-center gap-3">
            <Monograma />
            <span className="text-[19px] font-bold tracking-tight">Hub CFDI</span>
          </div>

          <div className="flex flex-col gap-4">
            <h1 className="m-0 text-[34px] leading-[1.15] font-bold tracking-[-0.02em] text-balance">
              El centro de tu cumplimiento CFDI
            </h1>
            <p className="m-0 text-[15px] leading-relaxed text-white/70 text-pretty">
              Descarga masiva ante el SAT, resguardo y vigilancia fiscal en un solo lugar.
            </p>
          </div>

          <div className="h-px w-full bg-white/15" />

          <ul className="m-0 p-0 list-none flex flex-col gap-3.5">
            {CAPACIDADES.map((c) => (
              <li key={c} className="flex items-start gap-3 text-[14px] text-white/85">
                <Check className="size-4 mt-0.5 shrink-0 text-white/55" aria-hidden />
                <span className="text-pretty">{c}</span>
              </li>
            ))}
          </ul>
        </div>

        <span className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 font-mono text-[11px] tracking-[0.18em] uppercase text-white/40">
          SAT · CFDI 4.0
        </span>
      </aside>

      {/* Panel del formulario */}
      <main className="flex flex-col justify-center bg-bg px-6 py-12 sm:px-10">
        <div className="w-full max-w-[380px] mx-auto flex flex-col gap-8 animate-dc-up">
          {/* Cabecera de marca compacta — solo móvil (el panel de marca se oculta) */}
          <div className="md:hidden flex items-center gap-3">
            <Monograma oscuro />
            <div>
              <div className="text-[18px] font-bold leading-tight tracking-tight">Hub CFDI</div>
              <div className="text-xs text-text-muted">Cumplimiento CFDI ante el SAT</div>
            </div>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
