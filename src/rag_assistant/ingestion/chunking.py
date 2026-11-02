"""Étape 4 : découper les pages du corpus en chunks, l'unité que l'on vectorise et que l'on retrouve.

Règles :
- on découpe page par page : un chunk ne chevauche jamais deux pages, ce qui permet de citer
  « document, p. 12 » sans ambiguïté ;
- chaque chunk porte une `section` : le premier intertitre de sa première moitié
  (« Article 9 », « 2.2.6 Semis »…), sinon la section en cours à son début.
  Les intertitres sont ceux que le chargement a repérés par la typographie (métadonnée
  `intertitres`) ; pour une page sans typographie exploitable (OCR), on se replie sur la
  numérotation (« 3.10. Qui est une PME ») ;
- dans les règlements, on coupe d'abord à chaque « Article N », pour qu'un chunk ne mélange
  pas deux articles ;
- chaque chunk commence par un en-tête contextuel (titre du document, organisme, section),
  pour être compris et retrouvé même lu seul ;
- chaque chunk reçoit un identifiant stable (`chunk_id`), utile pour ne pas indexer deux fois
  le même passage (étape 5).

Comparer trois réglages sur le corpus :
    uv run python -m rag_assistant.ingestion.chunking
"""

from __future__ import annotations

import json
import random
import re
import statistics
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_assistant.config import get_settings

# Réglages comparés (taille, chevauchement) en caractères ; le choix final se fait à l'étape 11
REGLAGES = [(500, 50), (1000, 150), (2000, 200)]
CHUNK_MIN_CARACTERES = 100  # en dessous, un chunk est signalé comme probablement trop pauvre
CARACTERES_PAR_TOKEN = 4  # ordre de grandeur pour le français et l'anglais

# Intertitre : « Article 9 », « ANNEXE I », « 2.2.6 Semis », « 6. LÉGALITÉ »…
# Pas de point final ni de deux-points (ce serait un alinéa numéroté), pas de points de suite
# (ce serait une ligne de sommaire).
INTERTITRE = re.compile(
    r"(Article \d+[a-z]?( bis)?|ANNEXE [IVX]+|Annexe [IVX\d]+|\d{1,2}(\.\d{1,2}){0,3}\.?\s+[A-ZÉÈÀ])"
)
ARTICLE = re.compile(r"\n\n(?=Article \d+[a-z]?(?: bis)?\n\n)")
ARTICLE_SEUL = re.compile(r"(Article \d+[a-z]?( bis)?|ANNEXE [IVX]+|Annexe [IVX\d]+)")


def est_intertitre(paragraphe: str) -> bool:
    p = paragraphe.strip()
    return (
        len(p) < 90
        and INTERTITRE.match(p) is not None
        and not p.endswith((".", ":", ";", ","))
        and not re.search(r"(\.\s?){3,}|…|\.\.\s*\d+$", p)  # ligne de sommaire (points de suite)
    )


def est_section(paragraphe: str, intertitres: set[str] | None) -> bool:
    """Le paragraphe ouvre-t-il une section ?

    `intertitres` : ceux que le chargement a repérés sur la page (gras ou plus grand), ou
    None si la page n'a pas de typographie exploitable : on se fie alors à la numérotation.
    Un intitulé d'article ou d'annexe compte toujours.
    """
    p = paragraphe.strip()
    if ARTICLE_SEUL.fullmatch(p):
        return True
    if intertitres is None:
        return est_intertitre(p)
    return p in intertitres


def fusionner_petits(
    bouts: list[str],
    minimum: int = CHUNK_MIN_CARACTERES,
    intertitres: set[str] | None = None,
) -> list[str]:
    """Rattache les morceaux trop courts (intertitre seul, légende, fin de phrase) à un voisin.

    Un morceau court est collé au suivant (un intertitre annonce ce qui suit) ; s'il est le
    dernier de la page, il est collé au précédent, sauf si c'est un intertitre (il annonce
    alors la page suivante et reste seul, la section étant de toute façon reportée).
    """
    resultat: list[str] = []
    en_attente = ""
    for bout in bouts:
        if en_attente:
            bout = f"{en_attente}\n\n{bout}"
            en_attente = ""
        if len(bout) < minimum:
            en_attente = bout
        else:
            resultat.append(bout)
    if en_attente:
        if resultat and not est_section(en_attente.split("\n\n")[-1], intertitres):
            resultat[-1] = f"{resultat[-1]}\n\n{en_attente}"
        else:
            resultat.append(en_attente)
    return resultat


