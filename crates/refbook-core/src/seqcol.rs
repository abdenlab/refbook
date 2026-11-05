//! GA4GH sequence collection (seqcol) digests.
//!
//! From the spec (github.com/ga4gh/refget, docs/seqcols/README.md): canonicalize
//! each attribute with RFC-8785, digest it with sha512t24u; the top-level digest
//! covers the inherent attributes, `names` and `sequences`. Also the ancillary
//! attributes refbook computes: `name_length_pairs`, `sorted_name_length_pairs`
//! and `sorted_sequences` from the spec, `named_sequences` as its footnote F1
//! suggests, and `sorted_named_sequences`, refbook's order-independent
//! identifier of a named sequence set.

use crate::refget::sha512t24u;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt::Write;

/// The JSON values seqcol digests: strings, integers, arrays and objects.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Json {
    Str(String),
    Int(i64),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl TryFrom<serde_json::Value> for Json {
    type Error = String;

    /// Booleans, nulls and non-integer numbers are not seqcol values.
    fn try_from(v: serde_json::Value) -> Result<Self, String> {
        use serde_json::Value;
        match v {
            Value::String(s) => Ok(Json::Str(s)),
            Value::Number(n) => n
                .as_i64()
                .map(Json::Int)
                .ok_or(format!("not an integer: {n}")),
            Value::Array(items) => items
                .into_iter()
                .map(Json::try_from)
                .collect::<Result<_, _>>()
                .map(Json::Arr),
            Value::Object(m) => m
                .into_iter()
                .map(|(k, v)| Ok((k, Json::try_from(v)?)))
                .collect::<Result<_, String>>()
                .map(Json::Obj),
            other => Err(format!("not a seqcol JSON value: {other}")),
        }
    }
}

impl From<&Json> for serde_json::Value {
    fn from(j: &Json) -> Self {
        use serde_json::Value;
        match j {
            Json::Str(s) => Value::String(s.clone()),
            Json::Int(i) => Value::from(*i),
            Json::Arr(items) => Value::Array(items.iter().map(Value::from).collect()),
            Json::Obj(m) => {
                Value::Object(m.iter().map(|(k, v)| (k.clone(), Value::from(v))).collect())
            }
        }
    }
}

/// RFC-8785 canonical JSON of the values seqcol uses (no floats): no whitespace,
/// object keys sorted, strings escaped minimally (`"` `\` and control characters,
/// with the short escapes where JSON has them).
pub fn canonical(value: &Json) -> String {
    let mut out = String::new();
    write_json(value, &mut out);
    out
}

fn write_json(value: &Json, out: &mut String) {
    match value {
        Json::Str(s) => write_str(s, out),
        Json::Int(i) => write!(out, "{i}").unwrap(),
        Json::Arr(items) => {
            out.push('[');
            for (k, item) in items.iter().enumerate() {
                if k > 0 {
                    out.push(',');
                }
                write_json(item, out);
            }
            out.push(']');
        }
        Json::Obj(members) => {
            // RFC 8785 sorts keys by UTF-16 code units.
            let mut sorted: Vec<&(String, Json)> = members.iter().collect();
            sorted.sort_by(|a, b| a.0.encode_utf16().cmp(b.0.encode_utf16()));
            out.push('{');
            for (k, (key, item)) in sorted.into_iter().enumerate() {
                if k > 0 {
                    out.push(',');
                }
                write_str(key, out);
                out.push(':');
                write_json(item, out);
            }
            out.push('}');
        }
    }
}

fn write_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => write!(out, "\\u{:04x}", c as u32).unwrap(),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// The level-1 digest of an attribute's level-2 value.
pub fn level1(value: &Json) -> String {
    sha512t24u(canonical(value).as_bytes())
}

fn strs(items: &[String]) -> Json {
    Json::Arr(items.iter().map(|s| Json::Str(s.clone())).collect())
}

fn ints(items: &[i64]) -> Json {
    Json::Arr(items.iter().map(|&i| Json::Int(i)).collect())
}

/// Level-1 digests of the base attributes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Level1 {
    pub names: String,
    pub lengths: String,
    pub sequences: String,
}

/// (top-level digest, level-1 digests) of a collection; sequences are `SQ.` digests.
pub fn digests(names: &[String], lengths: &[i64], sequences: &[String]) -> (String, Level1) {
    let l1 = Level1 {
        names: level1(&strs(names)),
        lengths: level1(&ints(lengths)),
        sequences: level1(&strs(sequences)),
    };
    let inherent = Json::Obj(vec![
        ("names".into(), Json::Str(l1.names.clone())),
        ("sequences".into(), Json::Str(l1.sequences.clone())),
    ]);
    (level1(&inherent), l1)
}

