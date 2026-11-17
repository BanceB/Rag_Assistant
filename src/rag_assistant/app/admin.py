"""Étape 9 : la page d'administration, séparée du chat (adresse /admin).

Elle n'apparaît pas dans le chat : seule l'équipe en connaît l'adresse, et elle demande le
mot de passe ADMIN_PASSWORD du fichier .env (jamais écrit dans le code ni dans Git).
Contenu : le tableau de bord du journal (étape 10, F9) avec les indicateurs du cahier des
charges, les dernières questions, l'export et la suppression des données ; le cache des
réponses fréquentes (F8), rempli statut par statut ; les résultats du questionnaire des
testeurs ; les suggestions ; puis le catalogue du corpus (F7), en lecture seule.
"""

from __future__ import annotations

import csv
import os
import time

import streamlit as st
from dotenv import load_dotenv

from rag_assistant.app.affichage import mot_de_passe_valide
from rag_assistant.app.chat import PROFIL_PAR_DEFAUT, PROFILS, SANS_PROFIL
from rag_assistant.app.commun import cache_partage, en_tete, journal_partage, mode_clair
from rag_assistant.config import PROJECT_ROOT, get_settings, secrets_manquants
from rag_assistant.services import cache as cache_reponses
from rag_assistant.services import questionnaire

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
            "- Aucun nom, aucune adresse IP : la session est un identifiant tiré au hasard.\n"
            "- Les suggestions des visiteurs suivent les mêmes règles (masquage, 90 jours).\n"
            "- Les questionnaires des testeurs sont anonymes (ni nom ni session) et suivent "
            "les mêmes règles."
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
        confirme = st.checkbox("Je veux effacer tout le journal (irréversible)")
        if st.button("Tout effacer", disabled=not confirme, icon=":material/delete_forever:"):
            st.success(f"{journal.tout_effacer()} échange(s) effacé(s).")


# ------------------------------------------------------------------ cache (F8)


@st.cache_resource(show_spinner=False)
def _prechauffage_serveur() -> cache_reponses.Prechauffage:
    """Un seul remplissage pour tout le serveur : il survit à la fermeture de la page."""
    return cache_reponses.Prechauffage()


def _prechauffage() -> cache_reponses.Prechauffage:
    return st.session_state.get("_prechauffage_test") or _prechauffage_serveur()


def _assistant_admin():
    """L'assistant du chat (déjà chargé en mémoire), ou None s'il n'est pas configuré."""
    ss = st.session_state
    if "_assistant_test" in ss:
        return ss["_assistant_test"]
    if secrets_manquants(get_settings()):
        return None
    from rag_assistant.app.chat import _assistant_partage

    return _assistant_partage()


def _profil_cache(cle: str) -> str | None:
    """Le profil tel que le chat l'enregistre dans le cache (« Non précisé » : aucun)."""
    return None if cle == SANS_PROFIL else cle


def _duree(secondes: float) -> str:
    minutes = round(secondes / 60)
    return "moins d'une minute" if minutes < 1 else f"environ {minutes} minute{'s' * (minutes > 1)}"


