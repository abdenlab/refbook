// The bases of the hosted roots, from root_blocks.parquet by range requests:
// rows of (root_id, start, bases), 64 kb blocks sorted by root and start, in
// row groups of 32 blocks that never span roots (python/refbook/blocks.py).
// Opening reads the footer once. A region reads the row groups it overlaps,
// whole (hyparquet reads a row group's column chunk whole anyway), start and
// bases only, and keeps the last few in memory, so nearby views are free.
import { parquetMetadataAsync, parquetReadObjects, type FileMetaData, type AsyncBuffer } from "hyparquet";
import { compressors } from "hyparquet-compressors";
import { rangeBuffer, type Catalog } from "./catalog.ts";

export const BLOCK_SIZE = 65536;
const CACHED_GROUPS = 8;  // ~16 MB of bases

const text = (v: unknown) => (v instanceof Uint8Array ? new TextDecoder().decode(v) : String(v));

interface Group { rowStart: number; rows: number; firstBlock: number }

export class Blocks {
  /** root_id -> its row groups, in start order. */
  private groups = new Map<string, Group[]>();
  private cache = new Map<number, Promise<string>>();
  private file: AsyncBuffer;
  private metadata: FileMetaData;

  private constructor(file: AsyncBuffer, metadata: FileMetaData) {
    this.file = file;
    this.metadata = metadata;
    let row = 0;
    for (const rg of metadata.row_groups) {
      const stats = rg.columns[0].meta_data?.statistics;
      const min = stats?.min_value ?? stats?.min;
      if (min === undefined) throw new Error("root_blocks has no root_id statistics");
      const root = text(min);
      const gs = this.groups.get(root) ?? [];
      const rows = Number(rg.num_rows);
      gs.push({ rowStart: row, rows, firstBlock: gs.reduce((n, g) => n + g.rows, 0) });
      this.groups.set(root, gs);
      row += rows;
    }
  }

  static async open(cat: Catalog): Promise<Blocks> {
    const { url, bytes } = cat.file("root_blocks.parquet");
    const file = rangeBuffer(url, bytes);
    return new Blocks(file, await parquetMetadataAsync(file));
  }

  hosts(root: string): boolean { return this.groups.has(root); }

  /** A row group's bases, concatenated (it starts at its first block). */
  private group(g: Group): Promise<string> {
    let p = this.cache.get(g.rowStart);
    if (p) {
      this.cache.delete(g.rowStart);  // most recently used last
    } else {
      p = parquetReadObjects({
        file: this.file, metadata: this.metadata, compressors,
        columns: ["start", "bases"], rowStart: g.rowStart, rowEnd: g.rowStart + g.rows,
      }).then((rows) => {
        if (Number(rows[0].start) !== g.firstBlock * BLOCK_SIZE) throw new Error("root_blocks is not in block order");
        return rows.map((r) => r.bases as string).join("");
      });
      p.catch(() => this.cache.delete(g.rowStart));
    }
    this.cache.set(g.rowStart, p);
    while (this.cache.size > CACHED_GROUPS) this.cache.delete(this.cache.keys().next().value!);
    return p;
  }

  /** A root's bases at [start, end), 0-based half-open, as stored (uppercase, IUPAC kept). */
  async read(root: string, start: number, end: number): Promise<Uint8Array> {
    const gs = this.groups.get(root);
    if (!gs) throw new Error(`${root} is not hosted (an external root?)`);
    if (end <= start) return new Uint8Array();
    const [k0, k1] = [Math.floor(start / BLOCK_SIZE), Math.floor((end - 1) / BLOCK_SIZE)];
    const needed = gs.filter((g) => g.firstBlock <= k1 && g.firstBlock + g.rows > k0);
    if (!needed.length) throw new Error(`${root} has no bases at ${start}`);
    const bases = (await Promise.all(needed.map((g) => this.group(g)))).join("");
    const offset = needed[0].firstBlock * BLOCK_SIZE;
    return new TextEncoder().encode(bases.slice(start - offset, end - offset));
  }
}
