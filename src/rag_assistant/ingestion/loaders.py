"""Étape 3 : charger les documents du corpus en texte propre, avec leurs métadonnées.

Chaque page d'un PDF devient un `Document` LangChain :
    page_content = le texte nettoyé de la page
    metadata     = les colonnes utiles du catalogue + le numéro de page

Seuls les documents au statut « valide » dans le catalogue sont chargés.
Les pages web du catalogue sont lues à partir d'une copie PDF datée, rangée dans
data/corpus/ comme les autres fichiers (colonne `fichier` du catalogue).

Choix du lecteur PDF : PyMuPDF. Sur le corpus (41 PDF, 1 311 pages), il retrouve les
447 extraits cités en preuve dans eval/questions.jsonl en moins de 3 secondes ;
pypdf n'en retrouve que 426 en près de 30 secondes. Licence : AGPL-3.0, compatible
avec un projet académique dont le code est publié.

Vérifier le chargement :
    uv run python -m rag_assistant.ingestion.loaders
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from langchain_core.documents import Document

from rag_assistant.catalogue import EntreeCatalogue, lire_catalogue
from rag_assistant.config import get_settings

log = logging.getLogger(__name__)


PAGE_MIN_CARACTERES = 30  # en dessous : page de couverture, photo, page blanche
MARGE_HAUTE_BASSE = 0.12  # part de la hauteur de page où se trouvent en-têtes et pieds de page
SEUIL_MARGE = 0.5  # bloc répété dans la marge sur au moins 50 % des pages : en-tête ou pied
SEUIL_PARTOUT = 0.8  # bloc court répété sur au moins 80 % des pages, où qu'il soit
TITRES_A_GARDER = re.compile(r"(article|section|chapitre|annexe|partie)\b")
BRUIT = {"[no notes on this page]"}  # annotations d'export laissées dans certains PDF
# Ligne de sommaire : intitulé suivi de points de suite et d'un numéro de page
LIGNE_DE_SOMMAIRE = re.compile(r"(\.\s?){4,}\s*\d{1,3}\s*$|…{2,}\s*\d{1,3}\s*$")
# Intertitres repérés par la typographie (gras ou corps plus grand que le texte courant)
TITRE_LIGNES_MAX = 3
TITRE_ECART_TAILLE = 1.5  # points de plus que le texte courant
TITRE_REPETITIONS_MAX = 2  # au-delà : en-tête de tableau ou de colonne, pas un intertitre
POLICE_OCR = "GlyphLessFont"  # couche de texte ajoutée par OCR : pas de gras ni de taille fiable
MOTS_VIDES_FINAUX = {
    "de", "des", "du", "la", "le", "les", "l", "d", "et", "à", "en", "au", "aux", "un", "une",
    "par", "pour", "sur", "dans", "the", "of", "and", "to", "in", "for", "a", "an",
}  # fmt: skip
# Ligatures typographiques (« ﬁ », « ﬀ »…) remplacées par leurs lettres
LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)

# Métadonnées du catalogue recopiées sur chaque page (citer la source, filtrer par thème)
CHAMPS_CATALOGUE = (
    "doc_id",
    "titre",
    "organisme",
    "type",
    "theme",
    "date",
    "langue",
    "licence",
    "url_source",
    "fichier",
)


# ---------------------------------------------------------------- nettoyage du texte


def nettoyer_texte(texte: str) -> str:
    """Nettoie un bloc de texte extrait d'un PDF.

    - normalise l'Unicode (accents composés) et les espaces insécables ;
    - remplace les ligatures typographiques (« ﬁ », « ﬀ »…) par leurs lettres, sinon
      « afford » ou « vérifiée » ne seraient plus retrouvés par une recherche ;
    - recolle les mots coupés en fin de ligne (« béné-\\nfice » → « bénéfice ») ;
    - réunit les lignes d'un même bloc en une seule ligne ;
    - réduit les espaces multiples.
    """
    texte = unicodedata.normalize("NFC", texte).translate(LIGATURES)
    texte = texte.replace("­", "").replace(" ", " ")
    texte = re.sub(r"[\uf000-\uf0ff]", "•", texte)  # puces des polices Symbol / Wingdings
    texte = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=[a-zà-ÿ])", "", texte)
    texte = re.sub(r"\s*\n\s*", " ", texte)
    return re.sub(r"[ \t]+", " ", texte).strip()


def _cle(bloc: str) -> str:
    """Forme comparable d'un bloc : minuscules, chiffres neutralisés (« Page 3 de 9 » = « Page 7 de 9 »)."""
    return re.sub(r"\d+", "#", bloc.lower()).strip()


