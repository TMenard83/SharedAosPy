"""Résolution des règles de faction/Armée de Renom à inclure dans un roster
(`build_roster_pdf`, `pdf_builder.py`) : pour chaque catégorie (Traits de
Bataille, Formation, Traits Héroïques/Artefacts, domaine de Sorts/Prières/
Manifestations, règles d'Armée de Renom), décide quelle source gagne --
Wahapedia (EN) d'abord, repli page de battletome copiée (French) par
catégorie non couverte, puis (manifestations seulement) le domaine générique
français, puis Wahapedia en texte brut en tout dernier recours -- et, en
mode `fr`/`fr-extended`, applique les correctifs/additions vérbatim
français de `data/json/faction_rules_fr.json` (`_fr_patch`) sur le pool déjà
résolu par Wahapedia. Ne construit aucune page PDF elle-même (hors l'unique
appel à `render_tactic_card` pour les cartes de tactique, dont la largeur
reste un paramètre fourni par l'appelant) -- `pdf_builder.py` reste seul
responsable de l'assemblage et de la mise en page du roster fini."""

from __future__ import annotations

import re
from dataclasses import replace as _dc_replace

from ..list_parser import ParsedList
from ..modes import RosterMode, mode_spec
from ..render.cards import render_tactic_card, tag_ability_origin
from ..render.phases import set_ability_category
from ..sources.faction_rules_fr import (
    GENERIC_LORES_FACTION,
    FactionRulesFr,
    ability_join_key,
    apply_fr_overrides,
    get_faction_category_overrides,
    get_renown_army_overrides,
)
from ..sources.roster_simplifications import compress_tactic_conditions_enabled
from ..sources.tactic_cards import TacticCard, compress_tactic_conditions, find_tactic_card
from ..sources.wahapedia_lookup import AbilityEntry, WahapediaLookup, WarscrollData
from ..sources.warscroll_index import FactionIndex, WarscrollIndex, find_generic_manifestation_lore, find_lore_pages

#: Variantes du roster : cf. `tournament_kit/modes.py` (`RosterMode`,
#: `ModeSpec`). `RosterMode` reste importable d'ici.


#: Sections de règles de faction toujours incluses quand la faction est
#: indexée (label affiché -> attribut de `warscroll_index.FactionRules`).
_STATIC_RULE_SECTIONS = (
    ("Traits de Bataille", "battle_traits"),
    ("Formations de Bataille", "formations"),
    ("Traits Héroïques et Artefacts de Pouvoir", "heroic_traits_artefacts"),
)

#: Une Armée de Renom remplace tout ou partie de ces sections par ses propres
#: règles (`Faction_abilities.csv`, groupées par `subtype_name` — cf.
#: `WahapediaLookup.find_renown_army_rules`) : quand l'une de ces catégories
#: est présente pour l'armée de renom choisie, la page correspondante du
#: battletome de la faction *de base* ne s'applique plus et doit être omise
#: (sans quoi le PDF afficherait les deux versions, l'ancienne et la
#: remplaçante, l'une à côté de l'autre). `heroic_traits_artefacts` est un
#: attribut combiné côté battletome (une seule page pour les deux) ; côté
#: armée de renom, Heroic Traits et Artefacts of Power sont deux catégories
#: séparées — l'une ou l'autre suffit à invalider la page combinée.
_AOR_REPLACES: dict[str, frozenset[str]] = {
    "battle_traits": frozenset({"Battle Traits"}),
    "formations": frozenset({"Battle Formations"}),
    "heroic_traits_artefacts": frozenset({"Heroic Traits", "Artefacts of Power"}),
}

#: `WahapediaLookup.find_renown_army_rules` groupe les lignes d'une Armée de
#: Renom par `subtype_name` Wahapedia -- cette table les fait correspondre à
#: la clé de catégorie `data/json/faction_rules_fr.json` (`renown_armies.<nom>.*`,
#: cf. `faction_rules_fr.get_renown_army_overrides`) sous laquelle un
#: correctif vérbatim français est cherché en `fr`/`fr-extended`. Pas de
#: `"Battle Formations"` : constaté sur toutes les entrées du CSV, aucune
#: Armée de Renom n'a sa propre Formation (cf. le docstring de ce module).
#: `"Prayer Lore"` (rare, une seule Armée de Renom constatée à ce jour --
#: Blades of Khorne, "Gorechosen Champions") suit `faction_rules_fr.py`'s
#: docstring qui documente `prayer_lores` comme 6e clé de catégorie
#: utilisable telle quelle par `get_faction_category_overrides`/
#: `get_renown_army_overrides` sans distinction de nom -- sans cette entrée,
#: `_renown_army_pool` renverrait toujours `None` pour cette Armée de Renom
#: (catégorie non reconnue), la condamnant à l'annexe anglaise même une fois
#: entièrement curée.
_RENOWN_ARMY_CATEGORY: dict[str, str] = {
    "Battle Traits": "battle_traits",
    "Heroic Traits": "heroic_traits_artefacts",
    "Artefacts of Power": "heroic_traits_artefacts",
    "Spell Lore": "spell_lores",
    "Manifestation Lore": "manifestation_lores",
    "Prayer Lore": "prayer_lores",
    # Cities of Sigmar, "The Iron March" : 3 tableaux d'optimisations uniques
    # pour les Mécaforts (l'équivalent d'un Trait Héroïque/Artefact), rangés
    # sous `heroic_traits_artefacts` comme les autres optimisations.
    "Commanders of The Iron March": "heroic_traits_artefacts",
    "Engineers of The Iron March": "heroic_traits_artefacts",
    "Iron March Auxiliaries": "heroic_traits_artefacts",
}

