# Rag_Assistant : agent RAG COCOACERT

Agent conversationnel en français, fondé sur une architecture RAG (Retrieval-Augmented Generation), qui vulgarise les connaissances en durabilité agroalimentaire pour la filière cacao : maladies du cacaoyer, règlement européen sur la déforestation (EUDR), certification, bonnes pratiques agricoles, indicateurs environnementaux.

Projet de mémoire de fin d'études, ESATIC / LASTIC, dans le cadre du projet COCOACERT (FCI4Africa).

> Statut : prototype en cours de développement (version 0.1.0).

## Prérequis

- Python 3.11 ou plus récent
- [uv](https://docs.astral.sh/uv/) pour gérer l'environnement et les dépendances
- Des clés API : Anthropic (LLM), Voyage AI (embeddings), Pinecone (base vectorielle), Tavily (crawl web), LangSmith (traçage, facultatif)

## Installation

```bash
git clone <url-du-depot>
cd Rag_Assistant
uv sync                      # crée .venv et installe les versions exactes de uv.lock
cp .env.example .env         # sous Windows : copy .env.example .env
```

Remplis ensuite les valeurs de `.env`. Ce fichier contient tes secrets : il n'est jamais versionné.

## Utilisation

```bash
# Indexer les documents dans la base vectorielle
uv run python -m rag_assistant.ingestion

# Poser une question de test en ligne de commande
uv run python -m rag_assistant.Backend.core
```

L'interface web (Streamlit) arrivera à l'étape 9 de la feuille de route.

## Structure du dépôt

```
config/        réglages (filière, modèles, k, seuil)
data/corpus/   documents sources, un dossier par thème
docs/          notes, spécifications techniques, méthode de constitution du corpus
eval/          jeu de questions et scripts d'évaluation
src/rag_assistant/
  ingestion.py     chargement, découpage et indexation des documents
  Backend/core.py  génération des réponses (sera remplacé par rag/)
  rag/             partie en ligne : recherche, prompts, garde-fous
  services/        stockage, retours utilisateurs, cache
  app/             interface Streamlit
tests/         tests automatiques
```

## Qualité du code

```bash
uv run ruff check src    # vérifier
uv run ruff format src   # mettre en forme
```
