"""Étape 9 : la logique de l'interface qui ne dépend pas de Streamlit (donc testable seule).

- texte_provisoire : ce qu'on montre pendant que la réponse s'écrit ;
- en_markdown / sources_markdown : mise en forme de la réponse finale ;
- Limiteur : nombre de questions par heure et par session (protège le budget API) ;
- mot_de_passe_valide : comparaison du mot de passe d'administration ;
- charger_suggestions : les questions proposées par catégorie (config/suggestions.yaml).
"""

from __future__ import annotations

import hmac
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from rag_assistant.config import PROJECT_ROOT
from rag_assistant.rag.prompts import AUCUNE_REPONSE, ETIQUETTES, HORS_SUJET

SUGGESTIONS = PROJECT_ROOT / "config" / "suggestions.yaml"

CITATION = re.compile(r"\s?\[\d+(?:\s*,\s*\d+)*\]")
MOTS_CONVENUS = (AUCUNE_REPONSE, HORS_SUJET)


# ------------------------------------------------------------------ pendant l'écriture


def texte_provisoire(brut: str) -> str:
    """Texte affiché pendant le flux, avant les garde-fous.

    On cache ce que la personne ne doit pas voir : les numéros de citation (ils seront
    renumérotés à la fin), la ligne ETIQUETTES (lue puis retirée par le code) et les mots
    convenus AUCUNE_REPONSE / HORS_SUJET (remplacés par un message type), y compris quand
    ils ne sont arrivés qu'à moitié.
    """
    debut = brut.lstrip().lstrip("*_ ")
    if any(m.startswith(debut) or debut.startswith(m) for m in MOTS_CONVENUS if debut):
        return ""
    ligne_etiquettes = re.search(rf"(?:^|\n)[^\w\n]*{ETIQUETTES}", brut)
    if ligne_etiquettes:
        brut = brut[: ligne_etiquettes.start()]
    lignes = brut.split("\n")
    fin = lignes[-1].strip().strip("*_").upper()
    if fin and fin.isalpha() and ETIQUETTES.startswith(fin) and len(lignes) > 1:
        brut = "\n".join(lignes[:-1])  # début possible de la ligne ETIQUETTES
    texte = CITATION.sub("", brut)
    texte = re.sub(r"\[\d*(?:\s*,\s*\d*)*$", "", texte)  # citation coupée en deux morceaux
    return echapper(texte.rstrip(" *_#\n"))


def echapper(texte: str) -> str:
    """Le markdown de Streamlit lit `$…$` comme une formule mathématique : on échappe $."""
    return texte.replace("$", r"\$")


# ------------------------------------------------------------------ réponse finale


def en_markdown(texte: str) -> str:
    """Réponse finale : les citations [1] restent visibles, mises en exposant discret."""
    return CITATION.sub(lambda m: f" **{m.group().strip()}**", echapper(texte))


def sources_markdown(sources: list[dict]) -> str:
    """Une ligne par source : numéro, titre (lien), organisme, année, page, section."""
    lignes = []
    for s in sources:
        titre = s.get("titre") or s.get("doc_id", "Document")
        titre = f"[{titre}]({s['url']})" if s.get("url") else titre
        details = [x for x in (s.get("organisme"), s.get("annee")) if x]
        if s.get("page"):
            details.append(f"p. {s['page']}")
        ligne = f"**[{s.get('numero', '?')}]** {titre}"
        if details:
            ligne += " — " + ", ".join(str(x) for x in details)
        if s.get("section"):
            ligne += f"  \n*Section : {s['section']}*"
        lignes.append(ligne)
    return echapper("\n\n".join(lignes))


def libelle_sources(nb: int) -> str:
    return f"{nb} source" + ("s" if nb > 1 else "")


# ------------------------------------------------------------------ limites et accès


@dataclass
class Limiteur:
    """Au plus `maximum` questions par `fenetre_s` secondes pour une session."""

    maximum: int = 30
    fenetre_s: float = 3600
    horodatages: list[float] = field(default_factory=list)

    def _purger(self, maintenant: float) -> None:
        self.horodatages = [t for t in self.horodatages if maintenant - t < self.fenetre_s]

    def autoriser(self, maintenant: float | None = None) -> bool:
        """Compte la question si elle est autorisée ; renvoie False si la limite est atteinte."""
        maintenant = time.time() if maintenant is None else maintenant
        self._purger(maintenant)
        if len(self.horodatages) >= self.maximum:
            return False
        self.horodatages.append(maintenant)
        return True

    def attente_minutes(self, maintenant: float | None = None) -> int:
        """Minutes avant de pouvoir reposer une question (0 si c'est déjà possible)."""
        maintenant = time.time() if maintenant is None else maintenant
        self._purger(maintenant)
        if len(self.horodatages) < self.maximum:
            return 0
        reste = self.fenetre_s - (maintenant - self.horodatages[0])
        return max(1, round(reste / 60))


def mot_de_passe_valide(saisi: str, attendu: str | None) -> bool:
    """Comparaison en temps constant ; jamais valide si aucun mot de passe n'est configuré."""
    if not attendu or not saisi:
        return False
    return hmac.compare_digest(saisi.encode(), attendu.encode())


# ------------------------------------------------------------------ suggestions


@dataclass
class Categorie:
    id: str
    libelle: str
    questions: list[tuple[str, str]]  # (identifiant, texte)
    icone: str | None = None
    couleur: str | None = None  # couleur de l'icône (mode sombre)
    couleur_clair: str | None = None  # couleur de l'icône en mode clair


def charger_suggestions(chemin: Path = SUGGESTIONS) -> list[Categorie]:
    if not chemin.exists():
        return []
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    return [
        Categorie(
            c["id"],
            c.get("libelle", c["id"]),
            [(q.get("id", ""), q["texte"]) for q in c.get("questions", [])],
            c.get("icone"),
            c.get("couleur"),
            c.get("couleur_clair") or c.get("couleur"),
        )
        for c in donnees.get("categories", [])
    ]
