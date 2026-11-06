"""Étape 10 : journal des échanges et des avis (F9), dans la base SQLite data/app.db.

Ce qui est enregistré pour chaque question (table `echanges`) :
- toujours, des chiffres sans contenu : date, refus et motif, nombre de sources, documents
  cités (doc_id et page), score du reranker, temps de réponse, tokens, erreur éventuelle ;
- le texte de la question et de la réponse, seulement si la personne a donné son accord,
  après masquage des courriels et des numéros de téléphone.
Et pour chaque avis 👍/👎 (table `avis`) : la valeur, reliée à l'échange. Les suggestions
libres des visiteurs (table `suggestions`) : un type et un texte, anonymisé de la même façon.

Protection des données (RGPD, §7.2 et §13 du cahier des charges) :
- minimisation : ni nom, ni adresse IP, ni navigateur ; la session est un identifiant tiré
  au hasard à l'ouverture de l'onglet, qui ne permet pas de retrouver la personne ;
- consentement : le texte n'est gardé qu'avec l'accord donné dans le panneau ;
- durée limitée : les échanges plus anciens que `journal.conservation_jours` (90 jours)
  sont supprimés automatiquement, avec leurs avis.

SQLite est fourni avec Python : rien à installer. Une connexion est ouverte à chaque
opération, ce qui permet plusieurs sessions Streamlit en même temps.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import statistics
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS echanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage TEXT NOT NULL,          -- UTC, ISO 8601
    session TEXT NOT NULL,             -- identifiant aléatoire de l'onglet
    profil TEXT,
    consentement INTEGER NOT NULL,     -- 1 : textes enregistrés
    question TEXT,                     -- NULL sans consentement
    question_recherche TEXT,
    reponse TEXT,
    suivi INTEGER NOT NULL DEFAULT 0,  -- question posée avec un historique
    refus INTEGER NOT NULL DEFAULT 0,
    motif TEXT,
    couverture TEXT,
    nb_sources INTEGER NOT NULL DEFAULT 0,
    sources TEXT,                      -- JSON [[doc_id, page], …]
    nb_avertissements INTEGER NOT NULL DEFAULT 0,
    meilleur_score REAL,
    latence_totale REAL,               -- secondes
    latence_premier_mot REAL,
    tokens_entree INTEGER,
    tokens_sortie INTEGER,
    erreur TEXT,                       -- type d'erreur, sans message
    cache INTEGER NOT NULL DEFAULT 0   -- 1 : réponse servie par le cache, 2 : cache de secours
);
CREATE INDEX IF NOT EXISTS echanges_horodatage ON echanges (horodatage);
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage TEXT NOT NULL,
    session TEXT NOT NULL,             -- même identifiant aléatoire que les échanges
    genre TEXT NOT NULL,               -- question qui manque, idée, problème
    texte TEXT NOT NULL                -- anonymisé (numéros et courriels masqués)
);
CREATE INDEX IF NOT EXISTS suggestions_horodatage ON suggestions (horodatage);
CREATE TABLE IF NOT EXISTS avis (
    echange_id INTEGER PRIMARY KEY REFERENCES echanges (id) ON DELETE CASCADE,
    horodatage TEXT NOT NULL,
    valeur INTEGER NOT NULL            -- 1 : utile, 0 : pas utile
);
"""

COURRIEL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SUITE_DE_CHIFFRES = re.compile(r"(?:\+|00)?\d[\d .\-/]{6,}\d")
CHIFFRES_MIN_NUMERO = 8  # un téléphone ivoirien en compte 10 ; « 1 800 000 FCFA » en compte 7

SEUIL_LATENCE_S = 5.0  # objectif du cahier des charges (§7.2)
LONGUEUR_SUGGESTION = 1000  # caractères gardés au plus par suggestion


def maintenant() -> datetime:
    return datetime.now(UTC)


def anonymiser(texte: str | None) -> str | None:
    """Masque courriels et numéros (téléphone, pièce d'identité) ; laisse prix et doses."""
    if not texte:
        return texte
    texte = COURRIEL.sub("[courriel]", texte)

    def numero(m: re.Match) -> str:
        chiffres = sum(c.isdigit() for c in m.group())
        return "[numéro]" if chiffres >= CHIFFRES_MIN_NUMERO else m.group()

    return SUITE_DE_CHIFFRES.sub(numero, texte)


def _quantile(valeurs: list[float], q: float) -> float | None:
    if not valeurs:
        return None
    if len(valeurs) == 1:
        return valeurs[0]
    return statistics.quantiles(valeurs, n=100, method="inclusive")[round(q * 100) - 1]


def _pourcentage(n: int, total: int) -> float | None:
    return round(100 * n / total, 1) if total else None


