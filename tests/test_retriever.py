"""Tests de l'étape 6 : recherche, reranking, seuil et analyse des mesures.

Un faux modèle d'embedding et un faux reranker remplacent Voyage : on teste la logique,
pas la qualité des modèles (mesurée par `rag_assistant.evaluation.recherche`).
"""

from types import SimpleNamespace

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from rag_assistant.evaluation import recherche as ev
from rag_assistant.ingestion.indexer import indexer
from rag_assistant.rag.retriever import Recuperateur, RerankerVoyage

TEXTES = {
    "MAL-001": "Le swollen shoot fait gonfler les rameaux du cacaoyer.",
    "MAL-002": "La pourriture brune noircit les cabosses en saison des pluies.",
    "EUDR-001": "Le règlement interdit le cacao issu de terres déboisées après 2020.",
    "BPA-009": "La pépinière doit être installée près d'un point d'eau.",
}


@pytest.fixture
def base(tmp_path):
    base = Chroma(
        collection_name="test",
        embedding_function=DeterministicFakeEmbedding(size=16),
        persist_directory=str(tmp_path / "chroma"),
        collection_metadata={"hnsw:space": "cosine"},
    )
    chunks = [
        Document(
            page_content=texte,
            metadata={
                "doc_id": d,
                "page": 1,
                "chunk_index": 0,
                "chunk_id": f"{d}-p001-c00",
                "theme": "eudr" if d.startswith("EUDR") else "agronomie",
            },
        )  # fmt: skip
        for d, texte in TEXTES.items()
    ]
    indexer(chunks, base)
    return base


def reranker_par_mot(mot):
    """Faux reranker : 0,9 aux textes qui contiennent `mot`, 0,1 aux autres."""

    def reranker(question, textes, top_k):
        scores = sorted(
            ((i, 0.9 if mot in t else 0.1) for i, t in enumerate(textes)), key=lambda x: -x[1]
        )
        return scores[:top_k] if top_k else scores

    return reranker


def test_sans_reranker_on_garde_l_ordre_vectoriel(base):
    resultat = Recuperateur(base, k=2, fetch_k=4).recuperer(TEXTES["BPA-009"])
    assert len(resultat.passages) == 2 and len(resultat.candidats) == 4
    assert resultat.passages[0].doc_id == "BPA-009"  # même texte : même vecteur
    assert resultat.passages[0].score == resultat.passages[0].similarite
    assert resultat.pertinent  # sans seuil : il suffit d'un passage


def test_le_reranker_reclasse_et_donne_le_score(base):
    rec = Recuperateur(base, reranker_par_mot("cabosses"), k=2, fetch_k=4)
    resultat = rec.recuperer("Pourquoi mes fruits pourrissent ?")
    premier = resultat.passages[0]
    assert premier.doc_id == "MAL-002" and premier.score == 0.9
    assert premier.rang_initial in range(1, 5)  # le rang vectoriel est conservé


def test_seuil(base):
    rec = Recuperateur(base, reranker_par_mot("cabosses"), k=2, fetch_k=4, seuil=0.5)
    assert rec.recuperer("cabosses noires").pertinent
    rec_sans = Recuperateur(base, reranker_par_mot("introuvable"), k=2, fetch_k=4, seuil=0.5)
    resultat = rec_sans.recuperer("Quel temps fera-t-il demain ?")
    assert not resultat.pertinent and resultat.meilleur_score == 0.1


def test_filtre_par_metadonnee(base):
    resultat = Recuperateur(base, k=4, fetch_k=4).recuperer("cacao", filtre={"theme": "eudr"})
    assert [p.doc_id for p in resultat.passages] == ["EUDR-001"]


def test_k_superieur_a_fetch_k_refuse(base):
    with pytest.raises(ValueError):
        Recuperateur(base, k=5, fetch_k=4)


