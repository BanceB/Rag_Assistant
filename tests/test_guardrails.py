"""Tests de l'étape 7 : garde-fous, citations, sources, avertissements et chaîne complète.

Un faux modèle d'embedding, un faux reranker et un faux générateur remplacent Voyage et
Claude : on teste la logique de la chaîne, pas la qualité des réponses
(mesurée par `rag_assistant.evaluation.reponses`).
"""

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from rag_assistant.evaluation.reponses import analyser, echantillon
from rag_assistant.ingestion.indexer import indexer
from rag_assistant.rag import guardrails as g
from rag_assistant.rag import prompts
from rag_assistant.rag.chain import Assistant, GenerateurClaude
from rag_assistant.rag.retriever import Recuperateur


def chunk(doc_id, page, texte, theme="maladies", index=0):
    return Document(
        page_content=f"En-tête\n\n{texte}",
        metadata={
            "doc_id": doc_id, "page": page, "chunk_index": index,
            "chunk_id": f"{doc_id}-p{page:03d}-c{index:02d}", "theme": theme,
            "titre": f"Titre {doc_id}", "organisme": "CNRA", "date": "2021-05",
            "url_source": f"https://exemple.ci/{doc_id}", "section": "Symptômes",
            "en_tete": "En-tête",
        },
    )  # fmt: skip


CHUNKS = [
    chunk("MAL-001", 1, "Bandes rouges le long des nervures des jeunes feuilles."),
    chunk("MAL-001", 1, "Gonflement des rameaux et des gourmands.", index=1),
    chunk("MAL-002", 2, "Utiliser un fongicide homologué contre la pourriture brune."),
    chunk("EUDR-001", 17, "Le cacao doit être zéro déforestation.", theme="eudr"),
]


# ---------------------------------------------------------------- citations et sources


def test_numeros_cites_dans_l_ordre_de_lecture():
    assert g.numeros_cites("Oui [2]. Et aussi [1][2], voire [3, 1].") == [2, 1, 3]


def test_sources_renumerotees_fusionnees_et_numeros_inventes_retires():
    texte, sources = g.construire_sources(
        "Bandes rouges [2]. Rameaux gonflés [1]. Inventé [9]. Fongicide [3].", CHUNKS
    )
    # [2] et [1] sont la même page du même document : une seule source
    assert texte == "Bandes rouges [1]. Rameaux gonflés [1]. Inventé. Fongicide [2]."
    assert [(s.numero, s.doc_id, s.page) for s in sources] == [(1, "MAL-001", 1), (2, "MAL-002", 2)]
    assert (
        sources[0].en_texte() == "[1] Titre MAL-001 — CNRA, 2021, p. 1. https://exemple.ci/MAL-001"
    )


def test_reponses_convenues():
    assert g.reponse_convenue("AUCUNE_REPONSE") == "aucune_reponse"
    assert g.reponse_convenue("**HORS_SUJET**") == "hors_sujet"
    assert g.reponse_convenue("Le swollen shoot [1].") is None


def test_refus_avant_le_modele():
    assert g.refus_avant_llm(0.39, 0.40, 4) == g.REFUS_SOUS_SEUIL
    assert g.refus_avant_llm(0.80, 0.40, 0) == g.REFUS_SOUS_SEUIL
    assert g.refus_avant_llm(0.41, 0.40, 4) is None
    assert g.refus_avant_llm(0.10, None, 4) is None  # sans seuil, on laisse décider le modèle


@pytest.mark.parametrize(
    "question, reponse, chunks, attendus",
    [
        ("Quel fongicide utiliser ?", "Un fongicide homologué [1].", [], ["traitement"]),
        ("Mon cacao est-il conforme ?", "Il faut trois conditions [1].", [], ["conformite"]),
        ("C'est quoi la zéro déforestation ?", "Explication [1].", [CHUNKS[3]], ["conformite"]),
        ("Combien coûte un audit ARS 1000 ?", "Le coût [1].", [], ["certification"]),
        ("Comment faire une pépinière ?", "Il faut 65 m2 [1].", [CHUNKS[0]], []),
    ],
)
def test_avertissements(question, reponse, chunks, attendus):
    assert g.avertissements(question, reponse, chunks) == [g.AVERTISSEMENTS[a] for a in attendus]


