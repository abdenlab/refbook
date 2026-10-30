#!/usr/bin/env bash
# Fetch published GRCh38 flavor files (the recipe targets) into $REGISTRY/raw.
#
# Same conventions as fetch_grch38.sh: files land at raw/<host>/<url path>,
# wget -N keeps the server's Last-Modified time and skips unchanged files.
# Each source's own checksum list is fetched too; check against it after.
#
# Usage: fetch_flavors.sh REGISTRY_DIR
set -euo pipefail

REGISTRY=${1:?usage: fetch_flavors.sh REGISTRY_DIR}
mkdir -p "$REGISTRY/raw"
cd "$REGISTRY/raw"

wget_mirror() {
    wget --no-verbose --timestamping --force-directories \
         --tries=5 --waitretry=10 --execute robots=off "$@"
}

# UCSC hg38: the top-level bigZips files are the initial release (455 seqs);
# p14/ is GRCh38.p14 (711, incl. 2 superseded fix patches); analysisSet/ is
# UCSC's copy of the GRC no_alt analysis set.
UCSC=https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips
for f in hg38.fa.gz hg38.chrom.sizes md5sum.txt \
         p14/hg38.p14.fa.gz p14/hg38.p14.chrom.sizes p14/hg38.p14.chromAlias.txt p14/md5sum.txt \
         analysisSet/hg38.analysisSet.fa.gz analysisSet/md5sum.txt; do
    wget_mirror "$UCSC/$f"
done
wget_mirror https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/analysisSet/README.txt \
    || echo "missing: analysisSet/README.txt" >&2

# Ensembl 116 (pinned release): unmasked primary_assembly and toplevel.
ENSEMBL=https://ftp.ensembl.org/pub/release-116/fasta/homo_sapiens/dna
for f in Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz Homo_sapiens.GRCh38.dna.toplevel.fa.gz \
         CHECKSUMS README; do
    wget_mirror "$ENSEMBL/$f"
done

# GENCODE v50 (pinned release): primary assembly and the full p14 genome.
GENCODE=https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_50
for f in GRCh38.primary_assembly.genome.fa.gz GRCh38.p14.genome.fa.gz MD5SUMS _README.TXT; do
    wget_mirror "$GENCODE/$f"
done
# Broad/GATK and 1000 Genomes (bwakit hs38DH: full_plus_hs38d1 + HLA):
# metadata only for now (.dict carries M5 per sequence).
BROAD=https://storage.googleapis.com/gcp-public-data--broad-references/hg38/v0
for f in Homo_sapiens_assembly38.dict Homo_sapiens_assembly38.fasta.fai; do
    wget_mirror "$BROAD/$f"
done
G1K=https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/technical/reference/GRCh38_reference_genome
for f in README.20150309.GRCh38_full_analysis_set_plus_decoy_hla \
         GRCh38_full_analysis_set_plus_decoy_hla.dict \
         GRCh38_full_analysis_set_plus_decoy_hla.fa.fai \
         GRCh38_full_analysis_set_plus_decoy_hla.fa.alt \
         GRCh38_full_analysis_set_plus_decoy_hla-extra.fa; do
    wget_mirror "$G1K/$f"
done
echo "fetch complete" >&2
