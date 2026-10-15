import { LngLatBounds, Map as MapLibreMap, Marker } from 'maplibre-gl';
import type { FeatureCollection, Feature, MultiLineString, Point, Polygon } from 'geojson';
import type { StyleSpecification } from 'maplibre-gl';
import { dataUrl } from '../backend';
import { guessTitle } from '../format';
import { geodesicCircle, greatCircle } from '../geo';
import type { Guess, MapStyleKind, Result } from '../types';
import { FONT_STACK, MAX_ZOOM, PALETTE, offlineStyle, onlineStyle, type Theme } from './mapStyles';

type Fc = FeatureCollection<Point | Polygon | MultiLineString>;

const CONF_COLOR: Record<Theme, Record<Guess['label'], string>> = {
  dark: { high: '#93d070', medium: '#e9b440', low: '#8e8a7f' },
  light: { high: '#3f8a2a', medium: '#b7791f', low: '#7b776c' },
};

// Shared between map instances so the 3.6 MB admin-1 file is fetched once per run.
let countriesFc: FeatureCollection | null = null;
let labelFc: Fc | null = null;
let countriesPromise: Promise<void> | null = null;
let admin1Fc: FeatureCollection | null = null;
let admin1Promise: Promise<void> | null = null;

function loadCountries(): Promise<void> {
  if (!countriesPromise) {
    countriesPromise = fetch(dataUrl('/data/countries.geojson'))
      .then((r) => r.json())
      .then((gj: FeatureCollection) => {
        countriesFc = gj;
        const features: Feature<Point>[] = [];
        for (const f of gj.features) {
          const p = f.properties ?? {};
          if (p.lx == null || p.ly == null) continue;
          features.push({
            type: 'Feature',
            properties: { name: p.name, minlabel: p.minlabel ?? 3 },
            geometry: { type: 'Point', coordinates: [p.lx, p.ly] },
          });
        }
        labelFc = { type: 'FeatureCollection', features };
      })
      .catch(() => {
        countriesPromise = null;
      });
  }
  return countriesPromise;
}

