"""Tests du second tour de relecture (page avant / après)."""

from rag_assistant.evaluation import relecture as r


def test_page_avant_apres_et_longueurs():
    q = [{"id": "Q010", "question": "Tache brune ?", "acteur": "agriculteur"}]
    avant = {"Q010": {"texte": "Un deux trois [1].", "avertissements": []}}
    apres = {"Q010": {"texte": "Un deux [1].", "avertissements": ["Avant tout traitement…"]}}
    texte = r.page(q, avant, apres)
    assert "Longueur totale : 3 mots avant, 2 mots après." in texte
    assert "**Avant** (3 mots)" in texte and "**Après** (2 mots)" in texte
    assert "> Avertissement affiché : Avant tout traitement…" in texte
    assert len(r.RELUES) == 10
