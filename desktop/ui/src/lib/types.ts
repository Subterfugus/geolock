// Shapes of the GeoLock backend contract (see desktop/API.md).

export type Provider = 'claude' | 'chatgpt';
export type DeviceName = 'GPU' | 'NPU' | 'CPU';
export type ConfidenceLabel = 'high' | 'medium' | 'low';
export type MapStyleKind = 'offline' | 'streets' | 'satellite';
export type ThemeMode = 'system' | 'light' | 'dark';

export interface AnalystStatus {
  available: boolean;
  via: string | null;
  detail: string;
}

export interface Status {
  state: 'needs_setup' | 'setting_up' | 'loading' | 'ready' | 'error';
  error: string | null;
  version: string;
  device: DeviceName | null;
  device_name?: string | null;
  available_devices: DeviceName[];
  analysts: Partial<Record<Provider, AnalystStatus>>;
  data_dir: string;
  models_dir: string;
}

export type StepState = 'pending' | 'running' | 'done' | 'error';

export interface SetupStep {
  id: string;
  label: string;
  state: StepState;
}

export interface SetupProgress {
  step: string;
  fraction: number | null;
  done_mb: number | null;
  total_mb: number | null;
  speed_mbps: number | null;
  eta_s: number | null;
  message: string;
}

export interface SetupInfo {
  ready: boolean;
  running: boolean;
  download_mb: number;
  disk_needed_mb: number;
  free_disk_mb: number;
  source: string;
  steps: SetupStep[];
  progress: SetupProgress | null;
  error: string | null;
}

export interface Settings {
  device: 'AUTO' | DeviceName;
  read_text: boolean;
  show_exif_gps: boolean;
  share_findings: boolean;
  keep_history: boolean;
  theme: ThemeMode;
  map_style: MapStyleKind;
}

export interface Place {
  name: string;
  admin1?: string | null;
  cc?: string | null;
  km: number;
}

export interface Why {
  effect: -1 | 0 | 1;
  text: string;
}

export interface Guess {
  lat: number;
  lon: number;
  confidence: number;
  label: ConfidenceLabel;
  radius_km: number;
  visual_mass?: number;
  country_code: string | null;
  country: string | null;
  continent?: string | null;
  region: string | null;
  place: Place | null;
  km_from_exif?: number | null;
  why: Why[];
}

export interface CountryOdds {
  code: string;
  name: string;
  prob: number;
  clip_prob?: number;
}

export type ClueKind =
  | 'ocr' | 'language' | 'script' | 'domain' | 'phone' | 'currency' | 'units'
  | 'scene' | 'timezone' | 'exif' | 'claude' | 'chatgpt' | 'vlm';

export interface Clue {
  kind: ClueKind | string;
  title: string;
  detail?: string | null;
  strength: number;
  countries?: { code: string; name: string; weight?: number }[];
  n_countries?: number;
}

export interface ScenePrediction {
  attribute: string;
  value: string;
  prob: number;
}

export interface OcrLine {
  text: string;
  score: number;
  box: [[number, number], [number, number], [number, number], [number, number]];
  model?: string;
}

export interface AnalystGuess {
  place: string | null;
  country: string | null;
  iso2?: string | null;
  lat: number;
  lon: number;
  radius_km: number;
  confidence: number;
  /** One sentence: the evidence for this guess over the others. */
  why?: string | null;
  km_from_exif?: number | null;
}

export interface AnalystClue {
  clue: string;
  suggests?: string | null;
}

/** One item of the geoguessing checklist the analyst went through. */
export interface AnalystCheck {
  category: string;
  label: string;
  seen: string;
  suggests: string;
}

/** A zoomed crop of a sign sent along with the photo; box is [x0, y0, x1, y1] in photo pixels. */
export interface AnalystCrop {
  box: [number, number, number, number];
  text: string;
}

export interface Analyst {
  provider: Provider;
  name: string;
  via: string;
  ok: boolean;
  error: string | null;
  model: string | null;
  ms: number | null;
  reasoning: string;
  /** Absent on answers saved before 2026-10-15 (they only have clues). */
  checklist?: AnalystCheck[];
  ruled_out?: { place: string; why: string }[];
  crops?: AnalystCrop[];
  clues: AnalystClue[];
  driving_side: string | null;
  text_seen: string | null;
  guesses: AnalystGuess[];
}

export interface Result {
  id: string;
  name: string;
  created: string;
  image_url: string;
  thumb_url: string;
  image: { width: number; height: number };
  options: { ocr: boolean; exif_gps: boolean; ask: Provider[]; share_local: boolean };
  guesses: Guess[];
  countries: CountryOdds[];
  clues: Clue[];
  scene: ScenePrediction[];
  ocr: OcrLine[];
  analysts: Analyst[];
  heat: [number, number, number][];
  exif: {
    camera?: string | null;
    datetime?: string | null;
    utc_offset?: string | null;
    gps?: { lat: number; lon: number } | null;
  } | null;
  exif_gps: { lat: number; lon: number } | null;
  exif_place: { country?: string; region?: string; place?: { name: string } } | null;
  device: DeviceName | string | null;
  timings: {
    clip_ms?: number | null;
    ocr_ms?: number | null;
    fusion_ms?: number | null;
    llm_ms?: number | null;
    total_ms?: number | null;
  };
}

export interface HistorySummary {
  id: string;
  name: string;
  created: string;
  thumb_url: string;
  top: {
    lat: number;
    lon: number;
    confidence: number;
    label: ConfidenceLabel;
    country: string | null;
    country_code: string | null;
    place: string | null;
    region: string | null;
  } | null;
  analysts: Provider[];
  has_exif_gps: boolean;
  km_from_exif: number | null;
}
