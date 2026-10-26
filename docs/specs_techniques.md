# Spécifications techniques : agent RAG COCOACERT

> Statut : **brouillon de l'étape 1, à valider avec le directeur de mémoire.**
> Tarifs et limites relevés le 26 octobre 2026 (sources en fin de document).

## 1. Architecture retenue

Deux circuits, qui partagent le même modèle d'embedding :

1. **Indexation (hors ligne).** Documents → chargement → découpage → embeddings → base vectorielle.
2. **Question (en ligne).** Question → reformulation si besoin → embedding → recherche + reranking → garde-fou → prompt augmenté → LLM → réponse + sources.

Tous les réglages sont centralisés dans `config/settings.yaml` ; les secrets dans `.env`.

## 2. Décisions

### D1. Chaîne RAG plutôt qu'agent — **décidé**

| Critère                   | Chaîne (recherche systématique) | Agent (le LLM choisit d'appeler l'outil)          |
| -------------------------- | --------------------------------- | ------------------------------------------------- |
| Ancrage sur le corpus      | Garanti : on cherche toujours     | Non garanti : le LLM peut répondre sans chercher |
| Appels au LLM par question | 1                                 | 2 ou plus                                         |
| Temps de réponse          | Plus court                        | Plus long                                         |
| Évaluation                | Reproductible                     | Variable d'une exécution à l'autre              |

Un assistant de conformité doit toujours s'appuyer sur ses sources : la chaîne répond directement à F5 et à la cible de 90 % de réponses sourcées.

### D2. Modèle de langage — **à valider**

| Option                                                | Prix (USD / million de tokens, entrée / sortie) | Coût estimé par question* | Remarque                                                              |
| ----------------------------------------------------- | ------------------------------------------------ | --------------------------- | --------------------------------------------------------------------- |
| Claude Sonnet 5.5                                     | 2 / 10                                           | ≈ 0,011 $                  | Très bonne rédaction en français                                   |
| Claude Haiku 5.5                                      | 0,10 / 0,50                                      | ≈ 0,0006 $                 | Rapide et très peu coûteux                                          |
| Modèle open source auto-hébergé (Mistral, Llama…) | Matériel                                        | —                          | Souveraineté maximale, mais GPU nécessaire et réponses plus lentes |

\* Hypothèse : 3 000 tokens en entrée (consignes + 4 passages + question), 500 en sortie.

**Proposition :** Sonnet 5.5 pour rédiger les réponses, Haiku 5.5 pour reformuler les questions de suivi. Comparer Sonnet et Haiku en génération à l'étape 11 (qualité, latence < 5 s). Mentionner l'auto-hébergement comme perspective de souveraineté.

### D3. Modèle d'embedding — **à valider**

| Option                          | Prix                             | Dimension | Multilingue                  | Remarque                                    |
| ------------------------------- | -------------------------------- | --------- | ---------------------------- | ------------------------------------------- |
| `voyage-4-lite` (actuel)      | 0,02 $ / M tokens, 200 M offerts | 1024      | Non précisé par l'éditeur | Optimisé coût et latence                  |
| `voyage-4`                    | 0,06 $ / M tokens, 200 M offerts | 1024      | Oui (annoncé)               | Meilleure qualité annoncée en multilingue |
| `bge-m3` (open source, local) | Gratuit                          | 1024      | Oui                          | Tourne sur la machine, plus lent sans GPU   |

Ordre de grandeur : 100 documents d'environ 20 pages font à peu près 1,2 million de tokens, donc bien moins que les 200 millions offerts.

**Point bloquant :** sans moyen de paiement enregistré, le compte Voyage est bridé (3 requêtes par minute d'après tes essais), ce qui rend les tests utilisateurs impossibles. Avec un moyen de paiement (palier 1), la limite passe à 2 000 requêtes par minute, et l'usage reste couvert par les tokens offerts.

**Proposition :** `voyage-4` pour son caractère multilingue annoncé, avec un moyen de paiement enregistré. Le reranker associé sera `rerank-3-lite` ou `rerank-3` (étape 6).

### D4. Base vectorielle — **à valider**

| Critère                                                                      | Pinecone (Starter, gratuit)         | Chroma (local)                                   |
| ----------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------------------ |
| Coût                                                                         | 0 $ (jusqu'à 2 Go, 5 index)        | 0 $                                              |
| Où sont les données                                                         | AWS us-east-1 (États-Unis)         | Sur ton PC ou le serveur du LASTIC               |
| Fonctionne sans Internet                                                      | Non                                 | Oui (seule la recherche ; le LLM reste en ligne) |
| Mise en place                                                                 | Déjà fonctionnelle dans le projet | À ajouter (`uv add langchain-chroma`)         |
| Taille adaptée au corpus (~quelques milliers de chunks)                      | Oui                                 | Oui                                              |
| Cohérence avec le cahier (§7.2 hébergement, §7.3 FAISS / Chroma / Milvus) | À justifier                        | Directe                                          |

**Proposition :** Chroma, pour la souveraineté des données, le coût nul et l'hébergement possible au LASTIC. Le code passera par `settings.vectorstore.provider`, afin de basculer d'une base à l'autre en changeant une ligne de configuration.

### D5. Découpage — **provisoire**

`RecursiveCharacterTextSplitter`, 2000 caractères et 200 de chevauchement, avec un découpage par article pour les textes réglementaires. Le réglage final sera choisi par la mesure à l'étape 11 (comparaison 500/50, 1000/150, 2000/200).

### D6. Interface — **décidé**

Streamlit : Python uniquement, composants de chat natifs, application multipage pour l'administration, léger côté navigateur.

## 3. Sources

- Tarifs Claude : [https://platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- Tarifs Voyage AI : [https://docs.voyageai.com/docs/pricing](https://docs.voyageai.com/docs/pricing)
- Limites de débit Voyage AI : [https://docs.voyageai.com/docs/rate-limits](https://docs.voyageai.com/docs/rate-limits)
- Modèles Voyage AI (dimensions, multilingue) : [https://mongodb.com/docs/voyageai/models/](https://mongodb.com/docs/voyageai/models/)
- Offre Pinecone Starter : [https://www.pinecone.io/pricing/](https://www.pinecone.io/pricing/)
