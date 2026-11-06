"""Étape 6 : mesurer la recherche sur le jeu d'évaluation et choisir le reranker et le seuil.

Pour chaque question de eval/questions.jsonl :
- recherche vectorielle des 20 candidats (scores de similarité) ;
- reranking des 20 candidats par chaque modèle comparé (rerank-2.5, rerank-3).

Les résultats bruts (identifiants et scores, pas de texte) sont enregistrés dans
eval/resultats/recherche_<date>.jsonl : l'analyse peut être refaite sans rappeler Voyage.

Mesures :
- rappel@k : part des questions dont un document attendu figure dans les k premiers
  passages (k = 4, celui de settings.yaml). Cible de la feuille de route : au moins 90 % ;
- rappel@1 et MRR (rang moyen inverse du premier bon passage) : qualité du classement ;
- rappel@20 de la recherche vectorielle : le plafond que le reranking peut atteindre ;
- seuil : pour chaque valeur, part des questions hors sujet détectées (meilleur score sous
  le seuil) et part des questions qui ont une réponse dans le corpus rejetées à tort ;
- temps de recherche (cahier des charges : réponse complète en 5 s au plus).

Lancer la mesure (appelle Voyage : environ 2 millions de tokens de reranking par modèle) :
    uv run python -m rag_assistant.evaluation.recherche
Étape 11, comparer un autre découpage (indexer d'abord avec la même taille, par exemple
`uv run python -m rag_assistant.ingestion.pipeline --taille 1000 --chevauchement 100`) :
    uv run python -m rag_assistant.evaluation.recherche --taille 1000 --chevauchement 100 --rerankers rerank-2.5
Refaire l'analyse à partir d'un fichier déjà produit :
    uv run python -m rag_assistant.evaluation.recherche --analyser eval/resultats/recherche_2026-11-02.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from rag_assistant.config import get_settings, secrets_manquants

log = logging.getLogger(__name__)

DENSE = "vectorielle"  # nom de la méthode sans reranking dans les résultats
AVEC_REPONSE = {"normale", "demande_de_decision"}
CIBLE_RAPPEL = 0.90
CIBLE_HORS_SUJET = (
    0.90  # cahier des charges §11 : au moins 90 % des questions hors corpus détectées
)


# ---------------------------------------------------------------- collecte (appelle Voyage)


def lire_questions(chemin: Path | None = None) -> list[dict]:
    chemin = chemin or get_settings().chemins.questions_eval
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


def collecter(questions: list[dict], recuperateur, rerankers: dict, sortie: Path) -> list[dict]:
    """Interroge la base pour chaque question et ajoute une ligne par question à `sortie`.

    `recuperateur` : un Recuperateur sans reranker (on reranke ensuite avec chaque modèle).
    Une mesure interrompue reprend où elle s'était arrêtée : les questions déjà présentes
    dans `sortie` ne sont pas réinterrogées.
    """
    deja = {}
    if sortie.exists():
        deja = {e["id"]: e for e in lire_resultats(sortie)}
    sortie.parent.mkdir(parents=True, exist_ok=True)
    enregistrements = []
    with open(sortie, "a", encoding="utf-8") as f:
        for n, q in enumerate(questions, start=1):
            if q["id"] in deja:
                enregistrements.append(deja[q["id"]])
                continue
            debut = time.perf_counter()
            candidats = recuperateur.candidats(q["question"])
            duree_vectorielle = time.perf_counter() - debut
            textes = [c.chunk.page_content for c in candidats]
            classements = {
                DENSE: [[c.chunk_id, c.doc_id, round(c.similarite, 4)] for c in candidats]
            }
            durees = {DENSE: round(duree_vectorielle, 3)}
            for nom, reranker in rerankers.items():
                debut = time.perf_counter()
                ordre = reranker(q["question"], textes, None)
                durees[nom] = round(duree_vectorielle + time.perf_counter() - debut, 3)
                classements[nom] = [
                    [candidats[i].chunk_id, candidats[i].doc_id, round(s, 4)] for i, s in ordre
                ]
            e = {
                "id": q["id"],
                "acteur": q["acteur"],
                "theme": q["theme"],
                "situation": q["situation"],
                "avec_historique": bool(q.get("historique")),
                "doc_ids_attendus": q.get("doc_ids_attendus", []),
                "classements": classements,
                "durees": durees,
            }
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.flush()
            enregistrements.append(e)
            if n % 25 == 0:
                log.info("%d / %d questions", n, len(questions))
    return enregistrements


def lire_resultats(chemin: Path) -> list[dict]:
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


# ---------------------------------------------------------------- analyse (sans réseau)


def rang_du_premier_attendu(classement: list, attendus: list[str]) -> int | None:
    """Rang (1 = premier) du premier passage issu d'un document attendu, sinon None."""
    for rang, (_, doc_id, _) in enumerate(classement, start=1):
        if doc_id in attendus:
            return rang
    return None


