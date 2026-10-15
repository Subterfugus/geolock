import { open } from '@tauri-apps/plugin-dialog';
import { readFile } from '@tauri-apps/plugin-fs';
import { isTauri } from './backend';

export const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tif', 'tiff', 'heic', 'heif'];

const MIME: Record<string, string> = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif',
  bmp: 'image/bmp', tif: 'image/tiff', tiff: 'image/tiff', heic: 'image/heic', heif: 'image/heif',
};

const extOf = (name: string): string => (name.split('.').pop() ?? '').toLowerCase();

export function isPhotoFile(f: { name: string; type?: string }): boolean {
  return (f.type ?? '').startsWith('image/') || IMAGE_EXTENSIONS.includes(extOf(f.name));
}

export function baseName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/** Reads files the shell handed us by path (file picker or OS drag and drop). */
export async function filesFromPaths(paths: string[]): Promise<File[]> {
  const out: File[] = [];
  for (const p of paths) {
    const name = baseName(p);
    if (!IMAGE_EXTENSIONS.includes(extOf(name))) continue;
    const bytes = await readFile(p);
    out.push(new File([new Uint8Array(bytes)], name, { type: MIME[extOf(name)] ?? 'application/octet-stream' }));
  }
  return out;
}

/** Opens the photo picker: the native dialog in the shell, a file input in the browser. */
export async function pickPhotos(): Promise<File[]> {
  if (isTauri()) {
    const picked = await open({
      multiple: true,
      directory: false,
      filters: [{ name: 'Photos', extensions: IMAGE_EXTENSIONS }],
    });
    if (!picked) return [];
    return filesFromPaths(Array.isArray(picked) ? picked : [picked]);
  }
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
