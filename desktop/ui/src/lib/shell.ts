import { openUrl, revealItemInDir } from '@tauri-apps/plugin-opener';
import { isTauri } from './backend';
import { toast } from './store';

/** Opens a web link in the user's browser. */
export async function openExternal(url: string): Promise<void> {
  try {
    if (isTauri()) await openUrl(url);
    else window.open(url, '_blank', 'noopener,noreferrer');
  } catch (e) {
    toast('error', "Couldn't open the link", e instanceof Error ? e.message : String(e));
  }
}

/** Shows the data folder in Explorer; in the browser the path is copied instead. */
export async function revealDataFolder(dir: string): Promise<void> {
  if (!dir) {
    toast('info', 'The data folder is set by the desktop app');
    return;
  }
  if (!isTauri()) {
    await navigator.clipboard?.writeText(dir).catch(() => undefined);
    toast('info', 'Data folder path copied', dir);
    return;
  }
  try {
    await revealItemInDir(dir);
  } catch (e) {
    toast('error', "Couldn't open the data folder", e instanceof Error ? e.message : String(e));
  }
}

export async function copyText(text: string, what: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast('success', `${what} copied`, text);
  } catch {
    toast('error', "Couldn't copy", text);
  }
}
