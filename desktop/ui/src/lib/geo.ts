const R = 6371.0088;
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

/** Great-circle distance in km. */
export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLat = rad(lat2 - lat1);
  const dLon = rad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** A circle of `radiusKm` on the sphere, as a closed [lon, lat] ring for GeoJSON. */
export function geodesicCircle(lat: number, lon: number, radiusKm: number, steps = 96): [number, number][] {
  const d = Math.max(radiusKm, 0.05) / R;
  const φ1 = rad(lat);
  const λ1 = rad(lon);
  const ring: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const brg = (i / steps) * 2 * Math.PI;
    const φ2 = Math.asin(Math.sin(φ1) * Math.cos(d) + Math.cos(φ1) * Math.sin(d) * Math.cos(brg));
    const λ2 = λ1 + Math.atan2(Math.sin(brg) * Math.sin(d) * Math.cos(φ1), Math.cos(d) - Math.sin(φ1) * Math.sin(φ2));
    let lo = deg(λ2);
    if (lo > 180) lo -= 360;
    if (lo < -180) lo += 360;
    ring.push([lo, deg(φ2)]);
  }
  return ring;
}

export type LngLat = [number, number];
