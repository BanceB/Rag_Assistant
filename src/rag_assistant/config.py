"""Chargement de la configuration du projet.

Deux sources, deux rôles :
- config/settings.yaml : les réglages (modèles, tailles, seuils), versionnés avec le code ;
- .env : les secrets (clés API), jamais versionnés.

Utilisation :
    from rag_assistant.config import get_settings
    settings = get_settings()
    settings.retrieval.k  # -> 4
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Racine du dépôt : src/rag_assistant/config.py -> on remonte de trois niveaux.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

# Clés API indispensables, quelle que soit la base vectorielle.
SECRETS_COMMUNS = ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY")
# Clés supplémentaires selon la base vectorielle choisie.
SECRETS_PAR_BASE = {"chroma": (), "pinecone": ("PINECONE_API_KEY", "INDEX_NAME")}


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    model_rapide: str
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class EmbeddingsSettings:
    provider: str
    model: str


@dataclass(frozen=True)
class VectorStoreSettings:
    provider: str  # "chroma" ou "pinecone"
    persist_directory: Path  # utilisé par Chroma
    index_name: str | None  # utilisé par Pinecone (lu dans .env)


@dataclass(frozen=True)
class ChunkingSettings:
    chunk_size: int
    chunk_overlap: int


@dataclass(frozen=True)
class RetrievalSettings:
    k: int
    fetch_k: int
    seuil_score: float | None


@dataclass(frozen=True)
class MemoireSettings:
    fenetre_messages: int


@dataclass(frozen=True)
class Chemins:
    corpus: Path
    catalogue: Path
    base_sqlite: Path
    logs: Path
    questions_eval: Path


@dataclass(frozen=True)
class Settings:
    filiere: str
    llm: LLMSettings
    embeddings: EmbeddingsSettings
    vectorstore: VectorStoreSettings
    chunking: ChunkingSettings
    retrieval: RetrievalSettings
    memoire: MemoireSettings
    chemins: Chemins

    @property
    def namespace(self) -> str:
        """Compartiment de la base vectorielle : un par filière."""
        return self.filiere


def _valider(s: Settings) -> None:
    """Refuse les réglages incohérents dès le démarrage plutôt qu'en plein traitement."""
    if s.chunking.chunk_overlap >= s.chunking.chunk_size:
        raise ValueError("chunking.chunk_overlap doit être plus petit que chunking.chunk_size")
    if not 0 <= s.llm.temperature <= 1:
        raise ValueError("llm.temperature doit être comprise entre 0 et 1")
    if s.retrieval.k > s.retrieval.fetch_k:
        raise ValueError("retrieval.k ne peut pas dépasser retrieval.fetch_k")
    if s.vectorstore.provider not in SECRETS_PAR_BASE:
        raise ValueError("vectorstore.provider doit valoir 'chroma' ou 'pinecone'")


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Lit settings.yaml et .env, puis renvoie des réglages validés."""
    load_dotenv(PROJECT_ROOT / ".env")
    with open(path, encoding="utf-8") as f:
        brut = yaml.safe_load(f)

    settings = Settings(
        filiere=brut["filiere"],
        llm=LLMSettings(**brut["llm"]),
        embeddings=EmbeddingsSettings(**brut["embeddings"]),
        vectorstore=VectorStoreSettings(
            provider=brut["vectorstore"]["provider"],
            persist_directory=PROJECT_ROOT / brut["vectorstore"]["persist_directory"],
            index_name=os.getenv("INDEX_NAME"),
        ),
        chunking=ChunkingSettings(**brut["chunking"]),
        retrieval=RetrievalSettings(**brut["retrieval"]),
        memoire=MemoireSettings(**brut["memoire"]),
        chemins=Chemins(**{nom: PROJECT_ROOT / p for nom, p in brut["chemins"].items()}),
    )
    _valider(settings)
    return settings


@lru_cache
def get_settings() -> Settings:
    """Version mise en cache : le fichier n'est lu qu'une fois par exécution."""
    return load_settings()


def secrets_manquants(settings: Settings | None = None) -> list[str]:
    """Liste les clés API absentes du .env (vide si tout est prêt)."""
    settings = settings or get_settings()
    requis = SECRETS_COMMUNS + SECRETS_PAR_BASE[settings.vectorstore.provider]
    return [nom for nom in requis if not os.getenv(nom)]


if __name__ == "__main__":
    # Vérification rapide : uv run python -m rag_assistant.config
    s = get_settings()
    print(f"Filière / namespace : {s.namespace}")
    print(
        f"LLM : {s.llm.model} | embeddings : {s.embeddings.model} | base : {s.vectorstore.provider}"
    )
    print(f"Chunks : {s.chunking.chunk_size}/{s.chunking.chunk_overlap} | k = {s.retrieval.k}")
    manquants = secrets_manquants(s)
    print("Clés API : toutes présentes" if not manquants else f"Clés API manquantes : {manquants}")
