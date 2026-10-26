import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import ToolMessage
from langchain.tools import tool
from langchain_pinecone import PineconeVectorStore
from langchain_voyageai import VoyageAIEmbeddings

# Charger les variables d'environnement (clés API)
load_dotenv()

# Initialiser les embeddings (identique à l'ingestion)
embeddings = VoyageAIEmbeddings(model="voyage-4-lite")

# Initialiser le magasin de vecteurs (Vector Store)
vectorstore = PineconeVectorStore(index_name=os.environ["INDEX_NAME"], embedding=embeddings)

# Initialiser le modèle de chat
model = init_chat_model("claude-sonnet-5-5", model_provider="anthropic")


@tool(response_format="content_and_artifact")
def retrieve_context(query: str):
    """Récupérer la documentation pertinente pour aider à répondre aux questions des utilisateurs sur LangChain."""
    # Récupérer les 4 documents les plus similaires
    retrieved_docs = vectorstore.as_retriever().invoke(query, k=4)

    # Sérialiser les documents pour le modèle
    serialized = "\n\n".join(
        (f"Source: {doc.metadata.get('source', 'Inconnue')}\n\nContenu: {doc.page_content}")
        for doc in retrieved_docs
    )

    # Retourner à la fois le contenu sérialisé et les documents bruts
    return serialized, retrieved_docs


def run_llm(query: str) -> Dict[str, Any]:
    """
    Exécuter le pipeline RAG pour répondre à une question en utilisant la documentation récupérée.

    Arguments:
        query: La question de l'utilisateur

    Retourne:
        Un dictionnaire contenant:
            - answer: La réponse générée
            - context: La liste des documents récupérés
    """
    # Créer le prompt système de l'agent avec l'outil de récupération
    system_prompt = (
        "Vous êtes un assistant IA utile qui répond aux questions sur la documentation de LangChain. "
        "Vous avez accès à un outil qui récupère la documentation pertinente. "
        "Utilisez cet outil pour trouver des informations pertinentes avant de répondre aux questions. "
        "Citez toujours les sources que vous utilisez dans vos réponses. "
        "Si vous ne trouvez pas la réponse dans la documentation récupérée, dites-le explicitement."
    )

    # Créer l'agent
    agent = create_agent(model, tools=[retrieve_context], system_prompt=system_prompt)

    # Construire la liste des messages
    messages = [{"role": "user", "content": query}]

    # Invoquer l'agent
    response = agent.invoke({"messages": messages})

    # Extraire la réponse du dernier message de l'IA
    answer = response["messages"][-1].content

    # Extraire les documents de contexte à partir des artefacts de ToolMessage
    context_docs = []
    for message in response["messages"]:
        # Vérifier s'il s'agit d'un ToolMessage avec un artefact
        if isinstance(message, ToolMessage) and hasattr(message, "artifact"):
            # L'artefact doit contenir la liste des objets Document
            if isinstance(message.artifact, list):
                context_docs.extend(message.artifact)

    return {"answer": answer, "context": context_docs}


if __name__ == "__main__":
    # Exemple d'exécution avec une question en français
    result = run_llm(query="que sont les deep agents ?")
    print(result)
