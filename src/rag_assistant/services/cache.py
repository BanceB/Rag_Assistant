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

Préchauffage (remplir le cache avec les questions proposées, environ 25 appels à Claude par
statut) : depuis la page /admin (section « Cache des réponses fréquentes »), ou en ligne de
commande :
    uv run python -m rag_assistant.services.cache --prechauffer --profil technicien
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
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

    def est_presente(self, question: str, profil: str | None, version: str) -> bool:
        """Vrai si la question a une réponse utilisable (même version, pas trop vieille)."""
        limite = (maintenant() - timedelta(days=self.duree_jours)).isoformat(timespec="seconds")
        with self._connexion() as c:
            ligne = c.execute(
                "SELECT 1 FROM cache_reponses WHERE cle = ? AND version = ? AND cree >= ?",
                (cle(question, profil), version, limite),
            ).fetchone()
        return ligne is not None

    def compter(
        self, questions: list[str], profils: list[str | None], version: str
    ) -> dict[str | None, int]:
        """Pour chaque profil, le nombre de ces questions qui ont une réponse utilisable."""
        return {p: sum(self.est_presente(q, p, version) for q in questions) for p in profils}

    def vider(self) -> int:
        with self._connexion() as c:
            return c.execute("DELETE FROM cache_reponses").rowcount

    def statistiques(self) -> dict:
        with self._connexion() as c:
            n, utilisations = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(utilisations), 0) FROM cache_reponses"
            ).fetchone()
        return {"reponses": n, "utilisations": utilisations}


ECHECS_AVANT_ARRET = 3
SECONDES_PAR_QUESTION = 5  # ordre de grandeur mesuré lors des préchauffages, pour l'estimation


def questions_proposees() -> list[tuple[str, str]]:
    """Les questions fréquentes du panneau du chat : [(identifiant, texte)]."""
    from rag_assistant.app.affichage import charger_suggestions

    return [
        (qid, texte) for categorie in charger_suggestions() for qid, texte in categorie.questions
    ]


def _afficher(qid: str, texte: str, etat: str, reponse: dict | None) -> None:
    """Suivi en ligne de commande (une ligne par question)."""
    if etat == "echec":
        print(f"{qid} échec : {reponse}  {texte[:60]}")
        return
    if etat == "deja":
        print(f"{qid} {'déjà dans le cache':<32}         {texte[:60]}")
        return
    libelle = (
        "gardée" if etat == "gardee" else f"non gardée ({reponse.get('motif') or 'sans source'})"
    )
    print(f"{qid} {libelle:<32} {reponse['latences'].get('total', 0):5.1f} s  {texte[:60]}")


def remplir(
    profil: str | None,
    assistant,
    cache: CacheReponses,
    questions: list[tuple[str, str]],
    *,
    seulement_manquantes: bool = False,
    arret: threading.Event | None = None,
    sur_question: Callable[[str, str, str, object], None] = _afficher,
) -> tuple[int, bool]:
    """Pose les questions à l'assistant pour ce profil et garde les bonnes réponses.

    `sur_question(qid, texte, etat, detail)` est appelée après chaque question, avec l'état
    « gardee », « non_gardee », « deja » (déjà dans le cache) ou « echec ».
    Renvoie (nombre de réponses gardées, interrompu) : interrompu après ECHECS_AVANT_ARRET
    échecs de suite (connexion coupée) ou sur demande (`arret`).
    """
    version = version_assistant(assistant)
    gardees = echecs_de_suite = 0
    for qid, texte in questions:
        if arret is not None and arret.is_set():
            return gardees, True
        if seulement_manquantes and cache.est_presente(texte, profil, version):
            sur_question(qid, texte, "deja", None)
            continue
        try:
            reponse = assistant.repondre(texte, None, profil).en_dict()
        except Exception as exc:  # coupure réseau, service indisponible…
            echecs_de_suite += 1
            sur_question(qid, texte, "echec", type(exc).__name__)
            if echecs_de_suite >= ECHECS_AVANT_ARRET:
                return gardees, True
            continue
        echecs_de_suite = 0
        ok = cache.ecrire(texte, profil, version, reponse)
        gardees += ok
        sur_question(qid, texte, "gardee" if ok else "non_gardee", reponse)
    return gardees, False


