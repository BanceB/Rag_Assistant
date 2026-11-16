"""Page /questionnaire : le questionnaire des testeurs (annexe 3 du mémoire).

Le lien est envoyé aux testeurs avec l'invitation, et le panneau du chat y mène aussi.
Les réponses sont anonymes : ni nom, ni téléphone, ni identifiant de session. Elles sont
enregistrées dans le journal (data/app.db, conservation 90 jours) et exploitées dans /admin.
"""

from __future__ import annotations

import logging

import streamlit as st

from rag_assistant.app.commun import en_tete, journal_partage
from rag_assistant.services import questionnaire as qs

log = logging.getLogger(__name__)

INTRODUCTION = (
    "Merci d'avoir testé l'assistant ! Ce questionnaire prend **5 minutes**. Il est **anonyme** : "
    "il ne vous demande ni votre nom, ni votre téléphone, ni votre adresse électronique, et "
    "n'écrivez aucune de ces informations dans les réponses libres. Vos réponses servent "
    "uniquement à évaluer l'assistant dans le cadre d'un mémoire de Master (IUA) ; elles sont "
    "conservées 90 jours au plus."
)
MERCI = "Merci ! Vos réponses ont bien été enregistrées."
STYLES = """<style>
/* questions bien séparées, et l'échelle 1 à 5 lisible sur téléphone */
.st-key-form_questionnaire [data-testid="stRadio"]{margin-bottom:.6rem}
.st-key-form_questionnaire [data-testid="stRadio"] label p{font-size:1rem}
.st-key-form_questionnaire [data-testid="stWidgetLabel"] p{font-weight:600}
</style>"""


def _horizontal(question: qs.Question) -> bool:
    """Choix courts côte à côte (échelle 1 à 5, Oui / Non…) ; choix longs les uns sous les autres."""
    return bool(question.choix) and max(len(c) for c in question.choix) <= 12


def _champ(question: qs.Question) -> None:
    cle = f"q_{question.id}"
    if question.choix is None:
        st.text_area(
            question.libelle + " (facultatif)",
            key=cle,
            max_chars=qs.LONGUEUR_TEXTE,
            height=90,
        )
        return
    st.radio(
        question.libelle,
        question.choix,
        index=None,
        horizontal=_horizontal(question),
        key=cle,
    )
    if question.legende:
        st.caption(question.legende)


def _envoyer() -> None:
    ss = st.session_state
    reponses = {q.id: ss.get(f"q_{q.id}") for q in qs.QUESTIONS}
    reponses[qs.PARTICIPATION.id] = "Oui"
    manque = qs.manquantes(reponses)
    if manque:
        ss["questionnaire_manque"] = manque
        return
    journal = journal_partage()
    if journal is None:
        ss["questionnaire_erreur"] = True
        return
    try:
        journal.ajouter_questionnaire(reponses)
    except Exception:
        log.exception("Questionnaire non enregistré")
        ss["questionnaire_erreur"] = True
        return
    ss["questionnaire_envoye"] = True


def page() -> None:
    st.set_page_config(layout="centered")
    en_tete("Questionnaire des testeurs")
    from rag_assistant.app.navigation import CHAT  # import ici : navigation importe cette page

    st.page_link(CHAT, label="Retour à l'assistant", icon=":material/arrow_back:")
    ss = st.session_state
    if ss.get("questionnaire_envoye"):
        st.success(MERCI, icon=":material/check_circle:")
        return
    st.html(STYLES)
    st.markdown(INTRODUCTION)
    participe = st.radio(
        qs.PARTICIPATION.libelle, qs.PARTICIPATION.choix, index=None, horizontal=True, key="q_q0"
    )
    if participe is None:
        return
    if participe == "Non":
        st.info("Merci tout de même pour votre temps. Rien n'a été enregistré.",
                icon=":material/info:")  # fmt: skip
        return
    with st.form("form_questionnaire", border=False):
        for question in qs.QUESTIONS:
            _champ(question)
        st.form_submit_button(
            "Envoyer mes réponses", type="primary", icon=":material/send:", on_click=_envoyer
        )
    manque = ss.pop("questionnaire_manque", None)
    if manque:
        st.warning(
            "Il manque une réponse aux questions " + ", ".join(map(str, manque)) + ".",
            icon=":material/edit:",
        )
    if ss.pop("questionnaire_erreur", False):
        st.error("Vos réponses n'ont pas pu être enregistrées. Réessayez dans un instant.",
                 icon=":material/error:")  # fmt: skip
