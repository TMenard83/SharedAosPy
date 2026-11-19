---
name: roster-pdf
description: Compile une liste d'armée (export texte brut de Warhammer Age of Sigmar: The App, dans data/Proposition de listes/) en un PDF de tournoi (liste mise en forme + une carte de règles de faction fusionnée + cartes de tactique de bataille + profils d'unité, tous en carte maison dessinée, complété en anglais via Wahapedia pour toute règle absente). Utiliser quand l'utilisateur dépose/désigne une liste et demande une fiche, un kit de tournoi, ou un PDF récapitulatif.
---

# Roster PDF

Délègue tout au CLI déjà implémenté : `src/aospy/tournament_kit/` (parser de
liste, résolution des règles via `data/wahapedia/*.csv`/`data/json/warscroll_index.json`,
cartes de tactique via `data/json/battle_tactic_cards.json`, assemblage PDF).
Aucune logique à réimplémenter ici.

## Contenu du PDF généré

Dans cet ordre : couverture (liste mise en forme, y compris les Regiments of
Renown) → **une carte de règles de faction fusionnée** (traits de bataille +
formation choisie + traits héroïques + artefacts de pouvoir + domaine de
sorts choisi + domaine de manifestations choisi, tous poolés ensemble et
triés par bandeau de phase plutôt qu'une carte par catégorie — deux traits
qui se déclenchent tous en phase des héros doivent apparaître groupés) →
**cartes de tactique de bataille citées** (verbatim français,
`tactic_cards.py`) → **cartes maison de profil d'unité** (une par unité
unique de la liste, y compris les membres de Regiments of Renown, plus la
charte complète de chaque manifestation invocable par le domaine choisi).
Hors modes split (`hybrid`/`en`/`fr`/`fr-extended`), les cartes de profil
d'unité viennent juste après la couverture, avant la carte de règles.

**Plus aucune section n'est une page de battletome/Manuel du général copiée
par défaut** — chacune est dessinée en carte compacte
(`tournament_kit/warscroll_card.py`) : profils d'unité et règles de faction
à partir de `data/wahapedia/*.csv` (aptitudes groupées par bandeau de phase
vertical, 7 phases du Manuel du général + une 8ᵉ verte pour les réactions
sans phase précise, badges en vraies pastilles pleines), cartes de tactique
à partir de `data/json/battle_tactic_cards.json` (transcription manuelle
verbatim). Profils d'unité et badges/mots-clés d'aptitude restent en
**anglais** (source Wahapedia, jamais traduite) ; règles de faction fusionnées
et cartes de tactique sont en **français** (source : PDF français transcrits/
scrapés). Une unité introuvable dans Wahapedia est un vrai `units_unmatched`.
Pour les sections de règles, un repli sur la page French existe encore *par
catégorie* si Wahapedia ne couvre pas telle faction/catégorie précisément —
contrairement aux unités, où il n'y en a plus du tout ; les cartes de
tactique, elles, n'ont aucun repli (pool fermé de 6 cartes, aucune autre
source). La Formation est filtrée sur celle réellement choisie par la liste
(`ParsedList.allegiance` — malgré son nom, c'est le nom de la formation, pas
une allégeance de grande alliance) ; Traits de Bataille/Héroïques/Artefacts
listent toutes les options de la faction, pas seulement celles effectivement
prises par tel ou tel héros (pas encore de rattachement carte-par-carte pour
ça).

**Un domaine de manifestations choisi entraîne toujours la charte (warscroll)
de chacune des manifestations qu'il permet d'invoquer**, pas seulement sa
page de règles de convocation — choisir le domaine donne accès à toutes ses
manifestations à la table, pas à une seule.

**Armée de Renom (ex. « Slaves to Darkness | Legion of the First Prince »)** :
ses propres traits de bataille / formations / traits héroïques / artefacts /
domaine de sorts *remplacent* ceux de la faction de base plutôt que s'y
ajouter — le code (`pdf_builder._AOR_REPLACES`) omet la carte/page de la
faction de base pour toute catégorie que l'armée de renom choisie remplace
effectivement, pour ne jamais montrer l'ancienne version à côté de la
nouvelle. Certaines catégories peuvent ne pas être remplacées (ex. une armée de renom sans
formation propre garde celle de la faction de base) — c'est déterminé au cas
par cas depuis les données, pas supposé.

**Regiment of Renown** : donne accès à des unités qui ne sont normalement pas
dans la faction (résolues comme n'importe quelle unité, recherche élargie à
toutes les factions) et peut en plus porter sa propre aptitude générique
propre au régiment (pas à une unité) — les deux sont déjà inclus
automatiquement, rien à faire de spécial pour une liste qui en contient un.
Quand le régiment n'a qu'un seul membre (ex. « The Exiled One » = Skarbrand
seul), son aptitude rejoint directement la carte de cette unité au lieu d'une
section séparée — un régiment à une unité et l'unité elle-même, c'est la
même chose pour le lecteur.

