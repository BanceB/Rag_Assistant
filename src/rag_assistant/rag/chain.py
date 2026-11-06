"""Étapes 7 et 8 : la chaîne complète, de la question à la réponse sourcée.

    question (+ historique) → reformulation en question autonome (étape 8, si historique)
             → recherche + reranking (étape 6) → garde-fou avant le modèle
             → prompt augmenté → Claude (un seul appel) → garde-fous après le modèle
             → réponse + sources construites par le code + avertissements

Essai :
    uv run python -m rag_assistant.rag.chain "Comment reconnaître le swollen shoot ?"
    uv run python -m rag_assistant.rag.chain --profil technicien "Quelle dose de fongicide ?"
    uv run python -m rag_assistant.rag.chain --conversation   (plusieurs questions à la suite)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from rag_assistant.config import Settings, get_settings, secrets_manquants
from rag_assistant.rag import guardrails, prompts
from rag_assistant.rag.memory import Memoire, Reformulateur, nettoyer
from rag_assistant.rag.retriever import Passage, Recuperateur, creer_recuperateur

log = logging.getLogger(__name__)

# (prompt système, messages [{"role", "content"}]) -> (texte, usage en tokens)
Generateur = Callable[[str, list[dict]], tuple[str, dict]]


class GenerateurClaude:
    """Appel à Claude par le SDK Anthropic.

    Claude 5.5 refuse `temperature` (erreur 400) : on règle `effort` et l'on coupe la
    réflexion préalable (`between_tools`) pour répondre vite. Le SDK réessaie de lui-même
    sur les erreurs passagères (quota, surcharge).

    La réponse est reçue en flux : on mesure le délai avant le premier mot, celui que la
    personne attend avant de commencer à lire dans l'interface (étape 9). `au_fil`, s'il est
    donné, reçoit chaque morceau de texte dès son arrivée.
    """

    def __init__(
        self,
        modele: str,
        effort: str,
        max_tokens: int,
        client=None,
        reflexion: str = "between_tools",  # Haiku 5.5 accepte aussi "disabled"
    ):
        if client is None:
            import anthropic

            client = anthropic.Anthropic(max_retries=3)  # lit ANTHROPIC_API_KEY (.env)
        self.modele, self.effort, self.max_tokens, self.client = modele, effort, max_tokens, client
        self.reflexion = reflexion

    def __call__(self, systeme: str, messages: list[dict], au_fil=None) -> tuple[str, dict]:
        debut = time.perf_counter()
        premier_mot = None
        morceaux: list[str] = []
        with self.client.messages.stream(
            model=self.modele,
            max_tokens=self.max_tokens,
            system=systeme,
            messages=messages,
            thinking={"type": self.reflexion},
            output_config={"effort": self.effort},
        ) as flux:
            for morceau in flux.text_stream:
                if premier_mot is None:
                    premier_mot = time.perf_counter() - debut
                morceaux.append(morceau)
                if au_fil:
                    au_fil(morceau)
            u = flux.get_final_message().usage
        usage = {"entree": u.input_tokens, "sortie": u.output_tokens}
        if premier_mot is not None:
            usage["premier_mot_s"] = round(premier_mot, 3)
        return "".join(morceaux), usage


@dataclass
class Reponse:
    question: str
    texte: str  # la réponse, citations renumérotées [1]…[n]
    sources: list[guardrails.Source]
    refus: bool
    motif: str | None  # sous_le_seuil, aucune_reponse, hors_sujet, sans_citation
    avertissements: list[str]
    meilleur_score: float
    passages: list[Passage] = field(repr=False)
    # « partielle » : le modèle a répondu en signalant que l'information précise manque
    couverture: str = "complete"
    latences: dict = field(default_factory=dict)  # secondes : recherche, generation, total
    usage: dict = field(default_factory=dict)
    question_recherche: str = ""  # question reformulée avec l'historique (étape 8)

    def en_texte(self) -> str:
        """Réponse prête à afficher : texte, avertissements, sources."""
        parties = [self.texte]
        parties += [f"⚠ {a}" for a in self.avertissements]
        if self.sources:
            parties.append("Sources :\n" + "\n".join(s.en_texte() for s in self.sources))
        return "\n\n".join(parties)

    def en_dict(self) -> dict:
        """Version enregistrable (journal, évaluation) : sans le texte des passages."""
        return {
            "question": self.question,
            "question_recherche": self.question_recherche or self.question,
            "texte": self.texte,
            "sources": [asdict(s) for s in self.sources],
            "refus": self.refus,
            "motif": self.motif,
            "couverture": self.couverture,
            "avertissements": self.avertissements,
            "meilleur_score": round(self.meilleur_score, 4),
            "passages": [[p.chunk_id, round(p.score, 4)] for p in self.passages],
            "latences": self.latences,
            "usage": self.usage,
        }


def messages_d_historique(historique: list[dict] | None, fenetre: int) -> list[dict]:
    """Historique prêt pour l'API : citations retirées (leurs passages ne sont plus fournis),
    premier message de la personne, rôles alternés (deux messages de suite du même rôle sont
    réunis)."""
    messages: list[dict] = []
    for m in (historique or [])[-fenetre:]:
        role, contenu = m.get("role"), nettoyer(m.get("content", ""))
        if role not in ("user", "assistant") or not contenu:
            continue
        if not messages and role == "assistant":
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + contenu
        else:
            messages.append({"role": role, "content": contenu})
    if messages and messages[-1]["role"] == "user":
        # la nouvelle question suit : une réponse manquante est signalée pour garder l'alternance
        messages.append({"role": "assistant", "content": "(pas de réponse)"})
    return messages


class Assistant:
    def __init__(
        self,
        recuperateur: Recuperateur,
        generateur: Generateur,
        fenetre: int = 6,
        reformulateur: Reformulateur | None = None,
        systeme: str | None = None,
    ):
        self.recuperateur = recuperateur
        self.systeme = systeme or prompts.SYSTEME  # consignes ; une autre version à l'étape 11
        self.generateur = generateur
        self.fenetre = fenetre  # messages d'historique transmis au modèle
        self.reformulateur = reformulateur

    def repondre(
        self,
        question: str,
        historique: list[dict] | None = None,
        profil: str | None = None,
        au_fil: Callable[[str], None] | None = None,
    ) -> Reponse:
        """Répond à la question avec un seul appel au modèle (aucun en cas de refus avant).

        `historique` : messages précédents [{"role": "user" | "assistant", "content": …}].
        S'il n'est pas vide, la question est d'abord reformulée en question autonome par le
        modèle rapide, et c'est elle qui sert à la recherche ; le modèle qui rédige reçoit
        l'historique court et la question telle que la personne l'a posée.

        `au_fil` (étape 9) reçoit le texte brut du modèle morceau par morceau, pour l'afficher
        pendant qu'il s'écrit. Ce texte n'a pas encore passé les garde-fous : l'interface le
        remplace par la réponse finale (`Reponse.texte`) dès qu'elle est prête.
        """
        debut = time.perf_counter()
        latences: dict = {}
        question_recherche = question
        historique = (historique or [])[-self.fenetre :]
        if historique and self.reformulateur:
            question_recherche = self.reformulateur(historique, question)
            latences["reformulation"] = round(time.perf_counter() - debut, 3)
        t = time.perf_counter()
        resultat = self.recuperateur.recuperer(question_recherche)
        latences["recherche"] = round(time.perf_counter() - t, 3)
        passages = resultat.passages

        def refus(texte: str, motif: str, usage: dict | None = None) -> Reponse:
            latences["total"] = round(time.perf_counter() - debut, 3)
            return Reponse(
                question, texte, [], True, motif, [], resultat.meilleur_score, passages,
                latences=latences, usage=usage or {}, question_recherche=question_recherche,
            )  # fmt: skip

        texte_refus = guardrails.refus_avant_llm(
            resultat.meilleur_score, resultat.seuil, len(passages)
        )
        if texte_refus:
            return refus(texte_refus, "sous_le_seuil")

        chunks = [p.chunk for p in passages]
        messages = messages_d_historique(historique, self.fenetre)
        comprise = question_recherche if question_recherche != question else None
        messages.append(
            {
                "role": "user",
                "content": prompts.message_utilisateur(question, chunks, profil, comprise),
            }
        )
        t = time.perf_counter()
        if au_fil:
            brut, usage = self.generateur(self.systeme, messages, au_fil=au_fil)
        else:
            brut, usage = self.generateur(self.systeme, messages)
        latences["generation"] = round(time.perf_counter() - t, 3)
        if "premier_mot_s" in usage:  # délai avant le premier mot, compté depuis la question
            latences["premier_mot"] = round(t - debut + usage.pop("premier_mot_s"), 3)

        brut, couverture, sujet = guardrails.lire_etiquettes(brut)
        couverture = "partielle" if guardrails.est_partielle(brut, couverture) else "complete"
        convenue = guardrails.reponse_convenue(brut)
        if convenue == "hors_sujet":
            return refus(guardrails.REFUS_HORS_SUJET, "hors_sujet", usage)
        if convenue == "aucune_reponse":
            return refus(guardrails.REFUS_ABSENT, "aucune_reponse", usage)

        texte, sources = guardrails.construire_sources(brut, chunks)
        if not sources:
            log.warning("Réponse sans citation valide, remplacée par le refus : %r", brut[:200])
            return refus(guardrails.REFUS_ABSENT, "sans_citation", usage)

        cites = {s.doc_id for s in sources}
        avert = guardrails.avertissements(
            question, texte, [c for c in chunks if c.metadata.get("doc_id") in cites], sujet
        )
        latences["total"] = round(time.perf_counter() - debut, 3)
        return Reponse(
            question, texte, sources, False, None, avert, resultat.meilleur_score, passages,
            couverture, latences, usage, question_recherche,
        )  # fmt: skip


class Conversation:
    """Un assistant et la mémoire des sessions : enchaîner les questions sans tout répéter."""

    def __init__(self, assistant: Assistant, memoire: Memoire):
        self.assistant = assistant
        self.memoire = memoire

    def poser(self, session: str, question: str, profil: str | None = None) -> Reponse:
        reponse = self.assistant.repondre(question, self.memoire.historique(session), profil)
        self.memoire.ajouter(session, "user", question)
        self.memoire.ajouter(session, "assistant", reponse.texte)
        return reponse


def reflexion_pour(modele: str) -> str:
    """Haiku 5.5 refuse « between_tools » (erreur 400) : sa réflexion est coupée."""
    return "disabled" if "haiku" in modele else "between_tools"


def creer_assistant(settings: Settings | None = None) -> Assistant:
    """Assistant configuré par settings.yaml (recherche, reranking, seuil, modèles, effort)."""
    settings = settings or get_settings()
    generateur = GenerateurClaude(
        settings.llm.model, settings.llm.effort, settings.llm.max_tokens,
        reflexion=reflexion_pour(settings.llm.model),
    )  # fmt: skip
    # reformulation : modèle rapide, sans réflexion, réponse d'une ligne
    rapide = GenerateurClaude(settings.llm.model_rapide, "low", 200, reflexion="disabled")
    return Assistant(
        creer_recuperateur(settings),
        generateur,
        settings.memoire.fenetre_messages,
        Reformulateur(rapide),
    )


def creer_conversation(settings: Settings | None = None) -> Conversation:
    settings = settings or get_settings()
    return Conversation(creer_assistant(settings), Memoire(settings.memoire.fenetre_messages))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("question", nargs="?")
    parser.add_argument("--profil", choices=sorted(prompts.PROFILS))
    parser.add_argument(
        "--conversation", action="store_true", help="poser plusieurs questions à la suite"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    manquants = secrets_manquants()
    if manquants:
        print(f"Clés absentes du fichier .env : {', '.join(manquants)}")
        return 1

    def afficher(reponse: Reponse) -> None:
        print(reponse.en_texte())
        if reponse.question_recherche != reponse.question:
            print(f"\n— question comprise comme : {reponse.question_recherche}")
        print(
            f"— refus : {reponse.motif or 'non'} | meilleur score {reponse.meilleur_score:.2f}"
            f" | temps {reponse.latences} | tokens {reponse.usage}"
        )

    if args.conversation:
        conversation = creer_conversation()
        print("Posez vos questions (ligne vide pour quitter).")
        while question := input("\n> ").strip():
            afficher(conversation.poser("terminal", question, args.profil))
        return 0
    if not args.question:
        parser.error("donner une question, ou --conversation")
    afficher(creer_assistant().repondre(args.question, profil=args.profil))
    return 0


if __name__ == "__main__":
    sys.exit(main())
