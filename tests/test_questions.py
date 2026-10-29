"""Vérifie que le jeu de questions est bien formé et couvre tout le périmètre de l'agent.

Le périmètre est défini dans docs/specs_techniques.md, section « Périmètre fonctionnel ».
"""

import json
from collections import Counter

import pytest

from rag_assistant.catalogue import lire_catalogue
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
TYPES_SPECIAUX = {"hors_perimetre", "decision"}
SITUATIONS_SPECIALES = {"hors_sujet", "absent_du_corpus", "demande_de_decision"}
THEMES = {"maladies", "eudr", "certification", "bonnes_pratiques", "indicateurs"}
ACTEURS = {"agriculteur", "cooperative", "technicien", "partie_prenante", "etudiant_chercheur"}
CHAMPS = {
    "id",
    "acteur",
    "theme",
    "type_demande",
    "situation",
    "avertissement_attendu",
    "historique",
    "question",
    "hors_corpus",
    "origine",
    "reponse_attendue",
    "preuves",
    "doc_ids_attendus",
}


@pytest.fixture(scope="module")
def questions():
    chemin = get_settings().chemins.questions_eval
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


@pytest.fixture(scope="module")
def docs_valides():
    entrees = lire_catalogue(get_settings().chemins.catalogue)
    return {e.doc_id for e in entrees if e.statut == "valide"}


def test_champs_complets(questions):
    for q in questions:
        assert set(q) == CHAMPS, q["id"]


def test_identifiants_et_questions_uniques(questions):
    for cle in ("id", "question"):
        doublons = [v for v, n in Counter(q[cle] for q in questions).items() if n > 1]
        assert doublons == [], cle


def test_valeurs_autorisees(questions):
    for q in questions:
        assert q["acteur"] in ACTEURS, q["id"]
        assert q["theme"] in THEMES | {"hors_sujet"}, q["id"]
        assert q["type_demande"] in TYPES_DEMANDE | TYPES_SPECIAUX, q["id"]
        assert q["situation"] in SITUATIONS_SPECIALES | {"normale"}, q["id"]


def test_chaque_type_de_demande_est_teste(questions):
    presents = {q["type_demande"] for q in questions if q["situation"] == "normale"}
    assert TYPES_DEMANDE <= presents, TYPES_DEMANDE - presents


def test_chaque_situation_speciale_est_testee(questions):
    presentes = {q["situation"] for q in questions}
    assert SITUATIONS_SPECIALES <= presentes, SITUATIONS_SPECIALES - presentes


def test_chaque_theme_est_teste(questions):
    presents = {q["theme"] for q in questions if q["situation"] == "normale"}
    assert THEMES <= presents, THEMES - presents


def test_chaque_acteur_est_represente_et_agriculteurs_majoritaires(questions):
    compte = Counter(q["acteur"] for q in questions)
    assert set(compte) == ACTEURS
    assert compte["agriculteur"] > len(questions) / 2


def test_hors_corpus_coherent(questions):
    for q in questions:
        attendu = q["situation"] in {"hors_sujet", "absent_du_corpus"}
        assert q["hors_corpus"] is attendu, q["id"]


def test_poursuivre_a_un_historique(questions):
    for q in questions:
        if q["type_demande"] == "poursuivre":
            assert q["historique"], q["id"]


def test_questions_normales_ont_des_preuves(questions):
    for q in questions:
        if q["situation"] == "normale":
            assert q["preuves"] and q["reponse_attendue"], q["id"]
        if q["hors_corpus"]:
            assert q["preuves"] == [] and q["doc_ids_attendus"] == [], q["id"]


def test_doc_ids_coherents_avec_le_catalogue(questions, docs_valides):
    for q in questions:
        depuis_preuves = list(dict.fromkeys(p["doc_id"] for p in q["preuves"]))
        assert q["doc_ids_attendus"] == depuis_preuves, q["id"]
        assert set(q["doc_ids_attendus"]) <= docs_valides, q["id"]
        for p in q["preuves"]:
            assert p["page"] >= 1 and p["extrait"].strip(), q["id"]
