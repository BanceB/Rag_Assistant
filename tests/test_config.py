"""Premiers tests automatiques : la configuration se charge et rejette les valeurs incohérentes."""

from dataclasses import replace

import pytest

from rag_assistant.config import _valider, load_settings


def test_settings_se_charge():
    s = load_settings()
    assert s.filiere == "cacao"
    assert s.namespace == "cacao"
    assert s.chunking.chunk_overlap < s.chunking.chunk_size
    assert s.retrieval.k <= s.retrieval.fetch_k


def test_chemins_absolus():
    s = load_settings()
    assert s.chemins.corpus.is_absolute()
    assert s.chemins.corpus.name == "corpus"


def test_chevauchement_trop_grand_refuse():
    s = load_settings()
    mauvais = replace(s, chunking=replace(s.chunking, chunk_overlap=s.chunking.chunk_size))
    with pytest.raises(ValueError):
        _valider(mauvais)


def test_temperature_hors_bornes_refusee():
    s = load_settings()
    mauvais = replace(s, llm=replace(s.llm, temperature=1.5))
    with pytest.raises(ValueError):
        _valider(mauvais)
