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
import { decodeRecipe, design, designTables, encodeRecipe, plainRecipe } from "../src/data/design.ts";
import { identifyTables, level2, pairs, parseHeader } from "../src/data/identify.ts";
import * as edit from "../src/data/recipeEdit.ts";
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

test("pasted headers parse in every format", () => {
  assert.deepEqual(parseHeader("chr1\t10\t6\t10\t11\nchr2\t5\t30\t5\t6\n"),
    { format: "names and lengths", entries: [{ name: "chr1", length: 10 }, { name: "chr2", length: 5 }] });
  assert.deepEqual(parseHeader("chr1 248956422\n# comment\n").entries, [{ name: "chr1", length: 248956422 }]);
  assert.deepEqual(parseHeader("@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:10\tM5:abc\tUR:x\n@SQ\tSN:chr2\tLN:5\n").entries,
    [{ name: "chr1", length: 10, md5: "abc" }, { name: "chr2", length: 5, md5: null }]);
  assert.deepEqual(parseHeader('##fileformat=VCFv4.2\n##contig=<ID=chr1,length=10,md5="abc">\n##contig=<ID=chrM>\n').entries,
    [{ name: "chr1", length: 10, md5: "abc" }, { name: "chrM", length: null, md5: null }]);
  const fa = parseHeader(">a desc\nACgt\nnN\n>b\nRY\n");
  assert.equal(fa.format, "FASTA");
  assert.deepEqual(fa.entries.map((e) => [e.name, e.length, e.md5, e.sq]),
    [["a", 6, ...rb.digests(new TextEncoder().encode("ACGTNN"))], ["b", 2, ...rb.digests(new TextEncoder().encode("RY"))]]);
  assert.equal(parseHeader("nothing here").format, "nothing recognized");
  const l2 = rb.seqcolLevel2(["chr1", "chr2"], [10, 5], ["SQ.a", "SQ.b"]);
  assert.deepEqual(parseHeader(JSON.stringify(l2)),
    { format: "seqcol (level 2)", entries: [{ name: "chr1", length: 10, sq: "SQ.a" }, { name: "chr2", length: 5, sq: "SQ.b" }] });
  assert.throws(() => parseHeader(JSON.stringify(rb.seqcolLevel1(["chr1"], [10], ["SQ.a"]))), /level-1/);
});

test("identify in the browser, like the catalog says", { skip }, async () => {
  const t = await identifyTables(cat);
  assert.ok(measured["identify tables"].bytes < 1e6, `${measured["identify tables"].bytes} bytes`);
  const rows = await manifest(cat, "hg38-analysis-set");
  const chr1 = rows.find((r) => r.name === "chr1")!;
  const [byMd5, byName, wrong] = rb.identifySequences(
    [{ name: "chr1", length: chr1.length, md5: chr1.md5 }, { name: "chr1", length: chr1.length }, { name: "chr1", length: 5 }], t);
  assert.deepEqual([byMd5.evidence, byMd5.sequence, byMd5.root_id, byMd5.operations], ["digest", chr1.sha512t24u, "CM000663.2", chr1.operations]);
  assert.ok(byMd5.flavors.some((u) => u.flavor === "hg38-analysis-set" && u.name === "chr1"));
  assert.deepEqual([byName.evidence, byName.root_id], ["name_and_length", "CM000663.2"]);
  assert.ok(byName.cognates.includes(chr1.sha512t24u));
  assert.deepEqual(wrong.notes.map((x) => x.kind), ["length_differs", "no_root_of_this_length"]);
});

test("two flavors compared: seqcol's counts and refbook's pairs", { skip }, async () => {
  const [a, b] = await Promise.all([manifest(cat, "grch38-no-alt"), manifest(cat, "hg38-analysis-set")]);
  const c = rb.seqcolCompare(level2(a), level2(b));
  assert.equal(c.array_elements.a_and_b_count.names, 195);
  assert.equal(c.array_elements.a_and_b_count.sequences, 181);
  const p = pairs(a, b);
  const count = (k: string) => p.filter((x) => x.kind === k).length;
  assert.deepEqual([count("same"), count("operations"), count("different"), count("a_only"), count("b_only")], [181, 14, 0, 0, 0]);
  const renamed = pairs([{ ...a[0], name: "one" }], [a[0]]);
  assert.deepEqual(renamed.map((x) => x.kind), ["renamed"]);
});