#: Catégories `Faction_abilities.csv` rendues en carte maison plutôt qu'en
#: page de battletome copiée — (label affiché, `type_name` Wahapedia, clé
#: `_STATIC_RULE_SECTIONS`/`_AOR_REPLACES` correspondante). Toutes les lignes
#: de la catégorie sont incluses (aucune sélection à faire, contrairement à
#: la Formation — cf. `resolve_rules`, qui filtre celle-ci sur le nom choisi
#: par la liste). Traits Héroïques/Artefacts de Pouvoir n'y figurent plus :
#: ce sont des optimisations choisies une seule fois puis rattachées à une
#: seule unité (comme sur la table), pas des règles génériques pour toute la
#: liste — `build_roster_pdf` les résout désormais par unité via
#: `WahapediaLookup.find_unit_enhancement` et les rattache à la carte de
#: l'unité concernée (cf. plus bas) ; une optimisation non choisie
#: n'apparaît nulle part, tout comme une unité non choisie.
_WAHAPEDIA_RULE_CATEGORIES = (
    ("Traits de Bataille", "Battle Traits", "battle_traits"),
)


#: Slaves to Darkness only — a unit can carry a "PLEDGED TO <GOD>" keyword
#: fixed for the whole battle (not a mid-game choice, unlike the generic
#: "Voué à <Dieu>" Battle Traits above, which merely apply an effect to
#: whichever units already carry the keyword). Two ways a unit ends up with
#: it, both visible as a ` • ... ` option in the list export: (1) a Daemon
#: Prince is given a "Pledged to <God>" option at list-building (no matching
#: `Faction_abilities.csv` row — its own warscroll notes describe the
#: choice, so `WahapediaLookup.find_unit_enhancement` can't find it, hence
#: `_PLEDGE_OPTION_RE` matching the option text directly); (2) a unit is
#: given one of these 4 "Ensorcelled Banners" artefacts, each of which
#: grants the keyword outright (`_BANNER_PLEDGED_GOD`, keyed by the raw
#: Wahapedia name `find_unit_enhancement` returns *before* any French
#: patch). The user asked (2026-09-11) for the matching "Voué à <Dieu>" Battle
#: Trait to also be attached to that specific unit's own card as a
#: convenience, since it's a rare case, in addition to the general rule card
#: it already appears on once.
_PLEDGE_OPTION_RE = re.compile(r"pledged\s+to\s+(khorne|nurgle|tzeentch|slaanesh)", re.IGNORECASE)
_PLEDGE_WAHAPEDIA_NAME = {
    "KHORNE": "PLEDGED TO KHORNE",
    "NURGLE": "PLEDGED TO NURGLE",
    "TZEENTCH": "PLEDGED TO TZEENTCH",
    "SLAANESH": "PLEDGED TO SLAANESH",
}
_BANNER_PLEDGED_GOD = {
    "THE BANNER OF RAGE": "KHORNE",
    "THE BLASTED STANDARD": "TZEENTCH",
    "THE ERODING ICON": "NURGLE",
    "THE BANNER OF SCREAMING FLESH": "SLAANESH",
}


def find_pledge_battle_trait(
    wh: WahapediaLookup, frf: FactionRulesFr, faction: str, mode: str, god: str,
) -> AbilityEntry | None:
    """The "Voué à <Dieu>" Battle Trait entry for `god` (`"KHORNE"` etc.),
    French-patched like `_fr_patch` does for the merged rule card — mirrors
    that function's single-entry lookup idiom (cf. the `heroic_overrides`
    loop below) but for one named entry rather than a whole category."""
    battle_traits = wh.find_faction_category(faction, "Battle Traits")
    if not battle_traits:
        return None
    wahapedia_name = _PLEDGE_WAHAPEDIA_NAME[god]
    entry = next((e for e in battle_traits if ability_join_key(e.name) == wahapedia_name), None)
    if entry is None:
        return None
    if mode_spec(mode).curated_patch:
        overrides = get_faction_category_overrides(frf, faction, "battle_traits")
        matching = [o for o in overrides if ability_join_key(o.get("wahapedia_name")) == wahapedia_name]
        if matching:
            entry = apply_fr_overrides([entry], matching)[0]
    return entry


