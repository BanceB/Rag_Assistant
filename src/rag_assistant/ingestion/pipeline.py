"""Pipeline hors ligne : charger le corpus → découper → vectoriser et indexer.

Indexer tout le corpus avec le réglage de settings.yaml :
    uv run python -m rag_assistant.ingestion.pipeline

Autres usages :
    uv run python -m rag_assistant.ingestion.pipeline --taille 1000 --chevauchement 150
    uv run python -m rag_assistant.ingestion.pipeline --chercher "symptômes du swollen shoot"
    uv run python -m rag_assistant.ingestion.pipeline --supprimer MAL-001

Une relance ne revectorise que les chunks nouveaux ou modifiés : elle est rapide et gratuite
quand rien n'a changé.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from rag_assistant.config import get_settings, secrets_manquants
from rag_assistant.ingestion.chunking import decouper
from rag_assistant.ingestion.indexer import (
    creer_embeddings,
    indexer,
    nom_collection,
    ouvrir_base,
    supprimer_document,
)
from rag_assistant.ingestion.loaders import charger_corpus


def main(argv: list[str] | None = None) -> int:
    reglages = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--taille", type=int, default=reglages.chunking.chunk_size)
    parser.add_argument("--chevauchement", type=int, default=reglages.chunking.chunk_overlap)
    parser.add_argument("--chercher", metavar="QUESTION", help="recherche de test, sans réindexer")
    parser.add_argument(
        "--k", type=int, default=reglages.retrieval.k, help="nombre de passages renvoyés"
    )
    parser.add_argument(
        "--supprimer", metavar="DOC_ID", help="retire tous les chunks d'un document"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("rag_assistant").setLevel(logging.INFO)
    # Windows sans mode développeur : avertissement sans conséquence du cache Hugging Face
    # (le découpage en tokens de Voyage y est téléchargé une fois)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    manquants = secrets_manquants(reglages)
    if manquants:
        print(f"Clés absentes du fichier .env : {', '.join(manquants)}")
        return 1

    collection = nom_collection(reglages, args.taille, args.chevauchement)
    base = ouvrir_base(creer_embeddings(reglages), collection, reglages)
    print(f"Collection : {collection} ({reglages.vectorstore.provider})")

    if args.supprimer:
        print(f"{supprimer_document(base, args.supprimer)} chunks retirés pour {args.supprimer}")
        return 0

    if args.chercher:
        resultats = base.similarity_search_with_relevance_scores(args.chercher, k=args.k)
        for rang, (chunk, score) in enumerate(resultats, start=1):
            m = chunk.metadata
            print(f"\n{rang}. score {score:.3f} | {m['chunk_id']} | {m.get('section', '')}")
            print(chunk.page_content[:500])
        return 0

    debut = time.time()
    pages, rapport = charger_corpus()
    if rapport.echecs:
        print(f"Attention, documents illisibles : {list(rapport.echecs)}")
    chunks = decouper(pages, args.taille, args.chevauchement)
    print(f"{rapport.documents} documents, {len(pages)} pages, {len(chunks)} chunks")
    bilan = indexer(chunks, base)
    print(
        f"\nAjoutés : {bilan.ajoutes} | modifiés : {bilan.modifies} | inchangés : {bilan.inchanges}"
        f" | retirés : {bilan.supprimes}\nTotal dans la collection : {bilan.total}"
        f" | durée : {time.time() - debut:.0f} s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
