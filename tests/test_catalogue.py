"""Tests du catalogue : lecture au format Excel français et détection des erreurs courantes."""

from rag_assistant.catalogue import (
    COLONNES,
    fichiers_non_catalogues,
    lire_catalogue,
    verifier_catalogue,
)


def ecrire_catalogue(chemin, lignes):
    entete = ";".join(COLONNES)
    contenu = "\n".join([entete, *(";".join(ligne) for ligne in lignes)])
    chemin.write_text(contenu, encoding="utf-8-sig")


def ligne(doc_id="EUDR-001", fichier="eudr/texte.pdf", statut="valide", valide_par="encadrant"):
    return [
        doc_id,
        "Titre",
        fichier,
        "https://exemple.org",
        "UE",
        "reglement",
        "eudr",
        "2023-06-09",
        "fr",
        "réutilisation autorisée",
        statut,
        valide_par,
        "",
    ]


def test_catalogue_correct(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "eudr").mkdir(parents=True)
    (corpus / "eudr" / "texte.pdf").write_bytes(b"%PDF")
    catalogue = tmp_path / "catalogue.csv"
    ecrire_catalogue(catalogue, [ligne()])

    entrees = lire_catalogue(catalogue)
    assert len(entrees) == 1
    assert verifier_catalogue(entrees, corpus) == []
    assert fichiers_non_catalogues(entrees, corpus) == []


def test_erreurs_detectees(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "oublie.pdf").write_bytes(b"%PDF")
    catalogue = tmp_path / "catalogue.csv"
    ecrire_catalogue(catalogue, [ligne(), ligne(statut="valide", valide_par="")])

    entrees = lire_catalogue(catalogue)
    problemes = " | ".join(verifier_catalogue(entrees, corpus))
    assert "plusieurs fois" in problemes
    assert "introuvable" in problemes
    assert "sans valide_par" in problemes
    assert fichiers_non_catalogues(entrees, corpus) == ["oublie.pdf"]
