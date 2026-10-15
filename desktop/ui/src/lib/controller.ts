// Non-React logic: boot and polling, library, the upload queue, second opinions, settings.
// Components call these functions; they read state through the store.
import {
  cancelSetup, clearHistory, deleteResult, getHistory, getResult, getSetup, getSettings, getStatus,
  importModels, locatePhoto, putSettings, refreshAnalysts, rerunPhoto, startSetup, type LocateOptions,
} from './api';
import { ApiError, assetUrl, currentBackend, resolveBackend } from './backend';
import { errorText, guessTitle, km, pct, plural } from './format';
import { getState, patch, toast, update } from './store';
import { applyTheme, watchSystemTheme } from './theme';
import { pickPhotoFolder, pickPhotos } from './files';
import { saveFile, stem, toCsv, toJson, toKml, type ExportFormat } from './exporter';
import { mapHandle } from './map/mapController';
import type { HistorySummary, Provider, Result, Settings, Status } from './types';
import type { QueueItem } from './store';

const BOOT_TIMEOUT_MS = 60_000;
const bootStarted = Date.now();
let started = false;

const uid = () => Math.random().toString(36).slice(2, 10);

export function startServices(): void {
  if (started) return;
  started = true;
  watchSystemTheme(() => getState().settings?.theme);
  void statusLoop();
  void setupLoop();
}

// ------------------------------------------------------------- status / boot

async function statusLoop(): Promise<void> {
  let delay = 700;
  try {
    const status: Status = await getStatus();
    const before = getState();
    const becameReady = status.state === 'ready' && before.status?.state !== 'ready';
    patch({ reachable: true, bootTimedOut: false, connectionLost: false, status });
    if (status.state === 'needs_setup' || status.state === 'setting_up') patch({ setupSeen: true });
    if (becameReady) {
      if (before.setupSeen) toast('success', 'GeoLock is ready', 'Drop a photo anywhere to locate it.');
      if (!before.settings) void loadSettings();
      void loadLibrary();
      void drainQueue();
    }
    delay = status.state === 'ready' ? 4000 : 900;
  } catch {
    const s = getState();
    if (s.reachable) patch({ connectionLost: true });
    if (!s.reachable && Date.now() - bootStarted > BOOT_TIMEOUT_MS && !s.bootTimedOut) {
      try {
        const b = await resolveBackend();
        patch({ bootTimedOut: true, logFile: b.logFile, dataDir: b.dataDir });
      } catch {
        patch({ bootTimedOut: true });
      }
    }
    delay = 700;
  }
  setTimeout(() => void statusLoop(), delay);
}

async function setupLoop(): Promise<void> {
  let delay = 500;
  const s = getState();
  if (s.reachable && s.status && s.status.state !== 'ready') {
    try {
      patch({ setup: await getSetup() });
    } catch {
      /* the status loop reports connection problems */
    }
  } else if (s.status?.state === 'ready') {
    delay = 3000;
  }
  setTimeout(() => void setupLoop(), delay);
}

export async function loadSettings(): Promise<void> {
  try {
    const settings: Settings = await getSettings();
    const first = !getState().settings;
    patch({ settings, ...(first ? { mapStyle: settings.map_style } : {}) });
    applyTheme(settings.theme);
  } catch {
    /* defaults apply until the backend answers */
  }
}

// -------------------------------------------------------------------- setup

export async function beginSetup(): Promise<void> {
  try {
    await startSetup();
    patch({ setup: await getSetup() });
  } catch (e) {
    toast('error', "Couldn't start the download", errorText(e));
  }
}

export async function stopSetup(): Promise<void> {
  try {
    await cancelSetup();
    patch({ setup: await getSetup() });
    toast('info', 'Setup paused', 'The partial download is kept, so it resumes next time.');
  } catch (e) {
    toast('error', "Couldn't cancel", errorText(e));
  }
}

export async function importFromFolder(folder: string): Promise<boolean> {
  try {
    await importModels(folder);
    patch({ setup: await getSetup() });
    toast('success', 'Models imported');
    return true;
  } catch (e) {
    toast('error', "That folder isn't a GeoLock models folder", errorText(e));
    return false;
  }
}

// ------------------------------------------------------------------ library

export function upsertHistory(prev: HistorySummary[] | null, item: HistorySummary): HistorySummary[] {
  const list = prev ?? [];
  const i = list.findIndex((h) => h.id === item.id);
  if (i >= 0) return list.map((h, j) => (j === i ? item : h));
  return [item, ...list];
}

