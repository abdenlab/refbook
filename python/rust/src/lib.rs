//! refbook._core: Python bindings of refbook-core.

use pyo3::create_exception;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3::types::{PyBool, PyDict, PyInt, PyList, PyString, PyTuple};
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
        wrap_pyfunction!(apply_operations, m)?,
        wrap_pyfunction!(compile_recipe, m)?,
    ] {
        m.add_function(f)?;
    }
    m.add_class::<RecipeTables>()?;
    m.add("RecipeError", m.py().get_type::<RecipeError>())?;
    Ok(())
}
