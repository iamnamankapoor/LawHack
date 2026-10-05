# Red test

This folder is the evidence behind the pitch's cross-lab numbers. It asks whether models and legal AI products attribute a Cour de cassation ruling to the right speaker, and whether a stance-attribution harness fixes it.

Open [`EVIDENCE.html`](EVIDENCE.html) in a browser for the full write-up, including screenshots and every graded answer.

## The test

- **Ruling:** Cass. soc., 11 September 2026, n° 24-21.242 (`cases/raw/C2_soc_2026-09-11_24-21242.txt`). It was three weeks old at test time, so it is in no model's training data.
- **Question (C2-Q1):** « Selon la Cour de cassation, le seul fait que le poste de reclassement proposé soit dépourvu de responsabilité managériale suffit-il à considérer que la proposition n'est pas loyale et sérieuse ? »
- **Correct answer:** the Court does not rule on this. §8 is the court of appeal's reasoning (« Il retient, enfin »), and the Court quashed that judgment on another ground (§10).

## Results

| Result | Numbers | File |
|---|---|---|
| Legora, 8 model options, full ruling pasted | 5 of 8 fail (default Agent 3/3 runs); Opus 5, Opus 5.5 and GPT 6 Astra pass | `runs/RESULTS.md`, `runs/legora/` |
| Bare Claude models via the API, 10 models × 3 runs | 19 of 30 calls do not pass; Sonnet 5.5, Opus 5.5 and Fable 5.1 pass 3/3 | `runs/RESULTS.md`, `runs/cli/` |
| Red → green, 6 models (Claude and Mistral) | Red test 0/18 → 18/18; all 9 dev questions 15/54 → 53/54 | `runs/green/summary_all.md` |
| Unseen rulings: 10 random Sept-2026 rulings × 29 questions × 4 models | 63/116 → 113/116 before any change (`runs/unseen/before_fixes/`), 115/116 after two fixes (`runs/unseen/summary.md`); excerpt-only questions 8/36 → 36/36 | `runs/unseen/` |
| Cost and speed, red test | Haiku 4.5 + harness passes 3/3 at $0.012 and 4.1 s per question, against $0.057 and 14.6 s for Opus 5.5 alone; labelling a ruling has a median of 2.1 s | `EVIDENCE.html` § Cost & speed |

The 19 setups quoted in the pitch are:
- the 10 Claude API models;
- the 6 Legora options not also run via the API: default Agent, Opus 4.7, Opus 4.8, GPT 5.5, GPT 5.6 Sol and GPT 6 Astra;
- the 3 Mistral models.

14 of them fail.

## Method and limits

- **Grading:** answers were graded by `runs/cli/judge.py` (Opus 5.5 with the gold rubric in `cases/questions.json`), which agreed 8/8 with hand grading on pass vs not-pass.
- **Gold answers:** the unseen-ruling questions and gold answers were written by Opus 5.5 from the raw text, independently of the pipeline. No lawyer has reviewed them yet.
- **Dev tuning:** the dev results (`runs/green/`) are tuned on the same 4 rulings they are scored on. The unseen-ruling results are the generalisation test.
- **Legora runs:** Legora was tested in "Quick answer" mode only.

## Code

- `engine/`: segmentation, Jev speaker and stance tagging with the drafting-convention rules (`tag.py`), annotated rendering, and the answer guard.
- `eval/run_green.py` and `eval/run_unseen.py` regenerate the results.

They call models through the Vercel AI Gateway, which needs `AI_GATEWAY_API_KEY` in a `.env` file in this folder. That file is git-ignored.
