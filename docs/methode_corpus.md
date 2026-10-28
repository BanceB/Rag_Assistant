# Méthode de constitution du corpus

> Statut : **en cours (étape 2)** : 51 documents validés au 28 octobre 2026. Objectif : au moins 100 documents ou fiches validés (§11 du cahier des charges).

## 1. Règles de rangement

- Un document = un fichier dans `data/corpus/<thème>/` **et** une ligne dans `data/corpus_catalogue.csv`.
- Thèmes : `maladies`, `eudr`, `certification`, `bonnes_pratiques`, `indicateurs`.
- Identifiant (`doc_id`) : préfixe du thème + numéro à trois chiffres. `MAL-001`, `EUDR-001`, `CERT-001`, `BPA-001`, `IND-001`.
- Nom de fichier : en minuscules, sans espace ni accent. Exemple : `eudr/reglement_ue_2023_1115.pdf`.
- Une page web gardée telle quelle : `fichier` vide, `url_source` renseignée, type `page_web`.
- Vérification après chaque ajout : `uv run python -m rag_assistant.catalogue`.

## 2. Le catalogue

Fichier CSV standard : séparé par des **virgules**, encodé en UTF-8. Il s'ouvre dans Data Wrangler (VS Code), pandas ou LibreOffice. Dans Excel : *Données > À partir d'un fichier texte/CSV*, délimiteur « virgule ». Un champ qui contient une virgule est entouré de guillemets.

| Colonne          | Contenu                                                      | Valeurs possibles                                                                                                                                   |
| ---------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `doc_id`       | Identifiant unique                                           | `EUDR-001`…                                                                                                                                      |
| `titre`        | Titre exact du document                                      | texte                                                                                                                                               |
| `fichier`      | Chemin dans `data/corpus/`                                 | `eudr/reglement_ue_2023_1115.pdf`                                                                                                                 |
| `url_source`   | Adresse d'origine, utilisée pour citer                      | URL                                                                                                                                                 |
| `organisme`    | Auteur ou éditeur                                           | texte                                                                                                                                               |
| `type`         | Nature du document                                           | `reglement`, `guide`, `fiche_technique`, `norme`, `article_scientifique`, `rapport`, `page_web`                                       |
| `theme`        | Dossier de rangement                                         | les 5 thèmes                                                                                                                                       |
| `date`         | Date de publication ou de version                            | `AAAA` ou `AAAA-MM-JJ`                                                                                                                          |
| `langue`       | Langue du document                                           | `fr`, `en`                                                                                                                                      |
| `licence`      | Conditions de réutilisation                                 | texte                                                                                                                                               |
| `statut`       | Avancement                                                   | `a_verifier`, `valide`, `exclu`                                                                                                               |
| `valide_par`   | Qui a validé                                                | nom ou fonction                                                                                                                                     |
| `remarques`    | Toute précision utile                                       | texte                                                                                                                                               |
| `consultation` | Ce qui a été vérifié de la source avant téléchargement | `contenu_verifie` (contenu lu), `apercu` (page vue, contenu partiel ou illisible), `non_consulte` (lien repéré, pas encore ouvert), ou vide |

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

Le règlement (UE) 2023/1115 a été **reporté et modifié plusieurs fois**, en dernier lieu par le règlement (UE) 2025/2650 du 19 décembre 2025. Selon la Commission, les principales obligations s'appliquent à partir du 30 décembre 2026 pour les grands et moyens opérateurs, et à partir du 30 juin 2027 pour les micro et petites entreprises (le 30 décembre 2026 pour celles déjà couvertes par l'ancien règlement sur le bois).

Points vérifiés dans le texte du règlement 2023/1115 (version française sur EUR-Lex, le 27 octobre 2026) :

- **Article 2, point 13** : « zéro déforestation » vise des produits issus de terres n'ayant pas fait l'objet de déforestation après le **31 décembre 2020**.
- **Article 2, point 28** : la géolocalisation se fait par coordonnées (au moins six décimales) ; pour les parcelles de **plus de 4 hectares** (hors bovins), elle se fait à l'aide de **polygones**.

Conséquence pour le corpus : tout document qui annonce une application en décembre 2024 ou décembre 2025 est **obsolète sur ce point**. On le marque dans `remarques`, ou on l'exclut s'il n'apporte rien d'autre. Exemple : l'analyse de Trase (EUDR-007) reste utile pour ses chiffres de traçabilité, mais annonce une application au 30 décembre 2024.

## 6. État du corpus

Le catalogue compte **55 sources : 51 validées, 1 à vérifier, 3 exclues** (au 28 octobre 2026). Tous les PDF téléchargés contiennent du texte sélectionnable : aucun n'a besoin d'OCR.

### 6.1 Répartition par thème

