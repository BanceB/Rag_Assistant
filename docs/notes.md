# Notes de révision

Notes personnelles déplacées depuis `src/rag_assistant/__init__.py` le 26 octobre 2026.

asyncio : est une bibliothèque Python intégrée utilisée pour écrire du code concurrent 
en utilisant la syntaxe async/ .await









on peut me poser des questions sur 

le type dembedding choisi ( contexwtuelle, sementique)
le type de chunking choisi (token, par taille, windows)
le type de vectore choisi



rate_limit ?


## Le chunking
Le chunking (en français : le découpage ou le fractionnement ) est l'action de découper 
un long document en plusieurs petits morceaux de texte indépendants, appelés des "chunks" 
(ou fragments).


Même si Voyage AI offre des millions de tokens gratuits, les comptes sans carte bancaire 
enregistrés sont bridés à un niveau extrêmement bas : 3 requêtes par minute (RPM) et 10 000 tokens 
par minute (TPM) . Avec votre premier lot (batch) de 50 morceaux, vous avez instantanément d
épassé le plafond des 10 000 tokens.