def blocs_repetes(pages: list[list[tuple[str, bool]]]) -> set[str]:
    """Repère les en-têtes et pieds de page : les blocs courts répétés sur la plupart des pages.

    `pages` : pour chaque page, la liste des blocs (texte, situé_dans_la_marge).
    Un bloc est retiré s'il revient dans la marge haute ou basse d'au moins la moitié des
    pages (les chiffres pouvant changer : « Page 3 de 9 »), ou s'il revient à l'identique,
    n'importe où, sur au moins 80 % des pages. Les intitulés d'articles, de sections ou
    d'annexes ne sont jamais retirés. Renvoie les blocs sous leur forme comparable.
    """
    n = len(pages)
    if n < 4:  # trop peu de pages pour distinguer un en-tête d'un contenu
        return set()
    en_marge = Counter(
        k for blocs in pages for k in {_cle(b) for b, m in blocs if m and len(b) <= 150}
    )
    partout = Counter(k for blocs in pages for k in {b.lower() for b, _ in blocs if len(b) <= 80})
    repetes = {k for k, v in en_marge.items() if v >= max(3, SEUIL_MARGE * n)}
    repetes |= {k for k, v in partout.items() if v >= SEUIL_PARTOUT * n}
    return {k for k in repetes if not TITRES_A_GARDER.match(k)}


def _assembler(blocs: list[str], titres: set[str] | None = None) -> str:
    """Assemble les blocs d'une page en paragraphes séparés par une ligne vide.

    Certains PDF découpent chaque ligne en un bloc : un bloc qui ne finit pas une phrase
    et qui est suivi d'un bloc commençant par une minuscule appartient au même paragraphe.
    Un intertitre (`titres`) reste toujours un paragraphe à part.
    """
    titres = titres or set()
    paragraphes: list[str] = []
    for bloc in blocs:
        if (
            paragraphes
            and paragraphes[-1] not in titres
            and bloc not in titres
            and not re.search(r"[.:;!?»)]$", paragraphes[-1])
            and re.match(r"[a-zà-ÿ(]", bloc)
        ):
            paragraphes[-1] += " " + bloc
        else:
            paragraphes.append(bloc)
    return "\n\n".join(paragraphes)


# ---------------------------------------------------------------- lecture des PDF


def est_titre_plausible(texte: str) -> bool:
    """Filtre les faux intertitres : légendes, crédits, en-têtes de tableau, fragments de ligne."""
    t = texte.lstrip("•◊▪-–— ").strip()
    mots = re.findall(r"\w+", t.lower())
    numerote = re.match(r"\d{1,2}(\.\d{1,2}){0,3}\.?\s+\S", t) is not None
    return (
        4 <= len(t) <= 120
        and bool(mots)
        and (t[0].isupper() or t[0].isdigit())
        and not t.endswith((".", ";", ",", ":"))
        and not LIGNE_DE_SOMMAIRE.search(t)
        and not re.search(r"(\.\s?){4,}|…{2,}", t)
        and not re.search(r"©|@|www\.|https?:|\btel\b|photo", t.lower())
        and sum(c.isdigit() for c in t) <= 6  # adresse, référence, ligne de tableau chiffrée
        and not re.fullmatch(r"(table des matières|sommaire|(table of )?contents)", t.lower())
        and not re.match(r"(source|figure|fig\.|tableau|table \d|photo|auteurs?)\b", t.lower())
        and mots[-1] not in MOTS_VIDES_FINAUX
        # tout en capitales : seulement s'il est numéroté ou annonce une partie
        and (
            any(c.islower() for c in t)
            or numerote
            or re.match(r"(PARTIE|CHAPITRE|ANNEXE|SECTION)\b", t) is not None
        )
    )


def _gras(span: dict) -> bool:
    police = span["font"].lower()
    return bool(span["flags"] & 16) or any(
        m in police for m in ("bold", "black", "heavy", "semibold", "demi")
    )


@dataclass
class _Bloc:
    texte: str
    dans_marge: bool
    titre: bool = False  # lignes de tête en gras ou en plus grand : intertitre candidat


