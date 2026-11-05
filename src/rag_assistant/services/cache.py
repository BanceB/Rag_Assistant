"""Étape 10 (F8, mode faible connectivité) : mise en cache des réponses fréquentes.

Deux usages :
1. Réponse instantanée : une question déjà posée (même texte, même profil, sans conversation
   en cours) reçoit la réponse déjà vérifiée, sans appeler Voyage ni Claude : zéro attente,
   zéro coût, utile pour les 25 questions proposées.
2. Secours : si le service ne répond pas (connexion coupée, API indisponible), une réponse
   déjà donnée à la même question est servie même si elle est ancienne, avec sa date.

Seules les réponses complètes et sourcées sont gardées (pas les refus, ni les questions de
suivi, qui dépendent de la conversation). Chaque réponse porte la « version » de l'assistant
(base vectorielle, modèle, consignes, seuil) : réindexer le corpus ou changer le prompt rend
les anciennes réponses invisibles pour l'usage 1, sans les effacer pour l'usage 2.

Préchauffage (remplir le cache avec les questions proposées, environ 25 appels à Claude) :
    uv run python -m rag_assistant.services.cache --prechauffer
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_reponses (
    cle TEXT PRIMARY KEY,              -- question normalisée + profil
    version TEXT NOT NULL,             -- version de l'assistant qui a répondu
    question TEXT NOT NULL,            -- question normalisée
    profil TEXT,
    reponse TEXT NOT NULL,             -- JSON de Reponse.en_dict()
    cree TEXT NOT NULL,                -- UTC, ISO 8601
    utilisations INTEGER NOT NULL DEFAULT 0
);
"""


def maintenant() -> datetime:
    return datetime.now(UTC)


def normaliser(question: str) -> str:
    """« Comment  reconnaître le Swollen Shoot ?? » → « comment reconnaître le swollen shoot »."""
    texte = unicodedata.normalize("NFKC", question).lower().replace("’", "'")
    texte = re.sub(r"\s+", " ", texte).strip()
    return re.sub(r"[\s?!.…:;]+$", "", texte)


def cle(question: str, profil: str | None) -> str:
    return hashlib.sha1(f"{profil or '-'}|{normaliser(question)}".encode()).hexdigest()


def version_assistant(assistant) -> str:
    """Empreinte de ce qui change une réponse : base vectorielle, modèle, prompt, seuil."""
    from rag_assistant.rag import prompts

    morceaux = [hashlib.sha1(prompts.SYSTEME.encode()).hexdigest()[:8]]
    try:
        rec = assistant.recuperateur
        collection = rec.base._collection
        morceaux += [collection.name, str(collection.count()), str(rec.seuil), str(rec.k)]
        morceaux.append(getattr(assistant.generateur, "modele", "?"))
    except Exception:  # assistant d'un autre type (tests) : version stable
        morceaux.append(type(assistant).__name__)
    return hashlib.sha1("|".join(morceaux).encode()).hexdigest()[:12]


def peut_etre_gardee(reponse: dict) -> bool:
    return not reponse.get("refus") and bool(reponse.get("sources"))


