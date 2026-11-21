"""Pool d'aptitudes des modes étendus/split : aptitudes sorties des warscrolls, sous-sections de choix (`_CHOICE_CLUSTERS`), ordre du déploiement, aptitudes retirées d'une carte de tour, alias d'unités, ordre des sous-sections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import replace as _dc_replace

from .modes import mode_spec
from .render.cards import tag_ability_origin
from .render.phases import (
    CHOICE_CATEGORIES,
    ability_section,
    ability_turn_sides,
    classify_phase,
    is_self_profile_modifier,
)
from .render.text import english_labels, strip_flavor
from .sources.faction_rules_fr import (
    ability_join_key,
)
from .sources.tactic_cards import find_tactic_card
from .sources.wahapedia_lookup import (
    AbilityEntry,
    WarscrollData,
)


def _apply_display_fr(ws: WarscrollData, display: dict) -> WarscrollData:
    """Nom, mots-clés et profils d'arme traduits (`faction_rules_fr.json`,
    cf. `get_unit_display_overrides`) — une arme sans traduction garde son
    nom Wahapedia."""
    if not display:
        return ws
    changes: dict = {}
    if display.get("name_fr"):
        changes["name"] = display["name_fr"]
    if display.get("subtitle_fr"):
        changes["subtitle"] = display["subtitle_fr"]
    if display.get("keywords_fr"):
        changes["keywords"] = list(display["keywords_fr"])
    weapons_fr = {ability_join_key(w["wahapedia_name"]): w for w in display.get("weapons", [])}
    if weapons_fr:
        changes["weapons"] = [
            _dc_replace(w, name=fr["name"], abilities=fr.get("abilities", w.abilities))
            if (fr := weapons_fr.get(ability_join_key(w.name))) else w
            for w in ws.weapons
        ]
    return _dc_replace(ws, **changes)


def _mark_self_profile(ws: WarscrollData) -> WarscrollData:
    """Marque (`AbilityEntry.self_profile`) les aptitudes qui ne modifient
    que le profil de l'unité (`is_self_profile_modifier`), sur le texte et
    les noms d'arme Wahapedia d'origine : à appeler *avant* les correctifs
    français, qui traduisent « Cursed Lances » dans le texte de l'aptitude
    sans forcément traduire le nom de l'arme dans le profil."""
    names = [w.name for w in ws.weapons]
    return _dc_replace(ws, abilities=[
        _dc_replace(ab, self_profile=True) if is_self_profile_modifier(ab, names) else ab for ab in ws.abilities
    ])


def _with_section(abilities: list[AbilityEntry], section: str) -> list[AbilityEntry]:
    return [_dc_replace(ab, section=section) for ab in abilities]


def _warscroll_ability_pool(warscrolls: list[WarscrollData]) -> list[AbilityEntry]:
    """Aptitudes de tous les warscrolls (`fr-split`), chacune marquée du nom
    de son warscroll (`AbilityEntry.warscrolls`, badge dédié). Une même
    aptitude (nom, texte et timing identiques — texte d'ambiance en tête
    ignoré, jamais imprimé : ex. « Descendez-les » des Boltboyz et de la
    Killbow) portée par plusieurs unités de la liste —
    n'apparaît qu'une fois, avec un badge par unité, plutôt que répétée à
    l'identique dans la même phase. Ordre de première apparition conservé
    (celui des cartes : héros d'abord, cf. `_role_rank`). Les aptitudes de
    profil de l'unité elle-même (`is_self_profile_modifier`, ex. Stigmates de Guerre, Charge Empaleuse) n'y entrent pas :
    elles restent sur la carte du warscroll. Les aptitudes d'une
    manifestation (mot-clé d'unité `MANIFESTATION`) reçoivent un badge
    « Manifestation » (demande de l'utilisateur) : sorties de leur carte,
    rien d'autre ne les distingue d'une aptitude d'unité."""
    merged: dict[tuple, AbilityEntry] = {}
    for ws in warscrolls:
        abilities = ws.abilities
        if any(kw.strip().upper() == "MANIFESTATION" for kw in ws.keywords):
            abilities = tag_ability_origin(abilities, "Manifestation")
        for ab in abilities:
            if is_self_profile_modifier(ab, [w.name for w in ws.weapons]):
                continue
            key = (ab.name, strip_flavor(ab.description), ab.condition, ab.ability_phase, ab.keywords, ab.points_type, ab.points)
            prev = merged.get(key)
            if prev is None:
                merged[key] = _dc_replace(ab, warscrolls=(ws.name,))
            elif ws.name not in prev.warscrolls:
                merged[key] = _dc_replace(prev, warscrolls=prev.warscrolls + (ws.name,))
    return list(merged.values())


