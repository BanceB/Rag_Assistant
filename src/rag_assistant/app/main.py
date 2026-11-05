"""Étape 9 : point d'entrée de l'interface Streamlit.

Lancement, depuis la racine du projet :
    uv run streamlit run src/rag_assistant/app/main.py

Puis ouvrir http://localhost:8501 (chat) ou http://localhost:8501/admin (équipe).
"""

import logging

import streamlit as st

from rag_assistant.app.commun import LOGO_PNG, NOM_APP
from rag_assistant.app.navigation import ADMIN, CHAT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")

st.set_page_config(page_title=NOM_APP, page_icon=str(LOGO_PNG))  # largeur : chaque page
st.navigation([CHAT, ADMIN], position="hidden").run()
