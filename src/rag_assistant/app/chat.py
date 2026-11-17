"""Étape 9 : la page de discussion (maquette V2).

Zone 1 : en-tête (logo, nom, mention IA).
Zone 2 : panneau de gauche ; profil, nouvelle conversation, catégories dépliantes de questions.
Zone 3 : discussion ; la réponse s'écrit au fil de l'eau, puis est remplacée par la version
         vérifiée par les garde-fous (citations renumérotées, sources, avertissements).

L'historique de la conversation vit dans `st.session_state` : il appartient à l'onglet du
navigateur et disparaît quand on le ferme (aucun compte, rien d'enregistré à cette étape).
"""

from __future__ import annotations

import html
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from rag_assistant.app import affichage as aff
from rag_assistant.app.commun import (
    LOGO_PNG,
    cache_partage,
    en_tete,
    journal_partage,
    logo_html,
    mode_clair,
)
from rag_assistant.config import get_settings, secrets_manquants
from rag_assistant.rag.chain import Assistant, creer_assistant
from rag_assistant.services.cache import version_assistant

log = logging.getLogger(__name__)

MAX_CARACTERES = 500
QUESTIONS_PAR_HEURE = 30

SANS_PROFIL = "non_precise"
PROFIL_PAR_DEFAUT = "agriculteur"  # public principal de l'assistant
PROFILS = {
    "agriculteur": "Agriculteur ou agricultrice",
    "cooperative": "Responsable de coopérative",
    "technicien": "Technicien ou conseiller agricole",
    "etudiant_chercheur": "Étudiant ou chercheur",
    "partie_prenante": "Partenaire de la filière",
    SANS_PROFIL: "Non précisé",
}

ATTENTE = "_Je cherche dans les documents…_"
ERREUR = (
    "Désolé, je n'ai pas pu répondre : le service est momentanément indisponible ou la "
    "connexion a été coupée. Réessayez dans un instant."
)
AVIS_IA = (
    "Vous échangez avec une intelligence artificielle. Elle ne remplace pas un technicien de "
    "l'ANADER ou du CNRA."
)
AIDE_CONSENTEMENT = (
    "Pour améliorer l'assistant, vos questions et ses réponses sont gardées 90 jours, sans "
    "votre nom ; les numéros de téléphone et les courriels sont masqués. N'écrivez pas votre "
    "nom. Sans cette option, seuls des chiffres sont gardés (temps de réponse, refus, avis)."
)

# Disposition de la maquette V2 : accueil centré, zone de saisie arrondie avec bouton orangé.
# Les couleurs (--doux, --carte…) viennent de commun.STYLES.
STYLES_CHAT = """
<style>
.accueil{display:flex;flex-direction:column;align-items:center;gap:14px;text-align:center;
  padding-top:0}
.accueil img{width:56px;height:56px}
.accueil h1{margin:0;font-family:'Bricolage Grotesque','Segoe UI',sans-serif;font-size:1.9rem;
  font-weight:700;line-height:1.2;text-wrap:balance;max-width:22ch;padding:0}
.accueil .doux{margin:0;max-width:54ch;color:var(--doux);font-size:1.05rem;line-height:1.6}
.accueil .avis-ia{margin:6px 0 0;max-width:60ch;font-size:.95rem;color:var(--doux);
  background:var(--carte);border:1px solid var(--bord);border-radius:10px;padding:10px 16px}
.bulle-personne{display:flex;justify-content:flex-end;margin:8px 0 4px}
.bulle-personne>div{max-width:min(78%,560px);background:var(--bulle);border-radius:16px;
  padding:12px 20px;line-height:1.55;overflow-wrap:anywhere}
[data-testid="stChatInput"]>div{border-radius:18px!important;padding:8px 10px 8px 8px}
[data-testid="stChatInputSubmitButton"]{background:var(--accent)!important;width:36px!important;
  height:36px!important;min-width:36px!important;border-radius:10px!important;opacity:1!important}
[data-testid="stChatInputSubmitButton"] svg{color:var(--accent-texte)!important}
</style>
"""


# ------------------------------------------------------------------ état de la session


