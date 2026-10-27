"""Lecture et vérification du catalogue du corpus (data/corpus_catalogue.csv).

Le catalogue décrit chaque document du corpus : une ligne par document.
Format CSV standard : séparé par des virgules, encodé en UTF-8. Il s'ouvre dans
Data Wrangler (VS Code), pandas ou LibreOffice. Un fichier réenregistré par Excel
en français (points-virgules) est aussi accepté à la lecture.

Vérifier le catalogue :
    uv run python -m rag_assistant.catalogue
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, fields
from pathlib import Path

from rag_assistant.config import get_settings

SEPARATEUR = ","  # séparateur utilisé à l'écriture
OBJECTIF_DOCUMENTS = 100  # cible du cahier des charges (§11)

THEMES = {"maladies", "eudr", "certification", "bonnes_pratiques", "indicateurs"}
TYPES = {
    "reglement",
    "guide",
    "fiche_technique",
    "norme",
    "article_scientifique",
    "rapport",
    "page_web",
}
STATUTS = {"a_verifier", "valide", "exclu"}
LANGUES = {"fr", "en"}


@dataclass(frozen=True)
class EntreeCatalogue:
    doc_id: str
    titre: str
    fichier: str  # chemin relatif à data/corpus, vide pour une page web
    url_source: str  # adresse d'origine, utilisée pour citer la source
    organisme: str
    type: str
    theme: str
    date: str  # AAAA ou AAAA-MM-JJ
    langue: str
    licence: str
    statut: str
    valide_par: str
    remarques: str


COLONNES = [f.name for f in fields(EntreeCatalogue)]


def detecter_separateur(entete: str) -> str:
    """Virgule (standard) ou point-virgule (Excel en français), d'après la ligne d'en-tête."""
    return ";" if entete.count(";") > entete.count(",") else ","


def lire_catalogue(chemin: Path) -> list[EntreeCatalogue]:
    """Lit le catalogue et renvoie une entrée par ligne non vide."""
    # utf-8-sig : accepte aussi un fichier avec BOM, comme ceux qu'écrit Excel
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        separateur = detecter_separateur(f.readline())
        f.seek(0)
        lecteur = csv.DictReader(f, delimiter=separateur)
        manquantes = set(COLONNES) - set(lecteur.fieldnames or [])
        if manquantes:
            raise ValueError(f"Colonnes manquantes dans le catalogue : {sorted(manquantes)}")
        entrees = []
        for ligne in lecteur:
            if not any((v or "").strip() for v in ligne.values()):
                continue  # ligne vide laissée par Excel
            entrees.append(EntreeCatalogue(**{c: (ligne[c] or "").strip() for c in COLONNES}))
        return entrees


def verifier_catalogue(entrees: list[EntreeCatalogue], dossier_corpus: Path) -> list[str]:
    """Renvoie la liste des problèmes trouvés (vide si le catalogue est correct)."""
    problemes = []
    doublons = [i for i, n in Counter(e.doc_id for e in entrees).items() if n > 1]
    for doc_id in doublons:
        problemes.append(f"{doc_id} : identifiant utilisé plusieurs fois")

    for e in entrees:
        nom = e.doc_id or f"(ligne sans doc_id : {e.titre[:40]})"
        if not e.doc_id:
            problemes.append(f"{nom} : doc_id manquant")
        if not e.titre:
            problemes.append(f"{nom} : titre manquant")
        if e.theme not in THEMES:
            problemes.append(f"{nom} : thème « {e.theme} » inconnu, attendu {sorted(THEMES)}")
        if e.type not in TYPES:
            problemes.append(f"{nom} : type « {e.type} » inconnu, attendu {sorted(TYPES)}")
        if e.statut not in STATUTS:
            problemes.append(f"{nom} : statut « {e.statut} » inconnu, attendu {sorted(STATUTS)}")
        if e.langue not in LANGUES:
            problemes.append(f"{nom} : langue « {e.langue} » inconnue, attendu {sorted(LANGUES)}")
        if not e.fichier and not e.url_source:
            problemes.append(f"{nom} : ni fichier ni url_source")
        if e.fichier and not (dossier_corpus / e.fichier).is_file():
            problemes.append(f"{nom} : fichier introuvable : data/corpus/{e.fichier}")
        if e.statut == "valide" and not e.valide_par:
            problemes.append(f"{nom} : statut « valide » sans valide_par")
    return problemes


def fichiers_non_catalogues(entrees: list[EntreeCatalogue], dossier_corpus: Path) -> list[str]:
    """Fichiers présents dans data/corpus mais absents du catalogue."""
    connus = {e.fichier.replace("\\", "/") for e in entrees if e.fichier}
    presents = {
        p.relative_to(dossier_corpus).as_posix()
        for p in dossier_corpus.rglob("*")
        if p.is_file() and p.name != ".gitkeep"
    }
    return sorted(presents - connus)


def main() -> None:
    chemins = get_settings().chemins
    entrees = lire_catalogue(chemins.catalogue)
    valides = [e for e in entrees if e.statut == "valide"]

    print(f"Documents catalogués : {len(entrees)}")
    print(f"Documents validés    : {len(valides)} / {OBJECTIF_DOCUMENTS} visés")
    for theme in sorted(THEMES):
        n_total = sum(e.theme == theme for e in entrees)
        n_valides = sum(e.theme == theme for e in valides)
        print(f"  {theme:<17} {n_valides:>3} validés sur {n_total}")

    problemes = verifier_catalogue(entrees, chemins.corpus)
    orphelins = fichiers_non_catalogues(entrees, chemins.corpus)
    for p in problemes:
        print(f"PROBLÈME  {p}")
    for f in orphelins:
        print(f"OUBLI     data/corpus/{f} n'est pas dans le catalogue")
    if not problemes and not orphelins:
        print("Catalogue cohérent.")


if __name__ == "__main__":
    main()
