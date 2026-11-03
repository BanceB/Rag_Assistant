"""Tests de l'étape 8 : mémoire par session, fenêtre glissante, reformulation des questions de
suivi, historique transmis au modèle et données de l'évaluation."""

import json

from test_guardrails import FauxGenerateur, assistant, base  # noqa: F401  (fixture base)

from rag_assistant.config import get_settings
from rag_assistant.evaluation.memoire import analyser_suivis, rang_attendu
from rag_assistant.evaluation.recherche import lire_questions
from rag_assistant.rag.chain import Conversation, messages_d_historique
from rag_assistant.rag.memory import Memoire, Reformulateur, formater_historique


def test_memoire_par_session_et_fenetre_glissante():
    m = Memoire(fenetre=4)
    for i in range(3):
        m.ajouter("awa", "user", f"question {i}")
        m.ajouter("awa", "assistant", f"réponse {i}")
    m.ajouter("kouame", "user", "autre personne")
    assert [x["content"] for x in m.historique("awa")] == [
        "question 1", "réponse 1", "question 2", "réponse 2",
    ]  # fmt: skip
    assert m.historique("kouame") == [{"role": "user", "content": "autre personne"}]
    m.effacer("awa")
    assert m.historique("awa") == []


def test_memoire_bornee_en_nombre_de_sessions():
    m = Memoire(fenetre=2, sessions_max=2)
    for s in ("a", "b", "c"):
        m.ajouter(s, "user", "q")
    assert m.historique("a") == [] and m.historique("c")


def test_reformulation_seulement_avec_un_historique():
    rapide = FauxGenerateur("Qui paie la prime du cacao certifié ARS 1000 ?")
    r = Reformulateur(rapide)
    assert r([], "Et c'est qui qui la paie ?") == "Et c'est qui qui la paie ?"
    assert rapide.appels == []
    historique = [{"role": "user", "content": "C'est quoi la prime ARS 1000 ?"}]
    assert (
        r(historique, "Et c'est qui qui la paie ?")
        == "Qui paie la prime du cacao certifié ARS 1000 ?"
    )
    assert "<conversation>" in rapide.appels[0][0]["content"]


def test_reformulation_nettoyee_et_garde_fou():
    historique = [{"role": "user", "content": "q"}]
    assert (
        Reformulateur(FauxGenerateur("Question réécrite : « Quand ? »\n"))(historique, "Et ?")
        == "Quand ?"
    )
    assert Reformulateur(FauxGenerateur(""))(historique, "Et ça ?") == "Et ça ?"
    assert Reformulateur(FauxGenerateur("x" * 500))(historique, "Et ça ?") == "Et ça ?"


def test_historique_sans_citations_ni_reponse_trop_longue():
    texte = formater_historique(
        [{"role": "assistant", "content": "Le virus [1][2]. " + "a " * 400}]
    )
    assert "[1]" not in texte and texte.endswith("…") and len(texte) < 650


def test_messages_d_historique_alternes_et_commencent_par_la_personne():
    messages = messages_d_historique(
        [
            {"role": "assistant", "content": "réponse orpheline"},
            {"role": "user", "content": "q1"},
            {"role": "user", "content": "q2"},
        ],
        fenetre=6,
    )
    assert messages == [
        {"role": "user", "content": "q1\n\nq2"},
        {"role": "assistant", "content": "(pas de réponse)"},
    ]


def test_conversation_reformule_le_suivi_pour_la_recherche(base):  # noqa: F811
    a, generateur = assistant(base, "nervures", "Réponse [1].")
    rapide = FauxGenerateur("Comment se transmettent les bandes rouges sur les nervures ?")
    a.reformulateur = Reformulateur(rapide)
    conversation = Conversation(a, Memoire(fenetre=6))
    premiere = conversation.poser("s1", "bandes rouges sur les nervures ?")
    assert premiere.question_recherche == premiere.question and rapide.appels == []
    suivi = conversation.poser("s1", "Et comment ça se transmet ?")
    assert suivi.question_recherche.startswith("Comment se transmettent")
    assert "reformulation" in suivi.latences
    dernier = generateur.appels[-1]
    assert [m["role"] for m in dernier] == ["user", "assistant", "user"]
    assert "Compte tenu de la conversation" in dernier[-1]["content"]


def test_analyse_des_suivis():
    def cas(docs, chunks):
        return {
            "docs": docs,
            "chunks": chunks,
            "pertinent": True,
            "texte": "",
            "meilleur_score": 0.5,
        }

    lignes = [
        {"id": "Q1", "attendus": ["A"], "duree_reformulation": 0.4,
         "seule": cas(["B"] * 4, list("wxyz")), "reformulee": cas(["A"] * 4, list("abcd")),
         "complete": cas(["A"] * 4, list("abce"))},
    ]  # fmt: skip
    r = analyser_suivis(lignes)
    assert r["seule"]["rappel@4"] == 0 and r["reformulee"]["rappel@4"] == 1
    assert r["reformulee"]["passages_communs_avec_complete"] == 0.75
    assert rang_attendu(["B", "A"], ["A"]) == 2


def test_chaque_question_de_suivi_a_sa_version_complete():
    chemin = get_settings().chemins.questions_eval.parent / "dialogues.json"
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    suivis = {q["id"] for q in lire_questions() if q["historique"]}
    assert suivis == set(donnees["completes"])
    assert len(donnees["dialogues"]) == 5 and all(
        len(d["tours"]) == 3 for d in donnees["dialogues"]
    )
