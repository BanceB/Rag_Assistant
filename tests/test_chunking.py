"""Tests de l'étape 4 : découpage en chunks, métadonnées et en-tête contextuel."""

import json

import pytest
from langchain_core.documents import Document

from rag_assistant.config import get_settings
from rag_assistant.ingestion.chunking import (
    _norm,
    decouper,
    est_intertitre,
    fusionner_petits,
    texte_sans_en_tete,
)

META = {
    "doc_id": "BPA-999",
    "titre": "Manuel de test",
    "organisme": "CNRA",
    "date": "2015-02",
    "type": "guide",
    "page": 1,
}


def page(texte, **meta):
    return Document(page_content=texte, metadata={**META, **meta})


def test_un_texte_court_donne_un_seul_chunk_avec_en_tete():
    chunks = decouper([page("Le cacaoyer aime l'ombre. " * 10)], chunk_size=1000, chunk_overlap=100)
    assert len(chunks) == 1
    assert chunks[0].page_content.startswith("Manuel de test (CNRA, 2015)\n\n")
    assert texte_sans_en_tete(chunks[0]) == ("Le cacaoyer aime l'ombre. " * 10).strip()


def test_decoupage_et_chevauchement():
    phrases = [f"Phrase numero {i} sur la pepiniere de cacaoyers." for i in range(40)]
    chunks = decouper([page(" ".join(phrases))], chunk_size=300, chunk_overlap=60)
    textes = [texte_sans_en_tete(c) for c in chunks]
    assert len(chunks) == 8
    assert all(len(t) <= 300 for t in textes)
    # chevauchement : la fin d'un chunk se retrouve au début du suivant
    for avant, apres in zip(textes, textes[1:]):
        assert avant.split(". ")[-1].strip(". ") in apres
    # rien n'est perdu
    assert all(p.rstrip(".") in " ".join(textes) for p in phrases)


def test_metadonnees_identifiants_et_section():
    pages = [
        page("1.1 Choix du terrain\n\n" + "Un sol profond convient. " * 30, page=1),
        page("Le pivot descend loin. " * 30, page=2),
    ]
    chunks = decouper(pages, chunk_size=400, chunk_overlap=0)
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    assert ids[0] == "BPA-999-p001-c00"
    assert all(c.metadata["section"] == "1.1 Choix du terrain" for c in chunks)  # reportée p. 2
    assert chunks[-1].metadata["page"] == 2
    assert "— 1.1 Choix du terrain" in chunks[-1].page_content.split("\n\n")[0]


def test_les_reglements_sont_coupes_a_chaque_article():
    texte = (
        "Article 1\n\nObjet\n\n" + "Le règlement fixe des règles. " * 5 + "\n\n"
        "Article 2\n\nDéfinitions\n\n" + "On entend par forêt une étendue. " * 5
    )
    chunks = decouper([page(texte, type="reglement")], chunk_size=2000, chunk_overlap=0)
    assert len(chunks) == 2
    assert [c.metadata["section"] for c in chunks] == ["Article 1", "Article 2"]
    assert "Article 2" not in texte_sans_en_tete(chunks[0])


def test_fusionner_petits():
    assert fusionner_petits(["2.2.6 Semis", "x" * 150]) == ["2.2.6 Semis\n\n" + "x" * 150]
    assert fusionner_petits(["x" * 150, "fin."]) == ["x" * 150 + "\n\nfin."]
    # un intertitre en fin de page reste seul : il annonce la page suivante
    assert fusionner_petits(["x" * 150, "Article 13"]) == ["x" * 150, "Article 13"]


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("Article 9", True),
        ("2.2.6. Semis", True),
        ("6. LÉGALITÉ", True),
        ("ANNEXE I", True),
        ("2. La diligence raisonnée comprend:", False),  # alinéa numéroté
        ("1.1. Origine et botanique du cacaoyer .......... 9", False),  # ligne de sommaire
        ("15 jours avant la plantation", False),
        ("Le cacaoyer est une plante de sous-bois.", False),
    ],
)
def test_est_intertitre(texte, attendu):
    assert est_intertitre(texte) is attendu


CORPUS = get_settings().chemins.corpus


@pytest.mark.skipif(not any(CORPUS.rglob("*.pdf")), reason="PDF du corpus absents (non versionnés)")
def test_corpus_aucune_preuve_coupee_avec_le_reglage_par_defaut():
    """Avec le réglage de settings.yaml, chaque extrait de preuve tient dans un seul chunk."""
    from rag_assistant.ingestion.loaders import charger_corpus

    pages, _ = charger_corpus()
    chunks = decouper(pages)
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    par_page = {}
    for c in chunks:
        cle = (c.metadata["doc_id"], c.metadata["page"])
        par_page.setdefault(cle, []).append(_norm(texte_sans_en_tete(c)))
    with open(get_settings().chemins.questions_eval, encoding="utf-8") as f:
        preuves = [p for ligne in f if ligne.strip() for p in json.loads(ligne)["preuves"]]
    coupees = [
        (p["doc_id"], p["page"])
        for p in preuves
        if not any(_norm(p["extrait"]) in t for t in par_page.get((p["doc_id"], p["page"]), []))
    ]
    assert coupees == []


# ---------------------------------------------------------------- intertitres typographiques


def test_section_typographique_prime_sur_la_numerotation():
    """Avec la typographie, une ligne de tableau numérotée n'ouvre plus de section."""
    texte = (
        "Symptômes sur les feuilles\n\n"
        + "Des taches jaunes apparaissent le long des nervures. " * 8
        + "\n\n16. Application d'engrais Entretien\n\n"
        + "Le système de traçabilité doit inclure les registres. " * 8
    )
    chunks = decouper(
        [page(texte, intertitres="Symptômes sur les feuilles")], chunk_size=400, chunk_overlap=0
    )
    assert {c.metadata["section"] for c in chunks} == {"Symptômes sur les feuilles"}
    assert all("intertitres" not in c.metadata for c in chunks)


def test_sans_typographie_on_se_replie_sur_la_numerotation():
    chunks = decouper([page("3.10. Qui est une PME\n\n" + "Texte de la réponse. " * 20)])
    assert chunks[0].metadata["section"] == "3.10. Qui est une PME"


def test_en_tete_abrege_titre_et_organisme_longs():
    meta = {
        **META,
        "titre": "ARS 1000 Cacao durable (parties 1 à 3) : " + "exigences relatives " * 10,
        "organisme": "ORAN / ARSO (Organisation régionale africaine de normalisation), diffusé par la WCF",
        "date": "2021",
    }
    chunks = decouper([Document(page_content="Texte de la norme. " * 20, metadata=meta)])
    en_tete = chunks[0].metadata["en_tete"]
    assert "(ORAN / ARSO, 2021)" in en_tete
    assert len(en_tete) < 130 and "…" in en_tete
