import 'maplibre-gl/dist/maplibre-gl.css';
import { Globe, Map as MapIcon, Maximize2, Plus, Minus, Satellite, Wifi } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';
import { GeoMap, mapHandle } from '../lib/map/mapController';
import { getState, patch, toast, useStore } from '../lib/store';
import { selectGuess } from '../lib/controller';
import type { MapStyleKind } from '../lib/types';
import { IconButton, Segmented } from './ui';
import { ATTRIBUTION } from '../lib/map/mapStyles';
import { Welcome } from './Welcome';
import { deviceLabel } from '../lib/format';
import { Spinner } from './ui';

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
    }, { zoom: getState().status?.state === 'ready' ? 1.7 : 1.15 });
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
    <div className="absolute inset-0 overflow-hidden bg-bg" data-testid="map">
      {/* MapLibre adds its own position:relative to this element, so it sits inside an absolute wrapper. */}
      <div ref={el} className="h-full w-full" aria-label="Map" role="region" />
      {dim && (
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'radial-gradient(ellipse 60% 55% at 50% 50%, rgb(0 0 0 / 0.15), var(--scrim) 85%)' }}
        />
      )}

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
            {mapStyle !== 'offline' && (
              <div className="flex items-center gap-1 px-1.5 text-[11px] text-fg-3">
                <Wifi size={11} /> Needs internet
              </div>
            )}
          </div>

          <div className="pointer-events-none absolute bottom-1 left-0 right-0 text-center text-[10.5px] text-fg-3">
            <span className="rounded bg-bg/50 px-1.5 py-px backdrop-blur-sm">{ATTRIBUTION[mapStyle]}</span>
          </div>
        </>
      )}

      {!dim && <Banner />}
      {!dim && <Welcome />}
    </div>
  );
}

/** Top-centre notice: connection trouble, or models reloading after a settings change. */
function Banner() {
  const lost = useStore((s) => s.connectionLost);
  const loading = useStore((s) => s.status?.state === 'loading');
  const device = useStore((s) => s.status?.device ?? null);
  if (!lost && !loading) return null;
  return (
    <div className="pointer-events-none absolute left-1/2 top-3 z-20 -translate-x-1/2 fade-in">
      <div className="glass flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[12.5px] text-fg-2">
        {lost ? (
          <><span className="h-2 w-2 rounded-full bg-danger" /> Lost contact with the engine. Reconnecting…</>
        ) : (
          <><Spinner size={13} className="text-accent" /> Loading models on {deviceLabel(device)}…</>
        )}
      </div>
    </div>
  );
}
