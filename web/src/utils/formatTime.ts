/** Unix seconds as a local hh:mm:ss clock time. */
export function formatTime(t: number): string {
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** "CoreSwitch retry in 2m": interfaces whose host list the firewall is too slow to send. */
export function formatHostsSlow(
  slow: { name: string; retry_at: number }[] | undefined,
  now: number = Date.now() / 1000,
): string | null {
  if (!Array.isArray(slow) || slow.length === 0) return null;
  return slow
    .map(({ name, retry_at }) => {
      const wait = Math.max(0, Math.round(retry_at - now));
      return `${name} retry in ${wait >= 60 ? `${Math.ceil(wait / 60)}m` : `${wait}s`}`;
    })
    .join(", ");
}