def _blocs_de_page(contenu: dict, taille_courante: float) -> list[_Bloc]:
    """Blocs de texte d'une page (sortie de `get_text("dict")`) ; les lignes de tête
    typographiées deviennent un bloc à part."""
    hauteur = contenu["height"]
    blocs: list[_Bloc] = []
    for bloc in contenu["blocks"]:
        if bloc["type"] != 0:  # 1 = image
            continue
        x0, y0, x1, y1 = bloc["bbox"]
        marge = y0 < MARGE_HAUTE_BASSE * hauteur or y1 > (1 - MARGE_HAUTE_BASSE) * hauteur
        lignes = []
        for ligne in bloc["lines"]:
            spans = [s for s in ligne["spans"] if s["text"].strip()]
            if spans:
                typo = taille_courante > 0 and (
                    all(_gras(s) for s in spans)
                    or min(s["size"] for s in spans) >= taille_courante + TITRE_ECART_TAILLE
                )
                lignes.append(("".join(s["text"] for s in ligne["spans"]), typo))
        tete = 0
        while tete < len(lignes) and lignes[tete][1]:
            tete += 1
        if 0 < tete <= TITRE_LIGNES_MAX:
            titre = nettoyer_texte("\n".join(t for t, _ in lignes[:tete]))
            reste = nettoyer_texte("\n".join(t for t, _ in lignes[tete:]))
            if est_titre_plausible(titre):
                blocs.append(_Bloc(titre, marge, titre=True))
                if reste:
                    blocs.append(_Bloc(reste, marge))
                continue
        texte = nettoyer_texte("\n".join(t for t, _ in lignes))
        if texte:
            blocs.append(_Bloc(texte, marge))
    return blocs


def _taille_courante(contenus: list[dict]) -> tuple[float, str]:
    """Taille et police du texte courant : celles qui portent le plus de caractères."""
    tailles: Counter[float] = Counter()
    polices: Counter[str] = Counter()
    for contenu in contenus:
        for bloc in contenu["blocks"]:
            for ligne in bloc.get("lines", []):
                for s in ligne["spans"]:
                    n = len(s["text"].strip())
                    tailles[round(s["size"])] += n
                    polices[s["font"]] += n
    if not tailles:
        return 0.0, ""
    return float(tailles.most_common(1)[0][0]), polices.most_common(1)[0][0]


@dataclass
class PageLue:
    texte: str
    titres: list[str] | None  # None : typographie inexploitable (OCR), repli sur la numérotation


def lire_pdf(chemin: Path) -> list[PageLue]:
    """Lit chaque page du PDF (page 1 = élément 0) : texte nettoyé et intertitres repérés.

    En-têtes et pieds de page répétés, numéros de page et lignes de sommaire sont retirés.
    Un intertitre est une ligne de tête en gras ou en plus grand que le texte courant, qui
    passe `est_titre_plausible` et ne revient pas plus de deux fois dans le document ; les
    titres du signet (table des matières du PDF) comptent aussi.
    """
    with pymupdf.open(chemin) as pdf:
        contenus = [page.get_text("dict") for page in pdf]
        signets = {nettoyer_texte(t).lower() for _, t, _ in pdf.get_toc()}
    taille, police = _taille_courante(contenus)
    typographie = police != POLICE_OCR
    pages = [_blocs_de_page(c, taille if typographie else 0.0) for c in contenus]
    repetes = blocs_repetes([[(b.texte, b.dans_marge) for b in blocs] for blocs in pages])
    occurrences = Counter(b.texte.lower() for blocs in pages for b in blocs if b.titre)
    resultat = []
    for blocs in pages:
        gardes = [
            b
            for b in blocs
            if _cle(b.texte) not in repetes
            and b.texte.lower() not in repetes
            and b.texte not in BRUIT
            and not re.fullmatch(r"[\d\s\-–/|.]*", b.texte)  # numéro de page seul
            and not LIGNE_DE_SOMMAIRE.search(b.texte)
        ]
        titres = [
            b.texte
            for b in gardes
            if (b.titre and occurrences[b.texte.lower()] <= TITRE_REPETITIONS_MAX)
            or (b.texte.lower() in signets and est_titre_plausible(b.texte))
        ]
        resultat.append(
            PageLue(
                _assembler([b.texte for b in gardes], set(titres)), titres if typographie else None
            )
        )
    return resultat


