"""Couche 4 — assaut : redondance des charges groupées (étalonnage : analyse Hibou_2 de l'utilisateur)."""

import pytest

from aospy.analysis.layers.assault import ChargeSource, at_least, chargers, p_roll, reroll_receivers, scenario
from aospy.domain.models import Unit, Weapon


def _u(name, move=10, kw=("SKAVEN", "VERMINUS", "HERO", "MONSTER"), melee=True):
    w = [Weapon("griffes", "melee" if melee else "ranged", 7, 3, 2, 2)]
    return Unit(name, 1, move, 4, 13, 5, 1, 260, True, keywords=frozenset(kw), weapons=w)


def test_p_roll_9_inch_charge():
    assert p_roll(9) == pytest.approx(10 / 36)
    assert p_roll(9, bonus=1) == pytest.approx(15 / 36)
    assert p_roll(9, bonus=1, reroll=True) == pytest.approx(1 - (21 / 36) ** 2)


def test_at_least_matches_user_hibou_numbers():
    # 4 Verminlords à 9" avec Short-tempered : ≥ 2 réussites 55 % sec, 69 % avec l'ordre, 88 % avec les Cogs
    p = 15 / 36
    assert at_least([p] * 4, 2) == pytest.approx(0.553, abs=0.005)
    assert at_least([p] * 4, 2, command=True) == pytest.approx(0.69, abs=0.01)
    cogs = 1 - (1 - p) ** 2
    assert at_least([cogs] * 4, 2) == pytest.approx(0.88, abs=0.01)


def test_at_least_edges():
    assert at_least([0.5, 0.5], 0) == 1.0
    assert at_least([0.5, 0.5], 3) == 0.0
    assert at_least([1.0, 0.0], 1) == 1.0


def test_command_rerolls_most_promising_failure():
    # un seul chargeur raté relancé : on choisit celui qui a le plus de chances
    assert at_least([0.9, 0.1], 2, command=True) == pytest.approx(
        0.9 * 0.1 + 0.9 * 0.9 * 0.1 + 0.1 * 0.1 * 0.9)


def test_reroll_receivers_reads_text():
    units = [_u("Verminlord"), _u("Clanrats", kw=("SKAVEN", "INFANTRY"))]
    vocab = frozenset(k for u in units for k in u.keywords)
    txt = "Until the start of your next turn, you can re roll charge rolls for friendly units while they are wholly within 12\""
    assert reroll_receivers(txt, units, vocab) == ("Verminlord", "Clanrats")
    assert reroll_receivers("You can re-roll charge rolls for friendly MONSTER units.", units, vocab) == ("Verminlord",)
    assert reroll_receivers("Add 1 to charge rolls.", units, vocab) is None


def test_chargers_keep_the_hitters():
    big, small = _u("Warbringer"), _u("Arch-Warlock", kw=("SKAVEN", "HERO"))
    gun = _u("Cannon", kw=("SKAVEN", "WAR MACHINE"))
    sm = {"Warbringer": 1.0, "Arch-Warlock": 0.7, "Cannon": 0.0}
    dmg = {"Warbringer": 10.8, "Arch-Warlock": 2.7, "Cannon": 0.0}
    assert [u.name for u in chargers([big, small, gun], sm, dmg)] == ["Warbringer"]


def test_scenario_cogs_expected_and_teleport():
    units = [_u(f"V{i}") for i in range(4)]
    names = tuple(u.name for u in units)
    srcs = [ChargeSource("Short-tempered", "x", "bonus", 1, names, 1.0, False),
            ChargeSource("Cogs", "manifestation", "relance", 0, names, 0.72, False)]
    sc = scenario("tp", units, lambda u: 9.0, srcs, p_arrive=0.72)
    by = {c.label.split(" (")[0]: c.at_least for c in sc.cases}
    assert by["bonus permanents"][1] == pytest.approx(0.553, abs=0.005)
    expected = next(c.at_least for c in sc.cases if c.label.startswith("attendu"))
    with_tp = next(c.at_least for c in sc.cases if "téléportation comprise" in c.label)
    assert by["bonus permanents"][1] < expected[1] < by["+ Cogs"][1]
    assert with_tp[1] < expected[1]


def test_longest_charge_threat_range():
    from aospy.analysis.layers.assault import longest_charge
    assert longest_charge(0, False) == 7          # P(2D6 ≥ 7) = 58 %, ≥ 8 = 42 %
    assert longest_charge(1, False) == 8
    assert longest_charge(1, True) == 9           # +1 et relance : 9" à 66 %, 10" à 48 %


