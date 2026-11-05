//! WebAssembly bindings of refbook-core, wrapped by the refbook npm package
//! (js/src). Function names are camelCase; data keys keep the catalog's and
//! the seqcol spec's names (root_id, sorted_name_length_pairs, ...), so the
//! same JSON reads the same in Python and JavaScript.

use refbook_core::seqcol::{self, Json};
use refbook_core::{operations, recipe, refget};
use serde::{Deserialize, Serialize};
use serde_bytes::ByteBuf;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use wasm_bindgen::prelude::*;

fn to_js<T: Serialize>(value: &T) -> Result<JsValue, JsError> {
    let s = serde_wasm_bindgen::Serializer::new().serialize_maps_as_objects(true);
    value
        .serialize(&s)
        .map_err(|e| JsError::new(&e.to_string()))
}

fn from_js<T: for<'de> Deserialize<'de>>(value: JsValue, what: &str) -> Result<T, JsError> {
    serde_wasm_bindgen::from_value(value).map_err(|e| JsError::new(&format!("{what}: {e}")))
}

// refget

/// The bases refget digests: whitespace removed, uppercased, A-Z only.
/// Throws on any other character.
#[wasm_bindgen(js_name = canonicalBases)]
pub fn canonical_bases(seq: &[u8]) -> Result<Vec<u8>, JsError> {
    refget::canonical_bases(seq).map_err(|e| JsError::new(&e.to_string()))
}

/// The bytes with whitespace removed.
#[wasm_bindgen(js_name = removeWhitespace)]
pub fn remove_whitespace(seq: &[u8]) -> Vec<u8> {
    refget::remove_whitespace(seq)
}

/// [MD5, SQ. digest] of canonical bases.
#[wasm_bindgen]
pub fn digests(bases: &[u8]) -> Vec<String> {
    let (md5, sq) = refget::digests(bases);
    vec![md5, sq]
}

/// The GA4GH digest of bytes: SHA-512 truncated to 24 bytes, base64url.
#[wasm_bindgen]
pub fn sha512t24u(data: &[u8]) -> String {
    refget::sha512t24u(data)
}

#[derive(Serialize)]
struct Scan {
    bases: ByteBuf,
    md5: String,
    sha512t24u: String,
    lower: Vec<(usize, usize)>,
    n_runs: Vec<(usize, usize)>,
    iupac: Vec<(usize, String)>,
}

/// One sequence (whitespace removed): its canonical bases, md5, sha512t24u,
/// lowercase runs (lower), N-runs (n_runs), both 0-based half-open, and IUPAC
/// positions with their codes (iupac).
#[wasm_bindgen]
pub fn scan(seq: &[u8]) -> Result<JsValue, JsError> {
    let s = refget::scan(seq).map_err(|e| JsError::new(&e.to_string()))?;
    to_js(&Scan {
        bases: ByteBuf::from(s.bases),
        md5: s.md5,
        sha512t24u: s.sha512t24u,
        lower: s.lower,
        n_runs: s.n_runs,
        iupac: s
            .iupac
            .into_iter()
            .map(|(i, b)| (i, (b as char).to_string()))
            .collect(),
    })
}

// seqcol

fn to_json(v: Value) -> Result<Json, JsError> {
    match v {
        Value::String(s) => Ok(Json::Str(s)),
        Value::Number(n) => n
            .as_i64()
            .map(Json::Int)
            .ok_or_else(|| JsError::new(&format!("not an integer: {n}"))),
        Value::Array(items) => items
            .into_iter()
            .map(to_json)
            .collect::<Result<_, _>>()
            .map(Json::Arr),
        Value::Object(m) => m
            .into_iter()
            .map(|(k, v)| Ok((k, to_json(v)?)))
            .collect::<Result<_, _>>()
            .map(Json::Obj),
        other => Err(JsError::new(&format!("not a seqcol JSON value: {other}"))),
    }
}

/// RFC-8785 canonical JSON of a value made of strings, integers, arrays and objects.
#[wasm_bindgen(js_name = canonicalJson)]
pub fn canonical_json(value: JsValue) -> Result<String, JsError> {
    Ok(seqcol::canonical(&to_json(from_js(value, "value")?)?))
}

/// The level-1 digest of an attribute's level-2 value.
#[wasm_bindgen]
pub fn level1(value: JsValue) -> Result<String, JsError> {
    Ok(seqcol::level1(&to_json(from_js(value, "value")?)?))
}

#[derive(Serialize)]
struct Digests {
    digest: String,
    level1: Level1,
}

#[derive(Serialize)]
struct Level1 {
    names: String,
    lengths: String,
    sequences: String,
}

/// A collection's top-level digest and level-1 digests ({digest, level1});
/// sequences are SQ. digests.
#[wasm_bindgen(js_name = seqcolDigests)]
pub fn seqcol_digests(
    names: Vec<String>,
    lengths: JsValue,
    sequences: Vec<String>,
) -> Result<JsValue, JsError> {
    let lengths: Vec<i64> = from_js(lengths, "lengths")?;
    let (digest, l1) = seqcol::digests(&names, &lengths, &sequences);
    to_js(&Digests {
        digest,
        level1: Level1 {
            names: l1.names,
            lengths: l1.lengths,
            sequences: l1.sequences,
        },
    })
}

#[derive(Serialize)]
struct NameLength {
    name: String,
    length: i64,
}

#[derive(Serialize)]
struct Ancillary {
    name_length_pairs: Vec<NameLength>,
    sorted_name_length_pairs: Vec<String>,
    sorted_sequences: Vec<String>,
    named_sequences: Vec<String>,
    sorted_named_sequences: Vec<String>,
}

