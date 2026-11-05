// The app's data layer against the repository's build (or REFBOOK_CATALOG),
// served over HTTP with Range support as a static host serves a release.
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import * as rb from "@abdenlab/refbook";
import { catalogHandler } from "../server/catalog.ts";
import { Blocks } from "../src/data/blocks.ts";
import { Catalog } from "../src/data/catalog.ts";
import { chromSizes, inOrder, sequenceDictionary } from "../src/data/exports.ts";
import { flavors, IUPAC_TO_N, manifest, region, targetOrder, targets, verify } from "../src/data/flavors.ts";
import { measure, onMeasure } from "../src/data/meter.ts";

const dir = process.env.REFBOOK_CATALOG ?? fileURLToPath(new URL("../../catalog/output/build/grch38", import.meta.url));
const skip = existsSync(`${dir}/catalog.json`) ? false : "no build";
const wasm = new URL(import.meta.resolve("@abdenlab/refbook")).pathname.replace(/dist\/index\.js$/, "pkg/refbook_wasm_bg.wasm");
rb.initSync({ module: readFileSync(wasm) });

const server = createServer(catalogHandler(dir));
let cat: Catalog, blocks: Blocks;
const measured: Record<string, { requests: number; bytes: number }> = {};
onMeasure((action, t) => { measured[action] = t; });

before(async () => {
  if (skip) return;
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  cat = await Catalog.open(`http://127.0.0.1:${(server.address() as AddressInfo).port}/`);
  blocks = await measure("open root_blocks", () => Blocks.open(cat));
});
after(() => server.close());

test("tables", { skip }, async () => {
  const fs = await flavors(cat);
  assert.equal(fs.length, 13);
  assert.equal((await targets(cat)).length, 17);
  const noAlt = fs.find((f) => f.flavor === "grch38-no-alt")!;
  const rows = await manifest(cat, "grch38-no-alt");
  assert.equal(rows.length, noAlt.n_sequences);
  assert.equal(rows.reduce((s, r) => s + r.length, 0), noAlt.total_length);
  // The manifest is the flavor: its named sequence set digest is the flavor's id.
  assert.equal(rb.namedSetDigest(rows.map((r) => r.name), rows.map((r) => r.sha512t24u)), noAlt.id);
  const doc = await cat.json(`collections/${noAlt.seqcol_digest}.json`);
  assert.equal(rb.seqcolDigests(doc.names, doc.lengths, doc.sequences).digest, noAlt.seqcol_digest);
  assert.equal(typeof rows[0].length, "number");
});

test("exports in a target's order", { skip }, async () => {
  const t = (await targets(cat)).find((t) => t.target === "UCSC_hg38.analysisSet")!;
  const rows = inOrder(await manifest(cat, t.flavor), await targetOrder(cat, t.target));
  assert.equal(rb.seqcolDigests(rows.map((r) => r.name), rows.map((r) => r.length), rows.map((r) => r.sha512t24u)).digest, t.seqcol_digest);
  assert.match(chromSizes(rows), /^chr1\t248956422\n/);
  assert.match(sequenceDictionary(rows), /^@HD\tVN:1\.6\n@SQ\tSN:chr1\tLN:248956422\tM5:[0-9a-f]{32}\n/);
});

test("root_blocks: opening reads only the footer", { skip }, () => {
  assert.ok(measured["open root_blocks"].bytes < 3e6, `${measured["open root_blocks"].bytes} bytes`);
});

test("sequences built from roots match their digests", { skip }, async () => {
  const rows = await manifest(cat, "hs38dh");
  const smallest = (pred: (r: (typeof rows)[0]) => boolean) =>
    rows.filter((r) => pred(r) && blocks.hosts(r.root_id)).sort((a, b) => a.length - b.length)[0];
  const plainRow = rows.find((r) => r.name === "chrM")!;
  const masked = smallest((r) => r.operations.includes("hardmask_grc"));
  assert.ok(masked, "a hard-masked sequence");
  for (const row of [plainRow, masked]) assert.ok(await verify(cat, blocks, row), row.name);
  const iupac = (await manifest(cat, "hg38")).filter((r) => r.operations.includes(IUPAC_TO_N)).sort((a, b) => a.length - b.length)[0];
  assert.ok(await verify(cat, blocks, iupac), iupac.name);
});

test("a region is the same bases as the whole sequence there", { skip }, async () => {
  const row = (await manifest(cat, "hg38")).filter((r) => r.operations.includes(IUPAC_TO_N)).sort((a, b) => a.length - b.length)[0];
  const whole = (await region(cat, blocks, row, 0, row.length)).bases;
  for (const [s, e] of [[0, 10], [65530, 65600], [row.length - 100, row.length], [123_456, 123_456 + 70_000]]) {
    const r = await measure(`region ${s}`, () => region(cat, blocks, row, s, e));
    assert.deepEqual(r.bases, whole.slice(s, e), `${s}-${e}`);
  }
  const r = measured["region 65530"];
  assert.ok(r.requests <= 4 && r.bytes < 4e6, JSON.stringify(r));
});
