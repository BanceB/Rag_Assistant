# Spécifications techniques : agent RAG COCOACERT

> Statut : **décisions D1 à D4 et D6 prises le 26 octobre 2026, à présenter au directeur de mémoire.** D5 reste provisoire jusqu'aux mesures de l'étape 11.
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

Le jeu `eval/questions.jsonl` (56 questions) contient chaque type de demande, chaque situation particulière et chaque thème. Le test `tests/test_questions.py` vérifie automatiquement cette couverture. Les cibles chiffrées sont celles du §11 : au moins 90 % de réponses sourcées, au moins 90 % des questions hors corpus détectées, 5 s maximum, au moins 80 % de pertinence perçue.

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

**Point bloquant :** sans moyen de paiement enregistré, le compte Voyage est bridé (3 requêtes par minute d'après tes essais), ce qui rend les tests utilisateurs impossibles. Avec un moyen de paiement (palier 1), la limite passe à 2 000 requêtes par minute, et l'usage reste couvert par les tokens offerts.

**Décision :** `voyage-4` pour son caractère multilingue annoncé, avec un moyen de paiement enregistré. Le reranker associé sera `rerank-3-lite` ou `rerank-3` (étape 6).

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

### D5. Découpage — **provisoire**

`RecursiveCharacterTextSplitter`, 2000 caractères et 200 de chevauchement, avec un découpage par article pour les textes réglementaires. Le réglage final sera choisi par la mesure à l'étape 11 (comparaison 500/50, 1000/150, 2000/200).

### D6. Interface — **décidé**

Streamlit : Python uniquement, composants de chat natifs, application multipage pour l'administration, léger côté navigateur.

## 4. Sources

- Tarifs Claude : <https://platform.claude.com/docs/en/about-claude/pricing>
- Tarifs Voyage AI : <https://docs.voyageai.com/docs/pricing>
- Limites de débit Voyage AI : <https://docs.voyageai.com/docs/rate-limits>
- Modèles Voyage AI (dimensions, multilingue) : <https://mongodb.com/docs/voyageai/models/>
- Offre Pinecone Starter : <https://www.pinecone.io/pricing/>
