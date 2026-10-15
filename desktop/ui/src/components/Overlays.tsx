import { AlertTriangle, CheckCircle2, Info, X, Keyboard, ImagePlus, MapPin } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { dismissToast, getState, patch, useStore } from '../lib/store';
import { cx, Button, Dialog, IconButton, Kbd } from './ui';
import { mapHandle } from '../lib/map/mapController';
import { assetUrl } from '../lib/backend';
import { Ocr } from './OcrBoxes';

// ----------------------------------------------------------------- toasts

export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2" aria-live="polite">
      {toasts.map((t) => {
        const Icon = t.kind === 'error' ? AlertTriangle : t.kind === 'success' ? CheckCircle2 : Info;
        return (
          <div
            key={t.id}
            role={t.kind === 'error' ? 'alert' : 'status'}
            className="pointer-events-auto pop-in glass flex max-w-[460px] items-start gap-3 rounded-xl px-4 py-3"
          >
            <Icon size={17} className={cx('mt-0.5 shrink-0', t.kind === 'error' && 'text-danger', t.kind === 'success' && 'text-high', t.kind === 'info' && 'text-accent')} />
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium">{t.title}</div>
              {t.body && <div className="mt-0.5 break-words text-[12px] text-fg-2">{t.body}</div>}
            </div>
            <button type="button" aria-label="Dismiss" onClick={() => dismissToast(t.id)} className="rounded p-0.5 text-fg-3 hover:text-fg">
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- confirm

export function ConfirmDialog() {
  const confirm = useStore((s) => s.confirm);
  const close = () => patch({ confirm: null });
  if (!confirm) return null;
  return (
    <Dialog
      open
      labelledById="confirm-title"
      onClose={close}
      title={confirm.title}
      width={420}
      footer={
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button
            variant={confirm.danger ? 'danger' : 'primary'}
            data-autofocus
            onClick={() => {
              const fn = confirm.onConfirm;
              close();
              fn();
            }}
          >
            {confirm.confirmLabel}
          </Button>
        </>
      }
    >
      <p className="px-5 py-5 text-[13.5px] leading-relaxed text-fg-2">{confirm.body}</p>
    </Dialog>
  );
}

// -------------------------------------------------------------- shortcuts

const SHORTCUTS: { keys: string[]; what: string }[] = [
  { keys: ['Ctrl', 'O'], what: 'Add photos' },
  { keys: ['Ctrl', 'V'], what: 'Paste a photo from the clipboard' },
  { keys: ['↑', '↓'], what: 'Previous or next photo in the library' },
  { keys: ['Delete'], what: 'Delete the selected photo' },
  { keys: ['F'], what: 'Fit the map to the guesses' },
  { keys: ['Ctrl', ','], what: 'Settings' },
  { keys: ['['], what: 'Show or hide the library' },
  { keys: [']'], what: 'Show or hide the inspector' },
  { keys: ['Esc'], what: 'Close a dialog or the full-size photo' },
  { keys: ['?'], what: 'This list' },
];

export function ShortcutsPopover() {
  const open = useStore((s) => s.shortcutsOpen);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50" onMouseDown={(e) => { if (e.target === e.currentTarget) patch({ shortcutsOpen: false }); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="shortcuts-title" className="pop-in glass absolute bottom-14 left-4 w-[340px] rounded-2xl p-4 shadow-[var(--shadow)]" style={{ background: 'var(--surface)' }}>
        <div className="mb-3 flex items-center justify-between">
          <h2 id="shortcuts-title" className="flex items-center gap-2 text-[14px] font-semibold"><Keyboard size={15} /> Keyboard shortcuts</h2>
          <IconButton label="Close shortcuts" onClick={() => patch({ shortcutsOpen: false })}><X size={15} /></IconButton>
        </div>
        <ul className="flex flex-col gap-2">
          {SHORTCUTS.map((s) => (
            <li key={s.what} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="text-fg-2">{s.what}</span>
              <span className="flex shrink-0 items-center gap-1">
                {s.keys.map((k) => <Kbd key={k}>{k}</Kbd>)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ------------------------------------------------------------- drop overlay

export function DropOverlay() {
  const active = useStore((s) => s.dropActive);
  if (!active) return null;
  return (
    <div className="fade-in pointer-events-none fixed inset-0 z-[55] flex items-center justify-center p-6" style={{ background: 'var(--scrim)', backdropFilter: 'blur(3px)' }}>
      <div className="relative flex h-full max-h-[520px] w-full max-w-[720px] flex-col items-center justify-center rounded-[28px] border-2 border-dashed border-accent bg-accent-soft/60 text-center">
        <div className="relative mb-6 flex h-28 w-28 items-center justify-center">
          <span className="absolute inset-0 rounded-full border-2 border-accent/50" style={{ animation: 'gl-ring 1.8s ease-out infinite' }} />
          <span className="absolute inset-0 rounded-full border-2 border-accent/40" style={{ animation: 'gl-ring 1.8s ease-out 0.6s infinite' }} />
          <div className="relative flex h-20 w-20 items-center justify-center rounded-3xl bg-accent text-accent-fg shadow-[0_18px_40px_rgb(79_110_247/0.45)]" style={{ animation: 'gl-float 2.4s ease-in-out infinite' }}>
            <ImagePlus size={34} strokeWidth={1.7} />
          </div>
          <MapPin size={22} className="absolute -bottom-1 right-2 text-accent" fill="currentColor" fillOpacity={0.25} />
        </div>
        <h2 className="text-[24px] font-semibold tracking-[-0.02em] text-fg">Drop photos to locate them</h2>
        <p className="mt-2 text-[14px] text-fg-2">Several at once are fine. They are located one by one.</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- lightbox

export function Lightbox() {
  const open = useStore((s) => s.lightboxOpen);
  const result = useStore((s) => (s.selectedId ? s.results[s.selectedId] ?? null : null));
  const show = useStore((s) => s.showTextBoxes);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    ref.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); patch({ lightboxOpen: false }); }
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [open]);
  if (!open || !result) return null;
  const { width: w, height: h } = result.image;
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-label={`Photo ${result.name}`}
      className="fade-in fixed inset-0 z-[70] flex items-center justify-center p-8 outline-none"
      style={{ background: 'rgb(3 5 8 / 0.9)' }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) patch({ lightboxOpen: false }); }}
    >
      <div className="relative flex h-full w-full items-center justify-center">
        <div className="relative max-h-full max-w-full" style={{ aspectRatio: `${w} / ${h}`, height: '100%' }}>
          <img src={assetUrl(result.image_url)} alt={result.name} className="h-full w-full object-contain" />
          {show && result.ocr.length > 0 && <Ocr result={result} />}
        </div>
      </div>
      <div className="absolute left-4 top-4 flex items-center gap-2">
        <button
          type="button"
          onClick={() => patch({ showTextBoxes: !show })}
          aria-pressed={show}
          disabled={!result.ocr.length}
          className={cx('glass h-8 rounded-lg px-3 text-[12px] font-medium text-fg disabled:opacity-50', show && 'ring-1 ring-medium')}
        >
          {result.ocr.length ? `Text boxes (${result.ocr.length})` : 'No text found'}
        </button>
        <span className="glass h-8 items-center rounded-lg px-3 text-[12px] text-fg-2 flex">{result.name}</span>
      </div>
      <IconButton label="Close full-size photo" onClick={() => patch({ lightboxOpen: false })} className="glass absolute right-4 top-4 h-9 w-9 text-fg">
        <X size={17} />
      </IconButton>
      <button
        type="button"
        onClick={() => { patch({ lightboxOpen: false }); const r = getState().results[result.id]; if (r) mapHandle.current?.flyTo(r.guesses[0].lat, r.guesses[0].lon, r.guesses[0].radius_km); }}
        className="glass absolute bottom-4 left-1/2 -translate-x-1/2 rounded-lg px-3 py-1.5 text-[12px] text-fg-2"
      >
        Show best guess on map
      </button>
    </div>
  );
}