def meilleur_score(classement: list) -> float:
    return classement[0][2] if classement else 0.0


def _part(valeurs: list[bool]) -> float:
    return sum(valeurs) / len(valeurs) if valeurs else 0.0


def mesures_classement(enregistrements: list[dict], methode: str, k: int) -> dict:
    """Rappel@1, rappel@k, MRR@k sur les questions qui ont une réponse dans le corpus."""
    rangs = [
        rang_du_premier_attendu(e["classements"][methode], e["doc_ids_attendus"])
        for e in enregistrements
        if e["situation"] in AVEC_REPONSE and e["doc_ids_attendus"]
    ]
    return {
        "questions": len(rangs),
        "rappel@1": _part([r == 1 for r in rangs]),
        f"rappel@{k}": _part([r is not None and r <= k for r in rangs]),
        "rappel@tous": _part([r is not None for r in rangs]),
        f"mrr@{k}": statistics.mean([1 / r if r and r <= k else 0.0 for r in rangs])
        if rangs
        else 0.0,
    }


def rappel_par(enregistrements: list[dict], methode: str, k: int, champ: str) -> dict[str, tuple]:
    """Rappel@k par acteur, thème… : {valeur: (rappel, nombre de questions)}."""
    groupes: dict[str, list[bool]] = defaultdict(list)
    for e in enregistrements:
        if e["situation"] in AVEC_REPONSE and e["doc_ids_attendus"]:
            r = rang_du_premier_attendu(e["classements"][methode], e["doc_ids_attendus"])
            groupes[str(e[champ])].append(r is not None and r <= k)
    return {g: (_part(v), len(v)) for g, v in sorted(groupes.items())}


def echecs(enregistrements: list[dict], methode: str, k: int) -> list[dict]:
    """Questions avec réponse dont aucun document attendu n'est dans les k premiers."""
    liste = []
    for e in enregistrements:
        if e["situation"] not in AVEC_REPONSE or not e["doc_ids_attendus"]:
            continue
        classement = e["classements"][methode]
        rang = rang_du_premier_attendu(classement, e["doc_ids_attendus"])
        if rang is None or rang > k:
            liste.append(
                {
                    "id": e["id"],
                    "attendus": e["doc_ids_attendus"],
                    "obtenus": [doc for _, doc, _ in classement[:k]],
                    "rang": rang,
                    "avec_historique": e["avec_historique"],
                }
            )
    return liste


def table_des_seuils(enregistrements: list[dict], methode: str, seuils: list[float]) -> list[dict]:
    """Pour chaque seuil : hors sujet détectés, absents détectés, questions avec réponse rejetées."""
    par_situation: dict[str, list[float]] = defaultdict(list)
    for e in enregistrements:
        par_situation[e["situation"]].append(meilleur_score(e["classements"][methode]))
    avec_reponse = [s for sit in AVEC_REPONSE for s in par_situation.get(sit, [])]
    return [
        {
            "seuil": round(seuil, 3),
            "hors_sujet_detectes": _part([s < seuil for s in par_situation.get("hors_sujet", [])]),
            "absents_detectes": _part(
                [s < seuil for s in par_situation.get("absent_du_corpus", [])]
            ),
            "avec_reponse_rejetees": _part([s < seuil for s in avec_reponse]),
        }
        for seuil in seuils
    ]


