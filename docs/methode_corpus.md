# Méthode de constitution du corpus

> Statut : **en cours (étape 2)**. Objectif : au moins 100 documents ou fiches validés (§11 du cahier des charges).

## 1. Règles de rangement

- Un document = un fichier dans `data/corpus/<thème>/` **et** une ligne dans `data/corpus_catalogue.csv`.
- Thèmes : `maladies`, `eudr`, `certification`, `bonnes_pratiques`, `indicateurs`.
- Identifiant (`doc_id`) : préfixe du thème + numéro à trois chiffres. `MAL-001`, `EUDR-001`, `CERT-001`, `BPA-001`, `IND-001`.
- Nom de fichier : en minuscules, sans espace ni accent. Exemple : `eudr/reglement_ue_2023_1115.pdf`.
- Une page web gardée telle quelle : `fichier` vide, `url_source` renseignée, type `page_web`.
- Vérification après chaque ajout : `uv run python -m rag_assistant.catalogue`.

## 2. Le catalogue

Fichier CSV séparé par des **points-virgules**, encodé en UTF-8 : il s'ouvre directement dans Excel en français.

| Colonne | Contenu | Valeurs possibles |
| --- | --- | --- |
| `doc_id` | Identifiant unique | `EUDR-001`… |
| `titre` | Titre exact du document | texte |
| `fichier` | Chemin dans `data/corpus/` | `eudr/reglement_ue_2023_1115.pdf` |
| `url_source` | Adresse d'origine, utilisée pour citer | URL |
| `organisme` | Auteur ou éditeur | texte |
| `type` | Nature du document | `reglement`, `guide`, `fiche_technique`, `norme`, `article_scientifique`, `rapport`, `page_web` |
| `theme` | Dossier de rangement | les 5 thèmes |
| `date` | Date de publication ou de version | `AAAA` ou `AAAA-MM-JJ` |
| `langue` | Langue du document | `fr`, `en` |
| `licence` | Conditions de réutilisation | texte |
| `statut` | Avancement | `a_verifier`, `valide`, `exclu` |
| `valide_par` | Qui a validé | nom ou fonction |
| `remarques` | Toute précision utile | texte |

## 3. Critères d'inclusion

Un document entre dans le corpus s'il remplit **tous** ces critères :

1. **Source identifiée et fiable** : institution publique, organisme de recherche, organisme de normalisation ou de certification, organisation internationale, revue scientifique.
2. **Pertinent** : il répond à au moins une question de `eval/questions.jsonl`, ou couvre un thème du cahier des charges.
3. **À jour** : c'est la version en vigueur. Les versions anciennes ou les brouillons sont exclus.
4. **Lisible** : texte sélectionnable dans le PDF, ou OCR possible.
5. **Réutilisable** : la licence permet de le stocker et d'en citer des extraits dans un cadre de recherche.

## 4. Critères d'exclusion

- Articles de presse et blogs : ils servent à repérer les vraies sources, pas à répondre.
- Études centrées sur un produit commercial, quand elles n'apportent rien à la vulgarisation générale.
- Versions de travail (« draft ») et versions remplacées.
- Doublons : on garde la version la plus complète et la plus récente.

## 5. Point de vigilance : les dates de l'EUDR

Le règlement (UE) 2023/1115 a été **reporté et modifié plusieurs fois**, en dernier lieu par le règlement (UE) 2025/2650. Selon la Commission, les principales obligations s'appliquent à partir du 30 décembre 2026 pour les grands et moyens opérateurs, et à partir du 30 juin 2027 pour les micro et petites entreprises (selon les produits).

Conséquence pour le corpus : tout document qui annonce une application en décembre 2024 ou décembre 2025 est **obsolète sur ce point**. On le marque dans `remarques`, ou on l'exclut s'il n'apporte rien d'autre.

## 6. Sources candidates

Liste de départ, à télécharger, vérifier et cataloguer. Les liens ont été relevés le 26 octobre 2026.

