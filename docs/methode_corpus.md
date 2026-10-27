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

Fichier CSV standard : séparé par des **virgules**, encodé en UTF-8. Il s'ouvre dans Data Wrangler (VS Code), pandas ou LibreOffice. Dans Excel : *Données > À partir d'un fichier texte/CSV*, délimiteur « virgule ». Un champ qui contient une virgule est entouré de guillemets.

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

Les 39 sources retenues pour l'instant sont **déjà inscrites dans le catalogue**, au statut `a_verifier`, avec leur lien et le nom de fichier prévu. Pour chacune : télécharger depuis `url_source`, enregistrer sous le nom indiqué dans `fichier`, vérifier, puis passer le statut à `valide`. Le vérificateur liste les fichiers encore à télécharger.

| Thème | Nombre | Principales sources |
| --- | --- | --- |
| maladies | 14 | Fiches techniques du CNRA (Swollen Shoot, pourriture brune, insectes nuisibles, pourridié, maladie rose…) |
| bonnes_pratiques | 12 | Manuel du planteur du Conseil du Café-Cacao (2015), manuels FIRCA, guide ICCO, guide CABI, fiches CNRA (culture, fertilisation, pépinière, greffage, séchage) |
| eudr | 6 | Règlements (UE) 2023/1115 et 2025/2650, Commission européenne, AGRINFO |
| certification | 4 | Rainforest Alliance, Preferred by Nature, World Cocoa Foundation (ARS 1000), ICI (SSRTE) |
| indicateurs | 3 | Green Means Go, Food Systems Dashboard, Digital Knowledge Hub (cahier §16) |

Fiches du CNRA : liste complète sur <https://cnra.ci/nos-fiches-techniques/?tax%5Bwpdmcategory%5D=cacao>. Le site ne donne pas de lien direct par fiche : on les télécharge depuis cette page.

### Écartés après examen (exemples de curation)

| Document | Motif |
| --- | --- |
| CNRA : échantillonnage de feuilles pour le diagnostic PCR du Swollen Shoot (2025) | Protocole de laboratoire, hors du public visé |
| CNRA : extraction de l'ADN génomique des feuilles de cacaoyer (2025) | Protocole de laboratoire, hors du public visé |
| CIRAD : séquences complètes du virus du Swollen Shoot | Article de génétique, trop spécialisé pour vulgariser |
| Rainforest Alliance, projet de norme v2 (2019) | Version de travail, remplacée par la norme définitive |
| Oro et al. (2020), biostimulant Banzaï et Swollen Shoot | Étude d'un produit commercial précis |
| Articles de presse sur le Swollen Shoot | Servent à repérer les sources officielles, pas à répondre |

### Manques à combler

- **Documents internes COCOACERT** : non publics, à demander au directeur de mémoire.
- **Norme ARS 1000** : texte de la norme (vérifier les conditions d'accès).
- **Indicateurs** : guides méthodologiques de Green Means Go et du Food Systems Dashboard ; c'est le thème le plus faible (3 sources).
- **Certification** : documents de Fairtrade et du Conseil du Café-Cacao sur la certification et la traçabilité.
- **Objectif** : 39 sources aujourd'hui, 100 visées. Compter un chapitre de manuel comme une fiche est possible, mais à décider avec ton encadrant et à signaler dans le mémoire.
