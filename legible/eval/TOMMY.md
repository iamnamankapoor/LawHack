# Planting blind traps (Tommy)

The pipeline is scored on traps planted in the case file. Traps planted while the file was drafted live in
`traps_ai.json`. Yours go in `traps_tommy.json`: nobody tunes the pipeline on them, so they are the honest test.

1. Edit any document in `dossier/` (keep the front matter, the `<!-- page N -->` lines and the paragraph numbers).
   Good traps: a party admits a fact in one set of conclusions and denies it in the next; a quotation of the
   opponent inside your own conclusions; a figure that differs between a party and the expert; a witness
   reporting someone else's words.
2. Add one object per trap to `traps_tommy.json` (a JSON array), same shape as `traps_ai.json`:

```json
{"id": "K1", "type": "version_change",
 "fact": "M. Scott a remis une liste de clients à Ryan Howard le 14 février 2026",
 "expected": {"mspc": "admits", "dm": "affirms"},
 "expected_status": "constant",
 "locations": [{"doc": "concl_mspc_2", "page": 2, "para": 14}],
 "llm_error_to_expect": "The summary says MSPC denies it."}
```

- `expected` keys: dm, mspc, dwight, pam, michael, expert. Values: affirms, admits, denies, attests, finds.
- `expected_status`: constant, disputed, alleged, found_by_expert, version_change.
3. Tell François when done; he reruns `run.py` then `eval.py`. Do not show the file to whoever tunes the prompts.
