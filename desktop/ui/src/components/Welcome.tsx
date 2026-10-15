import { FolderInput, FolderOpen, ImagePlus, MapPin } from 'lucide-react';
import { addFolder, addPhotos } from '../lib/controller';
import { deviceLabel } from '../lib/format';
import { useStore } from '../lib/store';
import { Button, Kbd } from './ui';

/** Shown over the map while the library is empty. */
export function Welcome() {
  const empty = useStore((s) => s.history !== null && s.history.length === 0 && s.queue.length === 0 && s.status?.state === 'ready');
  const device = useStore((s) => s.status?.device);
  if (!empty) return null;
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6 fade-in">
      <div className="pointer-events-auto glass flex w-full max-w-[460px] flex-col items-center rounded-md px-8 py-9 text-center">
        <div className="relative mb-6 flex h-[120px] w-[168px] items-center justify-center">
          <div className="absolute inset-0 rounded-[22px] border-[1.5px] border-dashed border-accent/50 bg-accent-soft" />
          <span className="absolute inset-0 rounded-[22px] border border-accent/30" style={{ animation: 'gl-ring 2.4s ease-out infinite' }} />
          <ImagePlus size={40} className="relative text-accent" strokeWidth={1.6} style={{ animation: 'gl-float 3.2s ease-in-out infinite' }} />
          <MapPin size={26} className="absolute -right-3 -top-3 text-accent" fill="currentColor" fillOpacity={0.2} />
        </div>
        <h2 className="text-[20px] font-semibold tracking-[-0.02em]">Where was this photo taken?</h2>
        <p className="mt-2 max-w-[360px] text-[14px] leading-relaxed text-fg-2">
          Drop photos or a whole folder anywhere, paste one with <span className="inline-flex items-center gap-1 align-middle"><Kbd>Ctrl</Kbd><Kbd>V</Kbd></span>, or press <span className="inline-flex items-center gap-1 align-middle"><Kbd>Ctrl</Kbd><Kbd>O</Kbd></span> to choose files.
        </p>
        <div className="mt-6 flex items-center gap-2">
          <Button variant="primary" size="lg" onClick={() => void addPhotos()}>
            <FolderInput size={16} /> Add photos
          </Button>
          <Button size="lg" onClick={() => void addFolder()}>
            <FolderOpen size={16} /> Add a folder
          </Button>
        </div>
        <p className="mt-5 text-[12px] text-fg-3">
          Runs on your {deviceLabel(device)} · nothing leaves this computer
        </p>
      </div>
    </div>
  );
}