#: Repli verbatim français pour une aptitude dont le champ Wahapedia est
#: authentiquement corrompu (cf. le commentaire de `clean_html` sur la
#: suite d'ids de tooltip collés bout à bout) *et* dont le contenu manquant
#: est significatif — pas une simple retouche cosmétique. Clé : `(faction
#: exactement comme dans `bsdata.KNOWN_ARMIES`, nom d'aptitude en
#: MAJUSCULES comme Wahapedia). Contrairement au reste de la carte de règle
#: (Wahapedia-first, anglais), cette entrée précise est transcrite depuis le
#: battletome français (« TRAITS DE BATAILLE » / « INSCRIPTION DE RUNE ») —
#: `clean_html` continue par ailleurs de signaler tout *autre* trou de ce
#: type par son message `[texte manquant...]`, cette table ne fait que
#: réparer les entrées déjà identifiées à la main.
_ABILITY_TEXT_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("Lumineth Realm-lords", "DEPICT RUNE"): (
        "INSCRIPTION DE RUNE",
        "<b>Effet :</b> Choisissez 1 des runes suivantes à inscrire dans votre <b>verset guerrier</b>. "
        "L'effet et les effets conditionnels <b>améliorés</b> de cette rune durent pour le restant du round "
        "de bataille. Chaque rune reste dans votre <b>verset guerrier</b> pour le restant de la bataille ou "
        "jusqu'à ce qu'elle soit retirée ou remplacée par une autre aptitude."
        "<br/><br/>"
        "<b>Varinor, la Rune de la Force :</b> Choisissez comme cibles jusqu'à 2 unités de "
        "<b>SUZERAINS LUMINETHS</b> amies pour chaque exemplaire de cette rune inscrit dans votre verset "
        "guerrier. Ajoutez 1 aux jets de course et de charge pour chaque cible. De plus, les effets "
        "améliorés suivants s'appliquent :<br/>"
        "• Tant qu'Ydriliqi, la Rune du Fleuve est inscrite dans votre verset guerrier, ajoutez 1 aux jets "
        "de blessure pour les attaques de mêlée de chaque cible.<br/>"
        "• Tant qu'Oreali, la Rune du Vent est inscrite dans votre verset guerrier, chaque cible peut "
        "utiliser des aptitudes de Tir et/ou de Charge même si elle a utilisé une aptitude de Repli au "
        "même tour."
        "<br/><br/>"
        "<b>Alaithi, la Rune de la Montagne :</b> Choisissez comme cibles jusqu'à 2 unités de "
        "<b>SUZERAINS LUMINETHS</b> amies pour chaque exemplaire de cette rune inscrit dans votre verset "
        "guerrier. Chaque cible a une <b>Protection (5+)</b>. De plus, les effets améliorés suivants "
        "s'appliquent :<br/>"
        "• Tant que Varinor, la Rune de Force est inscrite dans votre verset guerrier, les armes de mêlée "
        "des cibles ont <b>Anti-charge (+1 Perf.)</b>.<br/>"
        "• Tant qu'Ydriliqi, la Rune du Fleuve est inscrite dans votre verset guerrier, soustrayez 1 aux "
        "jets de blessure pour les attaques des unités ennemies tant qu'elles sont en mêlée avec une ou "
        "plusieurs des cibles."
        "<br/><br/>"
        "<b>Ydriliqi, la Rune du Fleuve :</b> Choisissez comme cibles jusqu'à 2 unités de "
        "<b>SUZERAINS LUMINETHS</b> amies pour chaque exemplaire de cette rune inscrit dans votre verset "
        "guerrier. Soustrayez 2 aux jets de charge pour les unités ennemies tant qu'elles sont à 12\" "
        "d'une ou plusieurs de ces cibles. De plus, les effets améliorés suivants s'appliquent :<br/>"
        "• Tant qu'Alaithi, la Rune de la Montagne est inscrite dans votre verset guerrier, ignorez les "
        "modificateurs négatifs aux jets de touche et de blessure pour les attaques des cibles.<br/>"
        "• Si Oreali, la Rune du Vent est inscrite dans votre verset guerrier, chaque cible peut se "
        "déplacer immédiatement de 3\" maximum. Chaque cible peut passer à portée de mêlée des unités "
        "ennemies et peut finir ce mouvement en mêlée."
        "<br/><br/>"
        "<b>Oreali, la Rune du Vent :</b> Choisissez comme cibles jusqu'à 2 unités de "
        "<b>SUZERAINS LUMINETHS</b> amies pour chaque exemplaire de cette rune inscrit dans votre verset "
        "guerrier. Soustrayez 1 aux jets de touche pour les attaques des unités ennemies tant qu'elles "
        "sont en mêlée avec une ou plusieurs des cibles. De plus, les effets améliorés suivants "
        "s'appliquent :<br/>"
        "• Tant que Varinor, la Rune de Force est inscrite dans votre verset guerrier, ajoutez 4\" à la "
        "caractéristique de Mouvement de chaque cible.<br/>"
        "• Tant qu'Alaithi, la Rune de la Montagne est inscrite dans votre verset guerrier, ajoutez 5 au "
        "score de contrôle de chaque cible."
        "<br/><br/>"
        "<b>Thalari, la Rune du Zénith :</b> Ajoutez 2 aux jets de lancement pour les unités de "
        "<b>SUZERAINS LUMINETHS</b> amies. De plus, si vous avez au moins 4 runes uniques inscrites dans "
        "votre verset guerrier, ajoutez 4\" à la caractéristique de Mouvement des unités de "
        "<b>SUZERAINS LUMINETHS</b> amies et les attaques de ces unités causent des touches critiques sur "
        "les jets non modifiés de 5+."
        "<br/><br/>"
        "<b>Note des Concepteurs :</b> <i>Nous recommandons de noter sur un papier les runes inscrites "
        "lors de chaque round de bataille pour garder la trace des runes inscrites actuellement dans "
        "votre verset guerrier. N'hésitez pas à les noter par type (Force, Fleuve, etc.), par initiale "
        "(chaque rune a une initiale différente) ou, si vous êtes particulièrement audacieux, vous pouvez "
        "essayer votre main à la calligraphie aelfique et apprendre à tracer chaque rune !</i>",
    ),
}


def _apply_ability_text_overrides(entries: list[AbilityEntry], faction: str) -> list[AbilityEntry]:
    """Substitue le texte français transcrit à la main (`_ABILITY_TEXT_OVERRIDES`)
    au champ Wahapedia d'origine (anglais, tronqué par la corruption des ids
    de tooltip) pour les quelques aptitudes déjà identifiées — le nom de
    l'aptitude passe alors en français avec, puisqu'il n'y a plus de texte à
    nettoyer côté Wahapedia pour cette entrée précise."""
    result = []
    for ab in entries:
        override = _ABILITY_TEXT_OVERRIDES.get((faction, ab.name.strip().upper()))
        if override is None:
            result.append(ab)
        else:
            name_fr, description_fr = override
            result.append(_dc_replace(ab, name=name_fr, description=description_fr))
    return result