export function summarize(r: Result): HistorySummary {
  const top = r.guesses[0];
  const place = top?.place && top.place.km < 60 ? top.place.name : null;
  return {
    id: r.id,
    name: r.name,
    created: r.created,
    thumb_url: r.thumb_url,
    top: top
      ? {
          lat: top.lat,
          lon: top.lon,
          confidence: top.confidence,
          label: top.label,
          country: top.country,
          country_code: top.country_code,
          place,
          region: top.region,
        }
      : null,
    analysts: r.analysts.map((a) => a.provider),
    has_exif_gps: !!r.exif_gps,
    km_from_exif: top?.km_from_exif ?? null,
  };
}

export async function loadLibrary(): Promise<void> {
  try {
    const history = await getHistory();
    const s = getState();
    patch({ history });
    if (!s.selectedId && history.length) selectResult(history[0].id, false);
  } catch (e) {
    patch({ history: getState().history ?? [] });
    toast('error', "Couldn't load your library", errorText(e));
  }
}

/** The library rows as the search box leaves them. */
export function visibleHistory(s: { history: HistorySummary[] | null; search: string; libraryFilter?: 'all' | 'gps' }): HistorySummary[] {
  const all = (s.history ?? []).filter((h) => s.libraryFilter !== 'gps' || h.has_exif_gps);
  const q = s.search.trim().toLowerCase();
  if (!q) return all;
  return all.filter((h) => {
    const t = h.top;
    const hay = [h.name, t?.place, t?.region, t?.country].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(q);
  });
}

export function selectResult(id: string | null, byUser = true): void {
  const now = Date.now();
  if (id === null) {
    patch({ selectedId: null, selectedGuess: 0, ...(byUser ? { userPickedAt: now } : {}) });
    return;
  }
  const s = getState();
  patch({
    selectedId: id,
    selectedGuess: 0,
    ...(byUser ? { userPickedAt: now } : {}),
    lightboxOpen: false,
  });
  if (!s.results[id]) void fetchResult(id);
}

export function selectGuess(i: number): void {
  patch({ selectedGuess: i });
}

/** Keyboard move through the visible library. */
export function moveSelection(delta: number): void {
  const s = getState();
  const list = visibleHistory(s);
  if (!list.length) return;
  const idx = list.findIndex((h) => h.id === s.selectedId);
  const next = list[Math.min(list.length - 1, Math.max(0, (idx < 0 ? 0 : idx) + delta))];
  selectResult(next.id, true);
}

export async function fetchResult(id: string): Promise<Result | null> {
  try {
    const r = await getResult(id);
    update((s) => ({ results: { ...s.results, [id]: r } }));
    return r;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      update((s) => ({ history: (s.history ?? []).filter((h) => h.id !== id) }));
      toast('info', 'That photo is no longer in the library');
    } else {
      toast('error', "Couldn't open this photo", errorText(e));
    }
    return null;
  }
}

export async function removeResult(id: string): Promise<void> {
  const s = getState();
  const list = visibleHistory(s);
  const idx = list.findIndex((h) => h.id === id);
  const neighbour = idx >= 0 ? list[idx + 1] ?? list[idx - 1] ?? null : null;
  const name = s.history?.find((h) => h.id === id)?.name ?? 'Photo';
  try {
    await deleteResult(id);
  } catch (e) {
    toast('error', "Couldn't delete", errorText(e));
    return;
  }
  update((st) => {
    const results = { ...st.results };
    delete results[id];
    const { asking } = st;
    const nextAsking = { ...asking };
    delete nextAsking[id];
    return {
      history: (st.history ?? []).filter((h) => h.id !== id),
      results,
      asking: nextAsking,
      ...(st.selectedId === id
        ? { selectedId: neighbour?.id ?? null, selectedGuess: 0, lightboxOpen: false }
        : {}),
    };
  });
  toast('info', 'Removed from library', name);
}

export async function clearLibrary(): Promise<void> {
  try {
    const r = await clearHistory();
    patch({ history: [], results: {}, selectedId: null, selectedGuess: 0 });
    toast('success', `Cleared ${r.deleted} ${r.deleted === 1 ? 'photo' : 'photos'}`);
  } catch (e) {
    toast('error', "Couldn't clear the library", errorText(e));
  }
}

// ------------------------------------------------------------ queue / locate

export function currentLocateOptions(ask: Provider[] = []): LocateOptions {
  const set = getState().settings;
  return {
    ocr: set?.read_text ?? true,
    exifGps: set?.show_exif_gps ?? true,
    ask,
    shareLocal: set?.share_findings ?? true,
  };
}

