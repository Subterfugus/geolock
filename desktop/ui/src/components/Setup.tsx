import { CircleCheck, CircleX, FolderInput, HardDrive, Download, Cpu, Circle, AlertTriangle, Activity } from 'lucide-react';
import type { ReactNode } from 'react';
import { beginSetup, importFromFolder, stopSetup } from '../lib/controller';
import { pickFolder } from '../lib/files';
import { deviceLabel, formatDuration, formatMB } from '../lib/format';
import { useStore } from '../lib/store';
import type { SetupInfo, SetupStep } from '../lib/types';
import { MapView } from './MapView';
import { Button, Spinner, cx, LOGO_SRC } from './ui';

/** First-run onboarding: sits over a dimmed map and walks through download, setup and model loading. */
export function SetupScreen() {
  const status = useStore((s) => s.status);
  const setup = useStore((s) => s.setup);
  const settings = useStore((s) => s.settings);
  const state = status?.state;
  const running = !!setup?.running || state === 'setting_up';
  const failed = !running && (!!setup?.error || state === 'error');
  const loading = state === 'loading';

  let body: ReactNode;
  if (loading) body = <LoadingModels device={status?.device ?? settings?.device ?? null} />;
  else if (running) body = <Running setup={setup} />;
  else if (failed) body = <Failed message={setup?.error ?? status?.error ?? 'Something stopped the download.'} />;
  else body = <Intro setup={setup} />;

  return (
    <div className="relative h-full">
      <MapView dim />
      <div className="absolute inset-0 flex items-center justify-center overflow-y-auto p-6">
        <div className="pop-in w-full max-w-[540px] rounded-3xl border border-border bg-surface shadow-[var(--shadow)]">
          <div className="flex items-center gap-3 border-b border-border px-7 py-4">
            <img src={LOGO_SRC} alt="" className="h-7 w-7" />
            <span className="text-[14px] font-semibold tracking-[-0.01em]">GeoLock setup</span>
            <span className="ml-auto text-[12px] text-fg-3 tnum">Step {loading ? 3 : running ? 2 : 1} of 3</span>
          </div>
          {body}
        </div>
      </div>
    </div>
  );
}

function Intro({ setup }: { setup: SetupInfo | null }) {
  const free = setup?.free_disk_mb ?? 0;
  const enough = !setup || free === 0 || free >= setup.disk_needed_mb;
  return (
    <div className="px-7 pb-7 pt-6">
      <h1 className="text-[24px] font-semibold leading-tight tracking-[-0.025em]">Let's find where photos were taken</h1>
      <p className="mt-2.5 text-[14px] leading-relaxed text-fg-2">
        GeoLock runs entirely on this computer. It needs to download one AI model once. After that it works offline, and your photos never leave the machine.
      </p>
      <div className="mt-5 grid grid-cols-3 gap-2.5">
        <Stat icon={<Download size={15} />} label="Download" value={formatMB(setup?.download_mb)} />
        <Stat icon={<HardDrive size={15} />} label="Disk needed" value={formatMB(setup?.disk_needed_mb)} />
        <Stat icon={<HardDrive size={15} />} label="Free here" value={free ? formatMB(free) : '–'} warn={!enough} />
      </div>
      {setup?.source && <p className="mt-3 text-[12px] text-fg-3">Source: {setup.source}</p>}
      <div className="mt-6 flex flex-col gap-2.5">
        <Button variant="primary" size="lg" className="w-full" onClick={() => void beginSetup()}>
          <Download size={16} /> Download and set up ({formatMB(setup?.download_mb ?? 608)})
        </Button>
        <Button variant="ghost" className="w-full" onClick={() => void chooseFolder()}>
          <FolderInput size={15} /> Use models from an existing GeoLock folder…
        </Button>
      </div>
    </div>
  );
}

async function chooseFolder() {
  const folder = await pickFolder();
  if (folder) await importFromFolder(folder);
}

function Stat({ icon, label, value, warn }: { icon: ReactNode; label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2 px-3.5 py-3">
      <div className="flex items-center gap-1.5 text-[11.5px] text-fg-3">{icon}{label}</div>
      <div className={cx('mt-1 text-[16px] font-semibold tnum', warn && 'text-medium')}>{value}</div>
    </div>
  );
}

