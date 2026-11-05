// Formatting and small browser helpers shared by the views.

export const n = (x: number) => x.toLocaleString("en-US");

/** A length in bases: 3,099,922,541 bp, or 3.10 Gb in tight places. */
export function bp(x: number, short = false): string {
  if (!short) return `${n(x)} bp`;
  for (const [unit, size] of [["Gb", 1e9], ["Mb", 1e6], ["kb", 1e3]] as const) {
    if (x >= size) return `${(x / size).toFixed(x >= 10 * size ? 1 : 2)} ${unit}`;
  }
  return `${x} bp`;
}

export function bytes(x: number): string {
  if (x >= 1e6) return `${(x / 1e6).toFixed(2)} MB`;
  if (x >= 1e3) return `${(x / 1e3).toFixed(1)} kB`;
  return `${x} B`;
}

/** Offer text as a file to save. */
export function download(filename: string, text: string, type = "text/plain"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const message = (e: unknown) => String((e as Error)?.message ?? e);