def _cache_section() -> None:
    st.markdown("#### Cache des réponses fréquentes (F8)")
    cache = cache_partage()
    if cache is None:
        st.caption("Le cache est désactivé (`cache.actif` dans config/settings.yaml) ou illisible.")
        return
    assistant = _assistant_admin()
    if assistant is None:
        st.warning("L'assistant n'est pas configuré (clés manquantes dans .env) : impossible de "
                   "remplir le cache.", icon=":material/key_off:")  # fmt: skip
        return
    st.caption(
        "Une question fréquente dont la réponse est dans le cache s'affiche tout de suite, sans "
        "appeler Voyage ni Claude. Le cache dépend du statut choisi dans le chat : chaque statut "
        f"se remplit à part. Les réponses sont recalculées après {get_settings().cache.duree_jours} "
        "jours ou quand le corpus, le modèle ou les consignes changent."
    )
    questions = cache_reponses.questions_proposees()
    textes = [texte for _, texte in questions]
    version = cache_reponses.version_assistant(assistant)
    comptes = cache.compter(textes, [_profil_cache(p) for p in PROFILS], version)
    prets = {p: comptes[_profil_cache(p)] for p in PROFILS}
    _tableau(
        [
            {"Statut": PROFILS[p], "Réponses prêtes": f"{n} / {len(textes)}",
             "État": "Complet" if n == len(textes) else ("Vide" if n == 0 else "Incomplet")}
            for p, n in prets.items()
        ]
    )  # fmt: skip
    stats = cache.statistiques()
    st.caption(f"{stats['reponses']} réponse(s) gardée(s) au total, servies {stats['utilisations']} "
               "fois. Une question peut rester absente : l'assistant ne garde que les réponses "
               "complètes et sourcées.")  # fmt: skip

    travail = _prechauffage()
    if travail.etat()["en_cours"]:
        _suivi_remplissage()
        return
    _resultat_dernier_remplissage(travail.etat())
    incomplets = [p for p, n in prets.items() if n < len(textes)]
    with st.container(border=True):
        choisis = st.multiselect(
            "Statuts à remplir",
            list(PROFILS),
            default=incomplets or [PROFIL_PAR_DEFAUT],
            format_func=PROFILS.get,
            key="cache_statuts",
        )
        manquantes = st.checkbox(
            "Seulement les questions qui manquent", value=True, key="cache_manquantes",
            help="Décochez pour recalculer toutes les réponses des statuts choisis.",
        )  # fmt: skip
        appels = sum(len(textes) - prets[p] if manquantes else len(textes) for p in choisis)
        if choisis and appels == 0:
            st.caption("Tout est déjà prêt pour ces statuts. Décochez la case ci-dessus pour "
                       "recalculer toutes leurs réponses.")  # fmt: skip
        elif choisis:
            st.caption(f"{appels} question(s) à poser à l'assistant : "
                       f"{_duree(appels * cache_reponses.SECONDES_PAR_QUESTION)}. Vous pouvez "
                       "quitter la page pendant le remplissage.")  # fmt: skip
        if st.button("Remplir le cache", type="primary", icon=":material/bolt:",
                     disabled=not choisis or appels == 0):  # fmt: skip
            travail.lancer(assistant, cache, [_profil_cache(p) for p in choisis], questions,
                           seulement_manquantes=manquantes)  # fmt: skip
            st.rerun()
    with st.expander("Vider le cache", icon=":material/mop:"):
        st.caption("Retire toutes les réponses gardées, pour tous les statuts. Les questions "
                   "fréquentes repasseront par Voyage et Claude jusqu'au prochain remplissage.")  # fmt: skip
        if st.button("Vider le cache maintenant"):
            st.success(f"{cache.vider()} réponse(s) retirée(s) du cache.")


@st.fragment(run_every=2)
def _suivi_remplissage() -> None:
    """Progression, rafraîchie toutes les 2 s ; la page entière se recharge à la fin."""
    travail = _prechauffage()
    etat = travail.etat()
    if not etat["en_cours"]:
        st.rerun(scope="app")
    profil = etat["profil"]
    nom = PROFILS.get(profil if profil is not None else SANS_PROFIL, profil)
    fait = etat["faites"] / etat["total"] if etat["total"] else 0
    st.progress(fait, text=f"Remplissage en cours : {etat['faites']} / {etat['total']} "
                f"questions · statut « {nom} »")  # fmt: skip
    st.caption(f"{etat['gardees']} gardée(s) · {etat['deja']} déjà prête(s) · "
               f"{etat['non_gardees']} non gardée(s) · {etat['echecs']} échec(s)")  # fmt: skip
    if st.button("Arrêter le remplissage", icon=":material/stop_circle:"):
        travail.arreter()
        st.info("Arrêt demandé : la question en cours se termine, puis le remplissage s'arrête.")


def _resultat_dernier_remplissage(etat: dict) -> None:
    if not etat["fin"]:
        return
    bilan = (f"{etat['gardees']} réponse(s) ajoutée(s), {etat['deja']} déjà prête(s), "
             f"{etat['non_gardees']} non gardée(s), {etat['echecs']} échec(s).")  # fmt: skip
    heure = etat["fin"][11:16]
    if etat["arrete_par_l_equipe"]:
        st.info(f"Remplissage arrêté à {heure} (UTC). {bilan}", icon=":material/stop_circle:")
    elif etat["interrompu"]:
        st.warning(f"Remplissage interrompu à {heure} (UTC) après {cache_reponses.ECHECS_AVANT_ARRET}"
                   f" échecs de suite : vérifiez la connexion du serveur et les clés. {bilan}",
                   icon=":material/wifi_off:")  # fmt: skip
    else:
        st.success(f"Remplissage terminé à {heure} (UTC). {bilan}", icon=":material/check_circle:")


