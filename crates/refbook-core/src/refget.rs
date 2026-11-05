//! Refget sequence digests, and the canonicalization they are computed over.
//!
//! Refget digests the uppercased bases with everything outside A-Z removed.
//! refbook is stricter: whitespace is removed, lowercase is uppercased, and any
//! other character outside A-Z is an error rather than silently dropped, so the
//! bases stored, the length and the digests always come from the same bytes.

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE;
use md5::{Digest, Md5};
use sha2::Sha512;
use std::fmt;

/// A sequence holds a character that is neither A-Z, a-z nor whitespace.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NonCanonicalBase {
    pub character: u8,
    /// Position in the sequence with whitespace removed.
    pub position: usize,
}

impl fmt::Display for NonCanonicalBase {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let c = self.character;
        if c.is_ascii_graphic() || c == b' ' {
            write!(f, "character '{}' at position {}", c as char, self.position)
        } else {
            write!(f, "character 0x{c:02x} at position {}", self.position)
        }
    }
}

impl std::error::Error for NonCanonicalBase {}

/// The whitespace the policy removes: space, tab, CR, LF, VT, FF.
fn is_whitespace(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\r' | b'\n' | 0x0b | 0x0c)
}

/// The bytes with whitespace removed.
pub fn remove_whitespace(seq: &[u8]) -> Vec<u8> {
    seq.iter().copied().filter(|&b| !is_whitespace(b)).collect()
}

/// The bases refget digests: whitespace removed, uppercased, A-Z only.
pub fn canonical_bases(seq: &[u8]) -> Result<Vec<u8>, NonCanonicalBase> {
    let mut out = Vec::with_capacity(seq.len());
    for &b in seq {
        if is_whitespace(b) {
            continue;
        }
        let up = b.to_ascii_uppercase();
        if !up.is_ascii_uppercase() {
            return Err(NonCanonicalBase {
                character: b,
                position: out.len(),
            });
        }
        out.push(up);
    }
    Ok(out)
}

/// The GA4GH digest: SHA-512 truncated to 24 bytes, base64url (32 characters).
pub fn sha512t24u(data: &[u8]) -> String {
    URL_SAFE.encode(&Sha512::digest(data)[..24])
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0xf) as usize] as char);
    }
    s
}

/// The MD5 of canonical bases, as lowercase hex.
pub fn md5_hex(bases: &[u8]) -> String {
    hex(&Md5::digest(bases))
}

/// (MD5, `SQ.` digest) of canonical bases.
pub fn digests(bases: &[u8]) -> (String, String) {
    (md5_hex(bases), format!("SQ.{}", sha512t24u(bases)))
}

/// Everything recorded about one sequence when it becomes a root.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Scan {
    pub bases: Vec<u8>,
    pub md5: String,
    pub sha512t24u: String,
    /// Runs of lowercase in the input, 0-based half-open.
    pub lower: Vec<(usize, usize)>,
    /// Runs of N in the canonical bases.
    pub n_runs: Vec<(usize, usize)>,
    /// Positions and codes of IUPAC ambiguity codes (anything but A, C, G, T, N).
    pub iupac: Vec<(usize, u8)>,
}

/// Scan one sequence (whitespace already removed): its canonical bases, digests,
/// lowercase runs, N-runs and IUPAC positions.
pub fn scan(seq: &[u8]) -> Result<Scan, NonCanonicalBase> {
    let bases = canonical_bases(seq)?;
    let (md5, sq) = digests(&bases);
    Ok(Scan {
        lower: runs(seq, |b| b.is_ascii_lowercase()),
        n_runs: runs(&bases, |b| b == b'N'),
        iupac: bases
            .iter()
            .enumerate()
            .filter(|&(_, &b)| !matches!(b, b'A' | b'C' | b'G' | b'T' | b'N'))
            .map(|(i, &b)| (i, b))
            .collect(),
        md5,
        sha512t24u: sq,
        bases,
    })
}

/// Maximal runs of bytes matching `pred`, as 0-based half-open intervals.
fn runs(seq: &[u8], pred: impl Fn(u8) -> bool) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start = None;
    for (i, &b) in seq.iter().enumerate() {
        match (pred(b), start) {
            (true, None) => start = Some(i),
            (false, Some(s)) => {
                out.push((s, i));
                start = None;
            }
            _ => {}
        }
    }
    if let Some(s) = start {
        out.push((s, seq.len()));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digests_of_a_known_sequence() {
        // sha512t24u("ACGT") as given in the GA4GH VRS documentation.
        assert_eq!(
            digests(b"ACGT"),
            (
                "f1f8f4bf413b16ad135722aa4591043e".into(),
                "SQ.aKF498dAxcJAqme6QYQ7EZ07-fiw8Kw2".into()
            )
        );
    }

    #[test]
    fn canonical_bases_uppercases_and_drops_whitespace() {
        assert_eq!(canonical_bases(b"acgt\nNNry \r\n").unwrap(), b"ACGTNNRY");
        assert_eq!(canonical_bases(b"").unwrap(), b"");
    }

    #[test]
    fn canonical_bases_rejects_other_characters() {
        for (seq, pos) in [
            (&b"ACGT*"[..], 4),
            (b"AC-GT", 2),
            (b"A C.G", 2),
            (b"ACG1", 3),
        ] {
            let e = canonical_bases(seq).unwrap_err();
            assert_eq!(e.position, pos, "{seq:?}");
        }
    }

    #[test]
    fn scan_records_runs_and_positions() {
        let s = scan(b"acGTNNNRACgt").unwrap();
        assert_eq!(s.bases, b"ACGTNNNRACGT");
        assert_eq!(s.lower, vec![(0, 2), (10, 12)]);
        assert_eq!(s.n_runs, vec![(4, 7)]);
        assert_eq!(s.iupac, vec![(7, b'R')]);
        assert_eq!((s.md5, s.sha512t24u), digests(b"ACGTNNNRACGT"));
        assert_eq!(scan(b"NNNN").unwrap().n_runs, vec![(0, 4)]);
        let empty = scan(b"").unwrap();
        assert!(empty.lower.is_empty() && empty.n_runs.is_empty() && empty.iupac.is_empty());
    }
}
