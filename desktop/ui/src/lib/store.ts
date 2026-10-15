import { useSyncExternalStore } from 'react';
import type {
  AnalystProgress, HistorySummary, MapStyleKind, ModelOptions, Provider, Result, Settings, SetupInfo, Status,
  UpdateInfo,
} from './types';

export interface QueueItem {
  id: string;
  name: string;
  /** Kept so a failed item can be retried. */
  file: File;
  thumb: string | null;
  status: 'queued' | 'running' | 'error';
  error: string | null;
}

export interface Toast {
  id: number;
  kind: 'success' | 'error' | 'info';
  title: string;
  body?: string;
}

export interface ConfirmRequest {
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
}

export interface AppState {
  /** The backend answered /api/status at least once. */
  reachable: boolean;
  bootTimedOut: boolean;
  logFile: string | null;
  dataDir: string | null;
  /** The last status poll failed after the backend had been reachable. */
  connectionLost: boolean;
  status: Status | null;
  setup: SetupInfo | null;
  /** Setup was seen on this run, so the "loading models" step belongs to the onboarding card. */
  setupSeen: boolean;
  settings: Settings | null;
  themeResolved: 'light' | 'dark';
  mapStyle: MapStyleKind;
  history: HistorySummary[] | null;
  results: Record<string, Result>;
  selectedId: string | null;
  selectedGuess: number;
  /** When the user last picked a photo by hand; auto-select after a queued job yields to it. */
  userPickedAt: number;
  queue: QueueItem[];
  /** Progress of the current run of queued photos; null when the queue is idle. */
  batch: { total: number; done: number; failed: number; ids: string[] } | null;
  asking: Record<string, Provider | undefined>;
  /** When the current ask started (ms), so progress from an earlier ask is ignored. */
  askStartedAt: number;
  /** Live progress of the analyst being asked, polled while it works. */
  analystProgress: AnalystProgress | null;
  /** Models and effort levels the installed CLIs accept; null until loaded. */
  models: ModelOptions | null;
  search: string;
  /** Library filter: every photo, or only those with their own GPS. */
  libraryFilter: 'all' | 'gps';
  /** An export is being written. */
  exporting: boolean;
  sidebarOpen: boolean;
  inspectorOpen: boolean;
  settingsOpen: boolean;
  shortcutsOpen: boolean;
  lightboxOpen: boolean;
  showTextBoxes: boolean;
  dropActive: boolean;
  toasts: Toast[];
  confirm: ConfirmRequest | null;
  /** The newest release and its download; null until the first check. */
  appUpdate: UpdateInfo | null;
  updateOpen: boolean;
}

const narrow = typeof window !== 'undefined' && window.innerWidth < 1180;

let state: AppState = {
  reachable: false,
  bootTimedOut: false,
  logFile: null,
  dataDir: null,
  connectionLost: false,
  status: null,
  setup: null,
  setupSeen: false,
  settings: null,
  themeResolved: typeof document !== 'undefined' && document.documentElement.dataset.theme === 'light' ? 'light' : 'dark',
  mapStyle: 'streets',
  history: null,
  results: {},
  selectedId: null,
  selectedGuess: 0,
  userPickedAt: 0,
  queue: [],
  batch: null,
  asking: {},
  askStartedAt: 0,
  analystProgress: null,
  models: null,
  search: '',
  libraryFilter: 'all',
  exporting: false,
  sidebarOpen: !narrow,
  inspectorOpen: true,
  settingsOpen: false,
  shortcutsOpen: false,
  lightboxOpen: false,
  showTextBoxes: false,
  dropActive: false,
  toasts: [],
  confirm: null,
  appUpdate: null,
  updateOpen: false,
};

const listeners = new Set<() => void>();

export const getState = (): AppState => state;

export function patch(p: Partial<AppState>): void {
  state = { ...state, ...p };
  listeners.forEach((l) => l());
}

export function update(fn: (s: AppState) => Partial<AppState>): void {
  patch(fn(state));
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Subscribe a component to a slice of the store. Selectors must return stable values. */
export function useStore<T>(selector: (s: AppState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(state), () => selector(state));
}

let toastSeq = 1;
export function toast(kind: Toast['kind'], title: string, body?: string): void {
  const id = toastSeq++;
  update((s) => ({ toasts: [...s.toasts.slice(-3), { id, kind, title, body }] }));
  const ms = kind === 'error' ? 7000 : 3800;
  setTimeout(() => dismissToast(id), ms);
}

export function dismissToast(id: number): void {
  update((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
}