def proposer_seuil(table: list[dict], cible: float = CIBLE_HORS_SUJET) -> dict | None:
    """Le plus petit seuil qui détecte au moins `cible` des questions hors sujet.

    Le plus petit, car chaque point de seuil en plus rejette davantage de vraies questions.
    """
    possibles = [ligne for ligne in table if ligne["hors_sujet_detectes"] >= cible]
    return min(possibles, key=lambda ligne: ligne["seuil"]) if possibles else None


def durees(enregistrements: list[dict], methode: str) -> dict:
    valeurs = sorted(e["durees"][methode] for e in enregistrements if methode in e["durees"])
    if not valeurs:
        return {}
    return {
        "moyenne_s": round(statistics.mean(valeurs), 3),
        "p95_s": round(valeurs[min(len(valeurs) - 1, int(0.95 * len(valeurs)))], 3),
        "max_s": round(valeurs[-1], 3),
    }


def analyser(enregistrements: list[dict], k: int) -> dict:
    methodes = list(enregistrements[0]["classements"]) if enregistrements else []
    seuils = [i / 100 for i in range(0, 101)]
    resume: dict = {"k": k, "questions": len(enregistrements), "methodes": {}}
    for m in methodes:
        table = table_des_seuils(enregistrements, m, seuils)
        resume["methodes"][m] = {
            "classement": mesures_classement(enregistrements, m, k),
            "sans_historique": mesures_classement(
                [e for e in enregistrements if not e["avec_historique"]], m, k
            ),
            "par_acteur": rappel_par(enregistrements, m, k, "acteur"),
            "par_theme": rappel_par(enregistrements, m, k, "theme"),
            "seuil_propose": proposer_seuil(table),
            "seuils": table,
            "durees": durees(enregistrements, m),
            "echecs": echecs(enregistrements, m, k),
        }
    return resume


def afficher(resume: dict) -> None:
    k = resume["k"]
    print(f"\n{resume['questions']} questions, k = {k}\n")
    print(f"{'méthode':<12} {'rappel@1':>9} {f'rappel@{k}':>9} {f'MRR@{k}':>7} {'rappel@20':>10}"
          f" {'sans hist.':>11} {'temps moy.':>11} {'p95':>6}")  # fmt: skip
    for m, r in resume["methodes"].items():
        c, d = r["classement"], r["durees"]
        print(
            f"{m:<12} {c['rappel@1']:>9.1%} {c[f'rappel@{k}']:>9.1%} {c[f'mrr@{k}']:>7.3f}"
            f" {c['rappel@tous']:>10.1%} {r['sans_historique'][f'rappel@{k}']:>11.1%}"
            f" {d.get('moyenne_s', 0):>10.2f}s {d.get('p95_s', 0):>5.2f}s"
        )
    print(f"\nCible : rappel@{k} d'au moins {CIBLE_RAPPEL:.0%} (questions qui ont une réponse).")
    print("\nSeuil : plus petit score qui écarte au moins 90 % des questions hors sujet")
    for m, r in resume["methodes"].items():
        s = r["seuil_propose"]
        if s is None:
            print(f"  {m:<12} aucun seuil n'atteint 90 %")
        else:
            print(
                f"  {m:<12} seuil {s['seuil']:.2f} : hors sujet détectés {s['hors_sujet_detectes']:.0%},"
                f" absents détectés {s['absents_detectes']:.0%},"
                f" questions avec réponse rejetées {s['avec_reponse_rejetees']:.1%}"
            )
    meilleure = max(
        resume["methodes"], key=lambda m: resume["methodes"][m]["classement"][f"rappel@{k}"]
    )
    r = resume["methodes"][meilleure]
    print(f"\nRappel@{k} par acteur ({meilleure}) :")
    for g, (v, n) in r["par_acteur"].items():
        print(f"  {g:<22} {v:>6.1%}  ({n} questions)")
    print(f"\nRappel@{k} par thème ({meilleure}) :")
    for g, (v, n) in r["par_theme"].items():
        print(f"  {g:<22} {v:>6.1%}  ({n} questions)")
    print(f"\nÉchecs ({meilleure}) : {len(r['echecs'])}")
    for e in r["echecs"]:
        hist = " [suite de conversation]" if e["avec_historique"] else ""
        rang = f"rang {e['rang']}" if e["rang"] else "absent des 20"
        print(f"  {e['id']} attendu {e['attendus']}, obtenu {e['obtenus']} ({rang}){hist}")


