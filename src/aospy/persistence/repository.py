"""CRUD pour les armées, unités, armes, traits, artefacts et compositions.

Façade : le code vit dans `persistence/repo/` (une section par sous-module), réexporté ici tel quel pour ne
changer aucun appelant."""

# ruff: noqa: F401
from .repo._sql import (
    _insert_rows,
    _sql_literal,
)
from .repo.units import (
    _keywords_from_db,
    _keywords_to_db,
    _list_composition_entries,
    _list_weapons,
    _refresh_total_points,
    _unit_points,
    add_army,
    add_artefact,
    add_composition,
    add_composition_entry,
    add_heroic_trait,
    add_unit,
    add_weapon,
    bulk_add_armies,
    clone_composition,
    compute_total_points,
    delete_composition,
    delete_units_imported_before,
    get_army_by_name,
    get_artefact_by_name,
    get_composition,
    get_composition_by_name,
    get_heroic_trait_by_name,
    get_unit,
    get_unit_by_name,
    list_armies,
    list_artefacts,
    list_compositions,
    list_heroic_traits,
    list_units_for_army,
    load_all_units_with_weapons,
    remove_composition_entry,
    replace_unit,
)
from .repo.benchmarks import (
    _BENCH_COLS,
    _RANKING_POOL_QUERY,
    _fmt_bench_value,
    clear_benchmark_results,
    get_ranking_pool,
    save_benchmark_result,
    save_benchmark_results_many,
)
from .repo.abilities import (
    ABILITY_COLS,
    ABILITY_EFFECT_COLS,
    ABILITY_OWNER_COLS,
    ABILITY_REVIEW_CATEGORIES,
    ABILITY_TAG_COLS,
    _ABILITY_TABLES,
    ability_review_queue,
    ability_stats,
    get_ability_effects,
    replace_ability_analyses,
    search_abilities,
)
from .repo.analysis import (
    CHASSIS_COLS,
    duel_roi_by_unit,
    list_chassis,
    list_encounters,
    list_enhancement_bearers,
    list_marriage,
    list_realized,
    replace_ability_marriage,
    replace_chassis,
    replace_encounters,
    replace_enhancement_bearers,
    replace_realized,
)
