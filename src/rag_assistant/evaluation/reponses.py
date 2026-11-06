"""Étape 7 : premier essai de la chaîne complète sur un échantillon du jeu d'évaluation.

Échantillon (71 questions par défaut) : les 14 questions hors sujet, les 14 absentes du
corpus, les 13 demandes de décision et 30 questions normales tirées au hasard (graine fixe),
réparties entre les thèmes. Les suites de conversation sont exclues : elles relèvent de
l'étape 8.

Mesures :
- questions hors sujet et absentes refusées (cible du cahier : au moins 90 % des questions
  hors corpus détectées ; feuille de route : toutes les questions hors sujet refusées) ;
- questions avec réponse refusées à tort ;
- réponses avec au moins une source, et dont une source est un document attendu ;
- avertissements présents quand le jeu d'évaluation en attend un, et en trop sinon ;
- temps de réponse (cible : 5 s) et coût.

Les réponses sont enregistrées dans eval/resultats/reponses_<date>_<heure>.jsonl (une
mesure interrompue se complète avec --reprendre FICHIER), et 10 d'entre
elles dans un fichier Markdown à faire relire par une personne non spécialiste.

    uv run python -m rag_assistant.evaluation.reponses
    uv run python -m rag_assistant.evaluation.reponses --analyser eval/resultats/reponses_2026-11-02_16h20.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rag_assistant.config import get_settings, secrets_manquants
from rag_assistant.evaluation.recherche import AVEC_REPONSE, lire_questions, lire_resultats

log = logging.getLogger(__name__)

NORMALES_PAR_DEFAUT = 30
GRAINE = 7
A_RELIRE = 10
# Tarifs Claude Sonnet 5.5 relevés le 2 novembre 2026, en dollars par million de tokens
PRIX_ENTREE, PRIX_SORTIE = 2.0, 10.0


def echantillon(questions: list[dict], normales: int = NORMALES_PAR_DEFAUT) -> list[dict]:
    """Toutes les questions particulières, plus `normales` questions normales sans historique."""
    particulieres = [q for q in questions if q["situation"] != "normale" and not q["historique"]]
    candidates = [q for q in questions if q["situation"] == "normale" and not q["historique"]]
    par_theme: dict[str, list[dict]] = defaultdict(list)
    for q in candidates:
        par_theme[q["theme"]].append(q)
    hasard = random.Random(GRAINE)
    for liste in par_theme.values():
        hasard.shuffle(liste)
    choisies: list[dict] = []
    while len(choisies) < min(normales, len(candidates)):  # une par thème, à tour de rôle
        for theme in sorted(par_theme):
            if par_theme[theme] and len(choisies) < normales:
                choisies.append(par_theme[theme].pop())
    return sorted(particulieres + choisies, key=lambda q: q["id"])


def collecter(questions: list[dict], assistant, sortie: Path) -> list[dict]:
    """Une ligne par question dans `sortie` ; une mesure interrompue reprend où elle en était."""
    deja = {e["id"]: e for e in lire_resultats(sortie)} if sortie.exists() else {}
    sortie.parent.mkdir(parents=True, exist_ok=True)
    enregistrements = []
    with open(sortie, "a", encoding="utf-8") as f:
        for n, q in enumerate(questions, start=1):
            if q["id"] in deja:
                enregistrements.append(deja[q["id"]])
                continue
            reponse = assistant.repondre(q["question"], profil=q["acteur"])
            e = {
                "id": q["id"],
                "acteur": q["acteur"],
                "theme": q["theme"],
                "situation": q["situation"],
                "avertissement_attendu": q.get("avertissement_attendu", False),
                "doc_ids_attendus": q.get("doc_ids_attendus", []),
                "modele": getattr(getattr(assistant, "generateur", None), "modele", None),
                **reponse.en_dict(),
                "en_texte": reponse.en_texte(),
            }
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.flush()
            enregistrements.append(e)
            log.info("%d / %d  %s  %s", n, len(questions), q["id"], e["motif"] or "réponse")
    return enregistrements


def _part(valeurs: list[bool]) -> float:
    return sum(valeurs) / len(valeurs) if valeurs else 0.0


def _detectee(e: dict) -> bool:
    return e["refus"] or e.get("couverture") == "partielle"


def analyser(enregistrements: list[dict]) -> dict:
    par = defaultdict(list)
    for e in enregistrements:
        par[e["situation"]].append(e)
    avec_reponse = [e for e in enregistrements if e["situation"] in AVEC_REPONSE]
    repondues = [e for e in avec_reponse if not e["refus"]]
    totaux = sorted(e["latences"].get("total", 0) for e in enregistrements if not e["refus"])
    premiers = sorted(
        e["latences"]["premier_mot"] for e in enregistrements if "premier_mot" in e["latences"]
    )
    entree = sum(e["usage"].get("entree", 0) for e in enregistrements)
    sortie = sum(e["usage"].get("sortie", 0) for e in enregistrements)
    motifs: dict[str, int] = defaultdict(int)
    for e in enregistrements:
        motifs[e["motif"] or "réponse"] += 1
    return {
        "questions": len(enregistrements),
        "par_situation": {s: len(v) for s, v in sorted(par.items())},
        "motifs": dict(motifs),
        "hors_sujet_refusees": _part([e["refus"] for e in par["hors_sujet"]]),
        "absentes_refusees": _part([e["refus"] for e in par["absent_du_corpus"]]),
        "hors_corpus_refusees": _part(
            [e["refus"] for e in par["hors_sujet"] + par["absent_du_corpus"]]
        ),
        # détectée = refusée, ou réponse qui dit d'emblée que l'information précise manque
        "absentes_detectees": _part([_detectee(e) for e in par["absent_du_corpus"]]),
        "hors_corpus_detectees": _part(
            [_detectee(e) for e in par["hors_sujet"] + par["absent_du_corpus"]]
        ),
        "avec_reponse_partielles": _part([e.get("couverture") == "partielle" for e in repondues]),
        "avec_reponse_refusees": _part([e["refus"] for e in avec_reponse]),
        "refus_a_tort": [e["id"] for e in avec_reponse if e["refus"]],
        "repondues_avec_source": _part([bool(e["sources"]) for e in repondues]),
        "source_attendue_citee": _part(
            [
                any(s["doc_id"] in e["doc_ids_attendus"] for s in e["sources"])
                for e in repondues
                if e["doc_ids_attendus"]
            ]
        ),
        "avertissement_present_si_attendu": _part(
            [bool(e["avertissements"]) for e in repondues if e["avertissement_attendu"]]
        ),
        "avertissement_en_trop": _part(
            [bool(e["avertissements"]) for e in repondues if not e["avertissement_attendu"]]
        ),
        "hors_corpus_acceptees": [
            e["id"] for e in par["hors_sujet"] + par["absent_du_corpus"] if not _detectee(e)
        ],
        "temps_moyen_s": round(statistics.mean(totaux), 2) if totaux else None,
        "temps_p95_s": round(totaux[min(len(totaux) - 1, int(0.95 * len(totaux)))], 2)
        if totaux
        else None,
        "temps_max_s": round(totaux[-1], 2) if totaux else None,
        "premier_mot_median_s": round(statistics.median(premiers), 2) if premiers else None,
        "temps_median_s": round(statistics.median(totaux), 2) if totaux else None,
        "tokens": {"entree": entree, "sortie": sortie},
        "cout_usd": round((entree * PRIX_ENTREE + sortie * PRIX_SORTIE) / 1e6, 3),
    }


def afficher(r: dict) -> None:
    print(f"\n{r['questions']} questions {r['par_situation']}")
    print(f"Issues : {r['motifs']}\n")
    print(f"Hors sujet refusées                  {r['hors_sujet_refusees']:.0%}")
    print(f"Absentes du corpus refusées          {r['absentes_refusees']:.0%}")
    print(f"Hors corpus refusées                 {r['hors_corpus_refusees']:.0%}")
    print(f"Absentes détectées (refus ou partiel) {r['absentes_detectees']:.0%}")
    print(f"Hors corpus détectées (cible ≥ 90 %) {r['hors_corpus_detectees']:.0%}")
    print(f"  non détectées : {r['hors_corpus_acceptees']}")
    print(
        f"Questions avec réponse refusées      {r['avec_reponse_refusees']:.0%}  {r['refus_a_tort']}"
    )
    print(f"Réponses avec au moins une source    {r['repondues_avec_source']:.0%}")
    print(f"Réponses partielles (info manquante) {r['avec_reponse_partielles']:.0%}")
    print(f"… dont une source attendue           {r['source_attendue_citee']:.0%}")
    print(f"Avertissement quand il est attendu   {r['avertissement_present_si_attendu']:.0%}")
    print(f"Avertissement non attendu            {r['avertissement_en_trop']:.0%}")
    print(
        f"Temps (réponses) : médiane {r.get('temps_median_s')} s, moyenne {r['temps_moyen_s']} s,"
        f" p95 {r['temps_p95_s']} s, max {r['temps_max_s']} s (cible 5 s)"
    )
    print(f"Délai avant le premier mot : médiane {r.get('premier_mot_median_s')} s")
    print(f"Tokens : {r['tokens']}, coût ≈ {r['cout_usd']} $")


def ecrire_a_relire(enregistrements: list[dict], chemin: Path, nombre: int = A_RELIRE) -> None:
    """Les réponses à faire lire à une personne non spécialiste, avec une grille simple."""
    choisies = [e for e in enregistrements if e["situation"] == "normale" and not e["refus"]]
    choisies = random.Random(GRAINE).sample(choisies, min(nombre, len(choisies)))
    lignes = [
        "# Réponses à faire relire",
        "",
        "Pour chaque réponse, noter de 1 (non) à 5 (oui) : ai-je compris ? est-ce utile ? "
        "est-ce trop long ? Relever les mots difficiles.",
        "",
    ]
    for e in sorted(choisies, key=lambda e: e["id"]):
        lignes += [
            f"## {e['id']} ({e['acteur']}, {e['theme']})",
            "",
            f"**Question :** {e['question']}",
            "",
            e["en_texte"],
            "",
            "Compris : _/5 · Utile : _/5 · Longueur : _/5 · Mots difficiles :",
            "",
        ]
    chemin.write_text("\n".join(lignes), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--analyser", type=Path, metavar="FICHIER", help="analyse seule")
    parser.add_argument(
        "--reprendre", type=Path, metavar="FICHIER", help="compléter une mesure interrompue"
    )
    parser.add_argument("--normales", type=int, default=NORMALES_PAR_DEFAUT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("rag_assistant").setLevel(logging.INFO)

    if args.analyser:
        sortie = args.analyser
        enregistrements = lire_resultats(sortie)
    else:
        if secrets_manquants():
            print(f"Clés absentes du fichier .env : {', '.join(secrets_manquants())}")
            return 1
        from rag_assistant.rag.chain import creer_assistant

        questions = echantillon(lire_questions(), args.normales)
        dossier = get_settings().chemins.questions_eval.parent / "resultats"
        horodatage = datetime.now().strftime("%Y-%m-%d_%Hh%M")
        sortie = args.reprendre or dossier / f"reponses_{horodatage}.jsonl"
        print(f"{len(questions)} questions → {sortie}")
        enregistrements = collecter(questions, creer_assistant(), sortie)

    resume = analyser(enregistrements)
    afficher(resume)
    sortie.with_name(sortie.stem + "_resume.json").write_text(
        json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    a_relire = sortie.with_name(sortie.stem + "_a_relire.md")
    ecrire_a_relire(enregistrements, a_relire)
    print(f"\nRéponses à faire relire : {a_relire}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
