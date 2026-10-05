# Benchmark LawHack — 25 arrêts Légifrance (Cour de cassation)

> **Statut : final.** 25 arrêts, 112 questions figées, 2 conditions et 2 systèmes, soit 448 réponses, toutes notées par le juge.
> Date : 2026-10-04 — code : `main` de talal95c/LawHack (80 tests verts).

## 1. Résumé

| | **LawHack** | Mistral seul |
|---|---|---|
| Score global Q&A (juge, 0–1), texte brut (B) | **0,87** | 0,76 |
| Score global Q&A, PDF uploadé (A) | **0,86** | 0,76 |
| Écart apparié LawHack − Mistral seul (IC 95 % bootstrap) | B : **+0,11** [+0,02 ; +0,20] — A : **+0,10** [+0,01 ; +0,19] | |
| Score sur les **pièges d'attribution** (B / A) | **0,82 / 0,79** | 0,48 / 0,49 |
| **Erreurs d'attribution** (B + A, 224 réponses chacun) | **11** | 44 |
| Latence médiane / réponse (B / A) | 2,4 s / 5,9 s | 1,1 s / 1,2 s |

**Verdict.** Sur l'objectif du projet, qui est de ne pas attribuer à la Cour de cassation ce qui vient d'une partie ou du juge du fond, LawHack fait **4 fois moins d'erreurs d'attribution** que le même modèle utilisé seul avec l'arrêt entier en contexte. L'écart global est statistiquement significatif dans les deux conditions, même si l'intervalle est large (n = 112).

Le gain vient surtout des questions « la Cour a-t-elle constaté [fait] ? » :
- LawHack obtient 0,95 ;
- Mistral seul obtient 0,18 ; il répond « Oui » à tort avec une erreur d'attribution dans 35 cas sur 50.

Faiblesses de LawHack :
- **moins bon** que Mistral seul sur les pièges « moyen du demandeur » (0,61–0,67 contre 0,89) et sur la « règle » (0,79 contre 0,92–1,00) ;
- un peu moins bon sur le hors sujet (0,88–0,92 contre 0,96–1,00) ;
- **2 à 5 fois plus lent**.

## 2. Jeu de données (le .zip)

- 25 arrêts de la Cour de cassation (2026), avec pour chacun le PDF Légifrance, l'export .txt et `cases.json` (métadonnées et sommaire officiel).
- Chambres : civiles 1/2/3, commerciale, sociale, criminelle.
- Solutions : rejet, cassation, cassation partielle, cassation sans renvoi, cassation partielle sans renvoi.
- 12 arrêts ont un sommaire officiel (« règle »). 16 arrêts contiennent un raisonnement du juge du fond explicitement censuré.

## 3. Méthode

Deux conditions :
- **A** : PDF tel qu'uploadé, avec l'en-tête et l'analyse Légifrance.
- **B** : `full_text` seul, sans en-tête ni résumé. Les offsets correspondent alors au gold structurel.

**Gold.** Il n'est pas produit par un LLM :
- la solution vient des métadonnées Légifrance ;
- les zones et locuteurs viennent des marqueurs structurels (« Faits et procédure », « Examen du moyen », « Réponse de la Cour », « PAR CES MOTIFS », « Selon l'arrêt attaqué », « Pour …, l'arrêt retient », « En statuant ainsi ») ;
- la règle vient du sommaire officiel.

**Questions.** 112 questions sont figées dans `questions.jsonl`, générées une seule fois par mistral-large à partir des zones gold :

| Type | n | Piège |
|---|---|---|
| `solution` | 25 | « La Cour a-t-elle cassé l'arrêt attaqué ? » |
| `hors_sujet` | 25 | question plausible que l'arrêt ne traite pas → il faut s'abstenir |
| `fait_cour` | 25 | fait de l'exposé présenté comme « constaté par la Cour de cassation » |
| `moyen_decision` | 9 | thèse du demandeur (rejetée) présentée comme « jugée par la Cour » |
| `appel_cour` | 16 | raisonnement du juge du fond (censuré) présenté comme « jugé par la Cour » |
| `regle` | 12 | « Quelle règle pose la Cour ? », comparée au sommaire officiel |

**Systèmes comparés :**
- **LawHack** : `analyse_async` (Jev openjev-latest), puis `ask` (Mistral medium avec vérification et réécriture des phrases).
- **Mistral seul** : mistral-medium-latest, arrêt complet dans le prompt (`ALONE_PROMPT` de `scripts/bench.py`). C'est le même modèle de rédaction, sans harness.

