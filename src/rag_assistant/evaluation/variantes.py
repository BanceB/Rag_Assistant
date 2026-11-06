"""Étape 11 : comparer plusieurs réglages de la chaîne sur le même échantillon de questions.

Chaque variante modifie un seul réglage de config/settings.yaml, le reste étant identique :
- reference      : réglages actuels (depuis D15 : Claude Haiku 5.5, effort low, k = 4) ;
- haiku          : Claude Haiku 5.5 rédige les réponses (plus rapide, 20 fois moins cher) ;
- sonnet         : Claude Sonnet 5.5 rédige les réponses (le modèle d'avant D15) ;
- effort_medium  : effort medium (plus de réflexion, plus lent) ;
- k3             : 3 passages donnés au modèle au lieu de 4 (prompt plus court) ;
- court          : consigne « au plus 70 mots » au lieu de 100 (les réponses de l'étape 7
                   font 120 mots en médiane, et le temps de génération suit leur longueur).

Les variantes passent l'une après l'autre sur les mêmes questions (échantillon de l'étape 7 :
71 questions dont 28 hors corpus) : les écarts viennent du réglage, pas des questions.
Chaque variante produit eval/resultats/variante_<nom>_<date>.jsonl (relançable avec
--reprendre) et le tableau comparatif est écrit dans eval/resultats/comparaison_<date>.md.

    uv run python -m rag_assistant.evaluation.variantes
    uv run python -m rag_assistant.evaluation.variantes --variantes reference,haiku --normales 10
    uv run python -m rag_assistant.evaluation.variantes --analyser eval/resultats/variante_*_2026-11-06_10h00.jsonl

Mesure du 5 novembre 2026 (décision D15) : reference = Sonnet ; haiku l'a emporté.
Coût pour les 71 questions : environ 0,7 $ par variante Sonnet (mesuré à l'étape 7 : 4 400
tokens d'entrée et 330 de sortie par réponse), environ 0,03 $ pour Haiku (tarifs relevés le
5 novembre 2026), plus le reranking Voyage. Durée : 5 à 6 minutes par variante.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from rag_assistant.config import Settings, get_settings, secrets_manquants
from rag_assistant.evaluation import reponses
from rag_assistant.evaluation.recherche import lire_questions, lire_resultats

log = logging.getLogger(__name__)

# dollars par million de tokens (entrée, sortie), https://platform.claude.com/docs/en/about-claude/pricing
TARIFS = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
SEUIL_S = 5.0  # cahier des charges §7.2

DESCRIPTIONS = {
    "reference": "Réglages actuels de settings.yaml",
    "haiku": "Haiku 5.5 rédige les réponses",
    "sonnet": "Sonnet 5.5 rédige les réponses",
    "effort_medium": "Effort medium",
    "k3": "3 passages au lieu de 4",
    "court": "Consigne de 70 mots au plus au lieu de 100",
}
LONGUEUR_ACTUELLE, LONGUEUR_COURTE = "au plus 100 mots", "au plus 70 mots"


def consignes(nom: str) -> str | None:
    """Le prompt système de la variante, ou None pour garder celui de prompts.py."""
    if nom != "court":
        return None
    from rag_assistant.rag.prompts import SYSTEME

    if LONGUEUR_ACTUELLE not in SYSTEME:
        raise ValueError(f"« {LONGUEUR_ACTUELLE} » introuvable dans prompts.SYSTEME")
    return SYSTEME.replace(LONGUEUR_ACTUELLE, LONGUEUR_COURTE)


def appliquer(settings: Settings, nom: str) -> Settings:
    """Les réglages de la variante : un seul changement par rapport aux réglages actuels."""
    if nom == "reference":
        return settings
    if nom == "haiku":
        return replace(settings, llm=replace(settings.llm, model=settings.llm.model_rapide))
    if nom == "sonnet":
        return replace(settings, llm=replace(settings.llm, model="claude-sonnet-5-5"))
    if nom == "effort_medium":
        return replace(settings, llm=replace(settings.llm, effort="medium"))
    if nom == "k3":
        return replace(settings, retrieval=replace(settings.retrieval, k=3))
    if nom == "court":
        return settings  # seul le prompt change (voir consignes)
    raise ValueError(f"variante inconnue : {nom} (connues : {', '.join(DESCRIPTIONS)})")


def mesures(enregistrements: list[dict], modele: str) -> dict:
    """Le résumé de l'étape 7, plus la part des réponses en 5 s ou moins et le coût réel."""
    r = reponses.analyser(enregistrements)
    repondues = [e for e in enregistrements if not e["refus"]]
    totaux = [e["latences"].get("total", 0) for e in repondues]
    r["sous_5s"] = sum(t <= SEUIL_S for t in totaux) / len(totaux) if totaux else None
    r["plus_de_5s"] = sum(t > SEUIL_S for t in totaux)
    prix_entree, prix_sortie = TARIFS.get(modele, (2.0, 10.0))
    t = r["tokens"]
    r["cout_usd"] = round((t["entree"] * prix_entree + t["sortie"] * prix_sortie) / 1e6, 3)
    r["cout_1000_questions_usd"] = (
        round(1000 * r["cout_usd"] / len(enregistrements), 2) if enregistrements else None
    )
    r["modele"] = modele
    return r


