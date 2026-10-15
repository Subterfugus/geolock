import { clsx } from 'clsx';
import { X } from 'lucide-react';
import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { confidenceName, flag as flagOf, pct } from '../lib/format';
import type { ConfidenceLabel } from '../lib/types';

export { clsx as cx };

/** The logo lives in public/ so it is referenced by URL, relative to the page (works from the Tauri origin). */
export const LOGO_SRC = './logo.svg';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-accent-fg hover:bg-accent-strong shadow-[0_1px_0_rgb(255_255_255/0.18)_inset] disabled:bg-accent/40',
  secondary: 'bg-surface-3 text-fg hover:bg-surface-3/70 border border-border',
  outline: 'border border-border-strong text-fg hover:bg-surface-3',
  ghost: 'text-fg-2 hover:text-fg hover:bg-surface-3',
  danger: 'bg-danger text-white hover:brightness-110 disabled:opacity-50',
};

export function Button({
  variant = 'secondary', size = 'md', className, children, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: 'sm' | 'md' | 'lg' }) {
  return (
    <button
      type="button"
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors duration-150',
        'disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.985]',
        size === 'sm' && 'h-7 px-2.5 text-[12px]',
        size === 'md' && 'h-8 px-3 text-[13px]',
        size === 'lg' && 'h-11 px-5 text-[14.5px] rounded-xl',
        VARIANT[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function IconButton({
  label, className, children, active, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={clsx(
        'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-fg-2 transition-colors duration-150',
        'hover:bg-surface-3 hover:text-fg disabled:opacity-40 disabled:hover:bg-transparent',
        active && 'bg-surface-3 text-fg',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] border border-border-strong bg-surface-2 px-1 font-sans text-[10.5px] font-medium text-fg-2 shadow-[0_1px_0_var(--border-strong)]">
      {children}
    </kbd>
  );
}

export function Switch({
  checked, onChange, label, disabled,
}: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        'relative inline-flex h-[20px] w-[36px] shrink-0 items-center rounded-full transition-colors duration-200',
        checked ? 'bg-accent' : 'bg-border-strong',
        disabled && 'opacity-50',
      )}
    >
      <span
        className={clsx(
          'inline-block h-[16px] w-[16px] rounded-full bg-white shadow transition-transform duration-200 ease-out',
          checked ? 'translate-x-[18px]' : 'translate-x-[2px]',
        )}
      />
    </button>
  );
}

export function Segmented<T extends string>({
  value, options, onChange, label, size = 'md', fullWidth,
}: {
  value: T;
  options: { value: T; label: ReactNode; disabled?: boolean; title?: string }[];
  onChange: (v: T) => void;
  label: string;
  size?: 'sm' | 'md';
  fullWidth?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={clsx('inline-flex rounded-[10px] bg-surface-3 p-[3px]', fullWidth && 'flex w-full')}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={o.disabled}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={clsx(
              'flex-1 rounded-[7px] px-2.5 font-medium transition-all duration-150 whitespace-nowrap',
              size === 'md' ? 'h-7 text-[12.5px]' : 'h-6 text-[12px]',
              on ? 'bg-surface text-fg shadow-[var(--shadow-sm)]' : 'text-fg-2 hover:text-fg',
              o.disabled && 'cursor-not-allowed opacity-40',
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

const CONF_TEXT: Record<ConfidenceLabel, string> = {
  high: 'text-high', medium: 'text-medium', low: 'text-low',
};
const CONF_BG: Record<ConfidenceLabel, string> = {
  high: 'bg-high', medium: 'bg-medium', low: 'bg-low',
};
export const confText = (l: ConfidenceLabel) => CONF_TEXT[l];
export const confBg = (l: ConfidenceLabel) => CONF_BG[l];

export function ConfidencePill({ label, value, className }: { label: ConfidenceLabel; value: number; className?: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-[2px] text-[11.5px] font-semibold tnum',
        className,
      )}
      title={`${confidenceName(label)} confidence`}
    >
      <span className={clsx('h-1.5 w-1.5 rounded-full', CONF_BG[label])} aria-hidden="true" />
      <span className={CONF_TEXT[label]}>{pct(value)}</span>
    </span>
  );
}

/** Circular meter for the hero card. */
export function ConfidenceRing({ value, label, size = 68 }: { value: number; label: ConfidenceLabel; size?: number }) {
  const stroke = 6;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  const color = label === 'high' ? 'var(--high)' : label === 'medium' ? 'var(--medium)' : 'var(--low)';
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${pct(value)} confidence`}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--ring-track)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - v)}
          style={{ transition: 'stroke-dashoffset 600ms var(--ease-out)' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span className={clsx('text-[17px] font-semibold tnum', CONF_TEXT[label])}>{pct(value)}</span>
      </div>
    </div>
  );
}

export function Meter({ value, label, className }: { value: number; label: ConfidenceLabel; className?: string }) {
  return (
    <div className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-surface-3', className)}>
      <div
        className={clsx('h-full rounded-full transition-[width] duration-500 ease-out', CONF_BG[label])}
        style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={clsx('animate-spin-slow shrink-0', className)} aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

export function Flag({ code }: { code: string | null | undefined }) {
  const f = code ? flagOf(code) : '';
  if (!f) return null;
  return <span aria-hidden="true" className="text-[13px] leading-none">{f}</span>;
}


export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-3">{children}</h3>
      {aside}
    </div>
  );
}

/** Centered modal sheet with a dimmed backdrop, Esc to close and focus kept inside. */
export function Dialog({
  open, onClose, title, children, width = 520, footer, labelledById,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  width?: number;
  footer?: ReactNode;
  labelledById: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('[data-autofocus], button, input')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 fade-in" style={{ background: 'var(--scrim)' }} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledById}
        className="pop-in flex max-h-full w-full flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-[var(--shadow)]"
        style={{ maxWidth: width }}
      >
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <h2 id={labelledById} className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h2>
          <IconButton label="Close" onClick={onClose}><X size={16} /></IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border bg-surface-2/60 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} aria-hidden="true" />;
}
