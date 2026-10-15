# word_count_v1 Unicode profile

The canonical `backend/app/word-count-profile.json` freezes Letter, Number and Mark
categories to Unicode 15.1.0. Both Python and TypeScript import this same artifact.
Native NFC normalization and existing connector rules are unchanged; raw answers
are never normalized or rewritten. Legacy written answers and casefold are unchanged.

Generated without network or data volumes by CPython 3.13 in the production-runtime
QA image `learning-qa-after:20261014` (image ID `sha256:204f0d30febef6b6701df69f3666438d98492e1817d653edf34b41d8a64bd3d3`). Reproduce:

```sh
docker run --rm -i --network none --entrypoint python sha256:204f0d30febef6b6701df69f3666438d98492e1817d653edf34b41d8a64bd3d3 < scripts/generate_word_count_profile.py > backend/app/word-count-profile.json
```

The generator refuses a different Unicode database. Inclusive ranges are sorted
and nonoverlapping. No duplicated handwritten table is maintained.

SHA-256: `c353dc252eeae73f2e7105258035767ad3e05a1eacf673370d110d8116b7e943`
