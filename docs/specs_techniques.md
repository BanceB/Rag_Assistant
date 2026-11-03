# Spécifications techniques : agent RAG COCOACERT

> Statut : **décisions D1 à D4 et D6 prises le 26 octobre 2026 (D7 et D8 le 1er novembre, D9 et D10 le 2 novembre, D11 le 3 novembre), à présenter au directeur de mémoire.** D5 reste provisoire jusqu'aux mesures de l'étape 11.
> Tarifs et limites relevés le 26 octobre 2026 (sources en fin de document).

## 1. Architecture retenue

Deux circuits, qui partagent le même modèle d'embedding :

1. **Indexation (hors ligne).** Documents → chargement → découpage → embeddings → base vectorielle.
2. **Question (en ligne).** Question → reformulation si besoin → embedding → recherche + reranking → garde-fou → prompt augmenté → LLM → réponse + sources.

Tous les réglages sont centralisés dans `config/settings.yaml` ; les secrets dans `.env`.

## 2. Périmètre fonctionnel

> **À valider avec le directeur de mémoire** (jalon « fin de cadrage » ; priorisation demandée au §6 du cahier des charges).

**Mission.** L'agent répond en français, par écrit, aux acteurs de la filière cacao (agriculteurs, coopératives, techniciens, certificateurs), sur cinq thèmes : maladies et ravageurs, EUDR, certification, bonnes pratiques agricoles, indicateurs de durabilité. Chaque réponse s'appuie uniquement sur le corpus documentaire validé.

### 2.1 Types de demandes traitées

| Type (`type_demande`) | Exemple | Comportement attendu |
| --- | --- | --- |
| `expliquer` | « C'est quoi la diligence raisonnable ? » | Définition simple, avec un exemple concret |
| `reconnaitre` | « Mes feuilles ont des bandes rouges le long des nervures » | Causes possibles d'après les fiches ; conseil de faire confirmer par un technicien ; jamais de diagnostic définitif |
| `guider` | « Comment faire du compost avec les cabosses ? » | Étapes numérotées |
| `lister` | « Quels documents pour être certifié ? » | Liste claire ; date de la source quand la règle évolue |
| `comparer` | « ARS 1000 ou Rainforest Alliance ? » | Différences essentielles en quelques points |
| `interpreter` | « Mon score biodiversité est faible » | Ce que mesure l'indicateur et ce qui peut l'améliorer |
| `poursuivre` | « Et pour une parcelle de 6 hectares ? » | Question comprise grâce à l'historique de la conversation |

### 2.2 Contrat de réponse

Chaque réponse est :

- **ancrée** : aucune information extérieure au corpus ;
- **sourcée** : liste des sources en fin de réponse (titre, page, lien) ;
- **simple** : phrases courtes, mots courants, termes techniques expliqués ;
- **courte** : quelques phrases, plus des étapes si nécessaire (lecture sur téléphone, bas débit) ;
- **prudente** : avertissement de non-substitution sur les sujets sensibles (pesticides, conformité, certification) ;
- **transparente** : l'utilisateur est informé qu'il échange avec une IA.

### 2.3 Situations particulières (`situation`)

| Situation | Exemple | Comportement attendu |
| --- | --- | --- |
| `hors_sujet` | « Qui a gagné la CAN ? » | Refus poli et rappel de ce que l'agent sait faire |
| `absent_du_corpus` | « Combien coûte un audit Rainforest Alliance ? » | « Je n'ai pas cette information dans mes documents », puis orientation (technicien, ANADER, coopérative) |
| `demande_de_decision` | « Mon cacao est-il conforme à l'EUDR ? » | Explication des critères, sans verdict, et orientation vers l'organisme compétent |

### 2.4 Hors périmètre

- Diagnostic à partir de photos (module dédié de COCOACERT).
- Décision de conformité ou de certification.
- Dosage de pesticides au-delà des fiches officielles (et toujours avec avertissement).
- Prévisions : prix, météo, récoltes.
- Accès aux données personnelles de l'exploitation (passeport numérique) : perspective d'intégration.
- Langues locales : perspective.
- Actions à la place de l'utilisateur (remplir une déclaration, par exemple).

### 2.5 Priorités (MoSCoW)

