# Faction Rules FR — portée, domaines génériques, sources

Annexe du skill `faction-rules-fr` (déplacée de SKILL.md, contenu inchangé).

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