#: aptitudes de faction qui ciblent un héros précis de la liste : retirées
#: quand aucune unité de la liste n'est une cible éligible (demande de
#: l'utilisateur, une règle inutilisable n'a rien à faire sur la carte).
#: (faction, nom Wahapedia) -> (mots-clés tous requis, au moins un de,
#: aucun de). StD : « L'Œil des Dieux » cible un Héros Warriors of Chaos ou
#: Darkoath non Unique, et « Sombre Apothéose » ne se nourrit que de ses
#: points.
_TARGET_REQUIREMENTS: dict[tuple[str, str], tuple[frozenset[str], frozenset[str], frozenset[str]]] = {
    ("Slaves to Darkness", name): (
        frozenset({"HERO"}), frozenset({"WARRIORS OF CHAOS", "DARKOATH"}), frozenset({"UNIQUE"}),
    )
    # noms Wahapedia et français (`faction_rules_fr.json`) : le filtre passe
    # après `_fr_patch`, qui sinon rajouterait le correctif d'une entrée
    # retirée comme addition nette.
    for name in ("EYE OF THE GODS", "L'ŒIL DES DIEUX", "DARK APOTHEOSIS", "SOMBRE APOTHÉOSE")
}


def _spawned_manifestations(
    wh: WahapediaLookup, manifestations: list[WarscrollData], base_faction: str
) -> list[WarscrollData]:
    """Manifestations sans aptitude « SUMMON » propre, posées par une autre
    manifestation du domaine (ex. la Vrille Abyssale, créée par les « Vrilles
    Préhensiles » de l'Incarnation des Profondeurs, IDK) : une manifestation
    de la même faction dont le nom apparaît dans une aptitude d'une charte
    déjà résolue. Sans elles, le domaine choisi n'imprime pas tout ce qu'il
    permet de mettre sur la table. Pas de `summon` (aucun sort de
    convocation à afficher)."""
    known = {ws.name.lower() for ws in manifestations}
    found: list[WarscrollData] = []
    for fid in {ws.faction_id for ws in manifestations}:
        for row in wh.warscrolls:
            name = row["name"]
            if row["faction_id"] != fid or row.get("role") != "Manifestation" or name.lower() in known:
                continue
            pattern = re.compile(rf"\b{re.escape(name)}s?\b", re.IGNORECASE)
            if any(pattern.search(ab.description or "") for ws in manifestations for ab in ws.abilities):
                ws = wh.find_warscroll(name, prefer_faction=base_faction)
                if ws is not None:
                    found.append(ws)
                    known.add(name.lower())
    return found


def _drop_untargetable(
    entries: list[AbilityEntry] | None, parsed: ParsedList, wh: WahapediaLookup,
) -> list[AbilityEntry] | None:
    """Retire de `entries` (après `_fr_patch`) les aptitudes
    de `_TARGET_REQUIREMENTS` sans aucune cible éligible dans la liste."""
    if not entries or not any((parsed.base_faction, ab.name.strip().upper()) in _TARGET_REQUIREMENTS for ab in entries):
        return entries
    unit_keywords = []
    for name in parsed.unique_unit_names():
        ws = wh.find_warscroll(name)
        if ws is not None:
            unit_keywords.append({kw.strip().upper() for kw in ws.keywords})

    def eligible(ab: AbilityEntry) -> bool:
        req = _TARGET_REQUIREMENTS.get((parsed.base_faction, ab.name.strip().upper()))
        if req is None:
            return True
        all_of, any_of, none_of = req
        return any(all_of <= kws and kws & any_of and not kws & none_of for kws in unit_keywords)

    return [ab for ab in entries if eligible(ab)]


def _fr_patch(
    mode: RosterMode, frf: FactionRulesFr, entries: list[AbilityEntry] | None,
    faction: str, category: str, scope: str | None = None,
) -> list[AbilityEntry] | None:
    """Corrige/complète `entries` (pool déjà résolu via Wahapedia,
    éventuellement `None`/vide) avec les correctifs/additions vérbatim
    français de `data/json/faction_rules_fr.json` pour `faction`/`category`
    (`scope` filtre en plus sur la formation/le domaine choisi, cf.
    `faction_rules_fr.get_faction_category_overrides`) — uniquement en mode
    `fr`/`fr-extended` ; renvoie `entries` tel quel en `hybrid`/`en`, ou si
    rien n'est curé pour cette faction/catégorie (dégrade naturellement vers
    le comportement `en`, sans cas particulier à coder)."""
    if not mode_spec(mode).curated_patch:
        return entries
    overrides = get_faction_category_overrides(frf, faction, category, scope)
    if not overrides and scope is not None:
        # domaine générique (sorts/manifestations partagés entre factions,
        # Wahapedia `faction_id == "EnS"`) : curé une seule fois sous la
        # pseudo-faction "Endless Spells" plutôt que sous chaque faction.
        overrides = get_faction_category_overrides(frf, GENERIC_LORES_FACTION, category, scope)
    if not overrides:
        return entries
    return apply_fr_overrides(entries or [], overrides)


