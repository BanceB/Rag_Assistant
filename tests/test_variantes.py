"""Tests de l'étape 11 : variantes de réglages comparées (sans appel aux API)."""

from pathlib import Path

import pytest

from rag_assistant.config import get_settings
from rag_assistant.evaluation import variantes as v


def test_chaque_variante_ne_change_qu_un_reglage():
    s = get_settings()
    assert v.appliquer(s, "reference") is s
    assert v.appliquer(s, "haiku").llm.model == s.llm.model_rapide
    assert v.appliquer(s, "haiku").retrieval == s.retrieval
    assert v.appliquer(s, "sonnet").llm.model == "claude-sonnet-5-5"
    assert v.appliquer(s, "effort_medium").llm.effort == "medium"
    assert v.appliquer(s, "k3").retrieval.k == 3 and v.appliquer(s, "k3").llm == s.llm
    assert v.appliquer(s, "court") is s and "au plus 70 mots" in v.consignes("court")
    assert v.consignes("reference") is None
    with pytest.raises(ValueError):
        v.appliquer(s, "inconnue")


def enregistrement(i, situation="normale", refus=False, total=3.0, motif=None):
    return {
        "id": f"Q{i:03d}", "acteur": "agriculteur", "theme": "maladies", "situation": situation,
        "avertissement_attendu": False, "doc_ids_attendus": ["MAL-001"],
        "question": "?", "texte": "R [1]", "refus": refus, "motif": motif,
        "couverture": "complete", "avertissements": [],
        "sources": [] if refus else [{"doc_id": "MAL-001", "page": 1}],
        "latences": {"total": total, "premier_mot": 1.5},
        "usage": {"entree": 2000, "sortie": 100},
    }  # fmt: skip


def test_mesures_et_tableau():
    e = [
        enregistrement(1, total=3.0),
        enregistrement(2, total=6.5),
        enregistrement(3, "hors_sujet", refus=True, total=0.4, motif="sous_le_seuil"),
    ]
    sonnet = v.mesures(e, "claude-sonnet-5-5")
    haiku = v.mesures(e, "claude-haiku-5-5")
    assert sonnet["sous_5s"] == 0.5 and sonnet["plus_de_5s"] == 1
    assert sonnet["cout_usd"] == round((6000 * 2 + 300 * 10) / 1e6, 3)
    assert haiku["cout_usd"] < sonnet["cout_usd"]
    texte = v.tableau({"reference": sonnet, "haiku": haiku})
    assert texte.splitlines()[0] == "| Mesure | reference | haiku |"
    assert "| Réponses en 5 s ou moins (cible) | 50% | 50% |" in texte


def test_nom_retrouve_dans_le_fichier(tmp_path):
    assert (
        v.nom_de_fichier(Path("variante_effort_medium_2026-11-06_10h00.jsonl")) == "effort_medium"
    )
    resumes = {"reference": v.mesures([enregistrement(1)], "claude-sonnet-5-5")}
    v.ecrire_comparaison(resumes, tmp_path / "c.md")
    assert "**reference**" in (tmp_path / "c.md").read_text(encoding="utf-8")


def test_haiku_sans_reflexion_between_tools():
    from rag_assistant.rag.chain import reflexion_pour

    assert reflexion_pour("claude-haiku-5-5") == "disabled"
    assert reflexion_pour("claude-sonnet-5-5") == "between_tools"


def test_modele_retrouve_pour_le_cout():
    assert v.modele_de([{"modele": "claude-haiku-5-5"}], "reference") == "claude-haiku-5-5"
    assert v.modele_de([{}], "reference") == "claude-sonnet-5-5"  # fichiers d'avant D15
    assert v.modele_de([{}], "haiku") == "claude-haiku-5-5"
