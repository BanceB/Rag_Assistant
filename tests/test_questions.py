"""Vérifie que le jeu de questions est bien formé et couvre tout le périmètre de l'agent.

Le périmètre est défini dans docs/specs_techniques.md, section « Périmètre fonctionnel ».
"""

import json
from collections import Counter

import pytest

from rag_assistant.config import get_settings

TYPES_DEMANDE = {
    "expliquer",
    "reconnaitre",
    "guider",
    "lister",
    "comparer",
    "interpreter",
    "poursuivre",
}
SITUATIONS_SPECIALES = {"hors_sujet", "absent_du_corpus", "demande_de_decision"}
THEMES = {"maladies", "eudr", "certification", "bonnes_pratiques", "indicateurs"}
CHAMPS = {
    "id",
    "theme",
    "type_demande",
    "situation",
    "avertissement_attendu",
    "historique",
    "question",
    "hors_corpus",
    "origine",
    "reponse_attendue",
    "doc_ids_attendus",
}


@pytest.fixture(scope="module")
def questions():
    chemin = get_settings().chemins.questions_eval
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


def test_champs_complets(questions):
    for q in questions:
        assert set(q) == CHAMPS, q["id"]


def test_identifiants_uniques(questions):
    doublons = [i for i, n in Counter(q["id"] for q in questions).items() if n > 1]
    assert doublons == []


def test_chaque_type_de_demande_est_teste(questions):
    presents = {q["type_demande"] for q in questions if q["situation"] == "normale"}
    assert TYPES_DEMANDE <= presents, TYPES_DEMANDE - presents


def test_chaque_situation_speciale_est_testee(questions):
    presentes = {q["situation"] for q in questions}
    assert SITUATIONS_SPECIALES <= presentes, SITUATIONS_SPECIALES - presentes


def test_chaque_theme_est_teste(questions):
    presents = {q["theme"] for q in questions if q["situation"] == "normale"}
    assert THEMES <= presents, THEMES - presents


def test_hors_corpus_coherent(questions):
    for q in questions:
        attendu = q["situation"] in {"hors_sujet", "absent_du_corpus"}
        assert q["hors_corpus"] is attendu, q["id"]


def test_poursuivre_a_un_historique(questions):
    for q in questions:
        if q["type_demande"] == "poursuivre":
            assert q["historique"], q["id"]
