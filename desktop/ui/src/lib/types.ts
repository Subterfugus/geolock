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
  diagnostics?: Diagnostics | null;
  analysts: Partial<Record<Provider, AnalystStatus>>;
  data_dir: string;
  models_dir: string;
}

export interface DeviceAttempt {
  device: DeviceName;
  step: 'compile' | 'run' | 'first run';
  ok: boolean;
  ms: number | null;
  error: string | null;
}

/** Where CLIP runs and how it got there (null until the models are loaded). */
export interface Diagnostics {
  requested: 'AUTO' | DeviceName;
  device: DeviceName;
  device_name: string | null;
  compile_ms: number | null;
  first_run_ms: number | null;
  last_run_ms: number | null;
  runs: number;
  warmup_ms: number | null;
  load_ms: number | null;
  /** The latest photo analysed since the models loaded. */
  last_locate: { device: DeviceName | null; timings: Result['timings']; at: number } | null;
  /** One sentence when a device failed and GeoLock fell back, else null. */
  fallback: string | null;
  attempts: DeviceAttempt[];
}

export interface BenchmarkRow {
  device: DeviceName;
  name: string | null;
  ok: boolean;
  compile_ms: number | null;
  first_run_ms: number | null;
  ms: number | null;
  error: string | null;
}

export interface Benchmark {
  rows: BenchmarkRow[];
  at: number | null;
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

export type Effort = '' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';

export interface Settings {
  device: 'AUTO' | DeviceName;
  read_text: boolean;
  show_exif_gps: boolean;
  share_findings: boolean;
  /** Claude/ChatGPT may search the web to check sign text and candidate places. */
  analyst_web_search: boolean;
  keep_history: boolean;
  theme: ThemeMode;
  map_style: MapStyleKind;
  /** "" = the CLI's own default model / effort. */
  claude_model: string;
  claude_effort: Effort;
  chatgpt_model: string;
  chatgpt_effort: Effort;
}

/** GET /api/analysts/models: what the installed claude / codex CLIs accept. */
export interface ModelChoice {
  id: string;
  name: string;
  description?: string;
  /** Codex models list their own effort levels; absent = the provider's list. */
  efforts?: Effort[];
  default_effort?: string | null;
}
export interface ProviderModels {
  installed: boolean;
  models: ModelChoice[];
  efforts: Effort[];
}
export type ModelOptions = Record<Provider, ProviderModels>;

export type AnalystStage = 'preparing' | 'starting' | 'thinking' | 'writing' | 'done' | 'error' | 'stopped';
export interface AnalystLive {
  stage: AnalystStage;
  /** Seconds since the epoch (backend clock, same machine). */
  started: number;
  updated: number;
  model: string | null;
  effort: string | null;
  /** The latest line of the model's thinking, when the CLI shares it. */
  note: string;
  chars: number;
  /** Web searches run so far (absent from older backends). */
  searches?: number;
  error: string | null;
}
export interface AnalystProgress {
  running: boolean;
  now: number;
  providers: Partial<Record<Provider, AnalystLive>>;
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
  /** GeoLock moved the guess onto the town it named; its original point and the distance. */
  snapped?: { to: string; region: string; km: number; lat: number; lon: number } | null;
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
  /** "text": where GeoLock found text; "tile": a close-up of the road area. */
  kind?: 'text' | 'tile';
}

export interface Analyst {
  provider: Provider;
  name: string;
  via: string;
  ok: boolean;
  error: string | null;
  model: string | null;
  effort?: string | null;
  /** The user pressed Stop before it answered. */
  stopped?: boolean;
  ms: number | null;
  reasoning: string;
  /** Absent on answers saved before 2026-10-15 (they only have clues). */
  checklist?: AnalystCheck[];
  ruled_out?: { place: string; why: string }[];
  crops?: AnalystCrop[];
  clues: AnalystClue[];
  driving_side: string | null;
  text_seen: string | null;
  /** Whether it was allowed to search the web, and what it checked (absent on older answers). */
  web?: boolean;
  web_checks?: { query: string; found: string }[];
  /** Its odds for the country alone (absent on answers before 0.4.2). */
  countries?: { iso2: string; probability: number }[];
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
