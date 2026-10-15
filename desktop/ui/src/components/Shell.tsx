import { PanelRight } from 'lucide-react';
import { useEffect } from 'react';
import { addPhotos, askDelete, enqueue, moveSelection } from '../lib/controller';
import { isPhotoFile } from '../lib/files';
import { mapHandle } from '../lib/map/mapController';
import { getState, patch, toast, useStore } from '../lib/store';
import { Inspector } from './Inspector';
import { Library } from './Library';
import { MapView } from './MapView';
import { ConfirmDialog, DropOverlay, Lightbox, ShortcutsPopover, Toasts } from './Overlays';
import { SettingsDialog } from './Settings';
import { IconButton } from './ui';

/** The main window: library, map and inspector, plus the global overlays. */
export function Shell() {
  useGlobalKeys();
  useFileDrop();
  const inspectorOpen = useStore((s) => s.inspectorOpen);
  return (
    <div className="flex h-full w-full overflow-hidden">
      <Library />
      <div className="relative min-w-0 flex-1">
        <MapView />
        {!inspectorOpen && (
          <div className="absolute right-4 top-3 z-20">
            <IconButton label="Show inspector" className="glass h-9 w-9" onClick={() => patch({ inspectorOpen: true })}>
              <PanelRight size={16} />
            </IconButton>
          </div>
        )}
      </div>
      <Inspector />
      <Toasts />
      <ConfirmDialog />
      <SettingsDialog />
      <ShortcutsPopover />
      <DropOverlay />
      <Lightbox />
    </div>
  );
}

function useGlobalKeys(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
      const mod = e.ctrlKey || e.metaKey;
      const s = getState();
      if (mod && !e.altKey && (e.key === 'o' || e.key === 'O')) {
        e.preventDefault();
        void addPhotos();
        return;
      }
      if (mod && !e.altKey && e.key === ',') {
        e.preventDefault();
        patch({ settingsOpen: true });
        return;
      }
      if (e.key === 'Escape') {
        if (s.shortcutsOpen) patch({ shortcutsOpen: false });
        if (s.lightboxOpen) patch({ lightboxOpen: false });
        return;
      }
      if (typing || mod || e.altKey || s.confirm || s.settingsOpen || s.lightboxOpen || s.status?.state !== 'ready') return;
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          moveSelection(1);
          break;
        case 'ArrowUp':
          e.preventDefault();
          moveSelection(-1);
          break;
        case 'Delete':
          if (s.selectedId) {
            e.preventDefault();
            askDelete(s.selectedId);
          }
          break;
        case 'f':
        case 'F':
          mapHandle.current?.fitToResult();
          break;
        case '?':
          patch({ shortcutsOpen: !s.shortcutsOpen });
          break;
        case '[':
          patch({ sidebarOpen: !s.sidebarOpen });
          break;
        case ']':
          patch({ inspectorOpen: !s.inspectorOpen });
          break;
        default:
          break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}

/** Drag and drop anywhere, and paste. In the shell, file drops arrive as paths from the webview. */
function useFileDrop(): void {
  useEffect(() => {
    let depth = 0;
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');
    const onEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth += 1;
      patch({ dropActive: true });
    };
    const onOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    };
    const onLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) patch({ dropActive: false });
    };
    const onDrop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      patch({ dropActive: false });
      const files = Array.from(e.dataTransfer?.files ?? []);
      const photos = files.filter(isPhotoFile);
      if (photos.length) enqueue(photos);
      else if (files.length) toast('error', 'That is not a photo', 'GeoLock reads JPEG, PNG, WebP, HEIC, TIFF and BMP files.');
    };
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.items ?? [])
        .filter((i) => i.kind === 'file')
        .map((i) => i.getAsFile())
        .filter((f): f is File => !!f);
      if (!files.length) return;
      e.preventDefault();
      enqueue(files);
    };
    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragover', onOver);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('drop', onDrop);
    window.addEventListener('paste', onPaste);
    return () => {
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('drop', onDrop);
      window.removeEventListener('paste', onPaste);
    };
  }, []);
}

