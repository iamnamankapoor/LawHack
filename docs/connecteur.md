# LawHack comme connecteur (MCP + REST)

Mode connecteur : c'est le LLM de la plateforme (Claude, ChatGPT, Le Chat, Legora…) qui rédige la réponse.
LawHack lui fournit **qui dit quoi** : les passages, leur locuteur, leur statut, la confiance et la citation.
Il vérifie aussi le brouillon avant envoi. La logique est écrite une seule fois, dans `lawhack/service.py`,
et deux façades l'exposent :

| Façade | Fichier | Clients |
|---|---|---|
| MCP (stdio + Streamable HTTP `/mcp`) | `server/mcp_server.py` | Claude (web, Desktop, Code), ChatGPT (mode développeur / Apps), Le Chat (connecteurs MCP), Legora, Cursor… |
| REST + OpenAPI (`/api`, doc `/api/docs`) | `server/api.py` | notre UI, GPT Actions, intégrations partenaires sans MCP |

## Outils

| Outil | Rôle |
|---|---|
| `lawhack_load_decision(text \| url \| pdf_base64 \| sample)` | Analyse l'arrêt et renvoie `decision_id`, la solution, les zones et le dispositif. À appeler une fois par arrêt. |
| `lawhack_read_decision(decision_id, zones?)` | Renvoie l'arrêt entier annoté, une ligne par phrase : `S-xx §n [locuteur · confiance] STATUT: texte`. Environ 9 000 caractères pour un arrêt type. |
| `lawhack_who_said(decision_id, question)` | Renvoie les passages pertinents avec leur locuteur, leur statut et leur confiance, ainsi que `answer_status` : `answered`, `only_alleged`, `not_decided_by_court` ou `not_in_decision`. |
| `lawhack_verify(decision_id, text)` | Vérifie un texte phrase par phrase. Une phrase qui cite `[S-xx]` ou `§n` est confrontée à ce segment précis. Verdicts possibles : `OK`, `A_VERIFIER`, `MAL_ATTRIBUE`, `NON_SOURCE` ou `SANS_ATTRIBUTION`. |
| `lawhack_get_passage(decision_id, segment_id)` | Renvoie le texte exact d'un passage et de ses voisins. |

Le serveur expose aussi le prompt `lawhack_answer` (la politique d'honnêteté) et la ressource `lawhack://samples`.
Tous les outils sont annotés en lecture seule. Ils sont sans état côté protocole : le `decision_id` est passé à
chaque appel, et le registre est mis en cache dans `data/cache/`.

Le registre est produit par Jev si `TYPESAFE_API_KEY` est définie. Sinon, un repli heuristique hors ligne
(`lawhack/heuristic.py`) prend le relais : les confiances y restent sous 0,8, si bien que toutes les réponses
s'affichent « à vérifier ». `heuristic_mode` le signale dans chaque résultat.

## Lancer

```bash
pip install -e ".[server]"
python -m server.mcp_server                       # stdio (Claude Desktop / Code)
LAWHACK_TOKEN=... uvicorn server.app:app --port 8000   # MCP sur /mcp + REST sur /api + /health
```

Pour Claude Code : `claude mcp add lawhack -- python -m server.mcp_server`.

## Brancher sur une plateforme

Les plateformes cloud appellent le serveur depuis leur propre infrastructure : il faut donc une URL HTTPS publique
(Railway, Fly.io, Cloud Run, ou un tunnel `cloudflared` pour une démo).

- **Claude** (Réglages → Connecteurs → Ajouter un connecteur personnalisé) : `https://<hôte>/mcp?key=<LAWHACK_TOKEN>`.
- **ChatGPT** (Réglages → Apps → Mode développeur → Créer) : la même URL, sans authentification.
- **Le Chat** (Intelligence → Connecteurs → MCP personnalisé) : `https://<hôte>/mcp`, avec l'authentification Bearer `<LAWHACK_TOKEN>`.
- **Legora** : connecteur MCP vers `https://<hôte>/mcp` avec Bearer. Legora peut transférer les fichiers, d'où `pdf_base64`.
- **Harvey et autres** : API REST, OpenAPI sur `/api/openapi.json`.

Le jeton partagé suffit pour le hackathon. Pour une publication dans les annuaires officiels de Claude et de ChatGPT,
ou pour un usage multi-cabinets, il faudra passer à OAuth 2.1 (FastMCP le gère via un fournisseur d'identité).

## Choix vérifiés

- **MCP distant en Streamable HTTP** : c'est le transport commun aux connecteurs personnalisés de Claude, au mode
  développeur de ChatGPT, aux connecteurs MCP de Le Chat et à Legora, qui annonce se brancher sur tout serveur MCP.
- **Accepter du texte, une URL ou un PDF en base64** : les plateformes ne transmettent généralement pas au serveur
  le PDF déposé dans la conversation. Le LLM peut en revanche coller le texte ou fournir une URL.
- **Ne pas faire doublon avec les serveurs Légifrance ou Judilibre existants** (par ex. `mcp-server-legifrance`) :
  ils servent à *trouver* les textes, alors que LawHack dit *qui parle* dans un arrêt. Les deux se combinent dans un
  même client.

## Attribution : règles d'abord, Jev ensuite

La rédaction des arrêts de la Cour de cassation est très codifiée (motivation enrichie). Les formules sûres sont donc
traitées par des règles, sans appel au modèle :
- **Énoncé du moyen** : demandeur, argument allégué.
- **Faits et procédure** : cour d'appel, avec un a priori de 0,9 ; Jev ne tranche que le type et le statut.
- **« Pour …, l'arrêt retient »** : cour d'appel.
- **« En statuant ainsi »**, **« Le moyen n'est pas fondé »**, **« Après avis donné aux parties »** : Cour de cassation.

Une phrase anaphorique (« Il en déduit… ») reprend la voix de la phrase précédente. Jev ne reçoit que le reste, par lots
de 6 phrases consécutives d'une même zone, ce qui lui donne plus de contexte en moins d'appels.

Le registre porte un numéro de `version` : un registre en cache est recalculé quand les règles changent, ou quand Jev
devient disponible après un passage en mode heuristique.

`python scripts/eval_attribution.py` mesure la précision (locuteur et chaîne), le nombre d'appels et les tokens
sur le jeu labellisé `eval/gold_speakers.json`.

| | Avant | Après |
|---|---|---|
| Précision sur le jeu labellisé (31 étiquettes, test de régression) | 87 % | 100 % |
| Appels Jev (2 arrêts) | 31 | 7 |
| Tokens en entrée (2 arrêts) | 19 800 | 7 300 |

Sur 12 arrêts récents non étiquetés (toutes chambres, jeu `antoinejeannot/jurisprudence`), on observe
2 à 6 appels et 2 300 à 6 700 tokens par arrêt. Sur ces 12 arrêts, le zonage concorde à 100 % avec les zones Judilibre ; à grande échelle (147 arrêts test), il est de 97,3 % (voir README, § Résultats).

## Sécurité

- Le chargement par URL refuse les hôtes privés, la boucle locale et les métadonnées cloud, y compris après une redirection
  (protection SSRF). `LAWHACK_ALLOW_PRIVATE_URLS=1` lève cette restriction en développement.
- Le texte est limité à 400 000 caractères et le téléchargement à 15 Mo.
- L'analyse PDF et le téléchargement s'exécutent hors de la boucle d'événements.
- Deux chargements simultanés du même arrêt ne paient Jev qu'une fois.
