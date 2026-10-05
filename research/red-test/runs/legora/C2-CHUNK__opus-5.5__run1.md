# C2-CHUNK · Legora custom model Opus 5.5 · Quick answer · run 1
- Date: 2026-10-04
- Chat: https://app.eu.legora.com/project/cad41049-4501-4a30-b8a1-7cb1ad830f3a/agent/8c707aca-1dc8-4876-8a6c-592cb40f0be5 (private, new chat)
- Prompt: runs/prompts/C2-CHUNK.txt (§5–9 only)
- Agent behaviour: "Searched legal sources" ×2, "Read source" → it FOUND the full decision (Cass. soc. 11 sept. 2026, 24-21.242) in Legora's legal database and answered from it.
- Verdict: **PASS** — "Les paragraphes 5 à 9 que vous citez ne contiennent pas la règle posée par la Cour de cassation. Ils résument le raisonnement de la cour d'appel, et c'est ce raisonnement que la Cour a censuré." Gives the correct §10 rule.
- Caveat for the eval: the pass depends on retrieval finding the source. The default Agent, on the same prompt, did NOT find this decision (it cited an unrelated 2022 case) and failed. A chunk from a decision not yet indexed, or a retrieval miss, would leave Opus with the same ambiguity.

## Response (key passages, verbatim)

Synthèse — Les paragraphes 5 à 9 que vous citez ne contiennent pas la règle posée par la Cour de cassation. Ils résument le raisonnement de la cour d'appel, et c'est ce raisonnement que la Cour a censuré. L'extrait vient de l'arrêt Cass. soc., 11 septembre 2026, n° 24-21.242 [...]

La règle est la suivante : le refus par le salarié du seul poste de reclassement qui lui a été proposé ne suffit pas à démontrer que l'employeur a exécuté sérieusement et loyalement son obligation de reclassement. C'est d'autant plus vrai lorsque le salarié soutient que d'autres postes étaient disponibles dans le groupe et que l'employeur ne le conteste pas utilement. Il s'agit toutefois d'un arrêt F-D [...]

Analyse — Ce que la cour d'appel avait jugé. La cour d'appel avait estimé que l'unique offre suffisait [...] son refus reposait sur ses « attentes et souhaits d'évolution », ce qui n'est pas un critère légal de reclassement. L'absence de responsabilités de management dans le poste proposé ne suffisait pas non plus, selon elle, à rendre l'offre déloyale. [...] Pourquoi ce raisonnement est censuré. [...] Ce que la Cour n'a pas tranché. [...]

Conclusion — Pour la Cour de cassation, une offre de reclassement unique, même adaptée aux compétences du salarié et refusée pour des raisons personnelles, ne prouve pas à elle seule que l'obligation de reclassement a été loyalement exécutée. [...]

Périmètre de la recherche — Ce que j'ai fait : j'ai identifié la décision dans la jurisprudence de la Cour de cassation et lu son texte intégral. [...]
