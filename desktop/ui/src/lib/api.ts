import { apiRequest } from './backend';
import type {
  Benchmark, HistorySummary, Provider, Result, Settings, SetupInfo, Status, AnalystStatus,
  AnalystProgress, ModelOptions, UpdateInfo,
} from './types';

export const getStatus = () => apiRequest<Status>('GET', '/api/status');
export const getSetup = () => apiRequest<SetupInfo>('GET', '/api/setup');
export const startSetup = () => apiRequest<SetupInfo>('POST', '/api/setup/start');
export const cancelSetup = () => apiRequest<SetupInfo>('POST', '/api/setup/cancel');
export const importModels = (folder: string) =>
  apiRequest<SetupInfo>('POST', '/api/setup/import', { json: { folder } });

export const getSettings = () => apiRequest<Settings>('GET', '/api/settings');
export const putSettings = (patch: Partial<Settings>) =>
  apiRequest<Settings>('PUT', '/api/settings', { json: patch });
export const refreshAnalysts = () =>
  apiRequest<Record<Provider, AnalystStatus>>('POST', '/api/analysts/refresh');

export const getAnalystModels = (refresh = false) =>
  apiRequest<ModelOptions>('GET', `/api/analysts/models${refresh ? '?refresh=true' : ''}`);
export const getAnalystProgress = () => apiRequest<AnalystProgress>('GET', '/api/analysts/progress');
export const stopAnalysts = () => apiRequest<{ stopped: number }>('POST', '/api/analysts/stop');

export const getBenchmark = () => apiRequest<Benchmark>('GET', '/api/diagnostics/benchmark');
export const runBenchmark = () => apiRequest<Benchmark>('POST', '/api/diagnostics/benchmark');

export const getUpdate = () => apiRequest<UpdateInfo>('GET', '/api/update');
export const checkUpdate = () => apiRequest<UpdateInfo>('POST', '/api/update/check');
export const downloadUpdate = () => apiRequest<UpdateInfo>('POST', '/api/update/download');
export const cancelUpdate = () => apiRequest<UpdateInfo>('POST', '/api/update/cancel');

export const getHistory = () => apiRequest<HistorySummary[]>('GET', '/api/history');
export const getResult = (id: string) => apiRequest<Result>('GET', `/api/history/${encodeURIComponent(id)}`);
export const deleteResult = (id: string) =>
  apiRequest<{ ok: boolean }>('DELETE', `/api/history/${encodeURIComponent(id)}`);
export const clearHistory = () =>
  apiRequest<{ ok: boolean; deleted: number }>('DELETE', '/api/history');

export interface LocateOptions {
  ocr: boolean;
  exifGps: boolean;
  ask: Provider[];
  shareLocal: boolean;
}

function optionsForm(o: LocateOptions, fd: FormData | URLSearchParams): void {
  fd.append('ocr', String(o.ocr));
  fd.append('exif_gps', String(o.exifGps));
  fd.append('ask', o.ask.join(','));
  fd.append('share_local', String(o.shareLocal));
}

export function locatePhoto(file: File, name: string, o: LocateOptions): Promise<Result> {
  const fd = new FormData();
  fd.append('file', file, name);
  fd.append('name', name);
  optionsForm(o, fd);
  return apiRequest<Result>('POST', '/api/locate', { form: fd });
}

/** Re-runs a stored photo; `ask` set means the user clicked a second-opinion button. */
export function rerunPhoto(id: string, o: LocateOptions): Promise<Result> {
  const fd = new URLSearchParams();
  optionsForm(o, fd);
  return apiRequest<Result>('POST', `/api/history/${encodeURIComponent(id)}/rerun`, { form: fd });
}