@dataclass(frozen=True)
class _ChoiceCluster:
    """Sous-section de choix en tête du bandeau `phase` (demande de
    l'utilisateur) : la ou les aptitudes qui font *choisir* (`chooser_names`,
    dans cet ordre) suivies de toutes les options possibles (`keyword`,
    mot-clé d'aptitude Wahapedia ; vide quand les options sont décrites dans
    le texte même du choix, ex. Bénédictions de Khaine), pour voir d'un coup
    d'oeil, au moment du choix, tout ce qu'on peut prendre. Les options qui
    agissent dans une autre phase restent *aussi* à leur place (doublon
    voulu) ; celles déjà dans `phase` n'y sont pas dupliquées, l'appelant
    retire leur original. `moved_names` : aptitudes liées au choix sans en
    être une option, *déplacées* (pas dupliquées) juste après les
    `chooser_names` (ou à leur place s'ils y figurent aussi) — elles n'ont de
    sens qu'au moment du choix. Toute réaction à un `chooser_names`
    (`_is_choice_reaction`, ex. « Offrandes Pourpres » des Blood Hags aux
    Bénédictions de Khaine) est déplacée de la même façon. Noms en
    anglais (Wahapedia) et en français (patch `faction_rules_fr.json`),
    minuscules. Appliquée dans les modes étendus (`ModeSpec.extended`).
    `option_names` : options repérées par leur nom quand elles n'ont pas de
    mot-clé commun (ex. les 4 « Voué à … » de Slaves to Darkness), dans cet
    ordre, une seule par nom (la copie d'un warscroll identique est déjà
    fondue dans la règle d'armée, cf. `_fold_warscroll_copies`)."""

    category: str
    chooser_names: tuple[frozenset[str], ...]
    keyword: str = ""
    option_names: tuple[frozenset[str], ...] = ()
    moved_names: frozenset[str] = frozenset()
    phase: str = "Start of Turn"


