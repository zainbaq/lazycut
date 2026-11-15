/** `M:SS.s` (or `H:MM:SS.s`), the clock format used everywhere in the app. */
export function clock(seconds: number | null | undefined, decimals = 1): string {
  if (seconds == null || !Number.isFinite(seconds)) return "–";
  const factor = 10 ** decimals;
  const total = Math.max(0, Math.round(seconds * factor) / factor);
  const whole = Math.floor(total);
  const frac = total - whole;
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = (whole % 60) + frac;
  const secs = s.toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${secs}` : `${m}:${secs}`;
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export function shortDate(value: string | number): string {
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function titleFromFile(name: string): string {
  return name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
}

/** "just now", "2 min ago", "3 h ago", "4 days ago", else a short date. */
export function ago(value: string | null | undefined, now = Date.now()): string {
  if (!value) return "–";
  const t = new Date(value).getTime();
  if (Number.isNaN(t)) return "–";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 14) return `${d} ${d === 1 ? "day" : "days"} ago`;
  return shortDate(value);
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
