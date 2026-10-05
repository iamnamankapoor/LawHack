# Red-test results: Legora (in-app browser, private chats), 2026-10-04

Method: one new private chat per run. Prompt = "Voici une décision de la Cour de cassation :" + full Légifrance text + "Question : …" (exact text in `runs/prompts/`). When Legora asked "Deep research or quick answer?" → always **Quick answer**. Per-run transcripts in `runs/legora/`.

## Matrix

| Question | Trap | Agent (default) | Opus 5.5 | GPT 6 Astra |
|---|---|---|---|---|
| **C2-Q1** (§8 cour d'appel under "Réponse de la Cour") | lower-court reasoning | **FAIL ×3 / 3** | PASS | PASS |
| C2-Q2 (§7 "pas un critère légal") | lower-court reasoning | FAIL (soft) | – | – |
| C2-Q3 (moyen "offres précises…") | appellant's ground | PASS | – | – |
| **C2-CHUNK** (§5–9 only, RAG simulation) | lower-court reasoning, no context | **FAIL (severe)** | PASS* | – |
| C3-Q1 (annexed ground, NSM rejection) | appellant's ground | PASS | – | – |
| C3-Q2 (summarise solution) | appellant's ground | PASS | – | – |
| C1-Q2 (which ground → cassation) | structure | PASS | – | – |
| C4-Q1 (tacit agreement censured?) | outcome per ground | PASS (minor slip) | – | – |
| C4-Q2 (Fillon annulment upheld?) | outcome per ground | PASS | – | – |
| **C4-Q3** (URSSAF branch 4°) | appellant's ground | **FAIL** | PASS | PASS |

\* Opus 5.5 passed C2-CHUNK only because Legora's legal-source search found the full decision; the default Agent's search returned an unrelated 2022 case and it failed.

C1-Q1 skipped: the copied Légifrance page includes the official "Titrages et résumés", which states the rule outright.

## Locked red test

**C2-Q1 on Legora default Agent — 3/3 failures.**
Cass. soc., 11 sept. 2026, n° 24-21.242. Question: "Selon la Cour de cassation, le seul fait que le poste de reclassement proposé soit dépourvu de responsabilité managériale suffit-il à considérer que la proposition n'est pas loyale et sérieuse ?"
- Correct: the Court does not rule on this; it is the cour d'appel's §8 ("Il retient, enfin…"), and the Court quashed that decision on another ground (§10).
- Legora Agent: "Non. Selon la Cour de cassation, … ne suffit pas" / "approuvée sur ce point par la décision" / "Selon l'arrêt, … ne suffisait pas".

Backup red tests: C2-CHUNK (severe, realistic RAG failure) and C4-Q3 (pre-2019 style) — 1 run each so far.

## What this tells us

1. The failure is real and reproducible in a top legal AI product's default mode, on a 2026 decision, with the full text supplied.
2. It is model-dependent: Opus 5.5 and GPT 6 Astra (selectable custom models) get it right. Our pitch is therefore strongest as (a) making the default/cheaper model reliable, and (b) making retrieval-chunk answers safe (C2-CHUNK), where even the strong model only passed thanks to a lucky retrieval.
3. The signature error is a "headline + caveat" pattern: the first sentence attributes the lower court's reasoning to the Court, a later paragraph half-corrects it. A lawyer skimming the answer takes away the wrong rule.
4. Even passing answers often call §4–10 "la Réponse de la Cour" — heading-based segmentation is what the models lean on, and it is wrong for this decision. Sentence-level attribution ("l'arrêt relève… Il retient… Il en déduit" = cour d'appel) is the fix.


## Update — older/weaker models on the locked red test (C2-Q1), 2026-10-04

### Legora, all selectable models, C2-Q1 (full decision pasted)

| Model (Legora) | Result |
|---|---|
| Agent (default) | **FAIL ×3 / 3** |
| GPT 5.5 | FAIL (soft: correct attribution in body, misattributed rule in "En bref") |
| GPT 5.6 Sol | **FAIL** (flat rule, never mentions cour d'appel) |
| GPT 6 Astra | PASS |
| Opus 4.7 | **FAIL** ("la Cour de cassation ne censure pas ce point" + rule) |
| Opus 4.8 | **FAIL** ("ne remet pas en cause le raisonnement" + rule) |
| Opus 5 | PASS (expert-level) |
| Opus 5.5 | PASS |

**5 of 8 Legora configurations fail C2-Q1 (soft fails counted as fails); Opus 5, Opus 5.5 and GPT 6 Astra pass.** _(Corrected on 2026-10-05: this line first said 6 of 8, which does not match the table above.)_

### Isolated Claude subagents (see `isolated/RESULTS_isolated_subagents.md`)

| Prompt | Haiku | Sonnet |
|---|---|---|
| C2-Q1 | **FAIL ×3 / 3** | PASS, FAIL (soft), PASS |
| C2-CHUNK | **FAIL (severe)** | PASS (with caveat) |
| C4-Q3 | **FAIL (severe)** | soft fail (headline) |

### Failure taxonomy observed across all runs
1. **Direct misattribution** — quotes §8 "Il retient…" as "La Cour énonce explicitement" (Haiku ×3, Legora Agent run 1).
2. **Laundering** — correctly names the cour d'appel, then says the Court "ne remet pas en cause / ne censure pas / approuve" it and restates it as a rule (Legora Agent run 2, Opus 4.7, Opus 4.8, GPT 5.5, Sonnet run 2).
3. **Silent rule** — states the lower-court reasoning as the answer without naming any speaker (GPT 5.6 Sol).
4. **Chunk inversion** — given only recited lower-court reasoning, presents it as the Court's rule (Legora Agent, Haiku).

The correct reading (only Opus 5 / 5.5, GPT 6 Astra, Sonnet 2/3 runs): §8 is the cour d'appel's motif; the Court neither approves nor rejects it; it falls with the quashed chef de dispositif.


## Update — Claude model sweep via isolated CLI calls (raw-ish), 2026-10-04

Setup: `claude -p --model <id> --tools "" --system-prompt "Tu es un assistant juridique."` from an empty temp dir, no MCP, no session; prompts = `runs/prompts/*.txt` (byte-identical to the Legora runs). Script: `cli/run_cli.py`. 50 calls, 0 errors; `modelUsage` confirms the requested model served each call (legacy remap disabled). Opus 4.1 no longer served.

Graded by `cli/judge.py` (claude-opus-5-5 with the gold rubric from `cases/questions.json`). Calibration on 8 hand-graded Legora answers: **8/8 agreement on PASS vs not-PASS**; the judge is more lenient than my hand grading on FAIL vs SOFT_FAIL (4 cases I called FAIL it called SOFT_FAIL — body correct, headline wrong). Treat P vs not-P as the reliable signal.

| Model | C2-Q1 (×3) | C2-CHUNK | C4-Q3 | C2-Q1 pass rate |
|---|---|---|---|---|
| Haiku 4.5 | F F F | F | F | 0/3 |
| Sonnet 4.5 | F F F | F | s | 0/3 |
| Sonnet 4.6 | F F s | F | F | 0/3 |
| Sonnet 5 | s F s | F | F | 0/3 |
| **Sonnet 5.5** | **P P P** | **P** | **P** | 3/3 |
| Opus 4.5 | s F F | F | s | 0/3 |
| Opus 4.6 | F s F | F | P | 0/3 |
| Opus 5 | P P s* | P | s* | 2/3 |
| **Opus 5.5** | **P P P** | **P** | **P** | 3/3 |
| Fable 5.1 | P P P | P | s* | 3/3 |

P = pass, s = soft fail, F = fail. \* borderline: answer opens "Non — mais la Cour ne se prononce pas…", body fully correct; arguably a pass.

**Totals on the locked red test C2-Q1: 19 of 30 calls do not pass (every model before Sonnet 5.5 / Opus 5).** _(Corrected on 2026-10-05: this line first said 21 of 30, which does not match the table above.)_ C2-CHUNK: 7/10 fail. Per-call answers + verdicts: `cli/out/<model>/`.

### Read-out
- The failure is not a Legora artefact: it reproduces on bare Claude models across two generations (4.5 → 5), small and large.
- Dominant pattern is **laundering**: "la Cour de cassation ne censure pas / ne remet pas en cause ce point" → restated as a rule. Older models also do direct misattribution ("Non, selon la Cour de cassation, … ne suffit pas").
- Only the newest generation (Sonnet 5.5, Opus 5.5, Fable 5.1, largely Opus 5) reads it correctly — consistent with Legora, where only Opus 5/5.5 and GPT 6 Astra passed.
- Product implication: a deterministic speaker/stance tagging layer lets a cheap model (Haiku/Sonnet 4.x, Legora's default Agent) answer like the frontier models. Green test = Haiku 4.5 + our tagging passes C2-Q1 3/3.

## GREEN — pipeline (segment → Jev who/stance → annotated decision → LLM → Jev guard), 2026-10-04

`python3 eval/run_green.py` — same gateway, same prompts/questions, same grader (`runs/cli/judge.py`, Opus 5.5).

| Model | Mode | C2-Q1 | C2-CHUNK | C4-Q3 | C2-Q3 | C3-Q1 | C4-Q1 | C4-Q2 |
|---|---|---|---|---|---|---|---|---|
| Haiku 4.5 | baseline | F F F | F | F | P | P | P | P |
| Haiku 4.5 | **pipeline** | **P P P** | **P** | **P** | P | P | P | P |
| Sonnet 4.6 | baseline | F F F | F | s | P | F | P | P |
| Sonnet 4.6 | **pipeline** | **P P P** | **P** | **P** | P | P | P | P |
| Opus 4.6 | baseline | F F F | F | s | P | s | P | P |
| Opus 4.6 | **pipeline** | **P P P** | **P** | **P** | P | P | P | P |

Baseline 10/27 pass → pipeline **27/27**. Red test C2-Q1: 0/9 → 9/9.

### How we got there (iterations, all on the 4 dev decisions)
1. Single Jev "stance" choice → C2 §8 labelled "quashed" (wrong: the Court never ruled on it). Replaced by two atomic Jev questions: ground outcome (cassation / rejet / non examiné) × "does the Court's own reasoning address this passage?" → §8 = not ruled, §9 = quashed.
2. Drafting-convention rules, deterministic: "En statuant ainsi / Qu'en se déterminant ainsi" censures the passage just recited; "sans qu'il y ait lieu de statuer sur la Xe branche" → not ruled; "par ce seul motif" → only the restated motif is approved, the rest is surplus.
3. First pipeline run: Haiku regressed on C4 (treated an accepted party argument as the Court's rule; answered "Non" to "did the Court uphold…" — overcorrection). Fixed by labels that separate *fate of the decision* from *author of the reasoning*.
4. Guard: one Jev check missed laundering; now three atomic checks (misattribution in the full answer, laundering, misattribution in the opening two sentences). On 41 graded C2-Q1 answers: catches all hard fails, 0/24 false positives at threshold 0.5 (calibrated on the same answers).

### Caveats
- Tuned on the same 4 decisions it is scored on (dev set). The real test is unseen decisions (next: 20 random Judilibre decisions with independently written gold answers).
- Pipeline cost per decision: ~30–60 Jev calls ≈ $0.002–0.004, plus the answer LLM call.

## Mistral + six-model run (pipeline incl. "never open with oui/non when the Court didn't rule"), 2026-10-04

`python3 eval/run_green.py <6 models> --summary summary_all` → `runs/green/summary_all.md`

| Model | Baseline pass (of 9) | Pipeline pass (of 9) | Red test C2-Q1 baseline → pipeline |
|---|---|---|---|
| Claude Haiku 4.5 | 4 | 9 | F F F → P P P |
| Claude Sonnet 4.6 | 3 | 9 | F F F → P P P |
| Claude Opus 4.6 | 3 | 9 | F F F → P P P |
| Mistral Large 3 | 2 | 8 (C2-Q3 soft) | F F F → P P P |
| Mistral Medium 3.5 | 2 | 9 | F F F → P P P |
| Mistral Small | 1 | 9 | F F F → P P P |

**Totals: baseline 15/54 → pipeline 53/54.** French-native Mistral models do *worse* than Claude at baseline (1–2/9 vs 3–4/9): the failure is structural, not linguistic. Through the pipeline even Mistral Small passes everything.

Before the oui/non rule, Mistral Small's pipeline answers opened with a bare "Non." on C2-Q1 (3 soft fails); the rule fixed it for all models. Still dev-set results: the 4 decisions were used to tune the pipeline.

## UNSEEN DECISIONS — first true generalisation test, 2026-10-04

10 decisions drawn at random (seed 7) from the 57 substantive Cour de cassation decisions on Légifrance's latest list (Sept 2026; Soc, Crim, Civ2, Civ3; rejet / cassation / cassation partielle) — `cases/unseen/selection.json`, texts in `cases/raw/U01…U10` (long ones with the formal header — parties, lawyers — omitted; reasoning and dispositif complete). Fetched via the browser (Judilibre sandbox key returns 403).

Questions written **independently of the pipeline** by Opus 5.5 from the raw text only (`eval/make_unseen.py` → `cases/unseen/questions.json`): 20 "Selon la Cour de cassation, …?" traps + 9 excerpt-only questions, each with gold + expected failure. Graded by the same judge. `eval/run_unseen.py`.

**Measured before any change to the pipeline (the honest number):**

| Model | Baseline pass (of 29) | Pipeline pass (of 29) | Baseline excerpts (of 9) | Pipeline excerpts |
|---|---|---|---|---|
| Claude Haiku 4.5 | 16 | **29** | 1 | 9 |
| Claude Sonnet 4.6 | 19 | **29** | 4 | 9 |
| Mistral Large 3 | 15 | **28** | 2 | 9 |
| Mistral Small | 13 | **27** | 1 | 9 |
| **Total** | **63/116 (54%)** | **113/116 (97%)** | 8/36 | 36/36 |

Pipeline non-passes (all Mistral): U01-Q2 ×2 (Court upheld the decision on its *own* reasoning; models said it "approved the cour d'appel on this point" — subtle laundering), U06-Q1 (Mistral Small over-applied "not ruled": the Court did rule that art. 1037-1 is inapplicable).

Gaps found on unseen text (fixed afterwards, results below are post-fix): (1) the Court quoting its **own overruled case law** (U08 §8, revirement of 2e Civ. 17 juin 2021) was tagged as "Court" → new speaker `jurisprudence_anterieure` with stance overruled / cited; (2) "De ces constatations… la cour d'appel **a pu / a exactement déduit**" approves the reasoning recited just before → deterministic approval rule (U08 §16–18, U01 §6).

**After the two fixes (re-run of the pipeline on both sets, fresh annotations; baselines unchanged):**

| Set | Baseline | Pipeline before fixes | Pipeline after fixes |
|---|---|---|---|
| Unseen, 10 decisions × 29 questions × 4 models | 63/116 | 113/116 | **115/116** |
| Dev, 4 decisions × 9 questions × 6 models | 15/54 | 53/54 | **53/54** (no regression; different single soft fail) |

Residual misses after fixes: Mistral Small U01-Q2 (soft: "approved the cour d'appel on this point" without saying approval covers only the deduction); Haiku C4-Q2 (soft: opens "Non." to "did the Court uphold…?" then says it did — the over-correction recurs ~1/54). Both are opening-line contradictions of a correct body; next guard check to add: "does the first sentence contradict the ground outcome?".

Caveats: gold answers for unseen decisions were written by Opus 5.5 (also the judge) — independent of the pipeline, but not yet human-verified. 10 decisions, single run per model×question.