def _renown_army_pool(
    mode: RosterMode, frf: FactionRulesFr, faction: str, renown_name: str,
    grouped: dict[str, list[AbilityEntry]],
) -> list[AbilityEntry] | None:
    """`grouped` (`WahapediaLookup.find_renown_army_rules`, Wahapedia EN,
    jamais vide) patché avec le vérbatim français de `renown_armies.<renown_name>`
    (`get_renown_army_overrides`) si `mode` est `fr`/`fr-extended` *et* que
    chaque aptitude de chaque catégorie a bien été corrigée (nom Wahapedia
    reconnu) -- sinon `None`, pour ne jamais rendre un mélange
    français/anglais non signalé comme tel sur la carte de règles fusionnée :
    une Armée de Renom partiellement curée continue de tomber entièrement
    dans l'annexe anglaise (`build_roster_pdf`), comme avant cette fonction,
    jusqu'à curation complète (cf. `_RENOWN_ARMY_CATEGORY` pour les catégories
    couvertes -- `"Battle Formations"` n'existe pour aucune Armée de Renom,
    donc jamais dans `grouped`)."""
    if not mode_spec(mode).curated_patch:
        return None
    # "Heroic Traits" et "Artefacts of Power" (2 subtypes Wahapedia
    # distincts) partagent une seule catégorie JSON `heroic_traits_artefacts`
    # (même regroupement que côté faction de base, cf. `_STATIC_RULE_SECTIONS`)
    # : il faut donc fusionner leurs entrées *avant* d'appeler
    # `apply_fr_overrides`, pas catégorie par catégorie séparément, sans quoi
    # chaque appel verrait les correctifs de l'autre subtype comme des
    # additions nettes sans correspondance — doublant chaque aptitude.
    entries_by_category: dict[str, list[AbilityEntry]] = {}
    for subtype, entries in grouped.items():
        category = _RENOWN_ARMY_CATEGORY.get(subtype)
        if category is None:
            return None
        entries_by_category.setdefault(category, []).extend(entries)
    pool: list[AbilityEntry] = []
    for category, entries in entries_by_category.items():
        overrides = get_renown_army_overrides(frf, faction, renown_name, category)
        entry_names = {ability_join_key(e.name) for e in entries}
        covered_names = {ability_join_key(o.get("wahapedia_name")) for o in overrides}
        if entry_names - covered_names:
            # au moins une aptitude Wahapedia de cette catégorie n'a pas de
            # correctif reconnu -- curation partielle, on ne rend rien plutôt
            # que de mélanger français patché et anglais non patché sur la
            # même carte sans le signaler.
            return None
        pool.extend(apply_fr_overrides(entries, overrides))
    return tag_ability_origin(pool, renown_name)


