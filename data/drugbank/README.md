# DrugBank data (not committed)

DrugBank is used **only as a local validation gold-standard** — it is never a
committed data source and never shipped in the app. Its license (CC BY-NC 4.0)
forbids redistribution, so the data files here are gitignored.

## How to obtain it

1. Create an academic account: <https://go.drugbank.com/public_users/sign_up>
2. Once approved, download the **full database (XML)** from
   <https://go.drugbank.com/releases/latest> and accept the academic license.
3. Place the unzipped file here as:

   ```
   data/drugbank/full_database.xml
   ```

## What it's used for

`scripts/validate_drugbank.py` (added once the file is present) parses the
drug–drug interactions from DrugBank, maps this project's dataset drugs to
DrugBank via RxNorm/name matching, and cross-checks the tool's `/check`
interaction calls — reporting agreement and coverage as an external validation
number for `EVALUATION.md`.

## Citation

Wishart DS, et al. *DrugBank 5.0: a major update to the DrugBank database.*
Nucleic Acids Res. 2018. Cite DrugBank in any writeup that uses this data.
