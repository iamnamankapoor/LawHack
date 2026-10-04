# Legible

> **Qui parle dans cette décision ?**
> Legal AI tools mix up who said what in French court decisions. Legible labels every paragraph with **who is speaking** and **what the Court did with it**, so lawyers read the decision as the Court wrote it — and AI answers stop crediting the Court with words it never adopted.

*Legi* is the law; *legible* is readable. Built at the Mistral × Stanford CodeX LLM x Law hackathon, Paris.

## The problem

When the Cour de cassation rules, it quotes the lower court's reasoning and the parties' arguments in order to answer them. AI tools read those quotations as the Court's own position.

On a real decision from September 2026 (Cass. soc., 11 sept. 2026, n° 24-21.242), asked *"Selon la Cour de cassation, …?"* about a sentence that is the cour d'appel's quashed reasoning:

- **Legora's default Agent: wrong 3 times out of 3.** 6 of Legora's 8 model options fail.
- **Bare Claude models: 21 of 30 calls fail** — every model before Sonnet 5.5 / Opus 5.
- **Mistral, French-native, does worst** on the raw text (1–2 of 9 questions right).

The dominant error is *laundering*: "the Court did not censure this point" turned into "the Court approves it". Full evidence, screenshots and every answer: [`docs/EVIDENCE.html`](docs/EVIDENCE.html).

## Results

Same questions, same gateway, same grader (an LLM judge with gold answers), model reading the raw decision vs the same model reading Legible's labelled decision.

| | Raw decision | With Legible |
|---|---|---|
| Red test (C2-Q1), 4 models × 3 runs | 0 / 12 | **12 / 12** |
| **10 unseen decisions** (random, Sept 2026), 29 questions × 4 models | 63 / 116 (54 %) | **116 / 116** |
| Excerpt-only questions (what search-based tools pass to the model) | 8 / 36 | **36 / 36** |

Questions on the unseen decisions were written independently of the pipeline (by Opus 5.5 from the raw text). Caveats in [`docs/RESULTS.md`](docs/RESULTS.md): single runs, gold answers not yet reviewed by a lawyer.

**Cost and speed:** labelling a decision takes a median **2.1 s** and **~$0.001** (Jev, priced on input only); it is done once and reused for every question. A cheap model on top (Mistral Small, Claude Haiku) then matches frontier models on attribution.

## How it works

```
decision ─► segment (rules) ─► who speaks (Jev) ─► what the Court did (Jev + rules) ─► labelled decision ─► answer (any LLM) ─► guard (Jev ×3 + outcome check)
```

- **Who speaks:** Cour de cassation · cour d'appel · partie · faits · jurisprudence antérieure. Jev reads the preceding paragraphs, so *"Il retient…"* resolves to the lower court.
- **What the Court did:** per ground, quashed or rejected; per passage, does the Court's own reasoning address it? → *approuvé · censuré · non tranché · argument écarté / accueilli · jurisprudence abandonnée*. French drafting conventions are rules: *"En statuant ainsi"* censures the passage just before; *"a pu / a exactement déduit"* approves it; *"par ce seul motif"* approves only the restated motif; *"sans qu'il y ait lieu de statuer sur…"* means not ruled on.
- **Uncertain labels:** a second Jev pass with the options reversed (averaged), then a cheap LLM only if still unsure.
- **Guard:** misattribution, laundering, a wrong opening line, and an answer that contradicts the dispositif → one rewrite.

Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Design language (IBM Carbon, IBM Plex): [`docs/design.html`](docs/design.html).

## The app

- **Décision:** the text with a margin bar per voice and a status tag per paragraph; *Cour seule* dims everything that is not the Court.
- **Ce que la Cour a jugé:** the Court's own sentences, quoted verbatim per ground, plus what it did not rule on. No paraphrase: interpretation stays with the lawyer.
- **Poser une question:** answers cite paragraphs (§ links jump to the text) and say when they were verified.
- **Vérifier un brouillon:** paste a note written by Legora, Harvey or ChatGPT; each sentence is *conforme / à vérifier / à corriger*, with its source paragraph and a rewrite.

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[pdf,dev]"
cp .env.example .env               # AI_GATEWAY_API_KEY is required
uvicorn legible.api:app --port 8766
```

Open http://localhost:8766 and pick one of the 14 bundled decisions (`data/decisions/`), or drop a PDF / .txt.

- **Tests (offline, fake Jev):** `pytest`
- **MCP connector** (Claude, ChatGPT, Le Chat, Legora): `pip install -e ".[mcp]"` then `python -m legible.mcp_server` (stdio) or `--http`
- **Evaluation:** `python eval/run_unseen.py` and `python eval/run_dev.py` (needs the `claude` CLI for the judge); `python eval/make_questions.py` regenerates the unseen questions.

## Credits

This version merges two efforts. The core (speaker + stance attribution, guard, evaluation) replaces the first `lawhack/` pipeline after a head-to-head on the same questions (ours 29/29, first pipeline 26/29 on unseen decisions with Mistral Large 3). Carried over from the team's first prototype: PDF ingest with Légifrance cleanup and Mistral OCR, the dispositif outcome check, the MCP connector, the second Jev pass with reversed options, and the Legible draft-checker idea. The previous code is in this repository's history.
