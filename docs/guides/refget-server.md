# A refget server

`refbook serve` implements every endpoint of the [GA4GH refget APIs](https://ga4gh.github.io/refget/), Sequences v2 and Sequence Collections v1, from the catalog:

```
$ refbook serve --port 8000
$ curl 'localhost:8000/sequence/insdc:CM000663.2?start=10000&end=10060'
$ curl localhost:8000/collection/Cs-_YD8aP4e7Gz5GsfmxKt88hyJ00ZBL
```

The API is described at `/openapi.json`. In Python, the service is
`refbook.service`.

## Sequences

A sequence can be named by its MD5, its `SQ.` digest, or a namespaced alias
(`insdc:CM000663.2`). An alias that names several sequences, such as
`ucsc:chr1` (the root and its IUPAC → N derivative), answers 300 with the list.

The namespaces are refget's recommended `insdc`, `refseq`, `ensembl` and
`ucsc`, plus `imgt.hla` and refbook's `grc` (the GRC Sequence-Name, e.g.
`grc:HSCHR1_CTG1_UNLOCALIZED`). Of these, `insdc`, `refseq`, `ensembl` and
`imgt.hla` are identifiers.org prefixes.

A sequence's metadata adds refbook's account of it under `refbook`: its root,
the operations that made it, and the editions that use it.

## Collections

Collections are served with refbook's seqcol schema: the spec's extended
schema plus `named_sequences` and `sorted_named_sequences` (see the
[glossary](../concepts/glossary.md#digests-and-identifiers)). Every edition and published file is a collection, under its seqcol digest.

## Compliance

- **Sequence Collections:** against the compliance suite in the `refget`
  package, it passes 52 of 65 checks. The rest are `named_sequences`
  appearing in comparisons (the suite expects exactly its own attributes) and
  `/list/attributes`, which is not in the spec.
- **Sequences:** against the refget Sequences compliance suite
  (ga4gh/refget-compliance-suite 2.0.0, from GitHub), on its test sequences, every check passes except range edge cases where the suite departs from the spec. It expects a Range past the end to be truncated (the spec says 400), a start or Range beyond the end to be 416 (the spec says 400), and a `start` equal to the length to be 416 (the spec allows it). The circular and TRUNC512 checks are skipped: neither is supported.

To run a suite, `--collections` and `--sequences` add its test data to what
the server holds.