def _etat() -> None:
    ss = st.session_state
    ss.setdefault("messages", [])  # {"role": "user", "texte"} | {"role": "assistant", "reponse"}
    ss.setdefault("limiteur", aff.Limiteur(QUESTIONS_PAR_HEURE))
    ss.setdefault("compteur", 0)  # identifiant des réponses (clé des boutons d'avis)
    # identifiant tiré au hasard pour l'onglet : relie les questions d'une même conversation
    # dans le journal, sans rien dire de la personne
    ss.setdefault("session_id", uuid.uuid4().hex)
    # question dont la réponse se prépare, et questions arrivées pendant ce temps (voir traiter)
    ss.setdefault("en_cours", None)
    ss.setdefault("file", [])


def _choisir(question: str) -> None:
    st.session_state["question_choisie"] = question


def _nouvelle_conversation() -> None:
    st.session_state["messages"] = []
    st.session_state.pop("erreur", None)


@st.cache_resource(show_spinner="Chargement de l'assistant…")
def _assistant_partage() -> Assistant:
    """Un seul assistant (modèles, base vectorielle) pour toutes les sessions du serveur."""
    return creer_assistant()


def _consentement() -> bool:
    return bool(
        st.session_state.get("consentement", get_settings().journal.consentement_par_defaut)
    )


def _assistant() -> Assistant | None:
    if "_assistant_test" in st.session_state:  # tests : faux assistant injecté
        return st.session_state["_assistant_test"]
    manquants = secrets_manquants(get_settings())
    if manquants:
        st.error(
            "L'assistant n'est pas configuré : il manque " + ", ".join(manquants)
            + " dans le fichier .env (voir README)."
        )  # fmt: skip
        return None
    return _assistant_partage()


# ------------------------------------------------------------------ suggestions (en-tête)

GENRES_SUGGESTION = ("Question qui manque", "Idée", "Problème")
SUGGESTIONS_PAR_SESSION = 5  # au-delà, on remercie sans enregistrer (évite les abus)


@st.dialog("Votre suggestion", icon=":material/lightbulb:")
def fenetre_suggestion() -> None:
    """Fenêtre ouverte par le bouton « Suggestion » de l'en-tête (F9, retours des visiteurs)."""
    ss = st.session_state
    st.caption(
        "Une question à laquelle l'assistant devrait savoir répondre, une idée, un problème ? "
        "N'écrivez pas votre nom : les numéros et courriels sont masqués, la suggestion est "
        "gardée 90 jours."
    )
    # un formulaire : le texte saisi est bien transmis au clic sur « Envoyer »
    with st.form("form_suggestion", border=False):
        genre = st.pills("Type", GENRES_SUGGESTION, default=GENRES_SUGGESTION[0])
        texte = st.text_area(
            "Votre message", max_chars=1000, height=140,
            placeholder="Par exemple : comment traiter la pourriture brune des cabosses ?",
        )  # fmt: skip
        envoye = st.form_submit_button("Envoyer", type="primary", icon=":material/send:")
    if not envoye:
        return
    if not texte.strip():
        st.warning("Écrivez quelques mots avant d'envoyer.", icon=":material/edit:")
        return
    journal = journal_partage()
    if journal is not None and ss.get("nb_suggestions", 0) < SUGGESTIONS_PAR_SESSION:
        try:
            journal.ajouter_suggestion(ss["session_id"], genre or GENRES_SUGGESTION[1], texte)
            ss["nb_suggestions"] = ss.get("nb_suggestions", 0) + 1
        except Exception:
            log.exception("Suggestion non enregistrée")
    ss["suggestion_envoyee"] = True
    st.rerun()


# ------------------------------------------------------------------ zone 2 : panneau


def styles_icones(categories: list[aff.Categorie], clair: bool) -> str:
    """Une couleur par catégorie pour son icône (couleurs de la maquette V2)."""
    regles = []
    for c in categories:
        couleur = c.couleur_clair if clair else c.couleur
        if couleur:
            cible = f".st-key-cat_{c.id} summary"
            regles.append(
                f'{cible} [data-testid="stExpanderIcon"],{cible} [data-testid="stIconMaterial"]'
                f"{{color:{couleur}!important}}"
            )
    return "<style>" + "".join(regles) + "</style>"


