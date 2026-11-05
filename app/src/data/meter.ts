// Count what the app downloads, per action: the spike's measurement of
// whether a static catalog is enough. Every catalog read goes through
// meteredFetch.

export interface Tally { requests: number; bytes: number; ms: number }

type Listener = (action: string, tally: Tally, total: Tally) => void;

const total: Tally = { requests: 0, bytes: 0, ms: 0 };
let current: Tally | null = null;
const listeners: Listener[] = [];

export function onMeasure(f: Listener): void { listeners.push(f); }

export function totals(): Tally { return { ...total }; }

/** Run an action and report the requests, bytes and time it took. */
export async function measure<T>(action: string, f: () => Promise<T>): Promise<T> {
  const outer = current;
  const tally: Tally = { requests: 0, bytes: 0, ms: 0 };
  current = tally;
  const t0 = performance.now();
  try {
    return await f();
  } finally {
    tally.ms = performance.now() - t0;
    current = outer;
    if (outer) { outer.requests += tally.requests; outer.bytes += tally.bytes; }
    else for (const l of listeners) l(action, tally, totals());
  }
}

/** fetch, counted: one request, and the bytes of its body. */
export async function meteredFetch(url: string, init?: RequestInit): Promise<ArrayBuffer> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  const body = await r.arrayBuffer();
  for (const t of [total, current]) if (t) { t.requests += 1; t.bytes += body.byteLength; }
  return body;
}
