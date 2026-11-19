---
name: warscroll-index
description: Curation manuelle d'une nouvelle entrée (ou correction d'une entrée existante) dans data/json/warscroll_index.json, l'index reliant chaque nom d'unité canonique et chaque règle de faction/carte de tactique à sa page de PDF. Utiliser quand une faction, une unité ou une section de règles n'est pas trouvée par le skill roster-pdf, ou qu'un nouveau battletome est ajouté sous data/Battle tome/.
---

# Warscroll Index

Les PDF de battletome (`data/Battle tome/*.pdf`) et du Manuel du général
(`data/Manuel du général/*.pdf`) n'ont **aucun calque texte** (aplatis/
vectorisés par GW) : impossible de chercher un nom d'unité ou de règle dans
le texte du PDF. `data/json/warscroll_index.json` est donc curé à la main, une
fois par PDF (ils changent rarement), sur le même principe que
`data/json/army_rules.json`. La curation se fait en 3 temps : lister ce qui est
attendu, rendre les pages en image, les lire visuellement pour faire la
correspondance.

## Format de `data/json/warscroll_index.json`

```json
{
  "factions": {
    "<Nom de faction>": {
      "file": "<battletome>.pdf",
      "units": [
        {"name": "<Nom canonique DB>", "pages": [N]},
        {"name": "<Variante Scourge of Aqshy>", "pages": [N], "file": "<supplément>.pdf"}
      ],
      "rules": {
        "battle_traits": [N],
        "formations": [N, ...],
        "heroic_traits_artefacts": [N],
        "spell_lores": [{"name": "<Nom du domaine>", "pages": [N]}, ...],
        "manifestation_lores": [{"name": "<Nom du domaine>", "pages": [N]}, ...]
      }
    }
  },
  "battle_tactic_cards": {
    "dir": "Manuel du général",
    "file": "MdG26-27 Tactiques.pdf",
    "cards": [{"name": "<Nom anglais de la carte>", "pages": [N]}, ...]
  },
  "generic_manifestation_lores": {
    "dir": "Manuel du général",
    "file": "sorts persistants - manifestations.pdf",
    "lores": {
      "<Nom anglais du domaine>": {
        "domain_pages": [N, ...],
        "manifestations": [{"name": "<Nom anglais de la manifestation>", "pages": [N]}, ...]
      }
    }
  }
}
```
`battle_traits`/`formations`/`heroic_traits_artefacts` sont des sections
*uniques par faction*, toujours incluses si présentes. `spell_lores` et
`manifestation_lores` sont des listes car une faction en propose souvent
plusieurs (ex. Lumineth : « Lore of Hysh » et « Lore of the Awakened
Realms ») — `aospy roster pdf` ne sélectionne que celui cité par la liste.
Attention : un domaine de manifestations doit lister **la page de
convocation ET la charte de chacune de ses manifestations propres**, pas
juste la première — sans quoi le domaine choisi se retrouve dans le PDF sans
qu'on puisse effectivement invoquer/résoudre ce qu'il permet de convoquer.

Un `"file"` par entrée d'unité est **optionnel** et ne sert que quand cette
unité a sa charte dans un PDF différent du battletome principal de la
faction — le cas type est un petit supplément « Scourge of Aqshy » livré à
part (2-3 pages, une variante par charte) plutôt que fusionné dans le
battletome ; le champ est absent pour la variante de base, qui hérite du
`file` de la faction. `unit_pdf_path(index, faction, unit_name, ...)`
résout le bon fichier pour une unité donnée ; `battletome_path` reste le
raccourci pour le PDF principal de toute la faction (rendu de couverture,
règles générales, etc.), inchangé par cet ajout.

`battle_tactic_cards` est un objet **indépendant des factions**, pointant
vers `Manuel du général/MdG26-27 Tactiques.pdf` (universel, toutes armées).
`generic_manifestation_lores` est le même principe pour les domaines de
manifestations **partagés entre plusieurs factions** (ex. « Twilit
Sorceries ») : `domain_pages` est la page de convocation, `manifestations`
liste chaque manifestation invocable par ce domaine avec sa/ses page(s) de
charte — `find_generic_manifestation_lore(...).all_pages()` renvoie les deux
concaténés, puisque choisir le domaine donne accès à toutes ses
manifestations, pas à une seule.

## Étapes

1. **Lister les noms canoniques attendus** (unités) — utiliser la DB aospy
   plutôt que de deviner :
   ```bash
   uv run --with duckdb python3 -c "
   import duckdb
   con = duckdb.connect('data/aospy.duckdb', read_only=True)
   print(con.execute(\"select u.name from unit u join army a on u.army_id=a.id where a.name='<Nom de la faction>' order by u.name\").fetchall())
   "
   ```
   (`aospy unit list --army ...` segfaultait dans certains environnements de
   ce projet — préférer la requête SQL directe si besoin). Ces noms
   (anglais) sont ceux utilisés tels quels dans les exports de listes
   (`data/Proposition de listes/*.txt`) — utiliser ces noms comme clé
   `"name"`, pas le titre français de la page. Pour les domaines de sorts/
   manifestations et les cartes de tactique, le nom anglais exact vient
   directement des champs `Spell Lore -`/`Manifestation Lore -`/
   `Battle Tactic Cards:` des fichiers de liste concernés — ne pas deviner
   la traduction anglaise depuis le titre français de la page.

