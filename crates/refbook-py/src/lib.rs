//! refbook._core: Python bindings of refbook-core.

use pyo3::create_exception;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3::types::{PyBool, PyDict, PyInt, PyList, PyString, PyTuple};
use refbook_core::identify;
use refbook_core::operations;
use refbook_core::recipe;
use refbook_core::refget;
use refbook_core::seqcol::{self, Json};

fn non_canonical(e: refget::NonCanonicalBase) -> PyErr {
    PyValueError::new_err(e.to_string())
}

/// The bases refget digests: whitespace removed, uppercased, A-Z only.
/// Raises ValueError on any other character.
#[pyfunction]
fn canonical_bases<'py>(py: Python<'py>, seq: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    let out = py
        .detach(|| refget::canonical_bases(seq))
        .map_err(non_canonical)?;
    Ok(PyBytes::new(py, &out))
}

/// The bytes with whitespace removed.
#[pyfunction]
fn remove_whitespace<'py>(py: Python<'py>, seq: &[u8]) -> Bound<'py, PyBytes> {
    let out = py.detach(|| refget::remove_whitespace(seq));
    PyBytes::new(py, &out)
}

/// (MD5, SQ. digest) of canonical bases.
#[pyfunction]
fn digests(py: Python<'_>, bases: &[u8]) -> (String, String) {
    py.detach(|| refget::digests(bases))
}

/// The GA4GH digest of bytes: SHA-512 truncated to 24 bytes, base64url.
#[pyfunction]
fn sha512t24u(py: Python<'_>, data: &[u8]) -> String {
    py.detach(|| refget::sha512t24u(data))
}

/// Scan one sequence (whitespace removed): a dict of its canonical bases,
/// digests, lowercase runs, N-runs and IUPAC positions (with their codes).
#[pyfunction]
fn scan<'py>(py: Python<'py>, seq: &[u8]) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
    let s = py.detach(|| refget::scan(seq)).map_err(non_canonical)?;
    let d = pyo3::types::PyDict::new(py);
    d.set_item("bases", PyBytes::new(py, &s.bases))?;
    d.set_item("md5", s.md5)?;
    d.set_item("sha512t24u", s.sha512t24u)?;
    d.set_item("lower", s.lower)?;
    d.set_item("n_runs", s.n_runs)?;
    let iupac: Vec<(usize, String)> = s
        .iupac
        .into_iter()
        .map(|(i, c)| (i, (c as char).to_string()))
        .collect();
    d.set_item("iupac", iupac)?;
    Ok(d)
}

fn to_json(obj: &Bound<'_, PyAny>) -> PyResult<Json> {
    if obj.is_instance_of::<PyString>() {
        Ok(Json::Str(obj.extract()?))
    } else if obj.is_instance_of::<PyBool>() {
        Err(PyValueError::new_err(
            "booleans are not part of seqcol's JSON",
        ))
    } else if obj.is_instance_of::<PyInt>() {
        Ok(Json::Int(obj.extract()?))
    } else if obj.is_instance_of::<PyList>() || obj.is_instance_of::<PyTuple>() {
        obj.try_iter()?
            .map(|item| to_json(&item?))
            .collect::<PyResult<_>>()
            .map(Json::Arr)
    } else if obj.is_instance_of::<PyDict>() {
        let d: Bound<'_, PyDict> = obj.extract()?;
        d.iter()
            .map(|(k, v)| Ok((k.extract::<String>()?, to_json(&v)?)))
            .collect::<PyResult<_>>()
            .map(Json::Obj)
    } else {
        Err(PyValueError::new_err(format!(
            "not a seqcol JSON value: {obj}"
        )))
    }
}

/// RFC-8785 canonical JSON of a value made of strings, integers, lists and dicts.
#[pyfunction]
fn canonical_json(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(seqcol::canonical(&to_json(obj)?))
}

/// The level-1 digest of an attribute's level-2 value.
#[pyfunction]
fn level1(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(seqcol::level1(&to_json(obj)?))
}

/// (top-level digest, level-1 digests of names, lengths and sequences).
#[pyfunction]
fn seqcol_digests<'py>(
    py: Python<'py>,
    names: Vec<String>,
    lengths: Vec<i64>,
    sequences: Vec<String>,
) -> PyResult<(String, Bound<'py, PyDict>)> {
    let (top, l1) = py.detach(|| seqcol::digests(&names, &lengths, &sequences));
    let d = PyDict::new(py);
    d.set_item("lengths", l1.lengths)?;
    d.set_item("names", l1.names)?;
    d.set_item("sequences", l1.sequences)?;
    Ok((top, d))
}

