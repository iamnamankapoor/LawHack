# C2-CHUNK · Legora Agent (default) · Quick answer · run 1
- Date: 2026-10-04
- Chat: https://app.eu.legora.com/project/cad41049-4501-4a30-b8a1-7cb1ad830f3a/agent/1b617eff-4e06-4c60-8b77-01abec4c43f6 (private, new chat)
- Prompt: runs/prompts/C2-CHUNK.txt — only §5–9 of Cass. soc. 11 sept. 2026, 24-21.242 (the cour d'appel's reasoning as recited by the Court), + "Quelle règle la Cour de cassation pose-t-elle sur l'obligation de reclassement ?"
- Agent behaviour: first asked for the source (pourvoi n°), then Quick/Deep prompt → Quick answer; searched legal sources and cited an unrelated decision (Cass. soc. 2 févr. 2022, 19-21.810) for the text of L. 1233-4.
- Verdict: **FAIL (severe)** — the Conclusion states: "La Cour de cassation (telle que retranscrite dans cet extrait) pose la règle selon laquelle le caractère loyal et sérieux d'une offre de reclassement s'apprécie exclusivement au regard des critères légaux objectifs [...] une offre de reclassement conforme aux critères objectifs ne peut être écartée au seul motif qu'elle ne répond pas aux attentes de carrière du salarié, ni au seul motif qu'elle comporte une perte de responsabilités managériales". This is the cour d'appel's reasoning, which the Cour de cassation QUASHED (§10). The answer even hedges "la Cour de cassation censure (ou valide, selon le sens de l'arrêt retenu par la cour d'appel)" and then picks the wrong reading. It also adds "caractère écrit et précis de l'offre", which is in neither the extract nor the Court's reasoning.
- This is the realistic RAG failure mode: a retrieved chunk of recited lower-court reasoning becomes "the Court's rule".

## Response (verbatim, citation markers removed)

[Pre-answer] Pour répondre précisément, j'ai besoin de connaître la source de cet arrêt afin de vérifier la portée exacte de la règle posée (numéro de pourvoi, date, ou à défaut le texte intégral de la décision si vous l'avez).

[User chose: Quick answer]

**Issue**

L'extrait soumis (arrêt de la chambre sociale de la Cour de cassation, licenciement économique, reclassement) pose la question suivante : lorsqu'un poste de reclassement proposé au salarié correspond à sa catégorie professionnelle, à ses compétences et à sa qualification, l'employeur satisfait-il à son obligation légale de reclassement même si ce poste ne correspond pas aux attentes d'évolution de carrière du salarié, ou comporte une perte de responsabilités (notamment de management) ?

**Règle applicable**

Aux termes de l'article L. 1233-4 du code du travail, le licenciement pour motif économique d'un salarié ne peut intervenir que lorsque tous les efforts de formation et d'adaptation ont été réalisés et que le reclassement de l'intéressé ne peut être opéré dans l'entreprise ou dans les entreprises du groupe ; le reclassement du salarié s'effectue sur un emploi relevant de la même catégorie que celui qu'il occupe ou sur un emploi équivalent assorti d'une rémunération équivalente, et, à défaut et sous réserve de l'accord exprès du salarié, sur un emploi d'une catégorie inférieure ; les offres de reclassement proposées au salarié doivent être écrites et précises. L'obligation de reclassement est une obligation de moyens, dont il appartient à l'employeur de démontrer qu'il s'en est acquitté loyalement.

Le texte ne mentionne nulle part, parmi les critères de validité d'une offre de reclassement, les souhaits d'évolution de carrière ou les aspirations personnelles du salarié : le critère légal porte sur la catégorie d'emploi, l'équivalence de poste et de rémunération, et l'adéquation aux compétences et à la formation du salarié.

**Analyse**

Dans l'extrait transmis, la Cour de cassation censure (ou valide, selon le sens de l'arrêt retenu par la cour d'appel) le raisonnement suivant : la cour d'appel a relevé que le poste de reclassement proposé (comptable fiscaliste) correspondait à la catégorie professionnelle de la salariée (statut cadre), à ses compétences (formation en comptabilité depuis 1995, anglais courant) et que la salariée elle-même, dans sa lettre de refus, n'invoquait pas une absence de compétence mais seulement une inadéquation à « ses attentes et souhaits d'évolution ». La cour d'appel en déduit que ce motif « n'est pas identique [à l'absence de compétence], et ne constitue pas un critère légal de reclassement » — formule qui reprend très exactement la lettre de l'article L. 1233-4 : les conditions de validité d'une offre de reclassement sont objectives (catégorie d'emploi, équivalence, compétences/qualifications), et non subjectives (aspirations de carrière du salarié). De même, la seule perte de responsabilités de management, sans que cela remette en cause l'équivalence de catégorie et de qualification du poste, ne suffit pas à disqualifier le caractère loyal et sérieux de la proposition.

La règle qui se dégage est donc que l'adéquation d'une offre de reclassement s'apprécie au regard des critères légaux objectifs de l'article L. 1233-4 du code du travail — catégorie d'emploi, équivalence, rémunération, compétences et qualifications du salarié — et non au regard de la conformité du poste aux souhaits d'évolution de carrière ou aux aspirations personnelles du salarié, qui ne constituent pas un critère légal de reclassement. Un employeur qui propose un poste correspondant à ces critères objectifs, dans un délai raisonnable avant le licenciement et par écrit, remplit loyalement son obligation de reclassement, même si le salarié estime que ce poste ne correspond pas à son projet professionnel ou implique une perte de responsabilités hiérarchiques, dès lors que cette perte ne rompt pas l'équivalence de catégorie et de qualification.

**Conclusion**

La Cour de cassation (telle que retranscrite dans cet extrait) pose la règle selon laquelle le caractère loyal et sérieux d'une offre de reclassement s'apprécie exclusivement au regard des critères légaux objectifs posés par l'article L. 1233-4 du code du travail :
- correspondance de catégorie d'emploi ou équivalence de poste et de rémunération ;
- adéquation aux compétences, à la formation et à la qualification du salarié ;
- caractère écrit et précis de l'offre.

Les souhaits personnels d'évolution de carrière du salarié ne figurent pas parmi ces critères légaux, de sorte qu'une offre de reclassement conforme aux critères objectifs ne peut être écartée au seul motif qu'elle ne répond pas aux attentes de carrière du salarié, ni au seul motif qu'elle comporte une perte de responsabilités managériales dès lors que l'équivalence de catégorie et de qualification est respectée.

**Portée et limites de la recherche**

Cette analyse s'appuie sur le texte intégral de l'extrait fourni et sur la confirmation du texte de l'article L. 1233-4 du code du travail retrouvée dans un arrêt de la chambre sociale de la Cour de cassation du 2 février 2022 (pourvoi n° 19-21.810). [...] Si vous le souhaitez, je peux approfondir la recherche [...].

Cited 1 source: Cass. soc. 2 févr. 2022, n° 19-21.810.
