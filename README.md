# LawHack

> **Les IA juridiques savent ce qui a été dit. LawHack vérifie qui l'a dit.**

LawHack est un *harness* **Système 1 → Système 2** pour les décisions de justice françaises.
Un modèle rapide et calibré (Jev, de TypeSafe) attribue chaque passage d'un arrêt à son
locuteur — la Cour, la juridiction du fond, une partie… — avec une probabilité. Un grand LLM
(Mistral) répond ensuite aux questions de l'avocat à partir de cette compréhension structurée,
en citant le paragraphe source et en signalant honnêtement ses doutes.

Projet né au hackathon Mistral × Stanford CodeX (LLM x Law, Paris).

---

## Sommaire

1. [Le problème](#1-le-problème)
2. [Le produit (V1)](#2-le-produit-v1)
3. [Format de présentation (UX AI native)](#3-format-de-présentation-ux-ai-native)
4. [Architecture](#4-architecture)
5. [Ontologie d'attribution](#5-ontologie-dattribution)
6. [Utilisation de Jev (Système 1)](#6-utilisation-de-jev-système-1)
7. [Système 2 et politique d'honnêteté](#7-système-2-et-politique-dhonnêteté)
8. [Données et benchmark](#8-données-et-benchmark)
9. [Stack technique et arborescence](#9-stack-technique-et-arborescence)
10. [Configuration et clés](#10-configuration-et-clés)
11. [Démo](#11-démo)
12. [Feuille de route](#12-feuille-de-route)
13. [Organisation de l'équipe](#13-organisation-de-léquipe-3-personnes)
14. [Consignes pour les agents de code](#14-consignes-pour-les-agents-de-code)
15. [Références](#15-références)

---

## 1. Le problème

Les LLM juridiques ne se trompent pas seulement en inventant des arrêts : ils se trompent
**d'auteur**. On appelle cela l'**hallucination d'attribution** :

- présenter le moyen du demandeur comme la position de la Cour (« la Cour retient que… ») ;
- confondre ce qu'a jugé la cour d'appel avec ce que décide la Cour de cassation ;
- présenter une simple allégation d'une partie comme un fait établi.

Les outils existants vérifient qu'une citation **existe** ; aucun ne vérifie **qui parle et
avec quel statut**. Pour un avocat, une erreur d'attribution est grave : elle est relevée
immédiatement par l'adversaire ou le juge.

**Cas d'usage V1 : les arrêts de la Cour de cassation.** Leur rédaction est balisée
(« Faits et procédure », « Énoncé du moyen », « Réponse de la Cour », dispositif) et l'API
Judilibre fournit ces zones : cela donne une vérité terrain gratuite pour mesurer l'attribution.

**Vision long terme :** un garde-fou générique d'attribution énonciative pour tout texte
juridique — dossiers de 100 à 200 pages, assignations, conclusions, pièces — avec une
restitution des faits croisée avec *qui affirme quoi*.

## 2. Le produit (V1)

Un **chat juridique** :

1. l'avocat dépose **un PDF propre** (ou un fichier `.txt`) d'arrêt (Légifrance ou Judilibre) ;
2. LawHack analyse l'arrêt en coulisse et construit un **registre d'attribution** interne ;
3. l'avocat pose des questions libres ;
4. chaque réponse **cite sa source** (« §8, Réponse de la Cour »), distingue les voix
   (« la Cour décide », « la cour d'appel avait retenu », « le demandeur soutient ») et
   **dit quand elle n'est pas sûre** ou quand l'arrêt ne tranche pas.

Principes produit :

- **Un seul arrêt par session** en V1.
- Réponses **fondées uniquement sur le PDF** (pas de connaissances générales du LLM présentées comme issues de l'arrêt).
- **Ne jamais promettre « zéro erreur »** : la promesse est « beaucoup moins d'erreurs, mesurées, et quand LawHack doute, il le dit ».
- La vue complète de l'arrêt coloré par locuteur est **hors V1** (option future).

## 3. Format de présentation (UX AI native)

L'interface reste un chat, mais la couche Système 1 doit être **visible**.

### 3.1 Pastilles d'attribution (prioritaire)

Chaque phrase de réponse se termine par une pastille colorée par locuteur :

> La Cour casse l'arrêt pour défaut de base légale **[Cour · §8 · 97 %]**.
> La cour d'appel avait retenu une faute grave **[Cour d'appel · §5 · 91 %]**.
> Le salarié soutenait l'inverse **[Demandeur · §3 · 62 % ⚠]**.

- **Survol** : affiche le paragraphe source et la distribution Jev (ex. « Cour 97 % · Cour d'appel 2 % · Demandeur 1 % »).
- **Couleurs d'état** : normal si confiance ≥ 0,8 ; orange « ⚠ à vérifier » entre 0,5 et 0,8 ; gris « l'arrêt ne tranche pas » si aucune source.
- Couleur de fond = locuteur (Cour, juridiction du fond, demandeur, défendeur, ministère public, loi, indéterminé).

### 3.2 Animation de lecture au dépôt (si le temps le permet)

Pendant l'analyse (~3 s), l'arrêt défile en miniature et chaque paragraphe se colore à mesure
qu'il est attribué, avec un compteur : `42 paragraphes · 38 ms/paragraphe · 0,001 $`.
La vue disparaît ensuite au profit du chat.

### 3.3 Mode démo : écran partagé

Même question piège posée à **Astra seul** et à **LawHack**. Bouton « Vérifier » : la réponse
d'Astra passe dans le vérificateur LawHack, la phrase mal attribuée devient rouge
(« attribué à la Cour — en réalité le demandeur, §3 »).

Hors périmètre : graphiques de probabilités détaillés, vue d'annotation complète.

## 4. Architecture

```text
PDF ──► [1] Extraction ──► [2] Zonage ──► [3] Segmentation ──► [4] Attribution (Jev)
                                                                     │
                                                                     ▼
                                                     [5] REGISTRE (JSON, mis en cache)
                                                                     │
Question ──► [6] Routage de la question (Jev) ──► [7] Récupération ◄─┘
                                                        │
                                                        ▼
                                  [8] Réponse (Mistral) avec citations [S-xx]
                                                        │
                                                        ▼
                                  [9] Vérification (Jev) + décision d'abstention
                                                        │
                                                        ▼
                         Réponse finale : texte + pastilles (locuteur · § · confiance)
```

| Étape | Qui | Détail |
|---|---|---|
| 1. Extraction | code (`pymupdf4llm`) | PDF → texte/Markdown en conservant pages et numéros de paragraphe. |
| 2. Zonage | **règles** | Rubriques de l'arrêt (« Faits et procédure », « Énoncé du moyen », « Réponse de la Cour », dispositif) → zone. Les zones Judilibre servent de référence et de vérité terrain. |
| 3. Segmentation | code | Paragraphes numérotés (§n) puis phrases, avec identifiants stables `S-001`… et offsets. |
| 4. Attribution | **Jev** | Uniquement là où les règles ne suffisent pas (ex. la Cour reprend la cour d'appel). Voir §6. |
| 5. Registre | code | JSON par segment : locuteur, type, statut, chaîne de citation, probabilités, confiance. Mis en cache par hash du PDF. |
| 6. Routage | **Jev** | Sur quoi porte la question : décision de la Cour, argument d'une partie, juridiction du fond, ou absent de l'arrêt. |
| 7. Récupération | code (+ Jev si besoin) | Sélection des segments pertinents (BM25 puis re-classement Jev). |
| 8. Réponse | **Mistral** | Rédige la réponse à partir du registre **et** des extraits originaux, avec citations `[S-xx]`. |
| 9. Vérification | **Jev** | Pour chaque phrase de la réponse : quel segment la soutient (Choice) et le locuteur annoncé est-il correct. |

**Règle d'or : ce qui peut être fait par du code ou des règles n'est pas confié à un modèle.**
Jev prend les décisions ambiguës, Mistral rédige, le code décide quoi faire de la confiance.

## 5. Ontologie d'attribution

Codes stables (à utiliser tels quels dans le code et les données) :

**Locuteur (`speaker`)**

| Code | Signification |
|---|---|
| `COUR_CASSATION` | La Cour énonce son propre raisonnement ou sa décision |
| `JURIDICTION_FOND` | Raisonnement rapporté de la cour d'appel / du tribunal |
| `DEMANDEUR` | Le demandeur au pourvoi |
| `DEFENDEUR` | Le défendeur |
| `MINISTERE_PUBLIC` | Avocat général / ministère public |
| `LOI` | Texte de loi cité ou visé |
| `INDETERMINE` | Impossible à déterminer — **toujours présent** |

**Type d'énoncé (`type`)** : `FAIT`, `PROCEDURE`, `MOYEN`, `MOTIF`, `VISA`, `DISPOSITIF`, `CITATION`.

**Statut épistémique (`status`)** : `CONSTATE` (fait retenu par les juges du fond), `ALLEGUE`
(affirmé par une partie), `CONTESTE`, `DECIDE` (tranché par la Cour).

**Chaîne de citation (`chain`)** : liste ordonnée des locuteurs pour les citations imbriquées,
ex. `["COUR_CASSATION", "JURIDICTION_FOND", "DEMANDEUR"]` = la Cour rapporte que la cour
d'appel a relevé que le demandeur soutenait…

Exemple d'entrée du registre :

```json
{
  "id": "S-017",
  "paragraph": 8,
  "zone": "motivations",
  "page": 3,
  "text": "Pour dire le licenciement fondé, l'arrêt retient que…",
  "speaker": "JURIDICTION_FOND",
  "chain": ["COUR_CASSATION", "JURIDICTION_FOND"],
  "type": "MOTIF",
  "status": "CONSTATE",
  "probabilities": {"JURIDICTION_FOND": 0.91, "COUR_CASSATION": 0.07, "INDETERMINE": 0.02},
  "confidence": 0.86,
  "source": "jev"
}
```

`source` vaut `rule` quand l'attribution vient du zonage déterministe.

## 6. Utilisation de Jev (Système 1)

Jev (TypeSafe) ne génère pas de texte : il reçoit un `state` et des questions typées
(`noul` = oui/non, `choice` ≤ 255 options, `score` = niveaux ordonnés) et renvoie une
probabilité par option et une confiance. Endpoint : `POST /v1/systemone`.

### Choix retenus

- **Fournisseur** : Jev hébergé (`jev-latest`, 0,042 $ / M tokens d'entrée, sortie gratuite,
  64k tokens de contexte). **Secours** : OpenJev sur Codiv (`openjev-latest`, même API et même
  SDK, seule l'URL change, 100 M tokens gratuits). Pas d'auto-hébergement en V1.
- **Granularité** : une requête **par paragraphe** ; `state` = le paragraphe avec ses phrases
  identifiées + la zone ; **une question `choice` par phrase** (questions évaluées en parallèle
  et isolément, donc quasi sans surcoût de latence). Ne jamais envoyer tout l'arrêt comme
  state : la précision baisse avec le contexte non pertinent.
- **Langue** : texte de l'arrêt en français ; consignes et descriptions d'options **en anglais**
  par défaut (Jev est surtout entraîné en anglais). À A/B tester contre des consignes en français.

### Pièges connus (doc « Jev 1.13 jaggedness ») et parades

| Piège | Parade dans LawHack |
|---|---|
| Une option est toujours choisie (probas somment à 1) | Toujours inclure `INDETERMINE` ; ajouter un `noul` « l'arrêt contient-il la réponse ? » |
| Biais vers la première option | Si confiance < 0,8, reposer la question avec options mélangées et comparer |
| Lecture littérale | Critères explicites par option, cas limites dans `criteria` |
| Indirection / multi-sauts | Une question = un saut ; la chaîne de citation se construit en code |
| Pas de calcul ni de dates | Dates, comptages et comparaisons en code |
| Calibration non garantie hors distribution | Mesurer la calibration sur notre jeu labellisé (§8) |

### Exemple de requête

```python
from typesafe_sdk import Choice, Noul, TypeSafeClient

client = TypeSafeClient()  # lit TYPESAFE_API_KEY et TYPESAFE_BASE_URL

SPEAKERS = {
    "COUR_CASSATION": "The Cour de cassation states its own reasoning or ruling",
    "JURIDICTION_FOND": "The lower court's (cour d'appel) reasoning is being reported",
    "DEMANDEUR": "The appellant's argument is being reported",
    "DEFENDEUR": "The respondent's argument is being reported",
    "MINISTERE_PUBLIC": "The advocate general / public prosecutor speaks",
    "LOI": "A legal provision is quoted or relied upon",
    "INDETERMINE": "The speaker cannot be determined from the text",
}

r = client.system_one(
    {"zone": "motivations", "paragraph": 8,
     "sentences": {"S-017": "...", "S-018": "..."}},
    {
        f"speaker_{sid}": Choice(
            instructions=f"Who is the primary speaker of sentence `sentences.{sid}`?",
            criteria=SPEAKERS,
        )
        for sid in ["S-017", "S-018"]
    },
)
r.choices["speaker_S-017"].choice, r.choices["speaker_S-017"].confidence
```

Abstraction à implémenter pour rester indépendant du fournisseur :

```python
class SystemOneClient(Protocol):
    def decide(self, state: str | dict | list, questions: dict[str, dict]) -> SystemOneResult: ...
```

## 7. Système 2 et politique d'honnêteté

- **Modèle de réponse** : Mistral Medium 3.5 (repli : Mistral Large 3, moins cher).
- **Baseline du benchmark** : GPT-6 Astra seul (≈ 7× plus cher en entrée que Mistral Medium 3.5).
- Mistral reçoit **le registre + les extraits originaux** des segments récupérés, jamais le
  registre seul. Il cite par identifiants `[S-xx]`, convertis par le code en
  « §n, Zone » et en pastilles.

Politique d'honnêteté (seuils de départ, à calibrer sur le jeu labellisé) :

| Situation | Comportement |
|---|---|
| Confiance ≥ 0,8 | Réponse normale avec citation |
| 0,5 ≤ confiance < 0,8 | Réponse avec avertissement : « probablement la cour d'appel — à vérifier au §6 » |
| Point présent seulement dans les moyens | « La Cour ne tranche pas ce point ; c'est l'argument du demandeur (§n) » |
| `noul` « réponse présente » faible / aucun segment | « L'arrêt ne traite pas cette question. » |

On préfère **répondre avec un avertissement** plutôt que refuser : un outil qui refuse trop
est inutilisable, mais une erreur d'auteur non signalée est pire qu'un doute affiché.

## 8. Données et benchmark

### Apprentissage par retours

Les retours de l'avocat corrigent les locuteurs du registre et recalibrent localement le seuil
« ok » ; ils accumulent aussi des réponses validées pour constituer des jeux SFT/préférences et
d'attribution. Aucun réglage de modèle ni variable d'environnement supplémentaire n'est requis.
Exporter les jeux avec `python scripts/export_training.py --out data/feedback/export`.
Cette commande prépare les données ; le fine-tuning Mistral n'est pas exécuté.

**Données**

- [`antoinejeannot/jurisprudence`](https://huggingface.co/datasets/antoinejeannot/jurisprudence)
  (Hugging Face, Etalab 2.0) : ~553 000 décisions de la Cour de cassation issues de Judilibre,
  avec le champ `zones` (`introduction`, `expose`, `moyens`, `motivations`, `dispositif`,
  offsets `start`/`end` ; une zone peut avoir plusieurs fragments → trier par `start`).
- API Judilibre / PDF Légifrance pour les documents de démo.
- **Jeu labellisé de l'équipe** (attribution par phrase) : **réservé à l'évaluation**.
  Moitié pour calibrer les seuils, moitié pour publier les chiffres. Jamais dans les prompts.

**Métriques**

1. Précision d'attribution du locuteur (par segment), vs zones Judilibre et vs jeu labellisé.
2. Taux d'**hallucination d'attribution** dans les réponses (Astra seul vs Jev + Mistral).
3. Abstention correcte sur les questions pièges (question non traitée, point seulement allégué).
4. Calibration : courbe fiabilité confiance Jev vs exactitude (ECE).
5. Latence et coût par arrêt et par question.

**Questions pièges** (`bench/questions.jsonl`) : « Que décide la Cour sur X ? » quand X n'est
qu'un moyen ; « La faute grave est-elle établie ? » quand seule la cour d'appel l'a retenue ;
questions hors arrêt.

## 9. Stack technique et arborescence

- Python 3.11+, Pydantic v2, FastAPI, `typesafe-sdk`, `mistralai` (ou OpenRouter pour Mistral + Astra).
- PDF : `pymupdf4llm` (V2 scans : Mistral OCR).
- MCP (après le chat web) : `fastmcp`.
- UI : Streamlit pour aller vite, ou Next.js si le temps le permet.

Arborescence cible :

```text
LawHack/
├── pyproject.toml
├── .env.example
├── data/            # raw/, pdf/, gold/, cache/  (non versionné sauf échantillons)
├── lawhack/
│   ├── schema.py        # modèles Pydantic : Segment, RegistryEntry, Answer, Citation
│   ├── ingest.py        # PDF → texte + pages + paragraphes
│   ├── zoning.py        # règles de rubriques → zones
│   ├── segmenter.py     # paragraphes / phrases, ids S-xxx, offsets
│   ├── system_one.py    # SystemOneClient (Jev / Codiv)
│   ├── attributor.py    # questions Jev → registre
│   ├── registry.py      # construction, cache, requêtes
│   ├── retrieval.py     # BM25 + re-classement
│   ├── answer.py        # Mistral, citations [S-xx]
│   ├── verifier.py      # vérification phrase par phrase + abstention
│   └── llm.py           # client Mistral / Astra
├── bench/
│   ├── fetch_sample.py
│   ├── eval_attribution.py
│   ├── eval_qa.py
│   └── questions.jsonl
├── server/
│   ├── api.py           # FastAPI : /load, /ask, /verify
│   ├── mcp_server.py    # outils MCP (stdio + Streamable HTTP)
│   └── app.py           # /mcp + /api + /health, jeton LAWHACK_TOKEN
└── ui/                  # chat + pastilles + écran partagé démo
```

Outils MCP : `lawhack_load_decision`, `lawhack_who_said`, `lawhack_verify`, `lawhack_get_passage` (voir [docs/connecteur.md](docs/connecteur.md)).

## 10. Configuration et clés

Ne **jamais** committer de clé. Fichier `.env` local (copier `.env.example`) :

```bash
TYPESAFE_API_KEY=            # Jev (TypeSafe) ou clé Codiv
TYPESAFE_BASE_URL=           # vide = TypeSafe ; https://api.codiv.ai pour OpenJev
SYSTEM_ONE_MODEL=jev-latest  # ou openjev-latest
MISTRAL_API_KEY=
OPENROUTER_API_KEY=          # baseline Astra (openai/gpt-6-astra) et/ou Mistral
ANSWER_MODEL=mistral-medium-3-5
# REVISE_MODEL= (défaut : ANSWER_MODEL) ; ANSWER_CACHE=1 active le cache des réponses
BASELINE_MODEL=openai/gpt-6-astra
```

### Démarrage rapide

```bash
python3 -m pip install --user -U pip        # pip ≥ 21.3 requis pour l'installation éditable
python3 -m pip install --user -e ".[dev]"
cp .env.example .env                         # puis renseigner les clés
python -m pytest                             # tests hors-ligne (client Jev simulé)
python scripts/analyse.py data/samples/cass_civ3_2022-12-14_21-24539.pdf          # registre (Système 1)
python scripts/ask.py data/samples/cass_civ3_2022-12-14_21-24539.pdf "Que décide la Cour ?"   # réponse (Système 2)
```

Le registre est mis en cache dans `data/cache/<doc_id>.json` (`--no-cache` pour le recalculer).

## 11. Démo (≈ 3 minutes)

1. Le problème en une phrase + un exemple réel d'erreur d'attribution.
2. Dépôt du PDF d'un arrêt → animation de lecture (vitesse, coût).
3. Question piège en écran partagé : Astra attribue à la Cour l'argument du demandeur ;
   LawHack répond juste, avec pastilles et §.
4. Bouton « Vérifier » sur la réponse d'Astra → phrase en rouge.
5. Un « je ne sais pas » honnête de LawHack face à une invention d'Astra.
6. Le chiffre du benchmark : taux d'hallucination d'attribution Astra vs LawHack, coût, latence.

## 12. Feuille de route

**Hackathon (6–7 h)**

1. Squelette repo, schémas, ingestion PDF, zonage par règles.
2. Client Système 1 (Jev / Codiv) + attribution → registre.
3. Réponse Mistral citée + politique d'honnêteté.
4. UI chat avec pastilles ; écran partagé Astra.
5. Benchmark sur un échantillon d'arrêts + chiffres pour le pitch.

**Après**

- Vérificateur générique de textes rédigés par humain / Harvey / Astra.
- Serveur MCP branchable sur Le Chat, Claude, Legora, Harvey.
- Plusieurs arrêts par session ; dossiers longs non balisés (assignations, conclusions, pièces).
- Restitution des faits : chronologie acteur · action · date · source · statut · confiance.
- Hébergement UE (ex. eu/jev) pour la confidentialité des dossiers.

## 13. Organisation de l'équipe (3 personnes)

Chaque personne possède ses dossiers ; le contrat entre elles est le format du registre (`lawhack/schema.py`), figé tôt.

| Rôle | Périmètre | Dossiers |
|---|---|---|
| **1 · Système 1 & registre** | Zonage robuste (20 arrêts variés), segmentation, prompts Jev EN vs FR, calibration des seuils, bascule Jev ↔ OpenJev | `lawhack/zoning.py`, `segmenter.py`, `attributor.py`, `system_one.py` |
| **2 · Système 2 & produit** | Récupération, réponse Mistral citée `[S-xx]`, vérification Jev + abstention, chat, pastilles, animation | `lawhack/answer.py`, `verify.py`, `app/` |
| **3 · Juriste : données, benchmark, pitch** | Annotation avec la grille de rôles, questions pièges + réponses attendues, benchmark Astra vs LawHack, choix du cas réel, pitch | `eval/`, `data/` |

Synchronisations : (1) schéma du registre figé ; (2) test de bout en bout à mi-parcours sur le PDF de démo ; (3) gel du code 1 h avant la fin (corrections, répétition, chiffres).

### Grille de rôles (fournie par l'équipe)

| Rôle | Code | Où il parle |
|---|---|---|
| Cour d'appel (2nd degré) | `JURIDICTION_FOND` | Rapportée dans l'exposé, le moyen et la réponse (« l'arrêt retient », « la cour d'appel a relevé ») |
| Cour de cassation (juge du droit, pas des faits) | `COUR_CASSATION` | « Réponse de la Cour », « Par ces motifs, la Cour : » |
| Demandeur (conteste l'arrêt d'appel) | `DEMANDEUR` | « Énoncé du moyen », moyen annexé |
| Défendeur | `DEFENDEUR` | Fins de non-recevoir, pourvoi incident |

Plan type d'un arrêt : informations générales → parties → faits et procédure → « Énoncé du moyen » → « Réponse de la Cour » → « Par ces motifs, la Cour : ».
Marqueurs d'approbation (la Cour valide la cour d'appel → statut `DECIDE`) : « a retenu à bon droit », « en a exactement déduit », « le moyen n'est donc pas fondé ».
Solutions : `REJET`, `CASSATION`, `CASSATION_PARTIELLE`, `CASSATION_PARTIELLE_SANS_RENVOI`, `CASSATION_SANS_RENVOI` (détectées dans `lawhack/solution.py`).

## 14. Consignes pour les agents de code

Ce README est la **source de vérité** du produit. Avant de coder :

- **Respecter le pipeline du §4** et la séparation : règles/code → Jev (décisions typées) → Mistral (rédaction).
- **Ne pas demander à Jev de générer du texte** ni du JSON libre ; uniquement `noul` / `choice` / `score`.
- **Toujours propager** probabilités et confiance jusqu'à la réponse finale (pastilles).
- **Toujours inclure `INDETERMINE`** dans les choix de locuteur.
- Utiliser les **codes de l'ontologie du §5** tels quels ; ne pas en inventer sans mettre à jour ce README.
- Chaque affirmation de la réponse doit pointer vers un segment `S-xx` existant ; sinon, abstention.
- Le jeu labellisé ne sert **qu'à l'évaluation** ; ne jamais l'injecter dans les prompts.
- Aucune clé dans le code ou les commits ; lire la configuration depuis l'environnement.
- Passer par l'abstraction `SystemOneClient` pour pouvoir basculer Jev ↔ OpenJev.
- Ne pas promettre « zéro erreur » dans l'UI ou la documentation.
- Petites PR focalisées, avec tests (`pytest`) sur zonage, segmentation et politique d'honnêteté.

## 15. Références

- TypeSafe — [Introducing System One models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) · [Documentation](https://docs.typesafe.ai) · [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- Cookbooks TypeSafe utiles : [Double-checking citations](https://docs.typesafe.ai/cookbooks/citation_check), [Line-by-line search](https://docs.typesafe.ai/cookbooks/semantic_find), [Re-ranking (CLERC legal)](https://docs.typesafe.ai/cookbooks/rerank_typesafe), [Confidence-gated routing](https://docs.typesafe.ai/patterns/confidence-routing)
- OpenJev — [github.com/razorback16/openjev](https://github.com/razorback16/openjev) · [Codiv](https://codiv.ai/docs)
- Judilibre — [Cour-de-cassation/judilibre-search](https://github.com/Cour-de-cassation/judilibre-search)
- Dataset — [antoinejeannot/jurisprudence](https://huggingface.co/datasets/antoinejeannot/jurisprudence)
- PDF — [pymupdf4llm](https://pypi.org/project/pymupdf4llm/) · MCP — [fastmcp](https://github.com/jlowin/fastmcp)