fn pair(a: &str, av: Json, b: &str, bv: Json) -> Json {
    Json::Obj(vec![(a.into(), av), (b.into(), bv)])
}

/// Level-2 values of the ancillary attributes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ancillary {
    /// `{"name", "length"}` per sequence, in collection order.
    pub name_length_pairs: Vec<(String, i64)>,
    /// The level-1 digest of each name-length pair, sorted.
    pub sorted_name_length_pairs: Vec<String>,
    /// The `SQ.` digests, sorted.
    pub sorted_sequences: Vec<String>,
    /// The level-1 digest of each `{"name", "sequence"}`, in collection order.
    pub named_sequences: Vec<String>,
    /// `named_sequences`, sorted.
    pub sorted_named_sequences: Vec<String>,
}

fn named_sequence(name: &str, sequence: &str) -> String {
    level1(&pair(
        "name",
        Json::Str(name.into()),
        "sequence",
        Json::Str(sequence.into()),
    ))
}

pub fn ancillary(names: &[String], lengths: &[i64], sequences: &[String]) -> Ancillary {
    let name_length_pairs: Vec<(String, i64)> =
        names.iter().cloned().zip(lengths.iter().copied()).collect();
    let mut sorted_name_length_pairs: Vec<String> = name_length_pairs
        .iter()
        .map(|(n, l)| level1(&pair("name", Json::Str(n.clone()), "length", Json::Int(*l))))
        .collect();
    sorted_name_length_pairs.sort();
    let mut sorted_sequences = sequences.to_vec();
    sorted_sequences.sort();
    let named_sequences: Vec<String> = names
        .iter()
        .zip(sequences)
        .map(|(n, s)| named_sequence(n, s))
        .collect();
    let mut sorted_named_sequences = named_sequences.clone();
    sorted_named_sequences.sort();
    Ancillary {
        name_length_pairs,
        sorted_name_length_pairs,
        sorted_sequences,
        named_sequences,
        sorted_named_sequences,
    }
}

/// The order-independent identifier of a named sequence set: the level-1 digest
/// of `sorted_named_sequences`.
pub fn named_set_digest(names: &[String], sequences: &[String]) -> String {
    let mut named: Vec<String> = names
        .iter()
        .zip(sequences)
        .map(|(n, s)| named_sequence(n, s))
        .collect();
    named.sort();
    level1(&strs(&named))
}

/// The seqcol schema refbook serves (`/service-info`): the spec's extended
/// schema plus `named_sequences` and `sorted_named_sequences`.
pub const SCHEMA: &str = include_str!("seqcol_schema.json");

/// Attributes that make the top-level digest (the schema's `ga4gh.inherent`).
pub const INHERENT: &[&str] = &["names", "sequences"];

/// Attributes with a level-1 digest but no level-2 value (`ga4gh.transient`):
/// left out of level 2, so not retrievable by `/attribute`.
pub const TRANSIENT: &[&str] = &["sorted_name_length_pairs", "sorted_named_sequences"];

/// Every attribute refbook gives a collection, at level 2, transient ones
/// included, in schema order.
pub fn attributes(names: &[String], lengths: &[i64], sequences: &[String]) -> Vec<(String, Json)> {
    let a = ancillary(names, lengths, sequences);
    let nlp = Json::Arr(
        a.name_length_pairs
            .iter()
            .map(|(n, l)| pair("name", Json::Str(n.clone()), "length", Json::Int(*l)))
            .collect(),
    );
    vec![
        ("lengths".into(), ints(lengths)),
        ("names".into(), strs(names)),
        ("sequences".into(), strs(sequences)),
        ("name_length_pairs".into(), nlp),
        (
            "sorted_name_length_pairs".into(),
            strs(&a.sorted_name_length_pairs),
        ),
        ("sorted_sequences".into(), strs(&a.sorted_sequences)),
        ("named_sequences".into(), strs(&a.named_sequences)),
        (
            "sorted_named_sequences".into(),
            strs(&a.sorted_named_sequences),
        ),
    ]
}

/// The level-2 representation (`/collection?level=2`): every attribute but
/// the transient ones.
pub fn level2(names: &[String], lengths: &[i64], sequences: &[String]) -> Vec<(String, Json)> {
    attributes(names, lengths, sequences)
        .into_iter()
        .filter(|(k, _)| !TRANSIENT.contains(&k.as_str()))
        .collect()
}

