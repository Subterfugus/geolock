// Fake GeoLock backend for UI development and screenshots. Implements desktop/API.md with canned data.
// Run: node desktop/ui/mock/server.mjs   (env: PORT=7861, MOCK_STATE=ready|needs_setup|loading|error)
import http from 'node:http';
import fs from 'node:fs';
import { randomUUID, createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const PORT = Number(process.env.PORT || 7861);
const DATA_DIR = fileURLToPath(new URL('../../../geolock/data/', import.meta.url));
const SETUP_TOTAL_S = 10;
const MB_TOTAL = 608;

// ---------------------------------------------------------------- state
const now = () => Date.now();
const iso = (ms) => new Date(ms).toISOString();

const S = {
  mode: process.env.MOCK_STATE || 'ready',       // initial mode
  setupState: process.env.MOCK_STATE === 'needs_setup' ? 'idle' : 'done', // idle | running | paused | done
  setupStartedAt: 0,
  setupElapsedS: 0,                               // progressed time, kept when paused
  setupError: process.env.MOCK_STATE === 'error' ? 'Could not start the model: out of memory while compiling for the GPU.' : null,
  loadingUntil: process.env.MOCK_STATE === 'loading' ? now() + 6000 : 0,
  device: 'GPU',
  bench: null,
  settings: {
    device: 'AUTO', read_text: true, show_exif_gps: true, share_findings: true,
    keep_history: true, theme: 'system', map_style: 'offline',
  },
  analysts: {
    claude: { available: true, via: 'claude-code', detail: 'Claude Code, your Claude login' },
    chatgpt: { available: false, via: null, detail: 'Install the Codex CLI and sign in (codex login) to use your ChatGPT plan.' },
  },
  history: [],        // newest first, ids
  results: new Map(), // id -> Result
  images: new Map(),  // id -> { bytes, type }
};

/** Advances the simulated setup; finishing it hands over to the model-loading phase. */
function tick() {
  if (S.setupState === 'running' && (now() - S.setupStartedAt) / 1000 + S.setupElapsedS >= SETUP_TOTAL_S) {
    S.setupState = 'done';
    S.setupElapsedS = 0;
    S.loadingUntil = now() + 2500;
  }
}

function setupInfo() {
  tick();
  const elapsed = S.setupState === 'running' ? (now() - S.setupStartedAt) / 1000 + S.setupElapsedS : S.setupElapsedS;
  const t = Math.min(elapsed, SETUP_TOTAL_S);
  const bounds = [[0, 5.5, 'download'], [5.5, 7.2, 'convert'], [7.2, 8.8, 'gallery'], [8.8, 10, 'load']];
  const cur = bounds.find(([a, b]) => t >= a && t < b) ?? null;
  const stepState = (i) => {
    if (S.setupState === 'done' || t >= bounds[i][1]) return 'done';
    if (S.setupState === 'running' && cur && cur[2] === bounds[i][2]) return 'running';
    return 'pending';
  };
  const steps = [
    { id: 'download', label: 'Download the CLIP vision model', state: stepState(0) },
    { id: 'convert', label: 'Optimise it for your processor', state: stepState(1) },
    { id: 'gallery', label: 'Build the map of 100,000 reference places', state: stepState(2) },
    { id: 'load', label: 'Load the models', state: stepState(3) },
  ];
  const running = S.setupState === 'running';
  let progress = null;
  if (running) {
    const dl = Math.min(1, t / 5.5);
    const doneMb = +(MB_TOTAL * dl).toFixed(1);
    const speed = 11.2;
    const left = MB_TOTAL - doneMb;
    progress = {
      step: cur ? cur[2] : 'load',
      fraction: cur && cur[2] === 'download' ? dl : null,
      done_mb: cur && cur[2] === 'download' ? doneMb : MB_TOTAL,
      total_mb: MB_TOTAL,
      speed_mbps: cur && cur[2] === 'download' ? speed : null,
      eta_s: cur && cur[2] === 'download' ? Math.round(left / speed) + 4 : null,
      message: cur && cur[2] === 'download' ? `Downloading… ${Math.round(doneMb)} of ${MB_TOTAL} MB` :
        cur && cur[2] === 'convert' ? 'Optimising for the Arc GPU…' :
        cur && cur[2] === 'gallery' ? 'Building the place gallery… 64,000 of 100,000' : 'Loading the models…',
    };
  }
  return {
    ready: S.setupState === 'done',
    running,
    download_mb: MB_TOTAL,
    disk_needed_mb: 1400,
    free_disk_mb: 412000,
    source: 'Hugging Face (Xenova/clip-vit-large-patch14, MIT licence)',
    steps,
    progress,
    error: S.setupState === 'paused' ? null : S.setupError,
  };
}

function status() {
  tick();
  let state = 'ready';
  if (S.setupState === 'running') state = 'setting_up';
  else if (S.setupState !== 'done') state = 'needs_setup';
  if (S.setupState === 'done' && S.loadingUntil > now()) state = 'loading';
  if (S.mode === 'error' && S.setupState === 'done') state = 'error';
  return {
    state,
    error: state === 'error' ? 'The CLIP model failed to compile for the GPU. Details are in the log file.' : null,
    version: '0.2.0',
    device: state === 'ready' || state === 'loading' ? diagnostics().device : null,
    device_name: NAMES[diagnostics().device],
    available_devices: ['CPU', 'GPU', 'NPU'],
    diagnostics: state === 'ready' ? diagnostics() : null,
    analysts: S.analysts,
    data_dir: 'C:\\Users\\Brady\\AppData\\Local\\com.geolock.desktop',
    models_dir: 'C:\\Users\\Brady\\AppData\\Local\\com.geolock.desktop\\models',
  };
}

const NAMES = { GPU: 'Intel(R) Arc(TM) 140V GPU (16GB)', NPU: 'Intel(R) AI Boost', CPU: 'Intel(R) Core(TM) Ultra 7 258V' };

/** MOCK_FALLBACK=1 pretends the NPU fails to compile, to show the fallback notice. */
function diagnostics() {
  const fell = process.env.MOCK_FALLBACK && S.settings.device === 'NPU';
  const device = fell ? 'CPU' : S.device;
  const last = S.history.length ? S.results.get(S.history[0]) : null;
  return {
    requested: S.settings.device, device, device_name: NAMES[device],
    compile_ms: device === 'GPU' ? 4200 : 1300, first_run_ms: device === 'GPU' ? 1900 : 520,
    last_run_ms: device === 'GPU' ? 190 : 640, runs: 3, warmup_ms: 3100, load_ms: 7400,
    last_locate: last ? { device: last.device, timings: last.timings, at: Date.now() / 1000 } : null,
    fallback: fell ? 'NPU couldn\'t start (RuntimeError: [NPU] Level0 driver not found), so GeoLock is using the CPU.' : null,
    attempts: [],
  };
}

// --------------------------------------------------------- deterministic helpers
function rng(seedStr) {
  let h = createHash('sha256').update(seedStr).digest();
  let i = 0;
  return () => {
    const v = h.readUInt32BE(i % 28) / 0xffffffff;
    i += 4;
    if (i % 28 === 0) h = createHash('sha256').update(h).digest();
    return v;
  };
}
const gauss = (r) => Math.sqrt(-2 * Math.log(r() || 1e-9)) * Math.cos(2 * Math.PI * r());

function haversine(a, b, c, d) {
  const R = 6371.0088, rad = (x) => (x * Math.PI) / 180;
  const dLat = rad(c - a), dLon = rad(d - b);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

const labelOf = (c) => (c >= 0.5 ? 'high' : c >= 0.2 ? 'medium' : 'low');

function heatFor(guesses, seed) {
  const r = rng(seed);
  const pts = [];
  for (const g of guesses) {
    const n = Math.round(60 + 240 * g.confidence);
    const sigma = Math.max(0.05, g.radius_km / 111);
    for (let i = 0; i < n; i++) {
      const lat = g.lat + gauss(r) * sigma * 0.7;
      const lon = g.lon + gauss(r) * sigma;
      const w = Math.max(0.05, Math.min(1, g.confidence * (0.4 + 0.6 * r())));
      pts.push([+lat.toFixed(4), +lon.toFixed(4), +w.toFixed(3)]);
    }
  }
  return pts.slice(0, 1500);
}

function guess(p) {
  const place = p.place ?? null;
  return {
    lat: p.lat, lon: p.lon, confidence: p.confidence, label: labelOf(p.confidence),
    radius_km: p.radius_km, visual_mass: p.visual_mass ?? +(p.confidence * 0.7).toFixed(2),
    country_code: p.cc, country: p.country, continent: p.continent ?? null, region: p.region ?? null,
    place, km_from_exif: null, why: p.why,
  };
}

// ----------------------------------------------------------- image placeholders
function svgPhoto(label, [c1, c2, c3], w, h, kind = 'city') {
  const hills = kind === 'mountain'
    ? `<polygon points="0,${h * 0.62} ${w * 0.18},${h * 0.36} ${w * 0.34},${h * 0.52} ${w * 0.55},${h * 0.22} ${w * 0.78},${h * 0.48} ${w},${h * 0.3} ${w},${h} 0,${h}" fill="${c3}" opacity="0.95"/>
       <polygon points="0,${h * 0.78} ${w * 0.3},${h * 0.6} ${w * 0.6},${h * 0.72} ${w},${h * 0.58} ${w},${h} 0,${h}" fill="#0b1520" opacity="0.6"/>`
    : kind === 'sea'
    ? `<rect x="0" y="${h * 0.55}" width="${w}" height="${h * 0.45}" fill="${c3}" opacity="0.9"/>
       <rect x="${w * 0.1}" y="${h * 0.35}" width="${w * 0.22}" height="${h * 0.22}" fill="#f3efe6" opacity="0.8"/>
       <rect x="${w * 0.6}" y="${h * 0.3}" width="${w * 0.3}" height="${h * 0.26}" fill="#e9e3d6" opacity="0.8"/>`
    : kind === 'temple'
    ? `<polygon points="${w * 0.2},${h * 0.5} ${w * 0.5},${h * 0.32} ${w * 0.8},${h * 0.5}" fill="#c9a24b"/>
       <rect x="${w * 0.24}" y="${h * 0.5}" width="${w * 0.52}" height="${h * 0.18}" fill="#c8402f" opacity="0.85"/>
       <rect x="0" y="${h * 0.7}" width="${w}" height="${h * 0.3}" fill="#1d3a2b" opacity="0.9"/>`
    : `<rect x="${w * 0.08}" y="${h * 0.34}" width="${w * 0.2}" height="${h * 0.5}" fill="#3b3550" opacity="0.85"/>
       <rect x="${w * 0.32}" y="${h * 0.26}" width="${w * 0.18}" height="${h * 0.58}" fill="#4a4262" opacity="0.85"/>
       <rect x="${w * 0.54}" y="${h * 0.38}" width="${w * 0.22}" height="${h * 0.46}" fill="#34304a" opacity="0.85"/>
       <rect x="0" y="${h * 0.84}" width="${w}" height="${h * 0.16}" fill="#1a1726" opacity="0.7"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c1}"/><stop offset="0.6" stop-color="${c2}"/><stop offset="1" stop-color="${c3}"/></linearGradient></defs>
    <rect width="${w}" height="${h}" fill="url(#g)"/>
    <circle cx="${w * 0.72}" cy="${h * 0.24}" r="${h * 0.09}" fill="#fff7e0" opacity="0.7"/>
    ${hills}
    <text x="${w / 2}" y="${h * 0.93}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="${Math.round(h * 0.055)}" fill="#ffffff" opacity="0.85">${label.replace(/&/g, '&amp;')}</text>
  </svg>`;
}

// ------------------------------------------------------------- analyst answers
function claudeAnswer(res, guesses, reasoning, checklist, side, text, extra = {}) {
  const exif = res.exif_gps;
  const pts = guesses.map((g) => ({ ...g, km_from_exif: exif ? +haversine(exif.lat, exif.lon, g.lat, g.lon).toFixed(1) : null }));
  const clues = checklist.map((c) => ({ clue: `${c.label}: ${c.seen}`, suggests: c.suggests }));
  return {
    provider: 'claude', name: 'Claude', via: 'Claude Code, your Claude login', ok: true, error: null,
    model: 'claude-opus-5-5', ms: 8400, reasoning, checklist, clues, ruled_out: [], crops: [],
    driving_side: side, text_seen: text, guesses: pts, ...extra,
  };
}

// ----------------------------------------------------------------- results
function finishResult(r) {
  if (r.exif_gps) {
    for (const g of r.guesses) g.km_from_exif = +haversine(r.exif_gps.lat, r.exif_gps.lon, g.lat, g.lon).toFixed(1);
  }
  return r;
}

function seedResults() {
  const t = now();
  const parisGuesses = [
    guess({ lat: 48.85341, lon: 2.3488, confidence: 0.46, radius_km: 38.5, visual_mass: 0.31, cc: 'FR', country: 'France', continent: 'Europe', region: 'Île-de-France',
      place: { name: 'Paris', admin1: 'Île-de-France', cc: 'FR', km: 1.2 },
      why: [
        { effect: 1, text: 'Visual similarity (GeoCLIP) puts 31% of its weight in this area.' },
        { effect: 1, text: "CLIP's country classifier ranks France #1 (22%)." },
        { effect: 1, text: 'Text in French: “boulangerie”, “rue”.' },
        { effect: 1, text: 'Haussmann-style façades, typical of central Paris.' },
        { effect: -1, text: 'Traffic drives on the right; this is consistent with France.' },
      ] }),
    guess({ lat: 50.6292, lon: 3.0573, confidence: 0.12, radius_km: 70, visual_mass: 0.08, cc: 'FR', country: 'France', continent: 'Europe', region: 'Hauts-de-France',
      place: { name: 'Lille', admin1: 'Hauts-de-France', cc: 'FR', km: 0.9 },
      why: [{ effect: 1, text: 'Similar architecture in northern France.' }, { effect: 0, text: 'Several cities share this street style.' }] }),
    guess({ lat: 50.8503, lon: 4.3517, confidence: 0.07, radius_km: 120, visual_mass: 0.05, cc: 'BE', country: 'Belgium', continent: 'Europe', region: 'Brussels-Capital',
      place: { name: 'Brussels', admin1: 'Brussels-Capital', cc: 'BE', km: 0.5 },
      why: [{ effect: 1, text: 'Brussels has matching brick facades.' }, { effect: -1, text: 'The shop sign is in French, which is less usual here.' }] }),
  ];
  const paris = finishResult({
    id: '20261015-092210-a1f3c2', name: 'IMG_2041.jpg', created: iso(t - 25 * 60e3),
    image_url: '', thumb_url: '', image: { width: 4032, height: 3024 },
    options: { ocr: true, exif_gps: true, ask: ['claude'], share_local: true },
    guesses: parisGuesses,
    countries: [
      { code: 'FR', name: 'France', prob: 0.58, clip_prob: 0.22 }, { code: 'BE', name: 'Belgium', prob: 0.11, clip_prob: 0.05 },
      { code: 'CH', name: 'Switzerland', prob: 0.05, clip_prob: 0.03 }, { code: 'DE', name: 'Germany', prob: 0.04, clip_prob: 0.04 },
      { code: 'LU', name: 'Luxembourg', prob: 0.03, clip_prob: 0.01 }, { code: 'ES', name: 'Spain', prob: 0.02, clip_prob: 0.02 },
    ],
    clues: [
      { kind: 'language', title: 'Text in French', detail: 'Language detector: 92% (“boulangerie, rue…”).', strength: 0.7, countries: [{ code: 'FR', name: 'France', weight: 1 }, { code: 'BE', name: 'Belgium', weight: 0.4 }], n_countries: 12 },
      { kind: 'ocr', title: 'Shop sign: “BOULANGERIE”', detail: 'Read with 97% confidence.', strength: 0.45, countries: [{ code: 'FR', name: 'France', weight: 1 }], n_countries: 6 },
      { kind: 'currency', title: 'Euro prices on a menu', detail: 'Two euro amounts were read.', strength: 0.35, countries: [{ code: 'FR', name: 'France', weight: 1 }, { code: 'DE', name: 'Germany', weight: 0.6 }], n_countries: 19 },
      { kind: 'timezone', title: 'Local time is UTC+2', detail: 'From the photo timestamp.', strength: 0.3, countries: [{ code: 'FR', name: 'France', weight: 1 }, { code: 'DE', name: 'Germany', weight: 1 }], n_countries: 9 },
      { kind: 'scene', title: 'City street, overcast', detail: 'Scene classifier.', strength: 0, countries: [], n_countries: 0 },
      { kind: 'exif', title: 'Taken with Apple iPhone 15', detail: 'Camera model from metadata.', strength: 0, countries: [], n_countries: 0 },
      { kind: 'claude', title: 'Blue enamel street sign', detail: 'Claude read “Rue de Rivoli” on a blue sign.', strength: 0.6, countries: [{ code: 'FR', name: 'France', weight: 1 }], n_countries: 1 },
    ],
    scene: [{ attribute: 'Setting', value: 'city street', prob: 0.61 }, { attribute: 'Weather', value: 'overcast', prob: 0.2 }, { attribute: 'Era', value: 'historic', prob: 0.4 }],
    ocr: [
      { text: 'BOULANGERIE', score: 0.97, box: [[410, 780], [1260, 780], [1260, 870], [410, 870]], model: 'default' },
      { text: 'PÂTISSERIE', score: 0.9, box: [[1330, 760], [1800, 760], [1800, 830], [1330, 830]], model: 'default' },
      { text: 'Rue de Rivoli', score: 0.93, box: [[1450, 1100], [2130, 1100], [2130, 1180], [1450, 1180]], model: 'default' },
    ],
    analysts: [claudeAnswer({ exif_gps: { lat: 48.853, lon: 2.3499 } }, [
      { place: 'Rue de Rivoli, Paris', country: 'France', iso2: 'FR', lat: 48.8606, lon: 2.3376, radius_km: 2, confidence: 0.7,
        why: 'The street sign names Rue de Rivoli, and the arcades fit its 1st arrondissement stretch.' },
      { place: 'Marais, Paris', country: 'France', iso2: 'FR', lat: 48.8575, lon: 2.3602, radius_km: 3, confidence: 0.15,
        why: 'Rue de Rivoli continues east into the Marais with the same façades.' },
    ], 'Haussmann façades, a blue enamel street sign reading “Rue de Rivoli”, and the French bakery signage all point to central Paris. The cars and the pavement fit France.',
    [
      { category: 'driving_side', label: 'Driving side', seen: 'Parked cars face the right-hand flow', suggests: 'Right-hand traffic; rules out the UK' },
      { category: 'road_markings', label: 'Road lines', seen: 'White dashed lines, no yellow', suggests: 'Continental Europe' },
      { category: 'signs', label: 'Signs', seen: 'Blue enamel street plate with a green border', suggests: 'Paris street name plate' },
      { category: 'script_language', label: 'Text and language', seen: '“BOULANGERIE”, “Rue de Rivoli”', suggests: 'French; Rue de Rivoli is in Paris' },
      { category: 'architecture', label: 'Architecture', seen: 'Cream stone façades, wrought-iron balconies, mansard roofs', suggests: 'Haussmann-era Paris' },
    ],
    'right', 'Rue de Rivoli', {
      ruled_out: [{ place: 'Brussels', why: 'Brussels street signs are bilingual French and Dutch.' }, { place: 'Quebec', why: 'Quebec stop signs and plates look different, and the façades are Parisian.' }],
      crops: [{ box: [330, 700, 1880, 950], text: 'BOULANGERIE / PÂTISSERIE' }, { box: [1380, 1040, 2200, 1240], text: 'Rue de Rivoli' }],
    })],
    heat: [], exif: { camera: 'Apple iPhone 15', datetime: '2026:07:03 14:22:10', utc_offset: '+02:00', gps: { lat: 48.853, lon: 2.3499 } },
    exif_gps: { lat: 48.853, lon: 2.3499 }, exif_place: { country: 'France', region: 'Île-de-France', place: { name: 'Paris' } },
    device: 'GPU', timings: { clip_ms: 210, ocr_ms: 640, fusion_ms: 380, llm_ms: 8400, total_ms: 9700 },
  });
  paris.heat = heatFor(paris.guesses, paris.id);
  paris.image_url = `/api/history/${paris.id}/image`;
  paris.thumb_url = `/api/history/${paris.id}/thumb`;

  const kyoto = finishResult({
    id: '20261015-062004-b71d90', name: 'kinkakuji_2024.jpg', created: iso(t - 3 * 3600e3),
    image_url: '', thumb_url: '', image: { width: 3024, height: 4032 },
    options: { ocr: true, exif_gps: true, ask: ['chatgpt'], share_local: true },
    guesses: [
      guess({ lat: 35.0394, lon: 135.7292, confidence: 0.82, radius_km: 6, visual_mass: 0.74, cc: 'JP', country: 'Japan', continent: 'Asia', region: 'Kyōto',
        place: { name: 'Kyoto', admin1: 'Kyoto', cc: 'JP', km: 0.8 },
        why: [{ effect: 1, text: 'Visual similarity to golden-pavilion temples in Kyoto.' }, { effect: 1, text: 'Japanese script on a sign: 金閣寺.' }, { effect: 1, text: 'Language detector: Japanese, 99%.' }] }),
      guess({ lat: 34.6937, lon: 135.5023, confidence: 0.05, radius_km: 80, visual_mass: 0.03, cc: 'JP', country: 'Japan', continent: 'Asia', region: 'Ōsaka',
        place: { name: 'Osaka', admin1: 'Osaka', cc: 'JP', km: 0.4 }, why: [{ effect: 0, text: 'Similar temples in the Kansai region.' }] }),
    ],
    countries: [{ code: 'JP', name: 'Japan', prob: 0.93, clip_prob: 0.71 }, { code: 'KR', name: 'South Korea', prob: 0.02, clip_prob: 0.02 }, { code: 'CN', name: 'China', prob: 0.01, clip_prob: 0.03 }],
    clues: [
      { kind: 'script', title: 'Japanese script', detail: 'Kanji and kana detected on a sign.', strength: 0.9, countries: [{ code: 'JP', name: 'Japan', weight: 1 }], n_countries: 3 },
      { kind: 'ocr', title: 'Sign reads 金閣寺', detail: 'Kinkaku-ji, a temple in Kyoto.', strength: 0.8, countries: [{ code: 'JP', name: 'Japan', weight: 1 }], n_countries: 1 },
      { kind: 'scene', title: 'Temple garden', detail: 'Scene classifier.', strength: 0, countries: [], n_countries: 0 },
    ],
    scene: [{ attribute: 'Setting', value: 'temple grounds', prob: 0.74 }, { attribute: 'Season', value: 'autumn', prob: 0.31 }, { attribute: 'Crowd', value: 'tourists', prob: 0.5 }],
    ocr: [{ text: '金閣寺', score: 0.95, box: [[1000, 1500], [1400, 1500], [1400, 1620], [1000, 1620]], model: 'default' }],
    analysts: [{
      provider: 'chatgpt', name: 'ChatGPT', via: 'Codex CLI, your ChatGPT login', ok: false,
      error: 'The Codex CLI did not answer within 60 seconds and was stopped.', model: 'gpt-5', ms: 60000,
      reasoning: '', clues: [], driving_side: null, text_seen: null, guesses: [],
    }],
    heat: [], exif: { camera: 'Canon EOS R6', datetime: '2026:10:14 09:12:44', utc_offset: '+09:00', gps: null },
    exif_gps: null, exif_place: null, device: 'GPU', timings: { clip_ms: 198, ocr_ms: 510, fusion_ms: 330, total_ms: 1040 },
  });
  kyoto.heat = heatFor(kyoto.guesses, kyoto.id);
  kyoto.image_url = `/api/history/${kyoto.id}/image`;
  kyoto.thumb_url = `/api/history/${kyoto.id}/thumb`;

  const patagonia = finishResult({
    id: '20261014-184530-5c0e7a', name: 'torres_del_paine.jpg', created: iso(t - 26 * 3600e3),
    image_url: '', thumb_url: '', image: { width: 4000, height: 2667 },
    options: { ocr: true, exif_gps: true, ask: [], share_local: true },
    guesses: [
      guess({ lat: -50.6, lon: -72.9, confidence: 0.09, radius_km: 420, visual_mass: 0.07, cc: 'CL', country: 'Chile', continent: 'South America', region: 'Magallanes Region',
        place: null, why: [
          { effect: 1, text: 'Landscape resembles the southern Andes.' },
          { effect: 0, text: 'No text or signage in the photo.' },
          { effect: -1, text: 'Similar scenery across the border in Argentina.' },
        ] }),
      guess({ lat: -49.3, lon: -72.9, confidence: 0.06, radius_km: 300, visual_mass: 0.05, cc: 'AR', country: 'Argentina', continent: 'South America', region: 'Santa Cruz',
        place: null, why: [{ effect: 1, text: 'Patagonian steppe and lake shapes.' }] }),
    ],
    countries: [{ code: 'CL', name: 'Chile', prob: 0.41, clip_prob: 0.2 }, { code: 'AR', name: 'Argentina', prob: 0.34, clip_prob: 0.18 }, { code: 'NZ', name: 'New Zealand', prob: 0.04, clip_prob: 0.03 }, { code: 'US', name: 'United States', prob: 0.02, clip_prob: 0.02 }],
    clues: [{ kind: 'scene', title: 'Mountain lake landscape', detail: 'Scene classifier.', strength: 0, countries: [], n_countries: 0 }],
    scene: [{ attribute: 'Setting', value: 'mountain', prob: 0.88 }, { attribute: 'Weather', value: 'clear', prob: 0.5 }],
    ocr: [], analysts: [], heat: [],
    exif: { camera: 'Sony ILCE-7M4', datetime: '2026:10:13 17:40:02', utc_offset: '-03:00', gps: null },
    exif_gps: null, exif_place: null, device: 'GPU', timings: { clip_ms: 214, ocr_ms: 0, fusion_ms: 301, total_ms: 610 },
  });
  patagonia.heat = heatFor(patagonia.guesses, patagonia.id);
  patagonia.image_url = `/api/history/${patagonia.id}/image`;
  patagonia.thumb_url = `/api/history/${patagonia.id}/thumb`;

  const capetown = finishResult({
    id: '20261013-160118-e2d9f4', name: 'IMG_4471.JPG', created: iso(t - 50 * 3600e3),
    image_url: '', thumb_url: '', image: { width: 4032, height: 3024 },
    options: { ocr: true, exif_gps: true, ask: [], share_local: true },
    guesses: [
      guess({ lat: -33.9249, lon: 18.4241, confidence: 0.58, radius_km: 25, visual_mass: 0.5, cc: 'ZA', country: 'South Africa', continent: 'Africa', region: 'Western Cape',
        place: { name: 'Cape Town', admin1: 'Western Cape', cc: 'ZA', km: 0.6 },
        why: [{ effect: 1, text: 'Table Mountain-like skyline in the background.' }, { effect: 1, text: 'English and Afrikaans signage read.' }, { effect: -1, text: 'Palm trees are also common in Durban.' }] }),
      guess({ lat: -34.0, lon: 18.8, confidence: 0.06, radius_km: 110, visual_mass: 0.05, cc: 'ZA', country: 'South Africa', continent: 'Africa', region: 'Western Cape', place: null, why: [{ effect: 0, text: 'Nearby wine country.' }] }),
    ],
    countries: [{ code: 'ZA', name: 'South Africa', prob: 0.86, clip_prob: 0.55 }, { code: 'NA', name: 'Namibia', prob: 0.02, clip_prob: 0.02 }],
    clues: [{ kind: 'language', title: 'English text', detail: 'Language detector: 88%.', strength: 0.5, countries: [{ code: 'ZA', name: 'South Africa', weight: 1 }], n_countries: 4 }],
    scene: [{ attribute: 'Setting', value: 'harbour', prob: 0.7 }],
    ocr: [{ text: 'V&A WATERFRONT', score: 0.92, box: [[500, 900], [2100, 900], [2100, 1000], [500, 1000]], model: 'default' }],
    analysts: [], heat: [],
    exif: { camera: 'Apple iPhone 13', datetime: '2026:10:11 15:01:33', utc_offset: '+02:00', gps: { lat: -33.904, lon: 18.423 } },
    exif_gps: { lat: -33.904, lon: 18.423 }, exif_place: null, device: 'GPU', timings: { clip_ms: 201, ocr_ms: 602, fusion_ms: 312, total_ms: 1140 },
  });
  capetown.heat = heatFor(capetown.guesses, capetown.id);
  capetown.image_url = `/api/history/${capetown.id}/image`;
  capetown.thumb_url = `/api/history/${capetown.id}/thumb`;

  const seeds = [
    [paris, ['#f7b98a', '#8a5a7a', '#2c2440'], 'Paris, street', 'city', 4032, 3024],
    [kyoto, ['#bfe3c4', '#5f9d72', '#1d3a2b'], 'Kinkaku-ji, Kyoto', 'temple', 3024, 4032],
    [patagonia, ['#9cc4e8', '#d6e6f0', '#4a6d8c'], 'Torres del Paine', 'mountain', 4000, 2667],
    [capetown, ['#8fd3f0', '#d8f1f9', '#2b6f9e'], 'V&A Waterfront, Cape Town', 'sea', 4032, 3024],
  ];
  for (const [r, pal, label, kind, w, h] of seeds) {
    const svg = Buffer.from(svgPhoto(label, pal, w, h, kind));
    const thumb = Buffer.from(svgPhoto(label, pal, 320, Math.round(320 * h / w), kind));
    S.results.set(r.id, r);
    S.images.set(r.id, { full: { bytes: svg, type: 'image/svg+xml' }, thumb: { bytes: thumb, type: 'image/svg+xml' } });
    S.history.push(r.id);
  }
  // Paris' analyst clues include the Claude kind too.
}
seedResults();

// -------------------------------------------------------- random locate
const CANDIDATES = [
  { name: 'Lisbon', lat: 38.7223, lon: -9.1393, cc: 'PT', country: 'Portugal', region: 'Lisbon District', continent: 'Europe', text: 'Pastéis, Tram 28' },
  { name: 'Oslo', lat: 59.9139, lon: 10.7522, cc: 'NO', country: 'Norway', region: 'Oslo', continent: 'Europe', text: 'Oslo S' },
  { name: 'Marrakesh', lat: 31.6295, lon: -7.9811, cc: 'MA', country: 'Morocco', region: 'Marrakesh-Safi', continent: 'Africa', text: 'Jemaa el-Fnaa' },
  { name: 'Hanoi', lat: 21.0285, lon: 105.8542, cc: 'VN', country: 'Vietnam', region: 'Hanoi', continent: 'Asia', text: 'Phở Bát Đàn' },
  { name: 'Mexico City', lat: 19.4326, lon: -99.1332, cc: 'MX', country: 'Mexico', region: 'Mexico City', continent: 'North America', text: 'Tacos al pastor' },
  { name: 'Berlin', lat: 52.52, lon: 13.405, cc: 'DE', country: 'Germany', region: 'Berlin', continent: 'Europe', text: 'Currywurst' },
  { name: 'Reykjavík', lat: 64.1466, lon: -21.9426, cc: 'IS', country: 'Iceland', region: 'Capital Region', continent: 'Europe', text: 'Bónus' },
];

function locateResult(id, name, exifGps, file) {
  const r = rng(id);
  const c = CANDIDATES[Math.floor(r() * CANDIDATES.length)];
  const conf = 0.3 + r() * 0.5;
  const guesses = [
    guess({ lat: c.lat + (r() - 0.5) * 0.1, lon: c.lon + (r() - 0.5) * 0.1, confidence: +conf.toFixed(2), radius_km: +(8 + r() * 40).toFixed(1), cc: c.cc, country: c.country, continent: c.continent, region: c.region,
      place: { name: c.name, admin1: c.region, cc: c.cc, km: +(r() * 2).toFixed(1) },
      why: [
        { effect: 1, text: `Visual similarity (GeoCLIP) puts ${Math.round(conf * 70)}% of its weight in this area.` },
        { effect: 1, text: `CLIP's country classifier ranks ${c.country} #1.` },
        { effect: -1, text: 'Few distinctive landmarks in view.' },
      ] }),
    guess({ lat: c.lat + 1.2, lon: c.lon - 2.4, confidence: +(conf * 0.2).toFixed(2), radius_km: 140, cc: c.cc, country: c.country, continent: c.continent, region: c.region, place: null, why: [{ effect: 0, text: 'Similar climate and architecture.' }] }),
  ];
  const r0 = finishResult({
    id, name, created: iso(now()), image_url: `/api/history/${id}/image`, thumb_url: `/api/history/${id}/thumb`,
    image: { width: 4032, height: 3024 },
    options: { ocr: true, exif_gps: true, ask: [], share_local: true },
    guesses,
    countries: [{ code: c.cc, name: c.country, prob: +(0.4 + r() * 0.3).toFixed(2), clip_prob: +(0.2 + r() * 0.2).toFixed(2) }, { code: 'ES', name: 'Spain', prob: 0.05, clip_prob: 0.04 }],
    clues: [
      { kind: 'ocr', title: `Text: “${c.text}”`, detail: 'Read from a sign in the photo.', strength: 0.6, countries: [{ code: c.cc, name: c.country, weight: 1 }], n_countries: 3 },
      { kind: 'scene', title: 'Street scene', detail: 'Scene classifier.', strength: 0, countries: [], n_countries: 0 },
    ],
    scene: [{ attribute: 'Setting', value: 'city street', prob: 0.66 }],
    ocr: [{ text: c.text, score: 0.9, box: [[600, 1000], [2000, 1000], [2000, 1120], [600, 1120]], model: 'default' }],
    analysts: [], heat: [],
    exif: exifGps ? { camera: 'Google Pixel 8', datetime: '2026:10:15 10:08:11', utc_offset: '+01:00', gps: exifGps } : null,
    exif_gps: exifGps ?? null, exif_place: null, device: 'GPU', timings: { clip_ms: 205, ocr_ms: 580, fusion_ms: 300, total_ms: 1500 },
  });
  r0.heat = heatFor(r0.guesses, id);
  return r0;
}

// --------------------------------------------------------------- multipart
function parseMultipart(buf, boundary) {
  const parts = {};
  const delim = Buffer.from(`--${boundary}`);
  let pos = buf.indexOf(delim);
  while (pos !== -1) {
    const start = pos + delim.length;
    if (buf.slice(start, start + 2).toString() === '--') break;
    const hdrEnd = buf.indexOf('\r\n\r\n', start);
    if (hdrEnd < 0) break;
    const headers = buf.slice(start + 2, hdrEnd).toString('utf8');
    const next = buf.indexOf(delim, hdrEnd + 4);
    const end = next === -1 ? buf.length : next - 2;
    const data = buf.slice(hdrEnd + 4, end);
    const name = /name="([^"]+)"/.exec(headers)?.[1];
    const filename = /filename="([^"]*)"/.exec(headers)?.[1];
    const type = /Content-Type:\s*([^\r\n]+)/i.exec(headers)?.[1]?.trim();
    if (name) parts[name] = { filename, type, data };
    pos = next;
  }
  return parts;
}

