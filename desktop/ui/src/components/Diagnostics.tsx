import { useEffect, useState } from 'react';
import { AlertTriangle, Copy, Gauge, Loader2 } from 'lucide-react';
import { getBenchmark, runBenchmark } from '../lib/api';
import { updateSettings } from '../lib/controller';
import { deviceLabel, errorText, formatSeconds } from '../lib/format';
import { toast, useStore } from '../lib/store';
import type { Benchmark, DeviceName } from '../lib/types';
import { Button, cx } from './ui';
import { APP_VERSION } from '../version';

/** Which processor ran, why it fell back, how long things took, and a speed test that
 *  compares the GPU, NPU and CPU on this computer. */
export function DeviceDiagnostics() {
  const status = useStore((s) => s.status);
  const requested = useStore((s) => s.settings?.device ?? 'AUTO');
  const d = status?.diagnostics ?? null;
  const [bench, setBench] = useState<Benchmark | null>(null);
  const [running, setRunning] = useState(false);
  const ready = status?.state === 'ready';

  useEffect(() => {
    if (!ready) { setBench(null); return; }
    getBenchmark().then((b) => setBench(b.rows.length ? b : null)).catch(() => undefined);
  }, [ready, d?.device]);

  const test = async () => {
    setRunning(true);
    try {
      setBench(await runBenchmark());
    } catch (e) {
      toast('error', "Couldn't run the speed test", errorText(e));
    } finally {
      setRunning(false);
    }
  };

  const copy = () => {
    const text = JSON.stringify({ version: APP_VERSION, available: status?.available_devices, diagnostics: d, speed_test: bench?.rows ?? null }, null, 2);
    void navigator.clipboard?.writeText(text).then(
      () => toast('info', 'Details copied', 'Paste them into a message to share them.'),
      () => toast('error', "Couldn't copy the details"),
    );
  };

  if (!d) return null;
  const okRows = bench?.rows.filter((r) => r.ok && r.ms != null) ?? [];
  const fastest = okRows.length ? okRows.reduce((a, b) => ((b.ms ?? Infinity) < (a.ms ?? Infinity) ? b : a)).device : null;
  const last = d.last_locate;

  return (
    <div className="flex flex-col gap-3">
      {d.fallback && (
        <div role="status" className="flex gap-2.5 rounded-xl border border-medium/30 bg-medium/10 px-3.5 py-2.5 text-[12.5px] leading-relaxed">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-medium" />
          <span>{d.fallback}</span>
        </div>
      )}

      <dl className="grid grid-cols-[150px_1fr] gap-x-3 gap-y-1.5 rounded-xl bg-surface-2 px-3.5 py-3 text-[12.5px]">
        <dt className="text-fg-3">Asked for</dt>
        <dd>{d.requested === 'AUTO' ? 'Auto' : deviceLabel(d.requested)}</dd>
        <dt className="text-fg-3">Running on</dt>
        <dd>{deviceLabel(d.device)}{d.device_name ? <span className="text-fg-3"> · {d.device_name}</span> : null}</dd>
        <dt className="text-fg-3">Model start-up</dt>
        <dd className="tnum">{formatSeconds(d.compile_ms)}<span className="text-fg-3"> to prepare, {formatSeconds(d.load_ms)} until ready</span></dd>
        <dt className="text-fg-3">Vision, per photo</dt>
        <dd className="tnum">{formatSeconds(d.last_run_ms)}{d.first_run_ms != null && <span className="text-fg-3"> · first run {formatSeconds(d.first_run_ms)}</span>}</dd>
        <dt className="text-fg-3">Last photo</dt>
        <dd className="tnum">
          {last?.timings?.total_ms != null ? (
            <>
              {formatSeconds(last.timings.total_ms)} in total on {deviceLabel(last.device)}
              <span className="text-fg-3">
                {' · '}vision {formatSeconds(last.timings.clip_ms)}
                {last.timings.ocr_ms != null ? ` · text ${formatSeconds(last.timings.ocr_ms)}` : ''}
                {last.timings.llm_ms != null ? ` · opinions ${formatSeconds(last.timings.llm_ms)}` : ''}
              </span>
            </>
          ) : <span className="text-fg-3">No photo yet since the models loaded</span>}
        </dd>
      </dl>

      {bench && (
        <table className="w-full text-left text-[12.5px]">
          <thead className="text-[11.5px] text-fg-3">
            <tr className="border-b border-border">
              <th className="py-1.5 font-medium">Processor</th>
              <th className="py-1.5 font-medium">Per photo</th>
              <th className="py-1.5 font-medium">Start-up</th>
              <th className="py-1.5" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {bench.rows.map((r) => (
              <tr key={r.device} className="border-b border-border last:border-b-0">
                <td className="py-2 pr-3 align-top">
                  <div className="font-medium">{deviceLabel(r.device)}</div>
                  {r.name && <div className="max-w-[230px] truncate text-[11.5px] text-fg-3" title={r.name}>{r.name}</div>}
                </td>
                {r.ok ? (
                  <>
                    <td className="py-2 align-top tnum">
                      <span className={cx(r.device === fastest && 'font-semibold text-high')}>{formatSeconds(r.ms)}</span>
                      {r.device === fastest && okRows.length > 1 && <span className="ml-1.5 text-[11px] text-high">fastest</span>}
                    </td>
                    <td className="py-2 align-top text-fg-3 tnum">{formatSeconds(r.compile_ms)}</td>
                  </>
                ) : (
                  <td colSpan={2} className="py-2 align-top text-[12px] text-fg-3">{r.error ?? 'Did not run'}</td>
                )}
                <td className="py-2 text-right align-top">
                  {r.ok && r.device !== requested && (
                    <Button size="sm" variant="ghost" onClick={() => void updateSettings({ device: r.device as DeviceName })}>Use</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" disabled={!ready || running} onClick={() => void test()}>
          {running ? <Loader2 size={14} className="animate-spin-slow" /> : <Gauge size={14} />}
          {running ? 'Testing each processor…' : bench ? 'Test again' : 'Test speed on each processor'}
        </Button>
        <Button variant="ghost" onClick={copy}><Copy size={14} /> Copy details</Button>
      </div>
      {running && <p className="text-[12px] text-fg-3">This prepares the model on every processor once, so it can take up to a minute the first time.</p>}
    </div>
  );
}
