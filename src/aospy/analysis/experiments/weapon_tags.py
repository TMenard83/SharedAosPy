"""Essai (partiellement concluant, adopté pour Charge/Crit) : les tags de texte libre
`Weapon.abilities` (Anti-<MOT-CLÉ>, Charge (+N <Stat>), type de Crit) expliquent-ils une part
du prix que le modèle de coût officiel (`cost_model.fit_cost_model_factorial`) rate
aujourd'hui ?

Contexte : un bug de parsing dans `engine/combat.py` (`_ANTI_RE`/`_CHARGE_RE` ne toléraient
pas le markup **gras**/^^exposant^^ de BSData ni le HTML <span> de Wahapedia) empêchait la
quasi-totalité des Anti-X réels de s'appliquer même en combat — corrigé séparément (159/159
unités concernées matchent maintenant). Même corrigé, ce bonus reste invisible aux features
officielles de `features.py` : ses défenseurs sondes (`_PROBE_SAVE2` etc.) n'ont aucun mot-clé,
et `_NO_MODS` n'a jamais `attacker_charged=True` — donc `dmg_vs_save2`/`dmg_vs_save6` ne
peuvent physiquement pas refléter un Anti-X ou un Charge (+N), quel que soit l'état du bug de
parsing.

Ici on recalcule, pour chaque unité, le supplément de dégât (à save 2+) que son Anti-X (contre
une cible portant tous les mots-clés jamais visés dans la base) et son Charge (+N) apporteraient
— un signal aujourd'hui totalement absent du modèle officiel — et on teste s'il explique une
part significative du prix, en plus (ou à la place) d'un simple indicateur catégoriel de
présence du tag.

Conclusion adoptée : la magnitude du bonus de charge (`charge_bonus_save2`) et le type de Crit
dominant (`crit_type`) sont désormais dans `cost_model.MODEL_FEATURES`/`CATEGORICAL_FEATURES` —
ce script dérive donc le contre-exemple "avant adoption" à partir du jeu officiel actuel plutôt
que l'inverse. Anti-X (présence et magnitude) reste écarté : ni l'un ni l'autre n'était
significatif ; ce script re-teste sa magnitude en plus du modèle déjà adopté pour le confirmer."""
from __future__ import annotations

import dataclasses

from aospy.analysis import cost_model
from aospy.domain.models import Unit
from aospy.engine.combat import CombatModifiers, _ANTI_RE, _CHARGE_RE, _normalize_abilities, _parse_crit, unit_damage_moments
from aospy.persistence import db, repository

con = db.connect()
by_army = repository.load_all_units_with_weapons(con)
frame = cost_model.feature_frame(con)
con.close()
frame = frame.reset_index(drop=True)

# Relevé empirique (pas une liste figée du jeu) des mots-clés visés par un
# Anti-X quelque part dans la base actuelle, cf. exploration ad hoc :
# HERO/INFANTRY/CAVALRY/MONSTER/BEAST/WAR MACHINE/WIZARD/PRIEST/DAEMON/
# MANIFESTATION/UNIQUE/FACTION TERRAIN. On donne tous ces mots-clés à la fois
# à un défenseur sonde : l'idée n'est pas de simuler un adversaire réaliste
# précis, mais de mesurer "cette arme a-t-elle un Anti-X qui peut se
# déclencher contre un adversaire plausible, et de combien ça vaut en dégât".
_ANTI_TARGET_KEYWORDS = frozenset({
    "HERO", "INFANTRY", "CAVALRY", "MONSTER", "BEAST", "WAR MACHINE",
    "WIZARD", "PRIEST", "DAEMON", "MANIFESTATION", "UNIQUE", "FACTION TERRAIN",
})
_PROBE_SAVE2_ANTI = Unit(
    name="_probe_anti", army_id=0, move=0, save=2, health=1, control=0, models=1,
    points=0, keywords=_ANTI_TARGET_KEYWORDS,
)
_PROBE_SAVE2_PLAIN = Unit(name="_probe_plain", army_id=0, move=0, save=2, health=1, control=0, models=1, points=0)
_NOT_CHARGED = CombatModifiers()
_CHARGED = CombatModifiers(attacker_charged=True)


def _tag_signals(unit: Unit) -> dict:
    """has_anti / has_charge / crit_type (dominant) / anti_bonus_save2 / charge_bonus_save2."""
    has_anti = has_charge = False
    best_weapon = None
    best_dmg = -1.0
    for w in unit.weapons:
        text = _normalize_abilities(w.abilities or "")
        for keyword, _amount, _stat in _ANTI_RE.findall(text):
            if keyword.strip().upper() != "CHARGE":  # "Anti-charge" : état non modélisé, cf. combat.py
                has_anti = True
        if _CHARGE_RE.search(text):
            has_charge = True
        dmg, _v, _s = unit_damage_moments(
            dataclasses.replace(unit, weapons=[w]), unit.models, _PROBE_SAVE2_PLAIN, _NOT_CHARGED,
        )
        if dmg > best_dmg:
            best_dmg = dmg
            best_weapon = w
    crit_type = _parse_crit(best_weapon.abilities) if best_weapon else "none"

    base, _v, _s = unit_damage_moments(unit, unit.models, _PROBE_SAVE2_PLAIN, _NOT_CHARGED)
    anti_aware, _v, _s = unit_damage_moments(unit, unit.models, _PROBE_SAVE2_ANTI, _NOT_CHARGED)
    charge_aware, _v, _s = unit_damage_moments(unit, unit.models, _PROBE_SAVE2_PLAIN, _CHARGED)

    return {
        "has_anti": has_anti,
        "has_charge": has_charge,
        "crit_type": crit_type,
        "anti_bonus_save2": anti_aware - base,
        "charge_bonus_save2": charge_aware - base,
    }


