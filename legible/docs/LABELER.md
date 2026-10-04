# Plugging in the team's voice-recognition model

Everything except the voice labelling is built: segmentation, fact list, status rules, the guard, the UI and
the evaluation. The default labeller is Jev. To use your model instead, serve one HTTP endpoint and run:

```
LABELER_URL=http://localhost:9000/label .venv/Scripts/python run.py
```

## Request (POST, JSON, up to 50 items)
```json
{"items": [{
  "sid": "concl_mspc_2.p2.§9.s1",
  "fact": "F07",
  "fact_statement": "Michael Scott a informé des clients de son départ avant le 13 février 2026",
  "sentence": "M. Scott conteste formellement avoir pris contact avec quelque client que ce soit…",
  "page_text": "…the whole page, for context…",
  "doc_type": "conclusions", "doc_date": "2026-09-09",
  "writer": "mspc",
  "speakers": {"dm": "Dunder Mifflin France SAS (demanderesse)", "mspc": "…", "expert": "…"}
}]}
```

## Response
```json
{"labels": [{
  "position": "denies",
  "position_conf": 0.93,
  "reported_speaker": "none",
  "reported_conf": 0.88,
  "reported_position": "none",
  "reported_position_conf": 0.9
}]}
```
One label per item, same order.

- `position`: what the writer of the document says about the fact in this sentence: `affirms`, `admits`
  (concedes it, e.g. « il n'est pas contesté que »), `denies`, `reports_only` (only reports someone else's
  version), `no_position`.
- `reported_speaker`: whose version the sentence reports besides the writer (a key of `speakers`), or `none`.
- `reported_position`: in that reported version, is the fact `true`, `false`, or `none`.
- Confidences are 0–1. Below 0.6 the UI shows the fact as « à vérifier ».

Ground truth to measure your model against: `eval/traps_ai.json` and `eval/traps_tommy.json`; run `eval.py`.
