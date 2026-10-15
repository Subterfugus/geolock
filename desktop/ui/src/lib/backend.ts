import { invoke } from '@tauri-apps/api/core';

export interface BackendInfo {
  url: string;
  token: string | null;
  dataDir: string | null;
  logFile: string | null;
}

/** True inside the Tauri shell (the webview injects this global). */
export const isTauri = (): boolean =>
  typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

let backend: BackendInfo | null = null;

/**
 * Where the Python engine listens. Inside the shell the port and token come from
 * the `backend_info` command; in a plain browser we use the dev server URL.
 * Throws while the shell has not started the backend yet, so callers can retry.
 */
export async function resolveBackend(): Promise<BackendInfo> {
  if (backend) return backend;
  if (isTauri()) {
    const info = await invoke<{ url: string; token: string; dataDir: string; logFile: string }>('backend_info');
    backend = { url: info.url, token: info.token, dataDir: info.dataDir, logFile: info.logFile };
  } else {
    const env = import.meta.env as Record<string, string | undefined>;
    backend = { url: env.VITE_BACKEND_URL || 'http://127.0.0.1:7861', token: null, dataDir: null, logFile: null };
  }
  return backend;
}

export function currentBackend(): BackendInfo | null {
  return backend;
}

/** Forgets the cached info so the next resolveBackend() asks the shell again. */
export function resetBackend(): void {
  backend = null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly network: boolean;
  constructor(message: string, status: number, network = false) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.network = network;
  }
}

/** Turns a FastAPI-style `{detail}` body (string or validation list) into one readable line. */
function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
      return d.map((e) => (e && typeof e === 'object' && 'msg' in e ? String((e as { msg: unknown }).msg) : String(e))).join('; ');
    }
  }
  return fallback;
}

export async function apiRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  opts: { json?: unknown; form?: FormData | URLSearchParams } = {},
): Promise<T> {
  const b = await resolveBackend();
  const headers: Record<string, string> = {};
  if (b.token) headers['X-GeoLock-Token'] = b.token;
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  let res: Response;
  try {
    res = await fetch(b.url + path, { method, headers, body });
  } catch {
    throw new ApiError("Can't reach GeoLock's engine. It may still be starting.", 0, true);
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) {
    throw new ApiError(detailOf(parsed, `Request failed (${res.status} ${res.statusText || ''})`.trim()), res.status);
  }
  return parsed as T;
}

/** URL for an <img>: the backend wants the token as a query parameter for images. */
export function assetUrl(path: string): string {
  const b = currentBackend();
  if (!b) return path;
  const sep = path.includes('?') ? '&' : '?';
  return b.token ? `${b.url}${path}${sep}t=${encodeURIComponent(b.token)}` : `${b.url}${path}`;
}

/** Map data is public, so it needs no token. */
export function dataUrl(path: string): string {
  return `${currentBackend()?.url ?? ''}${path}`;
}