/// Level-2 values of the ancillary attributes, by name.
#[pyfunction]
fn seqcol_ancillary<'py>(
    py: Python<'py>,
    names: Vec<String>,
    lengths: Vec<i64>,
    sequences: Vec<String>,
) -> PyResult<Bound<'py, PyDict>> {
    let a = py.detach(|| seqcol::ancillary(&names, &lengths, &sequences));
    let pairs = PyList::empty(py);
    for (name, length) in a.name_length_pairs {
        let p = PyDict::new(py);
        p.set_item("name", name)?;
        p.set_item("length", length)?;
        pairs.append(p)?;
    }
    let d = PyDict::new(py);
    d.set_item("name_length_pairs", pairs)?;
    d.set_item("sorted_name_length_pairs", a.sorted_name_length_pairs)?;
    d.set_item("sorted_sequences", a.sorted_sequences)?;
    d.set_item("named_sequences", a.named_sequences)?;
    d.set_item("sorted_named_sequences", a.sorted_named_sequences)?;
    Ok(d)
}

fn to_py<'py>(py: Python<'py>, j: &Json) -> PyResult<Bound<'py, PyAny>> {
    Ok(match j {
        Json::Str(s) => s.into_pyobject(py)?.into_any(),
        Json::Int(i) => i.into_pyobject(py)?.into_any(),
        Json::Arr(items) => {
            let l = PyList::empty(py);
            for item in items {
                l.append(to_py(py, item)?)?;
            }
            l.into_any()
        }
        Json::Obj(members) => {
            let d = PyDict::new(py);
            for (k, v) in members {
                d.set_item(k, to_py(py, v)?)?;
            }
            d.into_any()
        }
    })
}

fn members(obj: &Bound<'_, PyAny>, what: &str) -> PyResult<Vec<(String, Json)>> {
    match to_json(obj)? {
        Json::Obj(m) => Ok(m),
        _ => Err(PyValueError::new_err(format!(
            "{what}: not a collection (a dict)"
        ))),
    }
}

/// The level-2 representation: every attribute refbook gives a collection
/// but the transient ones, as a dict in schema order.
#[pyfunction]
fn seqcol_level2<'py>(
    py: Python<'py>,
    names: Vec<String>,
    lengths: Vec<i64>,
    sequences: Vec<String>,
) -> PyResult<Bound<'py, PyAny>> {
    let l2 = py.detach(|| seqcol::level2(&names, &lengths, &sequences));
    to_py(py, &Json::Obj(l2))
}

/// The level-1 representation: the digest of every attribute, transient ones
/// included.
#[pyfunction]
fn seqcol_level1<'py>(
    py: Python<'py>,
    names: Vec<String>,
    lengths: Vec<i64>,
    sequences: Vec<String>,
) -> PyResult<Bound<'py, PyDict>> {
    let l1 = py.detach(|| seqcol::level1_attributes(&names, &lengths, &sequences));
    let d = PyDict::new(py);
    for (k, v) in l1 {
        d.set_item(k, v)?;
    }
    Ok(d)
}

/// The top-level digest of a collection given as a dict of attributes (level
/// 2, or level 1), or None without the inherent attributes.
#[pyfunction]
fn seqcol_top_level_digest(collection: &Bound<'_, PyAny>) -> PyResult<Option<String>> {
    Ok(seqcol::top_level_digest(&members(
        collection,
        "collection",
    )?))
}

/// seqcol's /comparison of two collections given as dicts of their level-2
/// attributes, as JSON text.
#[pyfunction]
fn seqcol_compare(py: Python<'_>, a: &Bound<'_, PyAny>, b: &Bound<'_, PyAny>) -> PyResult<String> {
    let (a, b) = (members(a, "a")?, members(b, "b")?);
    let c = py.detach(|| seqcol::compare(&a, &b));
    serde_json::to_string(&c).map_err(|e| PyValueError::new_err(e.to_string()))
}

/// The order-independent identifier of a named sequence set.
#[pyfunction]
fn named_set_digest(py: Python<'_>, names: Vec<String>, sequences: Vec<String>) -> String {
    py.detach(|| seqcol::named_set_digest(&names, &sequences))
}

/// A root's bases (root positions start..start + len) with nucleotide
/// operations applied: the spans (0-based half-open, root coordinates) set to
/// N, then, if to_n, every base other than A, C, G, T and N set to N.
#[pyfunction]
#[pyo3(signature = (bases, start, spans, to_n))]
fn apply_operations<'py>(
    py: Python<'py>,
    bases: &[u8],
    start: usize,
    spans: Vec<(usize, usize)>,
    to_n: bool,
) -> Bound<'py, PyBytes> {
    let out = py.detach(|| {
        let mut b = bases.to_vec();
        operations::apply(&mut b, start, &spans, to_n);
        b
    });
    PyBytes::new(py, &out)
}

create_exception!(
    _core,
    RecipeError,
    PyValueError,
    "A recipe that doesn't compile."
);

type MemberRow = (
    String,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);

/// The catalog tables the recipe compiler reads, built once and shared by
/// every recipe: members as (assembly, accession, role, ucsc_name,
/// sequence_name, refseq_accession) in report order; every root id; the roots
/// with IUPAC codes; mask layer -> the roots it has spans on; external roots
/// as (root_id, collection, group, name) in rank order; placements as
/// (root_id, parent_type).
#[pyclass(frozen)]
struct RecipeTables(recipe::Tables);

