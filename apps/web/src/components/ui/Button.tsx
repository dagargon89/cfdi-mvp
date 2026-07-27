// Hub_CFDI_docs/01-vision/08_identidad_visual_design_system.md §5.1 (literal).
import { Loader2 } from 'lucide-react';
import type { ButtonHTMLAttributes } from 'react';

interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  loading?: boolean;
}

export function Button({ variant = 'primary', loading, className = '', children, ...rest }: BtnProps) {
  const base =
    'inline-flex items-center gap-2 rounded-md px-4 h-9 text-sm font-semibold ' +
    'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ' +
    'focus-visible:outline-primary disabled:opacity-50 disabled:pointer-events-none';
  const variants = {
    primary: 'bg-primary text-white hover:bg-primary-hover',
    secondary: 'border border-border bg-surface text-text-strong hover:bg-surface-alt',
    danger: 'bg-danger text-white hover:opacity-90',
    ghost: 'text-primary hover:bg-primary-soft',
  };
  return (
    <button className={`${base} ${variants[variant]} ${className}`} aria-busy={loading} {...rest}>
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}