def test_lire_etiquettes():
    texte = "Réponse [1].\n\nETIQUETTES : couverture=partielle ; avertissement=conformité"
    assert g.lire_etiquettes(texte) == ("Réponse [1].", "partielle", "conformite")
    assert g.lire_etiquettes("**ETIQUETTES** : avertissement=bidon")[1:] == ("complete", None)
    assert g.lire_etiquettes("Réponse sans étiquette [1].") == (
        "Réponse sans étiquette [1].", "complete", None,
    )  # fmt: skip


def test_avertissement_choisi_par_le_modele_et_filet_pour_les_produits_chimiques():
    eudr = [CHUNKS[3]]
    assert g.avertissements("Que dit la FAQ ?", "Elle explique [1].", eudr, "aucun") == []
    assert g.avertissements("Dois-je replanter ?", "Les critères [1].", [], "decision") == [
        g.AVERTISSEMENTS["decision"]
    ]
    assert g.avertissements("Comment lutter ?", "Un insecticide [1].", [], "aucun") == [
        g.AVERTISSEMENTS["traitement"]
    ]


def test_prompt_numerote_les_passages_sans_l_en_tete_du_chunk():
    message = prompts.message_utilisateur("Quels symptômes ?", CHUNKS[:2], profil="agriculteur")
    assert "[1] Titre MAL-001 (CNRA, 2021), page 1, section « Symptômes »" in message
    assert "[2] Titre MAL-001" in message and "En-tête" not in message
    assert "agriculteur" in message and message.endswith("Question : Quels symptômes ?")


# ---------------------------------------------------------------- chaîne complète


@pytest.fixture
def base(tmp_path):
    base = Chroma(
        collection_name="test",
        embedding_function=DeterministicFakeEmbedding(size=16),
        persist_directory=str(tmp_path / "chroma"),
        collection_metadata={"hnsw:space": "cosine"},
    )
    indexer(CHUNKS, base)
    return base


def reranker_par_mot(mot):
    def reranker(question, textes, top_k):
        scores = sorted(((i, 0.9 if mot in t else 0.1) for i, t in enumerate(textes)),
                        key=lambda x: -x[1])  # fmt: skip
        return scores[:top_k] if top_k else scores

    return reranker


class FauxGenerateur:
    def __init__(self, reponse):
        self.reponse, self.appels = reponse, []

    def __call__(self, systeme, messages):
        self.appels.append(messages)
        return self.reponse, {"entree": 100, "sortie": 20}


def assistant(base, mot, reponse):
    rec = Recuperateur(base, reranker_par_mot(mot), k=2, fetch_k=4, seuil=0.40)
    generateur = FauxGenerateur(reponse)
    return Assistant(rec, generateur), generateur


def test_question_hors_sujet_refusee_sans_appeler_le_modele(base):
    a, generateur = assistant(base, "introuvable", "ne doit pas servir")
    r = a.repondre("Qui a gagné la CAN ?")
    assert r.refus and r.motif == "sous_le_seuil" and r.texte == g.REFUS_SOUS_SEUIL
    assert generateur.appels == [] and r.sources == []


def test_question_du_corpus_obtient_au_moins_une_source(base):
    a, _ = assistant(base, "nervures", "Ce sont des signes du swollen shoot [1].")
    r = a.repondre("Mes feuilles ont des bandes rouges le long des nervures")
    assert not r.refus and r.sources and r.sources[0].doc_id == "MAL-001"
    assert "Sources :\n[1] Titre MAL-001" in r.en_texte()
    assert set(r.latences) == {"recherche", "generation", "total"}


@pytest.mark.parametrize(
    "reponse, motif, texte",
    [
        ("AUCUNE_REPONSE", "aucune_reponse", g.REFUS_ABSENT),
        ("HORS_SUJET", "hors_sujet", g.REFUS_HORS_SUJET),
        ("Une réponse sans aucune citation.", "sans_citation", g.REFUS_ABSENT),
        ("Une citation inventée [7].", "sans_citation", g.REFUS_ABSENT),
    ],
)
def test_garde_fous_apres_le_modele(base, reponse, motif, texte):
    a, _ = assistant(base, "nervures", reponse)
    r = a.repondre("bandes rouges sur les nervures")
    assert r.refus and r.motif == motif and r.texte == texte