**Si une règle de faction (traits/formation/artefacts/domaine de sorts ou
manifestations/armée de renom/Regiment of Renown à plusieurs unités) n'est
dans aucun de ces PDF français**, une recherche de repli est faite dans
`data/wahapedia/*.csv` (déjà téléchargé par l'importeur Wahapedia) ; si
trouvé, elle est ajoutée en **anglais**, sur une annexe clairement séparée en
fin de document (« ANNEXE — CONTENU WAHAPEDIA (ANGLAIS) ») — jamais traduite,
jamais mélangée aux pages françaises, pour éviter tout contresens sur une
règle de jeu. Ce n'est que si ni les PDF ni Wahapedia n'ont l'information
qu'elle est signalée comme réellement non trouvée. Les profils d'unité, eux,
ne passent jamais par cette annexe : ils ont leur propre section de cartes
(voir plus haut), pas un repli parmi d'autres.

## Étapes

1. Identifier le fichier de liste visé (dans `data/Proposition de listes/`,
   ou un chemin donné par l'utilisateur).
2. Vérifier que l'extra `[roster]` est installé (`pip install -e ".[roster]"`
   si `aospy roster pdf` échoue avec un message d'extra manquant).
3. Lancer :
   ```bash
   aospy roster pdf --list "data/Proposition de listes/<équipe>/<fichier>.txt"
   ```
   (ajouter `--out <chemin.pdf>` si l'utilisateur veut un emplacement précis ;
   par défaut le PDF est écrit sous `scratch/output/roster/<équipe>/<liste>/<liste> (<mode>).pdf` — ne pas passer `--out`, le défaut fait le rangement).
4. Rapporter à l'utilisateur : le chemin du PDF généré, le nombre de profils
   et de sections de règles inclus, ce qui a été complété via Wahapedia
   (anglais, à signaler clairement), et les éventuels **non trouvés** (les
   trois listes affichées par la commande).
5. Si quelque chose est réellement non trouvé (ni PDF français, ni
   Wahapedia) :
   - Si la faction de la liste n'est pas du tout indexée dans
     `data/json/warscroll_index.json`, ou si son battletome n'est pas dans
     `data/Battle tome/` (racine, pas `Draft/`), l'expliquer à l'utilisateur
     et proposer d'invoquer le skill `warscroll-index` pour l'ajouter avant
     de relancer.
   - Si la faction est indexée mais qu'une unité/un domaine de sorts précis
     manque alors qu'il est probablement présent dans le battletome (nouvelle
     unité ajoutée depuis la dernière curation, faute de frappe dans la
     liste), proposer `warscroll-index` pour étendre l'index.
   - Si Wahapedia lui-même ne l'a pas (rare — `data/wahapedia/` couvre déjà
     énormément de contenu, y compris les Regiments of Renown et les
     domaines génériques), c'est probablement une vraie lacune de données ;
     l'expliquer à l'utilisateur plutôt que d'inventer un contournement.

## Limites connues

- Seules les 2 battletomes finalisés à la racine de `data/Battle tome/`
  (Lumineth Realm-lords, Slaves to Darkness) sont indexés pour le repli page
  français — pas `Battle tome/Draft/`. Ça ne concerne que le repli des
  sections de règles de faction non couvertes par Wahapedia : les profils
  d'unité ne dépendent plus de cet index du tout, ils viennent toujours de
  Wahapedia (carte maison), faction indexée ou pas.
- Les cartes de profil d'unité (et leurs mots-clés/badges d'aptitude) sont
  toujours en anglais (source Wahapedia) — pas de version française,
  contrairement à la carte de règles de faction fusionnée et aux cartes de
  tactique, qui restent en français.
- Une donnée manquante côté Wahapedia (pas un bug de notre parsing) peut
  laisser un `[texte manquant dans l'export Wahapedia — voir le Manuel du
  général/l'App]` visible dans le corps d'une aptitude — repéré une fois sur
  le trait de bataille LRL « Depict Rune » (5 identifiants de tooltip
  consécutifs, sans texte entre eux, que le CSV exporté ne résout jamais).
  Le signaler ainsi plutôt que le faire disparaître silencieusement est
  volontaire (`pdf_builder._clean_html`) — si un utilisateur signale un texte
  d'aptitude visiblement incomplet ailleurs, chercher ce même motif avant de
  soupçonner autre chose.
