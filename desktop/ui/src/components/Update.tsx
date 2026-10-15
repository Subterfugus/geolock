import { ArrowUpCircle, Download, ExternalLink, RefreshCw, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { cancelUpdateDownload, checkForUpdates, installUpdate, startUpdateDownload } from '../lib/controller';
import { formatDuration, formatMB } from '../lib/format';
import { openExternal } from '../lib/shell';
import { patch, useStore } from '../lib/store';
import type { UpdateInfo } from '../lib/types';
import { Button, Dialog, Spinner, cx } from './ui';

const LABEL_ID = 'update-title';

/** True when there is something to offer: a newer release, its download, or the finished installer. */
export const hasUpdate = (u: UpdateInfo | null): boolean =>
  !!u && (u.state === 'available' || u.state === 'downloading' || u.state === 'ready');

/** The Update button in the library footer and the collapsed rail; hidden when there is nothing new. */
export function UpdateButton({ compact }: { compact?: boolean }) {
  const u = useStore((s) => s.appUpdate);
  if (!hasUpdate(u)) return null;
  const label = u!.state === 'ready' ? `Install GeoLock ${u!.latest}` : `Update to GeoLock ${u!.latest}`;
  const pctDone = u!.state === 'downloading' && u!.progress ? Math.round(u!.progress.fraction * 100) : null;
  return (
    <button
      type="button"
      onClick={() => patch({ updateOpen: true })}
      title={label}
      aria-label={label}
      className={cx(
        'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-accent font-semibold text-accent-fg transition-colors hover:bg-accent-strong',
        compact ? 'w-9 justify-center' : 'px-2.5 text-[12.5px]',
      )}
    >
      {pctDone != null ? <Spinner size={13} /> : <ArrowUpCircle size={14} />}
      {!compact && (pctDone != null ? <span className="tnum">{pctDone}%</span> : 'Update')}
    </button>
  );
}

export function UpdateDialog() {
  const open = useStore((s) => s.updateOpen);
  const u = useStore((s) => s.appUpdate);
  const busy = useStore((s) => s.queue.length > 0 || Object.values(s.asking).some(Boolean));
  if (!open || !u) return null;
  const close = () => patch({ updateOpen: false });
  const tooBig = u.size_mb != null && u.free_disk_mb != null && u.free_disk_mb < u.size_mb * 1.2;

  let footer: ReactNode;
  if (u.state === 'available') {
    footer = (
      <>
        <Button variant="ghost" onClick={close}>Later</Button>
        <Button variant="primary" data-autofocus disabled={tooBig} onClick={() => void startUpdateDownload()}>
          <Download size={14} /> Download {u.size_mb != null ? formatMB(u.size_mb) : ''}
        </Button>
      </>
    );
  } else if (u.state === 'downloading') {
    footer = (
      <>
        <Button variant="ghost" onClick={() => void cancelUpdateDownload()}>Cancel download</Button>
        <Button variant="secondary" onClick={close}>Keep working</Button>
      </>
    );
  } else if (u.state === 'ready') {
    footer = (
      <>
        <Button variant="ghost" onClick={close}>Later</Button>
        <Button variant="primary" data-autofocus onClick={() => void installUpdate()}>
          <ArrowUpCircle size={14} /> Install and restart
        </Button>
      </>
    );
  } else {
    footer = (
      <>
        <Button variant="ghost" onClick={() => void openExternal(u.releases_url)}><ExternalLink size={13} /> Releases page</Button>
        <Button variant="secondary" disabled={u.state === 'checking'} onClick={() => void checkForUpdates()}>
          <RefreshCw size={13} /> Check again
        </Button>
      </>
    );
  }

  return (
    <Dialog
      open
      onClose={close}
      labelledById={LABEL_ID}
      width={560}
      title={u.latest && hasUpdate(u) ? `GeoLock ${u.latest} is available` : 'Updates'}
      footer={footer}
    >
      <div className="flex flex-col gap-4 px-5 py-4">
        {hasUpdate(u) ? (
          <p className="text-[13px] text-fg-2">
            You have {u.current}.{' '}
            {u.state === 'ready'
              ? 'The update is downloaded and checked. GeoLock closes, installs it, and opens again in about a minute. Your library, settings and models are kept.'
              : `The download is ${u.size_mb != null ? formatMB(u.size_mb) : 'the full installer'}. Nothing is downloaded until you click Download.`}
          </p>
        ) : (
          <p className="text-[13px] text-fg-2">
            {u.state === 'checking' ? 'Checking GitHub for a newer version…' : u.error ?? `GeoLock ${u.current} is the newest version.`}
          </p>
        )}

        {u.state === 'downloading' && <Progress u={u} />}
        {u.state === 'available' && u.error && <p className="rounded-md bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{u.error}</p>}
        {u.state === 'available' && tooBig && (
          <p className="rounded-md bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
            Only {formatMB(u.free_disk_mb)} is free on this drive. Free some space, then try again.
          </p>
        )}
        {u.state === 'ready' && busy && (
          <p className="rounded-md bg-surface-2 px-3 py-2 text-[12.5px] text-fg-2">A photo is still being analysed. Installing now stops it.</p>
        )}

        {hasUpdate(u) && u.notes && (
          <div className="max-h-[300px] overflow-y-auto rounded-md border border-border bg-surface-2 px-4 py-3">
            <ReleaseNotes text={u.notes} />
          </div>
        )}
        {hasUpdate(u) && (
          <p className="flex items-center gap-1.5 text-[11.5px] text-fg-3">
            <ShieldCheck size={12} className="shrink-0" /> Downloaded from the GeoLock releases on GitHub and checked against its published checksum before it runs.
          </p>
        )}
      </div>
    </Dialog>
  );
}

function Progress({ u }: { u: UpdateInfo }) {
  const p = u.progress;
  const fraction = p?.fraction ?? 0;
  return (
    <div>
      <div className="relative h-2 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(fraction * 100)}>
        <div className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out" style={{ width: `${Math.max(2, fraction * 100)}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 text-[12.5px] text-fg-2">
        <span className="tnum">{p?.message ?? (p ? `${Math.round(p.done_mb)} of ${Math.round(p.total_mb)} MB` : 'Starting…')}</span>
        <span className="text-fg-3 tnum">
          {p?.speed_mbps ? `${p.speed_mbps.toFixed(1)} MB/s` : ''}
          {p?.eta_s != null && p.eta_s > 0 ? ` · about ${formatDuration(p.eta_s)} left` : ''}
        </span>
      </div>
    </div>
  );
}

/** A small Markdown subset for release notes: headings, bullets, paragraphs, **bold** and `code`. */
export function ReleaseNotes({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul${blocks.length}`} className="ml-4 list-disc space-y-1">
        {bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}
      </ul>,
    );
    bullets = [];
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    if (/^\s{2,}\S/.test(line) && bullets.length) {
      bullets[bullets.length - 1] += ` ${line.trim()}`;
      continue;
    }
    flush();
    const h = /^#{1,6}\s+(.*)$/.exec(line);
    if (h) blocks.push(<h4 key={blocks.length} className="mt-1 text-[13px] font-semibold text-fg">{inline(h[1])}</h4>);
    else if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="flex flex-col gap-2 text-[12.5px] leading-relaxed text-fg-2">{blocks}</div>;
}

function inline(s: string): ReactNode[] {
  // Links keep their text; the app opens no links from release notes.
  const plain = s.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  return plain.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i} className="font-semibold text-fg">{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i} className="rounded bg-surface-3 px-1 font-mono text-[11.5px]">{part.slice(1, -1)}</code>;
    return part;
  });
}
