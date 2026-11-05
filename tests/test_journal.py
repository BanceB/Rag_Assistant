"""Tests de l'étape 10 : journal SQLite, anonymisation, consentement, avis, purge."""

import json
import sqlite3
from datetime import timedelta

import pytest

from rag_assistant.services import journal as j


def reponse(question="Comment reconnaître le swollen shoot ?", refus=False, total=3.2, **autres):
    return {
        "question": question,
        "question_recherche": question,
        "texte": "Bandes rouges le long des nervures [1].",
        "sources": [] if refus else [{"doc_id": "MAL-001", "page": 4}],
        "refus": refus,
        "motif": "sous_le_seuil" if refus else None,
        "couverture": "complete",
        "avertissements": [],
        "meilleur_score": 0.8,
        "latences": {"total": total, "premier_mot": 1.4},
        "usage": {"entree": 1200, "sortie": 90},
        **autres,
    }


@pytest.fixture
def journal(tmp_path):
    return j.Journal(tmp_path / "app.db", conservation_jours=90)


@pytest.mark.parametrize(
    "texte, attendu",
    [
        ("Appelez-moi au 07 08 09 10 11", "Appelez-moi au [numéro]"),
        ("Mon numéro : +225 0102030405.", "Mon numéro : [numéro]."),
        ("Écrivez à kouassi.yao@exemple.ci", "Écrivez à [courriel]"),
        ("Le prix est de 1 800 000 FCFA", "Le prix est de 1 800 000 FCFA"),
        ("300 kg par hectare en 2025", "300 kg par hectare en 2025"),
    ],
)
def test_anonymiser_masque_numeros_et_courriels_mais_pas_les_chiffres_utiles(texte, attendu):
    assert j.anonymiser(texte) == attendu


def test_sans_consentement_aucun_texte_n_est_garde(journal):
    journal.enregistrer("s1", reponse(), consentement=False)
    ligne = journal.derniers()[0]
    assert ligne["question"] is None and ligne["reponse"] is None
    assert ligne["nb_sources"] == 1 and json.loads(ligne["sources"]) == [["MAL-001", 4]]
    assert ligne["latence_totale"] == 3.2


def test_avec_consentement_le_texte_est_garde_anonymise(journal):
    journal.enregistrer("s1", reponse("Je suis au 0707070707, que faire ?"), consentement=True)
    ligne = journal.derniers()[0]
    assert ligne["question"] == "Je suis au [numéro], que faire ?" and ligne["reponse"]


def test_avis_un_seul_par_echange_et_retrait(journal):
    i = journal.enregistrer("s1", reponse())
    journal.noter(i, 1)
    journal.noter(i, 0)
    assert journal.derniers()[0]["avis"] == 0
    journal.noter(i, None)
    assert journal.derniers()[0]["avis"] is None


def test_statistiques_du_tableau_de_bord(journal):
    a = journal.enregistrer("s1", reponse(total=2.0))
    journal.enregistrer("s1", reponse(total=6.0), suivi=True)
    journal.enregistrer("s2", reponse(refus=True, total=0.5))
    journal.enregistrer_erreur("s2", ConnectionError("réseau"))
    journal.noter(a, 1)
    st = journal.statistiques()
    assert (st["questions"], st["sessions"], st["erreurs"]) == (4, 2, 1)
    assert (st["reponses"], st["refus"], st["taux_refus"]) == (2, 1, 33.3)
    assert st["refus_par_motif"] == {"sous_le_seuil": 1} and st["taux_sourcees"] == 100.0
    assert st["taux_sous_5s"] == 66.7 and st["latence_mediane"] == 2.0
    assert (st["avis"], st["taux_utiles"], st["suivis"]) == (1, 100.0, 1)
    assert st["documents_cites"] == {"MAL-001": 2}


def test_purge_supprime_les_echanges_trop_anciens_et_leurs_avis(journal, monkeypatch):
    ancien = j.maintenant() - timedelta(days=120)
    monkeypatch.setattr(j, "maintenant", lambda: ancien)
    vieux = journal.enregistrer("s1", reponse())
    journal.noter(vieux, 1)
    monkeypatch.undo()
    journal.enregistrer("s1", reponse())
    assert journal.purger() == 1
    assert len(journal.derniers()) == 1
    with sqlite3.connect(journal.chemin) as c:
        assert c.execute("SELECT COUNT(*) FROM avis").fetchone()[0] == 0


def test_export_csv(journal):
    journal.enregistrer("s1", reponse())
    csv_texte = journal.exporter_csv()
    assert csv_texte.splitlines()[0].startswith("id,horodatage,session")
    assert len(csv_texte.splitlines()) == 2


def test_base_d_avant_le_cache_mise_a_jour(tmp_path):
    chemin = tmp_path / "app.db"
    with sqlite3.connect(chemin) as c:  # table créée par la première version de l'étape 10
        c.execute(
            "CREATE TABLE echanges (id INTEGER PRIMARY KEY AUTOINCREMENT, horodatage TEXT NOT NULL,"
            " session TEXT NOT NULL, profil TEXT, consentement INTEGER NOT NULL, question TEXT,"
            " question_recherche TEXT, reponse TEXT, suivi INTEGER NOT NULL DEFAULT 0,"
            " refus INTEGER NOT NULL DEFAULT 0, motif TEXT, couverture TEXT,"
            " nb_sources INTEGER NOT NULL DEFAULT 0, sources TEXT,"
            " nb_avertissements INTEGER NOT NULL DEFAULT 0, meilleur_score REAL,"
            " latence_totale REAL, latence_premier_mot REAL, tokens_entree INTEGER,"
            " tokens_sortie INTEGER, erreur TEXT)"
        )
    journal = j.Journal(chemin)
    journal.enregistrer("s1", reponse(depuis_cache={"date": "2026-11-05", "secours": False}))
    assert journal.derniers()[0]["cache"] == 1
    assert journal.statistiques()["latence_mediane"] is None  # le cache n'entre pas dans les temps
