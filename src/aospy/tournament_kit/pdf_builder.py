"""Assemble le PDF « kit de tournoi » : page de couverture (liste mise en
forme), puis les règles de faction pertinentes en carte maison (traits de
bataille, formation, traits héroïques/artefacts, domaines de sorts/
manifestations choisis — Wahapedia-first, repli page French par catégorie,
cf. `render/`) et les cartes de tactique de bataille citées, elles
aussi en carte maison verbatim français (`tactic_cards.py`, transcription
manuelle de `MdG26-27 Tactiques.pdf` — plus de copie de page pour aucune de
ces sections), puis les profils d'unité, en carte maison anglaise dessinée
par `render/` à partir de `data/wahapedia/*.csv` (jamais une page
de battletome copiée, cf. le module de ce fichier pour le détail). Un
domaine de manifestations générique (partagé entre
factions, absent du battletome) est résolu en français via
`data/Manuel du général/sorts persistants - manifestations.pdf`
(`warscroll_index.generic_manifestation_lores`) — règles de convocation
*et* charte de chaque manifestation invocable, pas seulement l'annonce du
sort. Enfin, si besoin, une annexe en anglais (repli Wahapedia,
`wahapedia_lookup.py`) pour tout ce qui n'existe dans *aucun* des PDF
fournis : règles d'armée de renom, Régiments de Renom, et tout domaine de
sorts/manifestations qui échapperait aussi au French. Aucun accès DB
requis.

Une Armée de Renom (ex. « Slaves to Darkness | Legion of the First Prince »)
*remplace* tout ou partie des traits de bataille / traits héroïques et
artefacts / domaine de sorts de la faction de base par ses propres règles
(cf. `_AOR_REPLACES`) — la page du battletome de base correspondante est
omise plutôt que dupliquée à côté de la version de remplacement (rendue à
part, en anglais via Wahapedia). Aucune armée de renom n'a en revanche ses
propres formations de bataille (constaté sur toutes les entrées du CSV) :
cette section-là reste toujours celle de la faction de base. Un Regiment of
Renown donne accès à des warscrolls normalement hors faction (résolus via
`WahapediaLookup.find_warscroll`, qui cherche dans toutes les factions) *et*
peut porter sa propre aptitude générique (`RegimentOfRenownData.abilities`) —
rendue dans l'annexe comme n'importe quel autre bloc d'aptitudes s'il compte
plusieurs unités membres, mais directement rattachée à la carte de l'unité
(`_render_warscroll(..., extra_abilities=...)`) quand le régiment n'en a
qu'une seule, pour ne pas dupliquer inutilement la structure.

Le paragraphe ci-dessus décrit le mode `hybrid` (défaut). `build_roster_pdf(...,
mode=...)` porte 3 autres variantes (`RosterMode`) : `en` (Wahapedia
uniquement, la copie de page French est sautée) et `fr`/`fr-extended`
(correctifs/additions vérbatim français de `data/json/faction_rules_fr.json`
appliqués sur le pool Wahapedia partout où ils existent, copie de page
également sautée — `fr-extended` ajoute les Aptitudes Génériques,
`data/json/generic_core_abilities.json`). Cf. le commentaire au-dessus de
`RosterMode` et le skill `faction-rules-fr` pour le détail.

Les Règles de Saison 2026-27 (`season_rules.py`, incluses dans tout PDF), les
Aptitudes Génériques (`fr-extended` seulement) et les règles de faction/
Armée de Renom résolues ci-dessus (`rule_ability_pool`) rejoignent toutes le
même bassin d'aptitudes puis une seule carte triée par bandeau de phase
(`build_roster_pdf`, badges d'origine « Saison »/« MdG »/faction pour rester
identifiables) — jamais 3 cartes séparées : un joueur qui consulte la carte
raisonne par phase du tour ("je suis en phase des héros, qu'ai-je le droit
de faire ?"), pas par type de règle."""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .assembly import (
    _RULE_CARD_WIDTH,
    _TACTIC_CARD_WIDTH,
    _TACTIC_MIN_SCALE,
    DEFAULT_SCENARIOS_FILE,
    _append_pages,
    _append_scenario_pages,
    _build_rule_cards_pdf,
    _build_tactic_cards_pdf,
    _build_wahapedia_appendix_pdf,
    _build_warscroll_cards_pdf,
    _pad_to_odd_page,
    _stamp_page_numbers,
    _strip_all_tags,
    _tactic_cards_block,
    scenario_variant_path,
)
from .cover import (
    _build_cover_pdf,
    _role_rank,
)
from .list_parser import parse_list_file
from .modes import RosterMode, mode_spec
from .render.cards import render_rule_card
from .render.options import render_session, update_render_options
from .render.phases import (
    CHOICE_CATEGORIES,
    SECTION_ARMY,
    SECTION_BASE,
    SPLIT_PHASE_ORDER,
    TURN_ENEMY,
    TURN_MINE,
    classify_phase,
    is_self_profile_modifier,
)
from .render.pills import drawn_badge_shapes, reset_drawn_badge_shapes
from .render.text import tr
from .resolution.absent_references import find_absent_keywords, find_absent_references
from .resolution.rules_resolution import (
    _BANNER_PLEDGED_GOD,
    _PLEDGE_OPTION_RE,
    find_pledge_battle_trait,
    resolve_rules,
)
from .sources.faction_rules_fr import (
    DEFAULT_APP_RULES_EN_FILE,
    ability_join_key,
    apply_fr_overrides,
    get_faction_category_overrides,
    get_regiment_of_renown_overrides,
    get_renown_army_overrides,
    get_unit_ability_overrides,
    get_unit_display_overrides,
    load_faction_rules_fr,
)
from .sources.generic_core_abilities import (
    CORE_RULES_SOURCE,
    DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE,
    load_generic_core_abilities,
)
from .sources.roster_simplifications import load_roster_simplifications
from .sources.season_rules import DEFAULT_SEASON_RULES_EN_FILE, load_season_rules
from .sources.tactic_cards import DEFAULT_TACTIC_CARDS_EN_FILE, load_tactic_cards
from .sources.wahapedia_lookup import (
    AbilityEntry,
    RegimentOfRenownData,
    WarscrollData,
    load_wahapedia,
    tag_ability_origin,
)
from .sources.warscroll_index import battletome_path, generic_manifestation_lores_path, load_index
from .split_pool import (
    _MINE_ONLY_KEYS,
    _PAID_OPTION_RE,
    _apply_choice_clusters,
    _apply_display_fr,
    _apply_section_order,
    _apply_unit_aliases,
    _collapse_alias_pills,
    _drop_enemy_charge_reroll,
    _drop_identical_alias_cards,
    _fold_warscroll_copies,
    _mark_self_profile,
    _merge_unit_keywords,
    _order_deploy,
    _relabel_options,
    _tactic_special_rules,
    _turn_sides,
    _warscroll_ability_pool,
    _with_section,
)

