"""Tests du catalogue : lecture au format Excel français et détection des erreurs courantes."""

import csv

from rag_assistant.catalogue import (
    COLONNES,
    fichiers_non_catalogues,
    lire_catalogue,
    verifier_catalogue,
)


def ecrire_catalogue(chemin, lignes, separateur=",", encodage="utf-8"):
    with open(chemin, "w", encoding=encodage, newline="") as f:
        ecrivain = csv.writer(f, delimiter=separateur)
        ecrivain.writerow(COLONNES)
        ecrivain.writerows(lignes)


def ligne(doc_id="EUDR-001", fichier="eudr/texte.pdf", statut="valide", valide_par="encadrant"):
    return [
        doc_id,
        "Titre, avec une virgule",
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


def test_format_excel_francais_accepte(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "eudr").mkdir(parents=True)
    (corpus / "eudr" / "texte.pdf").write_bytes(b"%PDF")
    catalogue = tmp_path / "catalogue.csv"
    ecrire_catalogue(catalogue, [ligne()], separateur=";", encodage="utf-8-sig")

    entrees = lire_catalogue(catalogue)
    assert entrees[0].titre == "Titre, avec une virgule"
    assert verifier_catalogue(entrees, corpus) == []
