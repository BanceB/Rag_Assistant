"""Tests de l'étape 3 : nettoyage du texte, lecture des PDF et chargement du corpus."""

import json
import re

import pymupdf
import pytest
from test_catalogue import ecrire_catalogue, ligne

from rag_assistant.config import get_settings
from rag_assistant.ingestion.loaders import (
    CHAMPS_CATALOGUE,
    _assembler,
    blocs_repetes,
    charger_corpus,
    charger_pdf,
    nettoyer_texte,
)

# ---------------------------------------------------------------- nettoyage


def test_nettoyer_texte_recolle_les_mots_coupes_et_les_lignes():
    brut = "Son béné-\nfice est de\n250 000 F   par­hectare"
    assert nettoyer_texte(brut) == "Son bénéfice est de 250 000 F parhectare"


def test_nettoyer_texte_remplace_les_ligatures():
    assert nettoyer_texte("cannot a\ufb00ord, v\u00e9ri\ufb01\u00e9e") == "cannot afford, vérifiée"


def test_nettoyer_texte_garde_les_tirets_des_mots_composes():
    assert nettoyer_texte("piqueurs-suceurs et\nNPK 0-23-19") == "piqueurs-suceurs et NPK 0-23-19"


def test_assembler_reunit_les_lignes_d_un_meme_paragraphe():
    blocs = ["Il faut prévoir", "environ 82 m2.", "Confection de l'ombrière"]
    assert _assembler(blocs) == "Il faut prévoir environ 82 m2.\n\nConfection de l'ombrière"


def test_blocs_repetes_retire_en_tetes_mais_garde_les_articles():
    pages = [
        [
            ("Manuel du planteur", True),
            (f"Article {i}", True),
            (f"Contenu {c}", False),
            (str(i), True),
        ]
        for i, c in enumerate("abcdef", start=1)
    ]
    repetes = blocs_repetes(pages)
    assert "manuel du planteur" in repetes
    assert "#" in repetes  # numéros de page
    assert "contenu a" not in repetes
    assert "article #" not in repetes
    assert not any(k.startswith("contenu") for k in repetes)


def test_blocs_repetes_ne_touche_pas_aux_documents_courts():
    pages = [[("Titre", True), ("Texte", False)]] * 3
    assert blocs_repetes(pages) == set()


# ---------------------------------------------------------------- lecture d'un PDF


def creer_pdf(chemin, corps):
    """PDF de test : un en-tête et un numéro de page sur chaque page, plus le corps donné."""
    pdf = pymupdf.open()
    for numero, texte in enumerate(corps, start=1):
        page = pdf.new_page()
        page.insert_text((72, 40), "Fiche technique CNRA")
        if texte:
            page.insert_text((72, 300), texte)
        page.insert_text((290, 820), str(numero))
    pdf.save(chemin)
    pdf.close()


def test_charger_pdf_une_page_par_document(tmp_path):
    chemin = tmp_path / "fiche.pdf"
    corps = [f"Paragraphe numero {i} sur la culture du cacaoyer." for i in range(1, 6)]
    corps[2] = ""  # page sans texte utile
    creer_pdf(chemin, corps)

    documents = charger_pdf(chemin, {"doc_id": "MAL-001"})

    assert [d.metadata["page"] for d in documents] == [1, 2, 4, 5]
    assert all(d.metadata["nb_pages"] == 5 for d in documents)
    assert all(d.metadata["doc_id"] == "MAL-001" for d in documents)
    assert documents[0].page_content == "Paragraphe numero 1 sur la culture du cacaoyer."
    assert all("Fiche technique CNRA" not in d.page_content for d in documents)


# ---------------------------------------------------------------- chargement du corpus


def test_charger_corpus_filtre_et_enrichit(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "eudr").mkdir(parents=True)
    creer_pdf(corpus / "eudr" / "texte.pdf", [f"Le cacao est concerne, point {c}." for c in "abcd"])
    (corpus / "eudr" / "abime.pdf").write_bytes(b"ceci n'est pas un PDF")
    catalogue = tmp_path / "catalogue.csv"
    ecrire_catalogue(
        catalogue,
        [
            ligne("EUDR-001"),
            ligne("EUDR-002", statut="a_verifier", valide_par=""),
            ligne("EUDR-003", fichier=""),
            ligne("EUDR-004", fichier="eudr/abime.pdf"),
        ],
    )

    documents, rapport = charger_corpus(catalogue, corpus)

    assert rapport.documents == 1 and rapport.pages == 4
    assert rapport.non_valides == ["EUDR-002"]
    assert rapport.sans_fichier == ["EUDR-003"]
    assert list(rapport.echecs) == ["EUDR-004"]
    meta = documents[0].metadata
    assert set(CHAMPS_CATALOGUE) <= set(meta)
    assert meta["titre"] == "Titre, avec une virgule" and meta["theme"] == "eudr"


# ---------------------------------------------------------------- corpus réel


def _norm(texte):
    texte = texte.replace("’", "'").replace(" ", " ").replace("‐", "-").replace("‑", "-")
    texte = re.sub(r"-\s*\n\s*", "", texte)
    return re.sub(r"\s+", " ", texte).strip().lower()


CORPUS = get_settings().chemins.corpus


@pytest.mark.skipif(not any(CORPUS.rglob("*.pdf")), reason="PDF du corpus absents (non versionnés)")
def test_le_texte_charge_contient_toutes_les_preuves():
    """Le chargement ne perd aucun passage cité en preuve dans le jeu d'évaluation."""
    documents, rapport = charger_corpus()
    assert rapport.echecs == {}
    pages = {(d.metadata["doc_id"], d.metadata["page"]): _norm(d.page_content) for d in documents}
    with open(get_settings().chemins.questions_eval, encoding="utf-8") as f:
        questions = [json.loads(ligne) for ligne in f if ligne.strip()]
    manquantes = [
        (q["id"], p["doc_id"], p["page"])
        for q in questions
        for p in q["preuves"]
        if _norm(p["extrait"]) not in pages.get((p["doc_id"], p["page"]), "")
    ]
    assert manquantes == []
