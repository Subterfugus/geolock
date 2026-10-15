import {
  Cpu, Keyboard, MoreHorizontal, PanelLeftClose, PanelLeftOpen, RotateCw, Search, Settings, Trash2, X,
  RefreshCw, FolderInput, Clock, FolderOpen, Download, LocateFixed, Square, ChevronDown, ChevronRight, FileJson, FileSpreadsheet, Globe2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  addFolder, addPhotos, askDelete, dismissQueued, exportLibrary, exportResult, gpsStats, reanalyse, retryQueued, selectResult, stopQueue, visibleHistory,
} from '../lib/controller';
import { assetUrl } from '../lib/backend';
import { ANALYST_NAME, dayLabel, deviceLabel, flag, km, plural, summaryTitle, timeLabel } from '../lib/format';
import { patch, useStore, type QueueItem } from '../lib/store';
import type { HistorySummary, Provider } from '../lib/types';
import { cx, ConfidencePill, IconButton, Kbd, LOGO_SRC, Spinner } from './ui';

const PROVIDER_CLASS: Record<Provider, string> = { claude: 'bg-claude', chatgpt: 'bg-chatgpt' };

export function Library() {
  const open = useStore((s) => s.sidebarOpen);
  if (!open) return <Rail />;
  return (
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-border bg-surface" aria-label="Library">
      <Header />
      <div className="flex gap-1.5 px-3 pb-2">
        <button
          type="button"
          onClick={() => void addPhotos()}
          className="flex h-10 min-w-0 flex-1 items-center justify-between rounded-md bg-accent px-3.5 text-[13.5px] font-semibold text-accent-fg transition-colors hover:bg-accent-strong active:translate-y-px"
        >
          <span className="flex items-center gap-2"><FolderInput size={16} /> Add photos</span>
          <span className="flex items-center gap-1 opacity-75"><Kbd>Ctrl</Kbd><Kbd>O</Kbd></span>
        </button>
        <IconButton
          label="Add a folder of photos (Ctrl+Shift+O)"
          onClick={() => void addFolder()}
          className="h-10 w-10 shrink-0 rounded-xl border border-border bg-surface-2 hover:bg-surface-3"
        >
          <FolderOpen size={17} />
        </IconButton>
      </div>
      <SearchBox />
      <FilterRow />
      <List />
      <Footer />
    </aside>
  );
}

function Header() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 px-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <img src={LOGO_SRC} alt="" className="h-[26px] w-[26px] shrink-0" />
        <span className="text-[15px] font-semibold tracking-[-0.01em]">GeoLock</span>
      </div>
      <div className="flex items-center">
        <IconButton label="Settings (Ctrl+,)" onClick={() => patch({ settingsOpen: true })}><Settings size={16} /></IconButton>
        <LibraryExport />
        <IconButton label="Hide library" onClick={() => patch({ sidebarOpen: false })}>
          <PanelLeftClose size={17} />
        </IconButton>
      </div>
    </header>
  );
}

function Rail() {
  return (
    <aside className="flex h-full w-[60px] shrink-0 flex-col items-center gap-1 border-r border-border bg-surface py-3" aria-label="Library (collapsed)">
      <img src={LOGO_SRC} alt="" className="mb-2 h-[26px] w-[26px]" />
      <IconButton label="Show library" onClick={() => patch({ sidebarOpen: true })}><PanelLeftOpen size={17} /></IconButton>
      <IconButton label="Add photos (Ctrl+O)" onClick={() => void addPhotos()}><FolderInput size={17} /></IconButton>
      <IconButton label="Add a folder of photos (Ctrl+Shift+O)" onClick={() => void addFolder()}><FolderOpen size={17} /></IconButton>
      <div className="mt-auto flex flex-col items-center gap-1">
        <IconButton label="Keyboard shortcuts (?)" onClick={() => patch({ shortcutsOpen: true })}><Keyboard size={16} /></IconButton>
        <IconButton label="Settings (Ctrl+,)" onClick={() => patch({ settingsOpen: true })}><Settings size={17} /></IconButton>
      </div>
    </aside>
  );
}