2. **Rendre les pages en images** (aucun outil système requis, `pymupdf`
   s'installe à la volée) :
   ```bash
   uv run --with pymupdf python3 - <<'EOF'
   import fitz
   doc = fitz.open("<chemin du PDF>")
   for i in range(doc.page_count):
       doc[i].get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).save(f"<scratchpad>/p{i:02d}.png")
   EOF
   ```
   Construire des planches contact (grille de vignettes numérotées, via PIL)
   pour repérer rapidement les pages candidates sans lire chaque image une à
   une (surtout utile pour un battletome de 20-40 pages ; les PDF du Manuel
   du général sont courts, quelques pages chacun, une lecture directe
   suffit). Relire en pleine résolution les pages ambiguës (ex. plusieurs
   profils au même titre : version à pied vs montée).

3. **Faire la correspondance et écrire le JSON.** Chaque page de battletome
   est en réalité une planche double (souvent 2 unités, gauche/droite) ;
   noter les index de page 0-indexés (ceux que `pypdf`/`fitz` utilisent).
   Attention aux unités « compagnon » gratuites listées séparément dans les
   exports de liste (ex. « Singri Brand », « The Oathsworn Kin ») : elles
   n'ont pas d'entrée dans la DB aospy (fusionnées dans leur unité parente à
   l'import BSData) mais apparaissent quand même comme unités à part entière
   dans le texte de liste — les indexer sous leur propre nom directement.
   Si un ou plusieurs noms DB de la faction portent le suffixe
   « (Scourge of Aqshy) » et ne se trouvent nulle part dans le battletome
   principal, chercher un petit PDF supplément dédié (nommé sur le modèle
   `fre_*_scourge_of_aqshy_<faction>-*.pdf`) — le rendre et l'indexer de la
   même façon, en ajoutant `"file"` à ces entrées d'unité (voir le format
   ci-dessus) plutôt qu'en les laissant absentes ou en pointant vers la page
   de la variante de base.

4. **Valider** :
   ```bash
   python3 -c "import json; json.load(open('data/json/warscroll_index.json'))"
   ```
   puis relancer `aospy roster pdf --list <liste concernée>` (ou le skill
   `roster-pdf`) et vérifier que les éléments visés ne sont plus signalés
   comme non trouvés (`units_unmatched`/`rules_unmatched`).

## Portée actuelle et limites connues

- Seuls les battletomes sous `data/Battle tome/Done/` (`DEFAULT_BATTLETOME_DIR`)
  sont dans le périmètre pour un rendu en **français**. `data/Battle tome/`
  contient aussi `A curer/` (battletomes pas encore indexés dans
  `warscroll_index.json`/`faction_rules_fr.json` — une fois la curation
  terminée pour une faction, déplacer son PDF vers `Done/`), `Draft/`
  (versions non retenues) et `Download GW/` (téléchargements bruts pas
  encore triés) — ces trois-là restent hors périmètre du code (`pdf_builder.py`
  ne lit que `Done/`).
- Les armées de renom (Legion of the First Prince, etc.), les Régiments de
  Renom (Regiments of Renown — concept différent, ex. « The Exiled One » /
  Skarbrand), et les domaines de sorts **génériques** partagés entre factions
  sont confirmés absents de tous les PDF fournis (battletomes + Manuel du
  général parcourus intégralement) — mais **pas besoin de les curer ici** :
  `tournament_kit/translation/wahapedia_lookup.py` les résout automatiquement en anglais
  depuis `data/wahapedia/*.csv` (déjà téléchargé par l'importeur Wahapedia,
  couvre toutes les factions). Rien à faire dans ce skill pour ces cas — s'ils
  apparaissent quand même en `rules_unmatched`/`units_unmatched`, c'est que
  Wahapedia lui-même ne les a pas non plus (vérifier avec `WahapediaLookup`
  avant de conclure à une vraie lacune).
- Les 6 domaines de manifestations **génériques** (Twilit Sorceries,
  Aetherwrought Machineries, Krondspine Incarnate, Forbidden Power, Primal
  Energy, Morbid Conjuration) sont couverts en **français** par
  `data/Manuel du général/sorts persistants - manifestations.pdf` (scan
  fourni par l'utilisateur) — indexés sous `generic_manifestation_lores` à la
  racine de `data/json/warscroll_index.json` (pas dans `factions/*/rules`, car
  partagés entre factions), avec pour chaque domaine `domain_pages` (la page
  de convocation) et `manifestations` (nom → pages de charte, une entrée par
  manifestation invocable). Pas besoin non plus de les curer ici sauf pour
  étendre ce fichier PDF lui-même s'il est un jour remplacé/complété — dans ce
  cas, suivre la même méthode (rendu + lecture visuelle) que pour un
  battletome, mais écrire sous `generic_manifestation_lores.lores` plutôt que
  sous une faction.
- Ce skill (curation manuelle de pages PDF) reste utile pour : étendre
  `data/json/warscroll_index.json` à un nouveau battletome complet sous
  `data/Battle tome/`, ou corriger une entrée existante qui pointe vers la
  mauvaise page.
