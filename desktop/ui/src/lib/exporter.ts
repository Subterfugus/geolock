// Export a result or the library: JSON, CSV, KML (Google Earth) and a PNG of the map.
// Files are built here; the backend only writes the bytes to the path the user picked.
import { save } from '@tauri-apps/plugin-dialog';
import { apiRequest, isTauri } from './backend';
import { guessTitle } from './format';
import { haversineKm } from './geo';
import type { Result } from './types';

export type ExportFormat = 'json' | 'csv' | 'kml' | 'png';

const MIME: Record<ExportFormat, string> = {
  json: 'application/json',
  csv: 'text/csv',
  kml: 'application/vnd.google-earth.kml+xml',
  png: 'image/png',
};

const FILTER_NAME: Record<ExportFormat, string> = {
  json: 'JSON', csv: 'CSV (Excel)', kml: 'KML (Google Earth)', png: 'PNG image',
};

/** "IMG_2041.jpg" -> "IMG_2041"; safe for a Windows file name. */
export function stem(name: string): string {
  const base = name.replace(/\.[a-z0-9]{2,5}$/i, '');
  return base.replace(/[<>:"/\\|?*\u0000-\u001f]+/g, '_').trim() || 'photo';
}

/** The photo's own GPS, whether or not the user chose to show it on the map. */
export const truthOf = (r: Result) => r.exif_gps ?? r.exif?.gps ?? null;

/** Distance from the photo's GPS to each guess (null without GPS). */
export function errorsKm(r: Result): (number | null)[] {
  const t = truthOf(r);
  return r.guesses.map((g) => (t ? g.km_from_exif ?? haversineKm(g.lat, g.lon, t.lat, t.lon) : null));
}

// ------------------------------------------------------------------ JSON

export function toJson(results: Result[]): string {
  const strip = (r: Result) => {
    // Image URLs only work inside this app; the heat map is large and not useful elsewhere.
    const { image_url: _i, thumb_url: _t, heat: _h, ...rest } = r;
    return rest;
  };
  const body = results.length === 1 ? strip(results[0]) : results.map(strip);
  return JSON.stringify(body, null, 2);
}

// ------------------------------------------------------------------- CSV

const CSV_HEAD = [
  'name', 'analysed_utc', 'rank', 'lat', 'lon', 'place', 'region', 'country', 'country_code',
  'confidence', 'confidence_label', 'radius_km', 'photo_gps_lat', 'photo_gps_lon', 'km_from_photo_gps',
  'claude_lat', 'claude_lon', 'claude_place', 'chatgpt_lat', 'chatgpt_lon', 'chatgpt_place', 'camera', 'taken',
];

function cell(v: unknown): string {
  if (v == null) return '';
  const s = typeof v === 'number' ? String(+v.toFixed(6)) : String(v);
  // Quote anything with a separator, and defuse leading = + - @ so Excel does not run it as a formula.
  const safe = /^[=+\-@]/.test(s) && typeof v !== 'number' ? `'${s}` : s;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** One row per guess (rank 1 is the best guess), so a spreadsheet can filter on rank = 1. */
export function toCsv(results: Result[]): string {
  const rows = [CSV_HEAD.join(',')];
  for (const r of results) {
    const t = truthOf(r);
    const errs = errorsKm(r);
    const an = (p: string) => r.analysts.find((a) => a.provider === p && a.ok)?.guesses[0] ?? null;
    const claude = an('claude');
    const chatgpt = an('chatgpt');
    const guesses = r.guesses.length ? r.guesses : [null];
    guesses.forEach((g, i) => {
      rows.push([
        r.name, r.created, g ? i + 1 : '', g?.lat, g?.lon, g?.place && g.place.km < 60 ? g.place.name : '',
        g?.region, g?.country, g?.country_code, g?.confidence, g?.label, g?.radius_km,
        t?.lat, t?.lon, errs[i] != null ? +(errs[i] as number).toFixed(1) : '',
        claude?.lat, claude?.lon, claude?.place, chatgpt?.lat, chatgpt?.lon, chatgpt?.place,
        r.exif?.camera, r.exif?.datetime,
      ].map(cell).join(','));
    });
  }
  // A byte-order mark so Excel reads accents (Île-de-France) as UTF-8.
  return '﻿' + rows.join('\r\n') + '\r\n';
}

// ------------------------------------------------------------------- KML

const esc = (s: unknown) => String(s ?? '').replace(/[<>&'"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[c] as string));
const coord = (lat: number, lon: number) => `${+lon.toFixed(6)},${+lat.toFixed(6)},0`;

function circleRing(lat: number, lon: number, km: number): string {
  const pts: string[] = [];
  const R = 6371.0088;
  const d = km / R;
  const φ1 = (lat * Math.PI) / 180;
  const λ1 = (lon * Math.PI) / 180;
  for (let i = 0; i <= 72; i++) {
    const b = (i / 72) * 2 * Math.PI;
    const φ2 = Math.asin(Math.sin(φ1) * Math.cos(d) + Math.cos(φ1) * Math.sin(d) * Math.cos(b));
    const λ2 = λ1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(φ1), Math.cos(d) - Math.sin(φ1) * Math.sin(φ2));
    pts.push(coord((φ2 * 180) / Math.PI, ((((λ2 * 180) / Math.PI) + 540) % 360) - 180));
  }
  return pts.join(' ');
}

export function toKml(results: Result[], title: string): string {
  const folders = results.map((r) => {
    const t = truthOf(r);
    const errs = errorsKm(r);
    const marks = r.guesses.map((g, i) => {
      const name = `#${i + 1} ${guessTitle(g).main}`;
      const desc = [
        `Confidence ${Math.round(g.confidence * 100)}% (${g.label}), likely within ${Math.round(g.radius_km)} km.`,
        g.country ? `Country: ${g.country}` : '',
        errs[i] != null ? `${Math.round(errs[i] as number)} km from the photo's own GPS.` : '',
        ...g.why.map((w) => `${w.effect > 0 ? '+' : w.effect < 0 ? '−' : '·'} ${w.text}`),
      ].filter(Boolean).join('\n');
      return `
      <Placemark><name>${esc(name)}</name><styleUrl>#${i === 0 ? 'best' : 'guess'}</styleUrl>
        <description>${esc(desc)}</description>
        <Point><coordinates>${coord(g.lat, g.lon)}</coordinates></Point></Placemark>
      <Placemark><name>${esc(`#${i + 1} uncertainty`)}</name><styleUrl>#area</styleUrl>
        <Polygon><outerBoundaryIs><LinearRing><coordinates>${circleRing(g.lat, g.lon, g.radius_km)}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>`;
    });
    const analysts = r.analysts.filter((a) => a.ok).flatMap((a) => a.guesses.map((g, gi) => `
      <Placemark><name>${esc(`${a.name} #${gi + 1}: ${[g.place, g.country].filter(Boolean).join(', ')}`)}</name><styleUrl>#analyst</styleUrl>
        <description>${esc(a.reasoning)}</description>
        <Point><coordinates>${coord(g.lat, g.lon)}</coordinates></Point></Placemark>`));
    const truth = t ? `
      <Placemark><name>Photo's own GPS</name><styleUrl>#truth</styleUrl>
        <description>From the photo's EXIF data. Never used for the guess.</description>
        <Point><coordinates>${coord(t.lat, t.lon)}</coordinates></Point></Placemark>` : '';
    return `
    <Folder><name>${esc(r.name)}</name><description>${esc(`Analysed ${r.created}`)}</description>${marks.join('')}${analysts.join('')}${truth}
    </Folder>`;
  });
  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>${esc(title)}</name>
    <Style id="best"><IconStyle><color>ffeb6325</color><scale>1.3</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/1.png</href></Icon></IconStyle></Style>
    <Style id="guess"><IconStyle><color>ffc7a38e</color><scale>0.9</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/wht-blank.png</href></Icon></IconStyle></Style>
    <Style id="analyst"><IconStyle><scale>0.9</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/purple-diamond.png</href></Icon></IconStyle></Style>
    <Style id="truth"><IconStyle><scale>1.1</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/ylw-stars.png</href></Icon></IconStyle></Style>
    <Style id="area"><LineStyle><color>aaeb6325</color><width>1.5</width></LineStyle><PolyStyle><color>22eb6325</color></PolyStyle></Style>${folders.join('')}
  </Document>
</kml>
`;
}

// ------------------------------------------------------------------ saving

/**
 * Asks where to save and writes the file. In the desktop app the native Save dialog picks a
 * path and the backend writes it; in a plain browser (dev mode) the file is downloaded.
 * Returns the saved path (or the file name for a download), or null when cancelled.
 */
export async function saveFile(fileName: string, format: ExportFormat, data: Blob | string): Promise<string | null> {
  const blob = typeof data === 'string' ? new Blob([data], { type: MIME[format] }) : data;
  if (!isTauri()) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    return fileName;
  }
  const path = await save({
    title: 'Export',
    defaultPath: fileName,
    filters: [{ name: FILTER_NAME[format], extensions: [format] }],
  });
  if (!path) return null;
  const fd = new FormData();
  fd.append('path', path);
  fd.append('file', blob, fileName);
  const res = await apiRequest<{ path: string; bytes: number }>('POST', '/api/save', { form: fd });
  return res.path;
}
