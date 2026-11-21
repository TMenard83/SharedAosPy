"""Chargement de `data/json/faction_rules_fr.json` — vérbatim français des règles
de faction (Traits de Bataille / Formations / Traits Héroïques et Artefacts
de Pouvoir / Domaines de Sorts / Domaines de Manifestations) et des aptitudes
propres à chaque unité, transcrites à la main depuis un battletome (« BT »),
un faction pack (« FP », règles provisoires avant la sortie du battletome)
ou des règles de saison type Scourge of Aqshy (« Aqshy ») — cf. le skill
`faction-rules-fr`. Consulté uniquement en mode `fr`/`fr-extended`
(`pdf_builder.build_roster_pdf`) ; ignoré en `hybrid`/`en`.

Une 6e catégorie, `prayer_lores`, existe pour les rares factions à Prêtres
plutôt qu'à Sorciers (même forme que `spell_lores`) — absente des 5 listées
plus haut faute d'avoir encore été nécessaire (LRL/StD sont tous deux à
Sorciers), mais `get_faction_category_overrides` ne distingue pas les noms
de catégorie, elle est donc déjà utilisable telle quelle.

Chaque entrée est soit un **correctif** d'une aptitude Wahapedia existante
(`wahapedia_name` renseigné — nom anglais exact, sert de clé de
rapprochement ; `name`/`description` sont toujours remplacés, `points_type`/
`points` restent toujours ceux de Wahapedia, et `condition`/`ability_phase`
restent eux aussi ceux de Wahapedia *sauf* si la ligne les renseigne
explicitement — cas réservé à une mise à jour de règles qui change le
*timing* d'une aptitude et pas seulement son texte (ex. Nighthaunt, "DAMNED
VESSEL" passe de Réaction à Passif) : fournir alors `condition` (et, si
besoin, `ability_phase`) avec le même mini-vocabulaire anglais interne
qu'une addition nette, cf. `apply_fr_overrides`), soit une
**addition nette** (`wahapedia_name` absent ou sans correspondance — ex. une
aptitude Scourge of Aqshy réellement absente de Wahapedia — auquel cas
`condition`/`ability_phase` doivent être renseignés à la main, même
mini-vocabulaire anglais interne que `season_rules.json`, jamais affiché tel
quel). Une addition nette n'a de sens que pour `battle_traits`/`formations`/
`heroic_traits_artefacts`/`spell_lores`/aptitudes d'unité : pour
`manifestation_lores`, seul un correctif (avec `wahapedia_name`) l'est —
`pdf_builder.resolve_rules` résout d'abord les manifestations invocables
sur les noms Wahapedia d'origine, *avant* d'appliquer ces correctifs, donc
une addition nette n'aurait aucun warscroll de manifestation à rattacher.

Chaque entrée corrigée par une mise à jour de règles garde un historique
complet dans `provenance` (`bt_text`/`errata_patch`/`errata_source`) à des
fins d'audit/re-curation seulement — jamais lu ni rendu dans le PDF,
`description` porte déjà le texte français final.

`formations`/`spell_lores`/`manifestation_lores` portent un champ `scope`
(nom de la formation/du domaine, cf. `ParsedList.allegiance`/`.spell_lore`/
`.manifestation_lore`) : seules les entrées dont le `scope` correspond à
l'option choisie par la liste s'appliquent (`get_faction_category_overrides`
filtre dessus, même normalisation « tronquer à partir de "(" » que
`WahapediaLookup.find_faction_category`) ; `battle_traits`/
`heroic_traits_artefacts` n'ont pas de `scope` (toutes les entrées
s'appliquent, comme côté Wahapedia).

Une Armée de Renom (ex. « Legion of the First Prince ») a son propre jeu de
règles vérbatim, rangé à part sous `factions.<faction>.renown_armies.<nom
de l'armée de renom>` plutôt que mêlé à `rules` — mêmes 4 clés de catégorie
que `rules` (`battle_traits`/`heroic_traits_artefacts`/`spell_lores`/
`manifestation_lores`, jamais `formations`, aucune Armée de Renom n'en ayant
une propre) mais sans `scope` (une Armée de Renom n'a qu'un seul jeu de
règles par catégorie, pas plusieurs options à filtrer). Cette séparation
existe parce qu'une Armée de Renom peut porter une aptitude qui partage son
nom Wahapedia avec une aptitude de la faction de base (ex. LRL, "DEPICT
RUNE" existe à la fois côté faction de base — avec un champ Wahapedia
authentiquement corrompu, cf. `pdf_builder._ABILITY_TEXT_OVERRIDES` — et
côté armée de renom "Aelementiri Conclave", avec un texte différent et
intact) : les mélanger dans une seule liste `rules.battle_traits` ferait
`apply_fr_overrides` corriger la mauvaise moitié selon l'ordre de résolution.
Cf. `get_renown_army_overrides` et `pdf_builder.resolve_rules`
(`renown_army`).

Un Régiment de Renom natif d'une faction (couvert par un PDF officiel
propre, ex. `fre_01-04_..._regiments_of_renown_lumineth_realmlords...pdf`
pour LRL) a de même son propre jeu d'aptitudes vérbatim, rangé sous
`factions.<faction>.regiments_of_renown.<nom Wahapedia du régiment, ex.
"Sigil Convocation">.abilities` (même forme correctif/addition que
`units.<unité>.abilities` — pas de `formations`/`scope`, un Régiment de
Renom n'a qu'un seul jeu de règles). Cf. `get_regiment_of_renown_overrides`
et `pdf_builder.build_roster_pdf` (résolution de `parsed.regiments_of_renown`) :
un Régiment à un seul membre voit son aptitude patchée rejoindre directement
la carte de cette unité (comme pour une optimisation) ; un Régiment à
plusieurs membres rejoint le pool d'aptitudes fusionné (`rule_ability_pool`)
avec un badge d'origine « Régiment de Renom : <nom> » au lieu de l'annexe
anglaise Wahapedia."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from pathlib import Path

from ..render.cards import tag_ability_origin
from .wahapedia_lookup import AbilityEntry, normalize_name, sanitize_glyphs

DEFAULT_FACTION_RULES_FR_FILE = Path("data") / "json" / "faction_rules_fr.json"
#: même schéma, textes officiels anglais relevés dans l'app Warhammer Age of
#: Sigmar (mode `en-split-simple`, badge d'origine « GW App ») — priment sur
#: Wahapedia en cas de différence
DEFAULT_APP_RULES_EN_FILE = Path("data") / "json" / "app_rules_en.json"


@dataclass(frozen=True)
class FactionRulesFr:
    factions: dict = field(default_factory=dict)


def load_faction_rules_fr(path: str | Path = DEFAULT_FACTION_RULES_FR_FILE) -> FactionRulesFr:
    """Fichier absent ou faction non (encore) curée -> aucune entrée (pas un
    plantage), même filet de sécurité que `season_rules.load_season_rules`."""
    p = Path(path)
    if not p.exists():
        return FactionRulesFr()
    # même assainissement que les CSV Wahapedia : le texte de l'App contient
    # des tirets insécables (« FLESH‑EATER », U+2011) que Helvetica dessine
    # en carré noir
    data = json.loads(sanitize_glyphs(p.read_text(encoding="utf-8")))
    return FactionRulesFr(factions=data.get("factions", {}))


def get_faction_category_overrides(
    frf: FactionRulesFr, faction_name: str, category: str, scope: str | None = None,
) -> list[dict]:
    """`category` in {battle_traits, formations, heroic_traits_artefacts,
    spell_lores, manifestation_lores}. `scope` filtre sur le champ `scope`
    d'une entrée — nécessaire pour formations/spell_lores/manifestation_lores
    (n'inclure que l'option choisie par la liste) ; sans effet pour
    battle_traits/heroic_traits_artefacts (pas de `scope`, toutes les
    entrées s'appliquent, comme côté Wahapedia)."""
    rows = frf.factions.get(faction_name, {}).get("rules", {}).get(category, [])
    if scope is None:
        return rows
    target = _scope_key(scope)
    return [r for r in rows if _scope_key(r.get("scope") or "") == target]


def _scope_key(scope: str) -> str:
    """Clé de rapprochement d'un `scope` : sans suffixe « (N Points) », et
    lettres doublées réduites — l'App et Wahapedia écrivent « Blood
    Blesssings of Khorne » (3 s), le battletome « Blessings »."""
    return re.sub(r"(.)\1+", r"\1", ability_join_key(scope.split("(", 1)[0]))


def get_unit_ability_overrides(frf: FactionRulesFr, faction_name: str, *unit_names: str) -> list[dict]:
    """Aptitudes curées d'une unité, cherchées sous chacun de `unit_names` dans
    l'ordre (typiquement le nom tel qu'exporté par l'App, puis le nom du
    warscroll Wahapedia résolu). Rapprochement via `wahapedia_lookup.normalize_name`
    (apostrophes typographiques, « : » d'un préfixe saisonnier, casse,
    accents) : une clé curée sous « Scourge of Aqshy: X » répond aussi à
    « Scourge of Aqshy X », et inversement."""
    return _unit_entry(frf, faction_name, *unit_names).get("abilities", [])


def get_unit_display_overrides(frf: FactionRulesFr, faction_name: str, *unit_names: str) -> dict:
    """Traduction de l'affichage d'une unité, même recherche que
    `get_unit_ability_overrides` : `name_fr` (remplace le nom de la carte —
    manifestations, absentes de l'export de liste), `subtitle_fr` (nom
    français en petit sous le nom anglais — unités, que l'App exporte en
    anglais), `keywords_fr` (mots-clés en pied de carte) et `weapons`
    (`wahapedia_name` → `name`/`abilities` d'un profil d'arme). Chaque clé
    est optionnelle ; `{}` si rien n'est curé."""
    entry = _unit_entry(frf, faction_name, *unit_names)
    return {k: entry[k] for k in ("name_fr", "subtitle_fr", "keywords_fr", "weapons") if k in entry}


def _unit_entry(frf: FactionRulesFr, faction_name: str, *unit_names: str) -> dict:
    units = frf.factions.get(faction_name, {}).get("units", {})
    by_key = {normalize_name(k): v for k, v in units.items()}
    for unit_name in unit_names:
        entry = units.get(unit_name) or by_key.get(normalize_name(unit_name))
        if entry:
            return entry
    return {}


def get_regiment_of_renown_overrides(frf: FactionRulesFr, faction_name: str, regiment_wahapedia_name: str) -> list[dict]:
    """Comme `get_unit_ability_overrides`, pour les aptitudes propres d'un
    Régiment de Renom natif de cette faction (`factions.<faction>.
    regiments_of_renown.<nom Wahapedia du régiment, ex. "Sigil Convocation">`).
    `regiment_wahapedia_name` est `RegimentOfRenownData.name` — le nom
    Wahapedia, pas le nom tel que cité dans l'export de liste (souvent déjà
    en français) : même clé de rapprochement que `wahapedia_name` partout
    ailleurs dans ce module. Un Régiment de Renom partagé entre plusieurs
    factions (rare) n'a de correctif que sous sa faction d'origine — même
    convention que `WahapediaLookup.find_regiment_of_renown`, qui ne retient
    que la ligne à `legend` non vide."""
    return frf.factions.get(faction_name, {}).get("regiments_of_renown", {}).get(regiment_wahapedia_name, {}).get("abilities", [])


def get_renown_army_overrides(
    frf: FactionRulesFr, faction_name: str, renown_name: str, category: str,
) -> list[dict]:
    """Comme `get_faction_category_overrides`, mais pour les règles propres
    d'une Armée de Renom (`factions.<faction>.renown_armies.<renown_name>`,
    même 4 clés de catégorie que `rules` -- `battle_traits`/
    `heroic_traits_artefacts`/`spell_lores`/`manifestation_lores`). Rangée à
    part de `rules` plutôt que d'y être mêlée : une Armée de Renom a souvent
    une aptitude qui porte le même nom Wahapedia qu'une aptitude de la
    faction de base (ex. LRL, "DEPICT RUNE" existe à la fois côté faction de
    base et côté armée de renom "Aelementiri Conclave", avec un texte
    différent) -- sans cette séparation, `get_faction_category_overrides`
    renverrait les deux lignes pour un seul et même appel, faisant `apply_fr_overrides`
    corriger la mauvaise aptitude côté base ou en ajouter une orpheline côté
    armée de renom. Aucun filtre `scope` nécessaire : déjà scopé par
    `renown_name`, une Armée de Renom n'ayant qu'un seul jeu de règles par
    catégorie (contrairement à une Formation ou un Domaine de Sorts d'une
    faction normale, choisis parmi plusieurs options)."""
    return frf.factions.get(faction_name, {}).get("renown_armies", {}).get(renown_name, {}).get(category, [])


#: Pseudo-faction sous laquelle sont curés les domaines et manifestations
#: génériques (Wahapedia `faction_id == "EnS"`, nom "Endless Spells") —
#: partagés par toutes les factions, donc curés une seule fois.
GENERIC_LORES_FACTION = "Endless Spells"


def ability_join_key(name: str | None) -> str:
    """Clé de rapprochement `wahapedia_name` <-> nom d'aptitude Wahapedia :
    majuscules, espaces de bord retirés, et apostrophes typographiques
    (`’`/`‘`, systématiques dans les CSV Wahapedia — « BASH ’EM LADZ! ») ramenées
    à l'apostrophe droite qu'on tape naturellement en curant le JSON — sans
    quoi un correctif silencieusement non apparié devient une addition nette,
    et la carte affiche l'anglais *et* le français côte à côte."""
    return (name or "").replace("\u2019", "'").replace("\u2018", "'").strip().upper()


def apply_fr_overrides(entries: list[AbilityEntry], overrides: list[dict]) -> list[AbilityEntry]:
    """Applique `overrides` (lignes `data/json/faction_rules_fr.json`, cf. le
    docstring de module) à `entries` (pool déjà résolu via Wahapedia,
    éventuellement vide) : une entrée dont `wahapedia_name` correspond au nom
    d'une aptitude déjà présente la corrige sur place (nom + description,
    plus `condition`/`ability_phase` si la ligne les renseigne explicitement
    — cf. `condition`/`ability_phase` ci-dessous ; tout le reste de ses
    champs, dont `points_type`/`points`, reste celui de Wahapedia) ; une
    entrée sans correspondance rejoint le pool comme addition nette.

    `condition`/`ability_phase` sur une ligne de correctif (`wahapedia_name`
    renseigné) sont optionnels et réservés au cas où une mise à jour de
    règles change le *timing* d'une aptitude (ex. Réaction -> Passif) et pas
    seulement son texte — un correctif normal ne les porte pas et le
    `condition`/`ability_phase` Wahapedia d'origine reste inchangé, comme
    documenté plus haut. Quand `condition` est fourni, `is_reaction` est
    recalculé à partir de son contenu (`"reaction:"` en tête, comme le fait
    déjà `_ability_entry` côté CSV Wahapedia) plutôt que laissé à sa valeur
    d'origine, pour que le badge rendu (`render/pills._condition_pill`)
    corresponde au nouveau timing plutôt qu'à l'ancien."""
    if not overrides:
        return entries
    # Une charte Wahapedia peut porter deux aptitudes homonymes (ex. les deux
    # "Putrescent Piety" des Pesticrates Putrides Fléau d'Aqshy) ou une
    # aptitude sans nom (champ vide, ex. le "Stigmates de Guerre" de Festus) :
    # chaque ligne de correctif consomme donc, dans l'ordre, la prochaine
    # entrée de ce nom pas encore corrigée, et une clé `wahapedia_name`
    # présente mais vide ("") apparie le nom vide plutôt que de devenir une
    # addition nette (réservée aux lignes *sans* clé `wahapedia_name`).
    by_name: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        by_name.setdefault(ability_join_key(e.name), []).append(i)
    result = list(entries)
    for row in overrides:
        idx = None
        if "wahapedia_name" in row:
            queue = by_name.get(ability_join_key(row.get("wahapedia_name")))
            if queue and row.get("wahapedia_type"):
                # homonyme de catégorie différente (ex. BoK « FRENZIED
                # TASKMASTER » Trait Héroïque vs Mutation d'Airain) : ne
                # corriger que l'entrée Wahapedia de la catégorie visée
                typed = [i for i in queue if result[i].wahapedia_type == row["wahapedia_type"]]
                if typed:
                    idx = typed[0]
                    if len(queue) > 1:
                        queue.remove(idx)
            elif queue:
                idx = queue.pop(0) if len(queue) > 1 else queue[0]
        if idx is not None:
            changes = {"name": row["name"], "description": row["description"]}
            if "condition" in row:
                changes["condition"] = row["condition"]
                changes["is_reaction"] = row["condition"].strip().lower().startswith("reaction:")
            if "ability_phase" in row:
                changes["ability_phase"] = row["ability_phase"]
            patched = _dc_replace(result[idx], **changes)
        else:
            patched = AbilityEntry(
                name=row["name"],
                description=row["description"],
                legend="",
                condition=row.get("condition", ""),
                keywords=row.get("keywords", ""),
                ability_phase=row.get("ability_phase", ""),
                points_type=row.get("points_type", ""),
                points=row.get("points", ""),
            )
        origin = row.get("origin")
        if origin:
            patched = tag_ability_origin([patched], origin)[0]
        if idx is not None:
            result[idx] = patched
        else:
            result.append(patched)
    return result