| Thème | Sources | Validées | À vérifier | Exclues |
| --- | --- | --- | --- | --- |
| maladies | 15 | 15 | 0 | 0 |
| bonnes_pratiques | 15 | 14 | 0 | 1 |
| eudr | 10 | 9 | 0 | 1 |
| certification | 9 | 8 | 0 | 1 |
| indicateurs | 6 | 5 | 1 | 0 |
| **Total** | **55** | **51** | **1** | **3** |

Seul le Digital Knowledge Hub (IND-003) reste à vérifier : son contenu est inaccessible sans compte.

### 6.2 Couverture des sources demandées par le cahier des charges (§3.2)

| Source du cahier | Situation |
| --- | --- |
| Documents COCOACERT | Aucun : documents internes, demande envoyée au directeur de mémoire |
| Digital Knowledge Hub (FCI4Africa) | Inaccessible sans compte (IND-003) ; demande envoyée |
| Green Means Go | Site consulté (IND-001) : aucun contenu cacao, aucune méthodologie téléchargeable |
| Food Systems Dashboard | Profil Côte d'Ivoire (IND-005), FAQ (IND-006), article de méthode (IND-004) |
| Littérature réglementaire | Règlements 2023/1115 et 2025/2650 en français, document d'orientation de la Commission du 20 juillet 2026 (EUDR-001, 002, 010) |
| Littérature scientifique | 5 articles en accès libre (MAL-015, BPA-013 à 015, IND-004) |

Sources institutionnelles ajoutées en dehors de la liste du cahier, pour leur fiabilité et leur adaptation à la vulgarisation : CNRA, Conseil du Café-Cacao, FIRCA, ICCO, CABI, ICI, Fairtrade, ORAN (norme ARS 1000), NORC, Trase.

Fiches du CNRA : liste complète sur <https://cnra.ci/nos-fiches-techniques/?tax%5Bwpdmcategory%5D=cacao>.

### 6.3 Écartés après examen (exemples de curation)

| Document                                                                           | Motif                                                                   |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| CNRA : échantillonnage de feuilles pour le diagnostic PCR du Swollen Shoot (2025) | Protocole de laboratoire, hors du public visé                          |
| CNRA : extraction de l'ADN génomique des feuilles de cacaoyer (2025)              | Protocole de laboratoire, hors du public visé                          |
| CIRAD : séquences complètes du virus du Swollen Shoot                            | Article de génétique, trop spécialisé pour vulgariser               |
| Karkour et al. (2021), état de l'analyse de cycle de vie en Afrique               | Revue générale, sans lien direct avec le cacao ni avec Green Means Go |
| Rainforest Alliance, projet de norme v2 (2019)                                     | Version de travail, remplacée par la norme définitive                 |
| Oro et al. (2020), biostimulant Banzaï et Swollen Shoot                           | Étude d'un produit commercial précis                                  |
| EUDR-008 : fiche de la Commission pour les petits exploitants | Contenu de type brochure promotionnelle ; l'information utile est reprise dans le document d'orientation (EUDR-010) |
| BPA-001 : manuel FIRCA version planteur | Doublon du Manuel du planteur du Conseil du Café-Cacao (BPA-005) |
| CERT-001 : norme Rainforest Alliance | Aucun document de la norme trouvé sur la page |
| Standard Fairtrade pour le cacao, version française 1.5 (2017-2019) | Version dépassée : CERT-009 cite la version 2.1 du 27.09.2023 ; seule la version anglaise récente est à rechercher |
| Articles de presse sur le Swollen Shoot                                            | Servent à repérer les sources officielles, pas à répondre           |

### 6.4 Manques à combler

- **Documents COCOACERT et Digital Knowledge Hub** : en attente de réponse du directeur de mémoire. Sans réponse, le corpus reste constitué de sources publiques, et cette limite est expliquée dans le mémoire, avec les dates des demandes.
- **Objectif** : 51 documents validés pour 100 visés. Compter un chapitre de manuel comme une fiche est possible, mais à justifier et à signaler dans le mémoire.

## 7. Droits d'auteur et versionnement

- Les fichiers du corpus **ne sont pas versionnés dans Git** (voir `.gitignore`) : plusieurs sont protégés par le droit d'auteur, comme la norme ARS 1000 (« © ORAN 2021, tous droits réservés »). Les publier sur GitHub reviendrait à les redistribuer.
- On versionne le **catalogue**, qui suffit à reconstituer le corpus : titre, organisme, lien d'origine, licence.
- Les articles des *Cahiers Agricultures* sont sous licence CC BY-NC (usage non commercial) : compatible avec un mémoire, à revoir si le prototype devient un service commercial.
- Dans le prototype, les documents servent à produire des réponses courtes et sourcées ; l'agent ne doit pas restituer de longs extraits d'un document protégé.