def prechauffer(profil: str | None = "agriculteur", seulement_manquantes: bool = False) -> int:
    """Ligne de commande : remplit le cache pour un profil. Renvoie le nombre gardé."""
    from rag_assistant.config import get_settings
    from rag_assistant.rag.chain import creer_assistant

    settings = get_settings()
    assistant = creer_assistant(settings)
    cache = CacheReponses(settings.chemins.base_sqlite, settings.cache.duree_jours)
    gardees, interrompu = remplir(
        profil, assistant, cache, questions_proposees(), seulement_manquantes=seulement_manquantes
    )
    if interrompu:
        print(
            f"\nArrêt après {ECHECS_AVANT_ARRET} échecs de suite : vérifiez la connexion "
            "internet, puis relancez la commande."
        )
        print(f"{gardees} réponse(s) gardée(s) avant l'arrêt.")
        return gardees
    print(f"\n{gardees} réponse(s) dans le cache (profil : {profil or 'non précisé'}).")
    return gardees


@dataclass
class EtatPrechauffage:
    en_cours: bool = False
    profils: list = field(default_factory=list)
    profil: str | None = None  # profil en cours
    total: int = 0  # questions à traiter, tous profils confondus
    faites: int = 0
    gardees: int = 0
    deja: int = 0
    non_gardees: int = 0
    echecs: int = 0
    interrompu: bool = False
    arrete_par_l_equipe: bool = False
    debut: str | None = None
    fin: str | None = None


class Prechauffage:
    """Remplissage du cache lancé depuis /admin, dans un fil d'exécution du serveur.

    Il continue si la page est fermée ; un seul remplissage à la fois. L'assistant utilisé est
    celui du chat (pas de seconde base vectorielle en mémoire).
    """

    def __init__(self):
        self._verrou = threading.Lock()
        self._arret = threading.Event()
        self._etat = EtatPrechauffage()

    def etat(self) -> dict:
        with self._verrou:
            return asdict(self._etat)

    def lancer(
        self,
        assistant,
        cache: CacheReponses,
        profils: list[str | None],
        questions: list[tuple[str, str]],
        seulement_manquantes: bool = True,
    ) -> bool:
        """Démarre le remplissage ; False si un remplissage est déjà en cours."""
        with self._verrou:
            if self._etat.en_cours:
                return False
            self._arret.clear()
            self._etat = EtatPrechauffage(
                en_cours=True, profils=list(profils), total=len(profils) * len(questions),
                debut=maintenant().isoformat(timespec="seconds"),
            )  # fmt: skip
        fil = threading.Thread(
            target=self._executer,
            args=(assistant, cache, list(profils), questions, seulement_manquantes),
            name="prechauffage-cache",
            daemon=True,
        )
        fil.start()
        return True

    def arreter(self) -> None:
        self._arret.set()

    def _suivre(self, qid: str, texte: str, etat: str, detail: object) -> None:
        with self._verrou:
            self._etat.faites += 1
            if etat == "gardee":
                self._etat.gardees += 1
            elif etat == "deja":
                self._etat.deja += 1
            elif etat == "non_gardee":
                self._etat.non_gardees += 1
            else:
                self._etat.echecs += 1

    def _executer(self, assistant, cache, profils, questions, seulement_manquantes) -> None:
        interrompu = False
        try:
            for profil in profils:
                with self._verrou:
                    self._etat.profil = profil
                _, interrompu = remplir(
                    profil, assistant, cache, questions,
                    seulement_manquantes=seulement_manquantes, arret=self._arret,
                    sur_question=self._suivre,
                )  # fmt: skip
                if interrompu:
                    break
        except Exception:  # sécurité : le fil ne doit jamais rester « en cours »
            interrompu = True
        finally:
            with self._verrou:
                self._etat.en_cours = False
                self._etat.profil = None
                self._etat.interrompu = interrompu
                self._etat.arrete_par_l_equipe = self._arret.is_set()
                self._etat.fin = maintenant().isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--prechauffer", action="store_true", help="remplir avec les questions proposées"
    )
    parser.add_argument("--profil", default="agriculteur", help="profil des réponses gardées")
    parser.add_argument(
        "--manquantes", action="store_true", help="ne poser que les questions absentes du cache"
    )
    parser.add_argument("--vider", action="store_true", help="vider le cache")
    args = parser.parse_args(argv)
    from rag_assistant.config import get_settings

    settings = get_settings()
    if args.vider:
        n = CacheReponses(settings.chemins.base_sqlite).vider()
        print(f"{n} réponse(s) retirée(s) du cache.")
    if args.prechauffer:
        prechauffer(None if args.profil == "non_precise" else args.profil, args.manquantes)
    if not (args.vider or args.prechauffer):
        print(CacheReponses(settings.chemins.base_sqlite).statistiques())
    return 0


if __name__ == "__main__":
    sys.exit(main())
