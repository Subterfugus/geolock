import { Check, FolderOpen, Info, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { clearLibrary, recheckAnalysts, updateSettings } from '../lib/controller';
import { ANALYST_COMPANY, ANALYST_NAME, deviceLabel } from '../lib/format';
import { revealDataFolder } from '../lib/shell';
import { patch, useStore } from '../lib/store';
import type { MapStyleKind, Provider, Settings as SettingsT, ThemeMode } from '../lib/types';
import { Button, Dialog, Segmented, Switch, cx } from './ui';
import { isTauri } from '../lib/backend';
import { APP_VERSION } from '../version';

const LABEL_ID = 'settings-title';

export function SettingsDialog() {
  const open = useStore((s) => s.settingsOpen);
  const close = () => patch({ settingsOpen: false });
  const settings = useStore((s) => s.settings);
  if (!open) return null;
  return (
    <Dialog open={open} onClose={close} title="Settings" labelledById={LABEL_ID} width={680}>
      {settings ? <SettingsBody settings={settings} /> : <div className="p-8 text-center text-fg-3">Loading settings…</div>}
    </Dialog>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border px-6 py-5 last:border-b-0">
      <h3 className="text-[13px] font-semibold">{title}</h3>
      {hint && <p className="mt-0.5 text-[12.5px] text-fg-3">{hint}</p>}
      <div className="mt-3.5 flex flex-col gap-3">{children}</div>
    </section>
  );
}

function Row({ label, hint, control }: { label: string; hint?: string; control: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6">
      <div className="min-w-0">
        <div className="text-[13.5px]">{label}</div>
        {hint && <div className="text-[12px] text-fg-3">{hint}</div>}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

function SettingsBody({ settings }: { settings: SettingsT }) {
  const status = useStore((s) => s.status);
  const mapStyle = useStore((s) => s.mapStyle);
  const reloading = status?.state === 'loading';
  const available = new Set(status?.available_devices ?? []);
  const device = (['AUTO', 'GPU', 'NPU', 'CPU'] as const);
  return (
    <div>
      <Section title="Processor" hint="Where the AI models run. Auto picks the fastest one this computer has.">
        <Segmented
          label="Processor"
          fullWidth
          value={settings.device}
          onChange={(v) => void updateSettings({ device: v })}
          options={device.map((d) => ({
            value: d,
            label: d === 'AUTO' ? 'Auto' : d,
            disabled: d !== 'AUTO' && !available.has(d) && available.size > 0,
            title: d === 'GPU' ? 'Intel Arc GPU' : d === 'NPU' ? 'Neural processing unit' : d === 'CPU' ? 'Processor cores' : 'Choose the fastest available',
          }))}
        />
        <div className="flex items-center gap-2 text-[12.5px] text-fg-3">
          {reloading ? (
            <><Loader2 size={13} className="animate-spin-slow" /> Reloading models…</>
          ) : (
            <>Running on {deviceLabel(status?.device)}{status?.device_name ? ` · ${status.device_name}` : ''}</>
          )}
        </div>
      </Section>

      <Section title="Analysis defaults">
        <Row label="Read text in photos" hint="Signs, shop names and street labels are strong clues." control={<Switch label="Read text in photos" checked={settings.read_text} onChange={(v) => void updateSettings({ read_text: v })} />} />
        <Row label="Show the photo's own GPS" hint="If the photo has a location tag, it is shown on the map for comparison. It is never used for the guess." control={<Switch label="Show the photo's own GPS" checked={settings.show_exif_gps} onChange={(v) => void updateSettings({ show_exif_gps: v })} />} />
      </Section>

      <Section title="Second opinion" hint="Optional. Ask Claude or ChatGPT about a photo with a click, using your own login. Nothing is sent automatically.">
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <AnalystCard provider="claude" />
          <AnalystCard provider="chatgpt" />
        </div>
        <Row
          label="Share GeoLock's findings with them"
          hint="Off gives the analyst the photo alone, for a fully independent opinion."
          control={<Switch label="Share GeoLock's findings" checked={settings.share_findings} onChange={(v) => void updateSettings({ share_findings: v })} />}
        />
        <p className="rounded-xl bg-surface-2 px-3.5 py-3 text-[12px] leading-relaxed text-fg-3">
          The photo is sent without GPS or other metadata, to Anthropic (Claude) or OpenAI (ChatGPT), through the tool you signed in to with your own plan. GeoLock does not keep their accounts or send them anything else.
        </p>
      </Section>

      <Section title="Library">
        <Row label="Keep history" hint="Results are saved on this computer. Turn off to only keep the current session." control={<Switch label="Keep history" checked={settings.keep_history} onChange={(v) => void updateSettings({ keep_history: v })} />} />
        <div className="flex flex-wrap gap-2 pt-1">
          <Button variant="outline" onClick={() => void revealDataFolder(status?.data_dir ?? '')}><FolderOpen size={14} /> Open data folder</Button>
          <Button variant="outline" className="text-danger hover:bg-danger-soft" onClick={() => patch({
            confirm: {
              title: 'Clear the whole library?',
              body: 'Every saved photo and its result is deleted from this computer. This cannot be undone.',
              confirmLabel: 'Clear library',
              danger: true,
              onConfirm: () => void clearLibrary(),
            },
          })}>
            <Trash2 size={14} /> Clear library
          </Button>
        </div>
      </Section>

      <Section title="Appearance">
        <Row
          label="Theme"
          control={
            <Segmented<ThemeMode>
              label="Theme"
              value={settings.theme}
              onChange={(v) => void updateSettings({ theme: v })}
              options={[{ value: 'system', label: 'System' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]}
            />
          }
        />
        <Row
          label="Default map style"
          hint="Streets and Satellite need an internet connection."
          control={
            <Segmented<MapStyleKind>
              label="Default map style"
              value={settings.map_style}
              onChange={(v) => { patch({ mapStyle: v }); void updateSettings({ map_style: v }); }}
              options={[{ value: 'offline', label: 'Offline' }, { value: 'streets', label: 'Streets' }, { value: 'satellite', label: 'Satellite' }]}
            />
          }
        />
        <span className="sr-only">Current map: {mapStyle}</span>
      </Section>

      <Section title="About">
        <div className="flex items-start gap-3">
          <Info size={15} className="mt-0.5 shrink-0 text-accent" />
          <div className="text-[13px] leading-relaxed text-fg-2">
            <div className="font-medium text-fg">GeoLock {APP_VERSION}{status?.version && status.version !== APP_VERSION ? ` · engine ${status.version}` : ''}</div>
            <div>Everything runs on this computer unless you ask Claude or ChatGPT.</div>
            <div className="mt-2 text-[12px] text-fg-3">
              Credits: OpenAI CLIP (MIT) · GeoCLIP (MIT) · RapidOCR and PaddleOCR (Apache-2.0) · Natural Earth (public domain) · GeoNames (CC BY 4.0) · MapLibre GL (BSD-3) · Noto Sans (OFL).
            </div>
          </div>
        </div>
        {!isTauri() && <p className="text-[11.5px] text-fg-3">Running in a browser for development. Desktop features are off.</p>}
      </Section>
    </div>
  );
}

function AnalystCard({ provider }: { provider: Provider }) {
  const st = useStore((s) => s.status?.analysts?.[provider]);
  const name = ANALYST_NAME[provider];
  const ok = !!st?.available;
  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-border bg-surface-2 p-3.5">
      <div className="flex items-center gap-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg text-[12px] font-bold text-white" style={{ background: provider === 'claude' ? 'var(--claude)' : 'var(--chatgpt)' }}>
          {provider === 'claude' ? 'C' : 'G'}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">{name}</div>
          <div className="text-[11.5px] text-fg-3">{ANALYST_COMPANY[provider]}</div>
        </div>
        <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium', ok ? 'bg-pos/15 text-pos' : 'bg-surface-3 text-fg-3')}>
          {ok ? <Check size={11} strokeWidth={3} /> : null}
          {ok ? 'Available' : 'Not set up'}
        </span>
      </div>
      <p className="min-h-[34px] text-[12px] leading-snug text-fg-2">{st?.detail ?? 'Checking…'}</p>
      <Button size="sm" variant="secondary" className="self-start" onClick={() => void recheckAnalysts()}>
        <RefreshCw size={12} /> Check again
      </Button>
    </div>
  );
}