class CacheReponses:
    def __init__(self, chemin: Path, duree_jours: int = 30):
        self.chemin = Path(chemin)
        self.duree_jours = duree_jours
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._connexion() as c:
            c.executescript(SCHEMA)

    def _connexion(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.chemin, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def lire(
        self, question: str, profil: str | None, version: str, secours: bool = False
    ) -> dict | None:
        """La réponse gardée, ou None.

        Usage normal : même version de l'assistant et moins de `duree_jours`.
        Secours (service en panne) : n'importe quelle version, n'importe quel âge.
        Renvoie le dict de la réponse avec `depuis_cache` = {"date", "secours"}.
        """
        with self._connexion() as c:
            ligne = c.execute(
                "SELECT * FROM cache_reponses WHERE cle = ?", (cle(question, profil),)
            ).fetchone()
            if ligne is None:
                return None
            if not secours:
                trop_vieille = datetime.fromisoformat(ligne["cree"]) < maintenant() - timedelta(
                    days=self.duree_jours
                )
                if ligne["version"] != version or trop_vieille:
                    return None
            c.execute(
                "UPDATE cache_reponses SET utilisations = utilisations + 1 WHERE cle = ?",
                (ligne["cle"],),
            )
        reponse = json.loads(ligne["reponse"])
        reponse["question"] = question  # la formulation de la personne, pas celle d'origine
        reponse["question_recherche"] = question
        reponse["depuis_cache"] = {"date": ligne["cree"], "secours": secours}
        reponse["latences"], reponse["usage"] = {"total": 0.0}, {}  # ni attente ni tokens
        return reponse

    def ecrire(self, question: str, profil: str | None, version: str, reponse: dict) -> bool:
        """Garde la réponse si elle le mérite (complète et sourcée). Renvoie True si gardée."""
        if not peut_etre_gardee(reponse):
            return False
        a_garder = {k: v for k, v in reponse.items() if k not in ("passages", "depuis_cache")}
        with self._connexion() as c:
            c.execute(
                "INSERT INTO cache_reponses (cle, version, question, profil, reponse, cree) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (cle) DO UPDATE SET "
                "version = excluded.version, reponse = excluded.reponse, cree = excluded.cree",
                (
                    cle(question, profil), version, normaliser(question), profil,
                    json.dumps(a_garder, ensure_ascii=False),
                    maintenant().isoformat(timespec="seconds"),
                ),
            )  # fmt: skip
        return True

    def vider(self) -> int:
        with self._connexion() as c:
            return c.execute("DELETE FROM cache_reponses").rowcount

    def statistiques(self) -> dict:
        with self._connexion() as c:
            n, utilisations = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(utilisations), 0) FROM cache_reponses"
            ).fetchone()
        return {"reponses": n, "utilisations": utilisations}


def prechauffer(profil: str | None = "agriculteur") -> int:
    """Pose les questions proposées à l'assistant et garde les réponses. Renvoie le nombre gardé."""
    from rag_assistant.app.affichage import charger_suggestions
    from rag_assistant.config import get_settings
    from rag_assistant.rag.chain import creer_assistant

    settings = get_settings()
    assistant = creer_assistant(settings)
    version = version_assistant(assistant)
    cache = CacheReponses(settings.chemins.base_sqlite, settings.cache.duree_jours)
    gardees = 0
    for categorie in charger_suggestions():
        for qid, texte in categorie.questions:
            reponse = assistant.repondre(texte, None, profil).en_dict()
            ok = cache.ecrire(texte, profil, version, reponse)
            gardees += ok
            etat = "gardée" if ok else f"non gardée ({reponse.get('motif') or 'sans source'})"
            print(f"{qid} {etat:<32} {reponse['latences'].get('total', 0):5.1f} s  {texte[:60]}")
    print(f"\n{gardees} réponse(s) dans le cache (profil : {profil or 'non précisé'}).")
    return gardees


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--prechauffer", action="store_true", help="remplir avec les questions proposées"
    )
    parser.add_argument("--profil", default="agriculteur", help="profil des réponses gardées")
    parser.add_argument("--vider", action="store_true", help="vider le cache")
    args = parser.parse_args(argv)
    from rag_assistant.config import get_settings

    settings = get_settings()
    if args.vider:
        n = CacheReponses(settings.chemins.base_sqlite).vider()
        print(f"{n} réponse(s) retirée(s) du cache.")
    if args.prechauffer:
        prechauffer(None if args.profil == "non_precise" else args.profil)
    if not (args.vider or args.prechauffer):
        print(CacheReponses(settings.chemins.base_sqlite).statistiques())
    return 0


if __name__ == "__main__":
    sys.exit(main())