export function enqueue(files: File[]): void {
  const photos = files.filter((f) => (f.type || '').startsWith('image/') || /\.(heic|heif|jpe?g|png|webp|gif|bmp|tiff?)$/i.test(f.name));
  const skipped = files.length - photos.length;
  if (!photos.length) {
    toast('error', 'That is not a photo', 'GeoLock reads JPEG, PNG, WebP, HEIC, TIFF and BMP files.');
    return;
  }
  if (skipped > 0) toast('info', `Skipped ${skipped} ${skipped === 1 ? 'file' : 'files'} that are not photos`);
  const items: QueueItem[] = photos.map((f) => ({
    id: uid(),
    name: f.name || 'Pasted image',
    file: f,
    thumb: f.type.startsWith('image/') && !/heic|heif/.test(f.type) ? URL.createObjectURL(f) : null,
    status: 'queued',
    error: null,
  }));
  update((s) => ({
    queue: [...s.queue, ...items],
    batch: s.batch
      ? { ...s.batch, total: s.batch.total + items.length }
      : { total: items.length, done: 0, failed: 0, ids: [] },
  }));
  void drainQueue();
}

/** Drops the photos still waiting; the one being located finishes. */
export function stopQueue(): void {
  const s = getState();
  const waiting = s.queue.filter((q) => q.status === 'queued');
  if (!waiting.length) return;
  waiting.forEach((q) => q.thumb && URL.revokeObjectURL(q.thumb));
  update((st) => ({
    queue: st.queue.filter((q) => q.status !== 'queued'),
    batch: st.batch ? { ...st.batch, total: st.batch.total - waiting.length } : null,
  }));
  toast('info', `Stopped. ${plural(waiting.length, 'photo')} not located`);
  finishBatchIfIdle();
}

/** When the queue has nothing left to do, sums up a multi-photo run once. */
function finishBatchIfIdle(): void {
  const s = getState();
  if (!s.batch || s.queue.some((q) => q.status === 'queued' || q.status === 'running')) return;
  const b = s.batch;
  patch({ batch: null });
  if (b.total < 2 || b.done === 0) return;
  const rows = (s.history ?? []).filter((h) => b.ids.includes(h.id));
  const stats = gpsStats(rows);
  const body = stats
    ? `${stats.n} of ${b.done} had their own GPS: median error ${km(stats.median)}, ${stats.within[1].count || 'none'} within 200 km.`
    : b.failed ? `${plural(b.failed, 'photo')} could not be read.` : undefined;
  toast('success', `Located ${plural(b.done, 'photo')}`, body);
}

export interface GpsStats {
  n: number;
  median: number;
  mean: number;
  within: { km: number; label: string; count: number; share: number }[];
}

/** Accuracy over the photos that carry their own GPS (the "ground truth"). */
export function gpsStats(rows: HistorySummary[]): GpsStats | null {
  const errs = rows.map((h) => h.km_from_exif).filter((x): x is number => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!errs.length) return null;
  const n = errs.length;
  const median = n % 2 ? errs[(n - 1) / 2] : (errs[n / 2 - 1] + errs[n / 2]) / 2;
  const bands = [[25, 'Street'], [200, 'City'], [750, 'Region'], [2500, 'Country']] as const;
  return {
    n,
    median,
    mean: errs.reduce((a, b) => a + b, 0) / n,
    within: bands.map(([k, label]) => {
      const count = errs.filter((e) => e <= k).length;
      return { km: k, label, count, share: count / n };
    }),
  };
}

export function retryQueued(id: string): void {
  update((s) => ({
    queue: s.queue.map((q) => (q.id === id ? { ...q, status: 'queued', error: null } : q)),
    batch: s.batch ?? { total: 1, done: 0, failed: 0, ids: [] },
  }));
  void drainQueue();
}

export function dismissQueued(id: string): void {
  update((s) => {
    const item = s.queue.find((q) => q.id === id);
    if (item?.thumb) URL.revokeObjectURL(item.thumb);
    return { queue: s.queue.filter((q) => q.id !== id) };
  });
}

let draining = false;