/// The level-1 representation (`/collection?level=1`): the digest of every
/// attribute, transient ones included.
pub fn level1_attributes(
    names: &[String],
    lengths: &[i64],
    sequences: &[String],
) -> Vec<(String, String)> {
    attributes(names, lengths, sequences)
        .into_iter()
        .map(|(k, v)| (k, level1(&v)))
        .collect()
}

/// The top-level digest of a collection given as its attributes, at level 2
/// or (as digests) at level 1, if it has every inherent attribute.
pub fn top_level_digest(collection: &[(String, Json)]) -> Option<String> {
    let mut inherent = Vec::new();
    for &k in INHERENT {
        let v = &collection.iter().find(|(name, _)| name == k)?.1;
        let d = match v {
            Json::Str(digest) => digest.clone(),
            _ => level1(v),
        };
        inherent.push((k.to_string(), Json::Str(d)));
    }
    Some(level1(&Json::Obj(inherent)))
}

/// The two `digests` of a comparison.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Digests {
    pub a: Option<String>,
    pub b: Option<String>,
}

/// The `attributes` of a comparison: attribute names, sorted.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct AttributeSets {
    pub a_only: Vec<String>,
    pub b_only: Vec<String>,
    pub a_and_b: Vec<String>,
}

/// The `array_elements` of a comparison, keyed by attribute name.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ArrayElements {
    pub a_count: BTreeMap<String, usize>,
    pub b_count: BTreeMap<String, usize>,
    pub a_and_b_count: BTreeMap<String, usize>,
    pub a_and_b_same_order: BTreeMap<String, Option<bool>>,
}

/// The return value of seqcol's `/comparison` (spec 3.3).
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Comparison {
    pub digests: Digests,
    pub attributes: AttributeSets,
    pub array_elements: ArrayElements,
}

/// Compare two collections, each given as its attributes at level 2, as
/// seqcol's `/comparison` does (spec 3.3).
///
/// - Every attribute is listed under `attributes`; only arrays are counted
///   under `array_elements`, so an attribute given as a digest (a transient
///   one) is listed but not counted.
/// - Elements are equal when their canonical JSON is.
/// - `a_and_b_count` counts with multiplicity: an element twice in A and
///   once in B counts once.
/// - `a_and_b_same_order` is null with fewer than 2 shared elements, or with
///   unbalanced duplicates (a shared element occurring a different number of
///   times in A and in B); otherwise, whether the shared elements come in the
///   same order.
/// - `digests` are the top-level digests, for a collection with the
///   inherent attributes.
pub fn compare(a: &[(String, Json)], b: &[(String, Json)]) -> Comparison {
    let ka: BTreeSet<&String> = a.iter().map(|(k, _)| k).collect();
    let kb: BTreeSet<&String> = b.iter().map(|(k, _)| k).collect();
    let attributes = AttributeSets {
        a_only: ka.difference(&kb).map(|k| k.to_string()).collect(),
        b_only: kb.difference(&ka).map(|k| k.to_string()).collect(),
        a_and_b: ka.intersection(&kb).map(|k| k.to_string()).collect(),
    };
    let arrays = |c: &[(String, Json)]| -> BTreeMap<String, Vec<String>> {
        c.iter()
            .filter_map(|(k, v)| match v {
                Json::Arr(items) => Some((k.clone(), items.iter().map(canonical).collect())),
                _ => None,
            })
            .collect()
    };
    let (ea, eb) = (arrays(a), arrays(b));
    let count =
        |e: &BTreeMap<String, Vec<String>>| e.iter().map(|(k, v)| (k.clone(), v.len())).collect();
    let mut array_elements = ArrayElements {
        a_count: count(&ea),
        b_count: count(&eb),
        a_and_b_count: BTreeMap::new(),
        a_and_b_same_order: BTreeMap::new(),
    };
    for (k, xa) in &ea {
        if let Some(xb) = eb.get(k) {
            let (shared, order) = compare_elements(xa, xb);
            array_elements.a_and_b_count.insert(k.clone(), shared);
            array_elements.a_and_b_same_order.insert(k.clone(), order);
        }
    }
    Comparison {
        digests: Digests {
            a: top_level_digest(a),
            b: top_level_digest(b),
        },
        attributes,
        array_elements,
    }
}

