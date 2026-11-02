"""Étape 6 : retrouver les passages qui répondent à une question, avec un score fiable.

Deux passes :
1. recherche vectorielle : les `fetch_k` chunks (20) dont le vecteur est le plus proche de
   celui de la question (similarité cosinus, entre 0 et 1). Rapide, mais le score dépend
   beaucoup de la formulation et de la langue : 0,50 pour une question en anglais sur un
   texte français, 0,73 pour une question en français bien formulée ;
2. reranking : un modèle Voyage relit la question avec chacun des 20 candidats et leur
   donne un score de pertinence. On garde les `k` meilleurs (4). Ce score est plus fiable
   et sert au seuil : si le meilleur passage est en dessous, aucun passage n'est jugé
   pertinent et l'agent dira que le corpus ne contient pas la réponse (garde-fou, étape 7).

Le seuil dépend du modèle de reranking : il se fixe par la mesure
(`uv run python -m rag_assistant.evaluation.recherche`) et vit dans settings.yaml.

Essai à la main :
    uv run python -m rag_assistant.ingestion.pipeline --chercher "symptômes du swollen shoot"
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

from rag_assistant.config import Settings, get_settings
from rag_assistant.ingestion.indexer import (
    avec_reessais,
    creer_embeddings,
    nom_collection,
    ouvrir_base,
)

# (question, textes des candidats, nombre à garder) -> [(indice du candidat, score)], du
# plus pertinent au moins pertinent
Reranker = Callable[[str, list[str], int | None], list[tuple[int, float]]]


@dataclass(frozen=True)
class Passage:
    chunk: Document
    score: float  # score final : celui du reranker s'il y en a un, sinon la similarité
    similarite: float  # similarité cosinus de la recherche vectorielle
    rang_initial: int  # rang dans la recherche vectorielle (1 = le plus proche)

    @property
    def doc_id(self) -> str:
        return self.chunk.metadata.get("doc_id", "")

    @property
    def chunk_id(self) -> str:
        return self.chunk.metadata.get("chunk_id", "")


@dataclass
class Resultat:
    question: str
    passages: list[Passage]  # les k passages retenus, du plus pertinent au moins pertinent
    candidats: list[Passage]  # les fetch_k candidats de la recherche vectorielle
    seuil: float | None

    @property
    def meilleur_score(self) -> float:
        return self.passages[0].score if self.passages else 0.0

    @property
    def pertinent(self) -> bool:
        """Au moins un passage dépasse le seuil (sans seuil : au moins un passage trouvé)."""
        if not self.passages:
            return False
        return self.seuil is None or self.meilleur_score >= self.seuil


class RerankerVoyage:
    """Reranker Voyage AI (`rerank-2.5`, `rerank-3`…), avec nouvel essai sur erreur passagère."""

    def __init__(self, modele: str, client=None):
        if client is None:
            import voyageai

            client = voyageai.Client()  # lit VOYAGE_API_KEY dans l'environnement (.env)
        self.modele = modele
        self.client = client

    def __call__(
        self, question: str, textes: list[str], top_k: int | None = None
    ) -> list[tuple[int, float]]:
        if not textes:
            return []
        reponse = avec_reessais(
            lambda: self.client.rerank(question, textes, model=self.modele, top_k=top_k),
            f"reranking ({self.modele})",
        )
        return [(r.index, r.relevance_score) for r in reponse.results]


class Recuperateur:
    """Recherche vectorielle large, puis reranking, puis décision « pertinent ou non »."""

    def __init__(
        self,
        base: VectorStore,
        reranker: Reranker | None = None,
        k: int = 4,
        fetch_k: int = 20,
        seuil: float | None = None,
    ):
        if k > fetch_k:
            raise ValueError("k ne peut pas dépasser fetch_k")
        self.base = base
        self.reranker = reranker
        self.k = k
        self.fetch_k = fetch_k
        self.seuil = seuil

    def candidats(self, question: str, filtre: dict | None = None) -> list[Passage]:
        """Les fetch_k chunks les plus proches. `filtre` : métadonnées, ex. {"theme": "eudr"}."""
        if type(self.base).__name__ == "Chroma":
            # Chroma renvoie une distance cosinus : similarité = 1 - distance (entre -1 et 1)
            trouves = [
                (doc, 1 - distance)
                for doc, distance in self.base.similarity_search_with_score(
                    question, k=self.fetch_k, filter=filtre
                )
            ]
        else:  # Pinecone renvoie directement la similarité
            trouves = self.base.similarity_search_with_relevance_scores(
                question, k=self.fetch_k, filter=filtre
            )
        return [
            Passage(chunk=doc, score=score, similarite=score, rang_initial=rang)
            for rang, (doc, score) in enumerate(trouves, start=1)
        ]

    def reclasser(self, question: str, candidats: list[Passage], k: int | None) -> list[Passage]:
        """Ordonne les candidats avec le reranker (ou garde l'ordre vectoriel sans reranker)."""
        if self.reranker is None or not candidats:
            return candidats[:k] if k else list(candidats)
        ordre = self.reranker(question, [c.chunk.page_content for c in candidats], k)
        return [replace(candidats[i], score=score) for i, score in ordre]

    def recuperer(self, question: str, k: int | None = None, filtre: dict | None = None):
        """Les k passages les plus pertinents pour la question, avec leurs scores."""
        k = k or self.k
        candidats = self.candidats(question, filtre)
        return Resultat(question, self.reclasser(question, candidats, k), candidats, self.seuil)


def creer_recuperateur(
    settings: Settings | None = None,
    reranker: Reranker | None = None,
    sans_reranking: bool = False,
) -> Recuperateur:
    """Récupérateur configuré par settings.yaml : collection du réglage courant, reranker, seuil."""
    settings = settings or get_settings()
    r = settings.retrieval
    collection = nom_collection(
        settings, settings.chunking.chunk_size, settings.chunking.chunk_overlap
    )
    base = ouvrir_base(creer_embeddings(settings), collection, settings)
    if reranker is None and r.reranker and not sans_reranking:
        reranker = RerankerVoyage(r.reranker)
    # le seuil n'a de sens qu'avec le score pour lequel il a été mesuré
    seuil = r.seuil_score if reranker is not None else None
    return Recuperateur(base, reranker, k=r.k, fetch_k=r.fetch_k, seuil=seuil)