function Running({ setup }: { setup: SetupInfo | null }) {
  const p = setup?.progress ?? null;
  const fraction = p?.fraction ?? null;
  const steps = setup?.steps ?? [];
  return (
    <div className="px-7 pb-7 pt-6">
      <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Setting things up</h1>
      <p className="mt-1.5 text-[13.5px] text-fg-2">This happens once. You can leave this window open.</p>
      <ol className="setup-steps mt-6 flex flex-col gap-3">
        {steps.map((st) => <StepRow key={st.id} step={st} />)}
      </ol>
      <div className="mt-6">
        <div className="relative h-2 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={fraction != null ? Math.round(fraction * 100) : undefined}>
          {fraction != null ? (
            <div className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out" style={{ width: `${Math.max(2, fraction * 100)}%` }} />
          ) : (
            <div className="absolute inset-y-0 w-1/3 rounded-full bg-accent" style={{ animation: 'gl-bar 1.3s ease-in-out infinite' }} />
          )}
        </div>
        <div className="mt-2.5 flex items-center justify-between gap-3 text-[12.5px] text-fg-2">
          <span className="truncate tnum">{p?.message ?? 'Starting…'}</span>
          <span className="shrink-0 text-fg-3 tnum">
            {p?.speed_mbps ? `${p.speed_mbps.toFixed(1)} MB/s` : ''}
            {p?.eta_s != null && p.eta_s > 0 ? ` · about ${formatDuration(p.eta_s)} left` : ''}
          </span>
        </div>
      </div>
      <div className="mt-6 flex justify-end">
        <Button variant="ghost" onClick={() => void stopSetup()}>Cancel</Button>
      </div>
    </div>
  );
}

function StepRow({ step }: { step: SetupStep }) {
  const icon =
    step.state === 'done' ? <CircleCheck size={22} className="text-high" /> :
    step.state === 'error' ? <CircleX size={22} className="text-danger" /> :
    step.state === 'running' ? <Spinner size={18} className="text-accent" /> :
    <Circle size={20} className="text-fg-3" />;
  return (
    <li className={cx('relative flex items-center gap-3 text-[14px]', step.state === 'pending' ? 'text-fg-3' : 'text-fg')}>
      <span className="flex h-[22px] w-[22px] items-center justify-center">{icon}</span>
      <span className={cx(step.state === 'running' && 'font-medium')}>{step.label}</span>
    </li>
  );
}

function LoadingModels({ device }: { device: string | null }) {
  return (
    <div className="px-7 pb-8 pt-6">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent-soft text-accent"><Cpu size={20} /></div>
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.02em]">Loading models on {deviceLabel(device)}…</h1>
          <p className="text-[13px] text-fg-2">Compiling for your processor. This can take a minute the first time.</p>
        </div>
      </div>
      <div className="relative mt-7 h-1.5 overflow-hidden rounded-full bg-surface-3">
        <div className="absolute inset-y-0 w-1/3 rounded-full bg-accent" style={{ animation: 'gl-bar 1.3s ease-in-out infinite' }} />
      </div>
      <p className="mt-4 flex items-center gap-2 text-[12.5px] text-fg-3"><Activity size={13} /> Later starts are a few seconds.</p>
    </div>
  );
}

function Failed({ message }: { message: string }) {
  return (
    <div className="px-7 pb-7 pt-6">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-danger-soft text-danger"><AlertTriangle size={20} /></div>
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.02em]">Setup didn't finish</h1>
          <p className="text-[13px] text-fg-2">Your download is kept, so a retry picks up where it stopped.</p>
        </div>
      </div>
      <p className="mt-5 break-words rounded-xl bg-danger-soft px-4 py-3 text-[13px] text-danger">{message}</p>
      <div className="mt-6 flex flex-col gap-2.5">
        <Button variant="primary" size="lg" className="w-full" onClick={() => void beginSetup()}>Try again</Button>
        <Button variant="ghost" className="w-full" onClick={() => void chooseFolder()}>
          <FolderInput size={15} /> Use models from an existing GeoLock folder…
        </Button>
      </div>
    </div>
  );
}
