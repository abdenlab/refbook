//! Nucleotide operations: changes to a root's bases.
//!
//! Two keep the root's length and coordinates. Each sets intervals to N: the
//! `hardmask_*` operations over a layer's spans, `iupac_to_n` over the root's
//! IUPAC positions (by layer_iupac's definition, every base other than A, C,
//! G, T and N). Both write N, so their order doesn't matter.
//!
//! The third, `pad`, puts a placed scaffold (an alt or a patch) in its
//! parent's coordinates, as Ensembl's GRCh37 files do: N for the parent's
//! bases before the placed region, the whole scaffold (reverse-complemented
//! if it is placed on the minus strand), then N for the parent's bases after
//! the region. It comes last: the masks apply to the root, in its own
//! coordinates, before it is padded.
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

/// Both length-keeping operations, as a recipe applies them: the masks, then
/// IUPAC to N.
pub fn apply(bases: &mut [u8], start: usize, spans: &[(usize, usize)], to_n: bool) {
    mask(bases, start, spans);
    if to_n {
        iupac_to_n(bases);
    }
}

/// A base's complement, IUPAC codes included (R and Y, K and M, B and V, D
/// and H swap; S, W and N are their own), keeping case.
pub fn complement(b: u8) -> u8 {
    let c = match b.to_ascii_uppercase() {
        b'A' => b'T',
        b'T' => b'A',
        b'C' => b'G',
        b'G' => b'C',
        b'R' => b'Y',
        b'Y' => b'R',
        b'K' => b'M',
        b'M' => b'K',
        b'B' => b'V',
        b'V' => b'B',
        b'D' => b'H',
        b'H' => b'D',
        other => other,
    };
    if b.is_ascii_lowercase() {
        c.to_ascii_lowercase()
    } else {
        c
    }
}

/// Reverse-complement bases in place.
pub fn reverse_complement(bases: &mut [u8]) {
    bases.reverse();
    for b in bases.iter_mut() {
        *b = complement(*b);
    }
}

/// How `pad` places a root of `root_length` bases: `before` Ns, the root
/// (reverse-complemented if `reverse`), then `after` Ns.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Padding {
    pub before: usize,
    pub root_length: usize,
    pub after: usize,
    pub reverse: bool,
}

impl Padding {
    /// From a placement: the placed region `parent_start..parent_end`
    /// (0-based half-open) on a parent of `parent_length` bases, and the
    /// orientation (`-` reverses; `+` and `b`, both, don't).
    pub fn of_placement(
        root_length: usize,
        parent_start: usize,
        parent_end: usize,
        parent_length: usize,
        orientation: &str,
    ) -> Padding {
        Padding {
            before: parent_start,
            root_length,
            after: parent_length.saturating_sub(parent_end),
            reverse: orientation == "-",
        }
    }

    /// The padded sequence's length.
    pub fn length(&self) -> usize {
        self.before + self.root_length + self.after
    }

    /// The root bases (0-based half-open, root coordinates) that bases
    /// `start..end` of the padded sequence show.
    pub fn root_range(&self, start: usize, end: usize) -> (usize, usize) {
        let clip = |x: usize| x.saturating_sub(self.before).min(self.root_length);
        let (s, e) = (clip(start), clip(end.max(start)));
        if self.reverse {
            (self.root_length - e, self.root_length - s)
        } else {
            (s, e)
        }
    }

    /// Bases `start..end` of the padded sequence, from `root`: the root's
    /// bases at `root_range(start, end)`, with the other operations applied.
    pub fn pad(&self, root: &[u8], start: usize, end: usize) -> Vec<u8> {
        let end = end.max(start);
        let (a, z) = self.root_range(start, end);
        assert_eq!(
            root.len(),
            z - a,
            "pad: the root slice must cover root_range"
        );
        let mut out = Vec::with_capacity(end - start);
        let first = self.before.clamp(start, end);
        out.resize(first - start, b'N');
        let mut middle = root.to_vec();
        if self.reverse {
            reverse_complement(&mut middle);
        }
        out.extend_from_slice(&middle);
        out.resize(end - start, b'N');
        out
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

    #[test]
    fn complements() {
        let mut b = b"ACGTRYKMSWBDHVNacgtn".to_vec();
        reverse_complement(&mut b);
        assert_eq!(b, b"nacgtNBDHVWSKMRYACGT");
    }

    #[test]
    fn padding() {
        // A 4-base scaffold placed at 3..6 on a 10-base parent.
        let p = Padding::of_placement(4, 3, 6, 10, "+");
        assert_eq!(p.length(), 3 + 4 + 4);
        assert_eq!(p.pad(b"ACGG", 0, 11), b"NNNACGGNNNN");
        let m = Padding::of_placement(4, 3, 6, 10, "-");
        assert_eq!(m.pad(b"ACGG", 0, 11), b"NNNCCGTNNNN");
        assert_eq!(Padding::of_placement(4, 3, 6, 10, "b"), p);
    }

    #[test]
    fn padded_slices_agree_with_whole_sequences() {
        let root = b"ACGTRACGTYKMACGA";
        for orientation in ["+", "-"] {
            let p = Padding::of_placement(root.len(), 5, 19, 26, orientation);
            let whole = p.pad(root, 0, p.length());
            assert_eq!(whole.len(), p.length());
            for start in 0..=p.length() {
                for end in start..=p.length() {
                    let (a, z) = p.root_range(start, end);
                    assert_eq!(
                        p.pad(&root[a..z], start, end),
                        &whole[start..end],
                        "{orientation} {start}..{end}"
                    );
                }
            }
        }
    }
}