def _suggestions_section() -> None:
    journal = journal_partage()
    if journal is None:
        return
    st.markdown("#### Suggestions des visiteurs (F9)")
    suggestions = journal.suggestions()
    if not suggestions:
        st.caption("Aucune suggestion pour l'instant (bouton « Suggestion » de l'en-tête du chat).")
        return
    par_genre = {}
    for s in suggestions:
        par_genre[s["genre"]] = par_genre.get(s["genre"], 0) + 1
    st.caption(
        f"{len(suggestions)} suggestion(s) : "
        + ", ".join(f"{n} « {g} »" for g, n in sorted(par_genre.items(), key=lambda x: -x[1]))
    )
    _tableau(
        [
            {
                "Date (UTC)": s["horodatage"].replace("T", " ")[:16],
                "Type": s["genre"],
                "Suggestion": s["texte"],
            }
            for s in suggestions
        ],
        hauteur=320 if len(suggestions) > 8 else None,
    )
    st.download_button(
        "Exporter les suggestions (CSV)",
        journal.exporter_suggestions_csv(),
        file_name="suggestions_assistant_cacao.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def _questionnaires_section() -> None:
    journal = journal_partage()
    if journal is None:
        return
    st.markdown("#### Questionnaire des testeurs (annexe 3)")
    reponses = journal.questionnaires()
    if not reponses:
        st.caption("Aucun questionnaire reçu pour l'instant (page /questionnaire).")
        return
    ind = questionnaire.indicateurs(reponses)
    a, b, c, d = st.columns(4)
    a.metric("Testeurs", ind["testeurs"], border=True,
             help=_objectif(ind["testeurs"], OBJECTIF_TESTEURS, "≥ 15 testeurs")
             + " · un testeur = un questionnaire envoyé")  # fmt: skip
    b.metric("Pertinence perçue", _pct(ind["pertinence"]), border=True,
             help=_objectif(ind["pertinence"], OBJECTIF_SATISFACTION, "≥ 80 %")
             + " · part des notes 4 ou 5 à la question 5")  # fmt: skip
    c.metric("Satisfaction", _pct(ind["satisfaction"]), border=True,
             help=_objectif(ind["satisfaction"], OBJECTIF_SATISFACTION, "≥ 80 %")
             + " · part des notes 4 ou 5 à la question 14")  # fmt: skip
    d.metric("Le conseilleraient", _pct(ind["recommandation"]), border=True,
             help="Part des « Oui » à la question 15")  # fmt: skip
    st.caption(
        "Notes 4 ou 5 : compréhension "
        + _pct(ind["comprehension"])
        + " · utilité "
        + _pct(ind["utilite"])
        + " · confiance "
        + _pct(ind["confiance"])
        + " · IA bien comprise (question 13) : "
        + _pct(ind["ia_comprise"])
    )
    libres = [
        {
            "Date (UTC)": r["horodatage"].replace("T", " ")[:16],
            "Statut": r.get("q1") or "",
            "Apprécié (16)": r.get("q16") or "",
            "À améliorer (17)": r.get("q17") or "",
            "Mal répondu (18)": r.get("q18") or "",
        }
        for r in reversed(reponses)
        if r.get("q16") or r.get("q17") or r.get("q18")
    ]
    if libres:
        st.markdown("**Réponses libres**")
        _tableau(libres, hauteur=320 if len(libres) > 8 else None)
    st.download_button(
        "Exporter les questionnaires (CSV)",
        journal.exporter_questionnaires_csv(),
        file_name="questionnaires_assistant_cacao.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def _tableau_de_bord() -> None:
    st.markdown("### Administration")
    _journal_section()
    _cache_section()
    _questionnaires_section()
    _suggestions_section()

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
