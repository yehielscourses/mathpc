# mathpc

Annales du bac (spé mathématiques et spé physique-chimie), sessions 2021–2025.

- `formation-bac/` — guide HTML imprimable (révision express spé maths & PC, adapté profil cognitif), publié sur [GitHub Pages](https://yehielscourses.github.io/mathpc/)

- `math/` — sujets et corrigés (source : APMEP)
- `physique-chimie/` — sujets et corrigés (source : sujetdebac.fr)
- `data/json/` — annales extraites en JSON (1 fichier par sujet + index global)
- `scripts/extract_annales.py` — extraction PDF → JSON

## Extraction JSON

```bash
pip install -r scripts/requirements-extract.txt
python scripts/extract_annales.py
```

Produit :

- `data/json/math/<slug>.json` et `data/json/physique-chimie/<slug>.json` — une annale par fichier
- `data/json/annales_completes.json` — index regroupant toutes les annales

Chaque JSON contient les exercices, questions, sous-questions, blocs de contenu typés (`text`, `code`, `image`, `page_image`) avec positions (`bbox`, `page`), et les réponses du corrigé quand disponible.
