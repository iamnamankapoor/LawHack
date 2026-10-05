# Red test research: who is speaking in a Cour de cassation decision

Research for the red test, as of 2026-10-04. The 4 candidate cases and 11 trap questions are in `cases/`.

## What we're testing

LLMs credit the Cour de cassation with reasoning that actually belongs to the cour d'appel, or to the appellant's grounds of appeal (*moyens*), because the Court quotes both on the same page. The red test is a single case and question that baseline LLMs get wrong consistently: at least 3 of 5 runs, across at least 2 vendors. The pipeline must turn it green. A separate eval on 20 random cases then checks that the fix generalizes.

## Candidate cases (`cases/raw/`)

| ID | Decision | Why it's a trap |
|---|---|---|
| C1 | Cass. 3e civ., 17 sept. 2026, 24-20.973 (cassation partielle) | The Court quashes on a ground it raised itself (*moyen relevé d'office*), not on the appellant's grounds. The lower court's rule (§11) is the exact opposite of the Court's rule (§10). |
| C2 | Cass. soc., 11 sept. 2026, 24-21.242 (cassation partielle) | **Strongest.** §5–9 sit under the heading "Réponse de la Cour" but are the cour d'appel's reasoning, carried by the pronoun "Il retient / Il relève / Il en déduit", where "Il" refers to the lower court's judgment (*l'arrêt*), not the Court. Splitting on headings alone gets this wrong. |
| C3 | Cass. soc., 9 nov. 2022, 21-17.571 (rejet non spécialement motivé) | The Court says nothing of substance. The only legal content is the losing employer's annexed ground, written as general rules, and those rules were rejected. |
| C4 | Cass. 2e civ., 9 mai 2018, 17-16.546 (cassation partielle, "Attendu" style) | 23k characters and three nested voices. The lower court is endorsed on ground 1 and censured on ground 2. The annexed grounds quote the lower court ("AUX MOTIFS QUE"). |

**Also noticed:** a Légifrance header said "Rejet non spécialement motivé", but the dispositif said DÉCLARE IRRECEVABLE (Civ. 1, 23 oct. 2024, 23-11.608). The page metadata can contradict the operative order, so ground truth must come from the dispositif.

## Data access

- **Légifrance is behind Cloudflare.** curl and in-page fetch() both get 403. The in-app browser works one page at a time. That's fine for a few cases, not for an eval.
- **Judilibre API (PISTE, free)** is the right source for the 20-case eval and beyond. It needs an account at piste.gouv.fr that you create yourself.
  - Production base URL: `https://api.piste.gouv.fr/cassation/judilibre/v1.0`. Endpoints: `/search`, `/decision`, `/export`.
  - `/decision` returns `zones` as character offsets: introduction, expose, moyens, motivations, dispositif, annexes.
  - This is free silver-standard segmentation, but coarse. My inference, which needs checking: the lower-court reasoning in C2 §5–9 would fall inside `motivations`. If so, the official zoning alone doesn't solve the problem, and the gap our product fills is sentence-level attribution inside the zones.
- **Conseil d'État:** opendata.justice-administrative.fr provides XML bulk downloads, with no official API and no zones. Leave it out of scope for now.

## Running the models

- **Vercel AI Gateway:** recommended for the run matrix because it's reproducible and lets us run each question 5 times per model.
  - It is OpenAI-compatible: base URL `https://ai-gateway.vercel.sh/v1`, `Authorization: Bearer $AI_GATEWAY_API_KEY`.
  - `GET /v1/models` lists the exact model ids (`anthropic/…`, `openai/…`, `google/…`).
  - It supports temperature and `json_schema`, and returns `usage`.
  - Rough cost: 11 questions × 6 models × 5 runs ≈ 330 calls at about 6k tokens each, roughly 2M input tokens, likely under $20. To be confirmed with a test call.
- **Consumer apps in the browser** (claude.ai, ChatGPT, Gemini): use these for 1–2 demo screenshots of the locked red test, since that's what lawyers actually use. They're not practical for the full matrix.

## Prior work (summary of the subagent report, mostly unverified)

- **No public benchmark found for this exact failure.** That's a gap, and an opportunity.
- **Stanford, "Large Legal Fictions" (arXiv 2401.01301):** at least 75% hallucination on questions about a case's core holding. Its companion study, "Hallucination-Free?", covers Lexis+ AI and Westlaw. Both are US-only, but the methodology is worth copying.
- **SemEval-2023 Task 6 (rhetorical roles in Indian judgments):** the closest analogue for a label set and a segmenter architecture (transformer + BiLSTM-CRF).
- **2023 Cour de cassation drafting guide (*motivation enrichie*):** three parts — Faits et procédure / Examen des moyens (Énoncé du moyen → Réponse de la Cour) / dispositif. The official PDF is not yet checked.

## Gold labels

The gold answers in `cases/questions.json` are Claude's drafts. Your former-employee contact should verify them before we lock the red test.

## Provenance check (2026-10-04)

All four cases were re-verified against two independent official sources:

| Case | Légifrance | Judilibre (courdecassation.fr) |
|---|---|---|
| C1 Civ. 3, 17 sept. 2026, 24-20.973 (FS-B) | JURITEXT000054929460 | found — "Publié au bulletin, 3e civ., formation de section, cassation" |
| C2 Soc., 11 sept. 2026, 24-21.242 (F-D) | JURITEXT000054929414, ECLI FR:CCASS:2026:SO00747 | found — /decision/6aa3c7f4195da062e02f2ac9; full text matches ours incl. §8 "Il retient, enfin, que le seul fait [...]" and the Schlumberger parties |
| C3 Soc., 9 nov. 2022, 21-17.571 | JURITEXT000046555975 | found — "Formation restreinte RNSM/NA, Rejet" |
| C4 Civ. 2, 9 mai 2018, 17-16.546 | JURITEXT000036930115 | found — "Formation restreinte hors RNSM/NA, Cassation" |

C2 is real but very recent (3 weeks old) and unpublished (inédit, F-D): no commentary or secondary coverage exists, so a web search for it returns little and it is certainly not in any model's training data. That makes it a "real but unseen" case, not a hallucinated one.