def resolve_rules(
    parsed: ParsedList, faction_index: FactionIndex | None, index: WarscrollIndex, wh: WahapediaLookup,
    tactic_cards: dict[str, TacticCard], renown_categories: frozenset[str] = frozenset(),
    *, mode: RosterMode = "hybrid", frf: FactionRulesFr = FactionRulesFr(),
    renown_army: tuple[str, dict[str, list[AbilityEntry]]] | None = None,
    tactic_card_width: float = 0,
) -> tuple[
    list[tuple[str, list[int]]], list[tuple[str, list[int]]], list[tuple[str, object]],
    list[tuple[str, list[AbilityEntry]]], list[str], list[str], list[str], list[AbilityEntry], list[WarscrollData],
]:
    """Résout les sections de règles à inclure. Renvoie
    `(sections_battletome, sections_manifestations_génériques, sections_cartes_tactique, blocs_wahapedia, non_trouvé, sources_wahapedia, labels_carte_de_regle, bassin_aptitudes, manifestations_invoquables)`
    — les deux premières listes de sections viennent chacune d'un PDF source
    différent (`(label, pages)`) ; `sections_cartes_tactique` est
    `(label, Flowable)` — une carte maison par tactique citée (`tactic_cards`,
    déjà chargé par l'appelant), plus une page de battletome copiée comme les
    deux autres. `blocs_wahapedia` est le repli anglais pour
    un domaine de sorts/manifestations qui échappe aussi à ces sources
    françaises (`(label, entrées)`) ; `bassin_aptitudes` (`rule_ability_pool`,
    liste brute d'`AbilityEntry`, vide si rien n'a été résolu par Wahapedia)
    réunit *toutes* les catégories que Wahapedia couvre — Traits de Bataille /
    Formation choisie / Traits Héroïques / Artefacts de Pouvoir / domaine de
    sorts choisi / domaine de manifestations choisi / règles d'Armée de Renom
    curées — chaque aptitude déjà étiquetée par un badge d'origine (cf.
    `tag_ability_origin`), prête à être fusionnée par l'appelant avec les
    Règles de Saison/Aptitudes Génériques puis rendue en une seule carte
    triée par bandeau de phase (`build_roster_pdf`, pas cette fonction —
    elle ne rend plus rien elle-même, cf. `render_rule_card`) : deux traits
    de bataille et une formation qui se déclenchent tous en phase des héros
    doivent apparaître groupés sous le même bandeau. `labels_carte_de_regle`
    porte le détail catégorie par catégorie pour `rules_included`, même si
    le rendu final, lui, est unique. Une catégorie que Wahapedia ne couvre pas
    retombe sur la page French dans `sections_battletome` (ou, pour le
    domaine de sorts/manifestations, sur les replis déjà en place) — jamais
    mélangée au bassin.

    Un domaine de sorts et un domaine de manifestations sont d'abord
    cherchés dans `Faction_abilities.csv` (propre à la faction, ou générique
    `EnS`) pour construire une carte, puis, seulement si Wahapedia ne les
    couvre pas, dans le battletome de la faction, puis (manifestations
    seulement) dans le domaine générique français (`generic_manifestation_lores`
    — partagé entre factions, `data/Manuel du général/sorts persistants -
    manifestations.pdf`), puis Wahapedia en texte brut en tout dernier
    recours. Choisir un domaine de manifestations donne accès à *toutes* ses
    manifestations : `manifestations_invoquables` porte la charte complète de
    chacune (résolue via `find_warscroll` sur le nom de l'aptitude de
    convocation, `"SUMMON <nom>"`, débarrassé de son préfixe) quand la carte
    du domaine a pu être construite — vide sinon, la charte de chaque
    manifestation restant alors dans les pages du repli utilisé à la place.

    `mode`/`frf` (cf. `RosterMode`/`faction_rules_fr.py`) : en `fr`/
    `fr-extended`, chaque catégorie ci-dessus passe par `_fr_patch` juste
    après sa résolution Wahapedia — corrige/complète le pool avec les
    correctifs/additions de `data/json/faction_rules_fr.json` pour cette
    faction/catégorie (une faction non curée dégrade naturellement vers le
    résultat `en`) ; en `en`/`fr`/`fr-extended`, la copie de page French
    (`sections_battletome`, et les paliers French du domaine de sorts/
    manifestations) est sautée (`allow_page_copy = mode_spec(mode).page_copy`) — seul
    `hybrid` la conserve.

    `renown_categories` (vide si la liste n'utilise pas d'Armée de Renom) est
    l'ensemble des catégories que l'armée de renom choisie remplace (cf.
    `_AOR_REPLACES`) — la section correspondante du battletome de base est
    alors omise plutôt que dupliquée à côté de la version de remplacement
    (rendue séparément, en anglais via Wahapedia, dans l'annexe — sauf en
    `fr`/`fr-extended` avec une curation complète, cf. `renown_army`
    ci-dessous, auquel cas elle rejoint plutôt la carte combinée).

    `renown_army` (`(nom, grouped)`, `None` si la liste n'utilise pas d'Armée
    de Renom) : ses propres règles ne sont normalement rendues que dans
    l'annexe anglaise par l'appelant (`build_roster_pdf`, indépendamment de
    cette fonction) ; en `fr`/`fr-extended`, `_renown_army_pool` tente de les
    patcher en vérbatim français (`data/json/faction_rules_fr.json`,
    `renown_armies.<nom>`) et, seulement si *toutes* ses aptitudes ont un
    correctif reconnu, les fait rejoindre `rule_ability_pool` comme les
    autres catégories (label `"Armée de Renom — <nom>"` dans
    `rule_card_labels`, que l'appelant peut inspecter pour savoir s'il doit
    encore lister l'armée de renom dans son annexe anglaise) — sinon `None`
    est renvoyé et rien n'est ajouté ici, l'appelant gardant son ancien
    comportement (annexe anglaise complète).

    `tactic_card_width` : largeur (mm) à passer à `render_tactic_card` -- un
    paramètre de mise en page qui reste décidé par l'appelant (`pdf_builder.py`),
    cette fonction ne faisant aucun autre choix de mise en page elle-même."""
    battletome_sections: list[tuple[str, list[int]]] = []
    generic_manifestation_sections: list[tuple[str, list[int]]] = []
    wahapedia_blocks: list[tuple[str, list[AbilityEntry]]] = []
    unmatched: list[str] = []
    wahapedia_used: list[str] = []
    # Toutes les aptitudes "sans unité" (traits de bataille, formation,
    # traits héroïques, artefacts, domaine de sorts, domaine de
    # manifestations) rejoignent le même bassin, étiqueté par catégorie
    # (`tag_ability_origin`), pour être rendues sur *une seule* carte triée
    # par bandeau de phase à la toute fin plutôt qu'une carte par catégorie
    # — deux traits de bataille et une formation qui se déclenchent tous
    # les trois en phase des héros doivent apparaître groupés sous le même
    # bandeau, pas sur 3 cartes séparées qui répètent chacune leur propre
    # tri par phase.
    rule_ability_pool: list[AbilityEntry] = []
    rule_card_labels: list[str] = []
    covered_static_attrs: set[str] = set()
    # `fr`/`fr-extended` visent une carte maison partout, jamais une page
    # scannée : la copie de page French (`_STATIC_RULE_SECTIONS` ci-dessous,
    # et les paliers de repli page French du domaine de sorts/manifestations
    # plus bas) est sautée dans ces deux modes, comme en `en` — seul `hybrid`
    # (le comportement historique) la conserve.
    allow_page_copy = mode_spec(mode).page_copy

    if renown_army is not None:
        renown_name, grouped = renown_army
        renown_pool = _renown_army_pool(mode, frf, parsed.base_faction, renown_name, grouped)
        if renown_pool:
            rule_ability_pool.extend(renown_pool)
            rule_card_labels.append(f"Armée de Renom — {renown_name}")

    for label, type_name, static_attr in _WAHAPEDIA_RULE_CATEGORIES:
        if _AOR_REPLACES.get(static_attr, frozenset()) & renown_categories:
            covered_static_attrs.add(static_attr)  # remplacée par l'armée de renom (annexe), rien à copier ni à dessiner ici
            continue
        entries = wh.find_faction_category(parsed.base_faction, type_name) if wh.available else None
        # `_fr_patch` d'abord, contre le nom Wahapedia d'origine (sa clé de
        # rapprochement `wahapedia_name`) : `_apply_ability_text_overrides`
        # (repli historique pour un champ Wahapedia corrompu, cf. son
        # docstring) renomme déjà en français les quelques entrées qu'il
        # connaît, ce qui casserait ce rapprochement par nom s'il passait en
        # premier. Appliqué après, il devient un simple no-op sur toute
        # entrée déjà prise en charge par une entrée `faction_rules_fr.json`
        # plus riche (origine/historique), sans double correction.
        entries = _fr_patch(mode, frf, entries, parsed.base_faction, static_attr)
        if entries and not mode_spec(mode).english:  # texte français : pas en anglais
            entries = _apply_ability_text_overrides(entries, parsed.base_faction)
        entries = _drop_untargetable(entries, parsed, wh)
        if not entries:
            continue
        rule_ability_pool.extend(tag_ability_origin(entries, label))
        rule_card_labels.append(label)
        covered_static_attrs.add(static_attr)

    if wh.available:
        # Traits Héroïques/Artefacts de Pouvoir : plus jamais montrés en bloc
        # générique dès que Wahapedia est disponible — résolus par unité
        # ailleurs (cf. `build_roster_pdf`), qu'une correspondance ait été
        # trouvée ou non (une optimisation non choisie ne doit apparaître
        # nulle part, pas retomber sur la page de battletome combinée).
        covered_static_attrs.add("heroic_traits_artefacts")

    if parsed.allegiance and not (_AOR_REPLACES.get("formations", frozenset()) & renown_categories):
        formation_name = parsed.allegiance.split("(", 1)[0].strip()
        entries = wh.find_faction_category(parsed.base_faction, "Battle Formations", parsed.allegiance) if wh.available else None
        entries = _fr_patch(mode, frf, entries, parsed.base_faction, "formations", parsed.allegiance)
        if entries:
            rule_ability_pool.extend(tag_ability_origin(entries, f"Formation : {formation_name}"))
            rule_card_labels.append(f"Formation — {formation_name}")
            covered_static_attrs.add("formations")

    if faction_index is not None and allow_page_copy:
        for label, attr in _STATIC_RULE_SECTIONS:
            if attr in covered_static_attrs:
                continue
            if _AOR_REPLACES.get(attr, frozenset()) & renown_categories:
                continue
            pages = getattr(faction_index.rules, attr)
            if pages:
                battletome_sections.append((label, pages))

    # Un sort est une aptitude comme une autre (même schéma que les 4
    # catégories ci-dessus) : carte Wahapedia d'abord, repli page French
    # (`spell_lores`) puis repli texte anglais (domaine générique `EnS`) —
    # inchangé, seule la 1re étape est nouvelle. Pas de badge d'origine au
    # nom du domaine (idem pour les prières plus bas) : l'aptitude porte déjà
    # son badge SORT/PRIÈRE et la liste ne cite qu'un domaine (demande de
    # l'utilisateur, tous modes).
    if parsed.spell_lore:
        lore_name = parsed.spell_lore
        entries = wh.find_faction_category(parsed.base_faction, "Spell Lore", lore_name) if wh.available else None
        entries = _fr_patch(mode, frf, entries, parsed.base_faction, "spell_lores", lore_name)
        if entries:
            rule_ability_pool.extend(entries)
            rule_card_labels.append(f"Domaine de Sorts — {lore_name}")
        else:
            pages = (
                find_lore_pages(faction_index, faction_index.rules.spell_lores, lore_name)
                if faction_index and allow_page_copy else None
            )
            if pages:
                battletome_sections.append((f"Domaine de Sorts — {lore_name}", pages))
            else:
                entries = wh.find_generic_lore(lore_name) if wh.available else None
                if entries:
                    label = f"Domaine de Sorts — {lore_name} (EN, Wahapedia)"
                    wahapedia_blocks.append((label, entries))
                    wahapedia_used.append(label)
                else:
                    unmatched.append(f"Domaine de sorts : {lore_name}")

    # Une prière est au Prêtre ce qu'un sort est au Sorcier — même schéma
    # que le domaine de sorts ci-dessus, en plus court : aucun battletome
    # indexé ne mappe encore de page French pour une catégorie "Prayer
    # Lore" (seuls LRL/StD sont indexés aujourd'hui, tous deux à Sorciers),
    # donc pas de palier de repli intermédiaire ici — Wahapedia d'abord,
    # sinon un domaine générique `EnS` (rare, pas connu à ce jour pour les
    # prières mais gardé par cohérence avec le domaine de sorts), sinon non
    # trouvé.
    if parsed.prayer_lore:
        lore_name = parsed.prayer_lore
        entries = wh.find_faction_category(parsed.base_faction, "Prayer Lore", lore_name) if wh.available else None
        entries = _fr_patch(mode, frf, entries, parsed.base_faction, "prayer_lores", lore_name)
        if entries:
            rule_ability_pool.extend(entries)
            rule_card_labels.append(f"Domaine de Prières — {lore_name}")
        else:
            entries = wh.find_generic_lore(lore_name) if wh.available else None
            if entries:
                label = f"Domaine de Prières — {lore_name} (EN, Wahapedia)"
                wahapedia_blocks.append((label, entries))
                wahapedia_used.append(label)
            else:
                unmatched.append(f"Domaine de prières : {lore_name}")

    # Un domaine de manifestations est deux choses à la fois : l'aptitude de
    # convocation elle-même (une par manifestation invocable, nommée
    # "SUMMON <nom de la manifestation>" côté Wahapedia — vérifié aussi bien
    # pour un domaine propre à une faction, ex. "Manifestations of Hysh",
    # que pour les 6 domaines génériques `EnS`) *et* la charte complète de
    # chaque manifestation qu'il permet d'invoquer (résolue via
    # `find_warscroll` en retirant le préfixe "SUMMON "). Les deux doivent
    # être trouvés pour basculer sur les cartes maison — sinon repli entier
    # sur l'ancien chemin (page French, puis domaine générique français,
    # puis bloc texte anglais) plutôt qu'un rendu à moitié en carte, à moitié
    # ailleurs, qui romprait la règle "le domaine donne accès à *toutes* ses
    # manifestations".
    manifestation_warscrolls: list[WarscrollData] = []
    if parsed.manifestation_lore:
        lore_name = parsed.manifestation_lore
        entries = wh.find_faction_category(parsed.base_faction, "Manifestation Lore", lore_name) if wh.available else None
        if not entries:
            entries = wh.find_generic_lore(lore_name) if wh.available else None
        resolved: list[WarscrollData] = []
        if entries and wh.available:
            for ab in entries:
                manif_name = re.sub(r"^summon\s+", "", ab.name, flags=re.IGNORECASE).strip()
                # La ligne "SUMMON <nom>" de Wahapedia omet parfois l'article
                # initial de la charte réelle (ex. "SUMMON BURNING HEAD" vs
                # la charte "The Burning Head", domaine "Primal Energy") —
                # sans ce repli, `find_warscroll` échoue sur cette seule
                # manifestation, ce qui fait basculer *tout* le domaine sur
                # l'annexe anglaise (cf. règle "toutes résolues ou aucune"
                # ci-dessous), pour une liste qui n'avait pourtant besoin que
                # de cette manifestation-là.
                ws = wh.find_warscroll(manif_name) or wh.find_warscroll(f"The {manif_name}")
                if ws is not None:
                    resolved.append(ws)
        if entries and len(resolved) == len(entries):
            # Les correctifs vérbatim français ne s'appliquent qu'*après*
            # avoir résolu les manifestations invocables ci-dessus, sur les
            # noms Wahapedia d'origine ("SUMMON <nom>") : un correctif qui
            # renommerait l'aptitude de convocation romprait ce
            # rapprochement par préfixe. Une addition nette (sans
            # `wahapedia_name`) n'a donc aucun sens ici, cf. le docstring de
            # `faction_rules_fr.py` — seul un correctif est appliqué.
            entries = _fr_patch(mode, frf, entries, parsed.base_faction, "manifestation_lores", lore_name)
            # `set_ability_category` : ces aptitudes de convocation portent un
            # `points_type` "Spell"/"Prayer" comme un sort/une prière
            # ordinaire côté Wahapedia — sans ce marquage explicite, elles
            # rejoindraient le regroupement Sorts/Prières de la carte de
            # règles fusionnée (`render/phases._ability_category`) plutôt
            # que leur propre bloc Manifestations.
            # Badge unique « Manifestation » (demande de l'utilisateur) : le
            # même que les aptitudes des chartes de manifestation
            # (`split_pool._warscroll_ability_pool`), à la place du mot-clé
            # Wahapedia « Summon » et du nom du domaine, qui n'apportent rien
            # en jeu.
            entries = [
                _dc_replace(ab, keywords=",".join(
                    kw for kw in (ab.keywords or "").split(",") if kw.strip() and kw.strip().lower() != "summon"
                ))
                for ab in entries
            ]
            tagged = set_ability_category(tag_ability_origin(entries, "Manifestation"), "manifestation")
            rule_ability_pool.extend(tagged)
            rule_card_labels.append(f"Domaine de Manifestations — {lore_name}")
            # chaque charte garde son aptitude de convocation (déjà patchée en
            # français, même ordre que `resolved` : un correctif ne réordonne
            # pas) pour son badge de lancement et sa note de pose.
            manifestation_warscrolls = [_dc_replace(ws, summon=ab) for ws, ab in zip(resolved, entries)]
            manifestation_warscrolls.extend(_spawned_manifestations(wh, manifestation_warscrolls, parsed.base_faction))
        else:
            pages = (
                find_lore_pages(faction_index, faction_index.rules.manifestation_lores, lore_name)
                if faction_index and allow_page_copy else None
            )
            if pages:
                battletome_sections.append((f"Domaine de Manifestations — {lore_name}", pages))
            else:
                generic_lore = find_generic_manifestation_lore(index, lore_name) if allow_page_copy else None
                if generic_lore is not None:
                    label = f"Domaine de Manifestations — {lore_name} (Manuel du général)"
                    generic_manifestation_sections.append((label, generic_lore.all_pages()))
                else:
                    entries = wh.find_generic_lore(lore_name) if wh.available else None
                    if entries:
                        label = f"Domaine de Manifestations — {lore_name} (EN, Wahapedia)"
                        wahapedia_blocks.append((label, entries))
                        wahapedia_used.append(label)
                    else:
                        unmatched.append(f"Domaine de manifestations : {lore_name}")

    # Cartes de tactique de bataille : rendues en carte maison (verbatim
    # français, transcription manuelle de `MdG26-27 Tactiques.pdf` — voir
    # `tactic_cards.py`) plutôt que copiées depuis le PDF, comme le reste du
    # kit. Pool fermé de 6 cartes pour la saison 2026-27 — pas de repli
    # nécessaire, une carte citée mais absente du JSON est un vrai
    # non-trouvé.
    tactic_sections: list[tuple[str, object]] = []
    for card_name in parsed.battle_tactic_cards:
        tactic_card = find_tactic_card(tactic_cards, card_name)
        if tactic_card is not None:
            if mode_spec(mode).simple and not mode_spec(mode).english and compress_tactic_conditions_enabled():
                tactic_card = compress_tactic_conditions(tactic_card)
            tactic_sections.append((card_name, render_tactic_card(tactic_card, width=tactic_card_width)))
        else:
            unmatched.append(f"Carte de tactique : {card_name}")

    return (
        battletome_sections, generic_manifestation_sections, tactic_sections, wahapedia_blocks, unmatched,
        wahapedia_used, rule_card_labels, rule_ability_pool, manifestation_warscrolls,
    )