def _ab(name, effects, text="", ft="", scope="friendly_aura", carriers=("Skreech",), freq="unlimited"):
    from aospy.analysis.layers.listing import ListAbility
    return ListAbility("u-" + name, name, "charte : Skreech", "warscroll", carriers, scope, freq, "yours", "",
                       "", None, 1.0, None, ft, False, "plan", 2, 2, 2, 2, tuple(effects), False, text)


def test_charge_sources_read_v25_v26_effects():
    from aospy.analysis.layers.assault import charge_sources
    from aospy.analysis.layers.encounter import EffectSpec
    verm, wiz = _u("Warbringer"), _u("Arch-Warlock", kw=("SKAVEN", "HERO", "WIZARD", "MASTERCLAN"))
    units = [verm, wiz]
    vocab = frozenset(k for u in units for k in u.keywords)
    thirteen = _ab("The Thirteen-headed One", [
        EffectSpec("stat_mod", "cast", 1.0), EffectSpec("stat_mod", "charge", 1.0, friendly_target="VERMINUS")],
        ft="MASTERCLAN WIZARD")
    cogs = _ab("Mechanisms of Time", [EffectSpec("reroll", "charge", 1.0)], ft="WIZARD",
               text="you can re roll charge rolls for friendly units while they are wholly within 12\"")
    partial = _ab("Pitiless", [EffectSpec("reroll", "charge", 0.5)], ft="SKAVEN")
    src = {s.name: s for s in charge_sources([thirteen, cogs, partial], units, vocab)}
    assert src["The Thirteen-headed One"].receivers == ("Warbringer",)      # cible de l'effet (v26)
    assert set(src["Mechanisms of Time"].receivers) == {"Warbringer", "Arch-Warlock"}   # texte : toutes
    assert "Pitiless" not in src                                            # relance partielle non comptée


def test_charge_sources_star_target_reaches_every_unit():
    from aospy.analysis.layers.assault import charge_sources
    from aospy.analysis.layers.encounter import EffectSpec
    units = [_u("Warbringer"), _u("Arch-Warlock", kw=("SKAVEN", "HERO", "WIZARD"))]
    vocab = frozenset(k for u in units for k in u.keywords)
    cogs = _ab("Mechanisms of Time", [EffectSpec("reroll", "charge", 1.0, friendly_target="*")], ft="WIZARD")
    (src,) = charge_sources([cogs], units, vocab)
    assert set(src.receivers) == {"Warbringer", "Arch-Warlock"}


def test_dice_count_modes():
    """v28 `dice_count` : chiffres d'aospy-51 pour une charge de 9" (3D6 74 %, 3 dés garder 2 52 %, 1D6 0 %)."""
    assert p_roll(9, dice="3d6") == pytest.approx(0.741, abs=0.001)
    assert p_roll(9, dice="3k2") == pytest.approx(0.523, abs=0.001)
    assert p_roll(9, dice="1d6") == 0.0
    assert p_roll(9) == pytest.approx(10 / 36)


def test_dice_source_feeds_scenario_and_threat():
    from aospy.analysis.layers.assault import charge_sources, longest_charge
    from aospy.analysis.layers.encounter import EffectSpec
    units = [_u("A"), _u("B")]
    vocab = frozenset(k for u in units for k in u.keywords)
    src = charge_sources([_ab("Starfall", [EffectSpec("dice_count", "charge", 1.0, "somme")], ft="")], units, vocab)
    assert src[0].kind == "dés" and src[0].dice == "3d6"
    sc = scenario("tp", units, lambda u: 9.0, src)
    assert dict((c, b) for c, _p, b in sc.chargers)["A"] == pytest.approx(0.741, abs=0.001)
    assert longest_charge(0, False, dice="3d6") == 11      # 3D6 ≥ 11 : 50 % (seuil atteint) ; ≥ 12 : 37,5 %


def test_dice_max_mode_and_best_choice():
    """v29 « max » : 2 × le plus haut des 2D6 (9" à 55,6 %) ; le joueur choisit le meilleur mode par distance."""
    assert p_roll(9, dice="max") == pytest.approx(1 - (4 / 6) ** 2)
    assert p_roll(4, dice="max") == pytest.approx(1 - (1 / 6) ** 2)
    # à 12", « max » (un 6 suffit : 30,6 %) bat 3 dés garder 2 (7,4 %) ; à 6", c'est l'inverse
    assert p_roll(12, dice=("2d6", "3k2", "max")) == pytest.approx(11 / 36)
    assert p_roll(6, dice=("2d6", "3k2", "max")) == pytest.approx(p_roll(6, dice="3k2"))
    assert p_roll(6, dice="3k2") > p_roll(6, dice="max")
