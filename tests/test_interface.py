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