/** Locates queued photos one at a time, as the backend expects. */
async function drainQueue(): Promise<void> {
  if (draining) return;
  draining = true;
  try {
    for (;;) {
      const s = getState();
      if (s.status?.state !== 'ready') break;
      const next = s.queue.find((q) => q.status === 'queued');
      if (!next) break;
      update((st) => ({ queue: st.queue.map((q) => (q.id === next.id ? { ...q, status: 'running' } : q)) }));
      const pickedBefore = getState().userPickedAt;
      try {
        const r = await locatePhoto(next.file, next.name, currentLocateOptions());
        update((st) => ({
          results: { ...st.results, [r.id]: r },
          history: upsertHistory(st.history, summarize(r)),
          queue: st.queue.filter((q) => q.id !== next.id),
          batch: st.batch ? { ...st.batch, done: st.batch.done + 1, ids: [...st.batch.ids, r.id] } : null,
        }));
        if (next.thumb) URL.revokeObjectURL(next.thumb);
        // Only jump to the new photo if the user has not picked something else meanwhile.
        if (getState().userPickedAt <= pickedBefore) selectResult(r.id, false);
        void refreshLibraryQuietly();
      } catch (e) {
        update((st) => ({
          queue: st.queue.map((q) => (q.id === next.id ? { ...q, status: 'error', error: errorText(e) } : q)),
          batch: st.batch ? { ...st.batch, failed: st.batch.failed + 1 } : null,
        }));
        if (e instanceof ApiError && e.network) break;
      }
    }
  } finally {
    draining = false;
    finishBatchIfIdle();
  }
}

async function refreshLibraryQuietly(): Promise<void> {
  try {
    const history = await getHistory();
    update((s) => {
      // Keep session-only photos (history turned off) that the backend does not return.
      const extra = (s.history ?? []).filter((h) => !history.some((x) => x.id === h.id) && s.results[h.id]);
      return { history: [...history, ...extra] };
    });
  } catch {
    /* the next refresh will catch up */
  }
}

// ------------------------------------------------------ re-analyse / second opinion

export async function reanalyse(id: string): Promise<void> {
  const name = getState().history?.find((h) => h.id === id)?.name ?? 'Photo';
  try {
    const r = await rerunPhoto(id, currentLocateOptions());
    update((s) => ({ results: { ...s.results, [id]: r }, history: upsertHistory(s.history, summarize(r)) }));
    toast('success', 'Re-analysed', name);
  } catch (e) {
    toast('error', "Couldn't re-analyse", errorText(e));
  }
}

/** Only ever called from an explicit click on "Ask Claude" / "Ask ChatGPT". */
export async function askAnalyst(id: string, provider: Provider): Promise<void> {
  if (getState().asking[id]) return;
  const label = provider === 'claude' ? 'Claude' : 'ChatGPT';
  update((s) => ({ asking: { ...s.asking, [id]: provider } }));
  try {
    const r = await rerunPhoto(id, currentLocateOptions([provider]));
    update((s) => ({ results: { ...s.results, [id]: r }, history: upsertHistory(s.history, summarize(r)) }));
    const a = r.analysts.find((x) => x.provider === provider);
    if (a && !a.ok) toast('error', `${label} didn't answer`, a.error ?? undefined);
    else toast('success', `${label} has answered`);
  } catch (e) {
    toast('error', `Couldn't ask ${label}`, errorText(e));
  } finally {
    update((s) => {
      const asking = { ...s.asking };
      delete asking[id];
      return { asking };
    });
  }
}

// ---------------------------------------------------------------- settings

export async function updateSettings(p: Partial<Settings>): Promise<void> {
  const prev = getState().settings;
  if (!prev) return;
  patch({ settings: { ...prev, ...p } });
  if (p.theme) applyTheme(p.theme);
  try {
    const saved = await putSettings(p);
    patch({ settings: saved });
    if (p.device) toast('info', 'Reloading models…', 'This takes a few seconds.');
  } catch (e) {
    patch({ settings: prev });
    if (p.theme) applyTheme(prev.theme);
    toast('error', "Couldn't save that setting", errorText(e));
  }
}

export async function recheckAnalysts(): Promise<void> {
  try {
    const res = await refreshAnalysts();
    const s = getState().status;
    if (s) patch({ status: { ...s, analysts: { ...s.analysts, ...res } } });
    toast('info', 'Checked your logins');
  } catch (e) {
    toast('error', "Couldn't check again", errorText(e));
  }
}

/** Browser dev mode has no file manager to open, so the path is copied instead. */
export function copyDataFolderPath(): void {
  const dir = currentBackend()?.dataDir ?? getState().dataDir ?? getState().status?.data_dir ?? '';
  void navigator.clipboard?.writeText(dir).catch(() => undefined);
  toast('info', 'Data folder path copied', dir);
}

