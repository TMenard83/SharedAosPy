---
name: faction-rules-fr
description: Curation manuelle d'une nouvelle faction (ou d'une entrée existante) dans data/json/faction_rules_fr.json, le vérbatim français des règles de faction et des aptitudes d'unité utilisé par les modes `fr`/`fr-extended` de `aospy roster pdf`. Utiliser quand l'utilisateur fournit un scan de battletome/faction pack (+ sa mise à jour de règles + ses règles de saison type Scourge of Aqshy) et demande de l'intégrer au mode français.
---

# Faction Rules FR

`data/json/faction_rules_fr.json` porte, par faction, le texte français **final**
(déjà corrigé par les erratas officiels) de chaque règle de faction et de
chaque aptitude d'unité, pour les modes `fr`/`fr-extended` de
`aospy roster pdf --mode ...` (`tournament_kit/sources/faction_rules_fr.py`,
`resolution/rules_resolution._fr_patch`). Contrairement à `warscroll_index.json`
(`warscroll-index` skill : curation par **numéro de page**, le PDF reste
copié tel quel), ici on transcrit le **texte intégral** — travail plus long,
étalé sur plusieurs sessions, une faction à la fois.

## Ce que l'utilisateur fournit

3 PDF par faction : le battletome/faction pack ("BT"/"FP"), sa mise à jour
de règles officielle ("MISES À JOUR DE RÈGLES" — le repère est écrit dans
l'en-tête de chaque page concernée), et les règles de saison en cours (ex.
Scourge of Aqshy — nouveaux warscrolls/aptitudes/optimisations, pas de
correctif à proprement parler). Pour les 2 premières factions (Slaves to
Darkness, Lumineth Realm-Lords), l'utilisateur a compilé les 3 en un seul
fichier (`data/Battle tome/AOSv4 - STD - BT - slave to darkness.pdf` /
`AOSv4 - LRL - BT - lumineth realm lord.pdf`) ; pour les suivantes, ils
arriveront en 3 PDF séparés — la procédure ci-dessous marche dans les deux
cas, seule la source des pages change.

**Ne jamais transcrire une aptitude qui n'a pas de contrepartie
identifiable** (soit un nom Wahapedia pour un correctif, soit un
`condition`/`ability_phase` clairs pour une addition) — en cas de doute sur
le classement d'une aptitude, demander à l'utilisateur plutôt que deviner :
c'est un document de règles de jeu, une erreur de transcription trompe le
joueur à la table.

## Format de `data/json/faction_rules_fr.json`

```json
{
  "factions": {
    "<Nom de faction, comme bsdata.KNOWN_ARMIES>": {
      "rules": {
        "battle_traits": [ {"...": "..."} ],
        "formations": [ {"scope": "<Nom de la formation>", "...": "..."} ],
        "heroic_traits_artefacts": [ {"...": "..."} ],
        "spell_lores": [ {"scope": "<Nom du domaine>", "...": "..."} ],
        "manifestation_lores": [ {"scope": "<Nom du domaine>", "...": "..."} ],
        "prayer_lores": [ {"scope": "<Nom du domaine>", "...": "..."} ]
      },
      "units": {
        "<Nom canonique Wahapedia de l'unité>": {
          "abilities": [ {"...": "..."} ]
        }
      }
    }
  }
}
```

Chaque entrée d'aptitude est soit un **correctif** soit une **addition** :

