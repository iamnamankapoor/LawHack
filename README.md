# Legible

**Know exactly who said what in every ruling.**

Legible is a harness for legal AI. It reads a French Cour de cassation ruling, labels every sentence with its speaker (the Court, the court of appeal, a party, the law) and with what the Court did with it, then makes sure any answer or draft built on that ruling quotes the right voice, with the paragraph as proof.

- **Live demo:** [legible-or4n.onrender.com](https://legible-or4n.onrender.com/) (free hosting: the first load after a quiet period takes about a minute)
- **Pitch deck:** [`pitch/index.html`](pitch/index.html) (open in a browser; ← → to move, N for speaker notes, F for fullscreen), script in [`pitch/SCRIPT.md`](pitch/SCRIPT.md)
- Built in one day at the Mistral × Stanford CodeX hackathon (LLM x Law, Paris, 4 October 2026).

## The problem

Lawyers hesitate to let AI summarise a ruling because the cost is trust. A Cour de cassation ruling quotes the court of appeal and the parties in order to answer them, and the quoted passages often sit under the heading « Réponse de la Cour ». Models read those quotes as the Court's own words. A lawyer then receives a rule the Court never laid down, sometimes taken from a judgment it quashed.

This is a voice disambiguation problem, and it is not specific to rulings: pleadings, case files and awards also layer several voices.

## How it works

1. **Attributing (System 1).** Rules built on the Court's drafting conventions (« En statuant ainsi », « a exactement déduit », « sans qu'il y ait lieu de statuer »…) label what they can. Jev (TypeSafe), a fast calibrated classifier, decides the ambiguous sentences and returns a probability. This runs once per ruling and is cached.
2. **Answering (System 2).** Any LLM (Mistral by default) answers from the labelled ruling. Every sentence carries a pill with its speaker, paragraph and confidence.
3. **Verifying.** A guard re-checks each sentence against its source. A sentence is marked sure, « à vérifier » (below 80% confidence) or blocked, and is rewritten when needed.

The LLM never decides who is speaking. Legible plugs in behind any legal AI through a REST API or an MCP server (`server/`), so a platform keeps its own model and interface.

## Results

Every number in the pitch and on the site comes from one of these tables. Scope and source are given for each.

| Claim | Result | Scope | Source |
|---|---|---|---|
| The same trap question fails across labs | **14 of 19** setups get the speaker wrong. Passes: Opus 5 (2/3 runs), Sonnet 5.5, Opus 5.5, Fable 5.1, GPT 6 Astra | Red test C2-Q1 (Cass. soc., 11 Sept 2026, n° 24-21.242): 10 Claude models via API × 3 runs; 6 Legora options not run via API (default Agent, Opus 4.7, Opus 4.8, GPT 5.5, GPT 5.6 Sol, GPT 6 Astra) × 1 run; 3 Mistral models × 3 runs | [`research/red-test/runs/RESULTS.md`](research/red-test/runs/RESULTS.md) |
| Every model passes with the harness | **0/18 → 18/18** red-test runs; **15/54 → 53/54** on all 9 dev questions | 6 models: Claude Haiku 4.5, Sonnet 4.6, Opus 4.6; Mistral Small, Medium 3.5, Large 3. Tuned on these 4 rulings | [`research/red-test/runs/green/summary_all.md`](research/red-test/runs/green/summary_all.md) |
| It generalises to new rulings | **54% → 97%** (63/116 → 113/116), measured before any change; 115/116 after two fixes | 10 random September 2026 rulings, 29 questions each, 4 models | [`research/red-test/runs/unseen/`](research/red-test/runs/unseen/) |
| It fixes search-based answers | **22% → 100%** (8/36 → 36/36) | Questions answered from excerpts only, same 10 rulings | same |
| Small model at frontier quality | Haiku 4.5 + harness passes the red test 3/3, like Opus 5.5, at **≈5× lower cost** ($0.012 vs $0.057 per question) and **3.5× faster** (4.1 s vs 14.6 s) | Red test C2-Q1 | [`research/red-test/EVIDENCE.html`](research/red-test/EVIDENCE.html) |
| Fewer misattributions in the app | **11 vs 44** misattributed answers out of 224 (**4× fewer**), with the same Mistral model | 25 Légifrance rulings, 112 questions × (PDF + text) | [`bench/legifrance25/BENCHMARK.md`](bench/legifrance25/BENCHMARK.md) |
| Every draft sentence traced to its source | **15/15** sentences with their source paragraph; GPT-6.1 Sol and GPT-6 Astra alone: 5/15 | 15 draft sentences, 9 traps, 2 rulings | [`legible/README.md`](legible/README.md), `app/static/showcase/data.json` |

