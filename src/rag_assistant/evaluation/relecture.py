"""Second tour de relecture : les 10 questions relues par des personnes, avant et après.

Les relecteurs (7 formulaires, 9 novembre 2026) ont noté les réponses du 2 novembre
(Sonnet, prompt V3). Ce module repose les mêmes questions avec les réglages actuels et écrit
une page Markdown qui met, pour chaque question, l'ancienne et la nouvelle réponse côte à côte,
avec leur longueur. On peut l'envoyer aux mêmes relecteurs pour un second tour.

    uv run python -m rag_assistant.evaluation.relecture --avant eval/resultats/reponses_2026-11-02_16h34.jsonl

Coût : 10 appels au modèle (moins d'un centime avec Haiku).
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from rag_assistant.config import get_settings, secrets_manquants
from rag_assistant.evaluation import reponses
from rag_assistant.evaluation.recherche import lire_questions, lire_resultats

RELUES = ["Q005", "Q010", "Q021", "Q026", "Q113", "Q118", "Q130", "Q157", "Q160", "Q234"]


def mots(texte: str) -> int:
    return len(re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", texte).split())


def page(questions: list[dict], avant: dict[str, dict], apres: dict[str, dict]) -> str:
    lignes = [
        f"# Relecture : avant et après la version 4 des consignes ({datetime.now():%d/%m/%Y})",
        "",
        "Pour chaque question : la réponse relue le 2 novembre, puis la nouvelle réponse.",
        "",
    ]
    total_avant = total_apres = 0
    for q in questions:
        a, b = avant.get(q["id"]), apres.get(q["id"])
        lignes += [f"## {q['id']} · {q['question']}", f"*Profil : {q['acteur']}*", ""]
        for titre, e in (("Avant", a), ("Après", b)):
            if e is None:
                lignes += [f"**{titre}** : (absente)", ""]
                continue
            n = mots(e["texte"])
            total_avant += n if titre == "Avant" else 0
            total_apres += n if titre == "Après" else 0
            lignes += [f"**{titre}** ({n} mots)", "", e["texte"], ""]
            if e.get("avertissements"):
                lignes += [f"> Avertissement affiché : {' '.join(e['avertissements'])}", ""]
    lignes.insert(3, f"Longueur totale : {total_avant} mots avant, {total_apres} mots après.\n")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--avant", type=Path, required=True, help="résultats relus (jsonl)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("rag_assistant").setLevel(logging.INFO)
    settings = get_settings()
    if secrets_manquants(settings):
        print(f"Clés absentes du fichier .env : {', '.join(secrets_manquants(settings))}")
        return 1
    from rag_assistant.rag.chain import creer_assistant

    par_id = {q["id"]: q for q in lire_questions()}
    questions = [par_id[i] for i in RELUES]
    horodatage = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    dossier = settings.chemins.questions_eval.parent / "resultats"
    sortie = dossier / f"relecture_{horodatage}.jsonl"
    apres = {e["id"]: e for e in reponses.collecter(questions, creer_assistant(settings), sortie)}
    avant = {e["id"]: e for e in lire_resultats(args.avant)}
    chemin = sortie.with_suffix(".md")
    chemin.write_text(page(questions, avant, apres), encoding="utf-8")
    print(f"\nPage avant / après : {chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