```json
// Correctif : renomme/retexte une aptitude Wahapedia existante. points_type/
// points restent TOUJOURS ceux de Wahapedia — ne pas les retranscrire, ils
// sont mécaniquement corrects côté Wahapedia. condition/ability_phase aussi,
// SAUF cas rare ci-dessous.
{
  "wahapedia_name": "RELENTLESS KILLERS",
  "name": "Tueurs Impitoyables",
  "description": "<b>...texte français final, HTML léger comme Wahapedia (<b>/<i>/<br/>)...</b>",
  "origin": "BT",
  "provenance": {
    "bt_text": "...texte du battletome AVANT correction, si une mise à jour de règles l'a touché...",
    "errata_patch": "...le correctif tel qu'écrit sur la page « MISES À JOUR DE RÈGLES », ou null si non touché...",
    "errata_source": "ex. « MdG26-27, mise à jour Slaves to Darkness, p.X » (optionnel)"
  }
}

// Correctif qui change aussi le TIMING (pas seulement le texte) : une mise
// à jour de règles peut transformer une Réaction en Passif (ou changer sa
// phase) sans toucher au reste. Ajouter alors condition (et/ou
// ability_phase) directement sur la ligne de correctif, même
// mini-vocabulaire anglais que pour une addition nette ci-dessous
// (apply_fr_overrides recalcule is_reaction à partir de ce condition -
// "reaction:" en tête ou non - pour que le badge rendu suive). N'ajouter
// ces clés QUE quand l'errata le justifie explicitement ; sinon les omettre
// pour laisser Wahapedia faire foi, comme dans l'exemple précédent.
{
  "wahapedia_name": "DAMNED VESSEL",
  "condition": "Passive",
  "name": "Vaisseau Damné",
  "description": "...",
  "origin": "BT",
  "provenance": {
    "bt_text": "...texte AVANT correction, en notant l'ancien timing (ex. « Timing d'origine : Réaction — ... »)...",
    "errata_patch": "...le correctif verbatim, en signalant le changement Réaction -> Passif...",
    "errata_source": "ex. « MdG26-27, mise à jour de règles Nighthaunt (août 2026), p.55 »"
  }
}

// Addition nette : aucune contrepartie Wahapedia (ex. contenu Scourge of
// Aqshy réellement absent de Wahapedia). condition/ability_phase deviennent
// alors OBLIGATOIRES, même mini-vocabulaire anglais que season_rules.json
// (jamais affiché tel quel) : "start of turn"/"hero phase"/"movement
// phase"/"shooting phase"/"charge phase"/"combat phase"/"end of turn"/
// "defensive reaction", ou vide -> bandeau "any".
{
  "name": "Rage Écarlate",
  "description": "...",
  "condition": "Passive",
  "ability_phase": "",
  "origin": "Aqshy",
  "provenance": {"bt_text": "...texte tel qu'imprimé...", "errata_patch": null, "errata_source": null}
}
```

`origin` ∈ `"BT"` / `"FP"` / `"Aqshy"` — devient le badge de provenance sur
la carte rendue (`tag_ability_origin`), en plus du badge de catégorie
existant ("Traits de Bataille"...).

