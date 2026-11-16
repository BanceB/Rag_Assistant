"""Questionnaire des testeurs (annexe 3 du mémoire), rempli dans l'application.

La page /questionnaire affiche ces questions ; les réponses sont enregistrées, sans nom ni
session, dans la table `questionnaires` du journal (data/app.db), et le tableau de bord de
/admin en tire les indicateurs du §11 du cahier des charges :
- pertinence perçue : part des testeurs qui donnent 4 ou 5 à la question 5 (cible 80 %) ;
- satisfaction : part des testeurs qui donnent 4 ou 5 à la question 14 (cible 80 %) ;
- nombre de testeurs : nombre de questionnaires reçus (cible 15).

Ce module ne dépend pas de Streamlit : la liste des questions et les calculs se testent seuls.
"""

from __future__ import annotations

from dataclasses import dataclass

ECHELLE = ("1", "2", "3", "4", "5")
ACCORD = "1 = pas du tout d'accord, 5 = tout à fait d'accord"
LONGUEUR_TEXTE = 1000  # caractères gardés au plus par réponse libre


@dataclass(frozen=True)
class Question:
    numero: int
    texte: str
    choix: tuple[str, ...] | None  # None : réponse libre
    obligatoire: bool = True
    legende: str | None = None  # explication de l'échelle 1 à 5

    @property
    def id(self) -> str:
        return f"q{self.numero}"

    @property
    def libelle(self) -> str:
        return f"{self.numero}. {self.texte}"


PARTICIPATION = Question(0, "Acceptez-vous de participer ?", ("Oui", "Non"))

QUESTIONS: tuple[Question, ...] = (
    Question(1, "Quel est votre statut ?", (
        "Agriculteur ou agricultrice", "Responsable de coopérative", "Technicien ou conseiller",
        "Étudiant ou chercheur", "Partenaire de la filière", "Autre")),
    Question(2, "Vous êtes… (facultatif)",
             ("Une femme", "Un homme", "Je préfère ne pas répondre"), obligatoire=False),
    Question(3, "Sur quel appareil avez-vous testé l'assistant ?",
             ("Téléphone", "Ordinateur", "Tablette")),
    Question(4, "Avez-vous déjà utilisé un assistant d'IA ?", ("Souvent", "Quelquefois", "Jamais")),
    Question(5, "Les réponses correspondaient à mes questions.", ECHELLE, legende=ACCORD),
    Question(6, "J'ai compris les réponses facilement.", ECHELLE, legende=ACCORD),
    Question(7, "Les réponses me sont utiles pour mon travail.", ECHELLE, legende=ACCORD),
    Question(8, "Je ferais confiance à ces réponses, après vérification avec un technicien si "
             "c'est important.", ECHELLE, legende=ACCORD),
    Question(9, "La longueur des réponses était…", ("Trop courte", "Bien", "Trop longue")),
    Question(10, "Le temps d'attente était…", ("Rapide", "Acceptable", "Trop long")),
    Question(11, "Les sources sous les réponses…", (
        "M'ont aidé", "Ne m'ont pas aidé", "Je ne les ai pas regardées")),
    Question(12, "Quand l'assistant ne savait pas, il l'a dit clairement.", (
        "Oui", "Non", "Cela ne m'est pas arrivé")),
    Question(13, "Avez-vous compris que l'assistant est une IA qui ne remplace pas un technicien ?",
             ("Oui", "Non")),
    Question(14, "Globalement, êtes-vous satisfait(e) de l'assistant ?", ECHELLE,
             legende="1 = pas du tout satisfait(e), 5 = très satisfait(e)"),
    Question(15, "Conseilleriez-vous l'assistant à un collègue ou à un planteur ?",
             ("Oui", "Peut-être", "Non")),
    Question(16, "Qu'avez-vous le plus apprécié ?", None, obligatoire=False),
    Question(17, "Que faut-il améliorer en priorité ?", None, obligatoire=False),
    Question(18, "Une question à laquelle l'assistant a mal répondu ?", None, obligatoire=False),
)  # fmt: skip

IDENTIFIANTS = [PARTICIPATION.id] + [q.id for q in QUESTIONS]


def manquantes(reponses: dict) -> list[int]:
    """Numéros des questions obligatoires sans réponse (ou avec une réponse hors des choix)."""
    manque = []
    for q in QUESTIONS:
        valeur = reponses.get(q.id)
        vide = valeur is None or (isinstance(valeur, str) and not valeur.strip())
        if (q.obligatoire and vide) or (q.choix and not vide and valeur not in q.choix):
            manque.append(q.numero)
    return manque


def _part(valeurs: list, retenues: set) -> float | None:
    valeurs = [v for v in valeurs if v is not None]
    if not valeurs:
        return None
    return round(100 * sum(1 for v in valeurs if v in retenues) / len(valeurs), 1)


def indicateurs(questionnaires: list[dict]) -> dict:
    """Indicateurs du tableau de bord, à partir des réponses enregistrées."""

    def colonne(qid: str) -> list:
        return [r.get(qid) for r in questionnaires]

    haut = {"4", "5"}
    return {
        "testeurs": len(questionnaires),
        "pertinence": _part(colonne("q5"), haut),
        "comprehension": _part(colonne("q6"), haut),
        "utilite": _part(colonne("q7"), haut),
        "confiance": _part(colonne("q8"), haut),
        "satisfaction": _part(colonne("q14"), haut),
        "recommandation": _part(colonne("q15"), {"Oui"}),
        "ia_comprise": _part(colonne("q13"), {"Oui"}),
    }