def panneau() -> None:
    with st.sidebar:
        st.button(
            "Nouvelle conversation",
            icon=":material/add:",
            on_click=_nouvelle_conversation,
            use_container_width=True,
        )
        st.selectbox(
            "**Statut**",
            list(PROFILS),
            index=list(PROFILS).index(PROFIL_PAR_DEFAUT),
            format_func=PROFILS.get,
            key="profil",
            help="Adapte le vocabulaire des réponses. Les sources restent les mêmes.",
        )
        st.toggle(
            "Partager mes questions",
            value=get_settings().journal.consentement_par_defaut,
            key="consentement",
            help=AIDE_CONSENTEMENT,
        )
        st.markdown("**Questions fréquentes**")
        categories = aff.charger_suggestions()
        st.html(styles_icones(categories, mode_clair()))
        for categorie in categories:
            # le conteneur nommé (classe st-key-cat_…) permet de colorer l'icône en CSS
            with (
                st.container(key=f"cat_{categorie.id}"),
                st.expander(categorie.libelle, icon=categorie.icone),
            ):
                for qid, texte in categorie.questions:
                    st.button(
                        texte,
                        key=f"suggestion_{categorie.id}_{qid}",
                        type="tertiary",
                        on_click=_choisir,
                        args=(texte,),
                    )
        from rag_assistant.app.navigation import QUESTIONNAIRE  # navigation importe ce module

        st.page_link(
            QUESTIONNAIRE, label="Donner mon avis (questionnaire)", icon=":material/assignment:"
        )


# ------------------------------------------------------------------ zone 3 : discussion


def accueil() -> None:
    """Écran d'accueil de la maquette : logo, salutation, consigne, avis IA, centrés."""
    st.html(
        f"""<div class="accueil">{logo_html(64)}
<h1>Bonjour, quelle est votre question sur le cacao ?</h1>
<p class="doux">Ouvrez le « Menu » pour choisir une question toute prête, ou écrivez la vôtre en bas.
Chaque réponse indique les documents d'où elle vient.</p>
<p class="avis-ia">{AVIS_IA}</p></div>"""
    )


def bulle_personne(texte: str) -> None:
    """Question de la personne : bulle arrondie, décalée à droite, sans avatar."""
    contenu = html.escape(texte).replace("\n", "<br>")
    st.html(f'<div class="bulle-personne"><div>{contenu}</div></div>')


def afficher_reponse(message: dict) -> None:
    """Réponse finale : texte, avertissements, sources, question comprise, avis."""
    r = message["reponse"]
    if r["refus"]:
        st.info(r["texte"], icon=":material/info:")
    else:
        st.markdown(aff.en_markdown(r["texte"]))
        if r.get("couverture") == "partielle":
            st.caption(
                "Réponse partielle : les documents ne couvrent qu'une partie de la question."
            )
    for avertissement in r.get("avertissements", []):
        st.warning(avertissement, icon=":material/warning:")
    if r.get("sources"):
        with st.expander(aff.libelle_sources(len(r["sources"])), icon=":material/description:"):
            st.markdown(aff.sources_markdown(r["sources"]))
    if r.get("depuis_cache"):
        date = r["depuis_cache"]["date"]
        jour = f"{date[8:10]}/{date[5:7]}/{date[:4]}"
        if r["depuis_cache"].get("secours"):
            st.caption(
                f":material/cloud_off: Le service ne répond pas pour l'instant : voici la réponse "
                f"donnée à cette question le {jour}."
            )
        else:
            st.caption(f":material/bolt: Réponse déjà donnée à cette question le {jour}.")
    if r.get("question_recherche") and r["question_recherche"] != r["question"]:
        st.caption(f"Question comprise comme : « {r['question_recherche']} »")
    avis = st.feedback("thumbs", key=f"avis_{message['id']}")
    if avis != message.get("avis"):
        message["avis"] = avis
        journal = journal_partage()
        if journal is not None and message.get("journal_id"):
            journal.noter(message["journal_id"], avis)


def historique_pour_l_assistant(messages: list[dict]) -> list[dict]:
    """Format attendu par Assistant.repondre : [{"role", "content"}]."""
    sortie = []
    for m in messages:
        if m["role"] == "user":
            sortie.append({"role": "user", "content": m["texte"]})
        elif m["role"] == "assistant":
            sortie.append({"role": "assistant", "content": m["reponse"]["texte"]})
    return sortie


