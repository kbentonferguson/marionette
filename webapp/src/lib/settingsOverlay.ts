/** Latch so Settings survives RightPane remounts and right-rail collapse. */

let settingsOverlayOpen = false;
const listeners = new Set<() => void>();

export function subscribeSettingsOverlay(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function isSettingsOverlayOpen(): boolean {
  return settingsOverlayOpen;
}

export function setSettingsOverlayOpen(open: boolean): void {
  if (settingsOverlayOpen === open) return;
  settingsOverlayOpen = open;
  listeners.forEach(listener => listener());
}

export function resetSettingsOverlay(): void {
  setSettingsOverlayOpen(false);
}
