"""Étape 9 : la page d'administration, séparée du chat (adresse /admin).

Elle n'apparaît pas dans le chat : seule l'équipe en connaît l'adresse, et elle demande le
mot de passe ADMIN_PASSWORD du fichier .env (jamais écrit dans le code ni dans Git).
Son contenu sera complété plus tard ; elle montre déjà le catalogue du corpus (F7) en
lecture seule.
"""

from __future__ import annotations

import csv
import os
import time

import streamlit as st
from dotenv import load_dotenv

from rag_assistant.app.affichage import mot_de_passe_valide
from rag_assistant.app.commun import en_tete
from rag_assistant.config import PROJECT_ROOT, get_settings

ESSAIS_MAX = 5
BLOCAGE_S = 300  # 5 minutes après 5 mauvais mots de passe
COLONNES = ("doc_id", "titre", "organisme", "theme", "date", "langue", "statut")


def _mot_de_passe_attendu() -> str | None:
    load_dotenv(PROJECT_ROOT / ".env")
    return os.environ.get("ADMIN_PASSWORD") or None


def _connexion() -> None:
    ss = st.session_state
    attendu = _mot_de_passe_attendu()
    st.markdown("### Espace réservé à l'équipe")
    st.markdown(
        "Cette page sert à gérer les documents que l'assistant peut utiliser. "
        "Les utilisateurs du chat n'y ont pas accès."
    )
    if attendu is None:
        st.warning(
            "Aucun mot de passe n'est configuré : ajoutez la ligne ADMIN_PASSWORD=… dans le "
            "fichier .env, puis relancez l'application.",
            icon=":material/key_off:",
        )
        return
    bloque_jusqua = ss.get("admin_bloque_jusqua", 0.0)
    if time.time() < bloque_jusqua:
        minutes = max(1, round((bloque_jusqua - time.time()) / 60))
        st.error(f"Trop d'essais. Réessayez dans {minutes} minute{'s' if minutes > 1 else ''}.")
        return
    with st.form("connexion_admin", clear_on_submit=True):
        saisi = st.text_input("Mot de passe", type="password", autocomplete="current-password")
        envoye = st.form_submit_button("Entrer", type="primary")
    if envoye:
        if mot_de_passe_valide(saisi, attendu):
            ss["admin"] = True
            ss["admin_essais"] = 0
            st.rerun()
        ss["admin_essais"] = ss.get("admin_essais", 0) + 1
        if ss["admin_essais"] >= ESSAIS_MAX:
            ss["admin_bloque_jusqua"] = time.time() + BLOCAGE_S
            ss["admin_essais"] = 0
        st.error("Mot de passe incorrect.")


def _catalogue() -> list[dict]:
    chemin = PROJECT_ROOT / get_settings().chemins.catalogue
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8") as f:
        return [{c: ligne.get(c, "") for c in COLONNES} for ligne in csv.DictReader(f)]


def _tableau_de_bord() -> None:
    st.markdown("### Administration")
    documents = _catalogue()
    themes = {d["theme"] for d in documents if d["theme"]}
    a, b, c = st.columns(3)
    a.metric("Documents au catalogue", len(documents))
    b.metric("Thèmes", len(themes))
    c.metric("Objectif du cahier des charges", "≥ 100")

    st.markdown("#### Documents du corpus (F7)")
    st.caption("Lecture seule pour l'instant : l'ajout et le retrait passent encore par la ligne "
               "de commande (`rag_assistant.ingestion.pipeline`).")  # fmt: skip
    if documents:
        st.dataframe(documents, hide_index=True, use_container_width=True)

    st.markdown("#### À venir")
    x, y = st.columns(2)
    with x.container(border=True):
        st.markdown("**Journal des questions** (F9)  \nQuestions, refus, temps de réponse.")
    with y.container(border=True):
        st.markdown("**Avis des utilisateurs** (F9)  \nRéponses jugées utiles ou non.")

    if st.button("Se déconnecter", icon=":material/logout:"):
        st.session_state["admin"] = False
        st.rerun()


def page() -> None:
    en_tete("Espace de l'équipe · page séparée du chat")
    from rag_assistant.app.navigation import CHAT  # import ici : navigation importe admin

    st.page_link(CHAT, label="Retour au chat", icon=":material/arrow_back:")
    if st.session_state.get("admin"):
        _tableau_de_bord()
    else:
        _connexion()
