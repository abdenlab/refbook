//! Identify sequences: what each entry of a sequence list is, as far as its
//! evidence goes.
//!
//! An entry has any of a name, a length, an MD5 and an `SQ.` digest (a `.fai`
//! has names and lengths; a `.dict` or CRAM header adds MD5s). Each is
//! identified on its own, with no collection-level guessing:
//!
//! - a digest the store knows pins the sequence: its root, the nucleotide
//!   operations from it, and the flavors that use it (under which names);
//! - otherwise a name that names a root of that length gives the root, and
//!   the stored sequences of that root (its cognates: the same length, the
//!   same bases but for N) are what it could be;
//! - a name alone gives the root, without a length to check it by.
//!
//! Anything that disagrees is a note: an unknown digest, a length other than
//! the sequence's or the root's, a name that names another root or several.

use serde::Serialize;
use std::collections::{BTreeSet, HashMap};

/// One entry of a sequence list.
#[derive(Debug, Clone, Default)]
pub struct Entry {
    pub name: Option<String>,
    pub length: Option<u64>,
    /// The refget MD5 (any case).
    pub md5: Option<String>,
    /// The `SQ.` digest.
    pub sq: Option<String>,
}

/// A stored sequence: a row of the catalog's sequence store.
#[derive(Debug, Clone)]
pub struct Stored {
    pub sq: String,
    pub md5: String,
    pub length: u64,
    pub root_id: String,
    pub operations: Vec<String>,
}

/// The catalog tables identify reads, indexed once.
pub struct IdentifyTables {
    stored: Vec<Stored>,
    by_sq: HashMap<String, usize>,
    by_md5: HashMap<String, usize>,
    root_length: HashMap<String, u64>,
    names: HashMap<String, BTreeSet<String>>,
    of_root: HashMap<String, Vec<usize>>,
    uses: HashMap<String, Vec<(String, String)>>,
}

impl IdentifyTables {
    /// `stored`: the sequence store. `roots`: (root_id, length) of every
    /// root. `aliases`: (root_id, alias) in any namespace. `manifests`:
    /// (flavor, name, SQ. digest) of every flavor's sequences; their names
    /// name roots too.
    pub fn new(
        stored: Vec<Stored>,
        roots: Vec<(String, u64)>,
        aliases: Vec<(String, String)>,
        manifests: Vec<(String, String, String)>,
    ) -> Self {
        let by_sq = stored
            .iter()
            .enumerate()
            .map(|(i, s)| (s.sq.clone(), i))
            .collect();
        let by_md5: HashMap<String, usize> = stored
            .iter()
            .enumerate()
            .map(|(i, s)| (s.md5.to_ascii_lowercase(), i))
            .collect();
        let mut of_root: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, s) in stored.iter().enumerate() {
            of_root.entry(s.root_id.clone()).or_default().push(i);
        }
        let mut names: HashMap<String, BTreeSet<String>> = HashMap::new();
        for (root, alias) in aliases {
            names.entry(alias).or_default().insert(root);
        }
        let mut t = IdentifyTables {
            stored,
            by_sq,
            by_md5,
            root_length: roots.into_iter().collect(),
            names,
            of_root,
            uses: HashMap::new(),
        };
        for (flavor, name, sq) in manifests {
            if let Some(&i) = t.by_sq.get(&sq) {
                let root = t.stored[i].root_id.clone();
                t.names.entry(name.clone()).or_default().insert(root);
                t.uses.entry(sq).or_default().push((flavor, name));
            }
        }
        for v in t.uses.values_mut() {
            v.sort();
        }
        for v in t.of_root.values_mut() {
            v.sort_by(|&a, &b| t.stored[a].sq.cmp(&t.stored[b].sq));
        }
        t
    }
}

/// What an identification rests on.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Evidence {
    /// A digest the store knows.
    Digest,
    /// A name that names one root, of the entry's length.
    NameAndLength,
    /// A name that names one root; no length to check it by.
    Name,
    /// Nothing the catalog knows.
    Nothing,
}

/// A flavor that uses a sequence, under a name.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FlavorUse {
    pub flavor: String,
    pub name: String,
    /// The `SQ.` digest of the sequence it uses.
    pub sequence: String,
}

/// Something about an entry that disagrees with the catalog.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Note {
    /// The entry's digest is not in the store: a sequence the catalog lacks.
    UnknownDigest { digest: String },
    /// The MD5 and the `SQ.` digest are of different stored sequences.
    DigestsDisagree,
    /// The entry's length is not the sequence's (or, without a known digest,
    /// the root's).
    LengthDiffers { expected: u64 },
    /// The name names other roots than the sequence's.
    NameOfOtherRoots { roots: Vec<String> },
    /// The name names several roots of this length (or, without a length,
    /// several roots).
    AmbiguousName { roots: Vec<String> },
    /// The name names roots, none of the entry's length.
    NoRootOfThisLength { roots: Vec<String> },
}

