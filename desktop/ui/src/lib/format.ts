import type { ConfidenceLabel, Guess, HistorySummary, Result } from './types';

const numberFmt = new Intl.NumberFormat('en-US');

/** 0.46 -> "46%"; tiny values read "<1%" and near-certain values "99%". */
export function pct(p: number): string {
  if (!Number.isFinite(p)) return '–';
  if (p >= 0.995) return '99%';
  if (p < 0.01) return '<1%';
  return `${Math.round(p * 100)}%`;
}

/** Kilometres with grouping: 0.4 -> "<1 km", 3.44 -> "3.4 km", 1240 -> "1,240 km". */
export function km(n: number): string {
  if (!Number.isFinite(n)) return '–';
  if (n < 1) return '<1 km';
  if (n < 10) return `${n.toFixed(1)} km`;
  return `${numberFmt.format(Math.round(n))} km`;
}

/** Radius form used for uncertainty: "±38 km". */
export const radiusText = (n: number): string => `±${km(n).replace(' km', '')} km`;

export const confidenceName = (l: ConfidenceLabel): string =>
  l === 'high' ? 'High' : l === 'medium' ? 'Medium' : 'Low';

/** ISO country code to a flag emoji (regional indicator pair). Empty when unknown. */
export function flag(cc: string | null | undefined): string {
  if (!cc || cc.length !== 2 || !/^[A-Za-z]{2}$/.test(cc)) return '';
  const base = 0x1f1e6;
  return String.fromCodePoint(...cc.toUpperCase().split('').map((c) => base + c.charCodeAt(0) - 65));
}

export function coordText(lat: number, lon: number): string {
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  return `${Math.abs(lat).toFixed(4)}° ${ns}, ${Math.abs(lon).toFixed(4)}° ${ew}`;
}

export const plainCoords = (lat: number, lon: number): string => `${lat.toFixed(5)}, ${lon.toFixed(5)}`;

/** "Paris, Île-de-France" style title; the place only when it is close to the guess. */
export function guessTitle(g: Pick<Guess, 'place' | 'region' | 'country'>): { main: string; sub: string } {
  const parts: string[] = [];
  if (g.place && g.place.km < 60) parts.push(g.place.name);
  if (g.region && g.region !== parts[0]) parts.push(g.region);
  return {
    main: parts.join(', ') || g.country || 'Unknown place',
    sub: parts.length ? g.country ?? '' : '',
  };
}

export function summaryTitle(h: HistorySummary): string {
  if (!h.top) return 'No guess';
  const parts = [h.top.place, h.top.region].filter(Boolean) as string[];
  const uniq = parts.filter((p, i) => parts.indexOf(p) === i);
  return uniq.join(', ') || h.top.country || 'Unknown place';
}

export function formatMB(mb: number | null | undefined): string {
  if (mb == null || !Number.isFinite(mb)) return '–';
  if (mb >= 1024) return `${(mb / 1024).toFixed(mb >= 10240 ? 0 : 1)} GB`;
  return `${Math.round(mb)} MB`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '';
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  const m = Math.round(seconds / 60);
  return `${m} min`;
}

export function formatSeconds(ms: number | null | undefined): string {
  if (ms == null) return '–';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

/** Library grouping and labels: "Today", "Yesterday", or a short date. */
export function dayLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (dayKey(d) === dayKey(now)) return 'Today';
  if (dayKey(d) === dayKey(yesterday)) return 'Yesterday';
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' });
}

export function timeLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export function fullDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function resultSummaryLine(r: Result): string {
  const top = r.guesses[0];
  return top ? `${guessTitle(top).main}` : 'No guess';
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

/** The name shown for the processor: "Arc GPU", "NPU" or "CPU". */
export function deviceLabel(device: string | null | undefined): string {
  if (device === 'GPU') return 'Arc GPU';
  if (device === 'NPU') return 'NPU';
  if (device === 'CPU') return 'CPU';
  return 'processor';
}

export const ANALYST_NAME: Record<'claude' | 'chatgpt', string> = { claude: 'Claude', chatgpt: 'ChatGPT' };
export const ANALYST_COMPANY: Record<'claude' | 'chatgpt', string> = { claude: 'Anthropic', chatgpt: 'OpenAI' };