| doc_id proposé | Document | Type | Lien |
| --- | --- | --- | --- |
| EUDR-001 | Règlement (UE) 2023/1115 (choisir la version FR sur EUR-Lex) | reglement | <https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX:32023R1115> |
| EUDR-002 | Règlement (UE) 2025/2650 modifiant le 2023/1115 | reglement | <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202502650> |
| EUDR-003 | Page EUDR de la Commission (documents d'orientation, FAQ) | page_web | <https://environment.ec.europa.eu/topics/forests/deforestation/regulation-deforestation-free-products_en> |
| EUDR-004 | AGRINFO : clarifications EUDR, mai 2026 (FR) | rapport | <https://agrinfo.eu/book-of-reports/eu-deforestation-regulation-eudr-clarifications-may-2026/translate/fr> |
| EUDR-005 | AGRINFO : EUDR, publications et ressources (FR) | page_web | <https://agrinfo.eu/book-of-reports/eu-deforestation-regulation-publications-and-resources/translate/fr> |
| EUDR-006 | Commission : report à décembre 2026 et autres évolutions | page_web | <https://trade.ec.europa.eu/access-to-markets/en/news/delay-until-december-2026-and-other-developments-implementation-eudr-regulation> |
| BPA-001 | FIRCA : Manuel technique de cacaoculture durable, version planteur | guide | <https://firca.ci/dl/manuel-technique-de-cacaoculture-durable-planteur> |
| BPA-002 | FIRCA : Manuel technique de cacaoculture durable, version technicien | guide | <https://firca.ci/dl/manuel-technique-de-cacaoculture-durable-technicien> |
| BPA-003 | ICCO : Guide du producteur de cacao (FR) | guide | <https://www.icco.org/wp-content/uploads/B27407-Cocoa-Grower-Guide-French-CFW-v7-interactive.pdf> |
| BPA-004 | UN-REDD : rapport sur l'agroforesterie en Côte d'Ivoire | rapport | <https://un-redd.org/sites/default/files/2021-10/rapport%20agroforesterie%20c%C3%B4te%20d%27ivoire.pdf> |
| MAL-001 | PlantVillage (Penn State) : fiche Cacao, maladies et ravageurs (FR) | page_web | <https://plantvillage.psu.edu/topics/cocoa-cacao-fr/infos> |
| CERT-001 | Rainforest Alliance : norme d'agriculture durable (page des documents) | norme | <https://rainforest-alliance.org/resource-item/rainforest-alliance-sustainable-agriculture-standard> |
| CERT-002 | Preferred by Nature : fiche sur la certification Rainforest Alliance des exploitations (FR) | fiche_technique | <https://preferredbynature.org/sites/default/files/RA-SAS-farm-certification-fact-sheet-Nov-2021-FRE.pdf> |
| CERT-003 | World Cocoa Foundation : ARS 1000, trois choses à savoir (EN) | page_web | <https://worldcocoafoundation.org/news-and-resources/article/africa-s-sustainable-cocoa-standard-3-things-to-know-about-ars-1000> |
| CERT-004 | ICI : manuel du système de suivi et de remédiation du travail des enfants (SSRTE), sept. 2025 (FR) | guide | <https://www.cocoainitiative.org/sites/default/files/resources/clmrs-manual_sept-2025_fr.pdf> |
| IND-001 | Green Means Go (cahier §16) | page_web | <https://greenmeansgo.ai/> |
| IND-002 | Food Systems Dashboard (cahier §16) | page_web | <https://www.foodsystemsdashboard.org/> |
| IND-003 | FCI4Africa Digital Knowledge Hub (cahier §16) | page_web | <https://fci4a.ubuntoo.com/> |

### Écartés après examen (exemples de curation)

| Document | Motif |
| --- | --- |
| Rainforest Alliance, projet de norme v2 (2019) | Version de travail, remplacée par la norme définitive |
| Oro et al. (2020), biostimulant Banzaï et Swollen Shoot, *Journal of Applied Biosciences* | Étude d'un produit commercial précis, peu utile pour vulgariser |
| Articles de presse sur le Swollen Shoot | Servent à repérer les sources officielles, pas à répondre |

### Manques à combler (avec l'encadrant)

- **Maladies** : fiches officielles du CNRA, de l'ANADER ou du Conseil du Café-Cacao sur le Swollen Shoot, la pourriture brune et les mirides.
- **Norme ARS 1000** : texte de la norme (vérifier les conditions d'accès auprès de l'organisme de normalisation).
- **Documents internes COCOACERT** : à demander au directeur de mémoire.
- **Indicateurs** : guides méthodologiques de Green Means Go et du Food Systems Dashboard.
