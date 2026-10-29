#!/usr/bin/env bash
# Fetch the raw NCBI inputs for the GRCh38 roots into $REGISTRY/raw.
#
# Files land at raw/<host>/<url path>, so every file's source URL is its path.
# wget -N keeps the server's Last-Modified time as the file's mtime and skips
# files that haven't changed, so the script is safe to re-run.
#
# Usage: fetch_grch38.sh REGISTRY_DIR
set -euo pipefail

REGISTRY=${1:?usage: fetch_grch38.sh REGISTRY_DIR}
RAW="$REGISTRY/raw"
NCBI=https://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405
mkdir -p "$RAW"
cd "$RAW"

wget_mirror() {
    wget --no-verbose --timestamping --force-directories \
         --tries=5 --waitretry=10 --execute robots=off "$@"
}

# GRCh38 p0..p14 are GCA_000001405.15..29.
releases=()
for i in $(seq 0 14); do
    v=$((15 + i))
    if [ "$i" -eq 0 ]; then
        releases+=("GCA_000001405.${v}_GRCh38")
    else
        releases+=("GCA_000001405.${v}_GRCh38.p${i}")
    fi
done

# Per-release metadata: small text files, plus the assembly_structure tree
# (AGP, placements, alignments, join certificates). The tree also holds FASTA
# for every assembly unit, about 1 GB per release; skip it, since p14's
# genomic.fna.gz already has every sequence.
for asm in "${releases[@]}"; do
    base="$NCBI/$asm/$asm"
    for suffix in assembly_report.txt assembly_regions.txt assembly_stats.txt \
                  genomic_gaps.txt.gz fcs_report.txt; do
        wget_mirror "${base}_${suffix}" || echo "missing: ${base}_${suffix}" >&2
    done
    for f in md5checksums.txt uncompressed_checksums.txt assembly_status.txt README.txt; do
        wget_mirror "$NCBI/$asm/$f" || echo "missing: $NCBI/$asm/$f" >&2
    done
    wget_mirror --recursive --no-parent --level=inf \
        --reject 'index.html*,*.fna.gz,*.fa.gz' \
        "$NCBI/$asm/${asm}_assembly_structure/"
    echo "done: $asm" >&2
done

# Sequence: p14 holds 709 of the 711 GRCh38 sequences.
p14="GCA_000001405.29_GRCh38.p14"
wget_mirror "$NCBI/$p14/${p14}_genomic.fna.gz"

# The 2 fix patches that p14 replaced with new versions (KQ759759.1,
# KQ759762.1) appear in no p14 file, so fetch them individually from GenBank.
EUTILS=https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
mkdir -p eutils.ncbi.nlm.nih.gov/efetch
for acc in KQ759759.1 KQ759762.1; do
    out="eutils.ncbi.nlm.nih.gov/efetch/nuccore_${acc}.fasta"
    [ -s "$out" ] || curl -sSfL --retry 5 -o "$out" \
        "$EUTILS?db=nuccore&id=${acc}&rettype=fasta&retmode=text"
done
echo "fetch complete" >&2