_CHOICE_CLUSTERS = (
    # Flesh-eater Courts : « Royaume Délirant » fait choisir le Délire du tour
    # (il n'a lui-même pas le mot-clé "Delusion", d'où le repère par nom) ;
    # « Épicentre de l'Illusion » (Ushoran, ±1 au jet de délire) y est déplacé.
    _ChoiceCluster(
        category="delusion", keyword="delusion",
        chooser_names=(frozenset({"a kingdom deluded", "royaume délirant"}),),
        moved_names=frozenset({"epicentre of delusion", "épicentre de l'illusion"}),
    ),
    # Blades of Khorne : « Des Crânes pour le Trône de Crânes » déverrouille
    # une aptitude de Dîme de Sang, « Trempés de Sang » réagit à ce
    # déverrouillage — puis toutes les aptitudes de Dîme de Sang, par coût.
    _ChoiceCluster(
        category="blood_tithe", keyword="blood tithe",
        chooser_names=(
            frozenset({"skulls for the skull throne", "des crânes pour le trône de crânes"}),
            frozenset({"blood-drenched", "trempés de sang"}),
        ),
    ),
    # Daughters of Khaine : « Rites de Sang » (comment on en accomplit,
    # passif déplacé) puis « Bénédictions de Khaine », qui fait choisir la
    # bénédiction — en fin de tour, moment de ce choix ; les 7 bénédictions
    # sont dans son propre texte, pas d'aptitudes-options séparées.
    _ChoiceCluster(
        category="khaine_blessing",
        chooser_names=(
            frozenset({"blood rites", "rites de sang"}),
            frozenset({"blessings of khaine", "bénédictions de khaine"}),
        ),
        moved_names=frozenset({"blood rites", "rites de sang"}),
        phase="End of Turn",
    ),
    # Slaves to Darkness : « Vocation au Chaos » (phase des héros) fait
    # choisir un vœu — les 4 « Voué à … » en options ; chacun reste aussi
    # dans la phase où il sert (demande de l'utilisateur).
    _ChoiceCluster(
        category="chaos_pledge",
        chooser_names=(frozenset({"pledge to chaos", "vocation au chaos"}),),
        option_names=(
            frozenset({"pledged to khorne", "voué à khorne"}),
            frozenset({"pledged to tzeentch", "voué à tzeentch"}),
            frozenset({"pledged to nurgle", "voué à nurgle"}),
            frozenset({"pledged to slaanesh", "voué à slaanesh"}),
        ),
        phase="Hero Phase",
    ),
)


def _is_option(ab: AbilityEntry, spec: _ChoiceCluster) -> bool:
    if spec.keyword and _has_keyword(ab, spec.keyword):
        return True
    return any(ab.name.strip().lower() in names for names in spec.option_names)


def _fold_warscroll_copies(pool: list[AbilityEntry]) -> list[AbilityEntry]:
    """Une aptitude de warscroll identique à une règle d'armée du bassin
    (même nom, même texte hors ambiance, même timing — ex. « Voué à Nurgle »
    du Prince Démon, qui a déjà le vœu, et le trait de bataille) n'est pas
    répétée : la règle d'armée prend la pastille de l'unité."""
    def key(ab: AbilityEntry) -> tuple:
        return (ab.name.strip().lower(), strip_flavor(ab.description), ab.condition, ab.ability_phase)

    army = {key(ab): i for i, ab in enumerate(pool) if not ab.warscrolls}
    out = list(pool)
    dropped: set[int] = set()
    for i, ab in enumerate(pool):
        j = army.get(key(ab)) if ab.warscrolls else None
        if j is None:
            continue
        out[j] = _dc_replace(out[j], warscrolls=out[j].warscrolls + tuple(w for w in ab.warscrolls if w not in out[j].warscrolls))
        dropped.add(i)
    return [ab for i, ab in enumerate(out) if i not in dropped]


def _has_keyword(ab: AbilityEntry, keyword: str) -> bool:
    return any(kw.strip().lower() == keyword for kw in (ab.keywords or "").split(","))


_DECLARED_ABILITY_RE = re.compile(r"you declared the\s*[‘'’\"]?%?\d*([^‘'’\"%]+)", re.IGNORECASE)


def _is_choice_reaction(ab: AbilityEntry, spec: _ChoiceCluster) -> bool:
    """Réaction (condition Wahapedia « Reaction: You declared the ‘<nom>’
    ability », toujours en anglais, le patch français ne la touche pas) à
    l'une des aptitudes de choix de `spec`."""
    m = _DECLARED_ABILITY_RE.search(ab.condition or "")
    return m is not None and any(m.group(1).strip().lower() in names for names in spec.chooser_names)


def _points_sort_key(ab: AbilityEntry) -> int:
    value = (ab.points or "").strip()
    return int(value) if value.isdigit() else 0


