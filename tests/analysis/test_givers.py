"""Couche 4 : fiabilité d'un donneur recalculée avec la liste (analysis/layers/givers.py)."""

from __future__ import annotations

import pytest

from aospy.analysis.layers.encounter import EffectSpec
from aospy.analysis.layers.givers import caster_bonus, guardians, list_survival, p_cast

from .test_listing import _ab, _unit

WIZ = frozenset({"HERO", "INFANTRY", "WIZARD", "WIZARD (1)", "LUMINETH REALM-LORDS"})


def test_p_cast_with_bonus_and_reroll():
    """Valeur 7 : 58 % ; +2 → 5+ : 83 % ; relance : 1 − 0,17² ≈ 97 % (Enlightener de Totosai)."""
    assert p_cast(7) == pytest.approx(21 / 36)
    assert p_cast("7", 2.0) == pytest.approx(30 / 36)
    assert p_cast(7, 2.0, reroll=True) == pytest.approx(1 - (6 / 36) ** 2)
    assert p_cast(None) is None


def test_caster_bonus_respects_a_rune_claimed_by_an_enhancement():
    """Scholar of the Sigils prend Thalari (« That rune cannot be depicted ») : DEPICT RUNE ne peut plus la
    représenter pour personne ; Silver Wand +1 ; la relance du décor compte."""
    enl = _unit("Enlightener", keywords=WIZ)
    wand = _ab("SILVER WAND", carriers=["Enlightener"], source="amélioration : Silver Wand",
               effects=[EffectSpec("stat_mod", "cast", 1.0)])
    scholar = _ab("SCHOLAR", carriers=["Enlightener"], source="amélioration : Scholar",
                  text="That rune cannot be depicted on your battle scripture",
                  effects=[EffectSpec("stat_mod", "cast", 1.0, option_group="Thalari")])
    depict = _ab("DEPICT RUNE", scope="army", effects=[EffectSpec("stat_mod", "cast", 2.0, option_group="Thalari")])
    shrine = _ab("Cleansing Rituals", scope="friendly_aura", carriers=["Shrine"],
                 effects=[EffectSpec("reroll", "cast", 1.0)])
    b = caster_bonus(enl, [wand, scholar, depict, shrine], frozenset())
    assert b.bonus == 2.0 and b.reroll


def test_one_guardian_per_terrain_and_its_shield():
    """Un seul gardien par décor (le lanceur de plus haut niveau, puis le plus fragile) ; le décor qui encaisse
    à sa place allonge sa survie."""
    text = ("Pick a friendly LUMINETH REALM-LORDS INFANTRY HERO within 3\" of it. "
            "All attacks that would target the Shrine Guardian target this terrain feature instead.")
    shrine = _ab("Shrine Guardian", carriers=["Shrine Luminor"], text=text)
    enl = _unit("Enlightener", health=5, save=5, keywords=WIZ)
    mage = _unit("Windmage", health=6, save=4, keywords=WIZ)
    assert guardians([shrine], [enl, mage], frozenset(WIZ)) == {"Enlightener": "Shrine Luminor"}
    bare = list_survival(enl, (4.0, 2.0), "longue", 1, True)
    shielded = list_survival(enl, (4.0, 2.0), "longue", 1, True, shield_wounds=20.0)
    assert shielded > bare
