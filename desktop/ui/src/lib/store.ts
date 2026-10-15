import { useSyncExternalStore } from 'react';
import type {
  HistorySummary, MapStyleKind, Provider, Result, Settings, SetupInfo, Status, ThemeMode,
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
  asking: Record<string, Provider | undefined>;
  search: string;
  sidebarOpen: boolean;
  inspectorOpen: boolean;
  settingsOpen: boolean;
  shortcutsOpen: boolean;
  lightboxOpen: boolean;
  showTextBoxes: boolean;
  dropActive: boolean;
  toasts: Toast[];
  confirm: ConfirmRequest | null;
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
  themeResolved: 'dark',
  mapStyle: 'offline',
  history: null,
  results: {},
  selectedId: null,
  selectedGuess: 0,
  userPickedAt: 0,
  queue: [],
  asking: {},
  search: '',
  sidebarOpen: !narrow,
  inspectorOpen: true,
  settingsOpen: false,
  shortcutsOpen: false,
  lightboxOpen: false,
  showTextBoxes: false,
  dropActive: false,
  toasts: [],
  confirm: null,
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