/// Level-2 values of the ancillary attributes refbook computes.
#[wasm_bindgen(js_name = seqcolAncillary)]
pub fn seqcol_ancillary(
    names: Vec<String>,
    lengths: JsValue,
    sequences: Vec<String>,
) -> Result<JsValue, JsError> {
    let lengths: Vec<i64> = from_js(lengths, "lengths")?;
    let a = seqcol::ancillary(&names, &lengths, &sequences);
    to_js(&Ancillary {
        name_length_pairs: a
            .name_length_pairs
            .into_iter()
            .map(|(name, length)| NameLength { name, length })
            .collect(),
        sorted_name_length_pairs: a.sorted_name_length_pairs,
        sorted_sequences: a.sorted_sequences,
        named_sequences: a.named_sequences,
        sorted_named_sequences: a.sorted_named_sequences,
    })
}

/// The order-independent identifier of a named sequence set.
#[wasm_bindgen(js_name = namedSetDigest)]
pub fn named_set_digest(names: Vec<String>, sequences: Vec<String>) -> String {
    seqcol::named_set_digest(&names, &sequences)
}

// nucleotide operations

/// A root's bases (root positions start..start + len) with nucleotide
/// operations applied: the spans ([start, end], 0-based half-open, root
/// coordinates) set to N, then, if toN, every base other than A, C, G, T and
/// N set to N.
#[wasm_bindgen(js_name = applyOperations)]
pub fn apply_operations(
    bases: &[u8],
    start: usize,
    spans: JsValue,
    to_n: bool,
) -> Result<Vec<u8>, JsError> {
    let spans: Vec<(usize, usize)> = from_js(spans, "spans")?;
    let mut b = bases.to_vec();
    operations::apply(&mut b, start, &spans, to_n);
    Ok(b)
}

// the recipe compiler

#[derive(Deserialize)]
struct MemberRow {
    assembly_accession: String,
    genbank_accession: String,
    role: String,
    ucsc_name: Option<String>,
    sequence_name: Option<String>,
    refseq_accession: Option<String>,
}

#[derive(Deserialize)]
struct ExternalRow {
    root_id: String,
    collection: String,
    group: String,
    name: Option<String>,
}

#[derive(Deserialize)]
struct PlacementRow {
    root_id: String,
    parent_type: String,
}

#[derive(Deserialize)]
struct TablesIn {
    members: Vec<MemberRow>,
    roots: Vec<String>,
    iupac: Vec<String>,
    layers: HashMap<String, Vec<String>>,
    #[serde(default)]
    external: Vec<ExternalRow>,
    #[serde(default)]
    placements: Vec<PlacementRow>,
}

/// The catalog tables the recipe compiler reads, built once and shared by
/// every recipe. From {members, roots, iupac, layers, external, placements}:
/// members are assembly_members rows (assembly_accession, genbank_accession,
/// role, ucsc_name, sequence_name, refseq_accession) in report order; roots
/// every root id; iupac the roots with IUPAC codes; layers a mask layer's
/// name -> the roots it has spans on; external roots_external rows (root_id,
/// collection, group, name) in rank order; placements layer_placements rows
/// (root_id, parent_type).
#[wasm_bindgen]
pub struct RecipeTables(recipe::Tables);

#[wasm_bindgen]
impl RecipeTables {
    #[wasm_bindgen(constructor)]
    pub fn new(tables: JsValue) -> Result<RecipeTables, JsError> {
        let t: TablesIn = from_js(tables, "tables")?;
        let mut parent_types = HashMap::<String, HashSet<String>>::new();
        for p in t.placements {
            parent_types
                .entry(p.root_id)
                .or_default()
                .insert(p.parent_type);
        }
        Ok(RecipeTables(recipe::Tables {
            members: t
                .members
                .into_iter()
                .map(|m| recipe::Member {
                    assembly: m.assembly_accession,
                    accession: m.genbank_accession,
                    role: m.role,
                    ucsc_name: m.ucsc_name,
                    sequence_name: m.sequence_name,
                    refseq_accession: m.refseq_accession,
                })
                .collect(),
            roots: t.roots.into_iter().collect(),
            iupac: t.iupac.into_iter().collect(),
            layers: t
                .layers
                .into_iter()
                .map(|(k, v)| (k, v.into_iter().collect()))
                .collect(),
            external: t
                .external
                .into_iter()
                .map(|e| recipe::External {
                    root_id: e.root_id,
                    collection: e.collection,
                    group: e.group,
                    name: e.name,
                })
                .collect(),
            parent_types,
        }))
    }
}

#[derive(Serialize)]
struct Row {
    name: String,
    root_id: String,
    operations: Vec<String>,
}

/// Compile a recipe (an object, or its JSON text): its manifest rows
/// ({name, root_id, operations}), in canonical order. Throws if it doesn't
/// compile.
#[wasm_bindgen(js_name = compileRecipe)]
pub fn compile_recipe(recipe: JsValue, tables: &RecipeTables) -> Result<JsValue, JsError> {
    let parsed = match recipe.as_string() {
        Some(text) => recipe::Recipe::from_json(&text),
        None => recipe::Recipe::from_value(from_js(recipe, "recipe")?),
    }
    .and_then(|r| recipe::compile(&r, &tables.0))
    .map_err(|e| JsError::new(&e.to_string()))?;
    to_js(
        &parsed
            .into_iter()
            .map(|r| Row {
                name: r.name,
                root_id: r.root_id,
                operations: r.operations,
            })
            .collect::<Vec<_>>(),
    )
}
