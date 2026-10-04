# Évaluer les hallucinations d'attribution : état de l'art et choix de LawHack

Revue faite pour concevoir le protocole d'éval (arXiv, GitHub et forums HN, octobre 2026). Pour chaque source, on
indique ce qu'on reprend et où c'est implémenté.

## 1. Hallucinations juridiques : ce qu'on mesure

| Travail | Idée clé | Repris dans LawHack |
|---|---|---|
| Magesh et al. 2024, *Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools* ([2405.20362](https://arxiv.org/abs/2405.20362)) | Éval préenregistrée de Lexis+ AI et de Westlaw. Le RAG juridique hallucine encore 17 à 33 % du temps. Typologie : *correct / incomplete / misgrounded / incorrect* ; hallucination = *incorrect* ou *misgrounded* | Le juge renvoie ce `label`, et `eval_qa.py` calcule le taux d'hallucination au sens Magesh. *Misgrounded* correspond exactement à notre erreur d'attribution : le contenu est vrai, mais rattaché au mauvais locuteur |
| Dahl et al. 2024, *Large Legal Fictions* ([2401.01301](https://arxiv.org/abs/2401.01301)) | Hallucinations à 58–88 % sur des questions vérifiables, et des LLM qui ne corrigent pas une prémisse fausse (*contra-factual*) | Questions pièges `piege_moyen` / `piege_fond` / `allegue` : la question présuppose que la Cour a dit ce que la partie ou la cour d'appel a dit |
| REASONS ([2405.02228](https://arxiv.org/abs/2405.02228)) | Deux métriques indissociables, le taux d'abstention et le taux d'hallucination : le RAG réduit les hallucinations mais n'ose plus s'abstenir | On publie toujours ensemble l'abstention correcte (`hors_arret`), la fausse abstention et l'hallucination |
| ClaimRAG-LAW ([2605.21071](https://arxiv.org/abs/2605.21071)), LexAgentHallu ([2609.09754](https://arxiv.org/abs/2609.09754)) | Éval fine, au niveau de l'affirmation ; benchmark juridique bilingue FR/EN | Mesure au niveau phrase sur le registre (`eval_zones.py`) et au niveau question (`eval_qa.py`) |
| LegalBench / LegalBench-RAG ([HazyResearch/legalbench](https://github.com/HazyResearch/legalbench), [2408.10343](https://arxiv.org/abs/2408.10343)) | Tâches juridiques anglophones et retrieval | Non repris : pas d'attribution de locuteur, pas de droit français |

## 2. Citations et ancrage

| Travail | Idée clé | Repris |
|---|---|---|
| ALCE ([2305.14627](https://arxiv.org/abs/2305.14627), [code](https://github.com/princeton-nlp/ALCE)) | *Citation precision/recall* : chaque phrase est-elle soutenue par ses citations ? | Contrôle déterministe des citations `[S-xxx]` de LawHack (existence dans le registre). Le vérificateur `lawhack/verify.py` contrôle le locuteur cité |
| *Correctness is not Faithfulness* ([2412.18004](https://arxiv.org/abs/2412.18004)) | Une citation « correcte » peut n'être qu'une post-rationalisation (jusqu'à 57 %) | Chez LawHack, les citations proviennent du registre *avant* la rédaction : l'attribution est construite, pas justifiée après coup |
| RAGAS ([2309.15217](https://arxiv.org/abs/2309.15217)), ARES ([2311.09476](https://arxiv.org/abs/2311.09476)) | Fidélité, pertinence, juges LLM. ARES corrige le juge par PPI avec quelques annotations humaines | Correction PPI reprise (§3) ; métriques RAGAS génériques non reprises (elles ne mesurent pas *qui* parle) |

## 3. Rigueur statistique et juge LLM

| Travail | Recommandation | Repris |
|---|---|---|
| Miller 2024, *Adding Error Bars to Evals* ([2411.00640](https://arxiv.org/abs/2411.00640)) | IC systématiques. Erreurs-types *clusterisées* quand les items partagent un contexte. Comparaisons *appariées* (mêmes questions pour les deux systèmes) | Bootstrap par **arrêt** (les phrases et questions d'un même arrêt ne sont pas indépendantes) ; comparaison appariée LawHack − baseline avec IC et test de McNemar exact |
| evalstats ([2609.35815](https://arxiv.org/abs/2609.35815), [code](https://github.com/ianarawjo/evalstats)) | Les statistiques calculées sur un juge LLM brut gonflent les faux positifs. Corriger par PPI avec un petit échantillon humain **tiré uniformément au hasard**, jamais ciblé | `eval_qa.py --export-labels N` (tirage uniforme, système masqué) puis `--import-labels` : kappa de Cohen juge/humain et taux corrigés PPI |
| *Validating LLM-as-a-Judge under Rating Indeterminacy* ([2503.05965](https://arxiv.org/abs/2503.05965)), *Accounting for Bias* ([2609.31184](https://arxiv.org/abs/2609.31184)) | Biais du juge : position, verbosité, auto-préférence. L'accord juge/humain doit être mesuré, pas supposé | Juge à l'aveugle (il ignore le système, et le prompt neutralise la longueur et le style), température 0, critère binaire défini avec contre-exemples. Le juge (mistral-large) est différent du modèle qui répond (mistral-medium) |
| Wilson | IC fiable sur les petits effectifs par catégorie | IC de Wilson par type de question |

## 4. Efficacité

- Cache disque des registres, des réponses et des verdicts du juge, avec des clés incluant le modèle et le prompt : une réexécution ne coûte aucun appel API, et un run interrompu reprend.
- Débit Jev plafonné (`EVAL_JEV_RPM`, 25 par défaut) avec reprise sur 429, sans perte d'arrêt : la clé Codiv (60 req/min) est partagée avec la démo.
- Vérité terrain gratuite et à grande échelle : les `zones` Judilibre servent d'annotation de section sur 277 arrêts (split dev/test par hash), donc aucune annotation manuelle n'est nécessaire pour le benchmark d'attribution de base.

## 5. Limites assumées

- Les réponses de référence QA sont générées par mistral-large puis validées par une seconde passe mistral-large contre le texte zoné (46/60 retenues). La validation humaine (§3) est la prochaine étape.
- Le juge appartient à la même famille que la baseline (Mistral) : le biais d'auto-préférence est possible, d'où la validation humaine et la correction PPI.
- Les `zones` Judilibre délimitent des sections, pas des locuteurs : « moyen attribué à la Cour » est une borne de l'erreur critique, pas une mesure exhaustive de toutes les erreurs d'attribution.