/// What one entry is.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Identity {
    pub evidence: Evidence,
    /// The stored sequence, when a digest pins it.
    pub sequence: Option<String>,
    pub md5: Option<String>,
    pub length: Option<u64>,
    pub root_id: Option<String>,
    /// The operations from the root, when the sequence is pinned.
    pub operations: Option<Vec<String>>,
    /// Without a known digest: the stored sequences of the root of the
    /// entry's length, any of which it could be.
    pub cognates: Vec<String>,
    /// The flavors that use the sequence (or, without a known digest, any of
    /// its cognates under the entry's name).
    pub flavors: Vec<FlavorUse>,
    pub notes: Vec<Note>,
}

fn uses_of<'a>(t: &'a IdentifyTables, sq: &str) -> impl Iterator<Item = FlavorUse> + 'a {
    let sq = sq.to_string();
    t.uses
        .get(&sq)
        .into_iter()
        .flatten()
        .map(move |(f, n)| FlavorUse {
            flavor: f.clone(),
            name: n.clone(),
            sequence: sq.clone(),
        })
}

/// Identify one entry.
pub fn identify_entry(e: &Entry, t: &IdentifyTables) -> Identity {
    let mut notes = Vec::new();
    let by_md5 = e
        .md5
        .as_ref()
        .map(|m| (m, t.by_md5.get(&m.to_ascii_lowercase()).copied()));
    let by_sq = e.sq.as_ref().map(|s| (s, t.by_sq.get(s).copied()));
    for (digest, found) in by_md5.iter().chain(by_sq.iter()) {
        if found.is_none() {
            notes.push(Note::UnknownDigest {
                digest: digest.to_string(),
            });
        }
    }
    let found: BTreeSet<usize> = by_md5
        .iter()
        .chain(by_sq.iter())
        .filter_map(|(_, f)| *f)
        .collect();
    if found.len() > 1 {
        notes.push(Note::DigestsDisagree);
    }
    let named: Vec<String> = e
        .name
        .as_ref()
        .and_then(|n| t.names.get(n))
        .map(|r| r.iter().cloned().collect())
        .unwrap_or_default();

    if let (Some(&i), 1) = (found.iter().next(), found.len()) {
        let s = &t.stored[i];
        if e.length.is_some_and(|l| l != s.length) {
            notes.push(Note::LengthDiffers { expected: s.length });
        }
        if !named.is_empty() && !named.contains(&s.root_id) {
            notes.push(Note::NameOfOtherRoots { roots: named });
        }
        return Identity {
            evidence: Evidence::Digest,
            sequence: Some(s.sq.clone()),
            md5: Some(s.md5.clone()),
            length: Some(s.length),
            root_id: Some(s.root_id.clone()),
            operations: Some(s.operations.clone()),
            cognates: vec![],
            flavors: uses_of(t, &s.sq).collect(),
            notes,
        };
    }

    // No digest pins it: the root the name gives, checked by the length.
    let mut id = Identity {
        evidence: Evidence::Nothing,
        sequence: None,
        md5: None,
        length: e.length,
        root_id: None,
        operations: None,
        cognates: vec![],
        flavors: vec![],
        notes,
    };
    if named.is_empty() {
        return id;
    }
    let roots: Vec<String> = match e.length {
        Some(l) => named
            .iter()
            .filter(|r| t.root_length.get(*r) == Some(&l))
            .cloned()
            .collect(),
        None => named.clone(),
    };
    match roots.len() {
        0 => {
            if let [only] = named.as_slice()
                && let Some(&expected) = t.root_length.get(only)
            {
                id.notes.push(Note::LengthDiffers { expected });
            }
            id.notes.push(Note::NoRootOfThisLength { roots: named });
            return id;
        }
        1 => {}
        _ => {
            id.notes.push(Note::AmbiguousName { roots });
            return id;
        }
    }
    let root = roots[0].clone();
    id.evidence = if e.length.is_some() {
        Evidence::NameAndLength
    } else {
        Evidence::Name
    };
    id.length = t.root_length.get(&root).copied();
    // An entry with a digest the store lacks is none of the stored cognates.
    if e.md5.is_none() && e.sq.is_none() {
        let name = e.name.as_deref().unwrap_or_default();
        for &i in t.of_root.get(&root).into_iter().flatten() {
            let s = &t.stored[i];
            if Some(s.length) == id.length {
                id.cognates.push(s.sq.clone());
                id.flavors
                    .extend(uses_of(t, &s.sq).filter(|u| u.name == name));
            }
        }
        id.flavors
            .sort_by(|a, b| (&a.flavor, &a.name).cmp(&(&b.flavor, &b.name)));
    }
    id.root_id = Some(root);
    id
}

