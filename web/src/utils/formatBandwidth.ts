export function formatBytes(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)} GB`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} MB`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} KB`;
  return `${n} B`;
}

export function formatMbps(n: number): string {
  if (n >= 1) return `${n.toFixed(2)} Mbit/s`;
  if (n * 1000 >= 1) return `${(n * 1000).toFixed(2)} kbit/s`;
  return `${(n * 1_000_000).toFixed(0)} bit/s`;
}