/** Opens the photo picker and queues whatever was chosen. */
export async function addPhotos(): Promise<void> {
  try {
    const files = await pickPhotos();
    if (files.length) enqueue(files);
  } catch (e) {
    toast('error', "Couldn't open the photos", errorText(e));
  }
}

/** Opens a folder picker and queues every photo in it, subfolders included. */
export async function addFolder(): Promise<void> {
  try {
    const files = await pickPhotoFolder();
    if (!files) return;
    if (!files.length) {
      toast('info', 'No photos in that folder', 'GeoLock reads JPEG, PNG, WebP, HEIC, TIFF and BMP files.');
      return;
    }
    enqueue(files);
    if (files.length > 1) toast('info', `Locating ${plural(files.length, 'photo')}`, 'They are done one at a time. You can keep browsing meanwhile.');
  } catch (e) {
    toast('error', "Couldn't open the folder", errorText(e));
  }
}

// ------------------------------------------------------------------ export

const today = () => new Date().toISOString().slice(0, 10);

async function withExport(what: string, fn: () => Promise<string | null>): Promise<void> {
  if (getState().exporting) return;
  patch({ exporting: true });
  try {
    const where = await fn();
    if (where) toast('success', `${what} exported`, where);
  } catch (e) {
    toast('error', `Couldn't export ${what.toLowerCase()}`, errorText(e));
  } finally {
    patch({ exporting: false });
  }
}

async function loadImage(url: string): Promise<ImageBitmap | null> {
  try {
    const res = await fetch(assetUrl(url));
    if (!res.ok) return null;
    return await createImageBitmap(await res.blob());
  } catch {
    return null;
  }
}

/** Exports one photo's result. PNG is the map as it is on screen, with the pins and a caption. */
export function exportResult(id: string, format: ExportFormat): Promise<void> {
  return withExport(format === 'png' ? 'Map image' : 'Result', async () => {
    const r = getState().results[id] ?? (await fetchResult(id));
    if (!r) return null;
    const base = `${stem(r.name)}-geolock`;
    if (format === 'json') return saveFile(`${base}.json`, format, toJson([r]));
    if (format === 'csv') return saveFile(`${base}.csv`, format, toCsv([r]));
    if (format === 'kml') return saveFile(`${base}.kml`, format, toKml([r], `GeoLock: ${r.name}`));
    const map = mapHandle.current;
    if (!map || getState().selectedId !== id) throw new Error('Open the photo on the map first.');
    const top = r.guesses[getState().selectedGuess] ?? r.guesses[0];
    const lines: string[] = [];
    if (top) lines.push(`Best guess: ${guessTitle(top).main}${top.country ? `, ${top.country}` : ''} · ${pct(top.confidence)} · within ±${Math.round(top.radius_km)} km`);
    if (top?.km_from_exif != null) lines.push(`The photo's own GPS (★) is ${km(top.km_from_exif)} from this guess.`);
    const blob = await map.snapshot({ title: r.name, lines }, await loadImage(r.image_url));
    return saveFile(`${base}-map.png`, 'png', blob);
  });
}

/** Exports the photos the library shows right now (search and filter applied). */
export function exportLibrary(format: Exclude<ExportFormat, 'png'>): Promise<void> {
  return withExport('Library', async () => {
    const rows = visibleHistory(getState());
    if (!rows.length) throw new Error('There are no photos to export.');
    const results: Result[] = [];
    for (const h of rows) {
      const r = getState().results[h.id] ?? (await getResult(h.id).catch(() => null));
      if (r) results.push(r);
    }
    const base = `geolock-${plural(results.length, 'photo').replace(' ', '-')}-${today()}`;
    if (format === 'json') return saveFile(`${base}.json`, format, toJson(results));
    if (format === 'csv') return saveFile(`${base}.csv`, format, toCsv(results));
    return saveFile(`${base}.kml`, format, toKml(results, `GeoLock: ${plural(results.length, 'photo')}`));
  });
}

/** Asks before deleting one photo. Used by the menu, the inspector and the Delete key. */
export function askDelete(id: string): void {
  const name = getState().history?.find((h) => h.id === id)?.name ?? 'this photo';
  patch({
    confirm: {
      title: 'Delete this photo?',
      body: `“${name}” and its result are removed from this computer. This can't be undone.`,
      confirmLabel: 'Delete',
      danger: true,
      onConfirm: () => void removeResult(id),
    },
  });
}