test("every flavor's recipe, compiled in the browser, is that flavor", { skip }, async () => {
  const t = await designTables(cat);
  assert.ok(measured["design tables"].bytes < 1e6, `${measured["design tables"].bytes} bytes`);
  const fs = await flavors(cat);
  for (const f of fs) {
    const d = design(plainRecipe(JSON.parse(f.recipe)), t, fs);
    assert.deepEqual(d.novel, [], f.flavor);
    assert.equal(d.id, f.id, f.flavor);
    assert.equal(d.seqcolDigest, f.seqcol_digest, f.flavor);
    assert.equal(d.equals, f.flavor);
    const m = await manifest(cat, f.flavor);
    assert.deepEqual(d.rows.map((r) => [r.name, r.root_id, r.operations, r.length, r.md5, r.sha512t24u]),
                     m.map((r) => [r.name, r.root_id, [...r.operations], r.length, r.md5, r.sha512t24u]), f.flavor);
  }
  const r = plainRecipe(JSON.parse(fs[0].recipe));
  assert.deepEqual(decodeRecipe(encodeRecipe(r)), r);
  const old = { ...r, rename: { namespace: "genbank", by_role: { "assembled-molecule": "sequence" } } };
  assert.deepEqual(decodeRecipe(encodeRecipe(old)).rename, { namespace: "genbank", by_role: { "assembled-molecule": "grc" } });
  assert.deepEqual(design(old, t, fs).rows, design(decodeRecipe(encodeRecipe(old)), t, fs).rows);
  assert.throws(() => design({ ...r, mask: [{ layer: "nope", with: "N" }] }, t, fs), /nope/);
});


