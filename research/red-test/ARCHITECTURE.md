# Architecture: who-said-what for Cour de cassation decisions

## Problem (from the red test, see EVIDENCE.html)

LLMs credit the Cour de cassation with reasoning it only quotes (cour d'appel) or answers (a party's moyen). Three failure modes:
1. **Direct misattribution**: "Il retient…" (= l'arrêt attaqué) read as the Court.
2. **Laundering** (most common): right speaker, but "not censured" turned into "approved" and restated as a rule.
3. **Excerpt inversion**: a chunk of recited lower-court reasoning presented as the Court's rule.

## Principle

The LLM never decides attribution. Narrow, typed classifiers (Jev) decide **who speaks** and **what the Court did with it** per segment. The LLM receives that as structure and only writes the answer. A final typed check (Jev) rejects answers that still misattribute.

## Pipeline

```
pourvoi n° ──► fetch ──► segment ──► who (Jev) ──► stance (Jev) ──► annotated decision ──► answer (any LLM) ──► guard (Jev)
```

| Step | Module | Kind | Output |
|---|---|---|---|
| 1. Fetch | `engine/fetch.py` | API | Text (+ Judilibre zones when available). Source: Judilibre API (PISTE); fallback to `cases/raw/` by pourvoi n°. |
| 2. Segment | `engine/segment.py` | rules | Ordered segments: numbered paragraphs (post-2019) or "Attendu" units (pre-2019); section of each (exposé, énoncé du moyen, réponse, dispositif, annexe); ground ("Sur le premier moyen…"). |
| 3. Who | `engine/tag.py` | Jev `choice` | `court` / `cour_appel` / `partie` / `faits`, with probability. State = preceding context + target, so "Il retient" resolves. Low confidence → gateway evaluation fallback to an LLM. |
| 4. Stance | `engine/tag.py` | Jev `choice` + `noul` + rules | Two atomic questions: per ground, outcome (`cassation` / `rejet` / `non_examine`); per non-Court segment, "does the Court's own reasoning address this passage?". Combined into `quashed` / `approved` / `approved_restated_only` / `not_ruled` / `argument_rejected` / `argument_accepted` / `no_court_answer_in_text`. Drafting-convention rules override: "En statuant ainsi" (censures the passage just before), "sans qu'il y ait lieu de statuer sur…" (not ruled), "par ce seul motif" (only the restated motif approved). |
| 5. Annotate | `engine/render.py` | code | XML-tagged decision (`<seg speaker=… stance=…>`) + a short "what the Court actually held" sheet built only from `court` segments and the dispositif. |
| 6. Answer | `engine/answer.py` | LLM | Any gateway model, with a fixed instruction: only `court` segments may be attributed to the Cour de cassation; `not_ruled` must be reported as such. |
| 7. Guard | `engine/answer.py` | Jev `noul` ×3 | Misattribution in the full answer, laundering ("ne remet pas en cause", restated as a rule), misattribution in the opening two sentences. Max ≥ 0.5 → one regeneration with the rejected answer quoted back. |

## Evaluation (red → green)

`eval/run_green.py`: for each model × question, run **baseline** (raw decision) and **pipeline** through the same gateway, grade both with `runs/cli/judge.py`.
- Models: Haiku 4.5, Sonnet 4.6, Opus 4.6 (all fail C2-Q1 3/3 at baseline).
- Questions: C2-Q1 ×3 (red test), C2-CHUNK, C4-Q3; regression: C2-Q3, C3-Q1, C4-Q1/Q2.
- Green = every model passes C2-Q1 3/3, no regressions. **Reached 2026-10-04: 27/27 vs 10/27 baseline** (see runs/RESULTS.md). Next: 20 unseen Judilibre decisions.

## Not in scope yet

Conseil d'État, UI, multi-decision research. Gold labels still need a French lawyer's confirmation.
