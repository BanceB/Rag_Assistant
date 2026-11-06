"""Éléments partagés par les deux pages : logo, en-tête, mode clair ou sombre, styles."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import streamlit as st

from rag_assistant.config import get_settings
from rag_assistant.services.cache import CacheReponses
from rag_assistant.services.journal import Journal

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
LOGO_PNG = STATIC / "logo.png"
# image en ligne (data URI) : st.html retire les balises <svg> écrites directement
LOGO_URI = (
    "data:image/svg+xml;base64," + base64.b64encode((STATIC / "logo.svg").read_bytes()).decode()
)


def logo_html(taille: int = 40) -> str:
    return f'<img alt="" width="{taille}" height="{taille}" src="{LOGO_URI}">'


LOGO_HTML = logo_html(40)

NOM_APP = "Assistant cacao durable"

# Hauteur de la barre d'en-tête, fixée en haut de la fenêtre sur toute la largeur (zone 1).
HAUTEUR_ENTETE = 72

# Retouches que le thème de config.toml ne couvre pas : la barre d'en-tête fixe (le panneau
# et la discussion commencent sous elle), les questions du panneau.
STYLES = f"""
<style>
@import url("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&display=swap");
:root{{--h-entete:{HAUTEUR_ENTETE}px;--doux:#B1AA9E;--carte:#2A2925;--bord:#3A3833;--bulle:#36342F;
  --accent:#E69A57;--accent-texte:#1B1A17;--avis-oui:#7FB069;--avis-non:#D2693C}}
.st-key-entete{{position:fixed;top:0;left:var(--gauche-entete,0px);right:0;height:var(--h-entete);
  width:auto!important;z-index:999989;
  box-sizing:border-box;padding:0 20px;background:var(--fond-entete,#181715);
  border-bottom:1px solid var(--bord-entete,#3A3833);flex-wrap:nowrap!important}}
.st-key-entete>div{{min-width:0}}
.entete{{display:flex;align-items:center;gap:12px;min-width:0}}
.entete img{{flex:none;width:40px;height:40px}}
.entete>div{{min-width:0}}
.entete .titre{{font-size:1.3rem;font-weight:700;line-height:1.2;margin:0;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}}
.entete .sous-titre{{font-size:.85rem;opacity:.75;margin:2px 0 0;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}}
/* logo et nom centrés sur la largeur de l'écran (et non de la barre, décalée par le panneau) :
   la zone du titre déborde à gauche de la largeur du panneau ; le bouton reste à droite */
.st-key-entete>[data-testid="stElementContainer"]:first-child{{position:absolute!important;
  top:0;bottom:0;right:0;left:calc(-1 * var(--gauche-entete,0px));width:auto!important;max-width:none!important;
  display:flex;align-items:center;
  justify-content:center;pointer-events:none}}
@media (min-width:641px) and (max-width:900px){{
  /* écran étroit avec panneau ouvert : pas la place de centrer, titre à gauche de la barre */
  body:has(section[data-testid="stSidebar"][data-collapsed="false"])
    .st-key-entete>[data-testid="stElementContainer"]:first-child{{position:static!important;
    justify-content:flex-start}}
  body:has(section[data-testid="stSidebar"][data-collapsed="false"])
    .st-key-entete>[data-testid="stElementContainer"]:first-child>*{{max-width:100%}}
}}
.st-key-entete>[data-testid="stElementContainer"]:first-child>*{{width:auto!important;
  max-width:calc(100% - 2 * var(--place-bouton,190px))}}
.st-key-bascule_theme{{flex:none!important;width:auto!important;margin-left:auto}}
.st-key-bascule_theme button{{white-space:nowrap}}
/* l'en-tête commence au bord droit du panneau, qui garde toute la hauteur ; la barre de
   Streamlit (bouton » du panneau replié) et la discussion passent sous l'en-tête */
@media (min-width:641px){{
  body:has(section[data-testid="stSidebar"][data-collapsed="false"]) .st-key-entete{{
    left:var(--gauche-entete,300px)}}
}}
[data-testid="stHeader"]{{top:var(--h-entete)!important;background:transparent!important;
  pointer-events:none}}
[data-testid="stHeader"] *{{pointer-events:auto}}
[data-testid="stMainBlockContainer"]{{padding-top:calc(var(--h-entete) + 2.5rem)!important}}
[data-testid="stSidebarHeader"]{{padding-top:.75rem;padding-bottom:0;height:auto}}
[data-testid="stSidebar"] button[kind="tertiary"]{{justify-content:flex-start;text-align:left;
  width:100%;padding:6px 8px;border-radius:8px;line-height:1.35}}
[data-testid="stSidebar"] button[kind="tertiary"]:hover{{background:rgba(128,128,128,.14)}}
[data-testid="stSidebar"] button[kind="tertiary"] p{{font-size:.92rem}}
/* listes déroulantes : main au survol (texte et flèche), pas de curseur de saisie, flèche
   tournée vers le haut quand la liste est ouverte, choix actuel en couleur et en gras */
.stSelectbox [role="group"],.stSelectbox [role="group"] input,
.stSelectbox [role="group"] button{{cursor:pointer!important}}
.stSelectbox [role="group"] input{{caret-color:transparent}}
.stSelectbox [role="group"] button svg{{transition:transform .2s ease}}
.stSelectbox [role="group"]:has(input[aria-expanded="true"]) button svg{{transform:rotate(180deg)}}
[data-testid="stSelectboxVirtualDropdown"] [role="option"]{{cursor:pointer}}
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] *{{
  color:var(--accent)!important;font-weight:600}}
/* avis 👍/👎 : survol teinté, petit rebond au clic, avis choisi en couleur sur fond teinté
   (vert : utile, brique : pas utile) */
[data-testid="stFeedback"] button{{border-radius:8px!important;padding:4px 6px!important;
  transition:background-color .2s ease,transform .12s ease}}
[data-testid="stFeedback"] button:hover{{background:rgba(128,128,128,.16)!important}}
[data-testid="stFeedback"] button:active{{transform:scale(.88)}}
[data-testid="stFeedbackButtonActive"] [data-testid="stIconMaterial"]{{
  animation:rebond-avis .4s ease}}
[data-testid="stFeedbackButtonActive"][aria-label="Thumbs up"]{{
  background:color-mix(in srgb,var(--avis-oui) 18%,transparent)!important}}
[data-testid="stFeedbackButtonActive"][aria-label="Thumbs up"] *{{color:var(--avis-oui)!important;opacity:1}}
[data-testid="stFeedbackButtonActive"][aria-label="Thumbs down"]{{
  background:color-mix(in srgb,var(--avis-non) 18%,transparent)!important}}
[data-testid="stFeedbackButtonActive"][aria-label="Thumbs down"] *{{color:var(--avis-non)!important;opacity:1}}
@keyframes rebond-avis{{0%{{transform:scale(1)}}45%{{transform:scale(1.35)}}100%{{transform:scale(1)}}}}
/* « Statut » à la même taille que « Questions fréquentes » */
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{{font-size:1rem}}
@media (max-width:640px){{
  :root{{--h-entete:60px}}
  .st-key-entete{{padding:0 12px}}
  .entete img{{width:32px;height:32px}}
  .entete .titre{{font-size:1.05rem}}
  .entete .sous-titre{{font-size:.75rem}}
  .st-key-bascule_theme button p{{display:none}}
  .st-key-bascule_theme button{{padding:0 10px;min-width:40px}}
  :root{{--place-bouton:62px}}
}}
</style>
"""

# Fondu des couleurs pendant le changement de thème (classe posée par le script CALAGE).
TRANSITION_THEME = """
<style>
html.theme-en-transition,html.theme-en-transition *,html.theme-en-transition *::before,
html.theme-en-transition *::after{transition:background-color .6s ease,color .6s ease,
  border-color .6s ease,fill .6s ease,stroke .6s ease,box-shadow .6s ease!important}
</style>
"""

# Mode clair de la maquette V2. Streamlit ne permet pas de changer de thème depuis le code :
# le thème sombre de config.toml reste la base, et ces règles le recouvrent quand la
# personne choisit le mode clair. (Le tableau de la page admin, dessiné dans un canevas,
# reste sombre.)
MODE_CLAIR = """
<style>
:root{--avis-oui:#4F7F3A;--avis-non:#B4532A;--accent-texte:#FFFFFF;--fond-entete:#EDEAE2;--bord-entete:#D8D3C8;--fond:#F7F5F0;--panneau:#EDEAE2;--carte:#FFFFFF;--survol:#E4E0D6;--bord:#D8D3C8;
  --texte:#211F1B;--doux:#5B554B;--accent:#A9541B;--bulle:#E6E1D6;--alerte-fond:#FFF2D4;
  --alerte:#5E3F00;--info-fond:#E4ECF7;--info:#1D3B66}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stBottom"],
[data-testid="stBottom"]>div,[data-testid="stBottomBlockContainer"]{background:var(--fond)!important}
[data-testid="stSidebar"],[data-testid="stSidebar"]>div{background:var(--panneau)!important}
.stApp :is(p,span,label,li,h1,h2,h3,h4,h5,h6,summary,strong,em,div,small){color:var(--texte)}
.stApp a,.stApp a *{color:var(--accent)!important}
.stApp svg{color:var(--texte)}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *,
.stApp [data-testid="stWidgetLabel"] svg{color:var(--doux)!important}
.stApp button[kind="secondary"],.stApp button[kind="secondaryFormSubmit"]{background:var(--carte)!important;
  border-color:var(--bord)!important;color:var(--texte)!important}
.stApp button[kind="secondary"]:hover{background:var(--survol)!important;border-color:var(--accent)!important}
.stApp button[kind="primary"],.stApp button[kind="primaryFormSubmit"]{background:var(--accent)!important;
  border-color:var(--accent)!important}
.stApp button[kind="primary"] *,.stApp button[kind="primaryFormSubmit"] *{color:#fff!important}
.stApp .stSelectbox [role="group"],.stApp [data-baseweb="input"],.stApp [data-baseweb="base-input"],
.stApp input,.stApp textarea{background:var(--carte)!important;border-color:var(--bord)!important;
  color:var(--texte)!important}
.stApp [data-baseweb="input"] button{background:var(--carte)!important}
[data-testid="stChatInput"]>div{background:var(--carte)!important;border-color:var(--bord)!important}
[data-testid="stChatInput"] textarea::placeholder{color:var(--doux)!important}
[data-baseweb="popover"] ul,[data-baseweb="popover"] li{background:var(--carte)!important;
  color:var(--texte)!important}
[data-baseweb="popover"] li:hover{background:var(--survol)!important}
[data-testid="stSelectboxVirtualDropdown"]{background:var(--carte)!important;
  border:1px solid var(--bord);box-shadow:0 6px 18px rgba(33,31,27,.12)!important}
[data-testid="stSelectboxVirtualDropdown"] [role="option"],
[data-testid="stSelectboxVirtualDropdown"] [role="option"] *{color:var(--texte)!important}
[data-testid="stSelectboxVirtualDropdown"] [role="option"],
[data-testid="stSelectboxVirtualDropdown"] [role="option"] *{background:transparent!important}
[data-testid="stSelectboxVirtualDropdown"] [role="option"][data-focused="true"]>div,
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover>div{background:var(--survol)!important}
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] *{
  color:var(--accent)!important;font-weight:600}
[data-testid="stExpander"] details{background:var(--carte);border-color:var(--bord)!important}
[data-testid="stExpander"] summary{background:var(--carte)!important}
[data-testid="stExpander"] summary:hover{background:var(--survol)!important}
[data-testid="stSidebar"] [data-testid="stExpander"] details{background:var(--fond)}
[data-testid="stSidebar"] [data-testid="stExpander"] summary{background:var(--fond)!important}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover{background:var(--survol)!important}
[data-testid="stAlertContainer"]{background:var(--alerte-fond)!important}
[data-testid="stAlertContainer"] *{color:var(--alerte)!important}
[data-testid="stAlertContentInfo"] *{color:var(--info)!important}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]){background:var(--info-fond)!important}
[data-testid="stVerticalBlockBorderWrapper"],[data-testid="stForm"]{border-color:var(--bord)!important}
hr{border-color:var(--bord)!important}
.stApp [data-testid="stButtonGroup"] button{background:var(--carte)!important;
  border-color:var(--bord)!important}
.stApp [data-testid="stButtonGroup"] button:hover{background:var(--survol)!important}
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"]{background:#F3E4D6!important;
  border-color:var(--accent)!important}
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"] *{color:var(--accent)!important}
.stApp code{background:var(--survol)!important;color:var(--texte)!important}
.stApp [data-testid="stMetric"]{border-color:var(--bord)!important}
[data-testid="stElementToolbar"]{background:transparent!important}
[data-testid="stElementToolbarButtonContainer"]{background:var(--carte)!important}
[data-testid="stTable"] table{background:var(--carte)!important;border-color:var(--bord)!important}
[data-testid="stTable"] th{background:var(--panneau)!important;color:var(--doux)!important}
[data-testid="stTable"] th,[data-testid="stTable"] td{border-color:var(--bord)!important;
  color:var(--texte)}
[data-testid="stElementToolbarButtonContainer"]{border:1px solid var(--bord);border-radius:8px}
[data-testid="stElementToolbar"] svg{color:var(--doux)!important}
[data-testid="stTooltipIcon"] button,[data-testid="stTooltipIcon"] svg{color:var(--doux)!important;
  stroke:var(--doux)!important}
.st-key-consentement label>div:first-of-type{background:#C9C3B6!important}
.st-key-consentement label>div:first-of-type>div{background:#FFFFFF!important;
  box-shadow:0 1px 2px rgba(33,31,27,.35)}
.st-key-consentement label:has(input:checked)>div:first-of-type{background:var(--accent)!important}
[data-testid="stSidebar"] button[kind="tertiary"]:hover{background:var(--survol)}
</style>
"""


def mode_clair() -> bool:
    """Le choix de la personne, gardé dans l'adresse (?theme=clair) pour survivre à F5."""
    if "mode_clair" not in st.session_state:
        st.session_state["mode_clair"] = st.query_params.get("theme") == "clair"
    return st.session_state["mode_clair"]


def _basculer_theme() -> None:
    st.session_state["mode_clair"] = not st.session_state.get("mode_clair", False)
    if st.session_state["mode_clair"]:
        st.query_params["theme"] = "clair"
    else:
        st.query_params.pop("theme", None)


# Petit script de la page, deux rôles :
# 1. Le panneau peut être élargi à la souris : le bord gauche de l'en-tête est calé sur le bord
#    droit réel du panneau (0 quand il est replié, ou sur téléphone où il passe par-dessus la
#    page). Sans JavaScript, la règle CSS ci-dessus suppose 300 px.
# 2. Passage mode clair / mode sombre en fondu : au clic sur le bouton, la classe
#    « theme-en-transition » est posée sur la page pendant 1,2 s ; elle anime les changements
#    de couleur (voir TRANSITION_THEME) le temps que Streamlit applique le nouveau thème.
#    Hors de ce moment, aucune animation : les survols restent immédiats.
CALAGE = """
<script>
(() => {
  if (window.__calageEntete) return;
  window.__calageEntete = true;
  const racine = document.documentElement;
  let precedent = null;
  const caler = () => {
    const panneau = document.querySelector('section[data-testid="stSidebar"]');
    let gauche = 0;
    if (panneau && window.innerWidth > 640 && panneau.getAttribute("data-collapsed") !== "true") {
      gauche = Math.max(0, Math.round(panneau.getBoundingClientRect().right));
    }
    if (gauche !== precedent) {
      racine.style.setProperty("--gauche-entete", gauche + "px");
      precedent = gauche;
    }
  };
  setInterval(caler, 150);
  window.addEventListener("resize", caler);
  caler();

  let minuteur = null;
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".st-key-bascule_theme")) return;
    racine.classList.add("theme-en-transition");
    clearTimeout(minuteur);
    minuteur = setTimeout(() => racine.classList.remove("theme-en-transition"), 1200);
  }, true);
})();
</script>
"""


def en_tete(sous_titre: str | None = None) -> None:
    """Zone 1 de la maquette : logo, nom, sous-titre facultatif, bouton mode clair/sombre."""
    st.html(STYLES)
    st.html(TRANSITION_THEME)
    st.html(CALAGE, unsafe_allow_javascript=True)
    clair = mode_clair()
    if clair:
        st.html(MODE_CLAIR)
    with st.container(key="entete", horizontal=True, vertical_alignment="center", gap="medium"):
        st.html(
            f'<div class="entete">{LOGO_HTML}<div><p class="titre">{NOM_APP}</p>'
            + (f'<p class="sous-titre">{sous_titre}</p>' if sous_titre else "")
            + "</div></div>",
            width="stretch",
        )
        st.button(
            "Mode sombre" if clair else "Mode clair",
            icon=":material/dark_mode:" if clair else ":material/light_mode:",
            key="bascule_theme",
            on_click=_basculer_theme,
            help="Changer les couleurs de l'affichage",
        )


@st.cache_resource(show_spinner=False)
def _journal_serveur() -> Journal:
    settings = get_settings()
    return Journal(settings.chemins.base_sqlite, settings.journal.conservation_jours)


def journal_partage() -> Journal | None:
    """Le journal SQLite (étape 10), partagé par les deux pages.

    Pendant les tests : celui injecté dans `_journal_test`, ou aucun (on n'écrit jamais dans
    data/app.db). Si la base est illisible, l'application continue sans journal.
    """
    ss = st.session_state
    if "_journal_test" in ss:
        return ss["_journal_test"]
    if "_assistant_test" in ss:
        return None
    try:
        return _journal_serveur()
    except Exception:
        log.exception("Journal indisponible")
        return None


@st.cache_resource(show_spinner=False)
def _cache_serveur() -> CacheReponses:
    settings = get_settings()
    return CacheReponses(settings.chemins.base_sqlite, settings.cache.duree_jours)


def cache_partage() -> CacheReponses | None:
    """Le cache des réponses fréquentes (F8), dans la même base que le journal.

    Mêmes règles que le journal pendant les tests ; None si le cache est désactivé
    (`cache.actif: false`) ou illisible.
    """
    ss = st.session_state
    if "_cache_test" in ss:
        return ss["_cache_test"]
    if "_assistant_test" in ss or not get_settings().cache.actif:
        return None
    try:
        return _cache_serveur()
    except Exception:
        log.exception("Cache indisponible")
        return None