def _choice_cluster(pool: list[AbilityEntry], spec: _ChoiceCluster) -> list[AbilityEntry]:
    """Les aptitudes de la sous-section `spec` (cf. `_ChoiceCluster`), basculées
    dans sa phase et marquées de sa catégorie. Liste vide si le bassin ne
    porte aucune option (ni aucun choix, pour une sous-section sans
    `keyword`) — toute autre faction : aucun effet."""
    if spec.option_names:
        options = [
            first for names in spec.option_names
            if (first := next((ab for ab in pool if ab.name.strip().lower() in names), None)) is not None
        ]
    else:
        options = sorted((ab for ab in pool if spec.keyword and _has_keyword(ab, spec.keyword)), key=_points_sort_key)
    choosers = [ab for names in spec.chooser_names for ab in pool if ab.name.strip().lower() in names]
    if not (options if (spec.keyword or spec.option_names) else choosers):
        return []
    # un nom à la fois choisi et déplacé (« Rites de Sang ») garde sa place
    # parmi les `chooser_names`, sans doublon.
    moved = [
        ab for ab in pool
        if (ab.name.strip().lower() in spec.moved_names or _is_choice_reaction(ab, spec)) and ab not in choosers
    ]
    return [
        _dc_replace(ab, ability_phase=spec.phase, ability_category=spec.category)
        for ab in choosers + moved + options
    ]


def _turn_sides(ab: AbilityEntry, pool: list[AbilityEntry]) -> set[str]:
    """Tour(s) d'une aptitude (`ability_turn_sides`) ; une copie de sous-section
    de choix n'apparaît que dans un tour où l'aptitude qui fait choisir (la
    première de sa catégorie, cf. `_choice_cluster`) sert aussi : les
    « Voué à … » passifs ne doivent pas ouvrir une « Vocation au Chaos »
    (votre phase des héros) dans le tour adverse."""
    sides = set(ability_turn_sides(ab))
    if ab.ability_category in CHOICE_CATEGORIES:
        chooser = next(x for x in pool if x.ability_category == ab.ability_category)
        sides &= set(ability_turn_sides(chooser))
    return sides


def _apply_choice_clusters(pool: list[AbilityEntry], mode: str) -> list[AbilityEntry]:
    """Ajoute au bassin chaque sous-section de choix (`_CHOICE_CLUSTERS`)
    active pour `mode`, en retirant les originaux qu'elle remplace : options
    et `chooser_names` déjà dans sa phase (pas de doublon dans la même
    phase), `moved_names` et réactions au choix quelle que soit leur phase."""
    if not mode_spec(mode).extended:
        return pool
    for spec in _CHOICE_CLUSTERS:
        cluster = _choice_cluster(pool, spec)
        if not cluster:
            continue
        chooser_names = frozenset().union(*spec.chooser_names)
        phase_key = classify_phase(cluster[0])
        pool = [
            ab for ab in pool
            if not ((_is_option(ab, spec) or ab.name.strip().lower() in chooser_names)
                    and classify_phase(ab) == phase_key)
            and ab.name.strip().lower() not in spec.moved_names
            and not _is_choice_reaction(ab, spec)
        ] + cluster
    return pool


#: ordre de déroulé d'une partie (demande de l'utilisateur) : ces aptitudes
#: ouvrent le bandeau Déploiement, dans cet ordre, une par ligne
#: (`AbilityEntry.full_width`) — modes `fr-extended`/`fr-split`/
#: `fr-split-simple`.
_DEPLOY_ORDER = tuple(ability_join_key(n) for n in (
    "Placez le Champ de Bataille", "Déploiement de Terrain de Faction", "Déploiement de Régiment",
    "Déploiement d’Unité", "Souffler sur les Braises",
    # pas un déploiement, mais même modèle « étapes numérotées » : ouvre le
    # bandeau « Début de Round », en pleine largeur
    "Début de Round de Bataille",
    # `en-split-simple` (`generic_core_abilities_en.json`, `season_rules_en.json`)
    "Set Up the Battlefield", "Deploy Faction Terrain", "Deploy Regiment", "Deploy Unit", "Raising the Heat",
    "Start of Battle Round",
))


