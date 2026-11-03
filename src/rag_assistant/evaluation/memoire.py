"""Étape 8 : mesurer la mémoire de conversation.

1. Recherche sur les 14 questions de suivi du jeu d'évaluation (« Et c'est qui qui la
   paie ? »), dans trois cas :
   - la question seule, sans historique (ce que faisait la chaîne jusqu'ici) ;
   - la question reformulée par le modèle rapide à partir de l'historique ;
   - la question posée en entier (eval/dialogues.json, rédigée à la main) : la référence.
   Critère de la feuille de route : les questions de suivi retrouvent les mêmes bons
   passages que si elles avaient été posées en entier.
2. Cinq dialogues de 3 tours passés dans la chaîne complète (reformulation, recherche,
   réponse), enregistrés en Markdown pour être relus.

    uv run python -m rag_assistant.evaluation.memoire
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from rag_assistant.config import get_settings, secrets_manquants
from rag_assistant.evaluation.recherche import lire_questions

log = logging.getLogger(__name__)
CAS = ("seule", "reformulee", "complete")


def rang_attendu(doc_ids: list[str], attendus: list[str]) -> int | None:
    for rang, d in enumerate(doc_ids, start=1):
        if d in attendus:
            return rang
    return None


def mesurer_suivis(
    questions: list[dict], completes: dict, recuperateur, reformulateur
) -> list[dict]:
    lignes = []
    for q in questions:
        historique = [{"role": "user", "content": h} for h in q["historique"]]
        t = time.perf_counter()
        reformulee = reformulateur(historique, q["question"])
        duree = round(time.perf_counter() - t, 3)
        textes = {"seule": q["question"], "reformulee": reformulee, "complete": completes[q["id"]]}
        ligne = {"id": q["id"], "attendus": q["doc_ids_attendus"], "duree_reformulation": duree}
        for cas, texte in textes.items():
            r = recuperateur.recuperer(texte)
            ligne[cas] = {
                "texte": texte,
                "chunks": [p.chunk_id for p in r.passages],
                "docs": [p.doc_id for p in r.passages],
                "meilleur_score": round(r.meilleur_score, 4),
                "pertinent": r.pertinent,
            }
        lignes.append(ligne)
        log.info("%s : %s", q["id"], reformulee)
    return lignes


def analyser_suivis(lignes: list[dict], k: int = 4) -> dict:
    resume: dict = {"questions": len(lignes)}
    for cas in CAS:
        rangs = [rang_attendu(x[cas]["docs"][:k], x["attendus"]) for x in lignes]
        resume[cas] = {
            f"rappel@{k}": sum(r is not None for r in rangs) / len(lignes),
            "sous_le_seuil": sum(not x[cas]["pertinent"] for x in lignes),
        }
    # mêmes passages que la question complète : part des chunks communs dans les k premiers
    for cas in ("seule", "reformulee"):
        communs = [
            len(set(x[cas]["chunks"][:k]) & set(x["complete"]["chunks"][:k])) / k for x in lignes
        ]
        resume[cas]["passages_communs_avec_complete"] = statistics.mean(communs)
    resume["duree_reformulation_mediane_s"] = statistics.median(
        x["duree_reformulation"] for x in lignes
    )
    return resume


def jouer_dialogues(dialogues: list[dict], conversation) -> list[dict]:
    sortie = []
    for d in dialogues:
        tours = []
        for i, question in enumerate(d["tours"], start=1):
            r = conversation.poser(d["id"], question, d.get("profil"))
            tours.append({"tour": i, **r.en_dict(), "en_texte": r.en_texte()})
        sortie.append({"id": d["id"], "profil": d.get("profil"), "tours": tours})
    return sortie


def ecrire_dialogues(dialogues: list[dict], chemin: Path) -> None:
    lignes = ["# Dialogues de 3 tours (étape 8)", ""]
    for d in dialogues:
        lignes += [f"## {d['id']} ({d['profil']})", ""]
        for t in d["tours"]:
            lignes.append(f"**Tour {t['tour']} — question :** {t['question']}")
            if t["question_recherche"] != t["question"]:
                lignes.append(f"*Comprise comme :* {t['question_recherche']}")
            lignes += ["", t["en_texte"], "", "---", ""]
    chemin.write_text("\n".join(lignes), encoding="utf-8")


def afficher(resume: dict) -> None:
    print(f"\n{resume['questions']} questions de suivi")
    print(f"{'cas':<12} {'rappel@4':>9} {'sous le seuil':>14} {'passages communs':>17}")
    for cas in CAS:
        r = resume[cas]
        communs = r.get("passages_communs_avec_complete")
        communs = f"{communs:.0%}" if communs is not None else "référence"
        print(f"{cas:<12} {r['rappel@4']:>9.0%} {r['sous_le_seuil']:>14} {communs:>17}")
    print(f"Reformulation : {resume['duree_reformulation_mediane_s']:.2f} s (médiane)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sans-dialogues", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("rag_assistant").setLevel(logging.INFO)
    if secrets_manquants():
        print(f"Clés absentes du fichier .env : {', '.join(secrets_manquants())}")
        return 1
    from rag_assistant.rag.chain import Conversation, creer_assistant
    from rag_assistant.rag.memory import Memoire

    reglages = get_settings()
    donnees = json.loads(
        (reglages.chemins.questions_eval.parent / "dialogues.json").read_text("utf-8")
    )
    suivis = [q for q in lire_questions() if q["historique"]]
    assistant = creer_assistant(reglages)
    lignes = mesurer_suivis(
        suivis, donnees["completes"], assistant.recuperateur, assistant.reformulateur
    )
    resume = analyser_suivis(lignes)
    afficher(resume)

    dossier = reglages.chemins.questions_eval.parent / "resultats"
    base = dossier / f"memoire_{datetime.now():%Y-%m-%d_%Hh%M}"
    resultat = {"resume": resume, "suivis": lignes}
    if not args.sans_dialogues:
        conversation = Conversation(assistant, Memoire(reglages.memoire.fenetre_messages))
        resultat["dialogues"] = jouer_dialogues(donnees["dialogues"], conversation)
        ecrire_dialogues(resultat["dialogues"], base.with_suffix(".md"))
        print(f"Dialogues à relire : {base.with_suffix('.md')}")
    base.with_suffix(".json").write_text(
        json.dumps(resultat, ensure_ascii=False, indent=1), "utf-8"
    )
    print(f"Résultats : {base.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
