//! The recipe compiler: a recipe and the catalog's tables in, an edition's
//! manifest rows out (name, root, nucleotide operations), in canonical order.
//!
//! A recipe (catalog/books/<book>/recipes/*.json) is data:
//!
//! - `select`: entries, each one of
//!   - `{"assembly": <accession.version>, "roles": [...], "accessions": [...]?,
//!     "placed_on": [...]?}`: members of an assembly with one of the roles,
//!     optionally only those accessions, and with `placed_on` only roots placed,
//!     if at all, on those parent types;
//!   - `{"roots": [...]}`: roots in no assembly (e.g. EBV);
//!   - `{"collection": ..., "groups": [...]}`: external roots, in their
//!     collection's rank order (never materialized).
//! - `mask`: `[{"layer": <name>, "with": "N"}]`, hard-mask a layer's spans.
//! - `alphabet`: `{"iupac": "N"}`, every IUPAC code to N.
//! - `rename`: `{"namespace", "by_role"?, "map"?, "template"?}`. The map wins,
//!   then the template for the root's assembly or collection (placeholders
//!   `{accession}`, `{accession_v}` with "." as "v", `{name}` for an external
//!   root), then the namespace for the root's role, then the default namespace.
//!
//! A recipe defines a named sequence set: no order, no formatting. Other keys
//! of a recipe (`target`, `published`, ...) are its metadata and are ignored;
//! a key the grammar doesn't know inside `select`, `mask`, `alphabet` or
//! `rename` is an error.

use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;

/// The operation `alphabet: {"iupac": "N"}` applies.
pub const IUPAC_TO_N: &str = "iupac_to_n";

/// Why a recipe doesn't compile.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RecipeError {
    /// Not valid recipe JSON, or not the grammar.
    Malformed(String),
    NoAssembly(String),
    NoRoot(String),
    NothingInCollection {
        collection: String,
        groups: Vec<String>,
    },
    SelectedTwice(String),
    /// A root with no name in the namespace its rename rule picks.
    NoName {
        root: String,
        namespace: String,
    },
    BadTemplate {
        template: String,
        reason: String,
    },
    NameUsedTwice(String),
    UnsupportedMask(String),
    /// A mask layer the tables don't have.
    UnknownLayer(String),
    UnsupportedAlphabet(String),
    /// An external root (bases not hosted) that an operation would change.
    ExternalChanged(String),
}

impl fmt::Display for RecipeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        use RecipeError::*;
        match self {
            Malformed(m) => write!(f, "malformed recipe: {m}"),
            NoAssembly(a) => write!(f, "no assembly {a}"),
            NoRoot(r) => write!(f, "no root {r}"),
            NothingInCollection { collection, groups } => {
                write!(f, "nothing in {collection} {groups:?}")
            }
            SelectedTwice(r) => write!(f, "root {r} is selected twice"),
            NoName { root, namespace } => {
                write!(f, "{root}: no {namespace} name and no rule to make one")
            }
            BadTemplate { template, reason } => write!(f, "template {template:?}: {reason}"),
            NameUsedTwice(n) => write!(f, "name {n} is used twice"),
            UnsupportedMask(m) => write!(f, "only N masks are implemented, not {m}"),
            UnknownLayer(l) => write!(f, "no mask layer {l}"),
            UnsupportedAlphabet(a) => {
                write!(
                    f,
                    "only the alphabet change iupac -> N is implemented, not {a}"
                )
            }
            ExternalChanged(r) => {
                write!(
                    f,
                    "{r}: external root (bases not hosted) would need materializing"
                )
            }
        }
    }
}

impl std::error::Error for RecipeError {}

/// A name column of assembly_members: UCSC names, GRC's Sequence-Names
/// (`grc`; `sequence`, the report column's name, is accepted too), GenBank
/// and RefSeq accessions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Namespace {
    Ucsc,
    #[serde(alias = "sequence")]
    Grc,
    Genbank,
    Refseq,
}