| Priorité | Fonctions |
| --- | --- |
| **Indispensable** (Must) | F1 interface web, F2 recherche, F3 génération, F4 sources, F5 garde-fous, F6 mémoire de conversation, F9 journalisation (nécessaire pour mesurer les indicateurs du §11) |
| **Important** (Should) | F7 administration du corpus, F8 cache et mode dégradé, reranking, réponses en streaming |
| **Bonus** (Could) | Canal WhatsApp (§4.1), suggestions de questions, filtre par thème |
| **Pas cette fois** (Won't) | Diagnostic par image, langues locales, connexion aux données réelles de COCOACERT, déploiement à grande échelle |

### 2.6 Vérification

Le jeu `eval/questions.jsonl` contient 297 questions : 156 posées par des agriculteurs, 42 par des techniciens, 43 par des coopératives, 29 par des étudiants ou chercheurs et 27 par d'autres parties prenantes (ONG, exportateurs, chocolatiers, bailleurs). 256 sont des questions normales (dont 14 conversations suivies et 11 comparaisons, dont plusieurs entre documents qui ne donnent pas les mêmes chiffres), 13 des demandes de décision, 14 portent sur une information absente du corpus et 14 sont hors sujet. Chaque question normale porte une réponse attendue et au moins une preuve (document, page, extrait mot pour mot) vérifiée automatiquement dans le texte des PDF ; `doc_ids_attendus` en découle et sert à mesurer le rappel de la recherche. Quand plusieurs documents donnent la même réponse, chacun est cité (67 questions ont plusieurs documents attendus ; 8 d'entre elles ont été complétées le 2 novembre 2026, voir D9) : retrouver l'un d'eux compte comme un succès. Les questions « absentes » ont été contrôlées par recherche dans tout le corpus PDF. Les 46 documents chargés sont tous cités, dont les 5 pages web capturées en PDF le 1er novembre 2026 ; 5 autres pages web ont été exclues. Le jeu a été généré par Claude à partir du corpus et doit être relu par l'étudiant. Le test `tests/test_questions.py` vérifie automatiquement la forme, la couverture et la cohérence avec le catalogue. Les cibles chiffrées sont celles du §11 : au moins 90 % de réponses sourcées, au moins 90 % des questions hors corpus détectées, 5 s maximum, au moins 80 % de pertinence perçue.

## 3. Décisions

### D1. Chaîne RAG plutôt qu'agent — **décidé**

| Critère | Chaîne (recherche systématique) | Agent (le LLM choisit d'appeler l'outil) |
| --- | --- | --- |
| Ancrage sur le corpus | Garanti : on cherche toujours | Non garanti : le LLM peut répondre sans chercher |
| Appels au LLM par question | 1 | 2 ou plus |
| Temps de réponse | Plus court | Plus long |
| Évaluation | Reproductible | Variable d'une exécution à l'autre |

Un assistant de conformité doit toujours s'appuyer sur ses sources : la chaîne répond directement à F5 et à la cible de 90 % de réponses sourcées.

### D2. Modèle de langage — **décidé**

| Option | Prix (USD / million de tokens, entrée / sortie) | Coût estimé par question* | Remarque |
| --- | --- | --- | --- |
| Claude Sonnet 5.5 | 2 / 10 | ≈ 0,011 $ | Très bonne rédaction en français |
| Claude Haiku 5.5 | 0,10 / 0,50 | ≈ 0,0006 $ | Rapide et très peu coûteux |
| Modèle open source auto-hébergé (Mistral, Llama…) | Matériel | — | Souveraineté maximale, mais GPU nécessaire et réponses plus lentes |

\* Hypothèse : 3 000 tokens en entrée (consignes + 4 passages + question), 500 en sortie.

**Décision :** Sonnet 5.5 pour rédiger les réponses, Haiku 5.5 pour reformuler les questions de suivi. Comparer Sonnet et Haiku en génération à l'étape 11 (qualité, latence < 5 s). Mentionner l'auto-hébergement comme perspective de souveraineté.

### D3. Modèle d'embedding — **décidé**

| Option | Prix | Dimension | Multilingue | Remarque |
| --- | --- | --- | --- | --- |
| `voyage-4-lite` (actuel) | 0,02 $ / M tokens, 200 M offerts | 1024 | Non précisé par l'éditeur | Optimisé coût et latence |
| `voyage-4` | 0,06 $ / M tokens, 200 M offerts | 1024 | Oui (annoncé) | Meilleure qualité annoncée en multilingue |
| `bge-m3` (open source, local) | Gratuit | 1024 | Oui | Tourne sur la machine, plus lent sans GPU |

