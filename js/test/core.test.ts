// The wasm build against known vectors. The cross-language checks (random
// inputs, every recipe on the build) are in tests/test_wasm.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import * as rb from "../src/index.ts";

rb.initSync({ module: readFileSync(new URL("../pkg/refbook_wasm_bg.wasm", import.meta.url)) });
const enc = (s: string) => new TextEncoder().encode(s);
const dec = (b: Uint8Array) => new TextDecoder().decode(b);

test("refget digests and canonicalization", () => {
  // sha512t24u("ACGT") as given in the GA4GH VRS documentation.
  assert.deepEqual(rb.digests(enc("ACGT")), ["f1f8f4bf413b16ad135722aa4591043e", "SQ.aKF498dAxcJAqme6QYQ7EZ07-fiw8Kw2"]);
  assert.equal(dec(rb.canonicalBases(enc("acgt\nNNry \r\n"))), "ACGTNNRY");
  assert.throws(() => rb.canonicalBases(enc("AC-GT")), /character '-' at position 2/);
  const s = rb.scan(enc("acGTNNNRACgt"));
  assert.equal(dec(s.bases), "ACGTNNNRACGT");
  assert.deepEqual([s.lower, s.n_runs, s.iupac], [[[0, 2], [10, 12]], [[4, 7]], [[7, "R"]]]);
});

test("seqcol: the spec's example", () => {
  const d = rb.seqcolDigests(["chr1", "chr2", "chr3"], [248956422, 242193529, 198295559], [
    "SQ.2YnepKM7OkBoOrKmvHbGqguVfF9amCST", "SQ.lwDyBi432Py-7xnAISyQlnlhWDEaBPv2", "SQ.Eqk6_SvMMDCc6C-uEfickOUWTatLMDQZ"]);
  assert.equal(d.digest, "sjNNwm4zov3Dl0FRWbRTcZwzqrTQKIqL");
  assert.deepEqual(d.level1, { names: "g04lKdxiYtG3dOGeUC5AdKEifw65G0Wp",
    lengths: "5K4odB173rjao1Cnbk5BnvLt9V7aPAa2", sequences: "rD29ZKmEqwwHRXjiQ36p6UMZQ5hemmsb" });
});

test("seqcol: the refget package's compliance data", () => {
  const fixtures = JSON.parse(readFileSync(new URL("../../python/tests/fixtures/refget_compliance/test_fasta_digests.json", import.meta.url), "utf8"));
  for (const [file, f] of Object.entries<any>(fixtures)) {
    const { names, lengths, sequences } = f.level2;
    const d = rb.seqcolDigests(names, lengths, sequences);
    assert.equal(d.digest, f.top_level_digest, file);
    assert.deepEqual(d.level1, { names: f.level1.names, lengths: f.level1.lengths, sequences: f.level1.sequences }, file);
    const a = rb.seqcolAncillary(names, lengths, sequences);
    for (const k of ["sorted_sequences", "name_length_pairs", "sorted_name_length_pairs"] as const)
      assert.equal(rb.level1(a[k]), f.level1[k], `${file} ${k}`);
  }
});

test("canonical JSON", () => {
  assert.equal(rb.canonicalJson(["a\"b", "c\\d", "\n\t\u0001", "é"]), String.raw`["a\"b","c\\d","\n\t\u0001","é"]`);
  assert.equal(rb.canonicalJson({ name: "x", length: -3 }), `{"length":-3,"name":"x"}`);
  assert.throws(() => rb.canonicalJson([1.5]), /not an integer/);
  assert.throws(() => rb.canonicalJson([true] as any), /not a seqcol JSON value/);
});

test("nucleotide operations, on slices too", () => {
  const bases = enc("ACGTRACGTY");
  assert.equal(dec(rb.applyOperations(bases, 0, [[8, 10]], true)), "ACGTNACGNN");
  assert.equal(dec(rb.applyOperations(bases.slice(3, 9), 3, [[8, 10]], true)), "TNACGN");
});

test("the recipe compiler", () => {
  const member = (acc: string, role: string, ucsc: string, seq: string | null = null) => ({
    assembly_accession: "GCA_1.1", genbank_accession: acc, role, ucsc_name: ucsc, sequence_name: seq, refseq_accession: null });
  const tables = rb.recipeTables({
    members: [member("C1.1", "assembled-molecule", "chr1", "1"), member("P1.1", "unplaced-scaffold", "chrUn_P1v1")],
    roots: ["C1.1", "P1.1", "EBV.1"], iupac: ["C1.1"], layers: { hardmask_x: ["P1.1"] },
  });
  const recipe = {
    flavor: "t", select: [{ assembly: "GCA_1.1", roles: ["assembled-molecule", "unplaced-scaffold"] }, { roots: ["EBV.1"] }],
    mask: [{ layer: "hardmask_x", with: "N" }], alphabet: { iupac: "N" },
    rename: { namespace: "ucsc", map: { "EBV.1": "chrEBV" } },
  };
  const want = [{ name: "chr1", root_id: "C1.1", operations: ["iupac_to_n"] },
    { name: "chrEBV", root_id: "EBV.1", operations: [] },
    { name: "chrUn_P1v1", root_id: "P1.1", operations: ["hardmask_x"] }];
  assert.deepEqual(rb.compileRecipe(recipe, tables), want);
  assert.deepEqual(rb.compileRecipe(JSON.stringify(recipe), tables), want);
  assert.throws(() => rb.compileRecipe({ ...recipe, rename: { namespace: "ucsc" } }, tables), /EBV.1: no ucsc name/);
});