function SearchBox() {
  const search = useStore((s) => s.search);
  return (
    <div className="px-3 pb-3">
      <label className="flex h-9 items-center gap-2 rounded-lg border border-border bg-surface-2 px-2.5 text-fg-3 transition-colors focus-within:border-accent/60 focus-within:text-fg-2">
        <Search size={14} className="shrink-0" />
        <input
          value={search}
          onChange={(e) => patch({ search: e.target.value })}
          onKeyDown={(e) => { if (e.key === 'Escape' && search) { patch({ search: '' }); e.stopPropagation(); } }}
          placeholder="Search photos and places"
          aria-label="Search library"
          className="min-w-0 flex-1 bg-transparent text-[13px] text-fg outline-none placeholder:text-fg-3"
        />
        {search && (
          <button type="button" aria-label="Clear search" onClick={() => patch({ search: '' })} className="rounded p-0.5 hover:bg-surface-3">
            <X size={13} />
          </button>
        )}
      </label>
    </div>
  );
}

function List() {
  const history = useStore((s) => s.history);
  const search = useStore((s) => s.search);
  const libraryFilter = useStore((s) => s.libraryFilter);
  const queue = useStore((s) => s.queue);
  const batch = useStore((s) => s.batch);
  const selectedId = useStore((s) => s.selectedId);
  const items = useMemo(() => visibleHistory({ history, search, libraryFilter }), [history, search, libraryFilter]);
  const groups = useMemo(() => {
    const out: { label: string; items: HistorySummary[] }[] = [];
    for (const h of items) {
      const label = dayLabel(h.created);
      const last = out[out.length - 1];
      if (last && last.label === label) last.items.push(h);
      else out.push({ label, items: [h] });
    }
    return out;
  }, [items]);
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[aria-current="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [selectedId]);

  if (history === null) {
    return (
      <div className="flex flex-col gap-2 px-3 pt-1">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 p-2">
            <div className="skeleton h-12 w-12 shrink-0" />
            <div className="flex-1 space-y-2"><div className="skeleton h-3 w-3/4" /><div className="skeleton h-3 w-1/2" /></div>
          </div>
        ))}
      </div>
    );
  }

  const queueRows = queue.length > 0 && (
    <section aria-label="Being located" className="mb-2">
      <BatchHeader batch={batch} waiting={queue.filter((q) => q.status === 'queued').length} />
      <ul className="flex flex-col gap-0.5 px-2">
        {queue.filter((q) => q.status !== 'queued').concat(queue.filter((q) => q.status === 'queued').slice(0, 4)).map((q) => <QueueRow key={q.id} item={q} />)}
      </ul>
      {queue.filter((q) => q.status === 'queued').length > 4 && (
        <p className="px-5 pt-1 text-[11.5px] text-fg-3">and {queue.filter((q) => q.status === 'queued').length - 4} more waiting</p>
      )}
    </section>
  );

  return (
    <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto pb-3">
      {queueRows}
      <AccuracyCard items={items} />
      {items.length === 0 && queue.length === 0 && (
        <p className="px-5 pt-6 text-center text-[13px] text-fg-3">
          {search ? <>No photos match “{search}”.</> : libraryFilter === 'gps' ? 'No photos with their own GPS yet.' : 'Your located photos will appear here.'}
        </p>
      )}
      {groups.map((g) => (
        <section key={g.label + g.items[0].id} className="mb-1">
          <SectionLabel>{g.label}</SectionLabel>
          <ul className="flex flex-col gap-0.5 px-2">
            {g.items.map((h) => (
              <li key={h.id}>
                <PhotoRow
                  item={h}
                  selected={h.id === selectedId}
                  onOpenMenu={(x, y) => setMenu({ id: h.id, x, y })}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {menu && <ItemMenu id={menu.id} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <h3 className="px-5 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-3">{children}</h3>;
}

function Thumb({ src, className, children }: { src: string | null; className?: string; children?: ReactNode }) {
  return (
    <div className={cx('relative h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-surface-3', className)}>
      {src ? (
        <img src={src} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-fg-3">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="3" /><circle cx="9" cy="10" r="1.8" /><path d="m21 16-5-5-8 8" />
          </svg>
        </div>
      )}
      {children}
    </div>
  );
}

function QueueRow({ item }: { item: QueueItem }) {
  const running = item.status === 'running';
  const failed = item.status === 'error';
  return (
    <div className={cx('enter flex items-center gap-3 rounded-xl p-2', failed ? 'bg-danger-soft' : 'bg-surface-2')}>
      <Thumb src={item.thumb} className={running ? '' : 'opacity-70'}>
        {running && <div className="shimmer absolute inset-0" />}
        {running && <div className="absolute inset-0 flex items-center justify-center bg-bg/35 text-white"><Spinner size={16} /></div>}
      </Thumb>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium">{item.name}</div>
        {running && <div className="text-[12px] text-fg-2">Locating…</div>}
        {item.status === 'queued' && <div className="text-[12px] text-fg-3">Waiting its turn</div>}
        {failed && <div className="line-clamp-2 text-[12px] text-danger">{item.error || 'Something went wrong.'}</div>}
        {failed && (
          <div className="mt-1.5 flex gap-1.5">
            <button type="button" onClick={() => retryQueued(item.id)} className="inline-flex items-center gap-1 rounded-md bg-surface px-2 py-0.5 text-[12px] font-medium text-fg hover:bg-surface-3">
              <RefreshCw size={12} /> Retry
            </button>
            <button type="button" onClick={() => dismissQueued(item.id)} className="rounded-md px-2 py-0.5 text-[12px] text-fg-2 hover:bg-surface-3">Dismiss</button>
          </div>
        )}
      </div>
    </div>
  );
}

function PhotoRow({
  item, selected, onOpenMenu,
}: { item: HistorySummary; selected: boolean; onOpenMenu: (x: number, y: number) => void }) {
  const top = item.top;
  const title = summaryTitle(item);
  return (
    <div
      className={cx(
        'group relative flex items-center gap-1 rounded-xl pr-1 transition-colors duration-150',
        selected ? 'bg-accent-soft' : 'hover:bg-surface-2',
      )}
      onContextMenu={(e) => { e.preventDefault(); onOpenMenu(e.clientX, e.clientY); }}
    >
      {selected && <span className="absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-accent" aria-hidden="true" />}
      <button
        type="button"
        aria-current={selected ? 'true' : undefined}
        onClick={() => selectResult(item.id, true)}
        className="flex min-w-0 flex-1 items-center gap-3 rounded-xl p-2 text-left"
      >
        <Thumb src={item.thumb_url ? assetUrl(item.thumb_url) : null} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[13px] font-medium">{item.name}</span>
            <span className="shrink-0 text-[11px] text-fg-3 tnum">{timeLabel(item.created)}</span>
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 truncate text-[12.5px] text-fg-2">
            {top && <span className="text-[12px]">{flag(top.country_code)}</span>}
            <span className="truncate">{top ? title : 'No guess'}</span>
          </div>
          <div className="mt-1.5 flex items-center gap-1.5">
            {top && <ConfidencePill label={top.label} value={top.confidence} className="h-[20px] text-[11px]" />}
            {item.has_exif_gps && <GpsBadge km={item.km_from_exif} />}
            <span className="ml-auto flex items-center gap-1">
              {item.analysts.map((p) => (
                <span key={p} title={`${ANALYST_NAME[p]} was asked`} className={cx('flex h-[16px] w-[16px] items-center justify-center rounded-[5px] text-[9.5px] font-bold text-white', PROVIDER_CLASS[p])}>
                  {p === 'claude' ? 'C' : 'G'}
                </span>
              ))}
            </span>
          </div>
        </div>
      </button>
      <IconButton
        label={`More actions for ${item.name}`}
        className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
        onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); onOpenMenu(r.right, r.bottom); }}
      >
        <MoreHorizontal size={15} />
      </IconButton>
    </div>
  );
}

function ItemMenu({ id, x, y, onClose }: { id: string; x: number; y: number; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('mousedown', down);
    window.addEventListener('keydown', key);
    window.addEventListener('blur', onClose);
    return () => {
      window.removeEventListener('mousedown', down);
      window.removeEventListener('keydown', key);
      window.removeEventListener('blur', onClose);
    };
  }, [onClose]);
  const left = Math.min(x, window.innerWidth - 230);
  const top = Math.min(y + 4, window.innerHeight - 230);
  return (
    <div ref={ref} role="menu" style={{ left, top }} className="pop-in fixed z-40 w-[220px] rounded-xl border border-border bg-surface p-1 shadow-[var(--shadow)]">
      <MenuItem icon={<RotateCw size={14} />} onClick={() => { onClose(); void reanalyse(id); }}>Re-analyse</MenuItem>
      <MenuItem icon={<Clock size={14} />} onClick={() => { onClose(); selectResult(id, true); }}>Show in inspector</MenuItem>
      <div className="my-1 h-px bg-border" />
      <MenuItem icon={<Globe2 size={14} />} onClick={() => { onClose(); void exportResult(id, 'kml'); }}>Export KML (Google Earth)</MenuItem>
      <MenuItem icon={<FileSpreadsheet size={14} />} onClick={() => { onClose(); void exportResult(id, 'csv'); }}>Export CSV</MenuItem>
      <MenuItem icon={<FileJson size={14} />} onClick={() => { onClose(); void exportResult(id, 'json'); }}>Export JSON</MenuItem>
      <div className="my-1 h-px bg-border" />
      <MenuItem danger icon={<Trash2 size={14} />} onClick={() => { onClose(); askDelete(id); }}>Delete</MenuItem>
    </div>
  );
}

function MenuItem({ children, icon, onClick, danger }: { children: ReactNode; icon: ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={cx('flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] hover:bg-surface-3', danger ? 'text-danger' : 'text-fg')}
    >
      <span className="text-fg-3">{icon}</span>{children}
    </button>
  );
}

function Footer() {
  const device = useStore((s) => s.status?.device);
  const available = useStore((s) => s.status?.available_devices ?? []);
  return (
    <footer className="flex h-12 shrink-0 items-center justify-between gap-2 border-t border-border px-3">
      <button
        type="button"
        onClick={() => patch({ settingsOpen: true })}
        className="inline-flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-[12px] text-fg-2 hover:bg-surface-2"
        title={available.length ? `Available processors: ${available.join(', ')}. Change in Settings.` : 'Where the AI models run'}
      >
        <Cpu size={13} className="shrink-0 text-accent" />
        <span className="truncate">{deviceLabel(device)}</span>
      </button>
      <div className="flex shrink-0 items-center gap-1">
        <IconButton label="Keyboard shortcuts (?)" onClick={() => patch({ shortcutsOpen: true })}><Keyboard size={15} /></IconButton>
        <button
          type="button"
          onClick={() => patch({ settingsOpen: true })}
          title="Settings (Ctrl+,)"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong px-2.5 text-[12.5px] font-medium text-fg transition-colors hover:bg-surface-3"
        >
          <Settings size={14} /> Settings
        </button>
      </div>
    </footer>
  );
}


/** How close a guess came to the photo's own GPS, coloured by band. */
export function GpsBadge({ km: d }: { km: number | null }) {
  const band = d == null ? null : d <= 25 ? 'high' : d <= 750 ? 'medium' : 'low';
  return (
    <span
      className={cx(
        'inline-flex h-[20px] items-center gap-1 whitespace-nowrap rounded-full border px-1.5 text-[11px] tnum',
        band === 'high' && 'border-high/40 text-high',
        band === 'medium' && 'border-medium/40 text-medium',
        (band === 'low' || band === null) && 'border-border text-fg-3',
      )}
      title={d == null ? 'The photo has its own GPS' : "Distance from the best guess to the photo's own GPS"}
    >
      <LocateFixed size={11} /> {d == null ? 'GPS' : `${km(d)} off`}
    </span>
  );
}

function FilterRow() {
  const filter = useStore((s) => s.libraryFilter);
  const total = useStore((s) => s.history?.length ?? 0);
  const withGps = useStore((s) => (s.history ?? []).filter((h) => h.has_exif_gps).length);
  if (!withGps && filter === 'all') return null;
  const chip = (value: 'all' | 'gps', label: string, n: number) => (
    <button
      type="button"
      aria-pressed={filter === value}
      onClick={() => patch({ libraryFilter: value })}
      className={cx(
        'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] transition-colors',
        filter === value ? 'border-accent/50 bg-accent-soft font-medium text-fg' : 'border-border text-fg-2 hover:bg-surface-2',
      )}
    >
      {label} <span className="text-fg-3 tnum">{n}</span>
    </button>
  );
  return (
    <div className="flex gap-1.5 px-3 pb-2" role="group" aria-label="Filter the library">
      {chip('all', 'All', total)}
      {chip('gps', 'With GPS', withGps)}
    </div>
  );
}

/** Accuracy against the photos' own GPS, for the photos the list shows. */
function AccuracyCard({ items }: { items: HistorySummary[] }) {
  const stats = useMemo(() => gpsStats(items), [items]);
  const [open, setOpen] = useState(true);
  if (!stats || stats.n < 2) return null;
  return (
    <section className="mx-3 mb-1 mt-1 rounded-xl border border-border bg-surface-2/60 px-3 py-2.5" aria-label="Accuracy on photos with GPS">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 text-left">
        <span className="flex items-center gap-1.5 text-[12px] font-medium text-fg-2">
          <LocateFixed size={13} className="shrink-0 text-accent" /> Accuracy, {plural(stats.n, 'photo')} with GPS
        </span>
        <span className="flex shrink-0 items-center gap-1 whitespace-nowrap text-[12px] text-fg-3 tnum">
          {km(stats.median)} median {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>
      </button>
      {open && (
        <div className="mt-2 grid grid-cols-4 gap-1.5 fade-in">
          {stats.within.map((b) => (
            <div key={b.km} className="rounded-lg bg-surface px-1 py-1.5 text-center" title={`${b.label} level: ${b.count} of ${stats.n} within ${b.km.toLocaleString()} km`}>
              <div className="text-[13px] font-semibold tnum">{Math.round(b.share * 100)}%</div>
              <div className="whitespace-nowrap text-[10.5px] leading-tight text-fg-3">{b.label}</div>
              <div className="whitespace-nowrap text-[10px] leading-tight text-fg-3 tnum">≤{b.km.toLocaleString()} km</div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function BatchHeader({ batch, waiting }: { batch: { total: number; done: number; failed: number } | null; waiting: number }) {
  if (!batch || batch.total < 2) return <SectionLabel>Locating</SectionLabel>;
  const finished = batch.done + batch.failed;
  return (
    <div className="px-5 pb-1.5 pt-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-3">
          Locating {Math.min(finished + 1, batch.total)} of {batch.total}
        </h3>
        {waiting > 0 && (
          <button type="button" onClick={stopQueue} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-fg-2 hover:bg-surface-3 hover:text-fg">
            <Square size={10} fill="currentColor" /> Stop
          </button>
        )}
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={batch.total} aria-valuenow={finished}>
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${(finished / batch.total) * 100}%` }} />
      </div>
      {batch.failed > 0 && <p className="mt-1 text-[11px] text-danger">{plural(batch.failed, 'photo')} could not be read</p>}
    </div>
  );
}

function LibraryExport() {
  const [open, setOpen] = useState(false);
  const count = useStore((s) => visibleHistory(s).length);
  const exporting = useStore((s) => s.exporting);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('mousedown', down);
    window.addEventListener('keydown', key);
    return () => { window.removeEventListener('mousedown', down); window.removeEventListener('keydown', key); };
  }, [open]);
  if (!count) return null;
  const run = (f: 'csv' | 'kml' | 'json') => { setOpen(false); void exportLibrary(f); };
  return (
    <div ref={ref} className="relative">
      <IconButton label="Export the library" disabled={exporting} onClick={() => setOpen((v) => !v)}>
        {exporting ? <Spinner size={15} /> : <Download size={16} />}
      </IconButton>
      {open && (
        <div role="menu" className="pop-in absolute left-0 top-9 z-40 w-[230px] rounded-xl border border-border bg-surface p-1 shadow-[var(--shadow)]">
          <div className="px-2.5 pb-1 pt-1.5 text-[11px] text-fg-3">Export {count === 1 ? 'the photo shown' : `the ${count} photos shown`}</div>
          <MenuItem icon={<FileSpreadsheet size={14} />} onClick={() => run('csv')}>CSV for Excel</MenuItem>
          <MenuItem icon={<Globe2 size={14} />} onClick={() => run('kml')}>KML for Google Earth</MenuItem>
          <MenuItem icon={<FileJson size={14} />} onClick={() => run('json')}>JSON (everything)</MenuItem>
        </div>
      )}
    </div>
  );
}