**BT fourni en anglais** (cas Sylvaneth, 29/10/2026 — l'utilisateur a demandé
explicitement la traduction) : `origin: "BT (trad.)"` pour tout texte traduit
par nos soins, afin que le joueur voie à la table que ce n'est pas un texte
officiel. Avant de traduire, récupérer tout le vérbatim FR officiel
disponible (Fléau d'Aqshy, Mises à jour de Règles, Armées/Régiments de Renom,
Fer de Lance, Profils de Bataille pour les noms d'unités/formations/domaines)
et le garder tel quel (`origin` normal). Le texte Wahapedia de ces factions
peut être tronqué ou fusionné entre deux aptitudes : traduire depuis le scan
du BT dans ce cas.

**`scope`** (formations/domaines de sorts/prières/manifestations
uniquement) : le nom de la formation/du domaine exact (comme
`ParsedList.allegiance`/`.spell_lore`/`.manifestation_lore`/`.prayer_lore`)
— seules les entrées dont le `scope` correspond à ce que la liste choisit
s'appliquent. `battle_traits`/`heroic_traits_artefacts` n'ont pas de
`scope` (tout s'applique, comme côté Wahapedia).

**Cas particulier `manifestation_lores`** : une addition nette n'a pas de
sens ici (`resolution/rules_resolution.resolve_rules` résout d'abord le warscroll de
chaque manifestation invocable sur le nom Wahapedia d'origine, *avant*
d'appliquer les correctifs — une aptitude sans `wahapedia_name` matchant
n'aurait aucun warscroll à rattacher). N'utiliser que des correctifs pour
cette catégorie.

## Étapes

1. **Lister les noms Wahapedia attendus** (les clés `wahapedia_name`
   possibles) directement depuis les CSV déjà téléchargés — jamais deviner
   depuis le titre français d'une page :
   ```bash
   python3 -c "
   import csv
   with open('data/wahapedia/Faction_abilities.csv', encoding='utf-8-sig') as f:
       rows = list(csv.DictReader(f, delimiter='|'))
   fid = '<id de faction, ex. LRL/STD — cf. data/wahapedia/Factions.csv>'
   for r in rows:
       if r['faction_id'] == fid:
           print(r['type_name'], '|', r['subtype_name'], '|', r['name'])
   "
   ```
   et, pour les aptitudes d'unité, la même lecture sur
   `data/wahapedia/Warscrolls_abilities.csv` filtrée par `warscroll_id`
   (cf. `Warscrolls.csv`, colonne `id`, pour retrouver l'unité). Ces noms
   anglais sont la seule clé de rapprochement fiable (`wahapedia_name`).

2. **Rendre les 3 PDF en images** (même méthode que le skill
   `warscroll-index`, `pymupdf` installé à la volée) :
   ```bash
   uv run --with pymupdf python3 - <<'EOF'
   import fitz
   doc = fitz.open("<chemin du PDF>")
   for i in range(doc.page_count):
       doc[i].get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).save(f"<scratchpad>/p{i:02d}.png")
   EOF
   ```
   Construire des planches contact pour repérer vite les pages de règles de
   faction (Traits de Bataille/Formations/Traits Héroïques/Artefacts/
   Domaines de Sorts ou Manifestations), les pages « MISES À JOUR DE
   RÈGLES » (repérables à l'en-tête de page — souvent regroupées en fin de
   livret), et les pages de règles de saison (Scourge of Aqshy...). Relire
   en pleine résolution pour la transcription elle-même — un board de
   contact suffit pour repérer, pas pour transcrire mot à mot.

3. **Transcrire chaque aptitude touchée.** Pour une aptitude **non** touchée
   par une mise à jour de règles : `provenance.bt_text` = `description`
   (identiques), `errata_patch: null`. Pour une aptitude **touchée** :
   `provenance.bt_text` = le texte du battletome avant correction,
   `provenance.errata_patch` = le correctif tel qu'écrit sur la page
   « MISES À JOUR DE RÈGLES », `description` = le texte final tel qu'il se
   lit une fois le correctif appliqué (c'est ce texte-là, et lui seul, qui
   est rendu dans le PDF). Pour le contenu de saison (Aqshy...) : `origin:
   "Aqshy"`, addition nette si absent de Wahapedia (vérifié à l'étape 1),
   sinon correctif si Wahapedia porte déjà l'ability sous un autre texte.

4. **Écrire dans `data/json/faction_rules_fr.json`** (fichier plat, une seule
   fois pour tout le projet — ajouter la faction sous `factions.<nom>` sans
   toucher aux autres factions déjà curées).

5. **Vérifier et compléter les données des chartes** (demande de l'utilisateur, 2026-11-20). On a
   trois sources : Wahapedia (en base), BattleScribe (BSData) et les scans. Pendant que les pages sont
   rendues, comparer chaque charte de la faction à ce que la base contient : caractéristiques,
   mots-clés (**niveau de Sorcier/Prêtre** compris), profils d'arme, et textes d'aptitude tronqués
   (`aospy ability show <nom>` ; un verdict `a-revoir` est souvent un texte coupé).
   ```bash
   aospy import verify --faction "<nom>"   # Wahapedia × BSData (.cat déposés dans data/bsdata/)
   ```
   Pas de réseau dans le shell : demander à l'utilisateur de déposer « <Faction> - Library.cat »
   (github.com/BSData/age-of-sigmar-4th) dans `data/bsdata/`.
   **Hiérarchie** : mise à jour de règles la plus récente > scan du battletome > Wahapedia / BSData.
   Le scan seul peut être périmé (Skreech : Sorcier (1) au BT, Sorcier (2) d'après la mise à jour de
   règles FR p. 33, ce que Wahapedia avait déjà). Chaque écart tranché va dans
   `data/json/source_corrections.json` (`importers/corrections.py`), avec la page en `source`. Ces
   corrections l'emportent sur tout : unités réappliquées après chaque import, textes d'aptitude
   remplacés avant l'analyse (en anglais, l'extracteur lit l'anglais ; une traduction d'un scan FR le
   dit dans `source`). Ensuite : `aospy ability analyze`, `aospy chassis build`, `aospy encounter build`.

6. **Valider** :
   ```bash
   python3 -c "import json; json.load(open('data/json/faction_rules_fr.json'))"
   ```
   puis un run réel en mode `fr` sur une liste citant la faction concernée :
   ```bash
   aospy roster pdf --list "data/Proposition de listes/<liste>.txt" --mode fr
   ```
   et vérifier visuellement (ou via `pypdf.PdfReader(...).pages[i].extract_text()`)
   que le texte français attendu apparaît, avec le bon badge d'origine
   (BT/FP/Aqshy), et qu'aucune page de battletome n'est plus copiée pour ce
   qui vient d'être curé. Comparer aussi avec `--mode hybrid`/`--mode en`
   sur la même liste : ces deux modes ne doivent **jamais** changer (le
   vérbatim français n'est lu qu'en `fr`/`fr-extended`) — une régression là
   signale un bug de plomberie, pas un problème de transcription.

## Portée actuelle et limites connues

- `data/json/faction_rules_fr.json` est vide (`{"factions": {}}`) tant qu'aucune
  faction n'a été curée par ce skill — les modes `fr`/`fr-extended`
  dégradent alors silencieusement vers le même résultat que `en` (Wahapedia
  uniquement), sans erreur.
- Slaves to Darkness et Lumineth Realm-Lords sont les 2 premières factions
  prévues (PDF déjà compilés par l'utilisateur, cf. ci-dessus) — curation
  différée à une session dédiée où l'utilisateur fournit le contenu à
  transcrire, pas faite en même temps que la mise en place de ce skill.
- `data/json/generic_core_abilities.json` (mode `fr-extended`, transcription
  complète de `data/Manuel du général/MdG26-27 Aptitudes.pdf`) suit la même
  logique mais n'est **pas** dans le périmètre de ce skill — c'est un
  contenu générique partagé entre toutes les factions, pas une entrée
  `faction_rules_fr.json` ; même forme que `data/json/season_rules.json`
  (`name`/`description`/`condition`/`ability_phase`), sans `origin`/
  `provenance` (pas de correctif/addition à distinguer, tout vient du même
  PDF).
- `resolution/rules_resolution._ABILITY_TEXT_OVERRIDES` (le correctif ad hoc pour le champ
  Wahapedia corrompu de "DEPICT RUNE", LRL) reste actif dans tous les modes,
  indépendamment de ce fichier — une future entrée `faction_rules_fr.json`
  pour cette même aptitude (`wahapedia_name: "DEPICT RUNE"`) prendrait le
  relais en `fr`/`fr-extended` sans qu'il faille toucher à
  `_ABILITY_TEXT_OVERRIDES`, qui continuerait de s'appliquer en
  `hybrid`/`en`.

## Domaines et manifestations génériques (`Endless Spells`)

Les 6 domaines de manifestations partagés entre factions (Wahapedia
`faction_id == "EnS"` : Pouvoir Interdit, Charmes Morbides, Machineries
Éthériques, Énergie Primordiale, Sortilèges Crépusculaires, Incarnation de la
Krondéchine) sont curés **une seule fois** sous la pseudo-faction
`factions."Endless Spells"` (`faction_rules_fr.GENERIC_LORES_FACTION`) :
sorts de convocation dans `rules.manifestation_lores` (avec `scope` = nom
Wahapedia du domaine), aptitudes des chartes dans `units.<nom Wahapedia>`.
`rules_resolution._fr_patch` y retombe quand la faction de la liste n'a rien
pour ce `scope`, et `pdf_builder` cherche les aptitudes d'une manifestation
invoquée sous la faction de sa charte (`"Endless Spells"`) avant celle de la
liste. Source : `data/Manuel du général/sorts persistants - manifestations.pdf`
(`origin: "MdG"`).

## Sources officielles téléchargeables

Les PDF Fléau d'Aqshy, la dernière « Mises à jour de Règles », les
« Profils de Bataille » et les suppléments de tome de bataille sont
téléchargeables en français depuis Warhammer Community (API
`/api/search/downloads/`, `"language": "french"`, fichiers sur
`assets.warhammer-community.com`) ; ils ont une couche texte. Les ranger
dans `data/Battle tome/Download GW/`. Avant de demander un scan à
l'utilisateur, vérifier s'ils n'y sont pas déjà.

**À chaque nouvelle « Mises à jour de Règles »** : les errata sont cumulatifs,
repasser la nouvelle version sur *toutes* les factions déjà curées, pas
seulement celle en cours. `scripts/audit_rules_updates.py` (alias
`tm-aospy-audit-errata`, `--old-wahapedia <ancien export>` pour le diff
Wahapedia) trie les candidats ; il ne voit pas les remplacements d'aptitude
entière non guillemetés, donc relire quand même les pages de chaque faction.

Chartes Wahapedia à deux aptitudes homonymes ou à nom vide :
`apply_fr_overrides` consomme les homonymes dans l'ordre et apparie une clé
`wahapedia_name: ""` au nom vide — transcrire dans le même ordre que
Wahapedia.
