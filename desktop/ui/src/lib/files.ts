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
