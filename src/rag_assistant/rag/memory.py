"""Étape 8 : la mémoire de conversation.

Un modèle de langage n'a pas de mémoire : chaque appel est indépendant. C'est le code qui
garde l'historique de chaque conversation et le renvoie au modèle.

- `Memoire` garde les messages de chaque session (une session = une personne dans
  l'interface), dans une fenêtre glissante : seuls les N derniers messages sont gardés
  (settings.yaml, memoire.fenetre_messages), pour limiter les tokens, le coût et le temps.
- `Reformulateur` réécrit une question de suivi en question autonome avant la recherche :
  « Et c'est qui qui la paie ? » devient « Qui paie la prime du cacao certifié ARS 1000 ? ».
  Sans cela, la recherche vectorielle ne trouve rien de pertinent. Un modèle rapide et peu
  coûteux suffit (Claude Haiku 5.5) ; il n'est appelé que s'il y a un historique.

Données personnelles : l'historique peut contenir des informations sur la personne ou son
exploitation. Il ne vit qu'en mémoire vive, le temps de la session ; sa conservation dans le
journal se décide à l'étape 10.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable

# (prompt système, messages) -> (texte, usage) : même forme que le générateur de chain.py
Generateur = Callable[[str, list[dict]], tuple[str, dict]]

SESSIONS_MAX = 1000  # au-delà, la session la plus ancienne est oubliée (mémoire vive bornée)
LONGUEUR_REPONSE_MAX = 600  # caractères d'une réponse de l'assistant gardés pour la reformulation

PROMPT_REFORMULATION = """Tu reçois le début d'une conversation entre une personne et un \
assistant sur la filière cacao en Côte d'Ivoire, puis la nouvelle question de la personne.

Réécris la nouvelle question pour qu'elle se comprenne seule, sans la conversation :
- nomme le sujet de la conversation (la maladie, le ravageur, la pratique, le règlement, la \
norme, le document) au lieu de « ça », « il », « elle », « le », « les », « et pour… », \
« et si… » ;
- reprends les précisions de la conversation qui comptent pour la réponse : ce que la personne \
a décrit, le lieu, la taille de la parcelle, l'étape de travail ;
- ne commence pas par « Et » ; garde les mots de la personne ;
- n'ajoute aucune information absente de la conversation, et ne réponds pas à la question ;
- si la question se comprend déjà seule, recopie-la telle quelle.

Exemples :
Personne : Comment greffer un cacaoyer ?
Nouvelle question : Et à quelle saison ?
Réécriture : À quelle saison faut-il greffer un cacaoyer ?

Personne : Mes cabosses deviennent noires et pourrissent sur l'arbre.
Nouvelle question : Je traite avec quoi ?
Réécriture : Avec quoi traiter des cabosses qui deviennent noires et pourrissent sur l'arbre ?

Personne : Qu'est-ce que la diligence raisonnée ?
Nouvelle question : Et pour une coopérative de 300 membres ?
Réécriture : Qu'est-ce que la diligence raisonnée pour une coopérative de 300 membres ?

Écris uniquement la réécriture, sur une seule ligne."""


def nettoyer(texte: str) -> str:
    """Texte d'un message sans les numéros de citation, sur une ligne."""
    texte = re.sub(r"\[\d+(?:\s*[,;]\s*\d+)*\]", "", texte)
    return re.sub(r"\s+", " ", texte).strip()


def formater_historique(historique: list[dict]) -> str:
    lignes = []
    for m in historique:
        contenu = nettoyer(m.get("content", ""))
        if m.get("role") == "assistant":
            if len(contenu) > LONGUEUR_REPONSE_MAX:
                contenu = contenu[:LONGUEUR_REPONSE_MAX].rsplit(" ", 1)[0] + "…"
            lignes.append(f"Assistant : {contenu}")
        else:
            lignes.append(f"Personne : {contenu}")
    return "\n".join(lignes)


class Reformulateur:
    """Réécrit une question de suivi en question autonome, avec un appel au modèle rapide."""

    def __init__(self, generateur: Generateur):
        self.generateur = generateur

    def __call__(self, historique: list[dict], question: str) -> str:
        if not historique:
            return question
        message = (
            f"<conversation>\n{formater_historique(historique)}\n</conversation>\n\n"
            f"Nouvelle question : {question.strip()}"
        )
        texte, _ = self.generateur(PROMPT_REFORMULATION, [{"role": "user", "content": message}])
        lignes = [x.strip() for x in texte.strip().splitlines() if x.strip()]
        reformulee = lignes[0] if lignes else ""
        reformulee = re.sub(
            r"^\W*(question( réécrite)?|nouvelle question|réécriture)\s*:\s*",
            "",
            reformulee,
            flags=re.I,
        )
        reformulee = reformulee.strip(" «»\"'*")
        # garde-fou : une réécriture vide ou démesurée n'est pas une reformulation
        if not reformulee or len(reformulee) > 4 * len(question) + 200:
            return question
        return reformulee


class Memoire:
    """Historique de chaque session, en fenêtre glissante (mémoire vive seulement)."""

    def __init__(self, fenetre: int = 6, sessions_max: int = SESSIONS_MAX):
        self.fenetre = fenetre
        self.sessions_max = sessions_max
        self._sessions: OrderedDict[str, list[dict]] = OrderedDict()

    def historique(self, session: str) -> list[dict]:
        """Les `fenetre` derniers messages de la session (copie)."""
        return [dict(m) for m in self._sessions.get(session, [])[-self.fenetre :]]

    def ajouter(self, session: str, role: str, contenu: str) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("role doit valoir 'user' ou 'assistant'")
        messages = self._sessions.setdefault(session, [])
        self._sessions.move_to_end(session)
        messages.append({"role": role, "content": contenu})
        del messages[: -self.fenetre]  # fenêtre glissante
        while len(self._sessions) > self.sessions_max:
            self._sessions.popitem(last=False)

    def effacer(self, session: str) -> None:
        self._sessions.pop(session, None)