const boolOf = (v, d) => (v === undefined ? d : v === 'true' || v === '1' || v === 'on');

// --------------------------------------------------------------- http
function send(res, code, body, type = 'application/json') {
  res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store' });
  res.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}
const fail = (res, code, detail) => send(res, code, { detail });

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
  });
}

function summary(r) {
  const top = r.guesses[0];
  const a = r.analysts.map((x) => x.provider);
  return {
    id: r.id, name: r.name, created: r.created, thumb_url: r.thumb_url,
    top: top ? {
      lat: top.lat, lon: top.lon, confidence: top.confidence, label: top.label,
      country: top.country, country_code: top.country_code,
      place: top.place && top.place.km < 60 ? top.place.name : null, region: top.region,
    } : null,
    analysts: a, has_exif_gps: !!r.exif_gps, km_from_exif: top?.km_from_exif ?? null,
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function route(req, res) {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const p = url.pathname;
  const m = req.method;

  // static map data
  if (m === 'GET' && p.startsWith('/data/')) {
    const file = DATA_DIR + p.slice('/data/'.length).replace(/\.\./g, '');
    if (!fs.existsSync(file)) return fail(res, 404, 'Not found');
    res.writeHead(200, { 'Content-Type': 'application/geo+json', 'Cache-Control': 'max-age=3600' });
    return fs.createReadStream(file).pipe(res);
  }

  if (m === 'GET' && p === '/api/status') return send(res, 200, status());

  if (p === '/api/setup' && m === 'GET') return send(res, 200, setupInfo());
  if (p === '/api/setup/start' && m === 'POST') {
    if (S.setupState === 'idle' || S.setupState === 'paused') {
      S.setupState = 'running';
      S.setupStartedAt = now();
      S.setupError = null;
    }
    return send(res, 200, setupInfo());
  }
  if (p === '/api/setup/cancel' && m === 'POST') {
    if (S.setupState === 'running') {
      S.setupElapsedS = Math.min(SETUP_TOTAL_S, (now() - S.setupStartedAt) / 1000 + S.setupElapsedS);
      S.setupState = 'paused';
    }
    return send(res, 200, setupInfo());
  }
  if (p === '/api/setup/import' && m === 'POST') {
    const body = JSON.parse((await readBody(req)).toString() || '{}');
    if (!body.folder || !/models/i.test(body.folder)) return fail(res, 400, `“${body.folder}” is not a GeoLock models folder (it has no clip_vision.xml).`);
    S.setupState = 'done';
    S.loadingUntil = now() + 3000;
    return send(res, 200, setupInfo());
  }

  if (p === '/api/settings' && m === 'GET') return send(res, 200, S.settings);
  if (p === '/api/settings' && m === 'PUT') {
    const patch = JSON.parse((await readBody(req)).toString() || '{}');
    const reloading = 'device' in patch && patch.device !== S.settings.device;
    S.settings = { ...S.settings, ...patch };
    if (reloading) {
      S.device = patch.device === 'CPU' ? 'CPU' : patch.device === 'NPU' ? 'NPU' : 'GPU';
      S.loadingUntil = now() + 2500;
    }
    return send(res, 200, S.settings);
  }
  if (p === '/api/diagnostics/benchmark' && m === 'GET') return send(res, 200, S.bench ?? { rows: [], at: null });
  if (p === '/api/diagnostics/benchmark' && m === 'POST') {
    await sleep(1800);
    S.bench = { at: Date.now() / 1000, rows: [
      { device: 'GPU', name: NAMES.GPU, ok: true, compile_ms: 3900, first_run_ms: 1700, ms: 185, error: null },
      process.env.MOCK_FALLBACK
        ? { device: 'NPU', name: NAMES.NPU, ok: false, compile_ms: null, first_run_ms: null, ms: null, error: 'RuntimeError: [NPU] Level0 driver not found' }
        : { device: 'NPU', name: NAMES.NPU, ok: true, compile_ms: 21000, first_run_ms: 410, ms: 330, error: null },
      { device: 'CPU', name: NAMES.CPU, ok: true, compile_ms: 1200, first_run_ms: 700, ms: 640, error: null },
    ] };
    return send(res, 200, S.bench);
  }
  if (p === '/api/analysts/refresh' && m === 'POST') {
    await sleep(600);
    return send(res, 200, S.analysts);
  }

  if (p === '/api/history' && m === 'GET') {
    return send(res, 200, S.history.map((id) => summary(S.results.get(id))));
  }
  if (p === '/api/history' && m === 'DELETE') {
    const n = S.history.length;
    S.history = [];
    S.results.clear();
    S.images.clear();
    return send(res, 200, { ok: true, deleted: n });
  }

  const hm = /^\/api\/history\/([^/]+)(\/[a-z]+)?$/.exec(p);
  if (hm) {
    const id = decodeURIComponent(hm[1]);
    const sub = hm[2] ?? '';
    const r = S.results.get(id);
    if (!r) return fail(res, 404, 'No photo with that id is in the library.');
    if (sub === '' && m === 'GET') return send(res, 200, r);
    if (sub === '' && m === 'DELETE') {
      S.results.delete(id);
      S.images.delete(id);
      S.history = S.history.filter((x) => x !== id);
      return send(res, 200, { ok: true });
    }
    if (sub === '/image' || sub === '/thumb') {
      const img = S.images.get(id);
      const pick = sub === '/thumb' ? img?.thumb : img?.full;
      if (!pick) return fail(res, 404, 'No image');
      res.writeHead(200, { 'Content-Type': pick.type, 'Cache-Control': 'no-store' });
      return res.end(pick.bytes);
    }
    if (sub === '/rerun' && m === 'POST') {
      const form = new URLSearchParams((await readBody(req)).toString());
      const ask = (form.get('ask') || '').split(',').map((x) => x.trim()).filter(Boolean);
      if (ask.includes('chatgpt') && !S.analysts.chatgpt.available) {
        return fail(res, 400, 'ChatGPT is not set up. Install the Codex CLI and sign in (codex login).');
      }
      if (ask.includes('claude')) {
        await sleep(2000);
        const others = r.analysts.filter((a) => a.provider !== 'claude');
        const top = r.guesses[0];
        const claude = claudeAnswer(r, [
          { place: `${top.place?.name ?? top.country}, ${top.country}`, country: top.country, iso2: top.country_code, lat: top.lat + 0.01, lon: top.lon - 0.01, radius_km: 3, confidence: 0.64 },
        ], `Looking at the scene, I'd place this in ${top.place?.name ?? top.country}. The architecture, the signage and the light all agree with ${top.country}.`,
        [{ category: 'signs', label: 'Signs', seen: 'Local signage', suggests: top.country }, { category: 'other', label: 'Other', seen: 'Street layout', suggests: top.place?.name ?? top.region }], 'right', null);
        r.analysts = [...others, claude];
      }
      r.options = { ...r.options, ask: ask.filter((a) => a) };
      S.results.set(id, finishResult(r));
      return send(res, 200, S.results.get(id));
    }
  }

  // The real backend writes the file; the mock only checks the request (the browser UI downloads instead).
  if (p === '/api/save' && m === 'POST') {
    const boundary = /boundary=(.+)$/.exec(req.headers['content-type'] || '')?.[1];
    if (!boundary) return fail(res, 400, 'Send the file as multipart/form-data.');
    const parts = parseMultipart(await readBody(req), boundary.replace(/"/g, ''));
    const path = parts.path?.data.toString('utf8') ?? '';
    if (!/\.(json|csv|kml|png)$/i.test(path)) return fail(res, 400, 'Exports are saved as .json, .csv, .kml, .png files.');
    return send(res, 200, { path, bytes: parts.file?.data.length ?? 0 });
  }

  if (p === '/api/locate' && m === 'POST') {
    const ct = req.headers['content-type'] || '';
    const boundary = /boundary=(.+)$/.exec(ct)?.[1];
    if (!boundary) return fail(res, 400, 'Send the photo as multipart/form-data.');
    const parts = parseMultipart(await readBody(req), boundary.replace(/"/g, ''));
    if (!parts.file) return fail(res, 422, 'No photo was sent.');
    const get = (k) => (parts[k] ? parts[k].data.toString('utf8') : undefined);
    const name = get('name') || parts.file.filename || 'Photo';
    await sleep(1500);
    const id = `${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '').replace(/^(\d{8})(\d{6})$/, '$1-$2')}-${randomUUID().slice(0, 6)}`;
    const exifGps = boolOf(get('exif_gps'), true) ? { lat: 40.4168 + Math.random() * 0.02, lon: -3.7038 + Math.random() * 0.02 } : null;
    const r = locateResult(id, name, exifGps, parts.file);
    r.image_url = `/api/history/${id}/image`;
    r.thumb_url = `/api/history/${id}/thumb`;
    r.options = { ocr: boolOf(get('ocr'), true), exif_gps: boolOf(get('exif_gps'), true), ask: [], share_local: boolOf(get('share_local'), true) };
    const type = parts.file.type || 'image/jpeg';
    const bytes = parts.file.data;
    if (/^image\/(jpeg|png|webp|gif)$/.test(type)) {
      S.images.set(id, { full: { bytes, type }, thumb: { bytes, type } });
    } else {
      const svg = Buffer.from(svgPhoto(name, ['#c3d4ff', '#7e9ae8', '#2e3b70'], 1024, 768, 'city'));
      S.images.set(id, { full: { bytes: svg, type: 'image/svg+xml' }, thumb: { bytes: svg, type: 'image/svg+xml' } });
    }
    if (S.settings.keep_history) {
      S.results.set(id, r);
      S.history.unshift(id);
    }
    return send(res, 200, r);
  }

  return fail(res, 404, `No route for ${m} ${p}`);
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-GeoLock-Token');
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }
  try {
    await route(req, res);
  } catch (e) {
    console.error(e);
    if (!res.headersSent) fail(res, 500, String(e && e.message ? e.message : e));
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`GeoLock mock backend on http://127.0.0.1:${PORT} (state: ${S.mode})`);
});
