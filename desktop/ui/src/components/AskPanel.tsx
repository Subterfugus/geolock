import { Check, Square } from 'lucide-react';
import { useEffect, useState } from 'react';
import { askAnalyst, loadModels, stopAnalyst, updateSettings } from '../lib/controller';
import { ANALYST_NAME, effortLabel } from '../lib/format';
import { useStore } from '../lib/store';
import type { AnalystLive, Effort, ModelChoice, Provider, ProviderModels, Result } from '../lib/types';
import { Button, cx, Select, Spinner, Switch } from './ui';

export const PROVIDER_VAR: Record<Provider, string> = { claude: 'var(--claude)', chatgpt: 'var(--chatgpt)' };
const PROVIDERS: Provider[] = ['claude', 'chatgpt'];

/** The square brand mark used for each analyst. */
export function ProviderMark({ provider, size = 18 }: { provider: Provider; size?: number }) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-[3px] font-mono font-semibold text-white"
      style={{ background: PROVIDER_VAR[provider], width: size, height: size, fontSize: Math.round(size * 0.55) }}
      aria-hidden="true"
    >
      {provider === 'claude' ? 'C' : 'G'}
    </span>
  );
}

/** The efforts that apply to the chosen model (Codex models list their own). */
export function effortsFor(models: ProviderModels | undefined, modelId: string): Effort[] {
  const m = models?.models.find((x) => x.id === modelId);
  return m?.efforts?.length ? m.efforts : models?.efforts ?? ['low', 'medium', 'high'];
}

/** Model and reasoning-effort pickers for one analyst; the choice is saved in Settings. */
export function ModelPickers({ provider, compact = false }: { provider: Provider; compact?: boolean }) {
  const settings = useStore((s) => s.settings);
  const models = useStore((s) => s.models?.[provider]);
  useEffect(() => { void loadModels(); }, []);
  if (!settings) return null;
  const modelKey = `${provider}_model` as const;
  const effortKey = `${provider}_effort` as const;
  const model = settings[modelKey];
  const effort = settings[effortKey];
  const list: ModelChoice[] = models?.models ?? [{ id: '', name: 'Default' }];
  // A model typed into settings.json by hand still shows up.
  const options = (list.some((m) => m.id === model) ? list : [...list, { id: model, name: model }])
    .map((m) => ({ value: m.id, label: m.id ? m.name : 'Default model', title: m.description }));
  const efforts = effortsFor(models, model);
  const current = list.find((m) => m.id === model);
  const effortOptions = [
    { value: '' as Effort, label: current?.default_effort ? `Default (${effortLabel(current.default_effort)})` : 'Default effort' },
    ...efforts.map((e) => ({ value: e, label: effortLabel(e) })),
  ];
  if (effort && !efforts.includes(effort)) effortOptions.push({ value: effort, label: effortLabel(effort) });
  return (
    <div className={cx('grid min-w-0 grid-cols-2 gap-1.5', compact && 'flex-1')}>
      <Select
        label={`${ANALYST_NAME[provider]} model`}
        title="Model"
        value={model}
        options={options}
        onChange={(v) => {
          const next = effortsFor(models, v);
          void updateSettings({ [modelKey]: v, ...(effort && !next.includes(effort) ? { [effortKey]: '' } : {}) });
        }}
      />
      <Select<Effort>
        label={`${ANALYST_NAME[provider]} reasoning effort`}
        title="Reasoning effort: higher thinks longer and uses more of your plan"
        value={effort}
        options={effortOptions}
        onChange={(v) => void updateSettings({ [effortKey]: v })}
      />
    </div>
  );
}

/** Ask Claude / Ask ChatGPT, with the model and effort right there and live progress while it works. */
export function AskPanel({ result }: { result: Result }) {
  const status = useStore((s) => s.status?.analysts ?? {});
  const asking = useStore((s) => s.asking[result.id]);
  const anyAsking = useStore((s) => Object.values(s.asking).some(Boolean));
  const share = useStore((s) => s.settings?.share_findings ?? true);
  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface-2">
      {PROVIDERS.map((p, i) => {
        const st = status[p];
        const available = !!st?.available;
        const answered = result.analysts.some((a) => a.provider === p && a.ok);
        return (
          <div key={p} className={cx('px-3 py-2.5', i > 0 && 'border-t border-border')}>
            {asking === p ? (
              <LiveProgress provider={p} resultId={result.id} />
            ) : (
              <>
                <div className="flex items-center gap-2.5">
                  <ProviderMark provider={p} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-semibold">{ANALYST_NAME[p]}</div>
                    <div className="truncate text-[11px] text-fg-3" title={st?.detail}>{available ? st?.detail : 'Not set up yet'}</div>
                  </div>
                  <Button
                    size="sm"
                    variant={available ? 'primary' : 'secondary'}
                    disabled={!available || anyAsking}
                    title={available ? `Send the photo to ${ANALYST_NAME[p]}` : st?.detail ?? 'Not set up'}
                    onClick={() => void askAnalyst(result.id, p)}
                  >
                    {answered ? 'Ask again' : `Ask ${ANALYST_NAME[p]}`}
                  </Button>
                </div>
                {available ? (
                  <div className="mt-2 pl-[28px]"><ModelPickers provider={p} /></div>
                ) : (
                  <p className="mt-1.5 pl-[28px] text-[11.5px] leading-snug text-fg-3">{st?.detail ?? 'Checking…'}</p>
                )}
              </>
            )}
          </div>
        );
      })}
      <div className="flex items-center justify-between gap-3 border-t border-border bg-surface px-3 py-2">
        <span className="text-[11.5px] leading-snug text-fg-3">
          {share ? "Sends the photo and GeoLock's findings." : 'Sends the photo only.'} No GPS or metadata. Nothing is sent until you click.
        </span>
        <Switch label="Share GeoLock's findings" checked={share} onChange={(v) => void updateSettings({ share_findings: v })} />
      </div>
    </div>
  );
}