Ordre de grandeur : 100 documents d'environ 20 pages font à peu près 1,2 million de tokens, donc bien moins que les 200 millions offerts.

**Point bloquant levé le 1er novembre 2026 :** le compte gratuit est bridé à 10 000 tokens et 3 requêtes par minute, ce qui rend les tests utilisateurs impossibles. Enregistrer une carte ne suffit pas : Voyage active le palier 1 après un **premier achat de crédit** (au moins 5 $, sans recharge automatique). Le compte est depuis au palier 1 : 8 millions de tokens et 2 000 requêtes par minute pour voyage-4. Une indexation complète (environ 1 million de tokens) reste couverte par les tokens offerts.

**Décision :** `voyage-4` pour son caractère multilingue annoncé, avec un moyen de paiement enregistré. Le reranker est choisi par la mesure de l'étape 6 (D9).

### D4. Base vectorielle — **décidé**

| Critère | Pinecone (Starter, gratuit) | Chroma (local) |
| --- | --- | --- |
| Coût | 0 $ (jusqu'à 2 Go, 5 index) | 0 $ |
| Où sont les données | AWS us-east-1 (États-Unis) | Sur ton PC ou le serveur du LASTIC |
| Fonctionne sans Internet | Non | Oui (seule la recherche ; le LLM reste en ligne) |
| Mise en place | Déjà fonctionnelle dans le projet | Ajoutée le 26 octobre (`langchain-chroma`) |
| Taille adaptée au corpus (~quelques milliers de chunks) | Oui | Oui |
| Cohérence avec le cahier (§7.2 hébergement, §7.3 FAISS / Chroma / Milvus) | À justifier | Directe |

**Décision :** Chroma, pour la souveraineté des données, le coût nul et l'hébergement possible au LASTIC. Le code passera par `settings.vectorstore.provider`, afin de basculer d'une base à l'autre en changeant une ligne de configuration. Les données Chroma sont stockées dans `data/chroma/`, non versionné : on les reconstruit à partir du corpus avec le pipeline d'ingestion.

### D5. Découpage — **provisoire (réglage), décidé (méthode)**

Méthode (`ingestion/chunking.py`) : `RecursiveCharacterTextSplitter` appliqué page par page (un chunk ne chevauche jamais deux pages, pour citer « document, p. 12 »). Dans les règlements, coupure préalable à chaque « Article N ». Les morceaux de moins de 100 caractères (intertitre seul, légende) sont rattachés à leur voisin. Chaque chunk commence par un en-tête contextuel (titre, organisme, année, section) et porte `section`, `chunk_index` et un identifiant stable `chunk_id` (`MAL-001-p003-c01`). Les lignes de sommaire (points de suite et numéro de page) sont retirées au chargement.

Mesure du 2 novembre 2026 sur le corpus (46 documents, 1 399 pages avec texte), refaite après le repérage typographique des intertitres, l'abrègement des en-têtes et le retrait des en-têtes de l'ARS 1000 : « preuves intactes » = part des 487 extraits de preuve du jeu d'évaluation contenus en entier dans un même chunk ; tokens estimés à 4 caractères par token, en-têtes compris.

| Réglage (caractères) | Chunks | Taille moyenne | Chunks < 100 car. | Tokens estimés | Preuves intactes |
| --- | --- | --- | --- | --- | --- |
| 500 / 50 | 9 420 | 355 | 31 | 1,22 M | 99,8 % |
| 1000 / 150 | 4 843 | 708 | 21 | 1,05 M | 100 % |
| 2000 / 200 | 2 588 | 1 308 | 20 | 0,95 M | 100 % |

Coût de vectorisation avec `voyage-4` : environ 1 million de tokens par indexation complète, soit quelques centimes, très en dessous des 200 millions offerts. Le critère de coût ne départage donc pas les réglages.

**Décision :** 2000 / 200 reste le réglage par défaut (`settings.yaml`). Les trois réglages préservent les preuves ; le choix final se fera à l'étape 11 sur la qualité de la recherche (rappel@k) et des réponses, en indexant les trois.

### D6. Interface — **décidé**

Streamlit : Python uniquement, composants de chat natifs, application multipage pour l'administration, léger côté navigateur.

### D7. Lecture des documents (ingestion) — **décidé**

Mesure du 31 octobre 2026 sur le corpus validé (41 PDF, 1 311 pages) : pour chaque lecteur, on vérifie que les 447 extraits cités en preuve dans `eval/questions.jsonl` se retrouvent dans le texte lu à la bonne page.

| Lecteur | Licence | Temps de lecture | Extraits retrouvés |
| --- | --- | --- | --- |
| PyMuPDF 1.28 | AGPL-3.0 | 2,7 s | 447 / 447 |
| pypdf 6.2 | BSD | 27,8 s | 426 / 447 |

**Décision :** PyMuPDF, appelé directement (sans `langchain-community`, inutile pour un seul format). Version limitée à la branche 1.x (`>=1.26,<2`) : la 2.0, sortie le 19 octobre 2026, est trop récente et ajoute trois dépendances. La licence AGPL impose de publier le code si l'agent est proposé comme service en ligne ; c'est le cas d'un dépôt de mémoire public. Une licence commerciale existe sinon.

Règles de chargement (`ingestion/loaders.py`) :

- un `Document` par page, avec le numéro de page du PDF (celui des preuves) et les métadonnées du catalogue (`doc_id`, titre, organisme, thème, date, langue, licence, lien) ;
- seuls les documents au statut `valide` et ayant un fichier sont chargés. Les pages web sont lues à partir d'une copie PDF datée rangée dans `data/corpus/`, pour que le texte indexé ne change pas d'une semaine à l'autre ; il n'y a donc pas de lecteur web ni Word ;
- nettoyage : mots coupés en fin de ligne recollés, lignes d'un même paragraphe réunies, en-têtes et pieds de page répétés retirés, numéros de page seuls retirés. Les intitulés d'articles et de sections sont toujours conservés ;
- une page web enregistrée avec l'imprimante « Microsoft Print to PDF » ne contient aucun texte (les lettres deviennent des dessins) : il faut choisir « Enregistrer au format PDF » dans le navigateur. Pour les captures du 1er novembre 2026, deux méthodes de rattrapage ont été utilisées. EUDR-003 et EUDR-009 (pages en français, bien lisibles) ont reçu une couche de texte par OCR (Tesseract 5, 300 ppp), sans changer leur aspect. EUDR-007, CERT-003 et IND-005 étaient en partie traduites par le navigateur ou contenaient un tableau mal lu par l'OCR : elles ont été remplacées par une copie texte de la page d'origine, en anglais, relevée dans le navigateur intégré et vérifiée par empreinte (SHA-256) contre la page ; les images et graphiques ne sont pas repris ;
- intertitres (ajout du 1er novembre 2026, après les premières recherches de l'étape 5) : une ligne en gras ou plus grande d'au moins 1,5 point que le texte courant est un intertitre si elle ouvre un bloc, ou si elle est numérotée au milieu d'un bloc (« 13 Exigences de traçabilité », « 13.1 Exigences générales »), et si elle ressemble à un titre (pas de point final, pas une légende, un crédit photo, une adresse, une ligne de sommaire ou un mot en capitales non numéroté) et ne revient pas plus de deux fois dans le document (sinon c'est un en-tête de tableau). Les titres des signets du PDF comptent aussi. Pour les pages passées à l'OCR, sans typographie fiable, le découpage se replie sur la numérotation (« 3.10. Qui est une PME »). Avant ce changement, une ligne de tableau numérotée (« 16. Application d'engrais Entretien ») servait de section à 95 chunks de l'ARS 1000 ; la section de chaque chunk suit maintenant les vrais titres (« 11 Principes de traçabilité ») : c'est le premier intertitre de la première moitié du chunk, sinon la section en cours à son début ;
- en-têtes et pieds de page : un bloc est retiré s'il revient dans la marge haute ou basse d'au moins un quart des pages (et non la moitié : l'ARS 1000 réunit trois parties qui ont chacune leur en-tête « ARS 1000-1:2021 ») ; une mention « © … » en marge est toujours retirée ;
- les puces des polices Symbol et Wingdings (caractères à usage privé) deviennent « • » ;
- les pages de moins de 30 caractères (couvertures, photos) sont ignorées : 27 pages sur 1 311 ;
- un fichier illisible est noté dans le rapport sans arrêter le chargement.

Avec le repérage des intertitres, la lecture complète du corpus prend une dizaine de secondes au lieu de 3 : PyMuPDF renvoie alors la police et la taille de chaque ligne.

Le test `test_le_texte_charge_contient_toutes_les_preuves` relance la vérification de tous les extraits (499 au 2 novembre 2026) à chaque `uv run pytest`, quand les PDF sont présents : un nettoyage trop agressif est détecté tout de suite.

### D8. Vectorisation et indexation — **décidé**

Code : `ingestion/indexer.py` ; commande : `uv run python -m rag_assistant.ingestion.pipeline`.

- **Une collection par filière, modèle et réglage de découpage**, par exemple `cacao_voyage-4_2000-200`. Les trois réglages de D5 peuvent ainsi coexister dans `data/chroma/` pour la comparaison de l'étape 11, et un changement de modèle d'embedding ne mélange jamais des vecteurs incompatibles.
- **Distance cosinus** (`hnsw:space = cosine`) : le score de similarité va de 0 à 1 et servira de seuil de pertinence à l'étape 6. Les vecteurs voyage-4 font 1 024 dimensions.
- **Indexation incrémentale et idempotente** : chaque chunk est rangé sous son `chunk_id` stable et porte l'empreinte SHA-1 de son texte. Une relance compare les empreintes : seuls les chunks nouveaux ou modifiés sont envoyés à Voyage, ceux qui ont disparu du corpus sont retirés. Relancer sans rien changer ne coûte rien et ne crée aucun doublon.
- **Envoi par lots de 64 chunks** (environ 30 000 tokens) et **nouvel essai** après 2, 4, 8, 16 puis 32 s en cas de quota dépassé ou de coupure réseau (backoff exponentiel).
- **En-tête contextuel court** : titre abrégé à 100 caractères et organisme à 40 (« ORAN / ARSO » plutôt que l'intitulé complet), pour que l'en-tête ne pèse pas plus que le passage dans le vecteur ; le catalogue garde les intitulés complets pour la citation.
- **Suppression d'un document** : `--supprimer DOC_ID` retire tous ses chunks (préparation de la page d'administration, F7).
- Télémétrie anonyme de Chroma désactivée : la base reste entièrement sur le poste.

Volume au réglage 2000/200 : 46 documents, 2 588 chunks, 3,9 millions de caractères, soit environ un million de tokens, vectorisés en une quarantaine de lots.

Vérification : `tests/test_indexer.py` (faux modèle d'embedding, sans réseau) contrôle l'absence de doublons, la mise à jour d'un chunk modifié, le retrait d'un chunk disparu, la suppression d'un document, la reprise après un quota dépassé et, quand les PDF sont présents, l'idempotence sur tout le corpus.

### D9. Recherche, reranking et seuil — **décidé**

Code : `rag/retriever.py` ; mesure : `uv run python -m rag_assistant.evaluation.recherche` (résultats bruts et résumé dans `eval/resultats/recherche_2026-11-02*`).

Méthode : recherche vectorielle des 20 chunks les plus proches (similarité cosinus), puis reranking des 20 par un modèle Voyage, qui relit la question avec chaque candidat ; on garde les 4 meilleurs. Si le meilleur score du reranker est sous le seuil, aucun passage n'est jugé pertinent (garde-fou, étape 7). Un filtre de métadonnées (thème, langue) est possible.

Mesure du 2 novembre 2026 sur les 297 questions (269 avec une réponse dans le corpus, 14 hors sujet, 14 absentes du corpus), réglage 2000/200. Rappel@k = part des questions dont un document attendu figure dans les k premiers passages ; MRR = moyenne de 1/rang du premier bon passage.

| Méthode | Rappel@1 | Rappel@4 | MRR@4 | Rappel@20 | Temps moyen (p95) |
| --- | --- | --- | --- | --- | --- |
| Vectorielle seule | 74,3 % | 91,4 % | 0,814 | 97,4 % | 0,46 s (0,62 s) |
| + rerank-2.5 | 81,0 % | **95,9 %** | 0,876 | 97,4 % | 0,95 s (1,43 s) |
| + rerank-3 | 81,0 % | 95,2 % | 0,868 | 97,4 % | 0,94 s (1,34 s) |

Chiffres calculés avec le jeu d'évaluation complété (voir plus bas). Avec le jeu d'origine, le rappel@4 était de 89,6 % (vectorielle), 92,9 % (rerank-2.5) et 92,6 % (rerank-3) : l'écart entre méthodes et le choix ne changent pas.

Complément du jeu d'évaluation : sur les 19 questions d'abord manquées, 8 avaient reçu un passage d'un autre document qui donne bien la réponse (par exemple la FAQ de la Commission pour la date d'application de l'EUDR, ou le manuel du technicien pour le foreur de tiges). Après relecture, ces documents ont été ajoutés avec un extrait vérifié mot pour mot (12 preuves, module `q_alternatives_etape6`). Les 11 échecs restants sont présentés tels quels :

- 3 suites de conversation (« Et c'est qui qui la paie ? ») : la question seule ne suffit pas ; la reformulation avec l'historique (étape 8) doit les résoudre ;
- 6 questions EUDR ou certification où un document voisin passe devant : FAQ de la Commission plutôt que le règlement ou le document d'orientation, pages en anglais (Trase, WCF) placées en tête pour des questions françaises sur l'aide de l'UE ou la décision d'achat ;
- 2 questions agronomiques où le guide général renvoie à une fiche spécialisée sans en donner le contenu (replantation après swollen shoot).

Le reranking gagne 4,5 points de rappel@4 et 6,7 points de rappel@1 pour environ 0,5 s de plus. Au-delà de k = 3, le rappel ne progresse presque plus (95,5 % à k = 3, 95,9 % de k = 4 à 6) : k = 4 est conservé.

Seuil sur le score du reranker : les 14 questions hors sujet ont un meilleur score entre 0,26 et 0,39 ; parmi les 269 questions avec réponse, deux seulement sont sous 0,45 (une demande de décision à 0,38 et une suite de conversation à 0,45), toutes les autres sont au-dessus de 0,53.

| Seuil | Hors sujet écartées | Absentes écartées | Questions avec réponse rejetées |
| --- | --- | --- | --- |
| 0,38 | 13 / 14 | 1 / 14 | 0 |
| **0,40** | **14 / 14** | 1 / 14 | 1 (0,4 %) |
| 0,45 | 14 / 14 | 4 / 14 | 2 (0,7 %) |

Les questions « absentes du corpus » portent sur le sujet (le cacao, l'EUDR) sans que la réponse figure dans les documents : les passages retrouvés sont proches et le seuil ne les écarte pas. C'est le rôle du garde-fou de l'étape 7 (le modèle de langage vérifie que les passages contiennent la réponse) ; la cible du cahier (au moins 90 % des questions hors corpus détectées) se mesurera sur la chaîne complète, à l'étape 11.

**Décision :** reranker `rerank-2.5` et seuil 0,40 (`settings.yaml`). `rerank-3`, sorti fin septembre 2026 et recommandé par Voyage, fait jeu égal (écart de 2 questions sur 269, non significatif) au même prix (0,05 $ par million de tokens) : il reste l'alternative si `rerank-2.5` est retiré. La recherche hybride avec mots-clés (BM25) n'est pas ajoutée : aucun des 11 échecs ne tient à un sigle ou à un numéro d'article ; la question sera rouverte si l'évaluation de l'étape 11 le montre. Le seuil, fixé sur 14 questions hors sujet seulement, sera revérifié à l'étape 11 avec les questions des testeurs.

Temps : la recherche complète prend 0,95 s en moyenne (1,43 s au 95e centile), ce qui laisse environ 3,5 s à la génération pour tenir les 5 s du cahier des charges.

### D10. Génération et garde-fous — **décidé (réglages à confirmer à l'étape 11)**

Code : `rag/prompts.py` (consignes), `rag/guardrails.py` (garde-fous), `rag/chain.py` (chaîne) ; essai : `uv run python -m rag_assistant.evaluation.reponses` (résultats dans `eval/resultats/reponses_2026-11-02*`).

Chaîne : recherche et reranking (D9) → refus immédiat si le meilleur score est sous 0,40 → un seul appel à Claude Sonnet 5.5 avec les 4 passages numérotés [1]…[4] (titre, organisme, année, page, section) → vérification des citations → réponse, avertissements et sources.

Garde-fous en trois couches :

1. **Avant le modèle** : sous le seuil, refus type sans appel à Claude (gratuit, immédiat).
2. **Dans le prompt** : ancrage strict (aucune information extérieure aux passages, aucun produit ni dose absent des passages), citation [n] après chaque phrase, pas de décision à la place de la personne. Le modèle écrit `HORS_SUJET` ou `AUCUNE_REPONSE` quand il n'y a rien à dire ; quand l'information principale manque mais que les passages s'en approchent, la réponse commence par « Les documents ne précisent pas… », puis donne ce qui s'en approche et oriente la personne. Une dernière ligne d'étiquettes (`couverture`, `avertissement`), lue puis retirée par le code, indique la couverture et le sujet sensible.
3. **Après le modèle** : les numéros cités qui ne correspondent à aucun passage sont retirés ; une réponse sans citation valide est remplacée par le refus type. La liste des sources est construite par le code à partir des numéros cités (deux passages de la même page deviennent une seule source) : elle ne peut pas être inventée.

Avertissements de non-substitution (§13 du cahier) : traitement par un produit, conformité EUDR, certification, demande de décision. Le sujet est choisi par le modèle, qui comprend le sens de la question ; un produit chimique cité dans la réponse déclenche toujours l'avertissement « traitement ».

Réglages : Claude 5.5 refuse le paramètre `temperature` (erreur 400). La profondeur de réflexion se règle avec `effort` : `low`, sans réflexion préalable (`thinking: between_tools`). Réponse de 100 mots au plus, reçue en flux pour afficher les premiers mots sans attendre la fin.

Essai du 2 novembre 2026 sur 71 questions (14 hors sujet, 14 absentes du corpus, 13 demandes de décision, 30 normales réparties entre les 5 thèmes ; profil = acteur de la question), en trois versions du prompt :

| Mesure | V1 | V3 (retenue) |
| --- | --- | --- |
| Hors sujet refusées | 14 / 14 | 14 / 14 |
| Absentes du corpus détectées (refus ou réponse « Les documents ne précisent pas… ») | 10 / 14 | 14 / 14 |
| Questions avec réponse refusées à tort | 1 / 43 | 1 / 43 |
| Réponses avec au moins une source | 100 % | 100 % |
| … dont une source attendue | 95 % | 95 % |
| Réponses signalées partielles alors que la réponse est dans le corpus | — | 1 / 42 |
| Avertissement présent quand il est attendu | 57 % | 86 % |
| Avertissement non attendu | 50 % | 21 % |
| Longueur médiane | 218 mots | 120 mots |
| Temps total médian (moyenne ; 95e centile) | 5,55 s (7,5 ; —) | 4,15 s (4,38 ; 5,99) |
| Délai avant le premier mot (médiane) | — | 1,98 s |
| Coût pour 71 questions | 0,67 $ | 0,66 $ |

V1 : premier prompt (réponses de 3 à 6 phrases, avertissements par mots-clés). V2, écartée : étiquettes ajoutées, mais le modèle marquait « partielle » 48 % des réponses complètes dès qu'un détail manquait, ce qui rendait la détection des questions absentes trop facile ; d'où la règle de V3 : une réponse n'est partielle que si elle est étiquetée ainsi **et** commence par « Les documents ne précisent pas ». V3 : limite à 100 mots, recherche plus rapide (la question n'est plus découpée en tokens avant l'envoi à Voyage, ce qui rechargeait à chaque fois le découpage depuis Hugging Face).

Lecture des résultats :

- les 12 questions absentes du corpus qui ne sont pas refusées reçoivent une réponse qui dit d'emblée que l'information manque (prix du jour, adresse, date à venir…), puis donne ce que disent les documents et oriente la personne : c'est le comportement prévu au §2.3, qui reste plus utile qu'un refus sec ;
- la seule question refusée à tort (« Dois-je quitter ma coopérative pour une autre qui paie une meilleure prime ? ») est une demande de décision dont le meilleur score est 0,38, juste sous le seuil ;
- 12 réponses sur 54 dépassent 5 s, surtout à cause de la rédaction (3,1 s en médiane) et de pics du réseau pendant la recherche. Avec l'affichage en flux de l'étape 9, la personne lit les premiers mots après 2 s environ. Leviers à mesurer à l'étape 11 : Claude Haiku 5.5 pour la rédaction, réponses plus courtes ;
- les avertissements « en trop » portent surtout sur des questions de certification ou d'EUDR où un rappel reste défendable ; ils sont à juger par les relecteurs.

Relecture humaine : 10 réponses sont rassemblées dans `eval/resultats/reponses_2026-11-02_16h34_a_relire.md`, avec une grille (compris, utile, longueur, mots difficiles), à faire lire par une personne non spécialiste.

### D11. Mémoire de conversation — **décidé**

Code : `rag/memory.py` (mémoire et reformulation), `Conversation` dans `rag/chain.py` ; mesure : `uv run python -m rag_assistant.evaluation.memoire` (résultats dans `eval/resultats/memoire_2026-11-03*`).

- **Mémoire par session**, en fenêtre glissante : les 6 derniers messages (`memoire.fenetre_messages`), en mémoire vive seulement (1 000 sessions au plus). Sa conservation dans le journal relève de l'étape 10 (données personnelles).
- **Reformulation des questions de suivi** par Claude Haiku 5.5 (effort `low`, sans réflexion), seulement quand il y a un historique : « Et c'est qui qui la paie ? » devient « Qui paie la prime pour le cacao certifié ARS 1000 ? ». La question reformulée sert à la recherche ; le modèle qui rédige reçoit l'historique court (citations retirées) et la question telle que la personne l'a posée, avec sa reformulation. Garde-fou : une réécriture vide ou démesurée est ignorée.

Mesure du 3 novembre 2026 sur les 14 questions de suivi du jeu d'évaluation, comparées à la même question rédigée en entier à la main (`eval/dialogues.json`) :

| Question utilisée pour la recherche | Rappel@4 | Passages communs avec la question complète |
| --- | --- | --- |
| Question seule (sans mémoire) | 79 % | 54 % |
| Reformulée, premier prompt | 79 % | 77 % |
| **Reformulée, prompt retenu** | **100 %** | **86 %** |
| Posée en entier (référence) | 100 % | — |

Le premier prompt perdait le sujet (« Et si ma parcelle fait plus de 4 hectares ? » restait sans l'EUDR ni les coordonnées GPS, et gagnait « en Côte d'Ivoire », absent de la conversation). Le prompt retenu demande de nommer le sujet, de reprendre les précisions utiles, de ne rien ajouter, avec trois exemples sans lien avec les questions mesurées. Pour une question (« Et ça commence quand ? »), la FAQ de la Commission a été ajoutée aux documents attendus, comme à l'étape 6 pour la question semblable (1 preuve, module `q_alternatives_etape8`).

Ce test ne donne au modèle que les questions précédentes, sans les réponses de l'assistant. Dans l'usage réel, les réponses sont aussi dans l'historique : les 5 dialogues de 3 tours (EUDR, swollen shoot, fermentation et séchage, ARS 1000, SSRTE) passés dans la chaîne complète donnent 15 réponses cohérentes, chaque question de suivi étant bien comprise (« Ça dure combien de jours ? » → « Combien de jours dure la fermentation des fèves de cacao sur feuilles de bananier ? »).

Coût et temps : la reformulation ajoute 1,7 s en médiane (de 1,2 à 3,5 s) aux seules questions de suivi, pour un coût négligeable. C'est le principal levier de temps pour l'étape 11 (prompt plus court, ou reformulation sautée quand la question nomme déjà son sujet).

## 4. Sources

- Tarifs Claude : <https://platform.claude.com/docs/en/about-claude/pricing>
- Tarifs Voyage AI : <https://docs.voyageai.com/docs/pricing>
- Limites de débit Voyage AI : <https://docs.voyageai.com/docs/rate-limits>
- Modèles Voyage AI (dimensions, multilingue) : <https://mongodb.com/docs/voyageai/models/>
- Rerankers Voyage AI : <https://docs.voyageai.com/docs/reranker>
- Claude Sonnet 5.5 (paramètres refusés, réflexion) : <https://platform.claude.com/docs/en/models/sonnet-5-5/overview>
- Paramètre `effort` : <https://platform.claude.com/docs/en/build-with-claude/effort>
- Offre Pinecone Starter : <https://www.pinecone.io/pricing/>
