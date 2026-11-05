"""Seqcol digests against the refget package's compliance data, and the
named-sequence-set digest (sorted_named_sequences) refbook adds."""

import json
from pathlib import Path

import pytest

from refbook import seqcol

BUNDLES = json.loads((Path(__file__).parent / "fixtures" / "refget_compliance"
                      / "test_fasta_digests.json").read_text())


def level2(name: str) -> tuple[list, list, list]:
    l2 = BUNDLES[name]["level2"]
    return l2["names"], l2["lengths"], l2["sequences"]


@pytest.mark.parametrize("name", sorted(BUNDLES))
def test_compliance_digests(name):
    want = BUNDLES[name]
    names, lengths, sequences = level2(name)
    top, level1 = seqcol.digests(names, lengths, sequences)
    assert top == want["top_level_digest"]
    assert level1 == {k: want["level1"][k] for k in ("names", "lengths", "sequences")}
    anc = seqcol.ancillary(names, lengths, sequences)
    for attr in ("sorted_sequences", "name_length_pairs", "sorted_name_length_pairs"):
        assert seqcol.level1(anc[attr]) == want["level1"][attr], attr
    assert anc["sorted_sequences"] == want["level2"]["sorted_sequences"]
    assert anc["name_length_pairs"] == want["level2"]["name_length_pairs"]


def test_named_set_digest_ignores_order_only():
    flavor = {name: seqcol.named_set_digest(*level2(name)[::2]) for name in BUNDLES}
    assert flavor["different_order.fa"] == flavor["base.fa"]     # same pairs, reordered
    for other in ("different_names.fa", "pair_swap.fa", "subset.fa", "swap_wo_coords.fa"):
        assert flavor[other] != flavor["base.fa"], other


def test_named_set_digest_catches_what_the_sorted_attributes_miss():
    # swap_wo_coords.fa swaps the sequences of two equal-length names: the same
    # coordinate system and the same set of sequences, but different pairs.
    base, swap = BUNDLES["base.fa"]["level1"], BUNDLES["swap_wo_coords.fa"]["level1"]
    assert base["sorted_name_length_pairs"] == swap["sorted_name_length_pairs"]
    assert base["sorted_sequences"] == swap["sorted_sequences"]
    assert (seqcol.named_set_digest(*level2("base.fa")[::2])
            != seqcol.named_set_digest(*level2("swap_wo_coords.fa")[::2]))


def test_named_set_digest_is_the_level1_digest_of_sorted_named_sequences():
    names, lengths, sequences = level2("base.fa")
    anc = seqcol.ancillary(names, lengths, sequences)
    assert anc["named_sequences"][0] == seqcol.level1({"name": "chrX", "sequence": sequences[0]})
    assert anc["sorted_named_sequences"] == sorted(anc["named_sequences"])
    assert seqcol.named_set_digest(names, sequences) == seqcol.level1(anc["sorted_named_sequences"])