#: Racine des PDF de roster générés sans `--out` explicite, rangés
#: `<équipe>/<liste>/<liste> (<mode>).pdf` (`default_output_path`) : toutes
#: les variantes d'une même liste côte à côte, sous le dossier de son équipe
#: — demande explicite de l'utilisateur. Distincte de
#: `scratch/output/best_unit/` (rapports pantheon/duels/coût de `reports/`),
#: l'autre moitié du même rangement.
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "scratch" / "output" / "roster"

#: Dossier des listes ; chaque sous-dossier direct est une équipe
#: (`Vae Victis Vernou/`, `Melusior/`, ...) dont le nom est repris en sortie.
DEFAULT_LISTS_DIR = Path(__file__).resolve().parents[3] / "data" / "Proposition de listes"


@dataclass(frozen=True)
class RosterPdfResult:
    output_path: Path
    units_matched: list[str]
    units_unmatched: list[str]
    rules_included: list[str] = field(default_factory=list)
    rules_unmatched: list[str] = field(default_factory=list)
    wahapedia_used: list[str] = field(default_factory=list)
    #: `*-split-simple` : la version avec les cartes de scénario à la fin
    scenario_output_path: Path | None = None
    #: `*-split-simple` : aptitudes qui citent une unité absente de la liste
    #: (`resolution.absent_references`) — à proposer au joueur (principe 7)
    absent_references: list = field(default_factory=list)
    #: `*-split-simple` : aptitudes visant des unités amies d'un type
    #: (Infanterie, Cavalerie…) qu'aucune unité de la liste ne porte
    absent_keywords: list = field(default_factory=list)
    #: modes split : aptitudes de chaque carte de tour (« deploy », « any »,
    #: « mine », « enemy ») et celles restées sur les cartes d'unité
    #: (« warscrolls ») — mêmes entrées que le PDF, pour l'analyse des listes
    #: (`aospy l3 export-lists`), pas lu par le rendu.
    ability_cards: dict = field(default_factory=dict)