/// (shared elements, counted with multiplicity; same order) of two arrays.
fn compare_elements(a: &[String], b: &[String]) -> (usize, Option<bool>) {
    fn tally(xs: &[String]) -> HashMap<&str, usize> {
        let mut m = HashMap::new();
        for x in xs {
            *m.entry(x.as_str()).or_default() += 1;
        }
        m
    }
    let (ta, tb) = (tally(a), tally(b));
    let (mut shared, mut balanced) = (0, true);
    for (x, &na) in &ta {
        if let Some(&nb) = tb.get(x) {
            shared += na.min(nb);
            balanced &= na == nb;
        }
    }
    if shared < 2 || !balanced {
        return (shared, None);
    }
    let fa = a.iter().filter(|x| tb.contains_key(x.as_str()));
    let fb = b.iter().filter(|x| ta.contains_key(x.as_str()));
    (shared, Some(fa.eq(fb)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(items: &[&str]) -> Vec<String> {
        items.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn spec_example() {
        let (top, l1) = digests(
            &s(&["chr1", "chr2", "chr3"]),
            &[248956422, 242193529, 198295559],
            &s(&[
                "SQ.2YnepKM7OkBoOrKmvHbGqguVfF9amCST",
                "SQ.lwDyBi432Py-7xnAISyQlnlhWDEaBPv2",
                "SQ.Eqk6_SvMMDCc6C-uEfickOUWTatLMDQZ",
            ]),
        );
        assert_eq!(l1.lengths, "5K4odB173rjao1Cnbk5BnvLt9V7aPAa2");
        assert_eq!(l1.names, "g04lKdxiYtG3dOGeUC5AdKEifw65G0Wp");
        assert_eq!(l1.sequences, "rD29ZKmEqwwHRXjiQ36p6UMZQ5hemmsb");
        assert_eq!(top, "sjNNwm4zov3Dl0FRWbRTcZwzqrTQKIqL");
    }

    #[test]
    fn canonical_json() {
        assert_eq!(
            canonical(&strs(&s(&["a\"b", "c\\d", "\n\t\u{1}", "é"]))),
            r#"["a\"b","c\\d","\n\t\u0001","é"]"#
        );
        assert_eq!(
            canonical(&pair(
                "name",
                Json::Str("x".into()),
                "length",
                Json::Int(-3)
            )),
            r#"{"length":-3,"name":"x"}"#
        );
        assert_eq!(canonical(&Json::Arr(vec![])), "[]");
    }

    #[test]
    fn named_set_digest_ignores_order_only() {
        let a = named_set_digest(&s(&["chr1", "chr2"]), &s(&["SQ.a", "SQ.b"]));
        assert_eq!(
            a,
            named_set_digest(&s(&["chr2", "chr1"]), &s(&["SQ.b", "SQ.a"]))
        );
        assert_ne!(
            a,
            named_set_digest(&s(&["chr1", "chr2"]), &s(&["SQ.b", "SQ.a"]))
        );
    }
    const FIXTURES: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../python/tests/fixtures/refget_compliance"
    );

    fn fixture(path: &str) -> serde_json::Value {
        let text = std::fs::read_to_string(format!("{FIXTURES}/{path}")).unwrap();
        serde_json::from_str(&text).unwrap()
    }

    fn members(v: serde_json::Value) -> Vec<(String, Json)> {
        match Json::try_from(v).unwrap() {
            Json::Obj(m) => m,
            _ => panic!("not an object"),
        }
    }

    fn columns(c: &serde_json::Value) -> (Vec<String>, Vec<i64>, Vec<String>) {
        let strings = |k: &str| -> Vec<String> {
            c[k].as_array()
                .unwrap()
                .iter()
                .map(|x| x.as_str().unwrap().to_string())
                .collect()
        };
        let lengths = c["lengths"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x.as_i64().unwrap())
            .collect();
        (strings("names"), lengths, strings("sequences"))
    }

    #[test]
    fn levels_match_the_compliance_digests() {
        let digests = fixture("test_fasta_digests.json");
        for (name, bundle) in digests.as_object().unwrap() {
            let (n, l, s) = columns(&bundle["level2"]);
            let l1: BTreeMap<String, String> = level1_attributes(&n, &l, &s).into_iter().collect();
            for (k, want) in bundle["level1"].as_object().unwrap() {
                assert_eq!(&l1[k], want.as_str().unwrap(), "{name} level 1 {k}");
            }
            // Level 2 is the suite's, plus refbook's named_sequences; no transient attributes.
            let l2: BTreeMap<String, serde_json::Value> = level2(&n, &l, &s)
                .iter()
                .map(|(k, v)| (k.clone(), serde_json::Value::from(v)))
                .collect();
            for (k, want) in bundle["level2"].as_object().unwrap() {
                assert_eq!(&l2[k], want, "{name} level 2 {k}");
            }
            assert!(TRANSIENT.iter().all(|t| !l2.contains_key(*t)), "{name}");
            assert_eq!(
                l2.len(),
                bundle["level2"].as_object().unwrap().len() + 1,
                "{name}"
            );
            let top = top_level_digest(&level2(&n, &l, &s));
            assert_eq!(
                top.as_deref(),
                bundle["top_level_digest"].as_str(),
                "{name}"
            );
        }
    }

    #[test]
    fn comparisons_match_the_compliance_suite() {
        let dir = std::fs::read_dir(format!("{FIXTURES}/comparison")).unwrap();
        let mut n = 0;
        for entry in dir {
            let file = entry.unwrap().file_name().into_string().unwrap();
            let stem = file
                .strip_prefix("compare_")
                .unwrap()
                .strip_suffix(".fa.json")
                .unwrap();
            let (a, b) = stem.split_once(".fa_").unwrap();
            let mut want = fixture(&format!("comparison/{file}"));
            // The one divergence: the reference implementation gives an order
            // for a single shared element; spec 3.3 says it is undefined.
            let ae = &mut want["array_elements"];
            for (k, n) in ae["a_and_b_count"].clone().as_object().unwrap() {
                if n.as_u64().unwrap() < 2 {
                    ae["a_and_b_same_order"][k] = serde_json::Value::Null;
                }
            }
            let got = compare(
                &members(fixture(&format!("collection/{a}.fa.json"))),
                &members(fixture(&format!("collection/{b}.fa.json"))),
            );
            assert_eq!(serde_json::to_value(&got).unwrap(), want, "{file}");
            n += 1;
        }
        assert_eq!(n, 15);
    }

    #[test]
    fn same_order_rules() {
        let arr = |xs: &[&str]| s(xs);
        // Fewer than 2 shared elements: undefined.
        assert_eq!(
            compare_elements(&arr(&["a", "b"]), &arr(&["a", "c"])),
            (1, None)
        );
        assert_eq!(compare_elements(&arr(&[]), &arr(&[])), (0, None));
        // Unbalanced duplicates: undefined; counted with multiplicity.
        assert_eq!(
            compare_elements(&arr(&["a", "a", "b"]), &arr(&["a", "b"])),
            (2, None)
        );
        assert_eq!(
            compare_elements(&arr(&["a", "a", "b"]), &arr(&["a", "b", "b"])),
            (2, None)
        );
        // Balanced duplicates: order is defined.
        assert_eq!(
            compare_elements(&arr(&["a", "b", "a"]), &arr(&["a", "b", "a", "c"])),
            (3, Some(true))
        );
        assert_eq!(
            compare_elements(&arr(&["a", "a", "b"]), &arr(&["a", "b", "a"])),
            (3, Some(false))
        );
        // Only shared elements count toward order.
        assert_eq!(
            compare_elements(&arr(&["x", "a", "b"]), &arr(&["a", "y", "b"])),
            (2, Some(true))
        );
        assert_eq!(
            compare_elements(&arr(&["b", "a"]), &arr(&["a", "b"])),
            (2, Some(false))
        );
    }

    #[test]
    fn transient_attributes_are_listed_not_counted() {
        let (n, l, s) = (s(&["c1", "c2"]), vec![1, 2], s(&["SQ.a", "SQ.b"]));
        let mut a = level2(&n, &l, &s);
        a.push((
            "sorted_name_length_pairs".into(),
            Json::Str("digest".into()),
        ));
        let c = compare(&a, &level2(&n, &l, &s));
        assert_eq!(c.attributes.a_only, vec!["sorted_name_length_pairs"]);
        assert!(
            !c.array_elements
                .a_count
                .contains_key("sorted_name_length_pairs")
        );
        assert_eq!(c.digests.a, c.digests.b);
        assert!(c.digests.a.is_some());
        assert_eq!(compare(&a[..1], &a[..1]).digests.a, None);
    }

    #[test]
    fn schema_qualifiers_agree_with_the_constants() {
        let schema: serde_json::Value = serde_json::from_str(SCHEMA).unwrap();
        let list = |k: &str| -> Vec<String> {
            schema["ga4gh"][k]
                .as_array()
                .unwrap()
                .iter()
                .map(|x| x.as_str().unwrap().into())
                .collect()
        };
        assert_eq!(list("inherent"), INHERENT);
        assert_eq!(list("transient"), TRANSIENT);
        let props: BTreeSet<&String> = schema["properties"].as_object().unwrap().keys().collect();
        let names = s(&["n"]);
        let ours: BTreeSet<String> = attributes(&names, &[1], &s(&["SQ.a"]))
            .into_iter()
            .map(|(k, _)| k)
            .collect();
        assert_eq!(
            props.into_iter().cloned().collect::<BTreeSet<String>>(),
            ours
        );
    }
}