by_unit_id = {u.id: u for units in by_army.values() for u in units}
signals = frame["unit_id"].map(lambda uid: _tag_signals(by_unit_id[uid]))
for key in ("has_anti", "has_charge", "crit_type", "anti_bonus_save2", "charge_bonus_save2"):
    frame[key] = signals.map(lambda d: d[key])

n = len(frame)
print(f"Unités dans le jeu d'entraînement : {n}")
print(f"  has_anti   : {frame['has_anti'].sum()} ({frame['has_anti'].mean()*100:.1f} %)")
print(f"  has_charge : {frame['has_charge'].sum()} ({frame['has_charge'].mean()*100:.1f} %)")
print(f"  crit_type  : {frame['crit_type'].value_counts().to_dict()}")
print(f"  anti_bonus_save2   : moyenne={frame['anti_bonus_save2'].mean():.3f}  max={frame['anti_bonus_save2'].max():.3f}")
print(f"  charge_bonus_save2 : moyenne={frame['charge_bonus_save2'].mean():.3f}  max={frame['charge_bonus_save2'].max():.3f}")
print()

# `frame["charge_bonus_save2"]` (calculé ci-dessus) écrase la colonne déjà
# présente dans le jeu officiel (feature_frame l'inclut nativement) — même
# valeur recalculée par la même formule, donc sans incidence sur le modèle.
feats_before = [f for f in cost_model.MODEL_FEATURES if f != "charge_bonus_save2"]
cats_before = [c for c in cost_model.CATEGORICAL_FEATURES if c != "crit_type"]

model_a = cost_model.fit_cost_model_factorial(features=feats_before, categorical=cats_before, frame=frame.copy())  # avant adoption, sans tags

cats_b = cats_before + ["has_anti", "has_charge", "crit_type"]
model_b = cost_model.fit_cost_model_factorial(features=feats_before, categorical=cats_b, frame=frame.copy())  # + présence (catégoriel)

feats_c = feats_before + ["anti_bonus_save2", "charge_bonus_save2"]
model_c = cost_model.fit_cost_model_factorial(features=feats_c, categorical=cats_before, frame=frame.copy())  # + magnitude (continu)

feats_d = feats_before + ["anti_bonus_save2", "charge_bonus_save2"]
cats_d = cats_before + ["crit_type"]
model_d = cost_model.fit_cost_model_factorial(features=feats_d, categorical=cats_d, frame=frame.copy())  # officiel actuel + Anti-X testé en plus

print(f"Modèle A (avant adoption, sans tags)                : R² = {model_a.r_squared:.4f}  R² ajusté = {model_a.adj_r_squared:.4f}")
print(f"Modèle B (+ has_anti/has_charge/crit_type, catégoriel) : R² = {model_b.r_squared:.4f}  R² ajusté = {model_b.adj_r_squared:.4f}  (gain {model_b.adj_r_squared - model_a.adj_r_squared:+.4f})")
print(f"Modèle C (+ magnitude anti_bonus/charge_bonus, continu): R² = {model_c.r_squared:.4f}  R² ajusté = {model_c.adj_r_squared:.4f}  (gain {model_c.adj_r_squared - model_a.adj_r_squared:+.4f})")
print(f"Modèle D (officiel actuel + Anti-X testé en plus)      : R² = {model_d.r_squared:.4f}  R² ajusté = {model_d.adj_r_squared:.4f}  (gain {model_d.adj_r_squared - model_a.adj_r_squared:+.4f})")
print()

print("-- Modèle B : coefficients des tags --")
for c in model_b.coefficients:
    if any(k in c.name.lower() for k in ("anti", "charge", "crit")):
        print(f"  {c.name:35s} {c.coef:+8.2f}  p={c.p_value:.3f}")
print()

print("-- Modèle C : coefficients des tags --")
for c in model_c.coefficients:
    if any(k in c.name.lower() for k in ("anti", "charge", "crit")):
        print(f"  {c.name:35s} {c.coef:+8.2f}  p={c.p_value:.3f}")
print()

print("-- Modèle D : coefficients des tags --")
for c in model_d.coefficients:
    if any(k in c.name.lower() for k in ("anti", "charge", "crit")):
        print(f"  {c.name:35s} {c.coef:+8.2f}  p={c.p_value:.3f}")
