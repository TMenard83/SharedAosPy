"""Duel et benchmark unité vs unité (sans passer par les compositions)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

import duckdb

from ..domain.models import Unit
from ..engine.combat import CombatModifiers, distribution_floor, expected_unit_damage, unit_damage_distribution
from ..persistence import repository
from .simulation import SideOptions

#: Mode de lecture du dégât d'un côté d'un duel : espérance brute, ou plancher
#: pessimiste à 66%/80%/95% de confiance — lu sur la distribution *exacte* des
#: dégâts (`engine/combat.py::unit_damage_distribution`/`distribution_floor`),
#: pas une approximation gaussienne (voir la docstring de `_attack_damage`).
DamageMode = Literal["mean", "floor66", "floor80", "floor95"]

#: Couverture (probabilité d'atteindre au moins le plancher) par mode `floorNN`.
_FLOOR_COVERAGE: dict[str, float] = {"floor66": 0.66, "floor80": 0.80, "floor95": 0.95}

#: Seuil de la règle optionnelle "seuil de charge" : le bonus intrinsèque
#: `Charge (+N <Stat>)` n'est actif que si le Move de l'attaquant dépasse
#: celui du défenseur de plus de 30 %.
CHARGE_MOVE_THRESHOLD_PCT = 0.3


@dataclass
class DuelRules:
    """Corpus de règles optionnelles pour un duel, indépendantes entre elles
    (désactivées par défaut — aucun changement de comportement si non demandées).

    - `double_shoot` : entre les deux unités du duel, celle qui a la plus
      petite portée à distance (0 si elle n'a aucune arme `ranged`) est réputée
      chargeuse — pas besoin de `SideOptions.charged`/`--charge`, c'est déduit
      des stats. Si son reach (`Move + charge_dist_in` [+ `run_dist_in` si
      `SideOptions.ran_and_charged`]) `< portée de l'arme à distance la plus
      longue de l'autre camp`, ce dernier voit son dégât à distance multiplié
      par `engine.combat.RANGED_DOUBLE_MULT` ce round (ses profils `ranged`
      uniquement, cf. `CombatModifiers.attacker_ranged_double`).
      Portées égales (y compris 0 des deux côtés) → aucun camp désigné, règle
      inactive pour cette paire.
    - `charge_move_threshold` : détermine à elle seule si l'attaquant est
      "chargé" (`attacker_charged`, qui gouverne le bonus `Charge (+N <Stat>)`
      d'une arme) — actif seulement si son Move dépasse celui du défenseur de
      plus de `CHARGE_MOVE_THRESHOLD_PCT`. Ne dépend pas de `SideOptions.charged`/
      `--charge` : pas besoin de déclarer une charge, elle est déduite du seul
      écart de Move (même logique de déduction par les stats que `double_shoot`).
    - `charge_dist_in`/`run_dist_in` : distances (pouces) utilisées par
      `double_shoot`, par défaut l'espérance des dés (2D6=7, 1D6=3.5).
    """
    double_shoot: bool = False
    charge_move_threshold: bool = False
    charge_dist_in: float = 7.0
    run_dist_in: float = 3.5


@dataclass
class DuelResult:
    """Résultat d'un duel unité A vs unité B (1 round). `mode_a`/`mode_b` peuvent
    différer : par exemple lire A→B au plancher pessimiste (dégât qu'on peut
    "garantir" en attaquant) et B→A à la moyenne (riposte "typique" plutôt que
    pire cas), un duel n'est donc pas nécessairement symétrique dans sa lecture."""
    attacker: Unit
    attacker_models: int
    attacker_reinforced: bool
    defender: Unit
    defender_models: int
    defender_reinforced: bool
    defender_army_name: str
    raw_a_to_b: float
    expected_a_to_b: float
    expected_models_killed_b: float
    raw_b_to_a: float
    expected_b_to_a: float
    expected_models_killed_a: float
    options_a: SideOptions
    options_b: SideOptions
    mode_a: DamageMode = "mean"
    mode_b: DamageMode = "mean"
    rules: DuelRules = field(default_factory=DuelRules)

    @property
    def attacker_total_hp(self) -> int:
        return self.attacker_models * self.attacker.health

    @property
    def defender_total_hp(self) -> int:
        return self.defender_models * self.defender.health

    @property
    def net(self) -> float:
        return self.expected_a_to_b - self.expected_b_to_a

    @property
    def pts_destroyed(self) -> float:
        """Valeur (en pts) détruite chez le défenseur."""
        if self.defender_total_hp == 0:
            return 0.0
        return self.expected_a_to_b / self.defender_total_hp * self.defender.points

    @property
    def pts_lost(self) -> float:
        """Valeur (en pts) perdue chez l'attaquant."""
        if self.attacker_total_hp == 0:
            return 0.0
        return self.expected_b_to_a / self.attacker_total_hp * self.attacker.points

    @property
    def pts_net(self) -> float:
        """Bilan en points : positif = trade rentable indépendamment de l'écart de coût."""
        return self.pts_destroyed - self.pts_lost

    @property
    def roi(self) -> float:
        """Return on investment : pts_net normalisé par le coût de l'attaquant."""
        if self.attacker.points == 0:
            return 0.0
        return self.pts_net / self.attacker.points


def _effective_models(unit: Unit, reinforced: bool) -> int:
    return unit.models * (2 if reinforced else 1)


def _mods(
    attacker: Unit, attacker_opts: SideOptions,
    defender: Unit, defender_opts: SideOptions,
    rules: DuelRules,
) -> CombatModifiers:
    """Modificateurs d'une direction d'attaque, règles optionnelles incluses.

    Symétrique par construction : pour A→B on appelle `_mods(attacker=A,
    attacker_opts=opts_a, defender=B, defender_opts=opts_b, ...)`, pour B→A on
    inverse les deux paires — même code des deux côtés, pas de cas particulier.

    `charge_move_threshold` : quand la règle est active, elle détermine à elle
    seule l'état chargé (`attacker_charged`, qui gouverne le bonus intrinsèque
    `Charge (+N <Stat>)`) — `Move(attaquant) > Move(défenseur) ×
    (1 + CHARGE_MOVE_THRESHOLD_PCT)` — sans tenir compte de `SideOptions.charged`
    ni de `--charge` : une charge n'est plus un choix déclaré, elle est déduite
    du seul écart de Move. Rule inactive → comportement de base inchangé,
    `attacker_charged` suit alors `SideOptions.charged`/`--charge` comme avant.

    `double_shoot` : contrairement à `charge_move_threshold`, ne dépend pas de
    `SideOptions.charged` — le camp qui charge est déduit des stats elles-mêmes
    : entre les deux unités du duel, celle qui a la plus petite portée à
    distance (0 si elle n'a aucune arme `ranged`) est forcément celle qui doit
    franchir la distance, donc celle qui charge. Ici, `attacker` tire dans
    cette direction et `defender` est le camp d'en face : si `attacker` a une
    portée strictement supérieure à celle de `defender`, `defender` est réputé
    chargeur et on compare son reach (Move + charge [+ course]) à la portée de
    `attacker`. Seuls les profils `ranged` de `attacker` sont concernés (géré
    dans `engine/combat.py`). En cas de portées égales (y compris 0 des deux
    côtés, mêlée pure), aucun camp n'est désigné chargeur : la règle ne
    s'applique pas.
    """
    attacker_charged = attacker_opts.charged
    if rules.charge_move_threshold:
        attacker_charged = attacker.move > defender.move * (1 + CHARGE_MOVE_THRESHOLD_PCT)

    ranged_double = False
    if rules.double_shoot:
        attacker_range = max((w.range_in for w in attacker.weapons if w.kind == "ranged"), default=0)
        defender_range = max((w.range_in for w in defender.weapons if w.kind == "ranged"), default=0)
        if attacker_range > defender_range:
            reach = defender.move + rules.charge_dist_in + (
                rules.run_dist_in if defender_opts.ran_and_charged else 0.0
            )
            ranged_double = reach < attacker_range

    return CombatModifiers(
        attacker_all_out_attack=attacker_opts.all_out_attack,
        attacker_charged=attacker_charged,
        defender_all_out_defense=defender_opts.all_out_defense,
        attacker_ranged_double=ranged_double,
    )


def _attack_damage(
    attacker: Unit, attacker_models: int, defender: Unit, modifiers: CombatModifiers,
    *, mode: DamageMode,
) -> float:
    """Dégât total d'une unité en 1 round, lu selon `mode` : espérance brute
    (`expected_unit_damage`), ou plancher pessimiste à 66%/80%/95% de confiance,
    lu *exactement* sur la distribution complète des dégâts
    (`unit_damage_distribution`/`distribution_floor`) plutôt qu'approximé par une
    loi normale sur (moyenne, écart-type) — voir `engine/combat.py` pour le détail
    et `damage_floor66`/`damage_floor80`/`damage_floor95` pour l'ancienne
    approximation gaussienne, conservée à titre de comparaison.
    """
    if mode == "mean":
        return expected_unit_damage(attacker, attacker_models, defender, modifiers)
    pmf = unit_damage_distribution(attacker, attacker_models, defender, modifiers)
    return distribution_floor(pmf, _FLOOR_COVERAGE[mode])


def unit_duel(
    attacker: Unit,
    defender: Unit,
    defender_army_name: str = "",
    *,
    attacker_reinforced: bool = False,
    defender_reinforced: bool = False,
    options_a: Optional[SideOptions] = None,
    options_b: Optional[SideOptions] = None,
    mode_a: DamageMode = "mean",
    mode_b: DamageMode = "mean",
    rules: Optional[DuelRules] = None,
) -> DuelResult:
    """Calcule le duel attaquant vs défenseur dans les deux sens.

    `mode_a`/`mode_b` contrôlent indépendamment la lecture du dégât de chaque
    sens (`_attack_damage`) — et donc de `pts_destroyed`/`pts_lost`/`pts_net`/`roi`,
    dérivés de `expected_a_to_b`/`expected_b_to_a`. Un duel n'est donc pas
    nécessairement symétrique : par ex. `mode_a="floor80"`, `mode_b="mean"` lit le
    dégât infligé par l'attaquant au plancher pessimiste 80% mais la riposte du
    défenseur à la moyenne.

    `rules` : corpus de règles optionnelles (`DuelRules`), désactivées par
    défaut — aucun changement de comportement si non fourni.
    """
    opts_a = options_a or SideOptions(charged=False)
    opts_b = options_b or SideOptions(charged=False)
    duel_rules = rules or DuelRules()

    a_models = _effective_models(attacker, attacker_reinforced)
    b_models = _effective_models(defender, defender_reinforced)
    a_hp_total = a_models * attacker.health
    b_hp_total = b_models * defender.health

    mods_ab = _mods(attacker, opts_a, defender, opts_b, duel_rules)
    mods_ba = _mods(defender, opts_b, attacker, opts_a, duel_rules)
    raw_ab = _attack_damage(attacker, a_models, defender, mods_ab, mode=mode_a)
    raw_ba = _attack_damage(defender, b_models, attacker, mods_ba, mode=mode_b)

    exp_ab = min(raw_ab, float(b_hp_total))
    exp_ba = min(raw_ba, float(a_hp_total))

    return DuelResult(
        attacker=attacker, attacker_models=a_models,
        attacker_reinforced=attacker_reinforced,
        defender=defender, defender_models=b_models,
        defender_reinforced=defender_reinforced,
        defender_army_name=defender_army_name,
        raw_a_to_b=raw_ab, expected_a_to_b=exp_ab,
        expected_models_killed_b=min(exp_ab / defender.health, float(b_models)),
        raw_b_to_a=raw_ba, expected_b_to_a=exp_ba,
        expected_models_killed_a=min(exp_ba / attacker.health, float(a_models)),
        options_a=opts_a, options_b=opts_b,
        mode_a=mode_a, mode_b=mode_b,
        rules=duel_rules,
    )


def find_unit(
    con: duckdb.DuckDBPyConnection, name: str, army_name: Optional[str],
) -> tuple[Unit, str]:
    """Résout une unité par nom (+ armée optionnelle pour lever l'ambiguïté)."""
    if army_name:
        army = repository.get_army_by_name(con, army_name)
        if army is None or army.id is None:
            raise ValueError(f"armée inconnue : {army_name}")
        unit = repository.get_unit_by_name(con, army.id, name)
        if unit is None:
            raise ValueError(f"unité '{name}' introuvable dans {army_name}")
        return unit, army_name
    matches: list[tuple[Unit, str]] = []
    for army in repository.list_armies(con):
        if army.id is None:
            continue
        unit = repository.get_unit_by_name(con, army.id, name)
        if unit is not None:
            matches.append((unit, army.name))
    if not matches:
        raise ValueError(f"unité '{name}' introuvable")
    if len(matches) > 1:
        names = ", ".join(a for _, a in matches)
        raise ValueError(f"unité '{name}' ambiguë ({names}) — précise --attacker-army")
    return matches[0]


def benchmark_attacker(
    con: duckdb.DuckDBPyConnection,
    attacker: Unit,
    *,
    attacker_reinforced: bool = False,
    defender_reinforced: bool = False,
    exclude_army_id: Optional[int] = None,
    target_army: Optional[str] = None,
    include_heroes: bool = False,
    options_a: Optional[SideOptions] = None,
    options_b: Optional[SideOptions] = None,
    defenders_by_army: Optional[dict[int, list[Unit]]] = None,
    army_names: Optional[dict[int, str]] = None,
    mode_a: DamageMode = "mean",
    mode_b: DamageMode = "mean",
    rules: Optional[DuelRules] = None,
) -> list[DuelResult]:
    """Lance le duel de `attacker` contre chaque unité défenseur sélectionnée.

    `defenders_by_army` et `army_names` permettent de fournir un cache pré-chargé
    pour éviter les requêtes DB par attaquant (utilisé par run_all_benchmarks).
    `mode_a`/`mode_b`/`rules` : cf. `unit_duel`.
    """
    results: list[DuelResult] = []
    if defenders_by_army is None or army_names is None:
        armies = repository.list_armies(con)
        defenders_by_army = {}
        army_names = {}
        for army in armies:
            if army.id is None:
                continue
            army_names[army.id] = army.name
            defenders_by_army[army.id] = repository.list_units_for_army(con, army.id)
    for army_id, defenders in defenders_by_army.items():
        army_name = army_names.get(army_id, "")
        if target_army and army_name != target_army:
            continue
        if exclude_army_id is not None and army_id == exclude_army_id:
            continue
        for defender in defenders:
            if defender.is_hero and not include_heroes:
                continue
            results.append(unit_duel(
                attacker, defender, army_name,
                attacker_reinforced=attacker_reinforced,
                defender_reinforced=defender_reinforced,
                options_a=options_a, options_b=options_b,
                mode_a=mode_a, mode_b=mode_b,
                rules=rules,
            ))
    return results



def save_results(con: duckdb.DuckDBPyConnection, results: list[DuelResult]) -> int:
    """Persiste une liste de DuelResult dans la table `unit_benchmark` (batch executemany).

    `mode_a`/`mode_b` sont lus sur chaque `DuelResult` (pas un flag partagé) : ils
    font partie de la clé de la table, donc deux runs avec des modes différents
    coexistent sans s'écraser (cf. `schema.sql::unit_benchmark`).
    """
    from datetime import datetime
    now = datetime.now()
    rows: list[tuple] = []
    for r in results:
        if r.attacker.id is None or r.defender.id is None:
            continue
        rows.append((
            r.attacker.id, r.defender.id,
            r.attacker_reinforced, r.defender_reinforced,
            r.options_a.charged, r.options_b.charged, r.mode_a, r.mode_b,
            r.raw_a_to_b, r.expected_a_to_b,
            r.raw_b_to_a, r.expected_b_to_a,
            r.pts_destroyed, r.pts_lost, r.pts_net, r.roi, now,
        ))
    repository.save_benchmark_results_many(con, rows)
    return len(rows)


@dataclass
class FullBenchmarkSummary:
    """Bilan d'un run global : nb d'attaquants traités et de duels écrits."""
    attackers: int = 0
    duels: int = 0


def run_all_benchmarks(
    con: duckdb.DuckDBPyConnection,
    *,
    options_a: Optional[SideOptions] = None,
    options_b: Optional[SideOptions] = None,
    include_heroes: bool = False,
    progress: Optional[Callable[[str, str, int, int], None]] = None,
    mode_a: DamageMode = "mean",
    mode_b: DamageMode = "mean",
    rules: Optional[DuelRules] = None,
) -> FullBenchmarkSummary:
    """Benchmarke chaque unité (non héros par défaut) contre toutes les autres armées.

    Les résultats sont persistés (upsert) dans `unit_benchmark`.
    `progress(attacker_name, army_name, idx, total)` est appelé avant chaque attaquant.
    `mode_a`/`mode_b`/`rules` : cf. `unit_duel`. Note : la table `unit_benchmark`
    n'a pas de colonne pour `rules` (pas de migration pour cet axe, cf.
    `DuelRules`) — un run avec des règles optionnelles actives écrase les
    lignes déjà persistées sous la même clé qu'un run sans ces règles.
    """
    summary = FullBenchmarkSummary()
    armies = [a for a in repository.list_armies(con) if a.id is not None]
    army_names: dict[int, str] = {a.id: a.name for a in armies}  # type: ignore[misc]
    defenders_by_army = repository.load_all_units_with_weapons(con)
    all_attackers: list[tuple[Unit, int]] = []
    for army in armies:
        for unit in defenders_by_army.get(army.id, []):  # type: ignore[arg-type]
            if unit.is_hero and not include_heroes:
                continue
            all_attackers.append((unit, army.id))  # type: ignore[arg-type]

    total = len(all_attackers)
    for idx, (attacker, army_id) in enumerate(all_attackers, start=1):
        if progress is not None:
            progress(attacker.name, army_names.get(army_id, "?"), idx, total)
        results = benchmark_attacker(
            con, attacker,
            exclude_army_id=army_id,
            include_heroes=include_heroes,
            options_a=options_a, options_b=options_b,
            defenders_by_army=defenders_by_army,
            army_names=army_names,
            mode_a=mode_a, mode_b=mode_b,
            rules=rules,
        )
        summary.duels += save_results(con, results)
        summary.attackers += 1
    return summary
