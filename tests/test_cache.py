"""Tests de l'étape 10 (F8) : cache des réponses fréquentes."""

from datetime import timedelta

import pytest

from rag_assistant.services import cache as c


def reponse(refus=False, sources=True):
    return {
        "question": "Comment reconnaître le swollen shoot ?",
        "texte": "Bandes rouges le long des nervures [1].",
        "sources": [{"doc_id": "MAL-001", "page": 4}] if sources else [],
        "refus": refus,
        "passages": [["MAL-001-p004-c00", 0.9]],
        "latences": {"total": 4.2},
        "usage": {"entree": 1200, "sortie": 80},
    }


@pytest.fixture
def cache(tmp_path):
    return c.CacheReponses(tmp_path / "app.db", duree_jours=30)


def test_normalisation_des_questions():
    assert c.normaliser("  Comment  reconnaître le Swollen Shoot ?? ") == (
        "comment reconnaître le swollen shoot"
    )
    assert c.cle("Qu’est-ce que l’EUDR ?", None) == c.cle("qu'est-ce que l'eudr", None)
    assert c.cle("Question", "agriculteur") != c.cle("Question", "technicien")


def test_lecture_apres_ecriture_sans_attente_ni_tokens(cache):
    assert cache.ecrire("Comment reconnaître le swollen shoot ?", "agriculteur", "v1", reponse())
    lue = cache.lire("comment reconnaître le SWOLLEN shoot", "agriculteur", "v1")
    assert lue["texte"].startswith("Bandes rouges") and lue["depuis_cache"]["secours"] is False
    assert lue["question"] == "comment reconnaître le SWOLLEN shoot"
    assert lue["latences"] == {"total": 0.0} and lue["usage"] == {} and "passages" not in lue
    assert cache.statistiques() == {"reponses": 1, "utilisations": 1}


def test_refus_et_reponses_sans_source_ne_sont_pas_gardes(cache):
    assert not cache.ecrire("Qui a gagné la CAN ?", None, "v1", reponse(refus=True))
    assert not cache.ecrire("Question", None, "v1", reponse(sources=False))
    assert cache.statistiques()["reponses"] == 0


def test_nouvelle_version_ou_reponse_trop_vieille_ignorees_sauf_en_secours(cache, monkeypatch):
    cache.ecrire("Question", None, "v1", reponse())
    assert cache.lire("Question", None, "v2") is None  # corpus réindexé, prompt changé…
    assert cache.lire("Question", None, "v2", secours=True)["depuis_cache"]["secours"] is True
    plus_tard = c.maintenant() + timedelta(days=31)
    monkeypatch.setattr(c, "maintenant", lambda: plus_tard)
    assert cache.lire("Question", None, "v1") is None
    assert cache.lire("Question", None, "v1", secours=True) is not None


def test_vider(cache):
    cache.ecrire("Question", None, "v1", reponse())
    assert cache.vider() == 1 and cache.lire("Question", None, "v1") is None


def test_prechauffage_s_arrete_proprement_sans_reseau(tmp_path, monkeypatch, capsys):
    """Coupure de connexion : 3 échecs de suite, puis arrêt avec un message (pas de trace)."""
    from dataclasses import replace
    from types import SimpleNamespace

    from rag_assistant import config
    from rag_assistant.app import affichage
    from rag_assistant.rag import chain

    class SansReseau:
        def repondre(self, *args):
            raise TimeoutError("api.voyageai.com ne répond pas")

    reglages = config.get_settings()
    reglages = replace(reglages, chemins=replace(reglages.chemins, base_sqlite=tmp_path / "a.db"))
    questions = [(f"S{i}", f"Question {i} ?") for i in range(5)]
    monkeypatch.setattr(config, "get_settings", lambda: reglages)
    monkeypatch.setattr(chain, "creer_assistant", lambda s: SansReseau())
    monkeypatch.setattr(
        affichage, "charger_suggestions", lambda: [SimpleNamespace(questions=questions)]
    )
    assert c.prechauffer() == 0
    sortie = capsys.readouterr().out
    assert sortie.count(" échec :") == c.ECHECS_AVANT_ARRET and "S3" not in sortie
    assert "vérifiez la connexion internet" in sortie


def test_delai_court_pour_voyage():
    from rag_assistant.ingestion.indexer import DELAI_RESEAU_S, client_voyage

    client = client_voyage()
    assert client._params["request_timeout"] == DELAI_RESEAU_S < 60
    assert client is client_voyage()  # un seul client pour toute l'application


# ------------------------------------------------------------------ remplissage depuis /admin


class FauxAssistant:
    """Répond tout de suite ; refuse les questions qui contiennent « CAN »."""

    def __init__(self, attente=0.0):
        self.appels, self.attente = [], attente

    def repondre(self, question, historique, profil):
        import time
        from types import SimpleNamespace

        time.sleep(self.attente)
        self.appels.append((question, profil))
        refus = "CAN" in question
        return SimpleNamespace(en_dict=lambda: reponse(refus=refus) | {"question": question})


QUESTIONS = [("Q1", "Question une ?"), ("Q2", "Question deux ?"), ("Q3", "Qui a gagné la CAN ?")]


def test_compter_par_profil_et_remplir_seulement_les_manquantes(cache):
    a = FauxAssistant()
    version = c.version_assistant(a)
    cache.ecrire("Question une ?", "technicien", version, reponse())
    textes = [t for _, t in QUESTIONS]
    assert cache.compter(textes, ["technicien", None], version) == {"technicien": 1, None: 0}

    etats = []
    gardees, interrompu = c.remplir(
        "technicien", a, cache, QUESTIONS, seulement_manquantes=True,
        sur_question=lambda qid, t, etat, d: etats.append((qid, etat)),
    )  # fmt: skip
    assert (gardees, interrompu) == (1, False)
    assert etats == [("Q1", "deja"), ("Q2", "gardee"), ("Q3", "non_gardee")]
    assert [q for q, _ in a.appels] == ["Question deux ?", "Qui a gagné la CAN ?"]
    assert cache.compter(textes, ["technicien"], version) == {"technicien": 2}


def test_remplissage_en_arriere_plan_puis_arret(cache):
    travail = c.Prechauffage()
    assert travail.lancer(FauxAssistant(), cache, ["cooperative", None], QUESTIONS)
    for _ in range(200):
        if not travail.etat()["en_cours"]:
            break
        import time

        time.sleep(0.02)
    etat = travail.etat()
    assert not etat["en_cours"] and not etat["interrompu"] and etat["fin"]
    assert (etat["total"], etat["faites"], etat["gardees"], etat["non_gardees"]) == (6, 6, 4, 2)

    # arrêt demandé pendant le remplissage : il s'arrête, sans rester « en cours »
    lent = FauxAssistant(attente=0.05)
    assert travail.lancer(lent, cache, ["etudiant_chercheur"], QUESTIONS * 20, False)
    assert not travail.lancer(lent, cache, ["etudiant_chercheur"], QUESTIONS)  # un seul à la fois
    travail.arreter()
    for _ in range(200):
        if not travail.etat()["en_cours"]:
            break
        import time

        time.sleep(0.02)
    etat = travail.etat()
    assert etat["arrete_par_l_equipe"] and etat["interrompu"] and etat["faites"] < 60
