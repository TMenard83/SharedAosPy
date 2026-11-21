"""Façade de transition : réexporte les `cmd_*` des modules de commandes (un par groupe).

Le code vit désormais dans `cli/{db,unit,comp,battle,import_,cost,roster,ability,chassis,encounter}.py` ;
importer depuis ces modules plutôt que d'ici.
"""
# ruff: noqa: F401

from .ability import (cmd_ability_analyze, cmd_ability_review, cmd_ability_search, cmd_ability_show,
                      cmd_ability_stats, cmd_ability_tags)
from .battle import cmd_battle_simulate
from .chassis import cmd_chassis_build, cmd_chassis_list, cmd_chassis_show
from .common import _connect, _duel_rules, _resolve_army_id, _resolve_side, _side_options
from .comp import (cmd_comp_add_unit, cmd_comp_clone, cmd_comp_create, cmd_comp_delete, cmd_comp_list,
                   cmd_comp_remove_entry, cmd_comp_show)
from .cost import cmd_cost_fit, cmd_cost_residuals
from .db import cmd_army_list, cmd_init, cmd_reset
from .encounter import (cmd_encounter_bearers, cmd_encounter_best, cmd_encounter_build, cmd_encounter_list,
                        cmd_encounter_marriage)
from .import_ import (cmd_import_bsdata, cmd_import_bsdata_list, cmd_import_verify, cmd_import_wahapedia,
                      cmd_import_wahapedia_list)
from .roster import cmd_roster_analyze, cmd_roster_pdf
from .unit import cmd_unit_benchmark, cmd_unit_benchmark_all, cmd_unit_duel, cmd_unit_list, cmd_unit_stats
