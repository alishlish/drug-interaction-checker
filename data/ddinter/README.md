# DDInter 2.0 data (not committed)

DDInter is an open-access drug–drug interaction database, used here as an
**external validation gold standard** for the tool's interaction calls. The raw
CSVs are gitignored (not ours to redistribute); only derived validation results
are committed.

## How to obtain it

Download the 8 category CSVs from <https://ddinter.scbdd.com/download/> into
this folder (or reproduce with):

```bash
base="https://ddinter.scbdd.com/static/media/download"
for c in A B D H L P R V; do
  curl -sL -o "data/ddinter/ddinter_downloads_code_${c}.csv" \
    "$base/ddinter_downloads_code_${c}.csv"
done
```

## Format

Each file: `DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level`
(`Level` = Major | Moderate | Minor | Unknown). ~222k interaction records total.

## Used by

`scripts/validate_ddinter.py` — joins DDInter to this project's dataset on the
RxNorm-canonical drug name and cross-checks the tool's `/check` interaction
verdicts, reporting agreement/coverage for `EVALUATION.md`.

## Citation

Tian Z, et al. *DDInter 2.0: an enhanced drug interaction resource…* Nucleic
Acids Res. 2024. <https://ddinter2.scbdd.com>
