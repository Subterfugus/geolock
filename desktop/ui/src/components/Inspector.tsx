import {
  AlertTriangle, ChevronDown, ChevronRight, Circle, Copy, ExternalLink, Maximize2, MapPin, Minus, PanelRightClose,
  Plus, RefreshCw, RotateCw, ScanText, Trash2, Download, FileJson, FileSpreadsheet, Globe2, Image as ImageIcon, LocateFixed, Star,
} from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { askAnalyst, askDelete, exportResult, reanalyse, selectGuess } from '../lib/controller';
import { errorsKm, truthOf } from '../lib/exporter';
import { haversineKm } from '../lib/geo';
import { assetUrl } from '../lib/backend';
import { copyText, openExternal } from '../lib/shell';
import { mapHandle } from '../lib/map/mapController';
import { Ocr } from './OcrBoxes';
import {
  ANALYST_COMPANY, ANALYST_NAME, confidenceName, coordText, deviceLabel, formatSeconds, fullDate, guessTitle, km, pct, plainCoords, radiusText,
} from '../lib/format';
import { patch, useStore } from '../lib/store';
import type { Analyst, AnalystCrop, Clue, Guess, Provider, Result } from '../lib/types';
import { Button, ConfidencePill, ConfidenceRing, cx, Flag, IconButton, Meter, SectionTitle, Spinner, confBg, confText } from './ui';

const PROVIDER_VAR: Record<Provider, string> = { claude: 'var(--claude)', chatgpt: 'var(--chatgpt)' };

export function Inspector() {
  const open = useStore((s) => s.inspectorOpen);
  const id = useStore((s) => s.selectedId);
  const result = useStore((s) => (s.selectedId ? s.results[s.selectedId] ?? null : null));
  const name = useStore((s) => s.history?.find((h) => h.id === s.selectedId)?.name ?? null);
  if (!open) return null;
  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-border bg-surface" aria-label="Photo details">
      <InspectorHeader name={result?.name ?? name} created={result?.created ?? null} hasId={!!id} />
      {!id && <EmptyInspector />}
      {id && !result && <InspectorSkeleton />}
      {id && result && <ResultBody key={result.id} result={result} />}
    </aside>
  );
}

function InspectorHeader({ name, created, hasId }: { name: string | null; created: string | null; hasId: boolean }) {
  const id = useStore((s) => s.selectedId);
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-semibold">{name ?? 'Photo details'}</div>
        {created && <div className="truncate text-[11.5px] text-fg-3">{fullDate(created)}</div>}
      </div>
      {hasId && id && (
        <>
          <ExportMenu id={id} />
          <IconButton label="Re-analyse" onClick={() => void reanalyse(id)}><RotateCw size={15} /></IconButton>
          <IconButton label="Delete photo" onClick={() => askDelete(id)}>
            <Trash2 size={15} />
          </IconButton>
        </>
      )}
      <IconButton label="Hide inspector" onClick={() => patch({ inspectorOpen: false })}><PanelRightClose size={16} /></IconButton>
    </header>
  );
}

function EmptyInspector() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-2 text-fg-3"><MapPin size={22} /></div>
      <p className="text-[13.5px] text-fg-2">Select a photo to see where it was most likely taken, and why.</p>
    </div>
  );
}

function InspectorSkeleton() {
  return (
    <div className="space-y-4 p-5">
      <div className="skeleton h-[180px] w-full rounded-2xl" />
      <div className="skeleton h-[150px] w-full rounded-2xl" />
      <div className="skeleton h-4 w-1/3" />
      <div className="skeleton h-20 w-full" />
    </div>
  );
}

