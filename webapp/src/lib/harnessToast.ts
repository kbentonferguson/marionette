/** How long a StatusBar harness-toast stays readable. */

export function toastDurationMs(message: string): number {
  const text = (message || "").toLowerCase();
  if (
    text.includes("unavailable")
    || text.includes("failed")
    || text.includes("error")
    || text.includes("refused")
  ) {
    return 12000;
  }
  return 4000;
}