TITRE_EN_TETE_MAX = 100  # caractères : l'en-tête doit rester court devant le passage
ORGANISME_EN_TETE_MAX = 40


def _abreger(texte: str, maximum: int) -> str:
    """Coupe au dernier mot entier avant `maximum` caractères, avec « … »."""
    if len(texte) <= maximum:
        return texte
    return texte[:maximum].rsplit(" ", 1)[0].rstrip(" ,;:—-(") + "…"


def en_tete(meta: dict) -> str:
    """En-tête contextuel ajouté au début de chaque chunk : titre (organisme, année) — section.

    Titre et organisme sont abrégés s'ils sont longs (« ORAN / ARSO (Organisation régionale
    africaine de normalisation), diffusé par… » → « ORAN / ARSO ») ; le catalogue garde les
    intitulés complets pour la citation.
    """
    organisme = meta.get("organisme", "")
    if len(organisme) > ORGANISME_EN_TETE_MAX:
        organisme = _abreger(organisme.split(" (")[0].split(", diffusé")[0], ORGANISME_EN_TETE_MAX)
    titre = _abreger(meta.get("titre", ""), TITRE_EN_TETE_MAX)
    source = ", ".join(x for x in (organisme, meta.get("date", "")[:4]) if x)
    ligne = f"{titre} ({source})" if source else titre
    if meta.get("section"):
        ligne += f" — {meta['section']}"
    return ligne


def decouper(
    pages: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    avec_en_tete: bool = True,
) -> list[Document]:
    """Découpe des pages (sorties de `charger_corpus`) en chunks enrichis de métadonnées.

    Les pages d'un même document doivent se suivre dans l'ordre, comme `charger_corpus` les
    renvoie : la section en cours passe d'une page à la suivante.
    """
    reglages = get_settings().chunking
    chunk_size = chunk_size or reglages.chunk_size
    chunk_overlap = reglages.chunk_overlap if chunk_overlap is None else chunk_overlap
    decoupeur = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        keep_separator="end",
    )
    chunks: list[Document] = []
    section_par_doc: dict[str, str] = {}
    for page in pages:
        meta = page.metadata
        doc_id = meta.get("doc_id", meta.get("source", ""))
        texte = page.page_content
        # intertitres repérés au chargement (texte sur plusieurs lignes : Chroma n'accepte
        # pas de liste) ; on ne les recopie pas dans les métadonnées du chunk
        meta = {k: v for k, v in meta.items() if k != "intertitres"}
        reperes = page.metadata.get("intertitres")
        intertitres_page = None if reperes is None else set(filter(None, reperes.split("\n")))
        # Règlements : un article commence toujours un nouveau morceau
        morceaux = ARTICLE.split(texte) if meta.get("type") == "reglement" else [texte]
        morceaux = [m for m in morceaux if m.strip()]
        # Les morceaux trop courts sont rattachés à un voisin, sans franchir un article
        bouts = [
            b
            for m in morceaux
            for b in fusionner_petits(decoupeur.split_text(m), intertitres=intertitres_page)
        ]
        for index, bout in enumerate(bouts):
            # section : le premier intertitre de la première moitié du chunk (le passage
            # en parle surtout), sinon celle en cours au début du chunk
            reperes_chunk, position = [], 0
            for paragraphe in bout.split("\n\n"):
                if est_section(paragraphe, intertitres_page):
                    reperes_chunk.append((position, paragraphe.strip()))
                position += len(paragraphe) + 2
            precoces = [titre for pos, titre in reperes_chunk if pos <= len(bout) / 2]
            section = precoces[0] if precoces else section_par_doc.get(doc_id, "")
            sections = [titre for _, titre in reperes_chunk]
            if sections:
                section_par_doc[doc_id] = sections[-1]
            meta_chunk = {
                **meta,
                "section": section,
                "chunk_index": index,
                "chunk_id": f"{doc_id}-p{meta.get('page', 0):03d}-c{index:02d}",
            }
            meta_chunk["en_tete"] = en_tete(meta_chunk) if avec_en_tete else ""
            contenu = f"{meta_chunk['en_tete']}\n\n{bout}" if avec_en_tete else bout
            chunks.append(Document(page_content=contenu, metadata=meta_chunk))
    return chunks


