Data of the seqcol compliance suite in the `refget` Python package
(refgenie/refget), copied unchanged under its BSD-2-Clause license
(`LICENSE.txt`):

- `test_fasta_digests.json`: expected digests (`test_fasta/`), version 0.12.0;
  identical at commit 63d99040 (2026-09-25).
- `collection/*.fa.json`: the level-2 collections of the test FASTAs, and
  `comparison/compare_*.fa_*.fa.json`: the expected `/comparison` of each
  pair (`tests/api/`), at commit 63d99040.

Used by the Python, Rust (refbook-core) and JS tests.
