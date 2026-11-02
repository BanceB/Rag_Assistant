"""Étape 7 : les garde-fous, en trois couches.

1. Avant le modèle : si le meilleur passage est sous le seuil du reranker (D9), on répond
   par un refus type sans appeler Claude. Rapide, gratuit et sûr.
2. Dans le prompt : le modèle écrit AUCUNE_REPONSE ou HORS_SUJET quand les passages ne
   répondent pas ; le code remplace ces mots par un message type.
3. Après le modèle : les citations [n] sont vérifiées. Les numéros inexistants sont
   retirés ; une réponse sans aucune citation valide est remplacée par le refus type,
   car rien ne prouve qu'elle vient des documents.

S'y ajoutent les avertissements de non-substitution (cahier des charges §13) sur les sujets
sensibles : traitements avec des produits, conformité EUDR, certification.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from langchain_core.documents import Document

from rag_assistant.rag.prompts import (
    AUCUNE_REPONSE,
    COUVERTURES,
    DEBUT_PARTIELLE,
    ETIQUETTES,
    HORS_SUJET,
    SUJETS_SENSIBLES,
)

THEMES_TRAITES = (
    "les maladies et ravageurs du cacaoyer, les bonnes pratiques agricoles, le règlement "
    "européen sur la déforestation (EUDR), la certification (ARS 1000, Fairtrade, Rainforest "
    "Alliance) et les indicateurs de durabilité"
)
ORIENTATION = (
    "Pour une question précise sur votre exploitation, adressez-vous à un technicien de "
    "l'ANADER, à votre coopérative ou au CNRA."
)

REFUS_SOUS_SEUIL = (
    "Je n'ai pas trouvé d'information sur ce sujet dans mes documents. Je réponds aux "
    f"questions sur {THEMES_TRAITES}. {ORIENTATION}"
)
REFUS_ABSENT = (
    "Je n'ai pas cette information dans mes documents. Les documents que je consulte ne "
    f"permettent pas de répondre de façon sûre à cette question. {ORIENTATION}"
)
REFUS_HORS_SUJET = (
    "Je ne peux pas répondre à cette question : je suis un assistant spécialisé dans la "
    f"filière cacao. Je réponds aux questions sur {THEMES_TRAITES}."
)

AVERTISSEMENTS = {
    "traitement": (
        "Avant tout traitement, utilisez uniquement un produit homologué, respectez l'étiquette "
        "et protégez-vous ; demandez conseil à un technicien de l'ANADER ou du CNRA."
    ),
    "conformite": (
        "Cette réponse ne vaut pas avis de conformité : la vérification revient à l'opérateur "
        "qui met le cacao sur le marché européen et aux autorités compétentes."
    ),
    "certification": (
        "La décision de certification revient à l'organisme de certification : vérifiez les "
        "exigences en vigueur auprès de lui ou de votre coopérative."
    ),
    "decision": (
        "Cette réponse présente ce que disent les documents ; la décision vous appartient. "
        "Faites-vous accompagner par un technicien de l'ANADER, votre coopérative ou "
        "l'organisme compétent."
    ),
}
# Produits chimiques : toujours un avertissement s'ils apparaissent dans la réponse, même si
# le modèle ne l'a pas signalé (filet de sécurité)
PRODUITS_CHIMIQUES = (
    r"pesticide|fongicide|insecticide|herbicide|nematicide|phytosanitaire|matiere active"
)

# Mots qui signalent un sujet sensible, cherchés dans la question et dans la réponse
# (sans accents, en minuscules)
MOTS_SENSIBLES = {
    "traitement": r"pesticide|fongicide|insecticide|herbicide|nematicide|produit (chimique|phyto)"
    r"|phytosanitaire|matiere active|pulveris|traitement chimique|dose|traiter avec|g/l|ml/",
    "conformite": r"eudr|conforme|conformite|diligence raisonnee|geolocalisation",
    "certification": r"certifi|ars 1000|ars-1000|fairtrade|rainforest|audit",
}
THEMES_SENSIBLES = {"eudr": "conformite", "certification": "certification"}

CITATION = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def _simplifier(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in sans_accents if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------- couche 1 : avant le modèle


def refus_avant_llm(meilleur_score: float, seuil: float | None, nb_passages: int) -> str | None:
    """Le message de refus si rien n'est assez pertinent, sinon None (on appelle le modèle)."""
    if nb_passages == 0 or (seuil is not None and meilleur_score < seuil):
        return REFUS_SOUS_SEUIL
    return None


# ---------------------------------------------------------------- couche 2 : réponses convenues


def reponse_convenue(texte: str) -> str | None:
    """« aucune_reponse » ou « hors_sujet » si le modèle a répondu par un mot convenu."""
    debut = texte.strip().strip("*_ .").upper()
    if debut.startswith(HORS_SUJET):
        return "hors_sujet"
    if debut.startswith(AUCUNE_REPONSE):
        return "aucune_reponse"
    return None