def test_reranker_voyage_appelle_le_client():
    appels = []

    class FauxClient:
        def rerank(self, question, textes, model, top_k):
            appels.append((model, top_k))
            return SimpleNamespace(
                results=[
                    SimpleNamespace(index=1, relevance_score=0.8),
                    SimpleNamespace(index=0, relevance_score=0.2),
                ]  # fmt: skip
            )

    reranker = RerankerVoyage("rerank-3", client=FauxClient())
    assert reranker("q", ["a", "b"], 2) == [(1, 0.8), (0, 0.2)]
    assert reranker("q", [], 2) == [] and appels == [("rerank-3", 2)]


# ---------------------------------------------------------------- analyse des mesures


def enregistrement(id_, situation, attendus, classement, historique=False):
    return {
        "id": id_,
        "acteur": "agriculteur",
        "theme": "maladies",
        "situation": situation,
        "avec_historique": historique,
        "doc_ids_attendus": attendus,
        "classements": {"m": [[f"{d}-c", d, s] for d, s in classement]},
        "durees": {"m": 0.5},
    }


ENREGISTREMENTS = [
    enregistrement("Q1", "normale", ["A"], [("A", 0.9), ("B", 0.5)]),  # rang 1
    enregistrement("Q2", "normale", ["A"], [("B", 0.8), ("C", 0.7), ("A", 0.6)]),  # rang 3
    enregistrement("Q3", "normale", ["A"], [("B", 0.7), ("C", 0.6)]),  # absent
    enregistrement("Q4", "hors_sujet", [], [("B", 0.2)]),
    enregistrement("Q5", "hors_sujet", [], [("C", 0.4)]),
    enregistrement("Q6", "absent_du_corpus", [], [("B", 0.75)]),
]


def test_mesures_de_classement():
    m = ev.mesures_classement(ENREGISTREMENTS, "m", k=2)
    assert m["questions"] == 3
    assert m["rappel@1"] == pytest.approx(1 / 3)
    assert m["rappel@2"] == pytest.approx(1 / 3)
    assert m["rappel@tous"] == pytest.approx(2 / 3)
    assert m["mrr@2"] == pytest.approx(1 / 3)
    assert [e["id"] for e in ev.echecs(ENREGISTREMENTS, "m", k=2)] == ["Q2", "Q3"]


def test_table_des_seuils_et_proposition():
    table = ev.table_des_seuils(ENREGISTREMENTS, "m", [0.3, 0.5, 0.75])
    assert table[0] == {
        "seuil": 0.3,
        "hors_sujet_detectes": 0.5,
        "absents_detectes": 0.0,
        "avec_reponse_rejetees": 0.0,
    }
    assert table[1]["hors_sujet_detectes"] == 1.0
    assert table[2]["avec_reponse_rejetees"] == pytest.approx(1 / 3)
    assert ev.proposer_seuil(table)["seuil"] == 0.5  # le plus petit qui atteint 90 %


def test_collecte_reprend_ou_elle_s_est_arretee(base, tmp_path):
    questions = [
        {"id": f"Q{i}", "acteur": "agriculteur", "theme": "maladies", "situation": "normale",
         "historique": [], "question": TEXTES["MAL-001"], "doc_ids_attendus": ["MAL-001"]}
        for i in (1, 2)
    ]  # fmt: skip
    sortie = tmp_path / "recherche.jsonl"
    rec = Recuperateur(base, k=2, fetch_k=4)
    ev.collecter(questions[:1], rec, {"faux": reranker_par_mot("gonfler")}, sortie)
    appels = []

    def reranker_compte(q, textes, k):
        appels.append(q)
        return reranker_par_mot("gonfler")(q, textes, k)

    enregistrements = ev.collecter(questions, rec, {"faux": reranker_compte}, sortie)
    assert len(appels) == 1  # Q1 n'est pas réinterrogée
    assert [e["id"] for e in ev.lire_resultats(sortie)] == ["Q1", "Q2"]
    resume = ev.analyser(enregistrements, k=2)
    assert resume["methodes"]["faux"]["classement"]["rappel@1"] == 1.0
    assert set(resume["methodes"]) == {"vectorielle", "faux"}
