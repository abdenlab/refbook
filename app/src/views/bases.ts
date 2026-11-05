// The bases of a region as lines of segments: runs of N, runs the operations
// changed (with the bases as submitted), and the rest.

export const LINE = 60;

export interface Segment { text: string; kind: "" | "n" | "changed"; submitted?: string }
export interface Line { pos: number; segments: Segment[] }

const N = 78;

export function lines(start: number, bases: Uint8Array, root: Uint8Array): Line[] {
  const decode = (a: Uint8Array) => new TextDecoder().decode(a);
  const kind = (k: number): Segment["kind"] => (bases[k] !== root[k] ? "changed" : bases[k] === N ? "n" : "");
  const out: Line[] = [];
  for (let i = 0; i < bases.length; i += LINE) {
    const end = Math.min(i + LINE, bases.length);
    const segments: Segment[] = [];
    for (let j = i; j < end;) {
      const c = kind(j);
      let k = j + 1;
      while (k < end && kind(k) === c) k++;
      segments.push({ text: decode(bases.subarray(j, k)), kind: c,
                      ...(c === "changed" ? { submitted: decode(root.subarray(j, k)) } : {}) });
      j = k;
    }
    out.push({ pos: start + i + 1, segments });
  }
  return out;
}

/** A region typed as chr:1,000-2,000 (1-based, inclusive) as [start, end), 0-based. */
export function parseLocus(text: string, length: number): [number, number] | null {
  const m = /^\s*(?:[^:]+:)?([\d,]+)\s*[-–]\s*([\d,]+)\s*$/.exec(text);
  if (!m) return null;
  const [s, e] = [Number(m[1].replaceAll(",", "")), Number(m[2].replaceAll(",", ""))];
  if (!(s >= 1 && e >= s && e <= length)) return null;
  return [s - 1, e];
}
