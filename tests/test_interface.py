"""Tests de l'étape 9 : l'interface Streamlit, sans appel à Voyage ni à Claude.

AppTest exécute les pages comme le ferait le navigateur. Un faux assistant (la vraie chaîne
avec un faux générateur, voir test_guardrails) remplace l'assistant configuré.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_guardrails import assistant, base  # noqa: F401  (fixture base)

from rag_assistant.app import affichage as aff
from rag_assistant.rag import guardrails as g

MAIN = str(Path(__file__).resolve().parents[1] / "src" / "rag_assistant" / "app" / "main.py")


# ------------------------------------------------------------------ texte pendant le flux


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("Ce sont des bandes rouges [1]. Et", "Ce sont des bandes rouges. Et"),
        ("Gonflement [1][2], puis [3", "Gonflement, puis"),
        ("AUCUNE_REP", ""),
        ("**HORS_SUJET**", ""),
        ("Réponse [1].\n\nETIQUETTES : couverture=complete", "Réponse."),
        ("Réponse [1].\n\nETIQ", "Réponse."),
        ("Respectez les étiquettes des produits [2].", "Respectez les étiquettes des produits."),
        ("Le prix est de 1 800 $ la tonne", r"Le prix est de 1 800 \$ la tonne"),
    ],
)
def test_texte_provisoire_cache_citations_etiquettes_et_mots_convenus(brut, attendu):
    assert aff.texte_provisoire(brut) == attendu


def test_sources_en_markdown_avec_lien_et_section():
    md = aff.sources_markdown(
        [{"numero": 1, "titre": "Guide", "organisme": "CNRA", "annee": "2021", "page": 4,
          "section": "Symptômes", "url": "https://exemple.ci/g"}]
    )  # fmt: skip
    assert md == "**[1]** [Guide](https://exemple.ci/g) — CNRA, 2021, p. 4  \n*Section : Symptômes*"
    assert aff.libelle_sources(1) == "1 source" and aff.libelle_sources(3) == "3 sources"


def test_limiteur_bloque_puis_libere():
    lim = aff.Limiteur(maximum=2, fenetre_s=3600)
    assert lim.autoriser(0) and lim.autoriser(10)
    assert not lim.autoriser(20) and lim.attente_minutes(20) == 60
    assert lim.autoriser(3601)  # la première question est sortie de la fenêtre


def test_mot_de_passe():
    assert aff.mot_de_passe_valide("secret", "secret")
    assert not aff.mot_de_passe_valide("Secret", "secret")
    assert not aff.mot_de_passe_valide("", None) and not aff.mot_de_passe_valide("x", None)


def test_suggestions_25_questions_du_jeu_d_evaluation():
    categories = aff.charger_suggestions()
    assert len(categories) == 5 and all(len(c.questions) == 5 for c in categories)
    assert all(qid.startswith("Q") for c in categories for qid, _ in c.questions)


# ------------------------------------------------------------------ pages


def lancer(faux_assistant=None) -> AppTest:
    at = AppTest.from_file(MAIN, default_timeout=30)
    if faux_assistant is not None:
        at.session_state["_assistant_test"] = faux_assistant
    return at.run()


def test_accueil_et_categories(base):  # noqa: F811
    a, _ = assistant(base, "nervures", "Swollen shoot [1].")
    at = lancer(a)
    assert not at.exception
    textes = " ".join(h.proto.body for h in at.get("html"))
    assert "quelle est votre question" in textes and "intelligence artificielle" in textes
    assert at.sidebar.selectbox[0].value == "agriculteur"  # profil par défaut
    assert len(at.sidebar.expander) == 5
    assert len([b for b in at.sidebar.button if b.key and b.key.startswith("suggestion_")]) == 25


def test_question_saisie_reponse_sourcee_puis_suivi(base):  # noqa: F811
    a, generateur = assistant(base, "nervures", "Ce sont des signes du swollen shoot [1].")
    at = lancer(a)
    at.chat_input[0].set_value("Bandes rouges le long des nervures ?").run()
    assert not at.exception
    messages = at.session_state["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    reponse = messages[1]["reponse"]
    assert not reponse["refus"] and reponse["sources"][0]["doc_id"] == "MAL-001"
    assert any("swollen shoot" in m.value for m in at.markdown)
    assert at.main.expander and at.main.expander[-1].label == "1 source"
    # deuxième question : l'historique est transmis au modèle
    at.chat_input[0].set_value("Et sur les nervures des feuilles âgées ?").run()
    assert len(at.session_state["messages"]) == 4
    assert len(generateur.appels[-1]) == 3  # question 1, réponse 1, question 2


def test_clic_sur_une_question_proposee(base):  # noqa: F811
    a, _ = assistant(base, "introuvable", "ne sert pas")
    at = lancer(a)
    at.sidebar.button(key="suggestion_maladies_Q005").click().run()
    assert not at.exception
    messages = at.session_state["messages"]
    assert messages[0]["texte"].startswith("Quelles plantes")
    assert messages[1]["reponse"]["refus"]  # le faux reranker ne trouve rien : refus poli
    assert any(g.REFUS_SOUS_SEUIL[:40] in i.value for i in at.info)


def test_nouvelle_conversation_vide_l_historique(base):  # noqa: F811
    a, _ = assistant(base, "nervures", "Swollen shoot [1].")
    at = lancer(a)
    at.chat_input[0].set_value("Bandes rouges ?").run()
    at.sidebar.button[0].click().run()  # « Nouvelle conversation »
    assert at.session_state["messages"] == []


def test_erreur_du_service_propose_de_reessayer(base):  # noqa: F811
    class EnPanne:
        def repondre(self, *args, **kwargs):
            raise ConnectionError("réseau coupé")

    at = lancer(EnPanne())
    at.chat_input[0].set_value("Bandes rouges ?").run()
    assert not at.exception and at.error and at.session_state["erreur"] == "Bandes rouges ?"
    assert any(b.label == "Réessayer" for b in at.button)


def test_admin_demande_un_mot_de_passe(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "essai-admin")
    at = AppTest.from_string(
        "from rag_assistant.app import admin\nadmin.page()", default_timeout=30
    ).run()
    assert not at.exception and at.text_input[0].label == "Mot de passe"
    entrer = [b for b in at.button if b.label == "Entrer"]
    at.text_input[0].input("faux")
    entrer[0].click().run()
    assert any("incorrect" in e.value for e in at.error)
    at.text_input[0].input("essai-admin")
    [b for b in at.button if b.label == "Entrer"][0].click().run()
    assert at.session_state["admin"] is True


def test_en_tete_sans_sous_titre_et_mode_clair(base):  # noqa: F811
    a, _ = assistant(base, "nervures", "Swollen shoot [1].")
    at = lancer(a)
    textes = " ".join(h.proto.body for h in at.get("html"))
    assert "Assistant cacao durable" in textes and 'class="sous-titre"' not in textes
    bouton = at.button(key="bascule_theme")
    assert bouton.label == "Mode clair"
    bouton.click().run()
    assert at.session_state["mode_clair"] is True and at.query_params["theme"] in (
        "clair",
        ["clair"],
    )
    assert at.button(key="bascule_theme").label == "Mode sombre"
    at.button(key="bascule_theme").click().run()
    assert at.session_state["mode_clair"] is False and "theme" not in at.query_params


def test_icones_colorees_selon_le_mode():
    from rag_assistant.app.chat import styles_icones

    categories = aff.charger_suggestions()
    assert all(c.couleur and c.couleur_clair for c in categories)
    sombre, clair = styles_icones(categories, False), styles_icones(categories, True)
    assert ".st-key-cat_maladies" in sombre and "#D2693C" in sombre and "#B4532A" in clair


def test_journal_sans_puis_avec_consentement(base, tmp_path):  # noqa: F811
    from rag_assistant.services.journal import Journal

    a, _ = assistant(base, "nervures", "Ce sont des signes du swollen shoot [1].")
    journal = Journal(tmp_path / "app.db")
    at = AppTest.from_file(MAIN, default_timeout=30)
    at.session_state["_assistant_test"] = a
    at.session_state["_journal_test"] = journal
    at.run()
    assert at.sidebar.toggle(key="consentement").value is False
    at.chat_input[0].set_value("Bandes rouges le long des nervures ?").run()
    premiere = journal.derniers()[0]
    assert premiere["question"] is None and premiere["nb_sources"] == 1
    assert premiere["session"] == at.session_state["session_id"]
    assert at.session_state["messages"][1]["journal_id"] == premiere["id"]

    at.sidebar.toggle(key="consentement").set_value(True).run()
    at.chat_input[0].set_value("Et sur les nervures âgées ?").run()
    seconde = journal.derniers()[0]
    assert seconde["question"] == "Et sur les nervures âgées ?" and seconde["suivi"] == 1


def test_panne_du_service_journalisee_sans_texte(tmp_path):
    from rag_assistant.services.journal import Journal

    class EnPanne:
        def repondre(self, *args, **kwargs):
            raise TimeoutError("trop long")

    journal = Journal(tmp_path / "app.db")
    at = AppTest.from_file(MAIN, default_timeout=30)
    at.session_state["_assistant_test"] = EnPanne()
    at.session_state["_journal_test"] = journal
    at.run()
    at.chat_input[0].set_value("Bandes rouges ?").run()
    ligne = journal.derniers()[0]
    assert ligne["erreur"] == "TimeoutError" and ligne["question"] is None


def test_avis_enregistre_dans_le_journal(base, tmp_path):  # noqa: F811
    from rag_assistant.services.journal import Journal

    a, _ = assistant(base, "nervures", "Swollen shoot [1].")
    journal = Journal(tmp_path / "app.db")
    at = AppTest.from_file(MAIN, default_timeout=30)
    at.session_state["_assistant_test"] = a
    at.session_state["_journal_test"] = journal
    at.run()
    at.chat_input[0].set_value("Bandes rouges le long des nervures ?").run()
    at.get("feedback")[0].set_value(1).run()  # 👍
    assert journal.derniers()[0]["avis"] == 1
    at.get("feedback")[0].set_value(0).run()  # 👎 : l'avis est remplacé
    assert journal.derniers()[0]["avis"] == 0
    assert journal.statistiques()["avis"] == 1


def test_tableau_de_bord_admin(tmp_path, monkeypatch):
    from rag_assistant.services.journal import Journal

    journal = Journal(tmp_path / "app.db")
    journal.noter(
        journal.enregistrer("s1", {"question": "Q", "texte": "R [1]", "refus": False,
                                   "sources": [{"doc_id": "MAL-001", "page": 2}],
                                   "latences": {"total": 3.0}}, consentement=True), 1)  # fmt: skip
    journal.enregistrer("s2", {"question": "Qui a gagné la CAN ?", "refus": True,
                               "motif": "sous_le_seuil", "latences": {"total": 0.4}})  # fmt: skip
    at = AppTest.from_string(
        "from rag_assistant.app import admin\nadmin.page()", default_timeout=30
    )
    at.session_state["admin"] = True
    at.session_state["_journal_test"] = journal
    at.run()
    assert not at.exception
    valeurs = {m.label: m.value for m in at.metric}
    assert valeurs["Réponses sourcées"] == "100 %" and valeurs["Réponses jugées utiles"] == "100 %"
    assert valeurs["Questions"] == "2" and valeurs["Refus"] == "1" and valeurs["Sessions"] == "2"
    tableau = at.dataframe[2].value  # refus, documents, dernières questions
    assert list(tableau["Question"]) == ["(non partagée)", "Q"]


def test_cache_reponse_instantanee_puis_secours_en_panne(base, tmp_path):  # noqa: F811
    from rag_assistant.services.cache import CacheReponses
    from rag_assistant.services.journal import Journal

    a, generateur = assistant(base, "nervures", "Ce sont des signes du swollen shoot [1].")
    cache, journal = CacheReponses(tmp_path / "app.db"), Journal(tmp_path / "app.db")

    def ouvrir(un_assistant):
        at = AppTest.from_file(MAIN, default_timeout=30)
        at.session_state["_assistant_test"] = un_assistant
        at.session_state["_cache_test"] = cache
        at.session_state["_journal_test"] = journal
        return at.run()

    question = "Bandes rouges le long des nervures ?"
    at = ouvrir(a)
    at.chat_input[0].set_value(question).run()
    assert len(generateur.appels) == 1 and cache.statistiques()["reponses"] == 1

    # nouvel onglet, même question : réponse du cache, sans appeler le modèle
    at = ouvrir(a)
    at.chat_input[0].set_value(question).run()
    assert len(generateur.appels) == 1
    assert any("Réponse déjà donnée" in c.value for c in at.caption)

    # service en panne : la réponse gardée est servie en secours
    class EnPanne:
        recuperateur = a.recuperateur

        def repondre(self, *args, **kwargs):
            raise ConnectionError("réseau coupé")

    cache.vider()
    cache.ecrire(
        question, "agriculteur", "ancienne-version", at.session_state["messages"][1]["reponse"]
    )
    at = ouvrir(EnPanne())
    at.chat_input[0].set_value(question).run()
    assert not at.error and any("ne répond pas" in c.value for c in at.caption)
    stats = journal.statistiques()
    assert (stats["depuis_cache"], stats["secours"], stats["erreurs"]) == (1, 1, 0)


def test_bouton_suggestion_dans_l_en_tete_du_chat_seulement(base, monkeypatch):  # noqa: F811
    a, _ = assistant(base, "nervures", "Swollen shoot [1].")
    at = lancer(a)
    assert at.button(key="bouton_suggestion").label == "Suggestion"
    monkeypatch.setenv("ADMIN_PASSWORD", "essai-admin")
    admin = AppTest.from_string("from rag_assistant.app import admin\nadmin.page()").run()
    assert all(b.key != "bouton_suggestion" for b in admin.button)
