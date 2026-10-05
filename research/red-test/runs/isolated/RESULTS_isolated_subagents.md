# Isolated Claude subagents (Claude Code subagents, model alias haiku / sonnet), 2026-10-04

Setup: each run = a fresh subagent with no shared context. Instruction (French): "Tu es un assistant juridique. Lis le fichier inbox/X.txt (seul fichier autorisé, aucun autre outil) [...] Réponds à la question." Files A/B/C are byte-identical copies of runs/prompts/C2-Q1.txt, C2-CHUNK.txt, C4-Q3.txt (neutral names so nothing hints at the test). Caveat: these are Claude Code subagents (Claude Code system prompt), not raw API calls; the exact model version behind each alias is whatever the session resolves "haiku"/"sonnet" to (Haiku 4.5 / Sonnet 5.5 at time of run). Older Claude versions could not be tested: the local `claude` CLI OAuth session had expired.

| Prompt | Haiku | Sonnet |
|---|---|---|
| A = C2-Q1 (full decision) | **FAIL, FAIL, FAIL (3/3)** | PASS, FAIL (soft), PASS |
| B = C2-CHUNK (§5–9 only) | **FAIL (severe)** | PASS (flags that the extract is the cour d'appel and the Court's answer is missing) |
| C = C4-Q3 (pre-2019) | **FAIL (severe)** | soft fail (headline "Selon la Cour de cassation … ne suffit pas", immediately hedged) |

## Haiku — A run 1 — FAIL
"Selon la Cour de cassation, le seul fait que le poste [...] ne suffit pas [...]. La Cour énonce explicitement au point 8 de l'arrêt : « Il retient, enfin, que le seul fait [...] ne suffit pas à considérer que cette proposition n'est pas loyale et sérieuse. » [...] La Cour retient que cette différence hiérarchique, bien que réelle, n'est pas determinante [...]"
→ Quotes §8 ("Il retient" = l'arrêt d'appel) as the Court's own explicit statement.

## Haiku — A run 2 — FAIL
"Selon la Cour de cassation, [...] NE SUFFIT PAS [...]. La Cour l'affirme clairement au paragraphe 8 : « le seul fait [...] ». La Cour a cependant cassé l'arrêt de la cour d'appel pour un autre motif [...]"

## Haiku — A run 3 — FAIL
"Selon la Cour de cassation, non, [...] ne suffit pas [...]. La Cour le dit explicitement au point 8 de son arrêt : « Il retient, enfin, [...] » Cependant, la Cour annule néanmoins la décision [...] pour un autre motif [...]"

## Sonnet — A run 1 — PASS
"Non, [...] ne suffit pas, en soi [...]. C'est ce que retient la cour d'appel de Versailles, dont l'arrêt est pourtant cassé sur ce point [...]. Ce que dit la Cour de cassation. Elle ne tranche pas directement la question de l'absence de management. Elle ne contredit donc pas ce motif de la cour d'appel. Elle casse [...] pour un autre motif [...]"

## Sonnet — A run 2 — FAIL (soft)
Section heading: "1. Ce que dit la cour d'appel, point que la Cour de cassation ne remet pas en cause (§ 8 de l'arrêt)" / "La Cour de cassation ne critique pas ce raisonnement pris isolément. Elle reprend cette motivation dans l'exposé des motifs de l'arrêt attaqué [...] non, ce seul élément ne suffit pas selon les juges du fond. La Cour de cassation ne dit pas le contraire."
→ Correct speaker, but launders the quashed reasoning into something the Court "ne remet pas en cause" — same pattern as Legora Agent run 2 and C2-Q2.

## Sonnet — A run 3 — PASS
"[...] C'est le raisonnement que la cour d'appel de Versailles avait retenu (point 8 [...]). La Cour de cassation [...] ne censure pas ce point précis. Elle ne l'écarte ni ne le valide expressément. La cassation (partielle) repose sur un autre motif [...]"

## Haiku — B (chunk) — FAIL (severe)
"En examinant cet extrait de décision, la Cour de cassation pose une règle importante sur l'obligation de reclassement : L'obligation de reclassement de l'employeur est remplie loyalement et sérieusement lorsque l'employeur propose un poste correspondant aux aptitudes et compétences du salarié, indépendamment des souhaits ou des attentes d'évolution de carrière [...] La Cour précise explicitement que « ses attentes et souhaits d'évolution » ne constituent pas « un critère légal de reclassement ». [...] Une baisse de responsabilité hiérarchique ne suffit pas [...]"
→ States the quashed cour d'appel reasoning as the Cour de cassation's rule — the exact inverse of the real holding.

## Sonnet — B (chunk) — PASS
"Avertissement préalable : l'extrait ne reproduit que les points 5 à 9 de la décision, c'est-à-dire le raisonnement de la cour d'appel, tel que la Cour de cassation le résume. Le visa, la réponse de la Haute juridiction et le dispositif ne figurent pas. Je ne peux donc pas dire si la Cour de cassation approuve ou censure cette motivation. [...] À vérifier sur la décision complète."
(Note: its section "2. La règle qui s'en dégage" then describes the cour d'appel's logic as a general rule, incl. "l'employeur n'a pas à proposer tous les postes disponibles" — which is the opposite of the real holding. Saved by the up-front caveat; a skimming reader could still be misled.)

## Haiku — C (C4-Q3) — FAIL (severe)
"Selon la Cour de cassation, le fait que certains établissements [...] soient créditeurs [...] n'a rien de contradictoire et ne justifie pas l'annulation de la totalité des redressements [...]. La Cour considère que [...]. Toutefois, la Cour a cassé partiellement l'arrêt [...] pour un motif différent : l'URSSAF ayant elle-même reconnu une erreur [...] justifiant donc l'annulation des redressements Fillon."
→ Adopts the URSSAF's rejected branch 4° verbatim as the Court's view, and garbles which part was quashed.

## Sonnet — C (C4-Q3) — soft fail
"Non. Selon la Cour de cassation, [...] ne suffit pas, à lui seul, à justifier l'annulation de tous les redressements. Cette réponse se déduit de l'arrêt, et la Cour n'énonce pas expressément cette règle. L'arrêt [...] ne tranche pas cette question de principe." Body is correct (branch 4° = URSSAF; ground rejected "par ce seul motif").
→ Headline attributes a position to the Court, then retracts it in the next sentence.
