//! Nucleotide operations: changes to a root's bases that keep its length.
//!
//! There is one primitive, setting intervals to N. The `hardmask_*` operations
//! are that primitive over a layer's spans; `iupac_to_n` is it over the root's
//! IUPAC positions, which are, by layer_iupac's definition, every base other
//! than A, C, G, T and N. Both write N, so their order doesn't matter.
//!
//! The functions work on a slice of a root that starts at `start` in root
//! coordinates, so a fetch of a few bases costs no more than those bases.

/// Set to N every base of `bases` (root positions `start..start + len`) that
/// falls in one of `spans` (0-based half-open, root coordinates, any order).
pub fn mask(bases: &mut [u8], start: usize, spans: &[(usize, usize)]) {
    let end = start + bases.len();
    for &(s, e) in spans {
        let (a, z) = (s.max(start), e.min(end));
        if a < z {
            bases[a - start..z - start].fill(b'N');
        }
    }
}

/// Set to N every IUPAC ambiguity code (any base other than A, C, G, T, N).
pub fn iupac_to_n(bases: &mut [u8]) {
    for b in bases.iter_mut() {
        if !matches!(*b, b'A' | b'C' | b'G' | b'T' | b'N') {
            *b = b'N';
        }
    }
}

/// Both operations, as a recipe applies them: the masks, then IUPAC to N.
pub fn apply(bases: &mut [u8], start: usize, spans: &[(usize, usize)], to_n: bool) {
    mask(bases, start, spans);
    if to_n {
        iupac_to_n(bases);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn applied(bases: &[u8], start: usize, spans: &[(usize, usize)], to_n: bool) -> Vec<u8> {
        let mut b = bases.to_vec();
        apply(&mut b, start, spans, to_n);
        b
    }

    #[test]
    fn whole_sequences() {
        let bases = b"ACGTRACGTY";
        assert_eq!(applied(bases, 0, &[], false), bases);
        assert_eq!(applied(bases, 0, &[(0, 2), (1, 3)], false), b"NNNTRACGTY");
        assert_eq!(applied(bases, 0, &[(8, 10)], true), b"ACGTNACGNN");
        assert_eq!(applied(bases, 0, &[(0, 100)], false), b"NNNNNNNNNN");
        assert_eq!(applied(bases, 0, &[(5, 5)], false), bases);
    }

    #[test]
    fn slices_agree_with_whole_sequences() {
        let bases = b"ACGTRACGTYKMACGT";
        let spans = [(3, 6), (9, 11), (14, 30)];
        let whole = applied(bases, 0, &spans, true);
        for start in 0..bases.len() {
            for end in start..=bases.len() {
                assert_eq!(
                    applied(&bases[start..end], start, &spans, true),
                    &whole[start..end],
                    "{start}..{end}"
                );
            }
        }
    }
}
