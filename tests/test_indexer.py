"""Tests de l'étape 5 : indexation idempotente, mise à jour, suppression et reprise sur erreur.

Un faux modèle d'embedding (déterministe, sans réseau) remplace Voyage : on teste la logique
d'indexation, pas la qualité des vecteurs.
"""

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from rag_assistant.config import get_settings
from rag_assistant.ingestion import indexer as module
from rag_assistant.ingestion.indexer import (
    avec_reessais,
    indexer,
    nom_collection,
    supprimer_document,
)


def chunk(doc_id, page, index, texte):
    return Document(
        page_content=texte,
        metadata={
            "doc_id": doc_id,
            "page": page,
            "chunk_index": index,
            "chunk_id": f"{doc_id}-p{page:03d}-c{index:02d}",
        },
    )


@pytest.fixture
def base(tmp_path):
    return Chroma(
        collection_name="test",
        embedding_function=DeterministicFakeEmbedding(size=16),
        persist_directory=str(tmp_path / "chroma"),
        collection_metadata={"hnsw:space": "cosine"},
    )


@pytest.fixture
def chunks():
    return [
        chunk("MAL-001", 1, 0, "Le swollen shoot fait gonfler les rameaux."),
        chunk("MAL-001", 1, 1, "Les cochenilles transmettent le virus."),
        chunk("BPA-005", 3, 0, "Semer les fèves à 1 cm de profondeur."),
    ]


def test_deux_lancements_ne_creent_aucun_doublon(base, chunks):
    premier = indexer(chunks, base)
    second = indexer(chunks, base)
    assert (premier.ajoutes, premier.total) == (3, 3)
    assert (second.ajoutes, second.modifies, second.inchanges, second.total) == (0, 0, 3, 3)


def test_un_chunk_modifie_est_revectorise_et_un_chunk_disparu_est_retire(base, chunks):
    indexer(chunks, base)
    nouveaux = [chunks[0], chunk("MAL-001", 1, 1, "Les cochenilles transmettent le CSSV.")]
    bilan = indexer(nouveaux, base)
    assert (bilan.modifies, bilan.inchanges, bilan.supprimes, bilan.total) == (1, 1, 1, 2)
    assert base.get(ids=["MAL-001-p001-c01"])["documents"] == [
        "Les cochenilles transmettent le CSSV."
    ]


def test_supprimer_un_document(base, chunks):
    indexer(chunks, base)
    assert supprimer_document(base, "MAL-001") == 2
    assert base.get()["ids"] == ["BPA-005-p003-c00"]


def test_la_recherche_retrouve_le_chunk(base, chunks):
    indexer(chunks, base)
    # le faux modèle donne le même vecteur au même texte : la question identique sort en tête
    resultat = base.similarity_search("Semer les fèves à 1 cm de profondeur.", k=1)[0]
    assert resultat.metadata["chunk_id"] == "BPA-005-p003-c00"
    assert "empreinte" in resultat.metadata


def test_identifiants_en_double_refuses(base, chunks):
    with pytest.raises(ValueError):
        indexer(chunks + [chunks[0]], base)


def test_reessai_apres_quota_depasse(monkeypatch):
    from voyageai import error

    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    appels = []

    def action():
        appels.append(1)
        if len(appels) < 3:
            raise error.RateLimitError("trop de requêtes")

    avec_reessais(action, "lot de test")
    assert len(appels) == 3


def test_nom_de_collection():
    assert nom_collection(get_settings(), 2000, 200) == "cacao_voyage-4_2000-200"


CORPUS = get_settings().chemins.corpus


@pytest.mark.skipif(not any(CORPUS.rglob("*.pdf")), reason="PDF du corpus absents (non versionnés)")
def test_pipeline_complet_idempotent(tmp_path, monkeypatch, capsys):
    """Tout le corpus, avec un faux modèle : la seconde exécution ne revectorise rien."""
    from rag_assistant.ingestion import pipeline

    def base_de_test(embeddings, collection, settings=None):
        return Chroma(
            collection_name=collection,
            embedding_function=embeddings,
            persist_directory=str(tmp_path / "chroma"),
            collection_metadata={"hnsw:space": "cosine"},
        )

    monkeypatch.setattr(pipeline, "creer_embeddings", lambda s: DeterministicFakeEmbedding(size=16))
    monkeypatch.setattr(pipeline, "ouvrir_base", base_de_test)
    monkeypatch.setattr(pipeline, "secrets_manquants", lambda s: [])

    assert pipeline.main([]) == 0
    premier = capsys.readouterr().out
    assert pipeline.main([]) == 0
    second = capsys.readouterr().out
    assert "Ajoutés : 0 | modifiés : 0" in second and "retirés : 0" in second
    total = [ligne for ligne in premier.splitlines() if ligne.startswith("Total")][0].split("|")[0]
    assert total in second
