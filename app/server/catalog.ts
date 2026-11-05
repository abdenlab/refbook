// Serve a catalog directory over HTTP with Range support, as a static host
// (Hugging Face, R2) does: the dev and preview servers mount it at /catalog/,
// and the tests run it on its own.
import { createReadStream, statSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { extname, resolve, sep } from "node:path";

const TYPES: Record<string, string> = { ".json": "application/json", ".parquet": "application/vnd.apache.parquet" };

/** A request handler serving `root`: GET and HEAD, single byte ranges, nothing outside root. */
export function catalogHandler(root: string) {
  const base = resolve(root);
  return (req: IncomingMessage, res: ServerResponse, next?: () => void) => {
    const path = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
    const file = resolve(base, "." + path);
    if (file !== base && !file.startsWith(base + sep)) return void (res.statusCode = 403, res.end());
    let size: number;
    try {
      const st = statSync(file);
      if (!st.isFile()) throw new Error("not a file");
      size = st.size;
    } catch {
      if (next) return next();
      return void (res.statusCode = 404, res.end());
    }
    res.setHeader("Accept-Ranges", "bytes");
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Content-Type", TYPES[extname(file)] ?? "application/octet-stream");
    let [start, end] = [0, size - 1];
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? "");
    if (req.headers.range) {
      if (!m || (m[1] === "" && m[2] === "")) return void (res.statusCode = 416, res.end());
      if (m[1] === "") [start, end] = [Math.max(0, size - Number(m[2])), size - 1];
      else [start, end] = [Number(m[1]), m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1)];
      if (start > end || start >= size) {
        res.setHeader("Content-Range", `bytes */${size}`);
        return void (res.statusCode = 416, res.end());
      }
      res.statusCode = 206;
      res.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);
    }
    res.setHeader("Content-Length", String(end - start + 1));
    if (req.method === "HEAD") return void res.end();
    createReadStream(file, { start, end }).pipe(res);
  };
}
