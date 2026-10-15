import 'maplibre-gl/dist/maplibre-gl.css';
import { Globe, Map as MapIcon, Maximize2, Plus, Minus, Satellite, Wifi } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';
import { GeoMap, mapHandle } from '../lib/map/mapController';
import { getState, patch, toast, useStore } from '../lib/store';
import { selectGuess } from '../lib/controller';
import type { MapStyleKind } from '../lib/types';
import { cx, IconButton, Segmented } from './ui';
import { ATTRIBUTION } from '../lib/map/mapStyles';
import { Welcome } from './Welcome';

const STYLE_OPTIONS: { value: MapStyleKind; label: ReactNode; title: string; disabled?: boolean }[] = [
  { value: 'offline', label: <span className="flex items-center gap-1.5"><Globe size={13} />Offline</span>, title: 'Works without internet' },
  { value: 'streets', label: <span className="flex items-center gap-1.5"><MapIcon size={13} />Streets</span>, title: 'Needs internet' },
  { value: 'satellite', label: <span className="flex items-center gap-1.5"><Satellite size={13} />Satellite</span>, title: 'Needs internet' },
];

/** The full-height map. Result overlays are drawn for the selected photo. */
export function MapView({ dim = false }: { dim?: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const theme = useStore((s) => s.themeResolved);
  const mapStyle = useStore((s) => s.mapStyle);
  const result = useStore((s) => (s.selectedId ? s.results[s.selectedId] ?? null : null));
  const sel = useStore((s) => s.selectedGuess);
  const last = useRef<{ id: string | null; sel: number; obj: unknown }>({ id: null, sel: 0, obj: null });

  // Create once. StrictMode mounts twice in development, so the instance is torn down on cleanup.
  useEffect(() => {
    const container = el.current;
    if (!container) return;
    const { mapStyle: style, themeResolved: mode } = getState();
    const map = new GeoMap(container, style, mode, {
      onGuessClick: (i) => selectGuess(i),
      onStyleFailed: () => {
        patch({ mapStyle: 'offline' });
        toast('error', "Couldn't load that map", 'Streets and Satellite need an internet connection. Showing the offline map.');
      },
    });
    mapHandle.current = map;
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(container);
    return () => {
      ro.disconnect();
      map.destroy();
      if (mapHandle.current === map) mapHandle.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    mapHandle.current?.setStyleKind(mapStyle, theme);
  }, [mapStyle, theme]);

  useEffect(() => {
    const m = mapHandle.current;
    if (!m) return;
    const prev = last.current;
    if (!result) {
      m.setResult(null);
      last.current = { id: null, sel: 0, obj: null };
      return;
    }
    if (prev.id !== result.id) {
      m.setResult(result, sel);
      m.fitToResult();
    } else if (prev.obj !== result) {
      m.setResult(result, sel);
    } else if (prev.sel !== sel) {
      m.highlight(sel);
      const g = result.guesses[sel];
      if (g) m.flyTo(g.lat, g.lon, g.radius_km);
    }
    last.current = { id: result.id, sel, obj: result };
  }, [result, sel]);

  return (
    <div className="relative h-full min-w-0 flex-1 overflow-hidden bg-bg" data-testid="map">
      <div ref={el} className="absolute inset-0" aria-label="Map" role="region" />
      {dim && <div className="pointer-events-none absolute inset-0" style={{ background: 'var(--scrim)' }} />}

      {!dim && (
        <>
          <div className="absolute bottom-4 right-4 flex flex-col overflow-hidden rounded-xl glass" role="group" aria-label="Map zoom">
            <IconButton label="Zoom in" className="h-9 w-9 rounded-none" onClick={() => mapHandle.current?.zoomBy(1)}><Plus size={16} /></IconButton>
            <span className="h-px bg-border" />
            <IconButton label="Zoom out" className="h-9 w-9 rounded-none" onClick={() => mapHandle.current?.zoomBy(-1)}><Minus size={16} /></IconButton>
            <span className="h-px bg-border" />
            <IconButton
              label="Fit to guesses (F)"
              className="h-9 w-9 rounded-none"
              disabled={!result}
              onClick={() => mapHandle.current?.fitToResult()}
            >
              <Maximize2 size={15} />
            </IconButton>
          </div>

          <div className="glass absolute bottom-4 left-4 flex flex-col gap-1.5 rounded-xl p-1.5">
            <Segmented
              size="sm"
              label="Map style"
              value={mapStyle}
              options={STYLE_OPTIONS}
              onChange={(v) => patch({ mapStyle: v })}
            />
            <div className={cx('flex items-center gap-1 px-1.5 text-[11px] text-fg-3', mapStyle === 'offline' && 'invisible')}>
              <Wifi size={11} /> Needs internet
            </div>
          </div>

          <div className="pointer-events-none absolute bottom-1 left-0 right-0 text-center text-[10.5px] text-fg-3">
            <span className="rounded bg-bg/50 px-1.5 py-px backdrop-blur-sm">{ATTRIBUTION[mapStyle]}</span>
          </div>
        </>
      )}

      {!dim && <Welcome />}
    </div>
  );
}
