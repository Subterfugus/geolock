import { Check, Cpu, FolderOpen, Info, Keyboard, Library, Loader2, Map as MapIcon, MessageSquareText, Palette, RefreshCw, ScanText, Trash2 } from 'lucide-react';
import { useRef, useState, type ReactNode } from 'react';
import { clearLibrary, recheckAnalysts, updateSettings } from '../lib/controller';
import { ANALYST_COMPANY, ANALYST_NAME, deviceLabel } from '../lib/format';
import { revealDataFolder } from '../lib/shell';
import { patch, useStore } from '../lib/store';
import type { MapStyleKind, Provider, Settings as SettingsT, ThemeMode } from '../lib/types';
import { Button, Dialog, Segmented, Switch, cx } from './ui';
import { isTauri } from '../lib/backend';
import { APP_VERSION } from '../version';
import { DeviceDiagnostics } from './Diagnostics';
import { ModelPickers, ProviderMark } from './AskPanel';
import { SHORTCUTS } from './Overlays';
import { Kbd } from './ui';

const LABEL_ID = 'settings-title';

export function SettingsDialog() {
  const open = useStore((s) => s.settingsOpen);
  const close = () => patch({ settingsOpen: false });
  const settings = useStore((s) => s.settings);
  if (!open) return null;
  return (
    <Dialog open={open} onClose={close} title="Settings" labelledById={LABEL_ID} width={880}>
      {settings ? <SettingsBody settings={settings} /> : <div className="p-8 text-center text-fg-3">Loading settings…</div>}
    </Dialog>
  );
}

const NAV: { id: string; label: string; icon: ReactNode }[] = [
  { id: 'processor', label: 'Processor', icon: <Cpu size={14} /> },
  { id: 'analysis', label: 'Analysis', icon: <ScanText size={14} /> },
  { id: 'second-opinion', label: 'Second opinion', icon: <MessageSquareText size={14} /> },
  { id: 'map', label: 'Map', icon: <MapIcon size={14} /> },
  { id: 'appearance', label: 'Appearance', icon: <Palette size={14} /> },
  { id: 'library', label: 'Library', icon: <Library size={14} /> },
  { id: 'shortcuts', label: 'Shortcuts', icon: <Keyboard size={14} /> },
  { id: 'about', label: 'About', icon: <Info size={14} /> },
];

