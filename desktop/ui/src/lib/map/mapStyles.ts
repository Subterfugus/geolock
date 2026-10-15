import type { StyleSpecification } from 'maplibre-gl';
import type { MapStyleKind, ThemeMode } from '../types';

export type Theme = 'light' | 'dark';

export interface Palette {
  ocean: string;
  land: string;
  border: string;
  admin: string;
  label: string;
  halo: string;
}

export const PALETTE: Record<Theme, Palette> = {
  dark: { ocean: '#0a1017', land: '#1a2029', border: '#343c48', admin: '#2a313c', label: '#9ba6b8', halo: '#1a2029' },
  light: { ocean: '#d9e6f0', land: '#f7f5f0', border: '#c6c0b3', admin: '#dcd7cb', label: '#5a6372', halo: '#f7f5f0' },
};

export const STREETS_URL: Record<Theme, string> = {
  dark: 'https://tiles.openfreemap.org/styles/dark',
  light: 'https://tiles.openfreemap.org/styles/liberty',
};

/** Glyph PBFs are shipped in public/fonts; resolve them against the page so they work from the Tauri origin too. */
export function glyphTemplate(): string {
  return `${new URL('./', document.baseURI).href}fonts/{fontstack}/{range}.pbf`;
}

export const FONT_STACK = 'Noto Sans Regular';

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): Theme {
  if (mode === 'light' || mode === 'dark') return mode;
  return prefersDark ? 'dark' : 'light';
}

/** The offline basemap starts empty; countries, borders and labels are added once their data is loaded. */
export function offlineStyle(theme: Theme): StyleSpecification {
  const p = PALETTE[theme];
  return {
    version: 8,
    name: 'GeoLock offline',
    glyphs: glyphTemplate(),
    sources: {},
    layers: [{ id: 'background', type: 'background', paint: { 'background-color': p.ocean } }],
  };
}

export function onlineStyle(kind: 'streets' | 'satellite', theme: Theme): string | StyleSpecification {
  if (kind === 'streets') return STREETS_URL[theme];
  return {
    version: 8,
    name: 'Satellite',
    sources: {
      satellite: {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256,
        maxzoom: 19,
        attribution: 'Esri, Maxar, Earthstar Geographics',
      },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#0a1017' } },
      { id: 'satellite', type: 'raster', source: 'satellite' },
    ],
  };
}

export const ATTRIBUTION: Record<MapStyleKind, string> = {
  offline: 'Basemap © Natural Earth',
  streets: '© OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors',
  satellite: 'Imagery © Esri, Maxar, Earthstar Geographics',
};
