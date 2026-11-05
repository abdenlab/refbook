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
use std::fmt::Write;

/// The JSON values seqcol digests: strings, integers, arrays and objects.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Json {
    Str(String),
    Int(i64),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
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
}
