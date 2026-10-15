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
  dark: { ocean: '#0d0d0c', land: '#1d1c1a', border: '#3d3b36', admin: '#2d2c28', label: '#9a968b', halo: '#1d1c1a' },
  light: { ocean: '#d3d9d6', land: '#f6f3eb', border: '#bdb5a3', admin: '#d9d3c4', label: '#5d594f', halo: '#f6f3eb' },
};

/** OpenFreeMap: free, no key, OpenStreetMap data with roads, buildings, places and points of interest. */
export const STREETS_URL: Record<Theme, string> = {
  dark: 'https://tiles.openfreemap.org/styles/dark',
  light: 'https://tiles.openfreemap.org/styles/liberty',
};
/** Tried when the themed style fails, before giving up on the online map. */
export const STREETS_BACKUP_URL = 'https://tiles.openfreemap.org/styles/liberty';
const OPENFREEMAP_TILES = 'https://tiles.openfreemap.org/planet';

/** How far each map can zoom: the offline basemap only has borders, so it stops at region level. */
export const MAX_ZOOM: Record<MapStyleKind, number> = { offline: 9, streets: 19, satellite: 19 };

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

export function onlineStyle(kind: 'streets' | 'satellite', theme: Theme, backup = false): string | StyleSpecification {
  if (kind === 'streets') return backup ? STREETS_BACKUP_URL : STREETS_URL[theme];
  // Satellite imagery with roads and place names on top (a "hybrid" map), labels in the bundled font.
  const halo = 'rgba(0,0,0,0.75)';
  const road = (cls: string[], minzoom: number, width: [number, number, number, number]) => ({
    type: 'line' as const, source: 'osm', 'source-layer': 'transportation', minzoom,
    filter: ['in', ['get', 'class'], ['literal', cls]],
    layout: { 'line-cap': 'round' as const, 'line-join': 'round' as const },
    paint: {
      'line-color': 'rgba(255,236,190,0.75)',
      'line-width': ['interpolate', ['exponential', 1.6], ['zoom'], width[0], width[1], width[2], width[3]],
    },
  });
  return {
    version: 8,
    name: 'Satellite',
    glyphs: glyphTemplate(),
    sources: {
      satellite: {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256,
        maxzoom: 19,
        attribution: 'Esri, Maxar, Earthstar Geographics',
      },
      osm: { type: 'vector', url: OPENFREEMAP_TILES },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#0a1017' } },
      { id: 'satellite', type: 'raster', source: 'satellite' },
      { id: 'roads-major', ...road(['motorway', 'trunk', 'primary'], 5, [5, 0.4, 18, 6]) },
      { id: 'roads-minor', ...road(['secondary', 'tertiary', 'minor', 'service'], 11, [11, 0.3, 18, 3.5]) },
      {
        id: 'road-names', type: 'symbol', source: 'osm', 'source-layer': 'transportation_name', minzoom: 13,
        layout: {
          'symbol-placement': 'line', 'text-field': ['coalesce', ['get', 'name:latin'], ['get', 'name']],
          'text-font': [FONT_STACK], 'text-size': 11,
        },
        paint: { 'text-color': '#ffffff', 'text-halo-color': halo, 'text-halo-width': 1.4 },
      },
      {
        id: 'places', type: 'symbol', source: 'osm', 'source-layer': 'place',
        filter: ['in', ['get', 'class'], ['literal', ['country', 'state', 'city', 'town', 'village', 'suburb', 'neighbourhood']]],
        layout: {
          'text-field': ['coalesce', ['get', 'name:latin'], ['get', 'name']],
          'text-font': [FONT_STACK],
          'text-size': ['match', ['get', 'class'], 'country', 14, 'state', 12, 'city', 14, 'town', 12.5, 11.5],
          'text-max-width': 8,
        },
        paint: { 'text-color': '#ffffff', 'text-halo-color': halo, 'text-halo-width': 1.6 },
      },
      {
        id: 'landmarks', type: 'symbol', source: 'osm', 'source-layer': 'poi', minzoom: 15,
        filter: ['<=', ['to-number', ['get', 'rank'], 99], 20],
        layout: { 'text-field': ['get', 'name'], 'text-font': [FONT_STACK], 'text-size': 10.5, 'text-max-width': 7 },
        paint: { 'text-color': '#ffe9b0', 'text-halo-color': halo, 'text-halo-width': 1.3 },
      },
    ],
  } as StyleSpecification;
}

export const ATTRIBUTION: Record<MapStyleKind, string> = {
  offline: 'Basemap © Natural Earth',
  streets: '© OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors',
  satellite: 'Imagery © Esri, Maxar, Earthstar Geographics · Labels © OpenStreetMap contributors',
};
