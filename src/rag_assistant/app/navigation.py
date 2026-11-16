"""Les pages de l'application et leurs adresses.

/               → la discussion (page par défaut)
/questionnaire  → le questionnaire des testeurs (lien dans l'invitation et dans le panneau)
/admin          → l'administration, absente des menus : seule l'équipe en connaît l'adresse.
"""

from __future__ import annotations

import streamlit as st

from rag_assistant.app import admin, chat, questionnaire

CHAT = st.Page(chat.page, title="Discussion", icon=":material/chat:", url_path="chat", default=True)
QUESTIONNAIRE = st.Page(
    questionnaire.page,
    title="Questionnaire",
    icon=":material/assignment:",
    url_path="questionnaire",
)
ADMIN = st.Page(admin.page, title="Administration", icon=":material/settings:", url_path="admin")