function ResultBody({ result }: { result: Result }) {
  const sel = useStore((s) => s.selectedGuess);
  const guess: Guess | undefined = result.guesses[sel] ?? result.guesses[0];
  const index = guess ? result.guesses.indexOf(guess) : 0;
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="space-y-7 px-5 pb-10 pt-4 enter">
        <PhotoPanel result={result} />
        {guess ? (
          <>
            <Hero guess={guess} index={index} />
            <GroundTruth result={result} index={index} />
            <OtherGuesses result={result} selected={index} />
            <Why guess={guess} index={index} />
            <Countries result={result} guess={guess} />
          </>
        ) : (
          <p className="text-[13px] text-fg-2">GeoLock could not find a likely place for this photo.</p>
        )}
        <Clues result={result} />
        <SecondOpinion result={result} />
        <Details result={result} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ photo

function PhotoPanel({ result }: { result: Result }) {
  const show = useStore((s) => s.showTextBoxes);
  const { width: w, height: h } = result.image;
  const hasOcr = result.ocr.length > 0;
  return (
    <div className="group relative w-full overflow-hidden rounded-2xl bg-surface-3" style={{ aspectRatio: `${w} / ${h}`, maxHeight: 250 }}>
      <img src={assetUrl(result.image_url)} alt={`Photo: ${result.name}`} className="h-full w-full object-contain" decoding="async" />
      {show && hasOcr && <Ocr result={result} />}
      <div className="absolute bottom-2 left-2 flex gap-1.5">
        <button
          type="button"
          disabled={!hasOcr}
          onClick={() => patch({ showTextBoxes: !show })}
          aria-pressed={show}
          title={hasOcr ? 'Outline the text GeoLock read' : 'No text was found in this photo'}
          className={cx(
            'glass inline-flex h-7 items-center gap-1.5 rounded-lg px-2 text-[11.5px] font-medium text-fg disabled:opacity-50',
            show && 'ring-1 ring-medium',
          )}
        >
          <ScanText size={13} /> {hasOcr ? `Text (${result.ocr.length})` : 'No text'}
        </button>
      </div>
      <button
        type="button"
        onClick={() => patch({ lightboxOpen: true })}
        aria-label="View photo full size"
        className="glass absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-lg opacity-90 transition-opacity hover:opacity-100"
      >
        <Maximize2 size={13} />
      </button>
    </div>
  );
}

// ------------------------------------------------------------------- hero

function Hero({ guess, index }: { guess: Guess; index: number }) {
  const t = guessTitle(guess);
  const sub = [guess.region && guess.region !== t.main ? guess.region : null, guess.country].filter(Boolean).join(' · ');
  const near = guess.place && guess.place.km >= 60 ? `${Math.round(guess.place.km)} km from ${guess.place.name}` : null;
  return (
    <section aria-label={index === 0 ? 'Best guess' : `Guess ${index + 1}`} className="rounded-2xl border border-border bg-surface-2 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-3">
          {index === 0 ? 'Best guess' : `Guess #${index + 1}`}
        </span>
        <ConfidencePill label={guess.label} value={guess.confidence} />
      </div>
      <div className="mt-3 flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[23px] font-semibold leading-[1.15] tracking-[-0.025em]">{t.main}</h3>
          <p className="mt-1 flex items-center gap-1.5 truncate text-[13px] text-fg-2">
            <Flag code={guess.country_code} />
            <span className="truncate">{sub || guess.continent || ''}</span>
          </p>
          {near && <p className="mt-0.5 truncate text-[12px] text-fg-3">{near}</p>}
        </div>
        <ConfidenceRing value={guess.confidence} label={guess.label} size={72} />
      </div>
      <div className="mt-4">
        <Meter value={guess.confidence} label={guess.label} />
        <div className="mt-2 flex items-center justify-between text-[12px] text-fg-3">
          <span title="68% of this guess's probability falls inside this radius">
            Likely within <span className={cx('font-semibold tnum', confText(guess.label))}>{radiusText(guess.radius_km)}</span>
          </span>
          <span className="tnum">{confidenceName(guess.label)}</span>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-2">
        <CopyCoords lat={guess.lat} lon={guess.lon} />
        <Button size="md" className="h-8 flex-1" onClick={() => void openExternal(`https://www.google.com/maps?q=${guess.lat.toFixed(6)},${guess.lon.toFixed(6)}`)}>
          <ExternalLink size={14} /> Google Maps
        </Button>
      </div>
      {index !== 0 && (
        <button type="button" onClick={() => selectGuess(0)} className="mt-3 text-[12px] font-medium text-accent hover:underline">
          ← Back to best guess
        </button>
      )}
    </section>
  );
}

function CopyCoords({ lat, lon }: { lat: number; lon: number }) {
  return (
    <button
      type="button"
      onClick={() => void copyText(plainCoords(lat, lon), 'Coordinates')}
      title="Copy coordinates"
      className="group flex h-8 flex-1 items-center justify-between gap-2 rounded-lg border border-border bg-surface px-2.5 text-left transition-colors hover:border-border-strong"
    >
      <span className="truncate font-mono text-[11.5px] text-fg-2 tnum">{coordText(lat, lon)}</span>
      <Copy size={13} className="shrink-0 text-fg-3 transition-colors group-hover:text-fg" />
    </button>
  );
}

// ---------------------------------------------------------- ground truth

/** How far off a distance is, in the GeoGuessr-style bands the evals use. */
function band(d: number): { label: string; tone: 'high' | 'medium' | 'low' } {
  if (d <= 1) return { label: 'Spot on', tone: 'high' };
  if (d <= 25) return { label: 'Street level', tone: 'high' };
  if (d <= 200) return { label: 'City level', tone: 'medium' };
  if (d <= 750) return { label: 'Region level', tone: 'medium' };
  if (d <= 2500) return { label: 'Country level', tone: 'low' };
  return { label: 'Missed', tone: 'low' };
}

/** When the photo carries its own GPS: where that is and how close each guess came. */
function GroundTruth({ result, index }: { result: Result; index: number }) {
  const truth = truthOf(result);
  if (!truth) return null;
  if (!result.exif_gps) {
    return (
      <p className="-mt-3 flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-[12px] text-fg-3">
        <LocateFixed size={13} className="shrink-0" /> This photo has its own GPS. Turn on “Show the photo's own GPS” in Settings and re-analyse to compare.
      </p>
    );
  }
  const errs = errorsKm(result);
  const d = errs[index] ?? errs[0];
  const best = errs.reduce<{ i: number; d: number } | null>((acc, e, i) => (e != null && (!acc || e < acc.d) ? { i, d: e } : acc), null);
  const analysts = result.analysts
    .filter((a) => a.ok && a.guesses[0])
    .map((a) => ({ name: a.name, d: a.guesses[0].km_from_exif ?? haversineKm(a.guesses[0].lat, a.guesses[0].lon, truth.lat, truth.lon) }));
  const where = [result.exif_place?.place?.name, result.exif_place?.region, result.exif_place?.country].filter(Boolean)
    .filter((v, i, a) => a.indexOf(v) === i).join(', ');
  const b = d != null ? band(d) : null;
  return (
    <section aria-label="The photo's own GPS" className="-mt-3 rounded-2xl border border-medium/35 bg-medium/[0.07] p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-medium">
            <Star size={12} fill="currentColor" /> Photo's own GPS
          </div>
          <p className="mt-1 truncate text-[13px] text-fg" title={plainCoords(truth.lat, truth.lon)}>{where || coordText(truth.lat, truth.lon)}</p>
          <p className="text-[11px] text-fg-3">Never used for the guess, only to check it.</p>
        </div>
        {d != null && b && (
          <div className="shrink-0 text-right">
            <div className="text-[20px] font-semibold leading-none tracking-[-0.02em] tnum">{km(d)}</div>
            <div className={cx('mt-1 text-[11.5px] font-medium', confText(b.tone))}>{b.label}</div>
          </div>
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-fg-2">
        {best && best.i !== index && (
          <button type="button" onClick={() => selectGuess(best.i)} className="rounded-md bg-surface px-2 py-0.5 hover:bg-surface-3" title="Show that guess">
            Closest: guess #{best.i + 1}, {km(best.d)}
          </button>
        )}
        {analysts.map((a) => (
          <span key={a.name} className="rounded-md bg-surface px-2 py-0.5">{a.name}: {km(a.d)}</span>
        ))}
        <button
          type="button"
          onClick={() => mapHandle.current?.flyTo(truth.lat, truth.lon, 20)}
          className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-accent hover:bg-surface"
        >
          <MapPin size={12} /> Show on map
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- export

function ExportMenu({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
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
  const run = (f: 'png' | 'kml' | 'csv' | 'json') => { setOpen(false); void exportResult(id, f); };
  const item = (f: 'png' | 'kml' | 'csv' | 'json', icon: ReactNode, label: string, hint: string) => (
    <button type="button" role="menuitem" onClick={() => run(f)} className="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-surface-3">
      <span className="mt-0.5 text-fg-3">{icon}</span>
      <span><span className="block text-[13px]">{label}</span><span className="block text-[11px] text-fg-3">{hint}</span></span>
    </button>
  );
  return (
    <div ref={ref} className="relative">
      <IconButton label="Export this result" disabled={exporting} onClick={() => setOpen((v) => !v)}>
        {exporting ? <Spinner size={14} /> : <Download size={15} />}
      </IconButton>
      {open && (
        <div role="menu" className="pop-in absolute right-0 top-9 z-40 w-[250px] rounded-xl border border-border bg-surface p-1 shadow-[var(--shadow)]">
          {item('png', <ImageIcon size={14} />, 'Map image (PNG)', 'The map as shown, with the photo and pins')}
          {item('kml', <Globe2 size={14} />, 'KML', 'Opens in Google Earth and Google My Maps')}
          {item('csv', <FileSpreadsheet size={14} />, 'CSV', 'One row per guess, for Excel')}
          {item('json', <FileJson size={14} />, 'JSON', 'The full result, clues included')}
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- guesses

function OtherGuesses({ result, selected }: { result: Result; selected: number }) {
  const others = result.guesses.map((g, i) => ({ g, i })).filter((x) => x.i !== selected);
  if (!others.length) return null;
  return (
    <section>
      <SectionTitle>Other guesses</SectionTitle>
      <ol className="flex flex-col gap-0.5">
        {others.map(({ g, i }) => {
          const t = guessTitle(g);
          return (
            <li key={i}>
              <button
                type="button"
                onClick={() => selectGuess(i)}
                className="grid w-full grid-cols-[22px_1fr_auto] items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-surface-2"
              >
                <span className={cx('flex h-[20px] w-[20px] items-center justify-center rounded-full text-[10.5px] font-bold text-[color:var(--pin-fg)] tnum', confBg(g.label))}>
                  {i + 1}
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 truncate text-[13px]">
                    <span className="truncate">{t.main}</span>
                    <Flag code={g.country_code} />
                  </span>
                  <span className="mt-1 flex items-center gap-2">
                    <span className="w-[72px] shrink-0"><Meter value={g.confidence} label={g.label} className="h-1" /></span>
                    <span className="truncate text-[11.5px] text-fg-3 tnum">±{Math.round(g.radius_km)} km</span>
                  </span>
                </span>
                <span className="text-[13px] font-semibold tnum text-fg-2">{pct(g.confidence)}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

// ------------------------------------------------------------------ why

function Why({ guess, index }: { guess: Guess; index: number }) {
  if (!guess.why.length) return null;
  return (
    <section>
      <SectionTitle>Why {index === 0 ? 'the best guess' : `guess #${index + 1}`}</SectionTitle>
      <ul className="flex flex-col gap-2">
        {guess.why.map((w, i) => (
          <li key={i} className="flex items-start gap-2.5 text-[13px] leading-snug">
            <span
              className={cx(
                'mt-[2px] flex h-[16px] w-[16px] shrink-0 items-center justify-center rounded-full',
                w.effect > 0 && 'bg-pos/15 text-pos',
                w.effect < 0 && 'bg-neg/15 text-neg',
                w.effect === 0 && 'text-fg-3',
              )}
              aria-label={w.effect > 0 ? 'Supports' : w.effect < 0 ? 'Argues against' : 'Neutral'}
            >
              {w.effect > 0 ? <Plus size={11} strokeWidth={3} /> : w.effect < 0 ? <Minus size={11} strokeWidth={3} /> : <Circle size={5} fill="currentColor" />}
            </span>
            <span className={w.effect < 0 ? 'text-fg-2' : 'text-fg'}>{w.text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------ countries

function Countries({ result, guess }: { result: Result; guess: Guess }) {
  const rows = result.countries.slice(0, 6);
  if (!rows.length) return null;
  const max = Math.max(...rows.map((c) => c.prob), 0.01);
  return (
    <section>
      <SectionTitle>Country odds</SectionTitle>
      <div className="flex flex-col gap-2.5">
        {rows.map((c) => {
          const here = c.code === guess.country_code;
          return (
            <div key={c.code} className="grid grid-cols-[minmax(0,118px)_1fr_40px] items-center gap-2.5" title={c.clip_prob != null ? `CLIP zero-shot alone: ${pct(c.clip_prob)}` : undefined}>
              <span className="flex min-w-0 items-center gap-1.5 text-[12.5px]">
                <Flag code={c.code} />
                <span className={cx('truncate', here ? 'font-semibold text-fg' : 'text-fg-2')}>{c.name}</span>
              </span>
              <span className="h-[7px] overflow-hidden rounded-full bg-surface-3">
                <span
                  className={cx('block h-full rounded-full transition-[width] duration-500 ease-out', here ? 'bg-accent' : 'bg-fg-3/45')}
                  style={{ width: `${Math.max(2, (c.prob / max) * 100)}%` }}
                />
              </span>
              <span className="text-right text-[12px] tnum text-fg-2">{pct(c.prob)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- clues

const CLUE_GROUPS: { title: string; kinds: string[] }[] = [
  { title: 'Text & language', kinds: ['ocr', 'language', 'script', 'domain', 'phone', 'currency', 'units'] },
  { title: 'Scene', kinds: ['scene', 'vlm'] },
  { title: 'Camera & time', kinds: ['exif', 'timezone'] },
  { title: 'Second opinions', kinds: ['claude', 'chatgpt'] },
];

const KIND_LABEL: Record<string, string> = {
  ocr: 'Text', language: 'Language', script: 'Script', domain: 'Website', phone: 'Phone', currency: 'Currency',
  units: 'Units', scene: 'Scene', vlm: 'Vision model', timezone: 'Time zone', exif: 'Camera', claude: 'Claude', chatgpt: 'ChatGPT',
};

function Clues({ result }: { result: Result }) {
  const groups = CLUE_GROUPS.map((g) => ({
    ...g,
    clues: result.clues
      .filter((c) => g.kinds.includes(c.kind))
      .sort((a, b) => b.strength - a.strength),
  })).filter((g) => g.clues.length);
  const other = result.clues.filter((c) => !CLUE_GROUPS.some((g) => g.kinds.includes(c.kind)));
  if (other.length) groups.push({ title: 'Other', kinds: [], clues: other });
  return (
    <section aria-label="Clues">
      <SectionTitle>Clues</SectionTitle>
      {!groups.length && (
        <p className="text-[13px] text-fg-2">No specific clues. The guess rests on overall visual similarity.</p>
      )}
      <div className="flex flex-col gap-4">
        {groups.map((g) => (
          <div key={g.title}>
            <h4 className="mb-1.5 text-[12px] font-medium text-fg-2">{g.title}</h4>
            <ul className="flex flex-col gap-1.5">
              {g.clues.map((c, i) => <ClueRow key={i} clue={c} />)}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function ClueRow({ clue }: { clue: Clue }) {
  const s = clue.strength;
  const bars = s >= 0.66 ? 3 : s >= 0.33 ? 2 : s > 0 ? 1 : 0;
  const pointsTo = clue.countries ?? [];
  return (
    <li className="rounded-xl border border-border bg-surface-2/60 px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-medium uppercase tracking-[0.06em] text-fg-3">{KIND_LABEL[clue.kind] ?? clue.kind}</span>
          </div>
          <div className="text-[13px] font-medium leading-snug">{clue.title}</div>
        </div>
        {bars > 0 ? (
          <span className="mt-1 flex shrink-0 items-end gap-[3px]" title={`Strength ${Math.round(s * 100)}%`} aria-label={`Strength ${bars} of 3`}>
            {[1, 2, 3].map((n) => (
              <span key={n} className={cx('w-[4px] rounded-sm', n <= bars ? 'bg-accent' : 'bg-border-strong')} style={{ height: 4 + n * 3 }} />
            ))}
          </span>
        ) : (
          <span className="mt-0.5 shrink-0 rounded-md border border-border px-1.5 py-px text-[10.5px] text-fg-3">info</span>
        )}
      </div>
      {clue.detail && <p className="mt-1 text-[12.5px] leading-snug text-fg-2">{clue.detail}</p>}
      {pointsTo.length > 0 && (
        <p className="mt-1.5 text-[11.5px] text-fg-3">
          Points to {pointsTo.slice(0, 4).map((c) => c.name).join(', ')}
          {(clue.n_countries ?? pointsTo.length) > 4 ? ` +${(clue.n_countries ?? pointsTo.length) - 4} more` : ''}
        </p>
      )}
    </li>
  );
}

// ----------------------------------------------------- second opinions

function SecondOpinion({ result }: { result: Result }) {
  const status = useStore((s) => s.status?.analysts ?? {});
  const asking = useStore((s) => s.asking[result.id]);
  const providers: Provider[] = ['claude', 'chatgpt'];
  const answered = (p: Provider) => result.analysts.find((a) => a.provider === p);
  return (
    <section aria-label="Second opinion">
      <SectionTitle>Second opinion</SectionTitle>
      <div className="grid grid-cols-2 gap-2">
        {providers.map((p) => {
          const st = status[p];
          const available = !!st?.available;
          const busy = asking === p;
          const done = answered(p);
          const label = `Ask ${ANALYST_NAME[p]}`;
          return (
            <button
              key={p}
              type="button"
              disabled={!available || !!asking}
              onClick={() => void askAnalyst(result.id, p)}
              title={available ? `${ANALYST_NAME[p]} sees only the photo and GeoLock's findings (if sharing is on).` : st?.detail ?? 'Not set up'}
              className="group flex min-h-[52px] flex-col items-start justify-center gap-0.5 rounded-xl border border-border bg-surface-2 px-3 py-2 text-left transition-colors hover:border-border-strong disabled:cursor-not-allowed disabled:opacity-55"
            >
              <span className="flex w-full items-center gap-2 text-[13px] font-semibold">
                <span className="flex h-[18px] w-[18px] items-center justify-center rounded-[5px] text-[10px] font-bold text-white" style={{ background: PROVIDER_VAR[p] }}>
                  {p === 'claude' ? 'C' : 'G'}
                </span>
                {busy ? <Spinner size={13} className="text-fg-2" /> : null}
                <span className="truncate">{busy ? `Asking ${ANALYST_NAME[p]}…` : done ? `Ask ${ANALYST_NAME[p]} again` : label}</span>
              </span>
              <span className="pl-[26px] text-[11px] text-fg-3">
                {busy ? 'Usually 5–30 s' : available ? 'Uses your own login' : 'Not set up'}
              </span>
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-[11.5px] leading-snug text-fg-3">
        Sends the photo (without GPS or other metadata) to Anthropic or OpenAI, using your own plan. Nothing is sent unless you click.
      </p>
      {result.analysts.length > 0 && (
        <div className="mt-4 flex flex-col gap-3">
          {result.analysts.map((a) => <AnalystCard key={a.provider} analyst={a} result={result} />)}
        </div>
      )}
    </section>
  );
}

function AnalystCard({ analyst: a, result }: { analyst: Analyst; result: Result }) {
  const resultId = result.id;
  const asking = useStore((s) => s.asking[resultId]);
  const color = PROVIDER_VAR[a.provider];
  const name = ANALYST_NAME[a.provider];
  const meta = [a.model, a.ms != null ? formatSeconds(a.ms) : null].filter(Boolean).join(' · ');
  const checklist = a.checklist ?? [];
  const ruledOut = a.ruled_out ?? [];
  const crops = a.crops ?? [];
  if (!a.ok) {
    return (
      <article className="rounded-xl border border-border bg-surface-2 p-3.5" style={{ borderLeft: `3px solid ${color}` }}>
        <header className="flex items-center justify-between gap-2">
          <span className="text-[13px] font-semibold" style={{ color }}>{name} didn't answer</span>
          <span className="text-[11px] text-fg-3 tnum">{meta}</span>
        </header>
        <div className="mt-2 flex gap-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
          <AlertTriangle size={15} className="mt-px shrink-0" />
          <span className="min-w-0 break-words">{friendlyError(a.error)}</span>
        </div>
        <Button size="sm" className="mt-2.5" disabled={!!asking} onClick={() => void askAnalyst(resultId, a.provider)}>
          <RefreshCw size={12} /> Try again
        </Button>
      </article>
    );
  }
  return (
    <article className="rounded-xl border border-border bg-surface-2 p-3.5" style={{ borderLeft: `3px solid ${color}` }}>
      <header className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold text-white" style={{ background: color }}>
            {a.provider === 'claude' ? 'C' : 'G'}
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-semibold" style={{ color }}>{name}'s view</div>
            <div className="truncate text-[11px] text-fg-3" title={a.via}>{a.via}</div>
          </div>
        </div>
        <span className="shrink-0 text-right text-[11px] text-fg-3 tnum">{meta}</span>
      </header>
      {a.reasoning && <p className="mt-2.5 text-[13px] leading-relaxed text-fg">{a.reasoning}</p>}
      {((a.driving_side && a.driving_side !== 'unknown') || a.text_seen) && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {a.driving_side && a.driving_side !== 'unknown' && <span className="rounded-md bg-surface px-2 py-0.5 text-[11.5px] text-fg-2">Drives on the <b className="font-semibold text-fg">{a.driving_side}</b></span>}
          {a.text_seen && <span className="max-w-full truncate rounded-md bg-surface px-2 py-0.5 text-[11.5px] text-fg-2" title={a.text_seen}>Text: “{a.text_seen}”</span>}
        </div>
      )}
      {crops.length > 0 && (
        <div className="mt-2.5">
          <div className="text-[11.5px] text-fg-3">Also looked closely at {crops.length === 1 ? 'one sign' : `${crops.length} signs`}</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {crops.map((c, i) => <CropThumb key={i} crop={c} result={result} />)}
          </div>
        </div>
      )}
      {a.guesses.length > 0 && (
        <ol className="mt-3 flex flex-col gap-1">
          {a.guesses.map((g, gi) => (
            <li key={gi}>
              <button
                type="button"
                onClick={() => mapHandle.current?.flyTo(g.lat, g.lon, g.radius_km)}
                className="flex w-full flex-col rounded-lg px-2 py-1.5 text-left text-[12.5px] hover:bg-surface"
                title="Show on map"
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="shrink-0 text-[11px] font-semibold text-fg-3 tnum">{gi + 1}.</span>
                    <span className="truncate">{[g.place, g.country].filter(Boolean).join(', ') || 'Unknown'}</span>
                  </span>
                  <span className="shrink-0 text-[11.5px] text-fg-3 tnum">
                    {pct(g.confidence)} · ±{Math.round(g.radius_km)} km
                  </span>
                </span>
                {g.why && <span className="mt-0.5 pl-[18px] text-[11.5px] leading-snug text-fg-2">{g.why}</span>}
              </button>
            </li>
          ))}
        </ol>
      )}
      {checklist.length > 0 && (
        <Disclosure label={`${name}'s checklist (${checklist.length})`} defaultOpen>
          <dl className="flex flex-col gap-2 text-[12.5px]">
            {checklist.map((c, i) => (
              <div key={i} className="leading-snug">
                <dt className="text-[10.5px] font-semibold uppercase tracking-wide text-fg-3">{c.label}</dt>
                <dd>
                  <span>{c.seen}</span>
                  {c.suggests && <span className="text-fg-2"> → {c.suggests}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </Disclosure>
      )}
      {ruledOut.length > 0 && (
        <Disclosure label={`Ruled out (${ruledOut.length})`}>
          <ul className="flex flex-col gap-1.5 text-[12.5px]">
            {ruledOut.map((r, i) => (
              <li key={i} className="leading-snug">
                <span className="font-medium">{r.place}</span>
                {r.why && <span className="text-fg-2">: {r.why}</span>}
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
      {checklist.length === 0 && a.clues.length > 0 && (
        <Disclosure label={`What ${name} saw (${a.clues.length})`}>
          <ul className="flex flex-col gap-1.5 text-[12.5px]">
            {a.clues.map((c, i) => (
              <li key={i} className="leading-snug">
                <span className="font-medium">{c.clue}</span>
                {c.suggests && <span className="text-fg-2"> → {c.suggests}</span>}
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
      <p className="mt-3 text-[11px] text-fg-3">{ANALYST_COMPANY[a.provider]} · answer is an opinion, not a measurement</p>
    </article>
  );
}

/** A sign the analyst was sent as a zoomed crop, cut from the photo with CSS. */
function CropThumb({ crop, result }: { crop: AnalystCrop; result: Result }) {
  const [x0, y0, x1, y1] = crop.box;
  const W = result.image.width || 1;
  const H = result.image.height || 1;
  const w = Math.max(1, x1 - x0);
  const h = Math.max(1, y1 - y0);
  const scale = Math.min(56 / h, 132 / w); // fit the crop in at most 132 x 56 px
  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-md border border-border bg-surface"
      style={{ width: Math.round(w * scale), height: Math.round(h * scale) }}
      title={crop.text ? `GeoLock read “${crop.text}” here` : 'Zoomed crop sent with the photo'}
    >
      {result.image_url && (
        <img
          src={assetUrl(result.image_url)}
          alt={crop.text ? `Close-up: ${crop.text}` : 'Close-up of a sign'}
          decoding="async"
          className="absolute max-w-none"
          style={{ width: W * scale, height: H * scale, left: -x0 * scale, top: -y0 * scale }}
        />
      )}
    </div>
  );
}

function friendlyError(e: string | null): string {
  if (!e) return 'Something went wrong. Try again.';
  if (/timed? ?out/i.test(e)) return `It took too long and was stopped. ${e}`;
  if (/not (logged|signed)|login|auth/i.test(e)) return `Your login isn't working. Sign in again and check. ${e}`;
  return e;
}

// --------------------------------------------------------------- details

function Details({ result }: { result: Result }) {
  const device = result.device ?? null;
  const t = result.timings;
  const [open, setOpen] = useState(false);
  return (
    <section>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-lg py-1.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-3 hover:text-fg-2"
      >
        Details
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {open && (
        <div className="mt-2 space-y-4 text-[12.5px] fade-in">
          {result.scene.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11.5px] text-fg-3">Scene</div>
              <div className="flex flex-wrap gap-1.5">
                {result.scene.slice(0, 12).map((s, i) => (
                  <span key={i} className="rounded-full border border-border px-2.5 py-0.5 text-[11.5px]" title={s.attribute}>
                    {s.value} <span className="text-fg-3 tnum">{pct(s.prob)}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.ocr.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11.5px] text-fg-3">Text found</div>
              <div className="flex flex-wrap gap-1.5">
                {result.ocr.slice(0, 14).map((l, i) => (
                  <span key={i} className="rounded-md bg-surface-3 px-1.5 py-0.5 font-mono text-[11px]">{l.text}</span>
                ))}
              </div>
            </div>
          )}
          <dl className="grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5">
            <dt className="text-fg-3">Camera</dt><dd>{result.exif?.camera ?? 'No camera data'}</dd>
            <dt className="text-fg-3">Taken</dt>
            <dd className="tnum">{result.exif?.datetime ? `${result.exif.datetime}${result.exif.utc_offset ? ` (UTC${result.exif.utc_offset})` : ''}` : 'No date in the photo'}</dd>
            <dt className="text-fg-3">GPS in photo</dt>
            <dd className="tnum">{result.exif?.gps ? plainCoords(result.exif.gps.lat, result.exif.gps.lon) : 'None'}</dd>
            {result.guesses.slice(0, 3).map((g, i) => g.km_from_exif != null && (
              <FragmentRow key={i} label={`Distance from #${i + 1}`} value={km(g.km_from_exif)} />
            ))}
            <dt className="text-fg-3">Size</dt><dd className="tnum">{result.image.width} × {result.image.height} px</dd>
            <dt className="text-fg-3">Processor</dt><dd>{deviceLabel(device)}{device ? ` (${device})` : ''}</dd>
            <dt className="text-fg-3">Timing</dt>
            <dd className="tnum">
              Vision {formatSeconds(t.clip_ms)}
              {t.ocr_ms != null ? ` · text ${formatSeconds(t.ocr_ms)}` : ''}
              {t.llm_ms != null ? ` · opinions ${formatSeconds(t.llm_ms)}` : ''}
              {t.total_ms != null ? ` · total ${formatSeconds(t.total_ms)}` : ''}
            </dd>
          </dl>
          <p className="text-[11px] text-fg-3">Stored {fullDate(result.created)}. Analysed on this computer.</p>
        </div>
      )}
    </section>
  );
}

function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-fg-3">{label}</dt>
      <dd className="tnum">{value}</dd>
    </>
  );
}

function Disclosure({ label, children, defaultOpen = false }: { label: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-3">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-1 text-[12px] font-medium text-fg-2 hover:text-fg">
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />} {label}
      </button>
      {open && <div className="mt-2 pl-1 fade-in">{children}</div>}
    </div>
  );
}
