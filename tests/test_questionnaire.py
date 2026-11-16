"""Tests du questionnaire des testeurs : questions, contrôle, indicateurs, enregistrement, pages."""

import csv
import io
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from rag_assistant.services import questionnaire as qs
from rag_assistant.services.journal import Journal

PAGE = "from rag_assistant.app import questionnaire\nquestionnaire.page()"
ADMIN = "from rag_assistant.app import admin\nadmin.page()"


def complet(**autres) -> dict:
    """Un questionnaire rempli : le premier choix partout, 4 sur les échelles."""
    reponses = {"q0": "Oui"}
    for q in qs.QUESTIONS:
        if q.choix:
            reponses[q.id] = "4" if q.choix == qs.ECHELLE else q.choix[0]
    reponses.update(autres)
    return reponses


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "app.db")


# ------------------------------------------------------------------ questions et calculs


def test_questions_de_l_annexe_3():
    assert [q.numero for q in qs.QUESTIONS] == list(range(1, 19))
    assert qs.IDENTIFIANTS == [f"q{n}" for n in range(19)]
    facultatives = {q.numero for q in qs.QUESTIONS if not q.obligatoire}
    assert facultatives == {2, 16, 17, 18}
    assert all(qs.QUESTIONS[n - 1].choix == qs.ECHELLE for n in (5, 6, 7, 8, 14))


def test_manquantes():
    assert qs.manquantes({}) == [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
    assert qs.manquantes(complet()) == []
    assert qs.manquantes(complet(q5="7")) == [5]  # hors de l'échelle
    assert qs.manquantes(complet(q9="  ")) == [9]


def test_indicateurs():
    reponses = [complet(q5="5", q14="2", q15="Oui"), complet(q5="3", q14="4", q15="Non")]
    ind = qs.indicateurs(reponses)
    assert ind["testeurs"] == 2 and ind["pertinence"] == 50.0 and ind["satisfaction"] == 50.0
    assert ind["recommandation"] == 50.0 and ind["comprehension"] == 100.0
    assert qs.indicateurs([])["pertinence"] is None


# ------------------------------------------------------------------ enregistrement


def test_enregistrement_anonyme(journal, tmp_path):
    journal.ajouter_questionnaire(
        complet(q17="Appelez-moi au 07 08 09 10 11 ou kouassi@exemple.ci", session="abc", nom="X")
    )
    [ligne] = journal.questionnaires()
    assert ligne["q17"] == "Appelez-moi au [numéro] ou [courriel]"
    assert "session" not in ligne and "nom" not in ligne and ligne["q16"] is None
    with sqlite3.connect(tmp_path / "app.db") as c:
        colonnes = [r[1] for r in c.execute("PRAGMA table_info(questionnaires)")]
    assert colonnes == ["id", "horodatage", "reponses"]


def test_export_csv_et_effacement(journal, tmp_path):
    journal.ajouter_questionnaire(complet())
    journal.ajouter_questionnaire(complet(q16="Les sources"))
    lignes = list(csv.DictReader(io.StringIO(journal.exporter_questionnaires_csv())))
    assert len(lignes) == 2 and lignes[1]["q16"] == "Les sources" and lignes[0]["q5"] == "4"
    with sqlite3.connect(tmp_path / "app.db") as c:
        c.execute("UPDATE questionnaires SET horodatage = '2020-01-01T00:00:00+00:00' WHERE id = 1")
    assert journal.purger() == 1 and len(journal.questionnaires()) == 1
    journal.tout_effacer()
    assert journal.questionnaires() == [] and journal.exporter_questionnaires_csv() == ""


# ------------------------------------------------------------------ pages


def ouvrir(journal) -> AppTest:
    at = AppTest.from_string(PAGE, default_timeout=30)
    at.session_state["_journal_test"] = journal
    return at.run()


def test_page_refus_de_participer(journal):
    at = ouvrir(journal)
    assert not at.exception and at.radio[0].label == "0. Acceptez-vous de participer ?"
    assert len(at.radio) == 1  # le reste n'apparaît qu'après « Oui »
    at.radio[0].set_value("Non").run()
    assert at.info and journal.questionnaires() == []


def test_page_reponses_manquantes_puis_envoi(journal):
    at = ouvrir(journal)
    at.radio[0].set_value("Oui").run()
    assert len(at.radio) == 1 + 15 and len(at.text_area) == 3
    envoyer = [b for b in at.button if b.label == "Envoyer mes réponses"][0]
    envoyer.click().run()
    assert "1, 3, 4" in at.warning[0].value and journal.questionnaires() == []

    reponses = complet()
    for radio in at.radio[1:]:
        numero = int(radio.label.split(".")[0])
        radio.set_value(reponses[f"q{numero}"])
    at.text_area[1].input("Plus d'exemples locaux")
    [b for b in at.button if b.label == "Envoyer mes réponses"][0].click().run()
    assert not at.exception and at.success[0].value.startswith("Merci")
    [ligne] = journal.questionnaires()
    assert ligne["q0"] == "Oui" and ligne["q17"] == "Plus d'exemples locaux"
    assert ligne["q1"] == "Agriculteur ou agricultrice" and ligne["q2"] == "Une femme"


def test_tableau_de_bord_admin(journal, monkeypatch):
    journal.ajouter_questionnaire(complet(q5="5", q14="5", q17="Plus court"))
    journal.ajouter_questionnaire(complet(q5="2", q14="4"))
    at = AppTest.from_string(ADMIN, default_timeout=30)
    at.session_state["admin"] = True
    at.session_state["_journal_test"] = journal
    at.run()
    assert not at.exception
    valeurs = {m.label: m.value for m in at.metric}
    assert valeurs["Testeurs"] == "2" and valeurs["Pertinence perçue"] == "50 %"
    assert valeurs["Satisfaction"] == "100 %"


def test_lien_vers_le_questionnaire_dans_le_panneau(monkeypatch):
    main = Path(__file__).resolve().parents[1] / "src" / "rag_assistant" / "app" / "main.py"
    at = AppTest.from_file(str(main), default_timeout=30)
    at.session_state["_assistant_test"] = None
    at.run()
    assert not at.exception
    assert any("questionnaire" in str(lien.label).lower() for lien in at.get("page_link"))
