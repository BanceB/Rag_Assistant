"""Étape 9 : la page d'administration, séparée du chat (adresse /admin).

Elle n'apparaît pas dans le chat : seule l'équipe en connaît l'adresse, et elle demande le
mot de passe ADMIN_PASSWORD du fichier .env (jamais écrit dans le code ni dans Git).
Contenu : le tableau de bord du journal (étape 10, F9) avec les indicateurs du cahier des
charges, les dernières questions, l'export et la suppression des données ; puis le catalogue
du corpus (F7), en lecture seule.
"""

from __future__ import annotations

import csv
import os
import time

import streamlit as st
from dotenv import load_dotenv

from rag_assistant.app.affichage import mot_de_passe_valide
from rag_assistant.app.chat import PROFILS
from rag_assistant.app.commun import cache_partage, en_tete, journal_partage, mode_clair
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


PERIODES = {"7 jours": 7, "30 jours": 30, "Tout": None}
MOTIFS = {
    "sous_le_seuil": "Rien de pertinent dans les documents",
    "aucune_reponse": "Documents insuffisants pour répondre",
    "hors_sujet": "Question hors sujet",
    "sans_citation": "Réponse sans source, bloquée",
}
# objectifs du §11 du cahier des charges
OBJECTIF_SOURCEES, OBJECTIF_5S, OBJECTIF_SATISFACTION, OBJECTIF_TESTEURS = 90, 90, 80, 15


def _pct(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:.0f} %".replace(".", ",")


def _sec(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:.1f} s".replace(".", ",")


def _objectif(valeur: float | None, cible: float, texte: str) -> str:
    if valeur is None:
        return f"Objectif {texte} · pas encore de données"
    return f"Objectif {texte} · {'atteint' if valeur >= cible else 'pas encore atteint'}"


def _journal_section() -> None:
    journal = journal_partage()
    st.markdown("#### Journal des échanges (F9)")
    if journal is None:
        st.warning("Le journal est indisponible : la base data/app.db ne peut pas être ouverte.")
        return
    periode = st.segmented_control(
        "Période", list(PERIODES), default="30 jours", key="periode", required=True
    )
    stats = journal.statistiques(PERIODES[periode or "30 jours"])
    if not stats["questions"]:
        st.info("Aucune question enregistrée sur cette période.", icon=":material/inbox:")
        _donnees(journal)
        return

    st.caption("Indicateurs du cahier des charges (§11)")
    a, b, c, d = st.columns(4)
    a.metric("Réponses sourcées", _pct(stats["taux_sourcees"]), border=True,
             help=_objectif(stats["taux_sourcees"], OBJECTIF_SOURCEES, "≥ 90 %"))  # fmt: skip
    b.metric("Réponses en 5 s ou moins", _pct(stats["taux_sous_5s"]), border=True,
             help=_objectif(stats["taux_sous_5s"], OBJECTIF_5S, "≥ 90 %") + " · médiane "
             + _sec(stats["latence_mediane"]) + ", 90e centile " + _sec(stats["latence_p90"]))  # fmt: skip
    c.metric("Réponses jugées utiles", _pct(stats["taux_utiles"]), border=True,
             help=_objectif(stats["taux_utiles"], OBJECTIF_SATISFACTION, "≥ 80 %")
             + f" · {stats['avis']} avis")  # fmt: skip
    d.metric("Sessions", stats["sessions"], border=True,
             help=_objectif(stats["sessions"], OBJECTIF_TESTEURS, "≥ 15 testeurs")
             + " · une session = un onglet ouvert")  # fmt: skip

    st.caption("Activité")
    e, f, g, h = st.columns(4)
    e.metric("Questions", stats["questions"], help="Premier mot (médiane) : "
             + _sec(stats["premier_mot_median"]))  # fmt: skip
    f.metric(
        "Refus", stats["refus"], help="Part des questions traitées : " + _pct(stats["taux_refus"])
    )
    g.metric("Erreurs du service", stats["erreurs"])
    h.metric(
        "Réponses du cache", stats["depuis_cache"] + stats["secours"],
        help=f"Réponses déjà données, servies sans appeler le modèle (F8), dont {stats['secours']} "
        "en secours pendant une panne. Exclues des temps de réponse.",
    )  # fmt: skip
    if len(stats["par_jour"]) > 1:
        # une seule série : une couleur (l'accent), pas de légende ; l'infobulle donne le chiffre
        st.markdown("**Questions par jour**")
        st.altair_chart(
            _graphique_par_jour(stats["par_jour"]), use_container_width=True, theme=None
        )

    gauche, droite = st.columns(2)
    with gauche:
        st.markdown("**Refus par motif**")
        if stats["refus_par_motif"]:
            _tableau(
                [
                    {"Motif": MOTIFS.get(m, m), "Nombre": n}
                    for m, n in stats["refus_par_motif"].items()
                ]
            )
        else:
            st.caption("Aucun refus.")
    with droite:
        st.markdown("**Documents les plus cités**")
        if stats["documents_cites"]:
            _tableau(
                [{"Document": doc, "Citations": n} for doc, n in stats["documents_cites"].items()]
            )
        else:
            st.caption("Aucune source citée.")

    st.markdown("**Dernières questions**")
    st.caption(
        f"{stats['consentements']} question(s) sur {stats['questions'] - stats['erreurs']} "
        "partagée(s) avec accord ; les autres n'apparaissent que par leurs chiffres."
    )
    _tableau(_lignes_recentes(journal), hauteur=420)
    _donnees(journal)