/// Identify every entry of a sequence list, in order.
pub fn identify(entries: &[Entry], t: &IdentifyTables) -> Vec<Identity> {
    entries.iter().map(|e| identify_entry(e, t)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tables() -> IdentifyTables {
        let st = |sq: &str, md5: &str, len, root: &str, ops: &[&str]| Stored {
            sq: sq.into(),
            md5: md5.into(),
            length: len,
            root_id: root.into(),
            operations: ops.iter().map(|o| o.to_string()).collect(),
        };
        let s = |a: &str, b: &str| (a.to_string(), b.to_string());
        IdentifyTables::new(
            vec![
                st("SQ.r1", "aa", 100, "R1", &[]),
                st("SQ.r1n", "ab", 100, "R1", &["iupac_to_n"]),
                st("SQ.r2", "bb", 50, "R2", &[]),
                st("SQ.r3", "cc", 50, "R3", &[]),
            ],
            vec![("R1".into(), 100), ("R2".into(), 50), ("R3".into(), 50)],
            vec![
                s("R1", "chr1"),
                s("R1", "1"),
                s("R2", "chrX"),
                s("R3", "chrX"),
            ],
            vec![
                ("hg".into(), "chr1".into(), "SQ.r1n".into()),
                ("grc".into(), "chr1".into(), "SQ.r1".into()),
                ("ens".into(), "1".into(), "SQ.r1".into()),
                ("grc".into(), "chrX".into(), "SQ.r2".into()),
            ],
        )
    }

    fn entry(name: Option<&str>, length: Option<u64>, md5: Option<&str>) -> Entry {
        Entry {
            name: name.map(Into::into),
            length,
            md5: md5.map(Into::into),
            sq: None,
        }
    }

    #[test]
    fn a_known_digest_pins_the_sequence() {
        let t = tables();
        let id = identify_entry(&entry(Some("chr1"), Some(100), Some("AB")), &t);
        assert_eq!(id.evidence, Evidence::Digest);
        assert_eq!(id.sequence.as_deref(), Some("SQ.r1n"));
        assert_eq!(id.operations, Some(vec!["iupac_to_n".to_string()]));
        assert_eq!(
            id.flavors,
            vec![FlavorUse {
                flavor: "hg".into(),
                name: "chr1".into(),
                sequence: "SQ.r1n".into()
            }]
        );
        assert!(id.notes.is_empty());
        let by_sq = identify_entry(
            &Entry {
                sq: Some("SQ.r1n".into()),
                ..Default::default()
            },
            &t,
        );
        assert_eq!(by_sq.sequence, id.sequence);
    }

    #[test]
    fn disagreements_are_notes() {
        let t = tables();
        let id = identify_entry(&entry(Some("chrX"), Some(99), Some("aa")), &t);
        assert_eq!(id.sequence.as_deref(), Some("SQ.r1"));
        assert_eq!(
            id.notes,
            vec![
                Note::LengthDiffers { expected: 100 },
                Note::NameOfOtherRoots {
                    roots: vec!["R2".into(), "R3".into()]
                }
            ]
        );
        let both = Entry {
            md5: Some("aa".into()),
            sq: Some("SQ.r2".into()),
            ..Default::default()
        };
        assert!(
            identify_entry(&both, &t)
                .notes
                .contains(&Note::DigestsDisagree)
        );
    }

    #[test]
    fn name_and_length_give_the_root_and_its_cognates() {
        let t = tables();
        let id = identify_entry(&entry(Some("chr1"), Some(100), None), &t);
        assert_eq!(id.evidence, Evidence::NameAndLength);
        assert_eq!(
            (id.root_id.as_deref(), id.sequence.as_deref()),
            (Some("R1"), None)
        );
        assert_eq!(id.cognates, vec!["SQ.r1", "SQ.r1n"]);
        assert_eq!(
            id.flavors
                .iter()
                .map(|u| u.flavor.as_str())
                .collect::<Vec<_>>(),
            ["grc", "hg"]
        );
        let id = identify_entry(&entry(Some("1"), None, None), &t);
        assert_eq!(
            (id.evidence, id.root_id.as_deref()),
            (Evidence::Name, Some("R1"))
        );
    }

    #[test]
    fn an_unknown_digest_is_a_version_of_the_root_we_lack() {
        let t = tables();
        let id = identify_entry(&entry(Some("chr1"), Some(100), Some("ff")), &t);
        assert_eq!(
            (id.evidence, id.root_id.as_deref()),
            (Evidence::NameAndLength, Some("R1"))
        );
        assert!(id.cognates.is_empty() && id.sequence.is_none());
        assert_eq!(
            id.notes,
            vec![Note::UnknownDigest {
                digest: "ff".into()
            }]
        );
    }

    #[test]
    fn names_that_do_not_settle_it() {
        let t = tables();
        let ambiguous = identify_entry(&entry(Some("chrX"), Some(50), None), &t);
        assert_eq!(ambiguous.evidence, Evidence::Nothing);
        assert_eq!(
            ambiguous.notes,
            vec![Note::AmbiguousName {
                roots: vec!["R2".into(), "R3".into()]
            }]
        );
        let wrong = identify_entry(&entry(Some("chr1"), Some(7), None), &t);
        assert_eq!(
            wrong.notes,
            vec![
                Note::LengthDiffers { expected: 100 },
                Note::NoRootOfThisLength {
                    roots: vec!["R1".into()]
                }
            ]
        );
        assert_eq!(
            identify_entry(&entry(Some("chrZ"), Some(5), None), &t).evidence,
            Evidence::Nothing
        );
        assert_eq!(
            identify_entry(&entry(None, Some(100), None), &t).evidence,
            Evidence::Nothing
        );
    }
}