def texte_sans_en_tete(chunk: Document) -> str:
    """Le passage tel qu'il figure dans le document, sans l'en-tête contextuel."""
    en_tete_chunk = chunk.metadata.get("en_tete", "")
    if en_tete_chunk and chunk.page_content.startswith(en_tete_chunk):
        return chunk.page_content[len(en_tete_chunk) :].lstrip("\n")
    return chunk.page_content


# ---------------------------------------------------------------- mesures


@dataclass
class Statistiques:
    chunk_size: int
    chunk_overlap: int
    chunks: int
    taille_moyenne: int
    taille_min: int
    taille_max: int
    petits: int  # chunks de moins de CHUNK_MIN_CARACTERES
    tokens_estimes: int
    preuves_intactes: float  # part des extraits de preuve contenus en entier dans un chunk


def _norm(texte: str) -> str:
    texte = texte.replace("’", "'").replace(" ", " ")
    return re.sub(r"\s+", " ", texte).strip().lower()


def mesurer(
    pages: list[Document], chunk_size: int, chunk_overlap: int, preuves: list[dict]
) -> Statistiques:
    chunks = decouper(pages, chunk_size, chunk_overlap)
    tailles = [len(texte_sans_en_tete(c)) for c in chunks]
    par_page: dict[tuple, list[str]] = {}
    for c in chunks:
        cle = (c.metadata["doc_id"], c.metadata["page"])
        par_page.setdefault(cle, []).append(_norm(texte_sans_en_tete(c)))
    intactes = sum(
        any(_norm(p["extrait"]) in t for t in par_page.get((p["doc_id"], p["page"]), []))
        for p in preuves
    )
    return Statistiques(
        chunk_size,
        chunk_overlap,
        len(chunks),
        int(statistics.mean(tailles)),
        min(tailles),
        max(tailles),
        sum(t < CHUNK_MIN_CARACTERES for t in tailles),
        sum(len(c.page_content) for c in chunks) // CARACTERES_PAR_TOKEN,
        intactes / len(preuves) if preuves else 0.0,
    )


def main() -> None:
    from rag_assistant.ingestion.loaders import charger_corpus

    pages, _ = charger_corpus()
    with open(get_settings().chemins.questions_eval, encoding="utf-8") as f:
        preuves = [p for ligne in f if ligne.strip() for p in json.loads(ligne)["preuves"]]
    print(f"{len(pages)} pages, {len(preuves)} extraits de preuve\n")
    print("réglage    chunks  moyenne  min   max   <100  tokens    preuves intactes")
    for taille, chevauchement in REGLAGES:
        s = mesurer(pages, taille, chevauchement, preuves)
        print(
            f"{taille:>4}/{chevauchement:<4} {s.chunks:>7} {s.taille_moyenne:>8} {s.taille_min:>4}"
            f" {s.taille_max:>5} {s.petits:>5} {s.tokens_estimes:>8,}   {s.preuves_intactes:.1%}".replace(
                ",", " "
            )
        )
    chunks = decouper(pages)
    print(f"\nTrois chunks au hasard (réglage de settings.yaml, {len(chunks)} chunks) :")
    for c in random.Random(0).sample(chunks, 3):
        print("\n" + "=" * 70)
        print({k: c.metadata[k] for k in ("chunk_id", "section", "theme")})
        print("-" * 70)
        print(c.page_content[:700])


if __name__ == "__main__":
    main()