def test_etiquettes_lues_et_retirees(base):
    a, _ = assistant(
        base,
        "nervures",
        "Les documents ne précisent pas le prix [1].\nETIQUETTES : couverture=partielle ; "
        "avertissement=traitement",
    )
    r = a.repondre("bandes rouges sur les nervures")
    assert not r.refus and r.couverture == "partielle"
    assert "ETIQUETTES" not in r.texte and r.avertissements == [g.AVERTISSEMENTS["traitement"]]


def test_reponse_convenue_suivie_d_etiquettes(base):
    a, _ = assistant(base, "nervures", "AUCUNE_REPONSE\nETIQUETTES : couverture=partielle")
    assert a.repondre("bandes rouges sur les nervures").motif == "aucune_reponse"


def test_historique_transmis_au_modele(base):
    a, generateur = assistant(base, "nervures", "Réponse [1].")
    historique = [
        {"role": "user", "content": "J'ai des bandes rouges."},
        {"role": "assistant", "content": "C'est peut-être le swollen shoot [1]."},
    ]
    a.repondre("Et sur les nervures ?", historique=historique)
    messages = generateur.appels[0]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert "<passages>" in messages[-1]["content"]


def test_generateur_claude_n_envoie_pas_de_temperature_et_lit_le_flux():
    envoye, recus = {}, []

    class Flux:
        text_stream = ["Réponse ", "[1]."]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_final_message(self):
            from types import SimpleNamespace as N

            return N(usage=N(input_tokens=10, output_tokens=3))

    class FauxClient:
        class messages:  # noqa: N801
            @staticmethod
            def stream(**kwargs):
                envoye.update(kwargs)
                return Flux()

    generateur = GenerateurClaude("claude-sonnet-5-5", "low", 512, client=FauxClient())
    texte, usage = generateur("s", [], au_fil=recus.append)
    assert texte == "Réponse [1]." and recus == ["Réponse ", "[1]."]
    assert usage["entree"] == 10 and usage["sortie"] == 3 and "premier_mot_s" in usage
    assert "temperature" not in envoye and envoye["output_config"] == {"effort": "low"}
    assert envoye["thinking"] == {"type": "between_tools"}


def test_partielle_seulement_si_la_reponse_le_dit_d_emblee():
    assert g.est_partielle("Les documents ne précisent pas le prix. Mais [1].", "partielle")
    assert not g.est_partielle("La maladie est [1]. Les documents ne précisent pas…", "partielle")
    assert not g.est_partielle("Les documents ne précisent pas le prix [1].", "complete")


# ---------------------------------------------------------------- évaluation des réponses


def test_echantillon_et_analyse():
    questions = [
        {"id": f"Q{i:03d}", "situation": s, "theme": t, "historique": [], "acteur": "agriculteur"}
        for i, (s, t) in enumerate(
            [("normale", "maladies")] * 5 + [("normale", "eudr")] * 5 + [("hors_sujet", "x")] * 2
        )
    ]
    choisies = echantillon(questions, normales=4)
    assert len(choisies) == 6 and sum(q["theme"] == "eudr" for q in choisies) == 2

    def e(situation, refus, sources=(), attendu=False, avert=()):
        return {"id": "Q", "situation": situation, "refus": refus, "motif": "x" if refus else None,
                "sources": [{"doc_id": d} for d in sources], "doc_ids_attendus": ["A"],
                "avertissement_attendu": attendu, "avertissements": list(avert),
                "latences": {"total": 2.0}, "usage": {"entree": 1000, "sortie": 100}}  # fmt: skip

    partielle = e("absent_du_corpus", False, ["B"])
    partielle["couverture"] = "partielle"
    r = analyser(
        [
            e("hors_sujet", True),
            e("absent_du_corpus", False, ["B"]),
            partielle,
            e("normale", False, ["A"], attendu=True, avert=["!"]),
            e("normale", False, ["B"]),
        ]
    )
    assert r["hors_sujet_refusees"] == 1.0 and r["absentes_refusees"] == 0.0
    assert r["absentes_detectees"] == 0.5 and r["hors_corpus_detectees"] == pytest.approx(2 / 3)
    assert r["source_attendue_citee"] == 0.5
    assert r["avertissement_present_si_attendu"] == 1.0 and r["avertissement_en_trop"] == 0.0
    assert r["cout_usd"] == round((5000 * 2 + 500 * 10) / 1e6, 3)
