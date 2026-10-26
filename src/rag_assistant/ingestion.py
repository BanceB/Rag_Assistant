import asyncio  # Bibliothèque centrale pour la gestion de la boucle d'événements asynchrones
import os  # Interface avec le système d'exploitation (fichiers, variables d'environnement)

# import sys  # Paramètres et fonctions spécifiques à l'interpréteur Python (arguments, arrêts)
import ssl  # Protocoles de chiffrement et de sécurité TLS/SSL pour le réseau
from typing import List  # Outils d'annotation de types pour l'analyse statique du code

import certifi  # Gestion des certificats racine pour les connexions HTTPS sécurisées
from dotenv import (
    load_dotenv,  # Chargement des variables d'environnement à partir d'un fichier .env
)
from langchain_core.documents import (
    Document,  # Représentation des documents pour le traitement du langage naturel
)
from langchain_pinecone import (
    PineconeVectorStore,  # Gestion du stockage vectoriel avec Pinecone pour la recherche et la récupération d'informations
)
from langchain_tavily import (  # Gestion du crawling, de l'extraction et de la cartographie des données avec Tavily
    TavilyCrawl,
    TavilyExtract,
    TavilyMap,
)
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,  # Outils pour diviser le texte en segments plus petits pour l'analyse et le traitement
)
from langchain_voyageai import (
    VoyageAIEmbeddings,  # Gestion des embeddings pour le traitement du langage naturel avec VoyageAI
)

from rag_assistant.logger import (  # Fonctions de journalisation pour le suivi des événements et des erreurs
    Colors,
    log_error,
    log_header,
    log_info,
    log_success,
    log_warning,
)

load_dotenv()  # Chargement des variables d'environnement à partir du fichier .env


# configuration SSL pour les connexions sécurisées
ssl_context = ssl.create_default_context(
    cafile=certifi.where()
)  # Création d'un contexte SSL sécurisé avec les certificats racine de certifi
os.environ["SSL_CERT_FILE"] = (
    certifi.where()
)  # Définition de la variable d'environnement pour le fichier de certificats SSL
os.environ["REQUESTS_CA_BUNDLE"] = (
    certifi.where()
)  # Définition de la variable d'environnement pour le bundle de certificats CA pour les requêtes HTTP

# Initialisation des embeddings pour le traitement du langage naturel avec VoyageAI
embeddings = VoyageAIEmbeddings(
    model="voyage-4-lite",  # Modèle d'embeddings à utiliser
    # batch_size= 2,             # Réduit de 1000 à 50 pour éviter les saturations réseau (Rate Limits)
    show_progress_bar=True,  # Active la barre de progression
    truncation=True,  # Évite les crashs si un document dépasse la taille maximale autorisée
)


# Initialisation du stockage vectoriel avec Pinecone pour la recherche et la récupération d'informations
# chroma = Chroma(persist_directory=chromadb, embedding_function=embeddings )
vectorstore = PineconeVectorStore(
    embedding=embeddings,
    index_name=os.environ["INDEX_NAME"],  # string ici, pas un objet Index
)


# Initialisation des outils Tavily pour le crawling, l'extraction et la cartographie des données
tavily_extract = TavilyExtract()
tavily_map = TavilyMap(max_depth=5, max_breadth=20, max_pages=1000)
tavily_crawl = TavilyCrawl()


""" 
#  Indexation asynchrone des documents par lots
async def index_documents_async(documents: List[Document], batch_size: int = 10):
    ""Traite les documents par lots de manière asynchrone.""

    log_info(f"📚 Batching : regroupement des chunks en lots de {batch_size}",Colors.DARKCYAN)
    # Création des lots
    batches = [documents[i : i + batch_size] for i in range(0, len(documents), batch_size)]

    log_info(f"📦 Batching : {len(batches)} batches de {batch_size} lots ")



    # Traitement de tous les lots de manière concurrente
    async def add_batch(batch: List[Document], batch_num: int):
        try:
            await vectorstore.aadd_documents(batch)
            log_success(
                f"Embedding et Stockage : Lot {batch_num}/{len(batches)} ajouté avec succès : ({len(batch)} documents)"
            )
        except Exception as e:
            log_error(f"Embedding et Stockage : Échec de l'ajout du lot {batch_num} - {e}")
            return False
        return True


    # Exécution des lots en parallèle
    tasks = [add_batch(batch, i + 1) for i, batch in enumerate(batches)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Comptage des lots réussis
    successful = sum(1 for result in results if result is True)

    if successful == len(batches):
        log_success(
            f"Embedding et Stockage : Tous les lots ont été traités avec succès ! ({successful}/{len(batches)})"
        )
    else:
        log_warning(
            f"Embedding et Stockage : {successful}/{len(batches)} lots traités avec succès"
        )
"""