test("the form's edits rebuild published flavors from scratch", { skip }, async () => {
  const t = await designTables(cat);
  const fs = await flavors(cat);
  const all = { hla: t.collections.get(edit.HLA)! };
  const is = (r: ReturnType<typeof edit.fromScratch>) => design(r, t, fs).equals;
  let r = edit.fromScratch();
  for (const role of ["unlocalized-scaffold", "unplaced-scaffold"]) r = edit.setRole(r, role, true);
  r = edit.setMask(edit.setEbv(r, true), "hardmask_grc", true);
  assert.equal(is(r), "grch38-no-alt");
  assert.equal(is(edit.setIupacToN(r, true)), "hg38-analysis-set");
  r = edit.setRole(r, "alt-scaffold", true);
  assert.equal(is(r), "grch38-full");
  r = edit.setDecoys(r, true);
  assert.equal(is(r), "grch38-full-hs38d1");
  const hla = edit.GUIDE.find((g) => g.goal === "HLA typing")!;
  assert.equal(hla.has(r), false);
  const dh = hla.set(r, true, all);
  assert.equal(hla.has(dh), true);
  assert.equal(is(dh), "hs38dh");
  // And back: each edit undoes, keeping the rest.
  assert.equal(is(edit.setHla(edit.setDecoys(dh, false), [], all.hla)), "grch38-full");
  assert.deepEqual(edit.hlaGroups(dh), edit.HLA_TYPING_GROUPS);
  assert.equal(edit.hlaKind(dh), "typing");
  assert.equal(edit.hlaKind(r), "none");
  assert.equal(edit.hlaKind(edit.setHla(r, ["A", "G"], all.hla)), "custom");
  assert.notEqual(design(edit.setHla(r, ["A", "G"], all.hla), t, fs).rows.length, 0);   // still compiles
  // Ensembl's names: GenBank by default, its own for chromosomes; IUPAC -> N.
  let e = edit.setNamespace(edit.setRelease(edit.fromScratch(), "GCA_000001405.29"), "genbank");
  for (const role of ["unlocalized-scaffold", "unplaced-scaffold"]) e = edit.setRole(e, role, true);
  e = edit.setChromosomeNames(edit.setIupacToN(e, true), "grc");
  assert.equal(is(e), "ensembl-grch38-primary");
  assert.deepEqual(edit.others(dh), []);
  // Every goal toggles: on adds it, off takes it away, each the other's inverse here.
  for (const g of edit.GUIDE) {
    const on = g.set(dh, true, all), off = g.set(dh, false, all);
    assert.ok(g.has(on) && !g.has(off), g.goal);
    assert.equal(is(g.set(off, true, all)), is(on), g.goal);
  }
  const scratch = edit.fromScratch();
  const primaryGoal = edit.GUIDE[0];
  assert.equal(primaryGoal.has(scratch), false);
  assert.deepEqual(edit.primary(primaryGoal.set(scratch, true, all))!.roles, ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold"]);
  const hg38p14 = JSON.parse(fs.find((f) => f.flavor === "hg38-p14")!.recipe);
  assert.equal(edit.others(hg38p14).length, 1);   // the p13 fix patches, kept as JSON
  // Naming per group: EBV, decoys and HLA always get a rule, so any default namespace compiles.
  for (const ns of edit.NAMESPACES) {
    let x = edit.setNamespace(edit.fromScratch(), ns);
    x = edit.setHla(edit.setDecoys(edit.setEbv(x, true), true), edit.HLA_TYPING_GROUPS, all.hla);
    const d = design(x, t, fs);
    assert.ok(d.rows.some((r) => r.name === (ns === "ucsc" ? "chrEBV" : edit.EBV)), ns);
    assert.ok(d.rows.some((r) => r.name === (ns === "ucsc" ? "chrUn_JTFH01000001v1_decoy" : "JTFH01000001.1")), ns);
    assert.ok(d.rows.some((r) => r.name === "HLA-A*01:01:01:01"), ns);
  }
  let named = edit.setRoleNames(dh, "unplaced-scaffold", "genbank");
  assert.equal(edit.roleNamespace(named, "unplaced-scaffold"), "genbank");
  assert.equal(edit.roleNamespace(named, "assembled-molecule"), "ucsc");
  assert.ok(design(named, t, fs).rows.some((r) => r.name === "KI270302.1"));
  assert.ok(design(named, t, fs).rows.some((r) => r.name === "chrUn_JTFH01000001v1_decoy"));   // the decoys keep their template
  named = edit.setRoleNames(named, "unplaced-scaffold", "ucsc");
  assert.equal(named.rename.by_role, undefined);   // the default again: no by_role
  named = edit.setGroupTemplate(edit.setEbvName(dh, "EBV"), edit.HLA, "{name}");
  assert.ok(design(named, t, fs).rows.some((r) => r.name === "EBV"));
  assert.ok(design(named, t, fs).rows.some((r) => r.name === "A*01:01:01:01"));
  assert.deepEqual([edit.releaseLabel("GRCh38", false), edit.releaseLabel("GRCh38.p14", true), edit.releaseLabel("GRCh38.p3", false)],
    ["p0 (the original release, no patches)", "p14 (latest)", "p3"]);
  assert.equal(t.roleCounts.get("GCA_000001405.15")!.get("fix-patch") ?? 0, 0);
  assert.equal(t.roleCounts.get("GCA_000001405.29")!.get("fix-patch"), 164);
  // Filters: leaving out patches placed on scaffolds is Ensembl's toplevel recipe; on again, back to all.
  const top = JSON.parse(fs.find((f) => f.flavor === "ensembl-grch38-toplevel")!.recipe);
  assert.deepEqual(edit.placedOn(top), ["chromosome"]);
  const all2 = edit.setPlacedOn(top, "scaffold", true);
  assert.equal(edit.primary(all2)!.placed_on, undefined);
  assert.equal(design(all2, t, fs).rows.length, design(top, t, fs).rows.length + 3);
  assert.equal(is(edit.setPlacedOn(all2, "scaffold", false)), "ensembl-grch38-toplevel");
  assert.deepEqual(edit.placedOn(edit.setPlacedOn(top, "chromosome", false)), ["chromosome"]);   // never none
});
