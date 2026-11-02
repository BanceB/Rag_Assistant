"""Étape 5 : vectoriser les chunks et les ranger dans la base vectorielle, sans doublon.

Principes :
- une collection par filière, modèle d'embedding et réglage de découpage
  (ex. `cacao_voyage-4_2000-200`) : on peut ainsi comparer plusieurs réglages à l'étape 11
  sans qu'ils se mélangent ;
- chaque chunk est rangé sous son `chunk_id` stable et porte une empreinte de son texte :
  une relance n'envoie à Voyage que les chunks nouveaux ou modifiés, et retire ceux qui ont
  disparu (indexation idempotente et incrémentale) ;
- envoi par lots, avec nouvel essai après une attente qui double à chaque échec
  (backoff exponentiel) en cas de quota dépassé ou de coupure réseau ;
- distance cosinus, pour obtenir des scores de similarité lisibles (étape 6).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from rag_assistant.config import Settings, get_settings

log = logging.getLogger(__name__)
T = TypeVar("T")

TAILLE_LOT = 64  # chunks par requête : environ 30 000 tokens, très en dessous des limites
ESSAIS_MAX = 6  # attentes successives : 2, 4, 8, 16, 32 s
ATTENTE_INITIALE = 2.0


def nom_collection(settings: Settings, chunk_size: int, chunk_overlap: int) -> str:
    """Nom de collection valide pour Chroma : lettres, chiffres, « . », « _ » et « - »."""
    brut = f"{settings.namespace}_{settings.embeddings.model}_{chunk_size}-{chunk_overlap}"
    return re.sub(r"[^A-Za-z0-9._-]", "-", brut)


def creer_embeddings(settings: Settings | None = None) -> Embeddings:
    """Modèle d'embedding de la configuration (le même pour les documents et les questions)."""
    settings = settings or get_settings()
    if settings.embeddings.provider != "voyageai":
        raise ValueError(
            f"Fournisseur d'embeddings non pris en charge : {settings.embeddings.provider}"
        )
    from langchain_voyageai import VoyageAIEmbeddings

    return VoyageAIEmbeddings(model=settings.embeddings.model, batch_size=TAILLE_LOT)


def ouvrir_base(
    embeddings: Embeddings,
    collection: str,
    settings: Settings | None = None,
) -> VectorStore:
    """Ouvre (ou crée) la collection dans la base choisie dans settings.yaml."""
    settings = settings or get_settings()
    if settings.vectorstore.provider == "chroma":
        import chromadb
        from langchain_chroma import Chroma

        # Base locale ; télémétrie anonyme de Chroma désactivée (rien ne sort du poste)
        client = chromadb.PersistentClient(
            path=str(settings.vectorstore.persist_directory),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        return Chroma(
            client=client,
            collection_name=collection,
            embedding_function=embeddings,
            collection_metadata={"hnsw:space": "cosine"},
        )
    if settings.vectorstore.provider == "pinecone":
        from langchain_pinecone import PineconeVectorStore

        return PineconeVectorStore(
            index_name=settings.vectorstore.index_name,
            embedding=embeddings,
            namespace=collection,
        )
    raise ValueError(f"Base vectorielle non prise en charge : {settings.vectorstore.provider}")


def empreinte(chunk: Document) -> str:
    """Empreinte du texte vectorisé : si elle change, le chunk doit être revectorisé."""
    return hashlib.sha1(chunk.page_content.encode("utf-8")).hexdigest()


def avec_reessais(action: Callable[[], T], description: str) -> T:
    """Exécute `action` et renvoie son résultat ; en cas d'erreur passagère (quota dépassé,
    coupure réseau), réessaie après 2, 4, 8… secondes. Sert aussi au reranking (étape 6)."""
    from voyageai import error as voyage

    passageres = (
        voyage.RateLimitError,
        voyage.ServiceUnavailableError,
        voyage.ServerError,
        voyage.APIConnectionError,
        voyage.Timeout,
        voyage.TryAgain,
    )
    attente = ATTENTE_INITIALE
    for essai in range(1, ESSAIS_MAX + 1):
        try:
            return action()
        except passageres as erreur:
            if essai == ESSAIS_MAX:
                raise
            log.warning(
                "%s : %s ; nouvel essai dans %.0f s", description, type(erreur).__name__, attente
            )
            time.sleep(attente)
            attente *= 2
    raise AssertionError("inaccessible : la dernière tentative renvoie ou lève")


@dataclass
class Bilan:
    ajoutes: int = 0
    modifies: int = 0
    inchanges: int = 0
    supprimes: int = 0
    total: int = 0  # chunks dans la collection à la fin


def _empreintes_existantes(base: VectorStore) -> dict[str, str]:
    """chunk_id → empreinte des chunks déjà indexés (Chroma seulement)."""
    if not hasattr(base, "get"):
        return {}  # Pinecone : pas de lecture groupée simple, on renvoie tout (upsert)
    contenu = base.get(include=["metadatas"])
    return {i: (m or {}).get("empreinte", "") for i, m in zip(contenu["ids"], contenu["metadatas"])}


def indexer(chunks: list[Document], base: VectorStore, supprimer_absents: bool = True) -> Bilan:
    """Synchronise la collection avec la liste de chunks : ajoute, met à jour, retire."""
    ids = [c.metadata["chunk_id"] for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Identifiants de chunks en double : vérifier le découpage")
    existants = _empreintes_existantes(base)
    bilan = Bilan()
    a_envoyer: list[Document] = []
    for chunk in chunks:
        e = empreinte(chunk)
        chunk.metadata["empreinte"] = e
        ancien = existants.get(chunk.metadata["chunk_id"])
        if ancien == e:
            bilan.inchanges += 1
            continue
        a_envoyer.append(chunk)
        if ancien is None:
            bilan.ajoutes += 1
        else:
            bilan.modifies += 1

    for debut in range(0, len(a_envoyer), TAILLE_LOT):
        lot = a_envoyer[debut : debut + TAILLE_LOT]
        lot_ids = [c.metadata["chunk_id"] for c in lot]
        avec_reessais(
            lambda lot=lot, lot_ids=lot_ids: base.add_documents(lot, ids=lot_ids),
            f"lot {debut // TAILLE_LOT + 1}",
        )
        log.info(
            "%d / %d chunks vectorisés", min(debut + TAILLE_LOT, len(a_envoyer)), len(a_envoyer)
        )

    if supprimer_absents and existants:
        absents = sorted(set(existants) - set(ids))
        if absents:
            base.delete(ids=absents)
        bilan.supprimes = len(absents)

    bilan.total = len(_empreintes_existantes(base)) or len(ids)
    return bilan


def supprimer_document(base: VectorStore, doc_id: str) -> int:
    """Retire tous les chunks d'un document (servira à la page d'administration, F7)."""
    trouves = base.get(where={"doc_id": doc_id}, include=[])["ids"]
    if trouves:
        base.delete(ids=trouves)
    return len(trouves)