def default_output_path(
    list_path: str | Path,
    mode: RosterMode,
    lists_dir: str | Path = DEFAULT_LISTS_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Chemin de sortie par défaut : `<output_dir>/<équipe>/<liste>/<liste> (<mode>).pdf`.

    L'équipe est le premier sous-dossier de `lists_dir` contenant la liste ;
    une liste hors de `lists_dir` (ou posée à sa racine) n'a pas de dossier
    d'équipe et va directement sous `<output_dir>/<liste>/`.
    """
    list_path = Path(list_path).resolve()
    out_dir = Path(output_dir)
    try:
        rel = list_path.relative_to(Path(lists_dir).resolve())
    except ValueError:
        rel = None
    if rel is not None and len(rel.parts) > 1:
        out_dir = out_dir / rel.parts[0]
    stem = list_path.stem.strip()
    return out_dir / stem / f"{stem} ({mode_spec(mode).file_label}).pdf"


def compact_renown(parsed, wh):
    """Export compact « Faction | X » : X arrive dans `allegiance` (place de la formation). Si X est une Armée
    de Renom et qu'aucune formation de base ne porte ce nom (Sylvaneth « Lords of the Clan » est les deux : la
    formation l'emporte), la liste est ramenée à la forme complète « Faction | AoR », sans formation — même
    règle que l'analyse de liste (`analysis/layers/listing.py::collect`)."""
    if not (wh.available and parsed.allegiance) or "|" in parsed.faction:
        return parsed
    aor_name = parsed.allegiance.split("(", 1)[0].strip()
    if wh.find_renown_army_rules(aor_name) and not wh.find_faction_category(
        parsed.base_faction, "Battle Formations", parsed.allegiance
    ):
        return _dc_replace(parsed, faction=f"{parsed.faction} | {aor_name}", allegiance=None)
    return parsed


def build_roster_pdf(
    list_path: str | Path,
    out_path: str | Path | None = None,
    index_path: str | Path | None = None,
    battletome_dir: str | Path | None = None,
    wahapedia_dir: str | Path | None = None,
    mode: RosterMode = "hybrid",
    faction_rules_fr_path: str | Path | None = None,
    generic_core_abilities_path: str | Path | None = None,
) -> RosterPdfResult:
    # options de rendu et relevé des pastilles (`render/options.py`) propres
    # à ce PDF : rien ne fuit vers le suivant
    with render_session():
        return _build_roster_pdf(
            list_path,
            out_path,
            index_path,
            battletome_dir,
            wahapedia_dir,
            mode,
            faction_rules_fr_path,
            generic_core_abilities_path,
        )


def _build_roster_pdf(
    list_path: str | Path,
    out_path: str | Path | None = None,
    index_path: str | Path | None = None,
    battletome_dir: str | Path | None = None,
    wahapedia_dir: str | Path | None = None,
    mode: RosterMode = "hybrid",
    faction_rules_fr_path: str | Path | None = None,
    generic_core_abilities_path: str | Path | None = None,
) -> RosterPdfResult:
    spec = mode_spec(mode)
    list_path = Path(list_path)
    parsed = parse_list_file(list_path)
    # `fr-split-simple` : simplifications propres à cette liste (cf.
    # `roster_simplifications.py`) — aptitudes de synthèse ajoutées à leur
    # unité, aptitudes qu'elles résument retirées partout (warscrolls,
    # optimisations, règles de faction, manifestations).
    simplifications = (
        load_roster_simplifications(list_path.stem.strip(), lang="en" if spec.english else "fr")
        if spec.simple
        else None
    )
    parsed, alias_sources = _apply_unit_aliases(parsed, simplifications)
    index = load_index(index_path) if index_path is not None else load_index()
    # Fichier vide (`{"factions": {}}`) tant qu'aucune faction n'est curée —
    # lecture à froid sans coût notable, inutile de la conditionner à `mode`
    # (`_fr_patch` ignore `frf` lui-même hors `fr`/`fr-extended`). Même
    # convention `*_path` optionnel que `index_path`, pour les tests.
    frf = load_faction_rules_fr(faction_rules_fr_path) if faction_rules_fr_path is not None else load_faction_rules_fr()
    if spec.english:
        # textes officiels anglais de l'app (même schéma que le français),
        # prioritaires sur Wahapedia
        frf = load_faction_rules_fr(DEFAULT_APP_RULES_EN_FILE)
    faction_index = index.factions.get(parsed.base_faction)
    bt_path = (
        battletome_path(index, parsed.base_faction, battletome_dir)
        if battletome_dir is not None
        else battletome_path(index, parsed.base_faction)
    )
    wh = load_wahapedia(wahapedia_dir) if wahapedia_dir is not None else load_wahapedia()
    # une seule fois par PDF, pour tout le rendu (cf. `render/options.py`)
    update_render_options(
        faction_keywords=wh.faction_specific_keywords() if wh.available else frozenset(),
        french_keywords=spec.french,
        bold_set_up=spec.french or spec.simple,
        french_weapon_tags=spec.french_names,
        english_labels=spec.english,
    )
    english = spec.english
    tactic_cards = load_tactic_cards(en_path=DEFAULT_TACTIC_CARDS_EN_FILE if english else None)
    parsed = compact_renown(parsed, wh)
    renown_prefix = parsed.faction.split("|", 1)[1].strip() if "|" in parsed.faction else None

    # Profils d'unité : rendus en carte maison (render/) à partir
    # de data/wahapedia/*.csv plutôt que copiés depuis le battletome — cf.
    # demande explicite de remplacer les pages PDF par les cartes pour les
    # unités. Wahapedia couvre la totalité du contenu AoS4 (bien plus large
    # que les 2 battletomes actuellement indexés en français), donc plus de
    # repli sur `find_pages`/copie de page pour une unité : introuvable ici
    # = réellement non trouvé, signalé comme tel plutôt que masqué par un
    # rendu différent.
    matched: list[str] = []
    unmatched_units: list[str] = []
    warscrolls_by_name: dict[str, WarscrollData] = {}
    wahapedia_used: list[str] = []
    for name in parsed.unique_unit_names():
        # `prefer_faction` : certaines unités d'armée de renom (ex.
        # "Bloodletters" pour "Legion of the First Prince") existent sous 2
        # lignes Wahapedia homonymes — la version de base (autre faction,
        # sans restriction) et une variante `parsed.base_faction`-only
        # ("This unit can only be taken in a <armée de renom> Army of
        # Renown", stats différentes) — sans indice de faction,
        # `find_warscroll` retombait sur la première ligne du CSV (la
        # version de base, erronée ici), signalé par l'utilisateur.
        ws = (
            wh.find_warscroll(alias_sources.get(name, name), prefer_faction=parsed.base_faction)
            if wh.available
            else None
        )
        if ws is None and wh.available and renown_prefix and name.startswith(renown_prefix):
            # les unités d'une armée de renom sont listées préfixées par son
            # nom (ex. "Legion of the First Prince Bloodletters") mais leur
            # warscroll Wahapedia est enregistré sous son nom nu ("Bloodletters").
            ws = wh.find_warscroll(name[len(renown_prefix) :].strip(), prefer_faction=parsed.base_faction)
        if ws is not None:
            warscrolls_by_name[name] = ws
            matched.append(name)
        else:
            unmatched_units.append(name)

    # Aptitudes propres à chaque unité : correctifs/additions vérbatim
    # français (`data/json/faction_rules_fr.json`, cf. `faction_rules_fr.py`) —
    # uniquement en `fr`/`fr-extended` (`_fr_patch` renvoie `entries` tel
    # quel sinon), une unité non curée gardant ses aptitudes Wahapedia (EN)
    # inchangées.
    if mode_spec(mode).curated_patch:
        for name, ws in list(warscrolls_by_name.items()):
            # Curé sous la faction PROPRE du warscroll résolu (`ws.faction_id`),
            # pas `parsed.base_faction` : une unité amenée par un Régiment de
            # Renom (ex. Skarbrand/Slaughterpriest/Bloodreavers/Skullreapers
            # via un Régiment Blades of Khorne cité par une liste Slaves to
            # Darkness) est curée sous sa faction d'origine, jamais sous celle
            # de la liste qui la cite — même raisonnement que la résolution du
            # Régiment de Renom lui-même ci-dessus. Repli sur `parsed.base_faction`
            # si `faction_id` n'est pas résolu (id manquant/inconnu), identique
            # au comportement précédent pour toute unité native de la liste.
            unit_faction = wh.faction_name(ws.faction_id) or parsed.base_faction
            ws = _mark_self_profile(ws)
            overrides = get_unit_ability_overrides(frf, unit_faction, name, ws.name)
            if overrides:
                ws = _dc_replace(ws, abilities=apply_fr_overrides(ws.abilities, overrides))
            warscrolls_by_name[name] = _apply_display_fr(
                ws, get_unit_display_overrides(frf, unit_faction, name, ws.name)
            )
    elif mode_spec(mode).french_names:
        # `hybrid` : noms seulement (sous-titre français, armes françaises),
        # le texte des aptitudes reste celui de Wahapedia.
        for name, ws in list(warscrolls_by_name.items()):
            unit_faction = wh.faction_name(ws.faction_id) or parsed.base_faction
            warscrolls_by_name[name] = _apply_display_fr(
                ws, get_unit_display_overrides(frf, unit_faction, name, ws.name)
            )

    # Armée de Renom : ses propres règles (Faction_abilities.csv, groupées
    # par catégorie) remplacent tout ou partie de celles de la faction de
    # base — calculé *avant* `resolve_rules` pour pouvoir lui passer les
    # catégories à omettre côté battletome (cf. `_AOR_REPLACES`).
    renown_army: tuple[str, dict[str, list[AbilityEntry]]] | None = None
    renown_categories: frozenset[str] = frozenset()
    if renown_prefix and wh.available:
        grouped = wh.find_renown_army_rules(renown_prefix)
        if grouped:
            renown_army = (renown_prefix, grouped)
            renown_categories = frozenset(grouped)

    (
        battletome_rules,
        generic_manifestation_sections,
        tactic_sections,
        wahapedia_lore_blocks,
        rules_unmatched,
        lore_wahapedia_used,
        rule_card_labels,
        rule_ability_pool,
        manifestation_warscrolls,
    ) = resolve_rules(
        parsed,
        faction_index,
        index,
        wh,
        tactic_cards,
        renown_categories,
        mode=mode,
        frf=frf,
        renown_army=renown_army,
        tactic_card_width=_TACTIC_CARD_WIDTH,
    )
    wahapedia_used.extend(lore_wahapedia_used)

    if renown_army is not None:
        renown_name = renown_army[0]
        if f"Armée de Renom — {renown_name}" in rule_card_labels:
            # curation vérbatim française complète (`_renown_army_pool`,
            # `fr`/`fr-extended` seulement) : déjà rendu sur la carte de
            # règles fusionnée par `resolve_rules`, ne doit plus apparaître
            # dans l'annexe anglaise ni y être rattaché par l'appelant.
            renown_army = None
        else:
            wahapedia_used.append(f"{renown_name} — Army of Renown Rules (EN, Wahapedia)")
        if "Spell Lore" in renown_categories and any(u.startswith("Domaine de sorts") for u in rules_unmatched):
            rules_unmatched = [u for u in rules_unmatched if not u.startswith("Domaine de sorts")]

    # Un Régiment de Renom natif d'une faction (PDF officiel propre, cf.
    # `faction_rules_fr.py`) peut avoir ses aptitudes vérbatim françaises
    # (`get_regiment_of_renown_overrides`, `fr`/`fr-extended` seulement) —
    # appliquées ici, *avant* le partage single/grouped ci-dessous, pour que
    # les deux chemins (aptitude repliée sur une unité, ou pool fusionné)
    # héritent du texte déjà patché sans double logique. `regiment_curated`
    # retient quels régiments l'ont reçu, pour ne compter ni dans
    # `wahapedia_used` (pas un repli anglais) ni dans l'annexe Wahapedia.
    regiments_of_renown: list[tuple[str, RegimentOfRenownData | None]] = []
    regiment_curated: set[str] = set()
    for ror in parsed.regiments_of_renown:
        ror_data = wh.find_regiment_of_renown(ror.name) if wh.available else None
        if ror_data is not None:
            if mode_spec(mode).curated_patch:
                # Curé sous la faction d'ORIGINE du Régiment de Renom
                # (`RegimentOfRenownData.faction_id`), pas `parsed.base_faction`
                # (la faction de la liste qui le cite) : plusieurs Régiments
                # (ex. Blades of Khorne "The Exiled One"/"The Red Revelation")
                # sont explicitement exclus de leur propre liste d'inclusion
                # (Wahapedia `Warscrolls_RoRfactions.csv`) — seules d'autres
                # factions Chaos peuvent les citer, donc `parsed.base_faction`
                # ne correspondrait jamais à la clé sous laquelle ce Régiment
                # est curé. Repli sur `parsed.base_faction` si la faction
                # d'origine n'est pas résolue (id manquant/inconnu).
                origin_faction = wh.faction_name(ror_data.faction_id) or parsed.base_faction
                overrides = get_regiment_of_renown_overrides(frf, origin_faction, ror_data.name)
                if overrides:
                    ror_data = _dc_replace(ror_data, abilities=apply_fr_overrides(ror_data.abilities, overrides))
                    regiment_curated.add(ror.name)
            if ror.name not in regiment_curated:
                wahapedia_used.append(f"Regiment of Renown : {ror.name} (EN, Wahapedia)")
        else:
            rules_unmatched.append(f"Regiment of Renown : {ror.name}")
        regiments_of_renown.append((ror.name, ror_data))

    # Un Regiment of Renown à une seule unité membre n'a rien de distinct de
    # cette unité pour le lecteur : son aptitude propre rejoint directement
    # sa carte (petite note de provenance + aptitude en plus) plutôt qu'une
    # section « Regiment of Renown » à part dans l'annexe. Un Régiment à
    # plusieurs membres curé en français (`regiment_curated`) rejoint le pool
    # d'aptitudes fusionné (`regiment_ability_pool`, badge d'origine dédié)
    # au lieu de l'annexe anglaise Wahapedia — seul un Régiment non curé (ou
    # curé mais résolu en mode `hybrid`/`en`) tombe encore dans
    # `grouped_regiments`.
    single_unit_ror_extras: dict[str, tuple[str, list[AbilityEntry]]] = {}
    grouped_regiments: list[tuple[str, RegimentOfRenownData | None]] = []
    regiment_ability_pool: list[AbilityEntry] = []
    for ror_name, ror_data in regiments_of_renown:
        member = _strip_all_tags(ror_data.composition[0]) if ror_data and len(ror_data.composition) == 1 else None
        if member is not None and member in warscrolls_by_name:
            single_unit_ror_extras[member] = (ror_name, ror_data.abilities)
        elif ror_name in regiment_curated:
            regiment_ability_pool.extend(tag_ability_origin(ror_data.abilities, f"Régiment de Renom : {ror_name}"))
        else:
            grouped_regiments.append((ror_name, ror_data))

    # Optimisations (Traits Héroïques/Artefacts de Pouvoir/Traits
    # Monstrueux/catégories saisonnières propres à la faction, ex. StD
    # "Brands of the Dark Gods"/"Ensorcelled Banners") : choisies une seule
    # fois pour toute la liste puis rattachées à une seule unité — jamais
    # montrées en bloc générique (cf. `resolve_rules`, qui marque désormais
    # `heroic_traits_artefacts` couvert sans jamais l'ajouter au pool), une
    # optimisation non choisie n'apparaissant nulle part, comme une unité non
    # choisie. Résolues par correspondance de nom sur les options ` • ... `
    # de chaque unité (`WahapediaLookup.find_unit_enhancement`) et rattachées
    # à sa carte plus bas — même mécanisme que l'aptitude d'un Regiment of
    # Renown à une seule unité membre (`single_unit_ror_extras` ci-dessus).
    unit_enhancements: dict[str, list[AbilityEntry]] = {}
    enhancements_included: list[str] = []
    attached_renown_enhancements: set[str] = set()
    if wh.available:
        # Correctifs vérbatim français pour cette catégorie (pas de `scope` —
        # toutes les optimisations de la faction, comme côté Wahapedia) :
        # récupérés une seule fois, appliqués ci-dessous par nom sur chaque
        # optimisation trouvée (même mécanisme que `_fr_patch`, appliqué ici
        # à une entrée unique plutôt qu'un pool entier).
        heroic_overrides = (
            get_faction_category_overrides(frf, parsed.base_faction, "heroic_traits_artefacts")
            if mode_spec(mode).curated_patch
            else []
        )
        # Optimisations propres à l'Armée de Renom (ex. DoK « Zainthar Kai »,
        # « Khaine's Inheritor ») : même correctif français que celles de la
        # faction de base, cherché sous `renown_armies.<nom>`, prioritaire
        # sur un homonyme de la faction de base (cf. plus bas). Une fois
        # rattachée à son porteur, elle est retirée du bassin de règles de
        # l'armée de renom (`attached_renown_enhancements`), sans quoi elle
        # y figurerait une 2e fois.
        renown_heroic_overrides = (
            get_renown_army_overrides(frf, parsed.base_faction, renown_prefix, "heroic_traits_artefacts")
            if renown_prefix and mode_spec(mode).curated_patch
            else []
        )
        heroic_overrides = heroic_overrides + renown_heroic_overrides
        renown_heroic_keys = {ability_join_key(o.get("wahapedia_name")) for o in renown_heroic_overrides}
        # Cf. `find_pledge_battle_trait` : unités StD qui commencent la
        # bataille déjà marquées (Prince Démon, porteur de Bannière
        # Ensorcelée) — la Trait de Bataille "Voué à <Dieu>" correspondante
        # leur est rattachée en plus, ci-dessous après la boucle.
        pledged_gods: dict[str, set[str]] = {}
        for regiment in parsed.regiments:
            for unit in regiment.units:
                if unit.name not in warscrolls_by_name:
                    continue
                for option in unit.options:
                    match = wh.find_unit_enhancement(parsed.base_faction, option)
                    if match is not None:
                        label, entry = match
                        entry_name = entry.name.strip().upper()
                        if heroic_overrides:
                            matching = [
                                o
                                for o in heroic_overrides
                                if ability_join_key(o.get("wahapedia_name")) == ability_join_key(entry_name)
                            ]
                            if matching:
                                if ability_join_key(entry_name) in renown_heroic_keys:
                                    # l'armée de renom l'emporte sur un homonyme de la faction de base
                                    matching = [o for o in matching if o in renown_heroic_overrides]
                                    entry = apply_fr_overrides([entry], matching)[0]
                                    attached_renown_enhancements.add(entry.name)
                                else:
                                    entry = apply_fr_overrides([entry], matching)[0]
                        unit_enhancements.setdefault(unit.name, []).extend(tag_ability_origin([entry], label))
                        enhancements_included.append(f"{label} : {entry.name} → {unit.name}")
                        god = _BANNER_PLEDGED_GOD.get(entry_name)
                        if god:
                            pledged_gods.setdefault(unit.name, set()).add(god)
                        continue
                    pledge_match = _PLEDGE_OPTION_RE.search(option)
                    if pledge_match:
                        pledged_gods.setdefault(unit.name, set()).add(pledge_match.group(1).upper())
        for unit_name, gods in pledged_gods.items():
            for god in sorted(gods):
                pledge_entry = find_pledge_battle_trait(wh, frf, parsed.base_faction, mode, god)
                if pledge_entry is None:
                    continue
                unit_enhancements.setdefault(unit_name, []).extend(
                    tag_ability_origin([pledge_entry], "Trait de Bataille")
                )
                enhancements_included.append(f"Trait de Bataille : {pledge_entry.name} → {unit_name}")
    if attached_renown_enhancements:
        rule_ability_pool = [ab for ab in rule_ability_pool if ab.name not in attached_renown_enhancements]

    # options payantes (« Brand of Unbreakable Bonds - (10) Points ») :
    # la carte affiche « base+N pts » (demande de l'utilisateur), le prix
    # Wahapedia ne les comptant pas.
    paid_options: dict[str, int] = {}
    for regiment in parsed.regiments:
        for unit in regiment.units:
            cost = sum(int(m.group(1)) for opt in unit.options if (m := _PAID_OPTION_RE.search(opt)))
            if cost:
                paid_options.setdefault(unit.name, cost)

    warscrolls_for_cards: list[WarscrollData] = []
    regiment_notes: dict[str, str] = {}
    for name in matched:
        ws = warscrolls_by_name[name]
        if name in alias_sources:
            # carte et pastilles d'unité sous le nom affiché, le nom du
            # warscroll en sous-titre
            ws = _dc_replace(ws, name=name, subtitle=ws.name)
        if name in paid_options and ws.points:
            ws = _dc_replace(ws, points=f"{ws.points}+{paid_options[name]}")
        extras = list(unit_enhancements.get(name, []))
        if simplifications is not None:
            extras += simplifications.unit_abilities.get(name, [])
        if name in single_unit_ror_extras:
            ror_name, ror_extras = single_unit_ror_extras[name]
            extras += ror_extras
            regiment_notes[ws.name] = f"Regiment of Renown — {ror_name}"
        if extras:
            ws = _dc_replace(ws, abilities=list(ws.abilities) + extras)
        if simplifications is not None:
            ws = _dc_replace(
                ws,
                abilities=[simplifications.rewrite_unit(name, ab) for ab in ws.abilities],
                keywords=_merge_unit_keywords(ws.keywords, simplifications.unit_keywords.get(name, ())),
                weapons=[
                    _dc_replace(w, **simplifications.unit_weapons.get(name, {}).get(w.name, {})) for w in ws.weapons
                ],
                **simplifications.unit_stats.get(name, {}),
            )
        warscrolls_for_cards.append(ws)
    # Ordre des cartes : Héros (toute base confondue) d'abord, puis
    # Infanterie/Cavalerie/Bêtes/Monstres/Machines de Guerre — demande
    # explicite de l'utilisateur ; tri stable, l'ordre relatif au sein d'un
    # même rang reste celui de la liste (régiment du général, puis régiment
    # 1, 2...). Cf. `_role_rank`.
    warscrolls_for_cards.sort(key=lambda ws: _role_rank(ws.role))
    if simplifications is not None and simplifications.warscroll_order:
        order = [ability_join_key(n) for n in simplifications.warscroll_order]
        warscrolls_for_cards.sort(
            key=lambda ws: order.index(ability_join_key(ws.name)) if ability_join_key(ws.name) in order else len(order),
        )
    # les manifestations invocables par le domaine choisi rejoignent la même
    # feuille de cartes, à la suite des unités de la liste — ce sont des
    # profils complets au même titre qu'une unité, juste optionnels/
    # invoqués en jeu plutôt que déployés d'entrée. Leurs aptitudes reçoivent
    # les mêmes correctifs vérbatim français que les unités de la liste
    # (`units.<manifestation>` de `faction_rules_fr.json`), cherchés sous la
    # faction propre du warscroll puis sous celle de la liste — une
    # manifestation partagée (ex. Foot of Gork, Mâchefers *et* Kruelboyz)
    # n'existe qu'en un exemplaire résolu par `find_warscroll`.
    if mode_spec(mode).curated_patch:
        patched_manifestations = []
        for ws in manifestation_warscrolls:
            ws = _mark_self_profile(ws)
            overrides = get_unit_ability_overrides(
                frf, wh.faction_name(ws.faction_id) or parsed.base_faction, ws.name
            ) or get_unit_ability_overrides(frf, parsed.base_faction, ws.name)
            if overrides:
                ws = _dc_replace(ws, abilities=apply_fr_overrides(ws.abilities, overrides))
            display = get_unit_display_overrides(
                frf, wh.faction_name(ws.faction_id) or parsed.base_faction, ws.name
            ) or get_unit_display_overrides(frf, parsed.base_faction, ws.name)
            patched_manifestations.append(_apply_display_fr(ws, display))
        manifestation_warscrolls = patched_manifestations
    elif mode_spec(mode).french_names:
        manifestation_warscrolls = [
            _apply_display_fr(
                ws,
                (
                    get_unit_display_overrides(frf, wh.faction_name(ws.faction_id) or parsed.base_faction, ws.name)
                    or get_unit_display_overrides(frf, parsed.base_faction, ws.name)
                ),
            )
            for ws in manifestation_warscrolls
        ]
    warscrolls_for_cards.extend(manifestation_warscrolls)
    if simplifications is not None:
        warscrolls_for_cards = [
            _dc_replace(
                ws, abilities=[simplifications.rewrite(ab) for ab in ws.abilities if not simplifications.is_removed(ab)]
            )
            for ws in warscrolls_for_cards
        ]
        rule_ability_pool = [
            simplifications.rewrite(ab) for ab in rule_ability_pool if not simplifications.is_removed(ab)
        ]
        regiment_ability_pool = [
            simplifications.rewrite(ab) for ab in regiment_ability_pool if not simplifications.is_removed(ab)
        ]

    # Règles de Saison 2026-27 / Aptitudes Génériques / règles de faction
    # (`rule_ability_pool`, déjà résolu par `resolve_rules`) rejoignent
    # toutes le *même* bassin puis une seule carte triée par bandeau de
    # phase — demande explicite de l'utilisateur : un joueur qui consulte
    # cette carte raisonne "je suis en phase des héros, qu'est-ce que j'ai le
    # droit de faire ?", pas par type de règle ; les séparer sur 3 cartes
    # (Saison / Générique / Faction, chacune déjà triée par phase en interne)
    # l'obligeait à vérifier 3 fois la même phase pour la même question.
    # `tag_ability_origin` pose un badge d'origine par source ("Saison"/
    # "MdG"/le nom de faction ou d'Armée de Renom) pour rester
    # identifiable malgré la fusion.
    #
    # Exception demandée par l'utilisateur pour Seraphon : "Le Grand
    # Dessein"/"Faites Avancer le Grand Dessein" choisissent/activent les 4
    # Astérismes (mot-clé Wahapedia "Asterism"), qui ont chacun leur propre
    # `ability_phase` réel et finissent donc éparpillés sur plusieurs pages
    # de la grande carte fusionnée (trop de contenu Saison/MdG partage les
    # mêmes bandeaux "Déploiement"/"Début de round" pour que les 6 tiennent
    # ensemble sur une page, même avec le bandeau virtuel "asterism" de
    # `render/phases._PHASE_ORDER`). Plutôt que de retravailler le tri
    # partagé par *toute* carte fusionnée (régression potentielle pour
    # n'importe quelle autre faction), ces 6 aptitudes ("Traits de Bataille")
    # rejoignent leur propre petite carte à part (cf. `rule_cards` plus bas)
    # — assez courte pour tenir sur une seule page sans jamais se disputer
    # l'espace avec le reste. Déclenché uniquement par la présence du
    # mot-clé "Asterism" (propre à Seraphon) : aucun effet pour aucune autre
    # faction/liste.
    battle_traits_entries = [
        ab
        for ab in rule_ability_pool
        if any(kw.strip().lower() == "traits de bataille" for kw in (ab.keywords or "").split(","))
    ]
    separate_battle_traits_card = None
    if battle_traits_entries and any("asterism" in (ab.keywords or "").lower() for ab in rule_ability_pool):
        rule_ability_pool = [ab for ab in rule_ability_pool if ab not in battle_traits_entries]
        separate_battle_traits_card = render_rule_card(
            tr("Traits de Bataille"),
            battle_traits_entries,
            width=_RULE_CARD_WIDTH,
            subtitle=parsed.base_faction,
        )

    # `section` : sous-section de la carte en mode `fr-split` (règles de base
    # = Saison/MdG, règles d'armée = tout le reste hors warscrolls), cf.
    # `render/phases.ability_section` ; ignoré par les autres modes.
    combined_pool = _with_section(list(rule_ability_pool) + regiment_ability_pool, SECTION_ARMY)
    season_entries = load_season_rules(en_path=DEFAULT_SEASON_RULES_EN_FILE if english else None)
    if simplifications is not None:
        season_entries = [ab for ab in season_entries if not simplifications.is_removed(ab)]
    # les Aptitudes Génériques (plus bas) s'insèrent ici, *avant* la Saison :
    # dans un bandeau, les règles de base du jeu (ex. « Placez le Champ de
    # Bataille », en tête du Déploiement) précèdent celles de la saison.
    generic_insert_at = len(combined_pool)
    if season_entries:
        # « Saison » dit que la règle change chaque saison ; sa source (badge
        # source, cf. `render/pills._TEXT_SOURCE_KEYWORDS`) est le MdG
        combined_pool.extend(
            _with_section(
                tag_ability_origin(tag_ability_origin(season_entries, "Saison"), "MdG"),
                SECTION_BASE,
            )
        )

    # Aptitudes Génériques (modes `fr-extended`/`fr-split`) : superset complet
    # de `MdG26-27 Aptitudes.pdf`, pas seulement les 4 règles de saison — cf.
    # `generic_core_abilities.py`. Fichier vide tant que non curé (liste
    # vide, pas d'erreur) : le mode se comporte alors comme `fr` sans rien
    # ajouter au bassin. `fr-split` les inclut aussi : son objet est de
    # répondre à « qu'ai-je le droit de faire dans cette phase de ce tour ? »,
    # aptitudes de base du jeu comprises (ex. Redéploiement en phase de
    # mouvement adverse).
    # « Musicien »/« Porte-Étendard »/« Champion » n'y restent que si une unité de la
    # liste en a (`requires_unit_keyword`, cf. `generic_core_abilities.py`).
    generic_entries: list[AbilityEntry] = []
    if mode_spec(mode).extended:
        unit_keywords = frozenset(kw.strip().upper() for ws in warscrolls_by_name.values() for kw in ws.keywords)
        # `en-split-simple` : verbatim Core Rules anglais par-dessus (cf.
        # `generic_core_abilities.py`), le français reste pour le reste.
        en_path = DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE if english else None
        generic_entries = (
            load_generic_core_abilities(generic_core_abilities_path, unit_keywords=unit_keywords, en_path=en_path)
            if generic_core_abilities_path is not None
            else load_generic_core_abilities(unit_keywords=unit_keywords, en_path=en_path)
        )
        if simplifications is not None:
            generic_entries = [ab for ab in generic_entries if not simplifications.is_removed(ab)]
        if generic_entries:
            # source « MdG » sauf pour celles déjà sourcées « Core Rules »
            generic_tagged = _with_section(
                [
                    ab if CORE_RULES_SOURCE.lower() in ab.keywords.lower() else tag_ability_origin([ab], "MdG")[0]
                    for ab in generic_entries
                ],
                SECTION_BASE,
            )
            # les règles de saison du Déploiement (ex. « Souffler sur les
            # Braises ») suivent directement « Placez le Champ de Bataille »,
            # qui désigne attaquant et défenseur dont elles dépendent (demande
            # de l'utilisateur), plutôt que la fin des aptitudes génériques.
            anchor = next(
                (
                    i + 1
                    for i, ab in enumerate(generic_tagged)
                    if ab.name in ("Placez le Champ de Bataille", "Set Up the Battlefield")
                ),
                None,
            )
            if anchor is not None:
                season_tail = combined_pool[generic_insert_at:]
                season_deploy = [ab for ab in season_tail if ab.ability_phase == "Deployment Phase"]
                combined_pool[generic_insert_at:] = [ab for ab in season_tail if ab not in season_deploy]
                generic_tagged[anchor:anchor] = season_deploy
            combined_pool[generic_insert_at:generic_insert_at] = generic_tagged

    combined_pool.extend(
        _with_section(
            tag_ability_origin(tag_ability_origin(_tactic_special_rules(parsed, tactic_cards), "Tactique"), "MdG"),
            SECTION_BASE,
        )
    )

    # Mode `fr-split` : les aptitudes des warscrolls quittent leur carte
    # d'unité (qui ne garde que stats + armes + mots-clés) pour rejoindre le
    # bassin de règles, chacune marquée du nom de son/ses warscroll(s)
    # (`_warscroll_ability_pool`), puis tout le bassin est réparti en 3
    # cartes « Déploiement » / « Mon tour » / « Tour adverse »
    # (`ability_turn_sides`) — une aptitude utilisable dans les 2 tours
    # figure sur les 2 cartes de tour. Chaque carte démarre sur sa propre page
    # (`_build_rule_cards_pdf` séparé), bandeaux dans l'ordre
    # `SPLIT_PHASE_ORDER`. « N'importe quelle phase » (vert) a sa propre
    # carte, juste après « Déploiement », plutôt que d'être dupliqué sur les
    # 2 cartes de tour (demande explicite de l'utilisateur). Les cartes de tactique de bataille rejoignent « Mon tour »,
    # juste après son dernier bandeau « Fin de tour » (moment où l'on marque
    # leurs points) — demande explicite de l'utilisateur ; elles ne sont
    # alors plus ajoutées en section séparée plus bas. Sur la même page que
    # « Fin de tour » dès que possible, quitte à être légèrement réduites
    # (`_TACTIC_MIN_SCALE`).
    rule_card_groups: list[tuple[str | None, list]] = []
    ability_cards: dict[str, list[AbilityEntry]] = {}
    tactics_in_turn_card = False
    if mode_spec(mode).split:
        # `fr-split-simple` : certaines aptitudes restent sur leur carte de
        # warscroll (`RosterSimplifications.keep_on_warscroll`).
        def kept(ab: AbilityEntry) -> bool:
            return simplifications is not None and simplifications.keeps_on_warscroll(ab)

        full_pool = combined_pool + _warscroll_ability_pool(
            [_dc_replace(ws, abilities=[ab for ab in ws.abilities if not kept(ab)]) for ws in warscrolls_for_cards]
        )
        full_pool = _collapse_alias_pills(full_pool, alias_sources)
        if simplifications is not None:
            # règles de base/saison, ajoutées au bassin après le premier
            # passage (cf. plus haut) : badges `all_lists` (« Simple »...)
            full_pool = [simplifications.rewrite(ab) for ab in full_pool]
            full_pool = simplifications.merge(full_pool)
        full_pool = _apply_choice_clusters(_fold_warscroll_copies(full_pool), mode)
        if simplifications is not None:
            full_pool = simplifications.expand_phases(
                full_pool,
                lambda ab: ab.ability_category in CHOICE_CATEGORIES,
            )
            full_pool = _apply_section_order(full_pool, simplifications.section_order)
        warscrolls_for_cards = [
            _dc_replace(
                ws,
                abilities=[
                    ab for ab in ws.abilities if kept(ab) or is_self_profile_modifier(ab, [w.name for w in ws.weapons])
                ],
            )
            for ws in warscrolls_for_cards
        ]
        warscrolls_for_cards = _drop_identical_alias_cards(warscrolls_for_cards, alias_sources)
        if separate_battle_traits_card is not None:
            rule_card_groups.append((None, [separate_battle_traits_card]))

        def turn_card(title: str, abilities: list[AbilityEntry]):
            return render_rule_card(
                title,
                abilities,
                width=_RULE_CARD_WIDTH,
                subtitle=parsed.base_faction,
                phase_order=SPLIT_PHASE_ORDER,
                hide_turn_qualifier=True,
                sectioned=True,
                base_last=simplifications is not None and simplifications.base_rules_last,
            )

        deploy = [ab for ab in full_pool if classify_phase(ab) == "deploy"]
        deploy = _order_deploy(deploy)
        any_phase = [ab for ab in full_pool if classify_phase(ab) == "any"]
        in_turn = _order_deploy([ab for ab in full_pool if classify_phase(ab) not in ("deploy", "any")])
        mine = [ab for ab in in_turn if TURN_MINE in _turn_sides(ab, in_turn)]
        enemy = _drop_enemy_charge_reroll(
            [
                ab
                for ab in in_turn
                if TURN_ENEMY in _turn_sides(ab, in_turn) and ability_join_key(ab.name) not in _MINE_ONLY_KEYS
            ]
        )
        ability_cards = {
            "deploy": deploy,
            "any": any_phase,
            "mine": mine,
            "enemy": enemy,
            "warscrolls": [
                _dc_replace(ab, warscrolls=(ws.name,)) for ws in warscrolls_for_cards for ab in ws.abilities
            ],
            "battle_traits": battle_traits_entries if separate_battle_traits_card is not None else [],
        }

        # « N'importe quelle phase » : sa propre carte (demande de
        # l'utilisateur), à la suite de « Déploiement » sur les mêmes pages.
        rule_card_groups.append(
            (
                None,
                [
                    turn_card(tr("Déploiement"), deploy),
                    turn_card(tr("N'importe quelle phase"), any_phase),
                ],
            )
        )
        rule_card_groups.append(
            (
                tr("Mon tour"),
                [
                    turn_card(tr("Mon tour"), mine),
                    _tactic_cards_block(
                        [flowable for _label, flowable in tactic_sections], min_scale=_TACTIC_MIN_SCALE
                    ),
                ],
            )
        )
        rule_card_groups.append((tr("Tour de l'adversaire"), [turn_card(tr("Tour adverse"), enemy)]))
        rule_card_groups = [(label, [c for c in group if c is not None]) for label, group in rule_card_groups]
        tactics_in_turn_card = True
    else:
        rule_cards: list = []
        if separate_battle_traits_card is not None:
            rule_cards.append(separate_battle_traits_card)
        combined_pool = _apply_choice_clusters(combined_pool, mode)
        if mode_spec(mode).extended:  # `fr-extended` (seul mode étendu hors split)
            combined_pool = _order_deploy(combined_pool)
        if combined_pool:
            # même rendu sectionné que les cartes du mode `fr-split` (en-tête
            # horizontal et espace entre bandeaux de phase, sous-sections
            # Règles de base / Règles d'armée / Sorts..., « (suite) » après une
            # coupe de page), « N'importe quelle phase » (vert) juste après
            # le Déploiement (`SPLIT_PHASE_ORDER`) — demande de l'utilisateur ;
            # la carte reste unique, pastilles de tour comprises.
            rule_cards.append(
                render_rule_card(
                    tr("Aptitudes"),
                    combined_pool,
                    width=_RULE_CARD_WIDTH,
                    subtitle=parsed.base_faction,
                    phase_order=SPLIT_PHASE_ORDER,
                    sectioned=True,
                )
            )
        rule_card_groups.append((None, rule_cards))

    rules_included = (
        (["Règles de Saison 2026-27"] if season_entries else [])
        + (["Aptitudes Génériques — MdG26-27"] if generic_entries else [])
        + rule_card_labels
        + [label for label, _pages in battletome_rules]
        + [label for label, _pages in generic_manifestation_sections]
        + [label for label, _flowable in tactic_sections]
        + [label for label, _entries in wahapedia_lore_blocks]
        + enhancements_included
        + ([f"{renown_army[0]} — Army of Renown Rules"] if renown_army else [])
        + [
            f"Régiment de Renom : {name} (FR)" if name in regiment_curated else f"Regiment of Renown : {name}"
            for name, data in regiments_of_renown
            if data is not None
        ]
    )

    # Chaque section est rendue avant la couverture, qui légende les pictos
    # réellement dessinés (`drawn_badge_shapes`).
    reset_drawn_badge_shapes()
    rule_cards_bytes_by_group = [
        (page_label, _build_rule_cards_pdf(rule_cards, page_label=page_label, label_margin=not mode_spec(mode).split))
        for page_label, rule_cards in rule_card_groups
    ]
    tactic_cards_bytes = (
        None if tactics_in_turn_card else _build_tactic_cards_pdf([flowable for _label, flowable in tactic_sections])
    )
    cards_bytes = _build_warscroll_cards_pdf(warscrolls_for_cards, regiment_notes)
    appendix_bytes = _build_wahapedia_appendix_pdf(
        wahapedia_lore_blocks,
        renown_army,
        grouped_regiments,
    )

    writer = PdfWriter()
    cover = _build_cover_pdf(
        _relabel_options(parsed, simplifications),
        unmatched_units,
        rules_unmatched,
        wahapedia_used,
        badge_shapes=drawn_badge_shapes(),
    )
    for page in PdfReader(BytesIO(cover)).pages:
        writer.add_page(page)

    # Les warscrolls, consultés le plus souvent, juste après la liste, dans
    # tous les modes (demande de l'utilisateur) ; en mode split, ils sont en
    # plus recopiés en tête de la section « Tour de l'adversaire » (recto),
    # pour que chaque moitié du livret imprimé ait ses chartes.
    if cards_bytes is not None:
        for page in PdfReader(BytesIO(cards_bytes)).pages:
            writer.add_page(page)

    for page_label, rule_cards_bytes in rule_cards_bytes_by_group:
        if rule_cards_bytes is not None:
            if mode_spec(mode).split and page_label == tr("Tour de l'adversaire"):
                _pad_to_odd_page(writer)
                if cards_bytes is not None:
                    for page in PdfReader(BytesIO(cards_bytes)).pages:
                        writer.add_page(page)
            for page in PdfReader(BytesIO(rule_cards_bytes)).pages:
                writer.add_page(page)

    seen_battletome_pages: set[int] = set()
    if bt_path is not None and bt_path.exists():
        source_reader = PdfReader(str(bt_path))
        _append_pages(writer, source_reader, seen_battletome_pages, battletome_rules)

    gm_path = generic_manifestation_lores_path(index)
    if gm_path is not None and gm_path.exists() and generic_manifestation_sections:
        gm_reader = PdfReader(str(gm_path))
        _append_pages(writer, gm_reader, set(), generic_manifestation_sections)

    if tactic_cards_bytes is not None:
        for page in PdfReader(BytesIO(tactic_cards_bytes)).pages:
            writer.add_page(page)

    if appendix_bytes is not None:
        for page in PdfReader(BytesIO(appendix_bytes)).pages:
            writer.add_page(page)

    # Chaque section (couverture, cartes de règle, cartes de tactique, cartes
    # de warscroll, annexe) est construite comme un mini-PDF `reportlab`
    # séparé (son propre `SimpleDocTemplate.build`), donc chacun réembarque
    # sa propre copie du fond `_STONE_TEXTURE` (~1,3 Mo) : `add_page` copie
    # ces pages telles quelles, sans dédoublonner un XObject par ailleurs
    # identique octet pour octet entre les pages. `compress_identical_objects`
    # fusionne ces objets par hash de contenu en un seul, partagé par toutes
    # les pages — le gain dominant, avant même la recompression des pages de
    # battletome copiées (`_compress_page_images`).
    _stamp_page_numbers(writer)
    writer.compress_identical_objects()

    if out_path is None:
        out_path = default_output_path(list_path, mode)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    # `*-split-simple` : une seconde version, même contenu + les 12 cartes de
    # scénario à la fin (demande de l'utilisateur), à côté de la première —
    # pages de scénario non numérotées (numéros déjà apposés).
    scenario_path = None
    if mode_spec(mode).simple and DEFAULT_SCENARIOS_FILE.exists():
        _append_scenario_pages(writer, DEFAULT_SCENARIOS_FILE)
        writer.compress_identical_objects()
        scenario_path = scenario_variant_path(out_path)
        with open(scenario_path, "wb") as f:
            writer.write(f)

    return RosterPdfResult(
        scenario_output_path=scenario_path,
        absent_references=find_absent_references(parsed) if mode_spec(mode).simple else [],
        absent_keywords=find_absent_keywords(parsed) if mode_spec(mode).simple else [],
        output_path=out_path,
        units_matched=matched,
        units_unmatched=unmatched_units,
        rules_included=rules_included,
        rules_unmatched=rules_unmatched,
        wahapedia_used=wahapedia_used,
        ability_cards=ability_cards,
    )