# Indexation asynchrone des documents par lots
async def index_documents_async(documents: List[Document], batch_size: int = 4):
    """Traite les documents par lots de manière séquentielle pour respecter les quotas."""

    log_info(f"📚 Batching : regroupement des chunks en lots de {batch_size}", Colors.DARKCYAN)
    # Création des lots
    batches = [documents[i : i + batch_size] for i in range(0, len(documents), batch_size)]

    log_info(f"📦 Batching : {len(batches)} batches de {batch_size} lots ")

    # Fonction unitaire de traitement d'un lot
    async def add_batch(batch: List[Document], batch_num: int):
        try:
            await vectorstore.aadd_documents(batch)
            log_success(
                f"Embedding et Stockage : Lot {batch_num}/{len(batches)} ajouté avec succès : ({len(batch)} documents)"
            )
            return True
        except Exception as e:
            log_error(f"Embedding et Stockage : Échec de l'ajout du lot {batch_num} - {e}")
            return False

    # MODIFICATION CRITIQUE : Traitement séquentiel avec pause (Adieu asyncio.gather)
    successful = 0
    for i, batch in enumerate(batches):
        batch_num = i + 1

        # Exécution du lot actuel
        result = await add_batch(batch, batch_num)
        if result:
            successful += 1

        # Pause obligatoire de 21 secondes entre les requêtes (sauf après le tout dernier lot)
        if batch_num < len(batches):
            log_info(
                f"⏳ Pause de 21s pour respecter les limites Voyage AI (3 RPM)... [{batch_num}/{len(batches)}]",
                Colors.DARKCYAN,
            )
            await asyncio.sleep(21)

    # Comptage final
    if successful == len(batches):
        log_success(
            f"Embedding et Stockage : Tous les lots ont été traités avec succès ! ({successful}/{len(batches)})"
        )
    else:
        log_warning(f"Embedding et Stockage : {successful}/{len(batches)} lots traités avec succès")


# Function principale asynchrone pour exécuter le pipeline d'ingestion et d'indexation des documents
async def main():
    "async main function to run the ingestion pipeline"

    # Crawling et extraction des documents depuis le site web https://docs.langchain.com/oss/python/langchain/overview
    log_header("PHASE D'EXTRACTION ET DE CHARGEMENT DE DOCUMENTS ")
    log_info(
        "TavilyCrawl: Parcours et extraction de documents depuis le site web https://docs.langchain.com/oss/python/langchain/overview",
        color=Colors.PURPLE,
    )

    response = tavily_crawl.invoke(
        {
            "url": "https://docs.langchain.com/oss/python/langchain/overview",
            "max_depth": 2,  # 5 Profondeur maximale de l'exploration du site web
            "extract_depth": "advanced",
        }
    )

    all_documents: List[Document] = [
        Document(page_content=result["raw_content"], metadata={"source": result["url"]})
        for result in response["results"]
        if result.get("raw_content") is not None  # Sécurité : ignore les valeurs nulles
    ]
    log_success(f"TavilyCrawl: {len(all_documents)} Documents parcourus et extraits avec succès.")

    # decoupage des documents en chunks(plusieurs petits morceaux de texte) pour l'indexation vectorielle
    log_header("PHASE DE CHUNKING DES DOCUMENTS ")
    log_info(
        f"Text splitter: Traitement de {len(all_documents)} documents avec un chunk_size de 2000 et un chunk_overlap de 200",
        color=Colors.YELLOW,
    )

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    splitted_docs = text_splitter.split_documents(all_documents)
    log_success(
        f"Text splitter: {len(splitted_docs)} Chunks générés avec succès pour {len(all_documents)} documents."
    )

    # Traitement des documents de manière asynchrone
    log_header("PHASE D'EMBEDDING ET DE STOCKAGE VECTORIEL")
    await index_documents_async(splitted_docs, batch_size=4)

    log_header("PIPELINE TERMINÉ")
    log_success("🎉 Le pipeline d'ingestion de la documentation s'est terminé avec succès !")
    log_info("📊 Résumé :", Colors.BOLD)
    # log_info(f"   • URL cartographiées : {len(site_map['results'])}")
    log_info(f"   • Documents extraits : {len(all_documents)}")
    log_info(f"   • Fragments créés : {len(splitted_docs)}")


if __name__ == "__main__":
    asyncio.run(main())