**Notation :**
- un **juge aveugle** (mistral-large) voit l'arrêt, la question, le gold et la réponse sans les pastilles ni le nom du système, et note 0, 1 ou 2, avec des drapeaux `attribution_error`, `fabrication` et `abstained` ;
- un grader déterministe (`scripts/bench.grade`, vérificateur Jev) sert de second avis (`det_ok`).

## 4. Système 1 (pipeline d'analyse), résultats complets sur 25 arrêts

| Mesure | Résultat |
|---|---|
| Fidélité ingestion PDF (similarité avec le .txt Légifrance) | min **0,986** (arrêt 21), toutes ≥ 0,986 |
| Zonage (précision au caractère, B) | **98,5 %**. Unique confusion : lignes « Sur le rapport de … » classées `introduction` au lieu de `motivations`. C'est du formulaire de procédure ; le classement est défendable et l'erreur réelle est quasi nulle. |
| Attribution des locuteurs sur segments ancrés | **259 / 259** (moyen → partie 58/58, « selon l'arrêt attaqué » → fond 20/20, « l'arrêt retient » → fond 24/24, « en statuant ainsi » → Cour 20/20, dispositif → Cour 133/133, « le moyen n'est pas fondé » → Cour 4/4) |
| Détection de la solution | **24 / 25** (A et B) |
| Segments à faible confiance (< 0,8) | 44 / 1168 (B), 41 / 677 (A) |
| Coût Jev (25 arrêts) | 157 appels / 196 k tokens (B), 165 appels / 204 k tokens (A) ; ≈ 0,7–1,2 s par arrêt |
| Condition A : résumé Légifrance « ANALYSE » | ne fuit dans aucune zone de la Cour (0 segment hors `metadonnees`) |

**Bug confirmé (arrêt 04)** : le dispositif est « REJETTE le recours ». Dans `lawhack/solution.py`, `_REJECT` ne reconnaît que `pourvois?|requêtes?|demandes?`, donc la solution sort en `AUTRE`. Correctif en une ligne : ajouter `recours`.

**Détail mineur (A)** : la ligne d'en-tête « Cour de cassation, civile, Chambre civile 3, … » est attribuée `COUR_CASSATION` en zone `introduction`. C'est sans impact sur les réponses.

## 5. Q&A — détail par type (score du juge 0–1 ; entre parenthèses, le nombre d'erreurs d'attribution)

### Condition B (texte brut) — 224 réponses

| Type | n | LawHack | Mistral seul |
|---|---|---|---|
| solution | 25 | **1,00** | **1,00** |
| hors_sujet | 25 | 0,88 (2 ; 2 fabrications) | **1,00** |
| fait_cour | 25 | **0,96** (1) | 0,16 (18) |
| moyen_decision | 9 | 0,67 (1) | **0,89** (1) |
| appel_cour | 16 | 0,69 (1) | **0,75** (3) |
| regle | 12 | 0,79 | **0,92** |
| **Pièges (fait+moyen+appel)** | 50 | **0,82** (3) | 0,48 (22) |
| **Global** | 112 | **0,87** (5) | 0,76 (22) |

### Condition A (PDF uploadé) — 224 réponses

| Type | n | LawHack | Mistral seul |
|---|---|---|---|
| solution | 25 | **0,98** | **0,98** |
| hors_sujet | 25 | 0,92 (2 fabrications) | **0,96** (1) |
| fait_cour | 25 | **0,94** (1) | 0,20 (17) |
| moyen_decision | 9 | 0,61 (1) | **0,89** (1) |
| appel_cour | 16 | 0,66 (4) | **0,72** (3) |
| regle | 12 | 0,79 | **1,00** |
| **Pièges** | 50 | **0,79** (6) | 0,49 (21) |
| **Global** | 112 | **0,86** (6) | 0,76 (22) |

Grader déterministe (second avis), global : LawHack 0,86 (B) et 0,88 (A) ; Mistral seul 0,71 (B) et 0,67 (A). Il donne le même classement.

## 6. Analyse des échecs de LawHack (score 0 : 8 en B, 10 en A)

1. **Thèse adverse reprise comme décision de la Cour (cause n°1, 7 cas).** Cas : 08 `appel_cour` (A et B), 09 `moyen_decision` (A et B), 16, 18 et 23 `appel_cour` (A). La réponse reprend le raisonnement censuré ou le moyen comme « la Cour juge que … ». La vérification phrase par phrase ne l'a pas bloqué : la phrase cite un segment correctement attribué, mais la **polarité** (approuvé, censuré ou rejeté) n'est pas vérifiée.
2. **Abstentions injustifiées (4 cas).** Cas : 04 `moyen_decision` (A et B), 01 `moyen_decision` (A), 05 `appel_cour` (B). LawHack répond « L'arrêt ne traite pas cette question. » alors que la Cour rejette le moyen ou censure le raisonnement. Ce n'est pas une hallucination, mais la réponse est fausse.
3. **Hors sujet traité à tort (5 cas).** Cas : 10 (B), 18 et 23 (A et B). La question est proche d'un thème de l'arrêt et LawHack produit une réponse de fond. Mistral seul s'est abstenu correctement sur ces cas.
4. **« Règle » moins complète** : 0,79 contre 0,92–1,00. La réécriture prudente coupe une partie de la règle (score 1, aucune note 0).
5. **Bruit du juge** : 13 `fait_cour` (« la cour d'appel a constaté que Mme [T] a été licenciée ») est noté 0. La réponse est défendable, donc la note est probablement un faux négatif du juge.

## 7. Analyse des échecs de Mistral seul

- **`fait_cour` : 35 erreurs d'attribution sur 50** (A + B), et **0 réponse** notée 2. Il répond presque systématiquement « Oui, la Cour de cassation a constaté que … » et reprend à son compte les constatations du juge du fond. C'est exactement l'hallucination d'attribution que LawHack vise.
- **`appel_cour`** : 6 erreurs. Il présente le raisonnement censuré de la cour d'appel comme jugé par la Cour (ex. 05, sociétés MMA).
- Ses points forts sont les abstentions hors sujet, la restitution de la règle et le piège « moyen ».

## 8. Score objectif de l'harness

- **Système 1 (ingestion + zonage + locuteurs + solution) : ≈ 97 / 100.** C'est solide ; la seule erreur réelle est le bug `recours`.
- **Q&A LawHack : 86–87 / 100**, contre 76 pour Mistral seul (+10 à +11 points, significatif).
- **Robustesse aux pièges d'attribution : 79–82 / 100**, contre 48–49 pour Mistral seul.
- **Erreurs d'attribution : 11 sur 448 réponses-condition**, contre 44.

## 9. Priorités d'amélioration (par impact estimé)

1. **Vérifier la polarité** dans le vérificateur, pas seulement le locuteur. Une phrase « la Cour juge X » doit être rejetée quand X correspond à un moyen rejeté ou à un raisonnement du fond censuré. Cela vise 7 échecs (08, 09, 16, 18, 23).
2. **Questions « La Cour a-t-elle jugé que [thèse X] ? »** : au lieu de s'abstenir quand X est un moyen ou un raisonnement du fond présent dans le registre, répondre « Non, c'est la thèse du demandeur / de la cour d'appel, que la Cour a rejetée / censurée ». Cela vise 4 échecs (01, 04, 05).
3. **Filtre hors sujet plus strict** (10, 18, 23) : exiger qu'un segment de la Cour réponde à la question elle-même, et pas seulement à un thème voisin.
4. Ajouter `recours` (et `pourvoi en cassation`) à `_REJECT` dans `lawhack/solution.py`.
5. Réécriture moins agressive sur la « règle » ; latence en condition A (6 s médiane) à surveiller.

## 10. Limites

- n = 25 arrêts et 112 questions : un écart de ±5 points n'est pas significatif par type ; l'écart sur `fait_cour` (0,95 contre 0,18) l'est clairement.
- Les questions pièges sont générées par mistral-large, de la même famille que le système testé. Le gold, lui, est structurel.
- Le juge est un LLM (mistral-large) ; au moins un faux négatif a été repéré (cas 13).
- Un seul tirage par question (pas de moyenne sur plusieurs essais).

## Fichiers

Le harness (`run_s1.py`, `gen_questions.py`, `run_qa.py`, `judge.py`, `aggregate.py`) et les résultats bruts (`s1.json`, `questions.jsonl`, `qa_A.json`, `qa_B.json`) ont été exécutés hors du repo, sur le ZIP de 25 arrêts fourni par l'équipe. Ils ne sont pas versionnés ici.