def main(argv: list[str] | None = None) -> int:
    reglages = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--analyser", type=Path, metavar="FICHIER", help="analyse seule, sans Voyage"
    )
    parser.add_argument("--rerankers", default="rerank-2.5,rerank-3", help="modèles comparés")
    parser.add_argument("--limite", type=int, help="ne traiter que les N premières questions")
    parser.add_argument("--k", type=int, default=reglages.retrieval.k)
    parser.add_argument("--taille", type=int, help="découpage à mesurer (collection déjà indexée)")
    parser.add_argument("--chevauchement", type=int, help="chevauchement de ce découpage")
    args = parser.parse_args(argv)
    if args.taille:
        from dataclasses import replace

        decoupage = replace(
            reglages.chunking,
            chunk_size=args.taille,
            chunk_overlap=args.chevauchement
            if args.chevauchement is not None
            else args.taille // 10,
        )
        reglages = replace(reglages, chunking=decoupage)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("rag_assistant").setLevel(logging.INFO)

    if args.analyser:
        enregistrements = lire_resultats(args.analyser)
        sortie = args.analyser
        # documents attendus : ceux du jeu d'évaluation actuel (il a pu être complété depuis)
        attendus = {q["id"]: q.get("doc_ids_attendus", []) for q in lire_questions()}
        for e in enregistrements:
            e["doc_ids_attendus"] = attendus.get(e["id"], e["doc_ids_attendus"])
    else:
        manquants = secrets_manquants(reglages)
        if manquants:
            print(f"Clés absentes du fichier .env : {', '.join(manquants)}")
            return 1
        from rag_assistant.rag.retriever import RerankerVoyage, creer_recuperateur

        recuperateur = creer_recuperateur(reglages, sans_reranking=True)
        if args.taille and recuperateur.base._collection.count() == 0:
            c = reglages.chunking
            print(
                f"La collection du découpage {c.chunk_size}/{c.chunk_overlap} est vide. Indexer "
                f"d'abord : uv run python -m rag_assistant.ingestion.pipeline --taille "
                f"{c.chunk_size} --chevauchement {c.chunk_overlap}"
            )
            return 1
        rerankers = {m: RerankerVoyage(m) for m in filter(None, args.rerankers.split(","))}
        questions = lire_questions()[: args.limite]
        c = reglages.chunking
        suffixe = f"_{c.chunk_size}-{c.chunk_overlap}" if args.taille else ""
        sortie = (
            reglages.chemins.questions_eval.parent
            / "resultats"
            / f"recherche_{date.today()}{suffixe}.jsonl"
        )
        print(f"{len(questions)} questions, rerankers : {list(rerankers)} → {sortie}")
        enregistrements = collecter(questions, recuperateur, rerankers, sortie)

    resume = analyser(enregistrements, args.k)
    afficher(resume)
    chemin_resume = sortie.with_name(sortie.stem + "_resume.json")
    chemin_resume.write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nRésumé enregistré : {chemin_resume}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