class Journal:
    def __init__(self, chemin: Path, conservation_jours: int = 90):
        self.chemin = Path(chemin)
        self.conservation_jours = conservation_jours
        self._derniere_purge = 0.0
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._connexion() as c:
            c.executescript(SCHEMA)
            colonnes = {r["name"] for r in c.execute("PRAGMA table_info(echanges)")}
            if "cache" not in colonnes:  # base créée avant le cache (F8) : on ajoute la colonne
                c.execute("ALTER TABLE echanges ADD COLUMN cache INTEGER NOT NULL DEFAULT 0")
        self.purger()

    def _connexion(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.chemin, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    # -------------------------------------------------------------- écriture

    def enregistrer(
        self,
        session: str,
        reponse: dict,
        *,
        profil: str | None = None,
        consentement: bool = False,
        suivi: bool = False,
    ) -> int:
        """Enregistre un échange (Reponse.en_dict()) et renvoie son identifiant."""
        self._purger_si_besoin()
        latences, usage = reponse.get("latences") or {}, reponse.get("usage") or {}
        sources = [[s.get("doc_id"), s.get("page")] for s in reponse.get("sources") or []]
        depuis_cache = reponse.get("depuis_cache") or {}
        cache = (2 if depuis_cache.get("secours") else 1) if depuis_cache else 0
        ligne = {
            "horodatage": maintenant().isoformat(timespec="seconds"),
            "session": session,
            "profil": profil,
            "consentement": int(consentement),
            "question": anonymiser(reponse.get("question")) if consentement else None,
            "question_recherche": (
                anonymiser(reponse.get("question_recherche")) if consentement else None
            ),
            "reponse": anonymiser(reponse.get("texte")) if consentement else None,
            "suivi": int(suivi),
            "refus": int(bool(reponse.get("refus"))),
            "motif": reponse.get("motif"),
            "couverture": reponse.get("couverture"),
            "nb_sources": len(sources),
            "sources": json.dumps(sources),
            "nb_avertissements": len(reponse.get("avertissements") or []),
            "meilleur_score": reponse.get("meilleur_score"),
            "latence_totale": latences.get("total"),
            "latence_premier_mot": latences.get("premier_mot"),
            "tokens_entree": usage.get("entree"),
            "tokens_sortie": usage.get("sortie"),
            "erreur": None,
            "cache": cache,
        }
        return self._inserer(ligne)

    def enregistrer_erreur(
        self, session: str, erreur: BaseException, *, profil: str | None = None
    ) -> int:
        """Une question restée sans réponse (service indisponible…) : le type d'erreur seul."""
        self._purger_si_besoin()
        return self._inserer(
            {
                "horodatage": maintenant().isoformat(timespec="seconds"),
                "session": session,
                "profil": profil,
                "consentement": 0,
                "erreur": type(erreur).__name__,
            }
        )

    def _inserer(self, ligne: dict) -> int:
        colonnes = ", ".join(ligne)
        marques = ", ".join(f":{k}" for k in ligne)
        with self._connexion() as c:
            return c.execute(
                f"INSERT INTO echanges ({colonnes}) VALUES ({marques})", ligne
            ).lastrowid

    def noter(self, echange_id: int, valeur: int | None) -> None:
        """Avis 👍 (1) / 👎 (0) ; None retire l'avis. Un seul avis par échange."""
        with self._connexion() as c:
            if valeur is None:
                c.execute("DELETE FROM avis WHERE echange_id = ?", (echange_id,))
                return
            c.execute(
                "INSERT INTO avis (echange_id, horodatage, valeur) VALUES (?, ?, ?) "
                "ON CONFLICT (echange_id) DO UPDATE SET valeur = excluded.valeur, "
                "horodatage = excluded.horodatage",
                (echange_id, maintenant().isoformat(timespec="seconds"), int(bool(valeur))),
            )

    # -------------------------------------------------------------- conservation

    def purger(self, jours: int | None = None) -> int:
        """Supprime échanges (avec leurs avis) et suggestions plus anciens que la durée de
        conservation. Renvoie le nombre de lignes supprimées."""
        limite = (maintenant() - timedelta(days=jours or self.conservation_jours)).isoformat(
            timespec="seconds"
        )
        with self._connexion() as c:
            n = c.execute("DELETE FROM echanges WHERE horodatage < ?", (limite,)).rowcount
            n += c.execute("DELETE FROM suggestions WHERE horodatage < ?", (limite,)).rowcount
        self._derniere_purge = time.time()
        return n

    def _purger_si_besoin(self) -> None:
        if time.time() - self._derniere_purge > 3600:  # au plus une fois par heure
            self.purger()

    def tout_effacer(self) -> int:
        with self._connexion() as c:
            n = c.execute("DELETE FROM echanges").rowcount
            return n + c.execute("DELETE FROM suggestions").rowcount

    # -------------------------------------------------------------- suggestions des visiteurs

    def ajouter_suggestion(self, session: str, genre: str, texte: str) -> int:
        """Suggestion libre envoyée depuis l'en-tête du chat (F9), sans nom, anonymisée."""
        texte = (anonymiser(texte.strip()) or "")[:LONGUEUR_SUGGESTION]
        if not texte:
            raise ValueError("suggestion vide")
        self._purger_si_besoin()
        with self._connexion() as c:
            return c.execute(
                "INSERT INTO suggestions (horodatage, session, genre, texte) VALUES (?, ?, ?, ?)",
                (maintenant().isoformat(timespec="seconds"), session, genre, texte),
            ).lastrowid

    def suggestions(self, n: int = 200) -> list[dict]:
        """Les suggestions, de la plus récente à la plus ancienne."""
        with self._connexion() as c:
            lignes = c.execute(
                "SELECT * FROM suggestions ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(r) for r in lignes]

    def exporter_suggestions_csv(self) -> str:
        lignes = self.suggestions(100_000)
        sortie = io.StringIO()
        if lignes:
            ecrivain = csv.DictWriter(sortie, fieldnames=list(lignes[0].keys()))
            ecrivain.writeheader()
            ecrivain.writerows(lignes)
        return sortie.getvalue()

    # -------------------------------------------------------------- lecture

    def _lignes(self, depuis_jours: int | None = None) -> list[sqlite3.Row]:
        requete = (
            "SELECT e.*, a.valeur AS avis FROM echanges e LEFT JOIN avis a ON a.echange_id = e.id"
        )
        parametres: tuple = ()
        if depuis_jours:
            requete += " WHERE e.horodatage >= ?"
            limite = maintenant() - timedelta(days=depuis_jours)
            parametres = (limite.isoformat(timespec="seconds"),)
        with self._connexion() as c:
            return c.execute(requete + " ORDER BY e.id", parametres).fetchall()

    def statistiques(self, depuis_jours: int | None = None) -> dict:
        """Indicateurs du tableau de bord (§11 du cahier des charges)."""
        lignes = self._lignes(depuis_jours)
        erreurs = [r for r in lignes if r["erreur"]]
        traitees = [r for r in lignes if not r["erreur"]]
        repondues = [r for r in traitees if not r["refus"]]
        refus = [r for r in traitees if r["refus"]]
        # temps mesurés sur les réponses calculées : une réponse du cache (0 s) flatterait le
        # pipeline ; le nombre de réponses servies par le cache est compté à part
        calculees = [r for r in traitees if not r["cache"]]
        totales = [r["latence_totale"] for r in calculees if r["latence_totale"] is not None]
        premiers = [
            r["latence_premier_mot"]
            for r in calculees
            if not r["refus"] and r["latence_premier_mot"]
        ]
        avis = [r["avis"] for r in lignes if r["avis"] is not None]
        par_jour = Counter(r["horodatage"][:10] for r in lignes)
        documents = Counter(doc for r in repondues for doc, _ in json.loads(r["sources"] or "[]"))
        return {
            "questions": len(lignes),
            "sessions": len({r["session"] for r in lignes}),
            "erreurs": len(erreurs),
            "reponses": len(repondues),
            "refus": len(refus),
            "taux_refus": _pourcentage(len(refus), len(traitees)),
            "refus_par_motif": dict(Counter(r["motif"] or "inconnu" for r in refus)),
            "taux_sourcees": _pourcentage(
                sum(1 for r in repondues if r["nb_sources"] > 0), len(repondues)
            ),
            "partielles": sum(1 for r in repondues if r["couverture"] == "partielle"),
            "suivis": sum(1 for r in traitees if r["suivi"]),
            "latence_mediane": _quantile(totales, 0.5),
            "latence_p90": _quantile(totales, 0.9),
            "premier_mot_median": _quantile(premiers, 0.5),
            "taux_sous_5s": _pourcentage(
                sum(1 for t in totales if t <= SEUIL_LATENCE_S), len(totales)
            ),
            "avis": len(avis),
            "taux_utiles": _pourcentage(sum(avis), len(avis)),
            "consentements": sum(1 for r in traitees if r["consentement"]),
            "depuis_cache": sum(1 for r in traitees if r["cache"] == 1),
            "secours": sum(1 for r in traitees if r["cache"] == 2),
            "par_jour": dict(sorted(par_jour.items())),
            "documents_cites": dict(documents.most_common(10)),
        }

    def derniers(self, n: int = 50) -> list[dict]:
        """Derniers échanges, du plus récent au plus ancien (textes seulement si consentis)."""
        lignes = self._lignes()[-n:]
        return [dict(r) for r in reversed(lignes)]

    def exporter_csv(self) -> str:
        """Tout le journal (avec les avis), pour l'analyse dans un tableur."""
        lignes = self._lignes()
        sortie = io.StringIO()
        if lignes:
            ecrivain = csv.DictWriter(sortie, fieldnames=list(lignes[0].keys()))
            ecrivain.writeheader()
            ecrivain.writerows(dict(r) for r in lignes)
        return sortie.getvalue()