const STEPS: { stage: AnalystLive['stage'] | 'merge'; label: (n: string) => string }[] = [
  { stage: 'preparing', label: () => 'Preparing the photo and sign close-ups' },
  { stage: 'starting', label: (n) => `Waiting for ${n} to start` },
  { stage: 'thinking', label: (n) => `${n} is studying the photo and checking online` },
  { stage: 'writing', label: () => 'Writing its answer' },
  { stage: 'merge', label: () => "Blending it with GeoLock's guess" },
];

function stepIndex(live: AnalystLive | null): number {
  if (!live) return 0;
  switch (live.stage) {
    case 'preparing': return 0;
    case 'starting': return 1;
    case 'thinking': return 2;
    case 'writing': return 3;
    default: return 4;
  }
}

/** The running analyst: steps, elapsed time, what it is thinking about, and Stop. */
function LiveProgress({ provider, resultId }: { provider: Provider; resultId: string }) {
  const startedAt = useStore((s) => s.askStartedAt);
  const progress = useStore((s) => s.analystProgress);
  const settings = useStore((s) => s.settings);
  const [now, setNow] = useState(Date.now());
  const [stopping, setStopping] = useState(false);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, []);
  const raw = progress?.providers?.[provider] ?? null;
  // Ignore what is left over from an earlier ask.
  const live = raw && raw.started * 1000 >= startedAt - 2000 ? raw : null;
  const step = stepIndex(live);
  const name = ANALYST_NAME[provider];
  const secs = Math.max(0, Math.floor((now - startedAt) / 1000));
  const elapsed = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
  const model = live?.model ?? (settings?.[`${provider}_model`] || 'default model');
  const effort = live?.effort ?? settings?.[`${provider}_effort`] ?? '';
  return (
    <div aria-live="polite">
      <div className="flex items-center gap-2.5">
        <ProviderMark provider={provider} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[13px] font-semibold">
            Asking {name}
            <span className="mono text-[12px] font-normal text-fg-2">{elapsed}</span>
          </div>
          <div className="truncate text-[11px] text-fg-3">
            <span className="mono">{model}</span> · {effortLabel(effort)}
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={stopping}
          onClick={() => { setStopping(true); void stopAnalyst(resultId); }}
          title="Stop waiting. The photo keeps the result it had."
        >
          {stopping ? <Spinner size={12} /> : <Square size={11} fill="currentColor" />} {stopping ? 'Stopping' : 'Stop'}
        </Button>
      </div>
      <ol className="mt-2.5 flex flex-col gap-1 pl-[28px]">
        {STEPS.map((s, i) => {
          const done = i < step;
          const active = i === step;
          return (
            <li key={s.stage} className={cx('flex items-start gap-2 text-[12px] leading-snug', done ? 'text-fg-2' : active ? 'text-fg' : 'text-fg-3')}>
              <span className="mt-[3px] flex h-3 w-3 shrink-0 items-center justify-center">
                {done ? <Check size={12} strokeWidth={2.5} className="text-pos" /> : active ? <Spinner size={11} className="text-accent" /> : <span className="h-1.5 w-1.5 bg-border-strong" />}
              </span>
              <span className="min-w-0">
                {s.label(name)}
                {active && s.stage === 'thinking' && (live?.searches ?? 0) > 0 && (
                  <span className="text-fg-3"> · {live!.searches} {live!.searches === 1 ? 'search' : 'searches'}</span>
                )}
                {active && s.stage === 'thinking' && live?.note && (
                  <span className="mt-0.5 block truncate text-[11.5px] italic text-fg-3" title={live.note}>“{live.note}”</span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="mt-2.5 ml-[28px] h-[3px] overflow-hidden bg-surface-3">
        <div className="h-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.min(96, 6 + step * 22 + (step === 2 ? Math.min(14, (live?.chars ?? 0) / 400) : 0))}%` }} />
      </div>
      <div className="mt-1 ml-[28px] flex justify-between text-[10.5px] text-fg-3">
        <span>Usually under a minute or two; web searches and higher effort take longer.</span>
        {live && live.chars > 0 && <span className="mono shrink-0 whitespace-nowrap">{live.chars.toLocaleString()} chars</span>}
      </div>
    </div>
  );
}
