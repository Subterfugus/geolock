import type { Result } from '../lib/types';

/** Outlines of the text GeoLock read, drawn in the photo's own pixel space so they line up at any size. */
export function Ocr({ result }: { result: Result }) {
  const { width: w, height: h } = result.image;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
      {result.ocr.map((l, i) => (
        <polygon
          key={i}
          points={l.box.map((p) => p.join(',')).join(' ')}
          fill="rgb(255 212 0 / 0.14)"
          stroke="#ffd400"
          strokeWidth={1.6}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}