function Section({ id, title, hint, children }: { id?: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section id={id ? `settings-${id}` : undefined} data-section={id} className="scroll-mt-2 border-b border-border px-6 py-5 last:border-b-0">
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
  const scroller = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState('processor');
  const go = (id: string) => {
    setActive(id);
    const el = scroller.current?.querySelector<HTMLElement>(`[data-section="${id}"]`);
    if (el && scroller.current) scroller.current.scrollTo({ top: el.offsetTop - 4, behavior: 'smooth' });
  };
  const onScroll = () => {
    const box = scroller.current;
    if (!box) return;
    const secs = Array.from(box.querySelectorAll<HTMLElement>('[data-section]'));
    const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 4;
    const cur = atEnd ? secs[secs.length - 1] : secs.filter((el) => el.offsetTop - box.scrollTop <= 40).pop();
    if (cur?.dataset.section) setActive(cur.dataset.section);
  };
  return (
    <div className="flex h-[min(640px,calc(100vh-140px))] min-h-0">
      <nav aria-label="Settings sections" className="flex w-[190px] shrink-0 flex-col gap-0.5 border-r border-border bg-surface-2 p-2">
        {NAV.map((n) => (
          <button
            key={n.id}
            type="button"
            onClick={() => go(n.id)}
            aria-current={active === n.id ? 'true' : undefined}
            className={cx(
              'flex h-8 items-center gap-2.5 rounded-[3px] px-2.5 text-left text-[13px] transition-colors',
              active === n.id ? 'bg-fg text-bg' : 'text-fg-2 hover:bg-surface-3 hover:text-fg',
            )}
          >
            {n.icon}{n.label}
          </button>
        ))}
      </nav>
      <div ref={scroller} onScroll={onScroll} className="relative min-w-0 flex-1 overflow-y-auto">
        <SettingsSections settings={settings} />
      </div>
    </div>
  );
}

function SettingsSections({ settings }: { settings: SettingsT }) {
  const status = useStore((s) => s.status);
  const mapStyle = useStore((s) => s.mapStyle);
  const reloading = status?.state === 'loading';
  const available = new Set(status?.available_devices ?? []);
  const device = (['AUTO', 'GPU', 'NPU', 'CPU'] as const);
  return (
    <div>
      <Section id="processor" title="Processor" hint="Where the AI models run. Auto picks the fastest one this computer has.">
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
        {reloading || !status?.diagnostics ? (
          <div className="flex items-center gap-2 text-[12.5px] text-fg-3">
            {reloading ? (
              <><Loader2 size={13} className="animate-spin-slow" /> Reloading models…</>
            ) : (
              <>Running on {deviceLabel(status?.device)}{status?.device_name ? ` · ${status.device_name}` : ''}</>
            )}
          </div>
        ) : <DeviceDiagnostics />}
      </Section>

      <Section id="analysis" title="Analysis" hint="What GeoLock looks at on every photo. Changes apply to the next photo or re-analysis.">
        <Row label="Read text in photos" hint="Signs, shop names and street labels are strong clues." control={<Switch label="Read text in photos" checked={settings.read_text} onChange={(v) => void updateSettings({ read_text: v })} />} />
        <Row
          label="Look up sign text on OpenStreetMap"
          hint="Shop and street names GeoLock reads are searched on OpenStreetMap, which can pin a photo to one town. Sends the text only, never the photo. Needs internet; adds a few seconds."
          control={<Switch label="Look up sign text on OpenStreetMap" checked={settings.osm_lookup ?? false} onChange={(v) => void updateSettings({ osm_lookup: v })} />}
        />
        <Row label="Show the photo's own GPS" hint="If the photo has a location tag, it is shown on the map for comparison. It is never used for the guess." control={<Switch label="Show the photo's own GPS" checked={settings.show_exif_gps} onChange={(v) => void updateSettings({ show_exif_gps: v })} />} />
      </Section>

      <Section id="second-opinion" title="Second opinion" hint="Optional. Ask Claude or ChatGPT about a photo with a click, using your own login. Nothing is sent automatically. The model and effort you pick here are also on each photo.">
        <div className="grid grid-cols-1 gap-2.5">
          <AnalystCard provider="claude" />
          <AnalystCard provider="chatgpt" />
        </div>
        <Row
          label="Share GeoLock's findings with them"
          hint="Off gives the analyst the photo alone, for a fully independent opinion."
          control={<Switch label="Share GeoLock's findings" checked={settings.share_findings} onChange={(v) => void updateSettings({ share_findings: v })} />}
        />
        <Row
          label="Let them search the web"
          hint="They look up shop names, street names and phone numbers they read, to confirm the exact place. Slower, but often much more precise. The photo itself is never searched."
          control={<Switch label="Let them search the web" checked={settings.analyst_web_search ?? true} onChange={(v) => void updateSettings({ analyst_web_search: v })} />}
        />
        <p className="rounded-xl bg-surface-2 px-3.5 py-3 text-[12px] leading-relaxed text-fg-3">
          The photo is sent without GPS or other metadata, to Anthropic (Claude) or OpenAI (ChatGPT), through the tool you signed in to with your own plan. GeoLock does not keep their accounts or send them anything else.
        </p>
      </Section>

      <Section id="map" title="Map" hint="Streets and Satellite come from OpenStreetMap and Esri over the internet; GeoLock falls back to the offline map when there is no connection.">
        <Row
          label="Map style"
          hint="Streets shows roads, buildings and landmarks. Satellite adds road and place names on top of aerial photos. Offline shows countries and regions only."
          control={
            <Segmented<MapStyleKind>
              label="Map style"
              value={settings.map_style}
              onChange={(v) => { patch({ mapStyle: v }); void updateSettings({ map_style: v }); }}
              options={[{ value: 'streets', label: 'Streets' }, { value: 'satellite', label: 'Satellite' }, { value: 'offline', label: 'Offline' }]}
            />
          }
        />
        <span className="sr-only">Current map: {mapStyle}</span>
      </Section>

      <Section id="appearance" title="Appearance">
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
      </Section>

      <Section id="library" title="Library">
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

      <Section id="shortcuts" title="Keyboard shortcuts">
        <ul className="flex flex-col gap-2">
          {SHORTCUTS.map((k) => (
            <li key={k.what} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="text-fg-2">{k.what}</span>
              <span className="flex shrink-0 items-center gap-1 text-fg-2">{k.keys.map((x) => <Kbd key={x}>{x}</Kbd>)}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="about" title="About">
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
        <ProviderMark provider={provider} size={26} />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">{name}</div>
          <div className="text-[11.5px] text-fg-3">{ANALYST_COMPANY[provider]}</div>
        </div>
        <span className={cx('inline-flex items-center gap-1 rounded-[3px] px-2 py-0.5 text-[11.5px] font-medium', ok ? 'bg-pos/15 text-pos' : 'bg-surface-3 text-fg-3')}>
          {ok ? <Check size={11} strokeWidth={3} /> : null}
          {ok ? 'Available' : 'Not set up'}
        </span>
      </div>
      <p className="text-[12px] leading-snug text-fg-2">{st?.detail ?? 'Checking…'}</p>
      <div className="flex items-center gap-2">
        <span className="w-[86px] shrink-0 text-[12px] text-fg-3">Model, effort</span>
        <ModelPickers provider={provider} compact />
      </div>
      <Button size="sm" variant="secondary" className="self-start" onClick={() => void recheckAnalysts()}>
        <RefreshCw size={12} /> Check login and models again
      </Button>
    </div>
  );
}