impl fmt::Display for Namespace {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Namespace::Ucsc => "ucsc",
            Namespace::Grc => "grc",
            Namespace::Genbank => "genbank",
            Namespace::Refseq => "refseq",
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssemblyEntry {
    pub assembly: String,
    pub roles: Vec<String>,
    #[serde(default)]
    pub accessions: Vec<String>,
    #[serde(default)]
    pub placed_on: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootsEntry {
    pub roots: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CollectionEntry {
    pub collection: String,
    pub groups: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Entry {
    Assembly(AssemblyEntry),
    Roots(RootsEntry),
    Collection(CollectionEntry),
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Mask {
    pub layer: String,
    pub with: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Alphabet {
    pub iupac: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rename {
    pub namespace: Namespace,
    #[serde(default)]
    pub by_role: BTreeMap<String, Namespace>,
    #[serde(default)]
    pub map: BTreeMap<String, String>,
    #[serde(default)]
    pub template: BTreeMap<String, String>,
}

/// A recipe's grammar, parsed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Recipe {
    pub select: Vec<Entry>,
    pub mask: Vec<Mask>,
    pub alphabet: Alphabet,
    pub rename: Rename,
}

fn field<T: DeserializeOwned>(v: Value, what: &str) -> Result<T, RecipeError> {
    serde_json::from_value(v).map_err(|e| RecipeError::Malformed(format!("{what}: {e}")))
}

impl Recipe {
    pub fn from_json(text: &str) -> Result<Recipe, RecipeError> {
        let v: Value =
            serde_json::from_str(text).map_err(|e| RecipeError::Malformed(e.to_string()))?;
        Recipe::from_value(v)
    }

    pub fn from_value(v: Value) -> Result<Recipe, RecipeError> {
        let Value::Object(mut o) = v else {
            return Err(RecipeError::Malformed("not an object".into()));
        };
        let take = |o: &mut serde_json::Map<String, Value>, k: &str| o.remove(k);
        let select: Vec<Value> = field(
            take(&mut o, "select").ok_or(RecipeError::Malformed("no select".into()))?,
            "select",
        )?;
        let select = select
            .into_iter()
            .map(|e| {
                let has = |k| e.get(k).is_some();
                if has("collection") {
                    field(e, "a collection entry").map(Entry::Collection)
                } else if has("roots") {
                    field(e, "a roots entry").map(Entry::Roots)
                } else if has("assembly") {
                    field(e, "an assembly entry").map(Entry::Assembly)
                } else {
                    Err(RecipeError::Malformed(format!(
                        "a select entry needs assembly, roots or collection: {e}"
                    )))
                }
            })
            .collect::<Result<_, _>>()?;
        let mask = match take(&mut o, "mask") {
            Some(m) => field(m, "mask")?,
            None => vec![],
        };
        let alphabet = match take(&mut o, "alphabet") {
            Some(a) => field(a, "alphabet")?,
            None => Alphabet::default(),
        };
        let rename = field(
            take(&mut o, "rename").ok_or(RecipeError::Malformed("no rename".into()))?,
            "rename",
        )?;
        Ok(Recipe {
            select,
            mask,
            alphabet,
            rename,
        })
    }
}

/// A row of assembly_members.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Member {
    pub assembly: String,
    pub accession: String,
    pub role: String,
    pub ucsc_name: Option<String>,
    pub sequence_name: Option<String>,
    pub refseq_accession: Option<String>,
}

impl Member {
    fn name(&self, ns: Namespace) -> Option<&str> {
        match ns {
            Namespace::Ucsc => self.ucsc_name.as_deref(),
            Namespace::Grc => self.sequence_name.as_deref(),
            Namespace::Genbank => Some(self.accession.as_str()),
            Namespace::Refseq => self.refseq_accession.as_deref(),
        }
        .filter(|s| !s.is_empty())
    }
}

/// A row of roots_external.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct External {
    pub root_id: String,
    pub collection: String,
    pub group: String,
    pub name: Option<String>,
}

/// What the compiler reads from the catalog.
#[derive(Debug, Clone, Default)]
pub struct Tables {
    /// assembly_members, in report order.
    pub members: Vec<Member>,
    /// Every root, hosted or external.
    pub roots: HashSet<String>,
    /// Roots with IUPAC codes (n_iupac > 0).
    pub iupac: HashSet<String>,
    /// Mask layer -> the roots it has spans on.
    pub layers: HashMap<String, HashSet<String>>,
    /// roots_external, in rank order.
    pub external: Vec<External>,
    /// Root -> the parent types it is placed on (layer_placements).
    pub parent_types: HashMap<String, HashSet<String>>,
}

/// A manifest row: a name, its root, and the operations that make it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Row {
    pub name: String,
    pub root_id: String,
    pub operations: Vec<String>,
}

enum Via<'a> {
    Member(&'a Member),
    External(&'a External),
    Root,
}

struct Selected<'a> {
    root_id: &'a str,
    /// The entry's assembly or collection, for templates.
    source: Option<&'a str>,
    via: Via<'a>,
}

fn select<'a>(recipe: &'a Recipe, t: &'a Tables) -> Result<Vec<Selected<'a>>, RecipeError> {
    let mut out = Vec::new();
    for entry in &recipe.select {
        match entry {
            Entry::Collection(c) => {
                let n = out.len();
                for e in &t.external {
                    if e.collection == c.collection && c.groups.contains(&e.group) {
                        out.push(Selected {
                            root_id: &e.root_id,
                            source: Some(&c.collection),
                            via: Via::External(e),
                        });
                    }
                }
                if out.len() == n {
                    return Err(RecipeError::NothingInCollection {
                        collection: c.collection.clone(),
                        groups: c.groups.clone(),
                    });
                }
            }
            Entry::Roots(r) => {
                for acc in &r.roots {
                    if !t.roots.contains(acc) {
                        return Err(RecipeError::NoRoot(acc.clone()));
                    }
                    out.push(Selected {
                        root_id: acc,
                        source: None,
                        via: Via::Root,
                    });
                }
            }
            Entry::Assembly(a) => {
                let mut any = false;
                for m in t.members.iter().filter(|m| m.assembly == a.assembly) {
                    any = true;
                    let placed_elsewhere = !a.placed_on.is_empty()
                        && t.parent_types
                            .get(&m.accession)
                            .is_some_and(|p| p.iter().any(|x| !a.placed_on.contains(x)));
                    if placed_elsewhere
                        || !a.roles.contains(&m.role)
                        || !(a.accessions.is_empty() || a.accessions.contains(&m.accession))
                    {
                        continue;
                    }
                    out.push(Selected {
                        root_id: &m.accession,
                        source: Some(&a.assembly),
                        via: Via::Member(m),
                    });
                }
                if !any {
                    return Err(RecipeError::NoAssembly(a.assembly.clone()));
                }
            }
        }
    }
    let mut seen = HashSet::new();
    for s in &out {
        if !seen.insert(s.root_id) {
            return Err(RecipeError::SelectedTwice(s.root_id.into()));
        }
    }
    Ok(out)
}

/// Fill a template's placeholders; `{{` and `}}` are literal braces.
pub fn fill_template(
    template: &str,
    accession: &str,
    name: Option<&str>,
) -> Result<String, RecipeError> {
    let bad = |reason: String| RecipeError::BadTemplate {
        template: template.into(),
        reason,
    };
    let mut out = String::new();
    let mut rest = template;
    while let Some(i) = rest.find(['{', '}']) {
        out.push_str(&rest[..i]);
        let tail = &rest[i..];
        if tail.starts_with("{{") || tail.starts_with("}}") {
            out.push_str(&tail[..1]);
            rest = &tail[2..];
            continue;
        }
        if tail.starts_with('}') {
            return Err(bad("unmatched '}'".into()));
        }
        let end = tail.find('}').ok_or_else(|| bad("unmatched '{'".into()))?;
        match &tail[1..end] {
            "accession" => out.push_str(accession),
            "accession_v" => out.push_str(&accession.replace('.', "v")),
            "name" => out.push_str(name.ok_or_else(|| bad(format!("{accession} has no name")))?),
            other => return Err(bad(format!("unknown placeholder {{{other}}}"))),
        }
        rest = &tail[end + 1..];
    }
    out.push_str(rest);
    Ok(out)
}

fn name_of(s: &Selected, rename: &Rename) -> Result<String, RecipeError> {
    if let Some(n) = rename.map.get(s.root_id) {
        return Ok(n.clone());
    }
    if let Some(tpl) = s.source.and_then(|a| rename.template.get(a)) {
        let name = match s.via {
            Via::External(e) => e.name.as_deref(),
            _ => None,
        };
        return fill_template(tpl, s.root_id, name);
    }
    let member = match s.via {
        Via::Member(m) => Some(m),
        _ => None,
    };
    let ns = member
        .and_then(|m| rename.by_role.get(&m.role))
        .copied()
        .unwrap_or(rename.namespace);
    member
        .and_then(|m| m.name(ns))
        .map(String::from)
        .ok_or_else(|| RecipeError::NoName {
            root: s.root_id.into(),
            namespace: ns.to_string(),
        })
}

/// Compile a recipe: its manifest rows, in canonical order (by name, as bytes).
/// Each row's operations are the recipe's mask layers that have spans on the
/// root, in recipe order, then `iupac_to_n` if the alphabet change applies and
/// the root has IUPAC codes.
pub fn compile(recipe: &Recipe, t: &Tables) -> Result<Vec<Row>, RecipeError> {
    for m in &recipe.mask {
        if m.with != "N" {
            return Err(RecipeError::UnsupportedMask(m.with.clone()));
        }
        if !t.layers.contains_key(&m.layer) {
            return Err(RecipeError::UnknownLayer(m.layer.clone()));
        }
    }
    let to_n = match recipe.alphabet.iupac.as_deref() {
        None => false,
        Some("N") => true,
        Some(other) => {
            return Err(RecipeError::UnsupportedAlphabet(format!(
                "iupac -> {other}"
            )));
        }
    };
    let mut rows = Vec::new();
    let mut names = HashSet::new();
    for s in select(recipe, t)? {
        let name = name_of(&s, &recipe.rename)?;
        if !names.insert(name.clone()) {
            return Err(RecipeError::NameUsedTwice(name));
        }
        let mut operations: Vec<String> = recipe
            .mask
            .iter()
            .filter(|m| t.layers[&m.layer].contains(s.root_id))
            .map(|m| m.layer.clone())
            .collect();
        if to_n && t.iupac.contains(s.root_id) {
            operations.push(IUPAC_TO_N.into());
        }
        if matches!(s.via, Via::External(_)) && !operations.is_empty() {
            return Err(RecipeError::ExternalChanged(s.root_id.into()));
        }
        rows.push(Row {
            name,
            root_id: s.root_id.into(),
            operations,
        });
    }
    rows.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(rows)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn member(acc: &str, role: &str, ucsc: &str, seq: Option<&str>) -> Member {
        Member {
            assembly: "GCA_1.1".into(),
            accession: acc.into(),
            role: role.into(),
            ucsc_name: Some(ucsc.into()),
            sequence_name: seq.map(String::from),
            refseq_accession: None,
        }
    }

    fn tables() -> Tables {
        let set = |xs: &[&str]| xs.iter().map(|x| x.to_string()).collect::<HashSet<_>>();
        Tables {
            members: vec![
                member("C1.1", "assembled-molecule", "chr1", Some("1")),
                member("U1.1", "unlocalized-scaffold", "chr1_U1v1_random", None),
                member("P1.1", "unplaced-scaffold", "chrUn_P1v1", None),
                member("A1.1", "alt-scaffold", "chr1_A1v1_alt", None),
                member("F1.1", "fix-patch", "chr1_F1v1_fix", None),
                member("F2.1", "fix-patch", "chr1_F2v1_fix", None),
            ],
            roots: set(&[
                "C1.1", "U1.1", "P1.1", "A1.1", "F1.1", "F2.1", "EBV.1", "H1", "H2",
            ]),
            iupac: set(&["C1.1", "H1"]),
            layers: [("hardmask_x".to_string(), set(&["P1.1", "H2"]))].into(),
            external: vec![
                External {
                    root_id: "H1".into(),
                    collection: "HLA".into(),
                    group: "A".into(),
                    name: Some("A*01".into()),
                },
                External {
                    root_id: "H2".into(),
                    collection: "HLA".into(),
                    group: "B".into(),
                    name: Some("B*07".into()),
                },
            ],
            parent_types: [
                ("A1.1".to_string(), set(&["chromosome"])),
                ("F1.1".to_string(), set(&["chromosome"])),
                ("F2.1".to_string(), set(&["scaffold"])),
            ]
            .into(),
        }
    }

    fn compiled(json: &str) -> Result<Vec<(String, String, Vec<String>)>, RecipeError> {
        let rows = compile(&Recipe::from_json(json)?, &tables())?;
        Ok(rows
            .into_iter()
            .map(|r| (r.name, r.root_id, r.operations))
            .collect())
    }

    fn roots(json: &str) -> Vec<String> {
        let mut r: Vec<String> = compiled(json).unwrap().into_iter().map(|r| r.1).collect();
        r.sort();
        r
    }

    #[test]
    fn select_entry_kinds_and_narrowings() {
        assert_eq!(
            roots(
                r#"{"select": [{"assembly": "GCA_1.1", "roles": ["assembled-molecule"]},
                {"roots": ["EBV.1"]}, {"collection": "HLA", "groups": ["A"]}],
                "rename": {"namespace": "genbank", "map": {"EBV.1": "chrEBV"},
                    "template": {"HLA": "HLA-{name}"}}}"#
            ),
            ["C1.1", "EBV.1", "H1"].map(String::from)
        );
        assert_eq!(
            roots(
                r#"{"select": [{"assembly": "GCA_1.1", "roles": ["alt-scaffold", "fix-patch"],
                "placed_on": ["chromosome"]}], "rename": {"namespace": "ucsc"}}"#
            ),
            ["A1.1", "F1.1"].map(String::from)
        );
        assert_eq!(
            roots(
                r#"{"select": [{"assembly": "GCA_1.1", "roles": ["fix-patch"],
                "accessions": ["F2.1"]}], "rename": {"namespace": "ucsc"}}"#
            ),
            ["F2.1"].map(String::from)
        );
    }

    #[test]
    fn rename_precedence_and_operations() {
        let rows = compiled(
            r#"{"target": "t", "published": "x",
            "select": [{"assembly": "GCA_1.1", "roles": ["assembled-molecule",
                "unlocalized-scaffold", "unplaced-scaffold"]}, {"roots": ["EBV.1"]},
                {"collection": "HLA", "groups": ["A"]}],
            "mask": [{"layer": "hardmask_x", "with": "N"}], "alphabet": {"iupac": "N"},
            "rename": {"namespace": "ucsc", "by_role": {"assembled-molecule": "grc"},
                "map": {"U1.1": "mapped", "EBV.1": "chrEBV"},
                "template": {"HLA": "HLA-{name}"}}}"#,
        );
        let ops = |xs: &[&str]| xs.iter().map(|x| x.to_string()).collect::<Vec<_>>();
        let row = |n: &str, r: &str, o: &[&str]| (n.to_string(), r.to_string(), ops(o));
        // H1 has IUPAC codes, but is external: iupac_to_n would change it.
        assert_eq!(rows, Err(RecipeError::ExternalChanged("H1".into())));
        let rows = compiled(
            r#"{"select": [{"assembly": "GCA_1.1", "roles": ["assembled-molecule",
                "unlocalized-scaffold", "unplaced-scaffold"]}, {"roots": ["EBV.1"]}],
            "mask": [{"layer": "hardmask_x", "with": "N"}], "alphabet": {"iupac": "N"},
            "rename": {"namespace": "ucsc", "by_role": {"assembled-molecule": "grc"},
                "map": {"U1.1": "mapped", "EBV.1": "chrEBV"},
                "template": {"GCA_1.1": "t_{accession_v}"}}}"#,
        )
        .unwrap();
        assert_eq!(
            rows,
            vec![
                row("chrEBV", "EBV.1", &[]),
                row("mapped", "U1.1", &[]),
                row("t_C1v1", "C1.1", &["iupac_to_n"]),
                row("t_P1v1", "P1.1", &["hardmask_x"]),
            ]
        );
    }

    #[test]
    fn errors() {
        use RecipeError::*;
        let err = |j: &str| compiled(j).unwrap_err();
        let am = r#"{"assembly": "GCA_1.1", "roles": ["assembled-molecule"]}"#;
        let r = |select: &str, rest: &str| {
            format!(r#"{{"select": [{select}], "rename": {{"namespace": "ucsc"}}{rest}}}"#)
        };
        assert_eq!(
            err(&r(&format!("{am}, {am}"), "")),
            SelectedTwice("C1.1".into())
        );
        assert_eq!(
            err(&r(r#"{"assembly": "GCA_9.9", "roles": []}"#, "")),
            NoAssembly("GCA_9.9".into())
        );
        assert_eq!(err(&r(r#"{"roots": ["NOPE"]}"#, "")), NoRoot("NOPE".into()));
        assert!(matches!(
            err(&r(r#"{"collection": "HLA", "groups": ["Z"]}"#, "")),
            NothingInCollection { .. }
        ));
        assert_eq!(
            err(&r(r#"{"roots": ["EBV.1"]}"#, "")),
            NoName {
                root: "EBV.1".into(),
                namespace: "ucsc".into()
            }
        );
        assert!(matches!(
            err(&r(am, r#", "mask": [{"layer": "x", "with": "X"}]"#)),
            UnsupportedMask(_)
        ));
        assert_eq!(
            err(&r(am, r#", "mask": [{"layer": "nope", "with": "N"}]"#)),
            UnknownLayer("nope".into())
        );
        assert!(matches!(
            err(&r(am, r#", "alphabet": {"iupac": "X"}"#)),
            UnsupportedAlphabet(_)
        ));
        assert!(matches!(
            err(&r(am, r#", "alphabet": {"iupac": "N", "oops": 1}"#)),
            Malformed(_)
        ));
        assert!(matches!(
            err(&r(r#"{"assembly": "GCA_1.1", "role": []}"#, "")),
            Malformed(_)
        ));
        let two = r#"{"select": [{"assembly": "GCA_1.1", "roles": ["assembled-molecule",
            "unplaced-scaffold"]}], "rename": {"namespace": "ucsc", "map": {"P1.1": "chr1"}}}"#;
        assert_eq!(err(two), NameUsedTwice("chr1".into()));
    }

    #[test]
    fn templates() {
        assert_eq!(
            fill_template("chrUn_{accession_v}_decoy", "K.1", None).unwrap(),
            "chrUn_Kv1_decoy"
        );
        assert_eq!(
            fill_template("{{{accession}}}", "K.1", None).unwrap(),
            "{K.1}"
        );
        assert_eq!(
            fill_template("HLA-{name}", "H", Some("A*01")).unwrap(),
            "HLA-A*01"
        );
        for bad in ["{nope}", "{accession", "}", "{name}"] {
            assert!(fill_template(bad, "K.1", None).is_err(), "{bad}");
        }
    }

    #[test]
    fn sequence_is_still_the_grc_namespace() {
        let r = Recipe::from_json(
            r#"{"select": [{"assembly": "A", "roles": ["assembled-molecule"]}],
                "rename": {"namespace": "sequence"}}"#,
        )
        .unwrap();
        assert_eq!(r.rename.namespace, Namespace::Grc);
        assert_eq!(r.rename.namespace.to_string(), "grc");
    }
}