def _order_deploy(abilities: list[AbilityEntry]) -> list[AbilityEntry]:
    """Aptitudes de `_DEPLOY_ORDER` en tête, dans cet ordre et en pleine
    largeur ; les autres suivent dans leur ordre d'origine (tri stable)."""
    rank = {key: i for i, key in enumerate(_DEPLOY_ORDER)}
    out = sorted(abilities, key=lambda ab: rank.get(ability_join_key(ab.name), len(rank)))
    return [_dc_replace(ab, full_width=True) if ability_join_key(ab.name) in rank else ab for ab in out]


#: relance du jet de charge (ordre de base) — EN Wahapedia + FR MdG.
_CHARGE_REROLL_KEYS = frozenset(ability_join_key(n) for n in ("En Avant, vers la Victoire", "Forward to Victory"))


def _has_charge_keyword(ability: AbilityEntry) -> bool:
    # « Charge Rampage » : virgule manquante dans au moins une ligne Wahapedia
    return any("charge" in kw.lower().split() for kw in (ability.keywords or "").split(","))


#: ordres inapplicables dans le tour adverse (demande de l'utilisateur) :
#: « Au Pas de Course » réagit à une Course, qui ne se fait qu'à votre phase
#: de mouvement — retirés de la carte « Tour adverse » (modes split).
_MINE_ONLY_KEYS = frozenset(ability_join_key(n) for n in ("Au Pas de Course", "At the Double"))


_CASTER_LEVEL_RE = re.compile(r"^(WIZARD|PRIEST)\s*\(\d+\)$", re.IGNORECASE)


def _merge_unit_keywords(keywords: list[str], added) -> list[str]:
    """`keywords` + mots-clés `add_unit_keywords` ; un `WIZARD (N)`/`PRIEST (N)`
    ajouté *remplace* celui du même type déjà porté (ex. Bâton des Marais
    *Appliqué* : Sorcier (1) → « WIZARD (2) »), au lieu d'un second badge."""
    out = list(keywords)
    for kw in added:
        m = _CASTER_LEVEL_RE.match(kw.strip())
        if m:
            out = [k for k in out if not ((c := _CASTER_LEVEL_RE.match(k.strip())) and c.group(1).upper() == m.group(1).upper())]
        if kw not in out:
            out.append(kw)
    return out


def _drop_enemy_charge_reroll(enemy: list[AbilityEntry]) -> list[AbilityEntry]:
    """Retire « En Avant, vers la Victoire » de la carte « Tour adverse »
    (modes split, demande de l'utilisateur) sauf si une autre aptitude de
    cette carte porte le mot-clé Charge : sinon la seule unité qui peut y
    charger est celle qui fait une Contre-Charge, déjà un ordre — elle ne
    peut pas en recevoir un second, la relance prête donc à confusion."""
    if any(_has_charge_keyword(ab) for ab in enemy if ability_join_key(ab.name) not in _CHARGE_REROLL_KEYS):
        return enemy
    return [ab for ab in enemy if ability_join_key(ab.name) not in _CHARGE_REROLL_KEYS]


def _tactic_special_rules(parsed, tactic_cards) -> list[AbilityEntry]:
    """Règle spéciale de chaque carte de tactique citée (ex. le repaire
    d'« Assaut Flamboyant ») en aptitude du bandeau Déploiement : elle se joue
    après le déploiement, avant de déterminer qui a le premier tour, alors que
    la carte elle-même n'est lue qu'en fin de tour (demande de l'utilisateur,
    tous modes). Texte vérbatim de la carte."""
    out = []
    for card_name in parsed.battle_tactic_cards:
        card = find_tactic_card(tactic_cards, card_name)
        if card is None or not card.special_rule:
            continue
        out.append(AbilityEntry(
            name=f"{card.name_en}: Special Rule" if english_labels() else f"{card.title_fr} : Règle Spéciale",
            description=card.special_rule, legend="",
            condition="Deployment Phase", ability_phase="Deployment Phase", full_width=True,
        ))
    return out


