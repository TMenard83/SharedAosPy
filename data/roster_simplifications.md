# Mode `fr-split-simple` — règles de simplification

## Le but

`fr-split` répond à « qu'ai-je le droit de faire dans cette phase de ce tour ? ».
`fr-split-simple` part **exactement de `fr-split`** et l'allège pour qu'un joueur
relise **sa** liste en partie, vite : le but global est d'**optimiser le temps de lecture**. On ne simplifie pas « les règles » : on
simplifie **ce qu'il faut pour jouer cette liste**.

## Qui décide

- **Le joueur dicte** chaque simplification. Claude ne l'invente pas et ne
  l'applique pas de lui-même.
- **Claude vérifie** chaque affirmation contre la règle (battletome FR, errata,
  Wahapedia) et signale toute erreur ou condition oubliée.
- **Claude propose**, le joueur valide : rien n'est appliqué sans accord explicite.

## Les 18 principes

| # | Principe | En pratique |
|---|----------|-------------|
| 1 | **Rien de faux, rien d'important oublié** | Une synthèse raccourcit, elle ne change pas la règle : portée, fréquence, « 1 fois par tour (armée) » restent. |
| 2 | **Regrouper ce qui se joue ensemble** | Artefact + trait + aptitude qui servent le même geste → 1 aptitude de synthèse (ex. « Jet de Lancement »). |
| 3 | **Ce qui est résumé disparaît** | Les aptitudes d'origine sont retirées partout : on ne lit pas deux fois la même chose. |
| 4 | **Provenance discrète** | Sous une synthèse, une note petite et grise dit d'où elle vient. |
| 5 | **Badge SIMPLE** | Signale un texte compressé, pas le verbatim (en cas de litige, revenir à l'original). |
| 6 | **Ne pas redire l'évident** | Annonce d'un sort réduite à sa cible ; « un Sorcier lance », « 2D6 », « un seul sort persistant de chaque type » sont sous-entendus. Le placement (Effet) reste. |
| 7 | **Retirer ce qui ne peut plus servir dans cette liste** | Ex. rune déjà prise par l'Érudit des Sceaux, option non équipée, effet réservé à un profil absent de la liste, type d'unité amie absent (« Infanterie et Cavalerie » sans cavalerie → « Infanterie »). La génération **signale** les candidats (unité citée absente, mot-clé de type ami absent) ; la réécriture reste validée par le joueur. |
| 8 | **Chaque règle là où on la cherche** | Ce qui décrit le châssis d'une unité reste sur son warscroll ; ce qui se joue pendant le tour va sur les cartes de tour. |
| 9 | **Suivre le déroulé de la partie** | Ordre de jeu et de lecture (runes les plus utiles d'abord, sorts et manifestations sur la même page). |
| 10 | **Gagner de la place sans perdre en lisibilité** | Cartes de même hauteur côte à côte, une phase tient sur une page. |
| 11 | **Un bonus *Appliqué* est compté sur le profil** | Une aptitude réduite à *Appliqué* (vœu, bannière…) doit avoir son effet reporté sur la carte (`stats`, `weapons`). **Jamais sur une arme `Compagnon`** : elle ne profite d'aucun bonus, sauf si l'aptitude le dit explicitement. |
| 12 | **Plusieurs étapes ou effets → des puces** | Une puce par étape, dans l'ordre où on les joue (ex. Voué à Tzeentch : jetez 2D6 / choisissez un point / replacez). |
| 13 | **Résoudre les conditions génériques avec les unités de la liste** | « Les unités d'Assermentés de Gunnar », « une unité non Démon, non Unique, sans Bannière » → les noms des unités concernées. Vérifier d'abord qui remplit la condition (mots-clés Wahapedia). |
| 14 | **Nommer l'unité plutôt que « cette unité »** | Quand l'aptitude a quitté sa charte pour une carte de tour (« Abraxia », « Gunnar Brand »). Au cas par cas, jamais automatique : « cette unité » peut désigner la cible. |
| 15 | **Pas de ligne « Lanceur : … »** | La pastille d'unité et le badge Sorcier/Prêtre suffisent. Un lanceur sous condition (Nadja) reçoit le badge sur sa carte (`add_unit_keywords`), son texte précise la condition. |
| 16 | **Une aptitude impossible dans un tour quitte la carte de ce tour** | Ex. « si cette unité a chargé à ce tour » pour une unité qui ne charge qu'à votre tour (`condition_overrides`). **Toujours proposé et validé par le joueur au cas par cas.** Attention aux réactions qui font agir une unité au tour adverse : un tir en État d'Alerte déclenche « si cette unité a utilisé une aptitude de Tir » (Esprit du Vent, Sevireth). |
| 17 | **Notation compacte** | « Cible : / Effet : », « sur 3+ », « 1D6 > Contrôle », « −1 Attaque » ; « pour le restant du tour » reste. L'« Annonce : Choisissez comme cible X » de toute aptitude devient « Cible : X » (`compress_declare`, automatique). La phrase « Cible : … » est toujours suivie d'un retour à la ligne (`_break_after_target`, automatique). « Placer » (*set up*, terme de règle) est toujours en gras : placé(e)(s), placez, replacez… (`_bold_set_up`, automatique, aussi en `fr`/`fr-extended`/`fr-split`). |
| 18 | **Réduire ponctuellement la taille pour gagner une page** | Un bloc qui manque sa page de peu est réduit plutôt que de partir à la page suivante en laissant un grand blanc : une phase de carte de tour à qui il manque ≤ 5 % de hauteur est recomposée plus large puis ramenée à la largeur de la carte (même largeur que les autres phases, texte ~5 % plus petit, `warscroll_card._SHRINK_TO_FIT`) ; la page de garde (liste + légende) est réduite autant que nécessaire pour tenir en page 1. Jamais d'agrandissement, jamais de réduction au point de gêner la lecture. Automatique. |

## Où ça s'applique

**Uniquement en `fr-split-simple`.** On ne touche jamais aux fichiers partagés
avec `fr-split`/`fr-extended` (`faction_rules_fr.json`,
`generic_core_abilities.json`), sauf décision explicite du joueur pour une règle
commune déjà compressée partout (ex. « Placez le Champ de Bataille »).

Tout est dans `data/json/roster_simplifications.json`
(lu par `src/aospy/tournament_kit/translation/roster_simplifications.py`) :

- **`all_lists`** — vaut pour toutes les listes : une simplification de règle
  générale validée va ici.
  - `add_keywords` (badge SIMPLE…), `description_overrides` (texte compressé,
    ex. actions de base réécrites en « Utilisée par », « Éruption de Fureur »).
  - `compress_spell_declare` (Annonce d'un sort → « Cible : … », badge SIMPLE
    d'office), `compress_prayer_declare` (idem pour une prière : « un Prêtre
    récite, à 1D6 » sous-entendu ; un Prêtre précis, ex. de Régiment de Renom,
    reste écrit), `compress_declare` (toute autre aptitude : « Annonce :
    Choisissez comme cible(s) X » → « Cible(s) : X », badge SIMPLE d'office),
    `compress_tactic_conditions` (conditions des cartes de tactique).
  - `merge_into` (ex. « Musicien » fondu dans « Ralliement », seulement si la
    liste a un musicien).
  - Mise en page : `base_rules_last` (règles de base en fin de bandeau de
    phase, sauf Déploiement/Début de Round qui suivent le déroulé). Les
    warscrolls suivent toujours la liste et, en mode split, sont recopiés en
    tête de « Tour de l'adversaire » (règle générale, pas une option).
- **`lists.<nom du fichier de liste>`** — une seule liste :
  `units.<unité>.add_abilities` (synthèses, avec `note` de provenance),
  `units.<unité>.description_overrides` (texte limité à cette unité, ex. copie
  d'un vœu réduite à *Appliqué*), `units.<unité>.stats` (caractéristique
  affichée : `move`/`save`/`control`/`health`/`ward`/`points`),
  `units.<unité>.weapons` (caractéristiques d'une arme, par nom affiché,
  ex. Cursed Lance `attacks: 4` avec Voué à Khorne *Appliqué* — jamais une
  arme Compagnon), `units.<unité>.add_unit_keywords` (mot-clé d'unité ajouté à sa carte, ex.
  « WIZARD (1) » sur The Oathsworn Kin : badge Sorcier, le texte de Nadja
  précise la condition ; un « WIZARD (N) »/« PRIEST (N) » ajouté remplace le niveau existant, ex. Bâton des Marais *Appliqué* → « WIZARD (2) »),
  `remove_abilities` (noms EN Wahapedia **et** FR), `keep_on_warscroll`,
  `condition_overrides` (timing remplacé, ex. « Faim Dévorante » réservée à
  votre phase de charge : elle quitte « Tour adverse »),
  `description_overrides`, `warscroll_order`, `section_order` (sous-sections d'unité en tête d'un bandeau de phase, ex. `"hero": ["Lord Skreech Verminking"]`), `option_labels` (page de garde),
  `unit_aliases` (une entrée de la liste, repérée par ses options, traitée
  comme un Héros à part sous un autre nom : sa carte, ses pastilles).

## Version anglaise (`en-split-simple`)

Même mise en page, en anglais. Ses simplifications vivent dans la section
**`en`** du même fichier (`en.all_lists`, `en.lists.<nom>`, même forme) et
**reprennent celles du français** : une simplification validée pour une liste
est aussi écrite en anglais (noms Wahapedia anglais, texte anglais), sauf pour
une règle que le mode anglais affiche encore en français.

## Générer le PDF

```bash
aospy roster pdf --list "data/Proposition de listes/<équipe>/<liste>.txt" --mode fr-split-simple
```

Sortie : `scratch/output/roster/<équipe>/<liste>/<liste> (fr-split-simple).pdf`

Une seconde version, `<liste> (fr-split-simple-scenar).pdf`, ajoute à la fin les
12 cartes de scénario du Manuel du Général 2026-27
(`data/Manuel du général/MdG26-27 Scenarii.pdf`), 4 par page A4.
(`--mode en-split-simple` → `… (en-split-simple).pdf`).

La commande liste aussi, sous « À vérifier », les aptitudes qui citent une
unité absente de la liste et celles qui visent un type d'unité amie
(Infanterie, Cavalerie, Monstre, Machine de Guerre, Bête, Héros, Sorcier,
Prêtre) qu'aucune unité de la liste ne porte (`translation/absent_references.py`,
texte anglais Wahapedia). Candidats au principe 7, à proposer au joueur.