def modele_de(enregistrements: list[dict], nom: str) -> str:
    """Le modèle noté dans les résultats ; sinon (fichiers du 5 novembre 2026, avant D15) :
    Haiku pour la variante haiku, Sonnet pour les autres."""
    notes = {e.get("modele") for e in enregistrements if e.get("modele")}
    if len(notes) == 1:
        return notes.pop()
    return "claude-haiku-5-5" if nom == "haiku" else "claude-sonnet-5-5"


def _pct(v) -> str:
    return "—" if v is None else f"{v:.0%}"


def _s(v) -> str:
    return "—" if v is None else f"{v:.1f} s".replace(".", ",")


LIGNES = [
    ("Hors corpus détectées (cible ≥ 90 %)", lambda r: _pct(r["hors_corpus_detectees"])),
    ("Questions avec réponse refusées à tort", lambda r: _pct(r["avec_reponse_refusees"])),
    ("Réponses avec au moins une source", lambda r: _pct(r["repondues_avec_source"])),
    ("… dont un document attendu cité", lambda r: _pct(r["source_attendue_citee"])),
    ("Avertissement quand il est attendu", lambda r: _pct(r["avertissement_present_si_attendu"])),
    ("Avertissement non attendu", lambda r: _pct(r["avertissement_en_trop"])),
    ("Réponses en 5 s ou moins (cible)", lambda r: _pct(r["sous_5s"])),
    ("Temps médian d'une réponse", lambda r: _s(r["temps_median_s"])),
    ("Temps au 95e centile", lambda r: _s(r["temps_p95_s"])),
    ("Premier mot (médiane)", lambda r: _s(r["premier_mot_median_s"])),
    ("Coût pour 1 000 questions", lambda r: f"{r['cout_1000_questions_usd']} $".replace(".", ",")),
]


def tableau(resumes: dict[str, dict]) -> str:
    """Tableau Markdown : une colonne par variante, une ligne par mesure."""
    noms = list(resumes)
    lignes = [
        "| Mesure | " + " | ".join(noms) + " |",
        "| --- | " + " | ".join("---" for _ in noms) + " |",
    ]
    for libelle, valeur in LIGNES:
        lignes.append(f"| {libelle} | " + " | ".join(valeur(resumes[n]) for n in noms) + " |")
    return "\n".join(lignes)


def ecrire_comparaison(resumes: dict[str, dict], chemin: Path) -> None:
    n = next(iter(resumes.values()))["questions"] if resumes else 0
    texte = [
        f"# Comparaison des réglages ({datetime.now():%d/%m/%Y %Hh%M})",
        "",
        f"{n} questions, les mêmes pour chaque variante.",
        "",
        *[f"- **{nom}** : {DESCRIPTIONS.get(nom, nom)}" for nom in resumes],
        "",
        tableau(resumes),
        "",
        "Non détectées et refus à tort, par variante :",
        "",
        *[
            f"- {nom} : hors corpus acceptées {r['hors_corpus_acceptees']}, "
            f"refus à tort {r['refus_a_tort']}"
            for nom, r in resumes.items()
        ],
        "",
    ]
    chemin.write_text("\n".join(texte), encoding="utf-8")


def nom_de_fichier(chemin: Path) -> str:
    m = re.match(r"variante_(.+?)_\d{4}-\d{2}-\d{2}_", chemin.name)
    return m.group(1) if m else chemin.stem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--variantes", default=",".join(DESCRIPTIONS), help="noms séparés par ,")
    parser.add_argument("--normales", type=int, default=reponses.NORMALES_PAR_DEFAUT)
    parser.add_argument(
        "--horodatage", help="reprendre une comparaison interrompue (AAAA-MM-JJ_HHhMM)"
    )
    parser.add_argument("--analyser", nargs="+", type=Path, metavar="FICHIER")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("rag_assistant").setLevel(logging.INFO)
    settings = get_settings()
    dossier = settings.chemins.questions_eval.parent / "resultats"
    resumes: dict[str, dict] = {}

    if args.analyser:
        for chemin in args.analyser:
            nom = nom_de_fichier(chemin)
            enregistrements = lire_resultats(chemin)
            resumes[nom] = mesures(enregistrements, modele_de(enregistrements, nom))
        horodatage = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    else:
        if secrets_manquants(settings):
            print(f"Clés absentes du fichier .env : {', '.join(secrets_manquants(settings))}")
            return 1
        from rag_assistant.rag.chain import creer_assistant

        questions = reponses.echantillon(lire_questions(), args.normales)
        horodatage = args.horodatage or datetime.now().strftime("%Y-%m-%d_%Hh%M")
        for nom in filter(None, args.variantes.split(",")):
            reglages = appliquer(settings, nom)
            sortie = dossier / f"variante_{nom}_{horodatage}.jsonl"
            print(f"\n=== {nom} : {DESCRIPTIONS[nom]} ({len(questions)} questions) → {sortie}")
            assistant = creer_assistant(reglages)
            if consignes(nom):
                assistant.systeme = consignes(nom)
            enregistrements = reponses.collecter(questions, assistant, sortie)
            resumes[nom] = mesures(enregistrements, reglages.llm.model)
            sortie.with_name(sortie.stem + "_resume.json").write_text(
                json.dumps(resumes[nom], ensure_ascii=False, indent=1), encoding="utf-8"
            )

    print("\n" + tableau(resumes))
    chemin = dossier / f"comparaison_{horodatage}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    ecrire_comparaison(resumes, chemin)
    print(f"\nTableau enregistré : {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
