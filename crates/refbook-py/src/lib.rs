//! refbook._core: Python bindings of refbook-core.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use refbook_core::refget;

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

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(canonical_bases, m)?)?;
    m.add_function(wrap_pyfunction!(remove_whitespace, m)?)?;
    m.add_function(wrap_pyfunction!(digests, m)?)?;
    m.add_function(wrap_pyfunction!(sha512t24u, m)?)?;
    m.add_function(wrap_pyfunction!(scan, m)?)?;
    Ok(())
}