def lire_etiquettes(texte: str) -> tuple[str, str, str | None]:
    """Retire la ligne « ETIQUETTES : couverture=… ; avertissement=… » écrite par le modèle.

    Renvoie (texte sans la ligne, couverture, sujet sensible). Sans ligne lisible : couverture
    « complete » et sujet None (les avertissements sont alors déduits des mots employés).
    """
    lignes = texte.rstrip().splitlines()
    for i in range(len(lignes) - 1, -1, -1):
        if re.match(rf"\W*{ETIQUETTES}\W*:", lignes[i].strip(), re.IGNORECASE):
            valeurs = dict(re.findall(r"(\w+)\s*=\s*(\w+)", _simplifier(lignes[i])))
            couverture = valeurs.get("couverture", "complete")
            sujet = valeurs.get("avertissement")
            reste = "\n".join(lignes[:i] + lignes[i + 1 :]).strip()
            return (
                reste,
                couverture if couverture in COUVERTURES else "complete",
                sujet if sujet in SUJETS_SENSIBLES else None,
            )
    return texte.strip(), "complete", None


def est_partielle(texte: str, couverture: str) -> bool:
    """Réponse partielle : étiquetée comme telle ET qui le dit d'emblée à la personne.

    Les deux conditions ensemble évitent de compter comme « information absente » une
    réponse complète où le modèle signale seulement un détail manquant.
    """
    return couverture == "partielle" and texte.lstrip("*_ ").startswith(DEBUT_PARTIELLE)


# ---------------------------------------------------------------- couche 3 : citations


def numeros_cites(texte: str) -> list[int]:
    """Numéros cités, dans l'ordre de première apparition : « [2] … [1][2] » → [2, 1]."""
    vus: list[int] = []
    for groupe in CITATION.findall(texte):
        for n in re.split(r"\s*[,;]\s*", groupe):
            if int(n) not in vus:
                vus.append(int(n))
    return vus


@dataclass(frozen=True)
class Source:
    numero: int  # numéro affiché dans la réponse
    doc_id: str
    titre: str
    organisme: str
    annee: str
    page: int | None
    section: str
    url: str

    def en_texte(self) -> str:
        ligne = f"[{self.numero}] {self.titre}"
        details = ", ".join(x for x in (self.organisme, self.annee) if x)
        if details:
            ligne += f" — {details}"
        if self.page:
            ligne += f", p. {self.page}"
        if self.url:
            ligne += f". {self.url}"
        return ligne


def construire_sources(texte: str, chunks: list[Document]) -> tuple[str, list[Source]]:
    """Renumérote les citations de 1 à n dans l'ordre de lecture et construit les sources.

    Les numéros qui ne correspondent à aucun passage sont retirés du texte. Deux passages de
    la même page d'un même document deviennent une seule source.
    """
    nouveaux: dict[int, int] = {}  # numéro du passage -> numéro affiché
    sources: list[Source] = []
    par_page: dict[tuple, int] = {}
    for n in numeros_cites(texte):
        if not 1 <= n <= len(chunks):
            continue
        m = chunks[n - 1].metadata
        cle = (m.get("doc_id"), m.get("page"))
        if cle not in par_page:
            par_page[cle] = len(sources) + 1
            sources.append(
                Source(
                    numero=len(sources) + 1,
                    doc_id=m.get("doc_id", ""),
                    titre=m.get("titre", ""),
                    organisme=m.get("organisme", ""),
                    annee=str(m.get("date", ""))[:4],
                    page=m.get("page"),
                    section=m.get("section", ""),
                    url=m.get("url_source", ""),
                )
            )
        nouveaux[n] = par_page[cle]

    def remplacer(correspondance: re.Match) -> str:
        numeros = [int(x) for x in re.split(r"\s*[,;]\s*", correspondance.group(1))]
        gardes = list(dict.fromkeys(nouveaux[x] for x in numeros if x in nouveaux))
        return "".join(f"[{x}]" for x in gardes)

    texte = CITATION.sub(remplacer, texte)
    texte = re.sub(r"(\[\d+\])(?:\1)+", r"\1", texte)  # [1][1] -> [1]
    texte = re.sub(r"[ \t]+([.,;:!?])", r"\1", texte)  # espace laissée par une citation retirée
    return texte.strip(), sources


# ---------------------------------------------------------------- avertissements


def avertissements(
    question: str, reponse: str, chunks_cites: list[Document], sujet: str | None = None
) -> list[str]:
    """Avertissements de non-substitution (cahier des charges §13).

    `sujet` : celui que le modèle a indiqué dans sa ligne d'étiquettes. Il comprend le sens de
    la question (« Mon cacao est-il conforme ? » appelle un avertissement, « Que dit la FAQ ? »
    non). Les produits chimiques cités dans la réponse déclenchent toujours l'avertissement
    « traitement ». Sans étiquette, on se rabat sur les mots de la question et de la réponse
    et sur le thème des passages cités.
    """
    if sujet is not None:
        sujets = [] if sujet == "aucun" else [sujet]
        if re.search(PRODUITS_CHIMIQUES, _simplifier(reponse)):
            sujets.append("traitement")
    else:
        texte = _simplifier(f"{question}\n{reponse}")
        sujets = [s for s, motif in MOTS_SENSIBLES.items() if re.search(motif, texte)]
        for c in chunks_cites:
            theme = THEMES_SENSIBLES.get(c.metadata.get("theme", ""))
            if theme and theme not in sujets:
                sujets.append(theme)
    return [AVERTISSEMENTS[s] for s in AVERTISSEMENTS if s in sujets]