# Une réponse prend plusieurs secondes. Streamlit relance la page à chaque clic (pouce, statut,
# autre question…) et abandonne alors le script en cours : une réponse préparée dans le script
# serait perdue avec sa question. La réponse se prépare donc dans un fil à part, dont le
# résultat est gardé dans la session : la page relancée reprend l'attente là où elle en était,
# sans reposer la question à Claude. Les questions arrivées pendant ce temps attendent leur tour.
REPONSES_EN_PARALLELE = 8


@st.cache_resource(show_spinner=False)
def _executeur() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=REPONSES_EN_PARALLELE, thread_name_prefix="reponse")


def _profil_choisi() -> str | None:
    profil = st.session_state.get("profil", PROFIL_PAR_DEFAUT)
    return None if profil == SANS_PROFIL else profil


def recevoir(question: str) -> None:
    """Met la question dans la file (avec le statut choisi au moment de l'envoi)."""
    ss = st.session_state
    question = question.strip()[:MAX_CARACTERES]
    if not question:
        return
    if not ss["limiteur"].autoriser():
        ss["limite_atteinte"] = ss["limiteur"].attente_minutes()
        return
    en_attente = [d["question"] for d in ss["file"]]
    if ss["en_cours"] is not None:
        en_attente.append(ss["en_cours"]["question"])
    if question in en_attente:  # même question touchée deux fois : une seule réponse
        return
    ss.pop("erreur", None)
    ss["file"].append({"question": question, "profil": _profil_choisi()})


def traiter(assistant: Assistant) -> None:
    """Fait avancer la question en cours, puis celles de la file, sans en perdre aucune."""
    ss = st.session_state
    if ss["en_cours"] is None:
        if not ss["file"]:
            return
        if not _lancer(ss["file"].pop(0), assistant):
            return  # réponse du cache, déjà affichée
    en_cours = ss["en_cours"]
    bulle_personne(en_cours["question"])
    with st.chat_message("assistant", avatar=str(LOGO_PNG)):
        zone = st.empty()
        zone.markdown(ATTENTE)
    for suivante in ss["file"]:  # arrivées pendant la réponse : affichées, en attente
        bulle_personne(suivante["question"])
    calcul = en_cours["calcul"]
    while not calcul.done():
        zone.markdown((aff.texte_provisoire("".join(en_cours["recu"])) or ATTENTE) + " ▌")
        time.sleep(0.1)
    zone.empty()
    ss["en_cours"] = None
    _terminer(en_cours, zone)
    if ss["file"]:
        st.rerun()  # question suivante


def _lancer(demande: dict, assistant: Assistant) -> bool:
    """Démarre la réponse. False si le cache a répondu tout de suite (rien à attendre)."""
    ss = st.session_state
    question, profil = demande["question"], demande["profil"]
    historique = historique_pour_l_assistant(ss["messages"])
    # cache (F8) : seulement pour une question posée hors conversation (sans historique)
    cache, version = _cache_et_version(assistant) if not historique else (None, None)
    gardee = _lire_cache(cache, question, profil, version)
    if gardee:  # réponse déjà vérifiée : pas d'appel au modèle
        message = _enregistrer(question, gardee, profil, suivi=False)
        bulle_personne(question)
        with st.chat_message("assistant", avatar=str(LOGO_PNG)):
            afficher_reponse(message)
        if ss["file"]:
            st.rerun()
        return False
    recu: list[str] = []
    ss["en_cours"] = {
        "question": question, "profil": profil, "suivi": bool(historique),
        "cache": cache, "version": version, "recu": recu,
        "calcul": _executeur().submit(
            assistant.repondre, question, historique, profil, au_fil=recu.append
        ),
    }  # fmt: skip
    return True


def _terminer(en_cours: dict, zone) -> None:
    """La réponse est prête (ou a échoué) : on la garde, on la journalise, on l'affiche."""
    ss = st.session_state
    question, profil = en_cours["question"], en_cours["profil"]
    cache, version = en_cours["cache"], en_cours["version"]
    exc = en_cours["calcul"].exception()
    if exc is not None:
        log.error("Échec de la réponse", exc_info=exc)
        secours = _lire_cache(cache, question, profil, version, secours=True)
        if secours:  # service coupé, mais la question a déjà reçu une réponse
            message = _enregistrer(question, secours, profil, suivi=False)
            with zone.container():
                afficher_reponse(message)
            return
        _journaliser_erreur(exc, profil)
        ss["erreur"] = question
        with zone.container():
            _boite_erreur(question)
        return
    resultat = en_cours["calcul"].result().en_dict()
    if cache is not None:
        try:
            cache.ecrire(question, profil, version, resultat)
        except Exception:
            log.exception("Réponse non gardée dans le cache")
    message = _enregistrer(question, resultat, profil, suivi=en_cours["suivi"])
    with zone.container():
        afficher_reponse(message)


