// A refbook catalog over HTTP: catalog.json, the small tables (downloaded
// whole, once), and root_blocks (read by range requests, never downloaded).
// Reads catalog format 2: a release (files at the top level) or a build
// (catalog.json maps each file to its step directory).
import { parquetReadObjects, type AsyncBuffer } from "hyparquet";
import { compressors } from "hyparquet-compressors";
import { meteredFetch } from "./meter.ts";

export const FORMAT = 2;

export interface Manifest {
  name: string;
  format: number;
  version: string;
  build?: boolean;
  files: Record<string, { path?: string; bytes: number; sha256?: string; role?: string }>;
}

/** BigInt (hyparquet's INT64) to number, all the way down; lengths fit in 2^53. */
function plain(v: unknown): any {
  if (typeof v === "bigint") return Number(v);
  if (Array.isArray(v)) return v.map(plain);
  if (v && typeof v === "object" && !(v instanceof Uint8Array)) {
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, plain(x)]));
  }
  return v;
}

/** A file read by HTTP range requests, for hyparquet. */
export function rangeBuffer(url: string, byteLength: number): AsyncBuffer {
  return {
    byteLength,
    slice: (start: number, end?: number) =>
      meteredFetch(url, { headers: { Range: `bytes=${start}-${(end ?? byteLength) - 1}` } }),
  };
}

export class Catalog {
  private tables = new Map<string, Promise<any[]>>();
  private docs = new Map<string, Promise<any>>();

  readonly url: string;
  readonly manifest: Manifest;

  private constructor(url: string, manifest: Manifest) {
    this.url = url;
    this.manifest = manifest;
  }

  static async open(url: string): Promise<Catalog> {
    const base = url.endsWith("/") ? url : url + "/";
    const manifest: Manifest = JSON.parse(new TextDecoder().decode(await meteredFetch(base + "catalog.json")));
    if (manifest.format !== FORMAT) {
      throw new Error(`${base} is catalog format ${manifest.format ?? 1}; this app reads format ${FORMAT}`);
    }
    return new Catalog(base, manifest);
  }

  has(name: string): boolean { return name in this.manifest.files; }

  /** A file's URL and size. */
  file(name: string): { url: string; bytes: number } {
    const f = this.manifest.files[name];
    if (!f) throw new Error(`the catalog has no ${name}`);
    return { url: this.url + (f.path ?? name), bytes: f.bytes };
  }

  /** A small table, every row as an object; downloaded once. */
  table<T = any>(name: string): Promise<T[]> {
    let t = this.tables.get(name);
    if (!t) {
      t = (async () => {
        const body = await meteredFetch(this.file(name).url);
        return plain(await parquetReadObjects({ file: body, compressors }));
      })();
      this.tables.set(name, t);
    }
    return t;
  }

  /** A JSON document of the catalog, e.g. collections/<digest>.json; downloaded once. */
  json<T = any>(name: string): Promise<T> {
    let d = this.docs.get(name);
    if (!d) {
      d = meteredFetch(this.file(name).url).then((b) => JSON.parse(new TextDecoder().decode(b)));
      this.docs.set(name, d);
    }
    return d;
  }
}
