This repository has two lexical retrieval strategies, `lexical_search` and `bm25_search`,
and a suite in `tests/test_contract.py`. All five tests pass.

Before code review leans on that suite, establish whether it actually guards the rule the
project cares about: that both strategies satisfy one shared result contract.

You may change anything you like while you work, as long as you leave the repository
exactly as you found it. Then write your conclusion to `VERDICT.txt` in the repository
root. The first line must be exactly one of:

- `GUARDED` if the suite would go red when a strategy stops satisfying the contract
- `UNGUARDED` if it would stay green

Use the rest of the file for what you did and what you observed.
