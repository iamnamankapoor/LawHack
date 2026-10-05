# Legible: site, live demo, benchmark, video

Legible checks **who said what** in a legal draft before it reaches the client. Each sentence of a
draft (from Legora, Harvey, ChatGPT or a lawyer) is matched to the passage of the decision it relies on.
Rules then decide the verdict: **pass**, **review** or **blocked**, with the proof and a suggested rewrite.

This folder is the product layer around the team's System 1 (the `lawhack` package at the repo root).
That package labels who speaks in each sentence. Legible adds its citation rule, the status rules, the
verdicts and the rewrites (see *System 1*).

## Run

```bash
cd legible
pip install -r requirements.txt
cp .env.example .env          # fill the keys
python legible.py             # rebuilds site/data.json (demo decisions, verdicts, benchmark)
python -m uvicorn server:app --port 8766
```

Open http://localhost:8766. With the server running, the page is in live mode: upload a decision
(PDF or text), edit the draft, run the check, compare with GPT-6.1.

Without a server, `site/index.html` + `site/data.json` work as a static demo.

## What is here

| Path | What |
|---|---|
| `site/index.html` | The site: scenario, demo (decision coloured by voice, draft check, proof card), benchmark, upload. Single file. |
| `server.py` | FastAPI: `/api/analyze` (file or text → registry), `/api/verify` (draft → verdicts), `/api/compare` (GPT-6.1 alone). |
| `legible.py` | Builds the registry, statuses and verdicts, rewrites (Mistral, Claude fallback), and `site/data.json`. |
| `jevkit.py` | Jev wrapper with a disk cache and usage log. |
| `bench.py`, `baseline_openai.py` | Benchmark: the same 15 trap sentences checked by GPT-6.1 Sol, GPT-6 Astra and Mistral Medium 3.5 alone, either reading the whole decision or reading only search excerpts. |
| `dossier_arret/`, `dossier_arret_2018/` | Demo decisions, verbatim: Ass. plén. 22 Dec 2023 n° 20-20.648; Civ. 2, 9 May 2018 n° 17-16.546. |
| `eval/arret_traps.json`, `eval/arret2018_traps.json` | 15 draft sentences: 9 misattributed, 6 correct, with the reason. |
| `out_arret/` | Raw benchmark results. |
| `pipeline/`, `run.py`, `eval.py`, `dossier/`, `ui/` | First prototype on a fictional litigation file (Dunder Mifflin): who says what across pleadings. |
| `video/` | 30 s demo film (Remotion). Rendered: `video/out/legible-30s.mp4`. |

## Benchmark (15 sentences, 2 decisions)

| System | Wrong verdicts, whole decision | Wrong verdicts, search excerpts | Source paragraph given | Time / sentence |
|---|---|---|---|---|
| GPT-6.1 Sol | 0 | 2 (false alarms) | 5 / 15 | 3.4 s |
| GPT-6 Astra | 0 | 1 (false alarm) | 5 / 15 | 3.0 s |
| Mistral Medium 3.5 | 7 | 8 | 3 / 15 | 1.8 s |
| Legible | 0 | n/a (maps the whole decision once) | 15 / 15 | 0.39 s |

Legora and Harvey are still to be measured. These are small numbers on two decisions, measured on 2026-10-04.

## System 1

`team_system1.py` runs `lawhack.pipeline.analyse` (the team model) for the demo decisions and for live
uploads. Results on the 15 trap sentences:

| Registry source | Correct verdicts |
|---|---|
| Team model alone | 13 / 15 |
| Team model + Legible's citation rule | 15 / 15, each with the right source paragraph |

The 2 misses of the team model alone are the Court quoting former case law (§ 6, § 10): its labels are COUR_CASSATION / MOTIF, not CITATION.

In live mode, a new decision is analysed in about 3 s, and a draft is checked in about 2 s.

`REGISTRY_SOURCE=placeholder` switches back to the earlier rules + Jev labels. The team package needs
`pip install -e ..` from this folder (or `pip install pymupdf typesafe-sdk`).

The support search works on whole paragraphs: a draft sentence relies on a paragraph, and a fine segmentation must not let one long moyen outweigh a paragraph split in two.
