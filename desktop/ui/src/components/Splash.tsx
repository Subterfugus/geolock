import { AlertTriangle, FolderOpen, Copy, RotateCw } from 'lucide-react';
import { revealDataFolder } from '../lib/shell';
import { copyText } from '../lib/shell';
import { useStore } from '../lib/store';
import { Button, LOGO_SRC } from './ui';

/** Shown while the Python engine starts. */
export function Splash() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 fade-in">
      <img src={LOGO_SRC} alt="" className="h-20 w-20 drop-shadow-[0_10px_30px_rgb(79_110_247/0.35)]" style={{ animation: 'gl-pulse 2.2s ease-in-out infinite' }} />
      <div className="text-center">
        <div className="text-[15px] font-medium text-fg">Starting GeoLock…</div>
        <div className="mt-1 text-[12.5px] text-fg-3">Warming up the engine on this computer</div>
      </div>
      <div className="relative h-1 w-44 overflow-hidden rounded-full bg-surface-3">
        <div className="absolute inset-y-0 w-1/3 rounded-full bg-accent" style={{ animation: 'gl-bar 1.3s ease-in-out infinite' }} />
      </div>
    </div>
  );
}

/** The engine did not answer for a minute: point the user at its log. */
export function BootError() {
  const logFile = useStore((s) => s.logFile);
  const dataDir = useStore((s) => s.dataDir);
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="pop-in w-full max-w-[480px] rounded-3xl border border-border bg-surface p-7 shadow-[var(--shadow)]">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-danger-soft text-danger"><AlertTriangle size={20} /></div>
        <h1 className="mt-4 text-[20px] font-semibold tracking-[-0.02em]">GeoLock's engine didn't start</h1>
        <p className="mt-2 text-[13.5px] leading-relaxed text-fg-2">
          It has not answered for a minute. Restarting the app usually fixes this. If it keeps happening, the details are in the log file.
        </p>
        {logFile && (
          <div className="mt-4 flex items-center gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2.5">
            <code className="min-w-0 flex-1 truncate text-[12px] text-fg-2" title={logFile}>{logFile}</code>
            <button type="button" aria-label="Copy log path" onClick={() => void copyText(logFile, 'Log path')} className="rounded-md p-1.5 text-fg-3 hover:bg-surface-3 hover:text-fg"><Copy size={14} /></button>
          </div>
        )}
        <div className="mt-6 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => window.location.reload()}><RotateCw size={14} /> Try again</Button>
          <Button variant="ghost" onClick={() => void revealDataFolder(dataDir ?? '')}><FolderOpen size={14} /> Open data folder</Button>
        </div>
      </div>
    </div>
  );
}

/** The backend reported its own fatal error. */
export function FatalError() {
  const message = useStore((s) => s.status?.error) ?? 'Something went wrong while starting the models.';
  const dataDir = useStore((s) => s.dataDir ?? s.status?.data_dir ?? null);
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="pop-in w-full max-w-[480px] rounded-3xl border border-border bg-surface p-7 shadow-[var(--shadow)]">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-danger-soft text-danger"><AlertTriangle size={20} /></div>
        <h1 className="mt-4 text-[20px] font-semibold tracking-[-0.02em]">GeoLock couldn't load its models</h1>
        <p className="mt-3 break-words rounded-xl bg-danger-soft px-4 py-3 text-[13px] text-danger">{message}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => window.location.reload()}><RotateCw size={14} /> Restart</Button>
          <Button variant="ghost" onClick={() => void revealDataFolder(dataDir ?? '')}><FolderOpen size={14} /> Open data folder</Button>
        </div>
      </div>
    </div>
  );
}