def _graphique_par_jour(par_jour: dict[str, int]):
    """Barres des questions par jour, aux couleurs du mode choisi (fond transparent)."""
    import altair as alt

    clair = mode_clair()
    barre, texte, grille = ("#A9541B", "#5B554B", "#D8D3C8") if clair else (
        "#E69A57", "#B1AA9E", "#3A3833"
    )  # fmt: skip
    donnees = alt.Data(
        values=[{"Jour": f"{j[8:10]}/{j[5:7]}", "Questions": n} for j, n in par_jour.items()]
    )
    return (
        alt.Chart(donnees, height=200)
        .mark_bar(color=barre, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("Jour:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Questions:Q", title=None, axis=alt.Axis(tickMinStep=1)),
            tooltip=["Jour:N", "Questions:Q"],
        )
        .configure(background="transparent")
        .configure_view(stroke=None)
        .configure_axis(labelColor=texte, gridColor=grille, domainColor=grille, tickColor=grille)
    )


def _tableau(lignes: list[dict], hauteur: int | None = None) -> None:
    """Tableau interactif en mode sombre ; en mode clair, tableau HTML (le tableau interactif
    de Streamlit est dessiné dans un canevas qui garde les couleurs du thème sombre)."""
    if not mode_clair():
        st.dataframe(lignes, hide_index=True, use_container_width=True, height=hauteur or "auto")
        return
    import pandas as pd

    tableau = pd.DataFrame(lignes).style.hide(axis="index")
    with st.container(height=hauteur, border=False) if hauteur else st.container():
        st.table(tableau)


def _lignes_recentes(journal) -> list[dict]:
    lignes = []
    for r in journal.derniers(50):
        if r["erreur"]:
            resultat = f"Erreur ({r['erreur']})"
        elif r["refus"]:
            resultat = "Refus : " + MOTIFS.get(r["motif"], r["motif"] or "")
        else:
            resultat = f"Réponse, {r['nb_sources']} source(s)"
        lignes.append(
            {
                "Date (UTC)": r["horodatage"].replace("T", " ")[:16],
                "Question": r["question"] or "(non partagée)",
                "Résultat": resultat,
                "Temps": _sec(r["latence_totale"]),
                "Avis": {1: "👍", 0: "👎"}.get(r["avis"], ""),
                "Statut": PROFILS.get(r["profil"], r["profil"] or ""),
            }
        )
    return lignes


def _donnees(journal) -> None:
    jours = get_settings().journal.conservation_jours
    with st.expander("Données et confidentialité", icon=":material/shield:"):
        st.markdown(
            f"- Conservation : **{jours} jours**, puis suppression automatique.\n"
            "- Le texte des questions n'est gardé qu'avec l'accord de la personne (option "
            "« Partager mes questions »), après masquage des numéros et des courriels.\n"
            "- Aucun nom, aucune adresse IP : la session est un identifiant tiré au hasard."
        )
        st.download_button(
            "Exporter le journal (CSV)",
            journal.exporter_csv(),
            file_name="journal_assistant_cacao.csv",
            mime="text/csv",
            icon=":material/download:",
        )
        if st.button(f"Supprimer maintenant les échanges de plus de {jours} jours"):
            st.success(f"{journal.purger()} échange(s) supprimé(s).")
        cache = cache_partage()
        if cache is not None:
            c = cache.statistiques()
            st.markdown(
                f"**Cache des réponses fréquentes (F8)** : {c['reponses']} réponse(s) gardée(s), "
                f"servie(s) {c['utilisations']} fois. Elles sont recalculées après "
                f"{get_settings().cache.duree_jours} jours ou quand le corpus change."
            )
            if st.button("Vider le cache", icon=":material/mop:"):
                st.success(f"{cache.vider()} réponse(s) retirée(s) du cache.")
        confirme = st.checkbox("Je veux effacer tout le journal (irréversible)")
        if st.button("Tout effacer", disabled=not confirme, icon=":material/delete_forever:"):
            st.success(f"{journal.tout_effacer()} échange(s) effacé(s).")


def _tableau_de_bord() -> None:
    st.markdown("### Administration")
    _journal_section()

    st.markdown("#### Documents du corpus (F7)")
    documents = _catalogue()
    themes = {d["theme"] for d in documents if d["theme"]}
    a, b, c = st.columns(3)
    a.metric("Documents au catalogue", len(documents))
    b.metric("Thèmes", len(themes))
    c.metric("Objectif du cahier des charges", "≥ 100")
    st.caption("Lecture seule pour l'instant : l'ajout et le retrait passent encore par la ligne "
               "de commande (`rag_assistant.ingestion.pipeline`).")  # fmt: skip
    if documents:
        _tableau(documents, hauteur=420)

    if st.button("Se déconnecter", icon=":material/logout:"):
        st.session_state["admin"] = False
        st.rerun()


def page() -> None:
    # page large : le tableau de bord a besoin de place (le chat reste centré)
    st.set_page_config(layout="wide")
    en_tete("Espace de l'équipe · page séparée du chat")
    from rag_assistant.app.navigation import CHAT  # import ici : navigation importe admin

    st.page_link(CHAT, label="Retour au chat", icon=":material/arrow_back:")
    if st.session_state.get("admin"):
        _tableau_de_bord()
    else:
        _connexion()