function loadAdmin1(): Promise<void> {
  if (!admin1Promise) {
    admin1Promise = fetch(dataUrl('/data/admin1.geojson'))
      .then((r) => r.json())
      .then((gj: FeatureCollection) => {
        admin1Fc = gj;
      })
      .catch(() => {
        admin1Promise = null;
      });
  }
  return admin1Promise;
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888888';

const EMPTY: Fc = { type: 'FeatureCollection', features: [] };

export interface GeoMapCallbacks {
  onGuessClick(index: number): void;
  onStyleFailed(kind: MapStyleKind): void;
  /** The map zoomed; used to suggest Streets when the offline map runs out of detail. */
  onZoom?(zoom: number): void;
}

/** A MapLibre map with the GeoLock basemap, result overlays and DOM pins. */
export class GeoMap {
  private map: MapLibreMap;
  private kind: MapStyleKind;
  private theme: Theme;
  private styleReady = false;
  private result: Result | null = null;
  private selected = 0;
  private pins: Marker[] = [];
  private heatFc: Fc = EMPTY;
  private uncFc: Fc = EMPTY;
  private truthFc: Fc = EMPTY;
  private labelKey = -1;
  private destroyed = false;
  /** The themed streets style failed and the backup style is in use. */
  private backup = false;

  constructor(container: HTMLElement, kind: MapStyleKind, theme: Theme, private cb: GeoMapCallbacks, opts: { zoom?: number } = {}) {
    this.kind = kind;
    this.theme = theme;
    this.map = new MapLibreMap({
      container,
      style: this.styleFor(kind, theme),
      center: [12, 24],
      zoom: opts.zoom ?? 1.7,
      minZoom: 1,
      maxZoom: MAX_ZOOM[kind],
      renderWorldCopies: false,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      fadeDuration: 150,
      // Lets "Export map image" read the canvas back.
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    this.map.on('style.load', () => this.onStyleLoad());
    this.map.on('zoom', () => this.onZoom());
    // A static map (setup screen, empty library) does not redraw by itself when data arrives; nudge it.
    this.map.on('sourcedata', (e) => { if (e.isSourceLoaded) this.map.triggerRepaint(); });
    this.map.on('error', () => {
      if (this.styleReady || this.kind === 'offline' || this.destroyed) return;
      // The dark streets style failed: try the standard one before giving up on the online map.
      if (this.kind === 'streets' && !this.backup) {
        this.backup = true;
        this.map.setStyle(onlineStyle('streets', this.theme, true), { diff: false });
        return;
      }
      // A remote style that never loaded falls back to the offline map.
      this.cb.onStyleFailed(this.kind);
    });
    void loadCountries().then(() => this.styleReady && this.ensureBasemap());
  }

  private styleFor(kind: MapStyleKind, theme: Theme): StyleSpecification | string {
    return kind === 'offline' ? offlineStyle(theme) : onlineStyle(kind, theme, kind === 'streets' && this.backup);
  }

  // ------------------------------------------------------------ style

  setStyleKind(kind: MapStyleKind, theme: Theme): void {
    if (kind === this.kind && theme === this.theme) return;
    if (theme !== this.theme) this.backup = false;
    this.kind = kind;
    this.theme = theme;
    this.styleReady = false;
    this.map.setMaxZoom(MAX_ZOOM[kind]);
    this.buildOverlayData();
    this.map.setStyle(this.styleFor(kind, theme), { diff: false });
  }

  private onStyleLoad(): void {
    this.styleReady = true;
    this.ensureBasemap();
    this.ensureOverlays();
    this.labelKey = -1;
    this.onZoom();
  }

  private ensureBasemap(): void {
    if (this.kind !== 'offline' || !this.styleReady || !countriesFc || !labelFc) return;
    const map = this.map;
    const p = PALETTE[this.theme];
    const before = map.getLayer('heat-layer') ? 'heat-layer' : undefined;
    map.setPaintProperty('background', 'background-color', p.ocean);
    if (!map.getSource('countries')) {
      map.addSource('countries', { type: 'geojson', data: countriesFc as FeatureCollection, maxzoom: 6, tolerance: 0.4 });
      map.addLayer({ id: 'land', type: 'fill', source: 'countries', paint: { 'fill-color': p.land, 'fill-opacity': 1 } }, before);
      map.addLayer({
        id: 'country-borders', type: 'line', source: 'countries',
        paint: { 'line-color': p.border, 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.4, 5, 1.1] },
      }, before);
      map.addSource('admin1', { type: 'geojson', data: admin1Fc ?? EMPTY, maxzoom: 6, tolerance: 0.4 });
      map.addLayer({
        id: 'admin1-lines', type: 'line', source: 'admin1', minzoom: 4,
        paint: { 'line-color': p.admin, 'line-width': 0.8, 'line-dasharray': [2, 2.2] },
      }, before);
      map.addSource('country-labels', { type: 'geojson', data: labelFc as FeatureCollection });
      map.addLayer({
        id: 'country-labels', type: 'symbol', source: 'country-labels',
        layout: {
          'text-field': ['get', 'name'],
          'text-font': [FONT_STACK],
          'text-size': ['interpolate', ['linear'], ['zoom'], 1, 9, 4, 12, 7, 15],
          'text-max-width': 7,
          'text-letter-spacing': 0.02,
        },
        paint: { 'text-color': p.label, 'text-halo-color': p.halo, 'text-halo-width': 1.4 },
      }, before);
      this.labelKey = -1;
      this.onZoom();
    } else {
      map.setPaintProperty('land', 'fill-color', p.land);
      map.setPaintProperty('country-borders', 'line-color', p.border);
      map.setPaintProperty('admin1-lines', 'line-color', p.admin);
      map.setPaintProperty('country-labels', 'text-color', p.label);
      map.setPaintProperty('country-labels', 'text-halo-color', p.halo);
    }
    if (!admin1Fc && this.map.getZoom() >= 3.5) void this.loadAdmin1Now();
  }

  private async loadAdmin1Now(): Promise<void> {
    await loadAdmin1();
    if (!this.styleReady || this.kind !== 'offline' || !admin1Fc) return;
    const src = this.map.getSource('admin1') as { setData?: (d: FeatureCollection) => void } | undefined;
    src?.setData?.(admin1Fc);
  }

  private onZoom(): void {
    this.cb.onZoom?.(this.map.getZoom());
    if (!this.styleReady) return;
    const z = this.map.getZoom();
    if (this.kind === 'offline' && z >= 3.5 && !admin1Fc) void this.loadAdmin1Now();
    if (this.kind !== 'offline' || !this.map.getLayer('country-labels')) return;
    // Show each country name from its own minimum zoom; quantised so setFilter isn't called every frame.
    const threshold = z + 0.6;
    const key = Math.floor(threshold * 4);
    if (key === this.labelKey) return;
    this.labelKey = key;
    this.map.setFilter('country-labels', ['<=', ['get', 'minlabel'], threshold]);
  }

  // --------------------------------------------------------- overlays

  private ensureOverlays(): void {
    const map = this.map;
    if (!map.getSource('heat')) {
      map.addSource('heat', { type: 'geojson', data: this.heatFc });
      map.addLayer({
        id: 'heat-layer', type: 'heatmap', source: 'heat',
        paint: {
          'heatmap-weight': ['interpolate', ['linear'], ['get', 'w'], 0, 0, 1, 1],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 0.6, 6, 1.2, 9, 1.5],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 7, 4, 18, 7, 24],
          'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 3, 0.9, 5.5, 0.6, 7.5, 0.18, 9, 0],
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(255,140,60,0)', 0.15, 'rgba(255,170,90,0.45)', 0.4, '#ffb15c', 0.65, '#ff8a3d', 0.85, '#ff6b2c', 1, '#e8381a',
          ],
        },
      });
    }
    if (!map.getSource('uncertainty')) {
      map.addSource('uncertainty', { type: 'geojson', data: this.uncFc });
      map.addLayer({
        id: 'uncertainty-fill', type: 'fill', source: 'uncertainty',
        paint: { 'fill-color': ['get', 'color'], 'fill-opacity': ['case', ['==', ['get', 'sel'], 1], 0.2, 0.08] },
      });
      map.addLayer({
        id: 'uncertainty-line', type: 'line', source: 'uncertainty',
        paint: {
          'line-color': ['get', 'color'],
          'line-width': ['case', ['==', ['get', 'sel'], 1], 2.2, 1.2],
          'line-opacity': ['case', ['==', ['get', 'sel'], 1], 0.95, 0.6],
        },
      });
    }
    if (!map.getSource('truth')) {
      map.addSource('truth', { type: 'geojson', data: this.truthFc });
      map.addLayer({
        id: 'truth-line', type: 'line', source: 'truth',
        layout: { 'line-cap': 'round' },
        paint: { 'line-color': '#f59e0b', 'line-width': 2, 'line-opacity': 0.9, 'line-dasharray': [1.5, 2] },
      });
    }
    this.pushData();
  }

  private pushData(): void {
    if (!this.styleReady) return;
    (this.map.getSource('truth') as { setData?: (d: Fc) => void } | undefined)?.setData?.(this.truthFc);
    (this.map.getSource('heat') as { setData?: (d: Fc) => void } | undefined)?.setData?.(this.heatFc);
    (this.map.getSource('uncertainty') as { setData?: (d: Fc) => void } | undefined)?.setData?.(this.uncFc);
  }

  private buildOverlayData(): void {
    const r = this.result;
    this.heatFc = {
      type: 'FeatureCollection',
      features: (r?.heat ?? []).map(([lat, lon, w]) => ({
        type: 'Feature', properties: { w }, geometry: { type: 'Point', coordinates: [lon, lat] },
      })),
    };
    this.uncFc = {
      type: 'FeatureCollection',
      features: (r?.guesses ?? []).map((g, i) => ({
        type: 'Feature',
        properties: { color: CONF_COLOR[this.theme][g.label], sel: i === this.selected ? 1 : 0 },
        geometry: { type: 'Polygon', coordinates: [geodesicCircle(g.lat, g.lon, g.radius_km)] },
      })),
    };
    // A dashed line from the selected guess to the photo's own GPS: how far off it is.
    const g = r?.guesses[this.selected] ?? r?.guesses[0];
    const t = r?.exif_gps;
    this.truthFc = g && t ? {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: greatCircle(g.lat, g.lon, t.lat, t.lon) } }],
    } : EMPTY;
  }

  /** Shows a result: heat, uncertainty circles and the pins. Does not move the camera. */
  setResult(result: Result | null, selected = 0): void {
    this.result = result;
    this.selected = selected;
    this.buildOverlayData();
    this.pushData();
    this.buildPins();
  }

  /** Highlights one guess (no camera move). */
  highlight(index: number): void {
    if (!this.result) return;
    this.selected = index;
    this.buildOverlayData();
    this.pushData();
    this.updatePinClasses();
  }

  private buildPins(): void {
    this.pins.forEach((m) => m.remove());
    this.pins = [];
    const r = this.result;
    if (!r) return;
    if (r.exif_gps) {
      const el = document.createElement('div');
      el.className = 'gl-pin gl-pin-exif';
      el.title = "Photo's own GPS (not used for the guess)";
      el.setAttribute('aria-label', "Photo's own GPS location");
      el.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M12 2.5l2.9 6.1 6.6.8-4.9 4.5 1.3 6.6L12 17.3l-5.9 3.2 1.3-6.6-4.9-4.5 6.6-.8z" fill="currentColor"/></svg>';
      this.pins.push(new Marker({ element: el }).setLngLat([r.exif_gps.lon, r.exif_gps.lat]).addTo(this.map));
    }
    for (const a of r.analysts) {
      if (!a.ok) continue;
      const letter = a.provider === 'claude' ? 'C' : 'G';
      a.guesses.forEach((g, gi) => {
        const el = document.createElement('button');
        el.type = 'button';
        el.className = `gl-pin gl-pin-llm gl-pin-${a.provider}${gi ? ' is-secondary' : ''}`;
        const place = [g.place, g.country].filter(Boolean).join(', ');
        el.title = `${a.name} #${gi + 1}: ${place} (±${Math.round(g.radius_km)} km)`;
        el.setAttribute('aria-label', el.title);
        el.innerHTML = `<span>${letter}${gi ? gi + 1 : ''}</span>`;
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          this.flyTo(g.lat, g.lon, g.radius_km);
        });
        this.pins.push(new Marker({ element: el }).setLngLat([g.lon, g.lat]).addTo(this.map));
      });
    }
    // Added last so that the primary guesses sit on top; rank 1 is the very top.
    for (let i = r.guesses.length - 1; i >= 0; i--) {
      const g = r.guesses[i];
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'gl-pin gl-pin-guess';
      el.dataset.label = g.label;
      el.dataset.rank = String(i + 1);
      const t = guessTitle(g);
      el.title = `#${i + 1} ${t.main}`;
      el.setAttribute('aria-label', `Guess ${i + 1}: ${t.main}`);
      el.innerHTML = `<span>${i + 1}</span>`;
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        this.cb.onGuessClick(i);
      });
      this.pins.push(new Marker({ element: el }).setLngLat([g.lon, g.lat]).addTo(this.map));
    }
    this.updatePinClasses();
  }

  private updatePinClasses(): void {
    this.pins.forEach((m) => {
      const el = m.getElement();
      if (el.classList.contains('gl-pin-guess')) {
        el.classList.toggle('is-selected', Number(el.dataset.rank) - 1 === this.selected);
      }
    });
  }

  // ----------------------------------------------------------- camera

  flyTo(lat: number, lon: number, radiusKm: number): void {
    // Small radii (an analyst naming a street) zoom right in when the map has street detail.
    const zoom = Math.min(MAX_ZOOM[this.kind],
      radiusKm < 3 ? 14 : radiusKm < 10 ? 11.5 : radiusKm < 30 ? 9.2 : radiusKm < 100 ? 6.9 : radiusKm < 300 ? 5.8 : 4.6);
    this.map.flyTo({ center: [lon, lat], zoom, duration: 900, essential: true });
  }

  /** Frames the top guesses; one faint far-off guess must not zoom out to the whole world. */
  fitToResult(): void {
    const r = this.result;
    if (!r || !r.guesses.length) return;
    const pts: [number, number][] = [];
    const top = r.guesses[0];
    pts.push([top.lon, top.lat]);
    for (const g of r.guesses.slice(1)) {
      if (g.confidence >= 0.25 * top.confidence) pts.push([g.lon, g.lat]);
    }
    for (const a of r.analysts) {
      if (a.ok && a.guesses[0]) pts.push([a.guesses[0].lon, a.guesses[0].lat]);
    }
    if (r.exif_gps) pts.push([r.exif_gps.lon, r.exif_gps.lat]);
    if (pts.length === 1) {
      this.map.flyTo({ center: pts[0], zoom: 6.2, duration: 900, essential: true });
      return;
    }
    const bounds = new LngLatBounds(pts[0], pts[0]);
    pts.forEach((p) => bounds.extend(p));
    this.map.fitBounds(bounds, {
      padding: { top: 90, bottom: 80, left: 70, right: 70 },
      maxZoom: 5.4,
      duration: 900,
      essential: true,
    });
  }

  // ----------------------------------------------------------- export

  /**
   * The current view as a PNG: basemap, heat and circles from the WebGL canvas, then the pins
   * (DOM markers, so redrawn here), an optional photo inset and a caption strip.
   */
  async snapshot(caption: { title: string; lines: string[] }, photo: ImageBitmap | null): Promise<Blob> {
    const map = this.map;
    await new Promise<void>((resolve) => {
      map.once('render', () => resolve());
      map.triggerRepaint();
    });
    const src = map.getCanvas();
    const dpr = src.width / Math.max(1, src.clientWidth);
    const w = src.clientWidth;
    const capH = 30 + 18 * caption.lines.length;
    const h = src.clientHeight + capH;
    const out = document.createElement('canvas');
    out.width = Math.round(w * dpr);
    out.height = Math.round(h * dpr);
    const ctx = out.getContext('2d');
    if (!ctx) throw new Error('No 2D canvas');
    ctx.scale(dpr, dpr);
    ctx.drawImage(src, 0, 0, w, src.clientHeight);
    const dark = this.theme === 'dark';
    const col = CONF_COLOR[this.theme];
    const font = (px: number, weight = 600) => `${weight} ${px}px "IBM Plex Sans", "Segoe UI", system-ui, sans-serif`;
    const r = this.result;
    const disc = (x: number, y: number, rad: number, fill: string, text: string, ring = '#ffffff') => {
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.shadowColor = 'rgba(0,0,0,0.35)';
      ctx.shadowBlur = 6;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = 2;
      ctx.strokeStyle = ring;
      ctx.stroke();
      ctx.fillStyle = dark ? '#0b0f14' : '#ffffff';
      ctx.font = font(rad > 14 ? 13 : 11, 700);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, x, y + 0.5);
    };
    if (r) {
      if (r.exif_gps) {
        const p = map.project([r.exif_gps.lon, r.exif_gps.lat]);
        disc(p.x, p.y, 11, '#f59e0b', '★', dark ? '#0b0f14' : '#ffffff');
      }
      for (const a of r.analysts) {
        if (!a.ok) continue;
        a.guesses.forEach((g, gi) => {
          const p = map.project([g.lon, g.lat]);
          disc(p.x, p.y, 10, cssVar(a.provider === 'claude' ? '--claude' : '--chatgpt'), `${a.provider === 'claude' ? 'C' : 'G'}${gi ? gi + 1 : ''}`);
        });
      }
      for (let i = r.guesses.length - 1; i >= 0; i--) {
        const g = r.guesses[i];
        const p = map.project([g.lon, g.lat]);
        disc(p.x, p.y, i === 0 ? 16 : 14, col[g.label], String(i + 1), i === this.selected ? '#3b82f6' : '#ffffff');
      }
    }
    if (photo) {
      const maxW = Math.min(220, w * 0.28);
      const scale = Math.min(maxW / photo.width, (src.clientHeight * 0.4) / photo.height);
      const pw = photo.width * scale;
      const ph = photo.height * scale;
      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,0.35)';
      ctx.shadowBlur = 10;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(12, 12, pw + 6, ph + 6);
      ctx.restore();
      ctx.drawImage(photo, 15, 15, pw, ph);
    }
    // Caption strip
    const y0 = src.clientHeight;
    ctx.fillStyle = dark ? '#11161d' : '#ffffff';
    ctx.fillRect(0, y0, w, capH);
    ctx.fillStyle = dark ? '#2a313c' : '#e3e6ea';
    ctx.fillRect(0, y0, w, 1);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = dark ? '#e8edf3' : '#111827';
    ctx.font = font(14, 650);
    ctx.fillText(caption.title, 14, y0 + 21);
    ctx.font = font(12, 450);
    ctx.fillStyle = dark ? '#9ba6b8' : '#4b5563';
    caption.lines.forEach((l, i) => ctx.fillText(l, 14, y0 + 21 + 18 * (i + 1)));
    ctx.textAlign = 'right';
    ctx.fillStyle = dark ? '#6b7686' : '#9aa3af';
    ctx.font = font(11, 500);
    ctx.fillText('GeoLock', w - 14, y0 + 21);
    return new Promise<Blob>((resolve, reject) => {
      out.toBlob((b) => (b ? resolve(b) : reject(new Error('The map could not be saved as an image.'))), 'image/png');
    });
  }

  zoomBy(delta: number): void {
    if (delta > 0) this.map.zoomIn({ duration: 250 });
    else this.map.zoomOut({ duration: 250 });
  }

  resize(): void {
    this.map.resize();
  }

  destroy(): void {
    this.destroyed = true;
    this.pins.forEach((m) => m.remove());
    this.pins = [];
    this.map.remove();
  }
}

/** The live map, for components outside MapView (inspector pins, toolbar buttons). */
export const mapHandle: { current: GeoMap | null } = { current: null };
