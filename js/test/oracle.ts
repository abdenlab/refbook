// Run the wasm build on a request file and print the results as JSON, for
// tests/test_wasm.py to compare with the Python bindings of the same core.
// Request: {sequences: [base64], collections: [{names, lengths, sequences}],
// tables, recipes}.
import { readFileSync } from "node:fs";
import * as rb from "../src/index.ts";

rb.initSync({ module: readFileSync(new URL("../pkg/refbook_wasm_bg.wasm", import.meta.url)) });
const req = JSON.parse(readFileSync(process.argv[2], "utf8"));
const attempt = <T>(f: () => T) => { try { return { ok: f() }; } catch (e) { return { error: String((e as Error).message) }; } };

const scans = req.sequences.map((b64: string) => attempt(() => {
  const s = rb.scan(Buffer.from(b64, "base64"));
  return { ...s, bases: Buffer.from(s.bases).toString("latin1"), digests: rb.digests(s.bases) };
}));
const collections = req.collections.map((c: any) => ({
  ...rb.seqcolDigests(c.names, c.lengths, c.sequences),
  ancillary: rb.seqcolAncillary(c.names, c.lengths, c.sequences),
  named_set: rb.namedSetDigest(c.names, c.sequences),
}));
const compiled: Record<string, unknown> = {};
if (req.tables) {
  const tables = rb.recipeTables(req.tables);
  for (const r of req.recipes) compiled[r.flavor] = attempt(() => rb.compileRecipe(r, tables));
}
process.stdout.write(JSON.stringify({ scans, collections, compiled }));
