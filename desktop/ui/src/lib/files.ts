import { open } from '@tauri-apps/plugin-dialog';
import { isTauri } from './backend';

export const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tif', 'tiff', 'heic', 'heif'];


const extOf = (name: string): string => (name.split('.').pop() ?? '').toLowerCase();

export function isPhotoFile(f: { name: string; type?: string }): boolean {
  return (f.type ?? '').startsWith('image/') || IMAGE_EXTENSIONS.includes(extOf(f.name));
}

export function baseName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/** Opens the photo picker. WebView2 shows the native Windows dialog for a file input, and
 *  hands back File objects directly, so no file-system permission is needed. */
export async function pickPhotos(): Promise<File[]> {
  return new Promise<File[]>((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*,.heic,.heif';
    input.multiple = true;
    input.addEventListener('change', () => resolve([...(input.files ?? [])]));
    input.addEventListener('cancel', () => resolve([]));
    input.click();
  });
}

/** Prompt-based folder entry for the browser dev mode (no native dialog there). */
export async function pickFolder(): Promise<string | null> {
  if (isTauri()) {
    const picked = await open({ directory: true, multiple: false, title: 'Choose a GeoLock models folder' });
    return typeof picked === 'string' ? picked : null;
  }
  const value = window.prompt('Path to an existing GeoLock models folder (the one with clip_vision.xml):');
  return value && value.trim() ? value.trim() : null;
}

/** Opens a folder picker and returns every photo in it, subfolders included; null when
 *  cancelled. WebView2 shows the native folder dialog for a directory input. */
export async function pickPhotoFolder(): Promise<File[] | null> {
  return new Promise<File[] | null>((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.webkitdirectory = true;
    input.multiple = true;
    input.addEventListener('change', () => resolve(sortByPath([...(input.files ?? [])].filter(isPhotoFile))));
    input.addEventListener('cancel', () => resolve(null));
    input.click();
  });
}

const relPath = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;

function sortByPath(files: File[]): File[] {
  return files.sort((a, b) => relPath(a).localeCompare(relPath(b), undefined, { numeric: true }));
}

/** Files from a drop, walking into dropped folders. Falls back to the flat file list. */
export async function filesFromDrop(dt: DataTransfer): Promise<File[]> {
  const entries = Array.from(dt.items ?? [])
    .filter((i) => i.kind === 'file')
    .map((i) => i.webkitGetAsEntry?.() ?? null);
  if (!entries.length || entries.some((e) => !e) || !entries.some((e) => e?.isDirectory)) {
    return Array.from(dt.files ?? []);
  }
  const out: File[] = [];
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile) {
      const f = await new Promise<File | null>((res) => (entry as FileSystemFileEntry).file(res, () => res(null)));
      if (f) out.push(f);
      return;
    }
    if (!entry.isDirectory) return;
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries returns at most 100 entries per call; keep reading until it returns none.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res) => reader.readEntries(res, () => res([])));
      if (!batch.length) break;
      for (const e of batch) await walk(e);
    }
  };
  for (const e of entries) if (e) await walk(e);
  return sortByPath(out);
}