#[pymethods]
impl RecipeTables {
    #[new]
    fn new(
        members: Vec<MemberRow>,
        roots: Vec<String>,
        iupac: Vec<String>,
        layers: std::collections::HashMap<String, Vec<String>>,
        external: Vec<(String, String, String, Option<String>)>,
        placements: Vec<(String, String)>,
    ) -> Self {
        let mut parent_types =
            std::collections::HashMap::<String, std::collections::HashSet<String>>::new();
        for (root, parent) in placements {
            parent_types.entry(root).or_default().insert(parent);
        }
        RecipeTables(recipe::Tables {
            members: members
                .into_iter()
                .map(
                    |(assembly, accession, role, ucsc_name, sequence_name, refseq_accession)| {
                        recipe::Member {
                            assembly,
                            accession,
                            role,
                            ucsc_name,
                            sequence_name,
                            refseq_accession,
                        }
                    },
                )
                .collect(),
            roots: roots.into_iter().collect(),
            iupac: iupac.into_iter().collect(),
            layers: layers
                .into_iter()
                .map(|(k, v)| (k, v.into_iter().collect()))
                .collect(),
            external: external
                .into_iter()
                .map(|(root_id, collection, group, name)| recipe::External {
                    root_id,
                    collection,
                    group,
                    name,
                })
                .collect(),
            parent_types,
        })
    }
}

/// Compile a recipe (JSON text): its manifest rows (name, root_id, operations),
/// in canonical order. Raises RecipeError.
#[pyfunction]
fn compile_recipe(
    py: Python<'_>,
    recipe_json: &str,
    tables: &RecipeTables,
) -> PyResult<Vec<(String, String, Vec<String>)>> {
    py.detach(|| {
        let r = recipe::Recipe::from_json(recipe_json)?;
        recipe::compile(&r, &tables.0)
    })
    .map(|rows| {
        rows.into_iter()
            .map(|r| (r.name, r.root_id, r.operations))
            .collect()
    })
    .map_err(|e| RecipeError::new_err(e.to_string()))
}

/// The catalog tables identify reads, indexed once: the sequence store as
/// (sq, md5, length, root_id, operations), roots as (root_id, length),
/// aliases as (root_id, alias), manifests as (edition, name, sq).
#[pyclass(frozen)]
struct IdentifyTables(identify::IdentifyTables);

#[pymethods]
impl IdentifyTables {
    #[new]
    fn new(
        py: Python<'_>,
        stored: Vec<(String, String, u64, String, Vec<String>)>,
        roots: Vec<(String, u64)>,
        aliases: Vec<(String, String)>,
        manifests: Vec<(String, String, String)>,
    ) -> Self {
        let stored = stored
            .into_iter()
            .map(|(sq, md5, length, root_id, operations)| identify::Stored {
                sq,
                md5,
                length,
                root_id,
                operations,
            })
            .collect();
        IdentifyTables(
            py.detach(|| identify::IdentifyTables::new(stored, roots, aliases, manifests)),
        )
    }
}

/// (name, length, md5, sq), any of them None.
type EntryRow = (Option<String>, Option<u64>, Option<String>, Option<String>);

/// Identify each entry (name, length, md5, sq; any may be None), as JSON text:
/// a list of identities.
#[pyfunction]
fn identify_sequences(
    py: Python<'_>,
    entries: Vec<EntryRow>,
    tables: &IdentifyTables,
) -> PyResult<String> {
    let entries: Vec<identify::Entry> = entries
        .into_iter()
        .map(|(name, length, md5, sq)| identify::Entry {
            name,
            length,
            md5,
            sq,
        })
        .collect();
    let ids = py.detach(|| identify::identify(&entries, &tables.0));
    serde_json::to_string(&ids).map_err(|e| PyValueError::new_err(e.to_string()))
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(canonical_bases, m)?)?;
    m.add_function(wrap_pyfunction!(remove_whitespace, m)?)?;
    m.add_function(wrap_pyfunction!(digests, m)?)?;
    m.add_function(wrap_pyfunction!(sha512t24u, m)?)?;
    m.add_function(wrap_pyfunction!(scan, m)?)?;
    for f in [
        wrap_pyfunction!(canonical_json, m)?,
        wrap_pyfunction!(level1, m)?,
        wrap_pyfunction!(seqcol_digests, m)?,
        wrap_pyfunction!(seqcol_ancillary, m)?,
        wrap_pyfunction!(named_set_digest, m)?,
        wrap_pyfunction!(seqcol_level2, m)?,
        wrap_pyfunction!(seqcol_level1, m)?,
        wrap_pyfunction!(seqcol_top_level_digest, m)?,
        wrap_pyfunction!(seqcol_compare, m)?,
        wrap_pyfunction!(apply_operations, m)?,
        wrap_pyfunction!(compile_recipe, m)?,
        wrap_pyfunction!(identify_sequences, m)?,
    ] {
        m.add_function(f)?;
    }
    m.add("SEQCOL_SCHEMA", seqcol::SCHEMA)?;
    m.add("SEQCOL_TRANSIENT", seqcol::TRANSIENT.to_vec())?;
    m.add_class::<RecipeTables>()?;
    m.add_class::<IdentifyTables>()?;
    m.add("RecipeError", m.py().get_type::<RecipeError>())?;
    Ok(())
}