def _cache_et_version(assistant: Assistant):
    cache = cache_partage()
    if cache is None:
        return None, None
    try:
        return cache, version_assistant(assistant)
    except Exception:
        log.exception("Version de l'assistant inconnue : cache ignoré")
        return None, None


def _lire_cache(cache, question, profil, version, secours: bool = False) -> dict | None:
    if cache is None:
        return None
    try:
        return cache.lire(question, profil, version, secours=secours)
    except Exception:
        log.exception("Cache illisible")
        return None


def _enregistrer(question: str, resultat: dict, profil: str | None, suivi: bool) -> dict:
    """Ajoute l'échange à la conversation et l'enregistre au journal ; renvoie la réponse."""
    ss = st.session_state
    ss["compteur"] += 1
    message = {"role": "assistant", "id": ss["compteur"], "reponse": resultat}
    message["journal_id"] = _journaliser(resultat, profil, suivi=suivi)
    ss["messages"] += [{"role": "user", "texte": question}, message]
    log.info("Réponse %s : %s", message["id"], resultat.get("latences"))
    return message


def _journaliser(reponse: dict, profil: str | None, suivi: bool) -> int | None:
    """Enregistre l'échange ; une panne du journal ne doit jamais empêcher de répondre."""
    journal = journal_partage()
    if journal is None:
        return None
    try:
        return journal.enregistrer(
            st.session_state["session_id"], reponse, profil=profil,
            consentement=_consentement(), suivi=suivi,
        )  # fmt: skip
    except Exception:
        log.exception("Échange non enregistré")
        return None


def _journaliser_erreur(exc: BaseException, profil: str | None) -> None:
    journal = journal_partage()
    if journal is not None:
        try:
            journal.enregistrer_erreur(st.session_state["session_id"], exc, profil=profil)
        except Exception:
            log.exception("Erreur non enregistrée")


def _boite_erreur(question: str) -> None:
    st.error(ERREUR, icon=":material/cloud_off:")
    st.button("Réessayer", icon=":material/refresh:", on_click=_choisir, args=(question,))


def erreur(question: str) -> None:
    """Après un échec : la question restée sans réponse et un bouton pour la reposer."""
    bulle_personne(question)
    with st.chat_message("assistant", avatar=str(LOGO_PNG)):
        _boite_erreur(question)


def page() -> None:
    st.set_page_config(layout="centered")  # discussion centrée (la page admin est large)
    _etat()
    panneau()
    assistant = _assistant()
    en_tete(sur_suggestion=fenetre_suggestion)
    if st.session_state.pop("suggestion_envoyee", False):
        st.toast("Merci ! Votre suggestion a bien été envoyée.", icon=":material/check_circle:")
    st.html(STYLES_CHAT)
    ss = st.session_state
    # la saisie est lue avant d'afficher la conversation (elle reste en bas de l'écran) :
    # une question envoyée entre dans la file tout de suite, même si la page est relancée
    saisie = st.chat_input(
        "Posez votre question sur le cacao…",
        max_chars=MAX_CARACTERES,
        disabled=assistant is None,
    )
    question = saisie or ss.pop("question_choisie", None)
    if question and assistant is not None:
        recevoir(question)
    attente = ss.pop("limite_atteinte", None)
    if attente:
        st.warning(
            f"Vous avez posé beaucoup de questions en peu de temps. Vous pourrez reprendre "
            f"dans {attente} minute{'s' if attente > 1 else ''}.",
            icon=":material/hourglass_top:",
        )
    occupe = ss["en_cours"] is not None or bool(ss["file"])
    if not ss["messages"] and "erreur" not in ss and not occupe:
        accueil()
    for message in ss["messages"]:
        if message["role"] == "user":
            bulle_personne(message["texte"])
        else:
            with st.chat_message("assistant", avatar=str(LOGO_PNG)):
                afficher_reponse(message)
    if occupe and assistant is not None:
        traiter(assistant)
    elif "erreur" in ss:
        erreur(ss["erreur"])