Speed, measured:
- labelling a ruling takes **2.1 s** (median of 14 rulings, red-test engine) and **2.7 s** on the live app for the red-test ruling;
- a draft-check call takes **0.39 s** per sentence (mean of 66 calls);
- a cited answer in the app takes **2.4 s** from text and **5.9 s** from a PDF (median), against 1.1 s and 1.2 s for Mistral alone.

### Where Legible is weaker

We report these alongside the headline numbers:

- **Held-out QA (Judilibre, 102 questions, 30 rulings never used in tuning):** attribution hallucination 22% for Legible against 26% for Mistral alone. The difference is not significant (p = 0.66), and Legible abstains wrongly more often (23% against 8%). See [`docs/SPEC.md` § 8](docs/SPEC.md#8-évaluation).
- **Légifrance benchmark:**
  - party arguments or censured reasoning passed off as the ruling: 27/50 correct for Legible against 39/50 for Mistral alone;
  - rule matching the official summary: 14/24 against 22/24;
  - invented facts: 4 against 1.
- **Grading:**
  - the red-test and unseen answers were graded by an Opus 5.5 judge with a gold rubric (8/8 agreement with hand grading);
  - the Légifrance benchmark was graded by a blind `mistral-large` judge;
  - no lawyer has reviewed the gold answers yet.
- **Scope:** Cour de cassation rulings only.

## Repository map

| Path | What it is |
|---|---|
| `app/` | The live web app (FastAPI + one-page UI): landing page, reading view, cited answers, draft-check showcase at `/showcase/` |
| `lawhack/` | The harness: ingestion and OCR, zoning, segmentation, Jev attribution, retrieval, answering, verification, feedback |
| `server/` | REST API and MCP server (`lawhack_who_said`, `lawhack_verify`, `lawhack_get_passage`…); see [`docs/connecteur.md`](docs/connecteur.md) |
| `legible/` | The draft checker and its 15-sentence benchmark against GPT-6.1 Sol, GPT-6 Astra and Mistral |
| `bench/`, `eval/`, `scripts/` | Légifrance and Judilibre benchmarks, question sets, judges and evaluation scripts |
| `research/red-test/` | The red test: cross-lab failures, the stance-attribution engine, red → green and unseen-ruling results, Legora transcripts |
| `pitch/` | The pitch deck, speaker script and screenshots of the live app |
| `docs/SPEC.md` | The original design document, in French: ontology, Jev usage, honesty policy, full evaluation protocol |
| `tests/` | Offline tests (Jev mocked) |

## Run it locally

```bash
python3 -m pip install -e ".[dev]"
cp .env.example .env          # TYPESAFE_API_KEY (Jev or Codiv) and MISTRAL_API_KEY
python -m uvicorn app.server:app --port 8765
```

Then open http://localhost:8765. Without keys the app still opens, but it labels rulings with an offline heuristic and cannot answer questions.

`python -m pytest` runs the offline tests: 119 pass and 2 fail (`test_rewrite_is_dropped_or_ignored`, `test_ask_returns_answer_id_and_wrong_speaker_updates_registry`). Both fail the same way on the upstream branch.

**Deploying:** `render.yaml` describes a single Render web service. Create a Render Blueprint from this repo and set `TYPESAFE_API_KEY` and `MISTRAL_API_KEY`. The current live demo is deployed from [talal95c/LawHack](https://github.com/talal95c/LawHack), which runs the same app code.

## Data

- Rulings from Légifrance and the Judilibre API, plus the [`antoinejeannot/jurisprudence`](https://huggingface.co/datasets/antoinejeannot/jurisprudence) dataset (Etalab 2.0).
- The red-test rulings are listed with their sources in `research/red-test/cases/`.