def charger_pdf(chemin: Path, metadonnees: dict | None = None) -> list[Document]:
    """Un `Document` par page non vide, avec `page` (numérotation du PDF, à partir de 1)."""
    pages = lire_pdf(chemin)
    documents = []
    for numero, lue in enumerate(pages, start=1):
        texte = lue.texte
        if len(texte) < PAGE_MIN_CARACTERES:
            continue
        meta = {
            **(metadonnees or {}),
            "source": str(chemin),
            "page": numero,
            "nb_pages": len(pages),
        }
        if lue.titres is not None:
            meta["intertitres"] = "\n".join(lue.titres)  # lu par le découpage (étape 4)
        documents.append(Document(page_content=texte, metadata=meta))
    return documents


# ---------------------------------------------------------------- chargement du corpus


@dataclass
class Rapport:
    """Bilan d'un chargement, affiché à la fin et utile pour le journal."""

    documents: int = 0
    pages: int = 0
    pages_vides: int = 0
    caracteres: int = 0
    non_valides: list[str] = field(default_factory=list)
    sans_fichier: list[str] = field(default_factory=list)
    echecs: dict[str, str] = field(default_factory=dict)


def metadonnees_catalogue(entree: EntreeCatalogue) -> dict:
    return {champ: getattr(entree, champ) for champ in CHAMPS_CATALOGUE}


def charger_corpus(
    catalogue: Path | None = None, dossier_corpus: Path | None = None
) -> tuple[list[Document], Rapport]:
    """Charge tous les documents validés du catalogue. Ne s'arrête pas sur un fichier en échec."""
    reglages = get_settings()
    catalogue = catalogue or reglages.chemins.catalogue
    dossier_corpus = dossier_corpus or reglages.chemins.corpus
    rapport = Rapport()
    documents: list[Document] = []
    for entree in lire_catalogue(catalogue):
        if entree.statut != "valide":
            rapport.non_valides.append(entree.doc_id)
            continue
        if not entree.fichier:
            rapport.sans_fichier.append(entree.doc_id)
            continue
        chemin = dossier_corpus / entree.fichier
        try:
            if chemin.suffix.lower() != ".pdf":
                raise ValueError(f"format non pris en charge : {chemin.suffix}")
            pages = charger_pdf(chemin, metadonnees_catalogue(entree))
        except Exception as erreur:  # un fichier abîmé ne doit pas bloquer tout le corpus
            rapport.echecs[entree.doc_id] = f"{type(erreur).__name__} : {erreur}"
            log.error("%s : échec de lecture de %s (%s)", entree.doc_id, chemin, erreur)
            continue
        nb_pages = pages[0].metadata["nb_pages"] if pages else 0
        rapport.documents += 1
        rapport.pages += len(pages)
        rapport.pages_vides += nb_pages - len(pages)
        rapport.caracteres += sum(len(p.page_content) for p in pages)
        documents.extend(pages)
        log.info("%s : %d pages lues sur %d", entree.doc_id, len(pages), nb_pages)
    return documents, rapport


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    documents, r = charger_corpus()
    print(f"Documents chargés  : {r.documents}")
    print(f"Pages avec texte   : {r.pages}  (pages vides ignorées : {r.pages_vides})")
    print(f"Caractères         : {r.caracteres:,}".replace(",", " "))
    print(f"Non validés        : {len(r.non_valides)}  {r.non_valides}")
    print(f"Sans fichier (web) : {len(r.sans_fichier)}  {r.sans_fichier}")
    print(f"Échecs             : {len(r.echecs)}")
    for doc_id, erreur in r.echecs.items():
        print(f"   {doc_id} : {erreur}")
    # Vérification à l'œil : la première page utile de 3 documents de thèmes différents
    vus: set[str] = set()
    for doc in documents:
        theme = doc.metadata["theme"]
        if theme in vus or len(vus) == 3:
            continue
        vus.add(theme)
        print("\n" + "=" * 70)
        print(
            {
                k: doc.metadata[k]
                for k in ("doc_id", "titre", "theme", "page", "nb_pages", "licence")
            }
        )
        print("-" * 70)
        print(doc.page_content[:500])


if __name__ == "__main__":
    main()