#: coût d'une option payante en fin de sous-ligne ` • ... - (N) Points`.
_PAID_OPTION_RE = re.compile(r"\((\d+)\)\s*points?\s*$", re.IGNORECASE)


def _relabel_options(parsed, simplifications):
    """Page de garde `fr-split-simple` : options ` • ...` renommées selon
    `RosterSimplifications.option_labels` (copie, `parsed` reste intact pour
    la résolution des optimisations)."""
    if simplifications is None or not simplifications.option_labels:
        return parsed
    labels = simplifications.option_labels
    regiments = [
        _dc_replace(reg, units=[
            _dc_replace(u, options=[labels.get(o, o) for o in u.options]) for u in reg.units
        ])
        for reg in parsed.regiments
    ]
    return _dc_replace(parsed, regiments=regiments)


def _apply_unit_aliases(parsed, simplifications):
    """`RosterSimplifications.unit_aliases` : l'entrée de la liste dont le nom
    et les options correspondent prend le nom affiché (copie de `parsed`).
    Renvoie aussi `{nom affiché -> nom d'unité}`, pour retrouver son warscroll."""
    if simplifications is None or not simplifications.unit_aliases:
        return parsed, {}
    sources: dict[str, str] = {}
    regiments = []
    for reg in parsed.regiments:
        units = []
        for u in reg.units:
            for alias, (unit, options) in simplifications.unit_aliases.items():
                if u.name == unit and set(options) <= set(u.options):
                    u = _dc_replace(u, name=alias)
                    sources[alias] = unit
                    break
            units.append(u)
        regiments.append(_dc_replace(reg, units=units))
    return _dc_replace(parsed, regiments=regiments), sources


def _apply_section_order(pool: list[AbilityEntry], section_order: dict[str, tuple[str, ...]]) -> list[AbilityEntry]:
    """`section_order` (`roster_simplifications.json`) : les sous-sections
    nommées passent en tête de leur bandeau de phase, dans l'ordre donné
    (rang négatif, avant « Règles de base »)."""
    if not section_order:
        return pool
    out = []
    for ab in pool:
        titles = section_order.get(classify_phase(ab), ())
        title = ability_section(ab)
        if title in titles:
            ab = _dc_replace(ab, section_rank=titles.index(title) - len(titles))
        out.append(ab)
    return out


def _collapse_alias_pills(pool: list[AbilityEntry], alias_sources: dict[str, str]) -> list[AbilityEntry]:
    """Une aptitude portée à la fois par un alias (`unit_aliases`) et par son
    unité d'origine ne garde que l'unité d'origine (« Verminlord
    Warbringer » couvre les deux Warbringers) — demande de l'utilisateur."""
    out = []
    for ab in pool:
        names = ab.warscrolls or ()
        kept = tuple(n for n in names if not (n in alias_sources and alias_sources[n] in names))
        out.append(ab if kept == tuple(names) else _dc_replace(ab, warscrolls=kept))
    return out


def _drop_identical_alias_cards(warscrolls: list[WarscrollData], alias_sources: dict[str, str]) -> list[WarscrollData]:
    """Modes split (demande de l'utilisateur) : une fois les aptitudes parties
    sur les cartes de tour, la carte d'un alias (`unit_aliases`, ex.
    « Warbringer riche et outillé ») identique à celle de son unité d'origine
    — mêmes caractéristiques, armes, mots-clés et aptitudes restées — n'est
    plus qu'un doublon : retirée, l'alias ne sert plus qu'aux pastilles des
    cartes de tour."""
    by_name = {ws.name: ws for ws in warscrolls}

    def same(alias: WarscrollData, base: WarscrollData) -> bool:
        return _dc_replace(alias, name=base.name, subtitle=base.subtitle) == base

    return [
        ws for ws in warscrolls
        if not (ws.name in alias_sources and alias_sources[ws.name] in by_name and same(ws, by_name[alias_sources[ws.name]]))
    ]
