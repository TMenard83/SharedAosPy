import math

import pytest

from aospy.l3.layer4 import L4Indices, _time_factor


def test_time_factor_flat_curve_is_one():
    assert _time_factor([10.0] * 5) == 1.0


def test_time_factor_weights_rounds_2_3():
    # rythme 1/3, 1, 1, 1/3, 1/3 : un gain aux rounds 2-3 pèse plus qu'en fin de partie
    mid = _time_factor([1, 2, 2, 1, 1])
    late = _time_factor([1, 1, 1, 2, 2])
    assert mid > late > 1.0


def test_value_is_log_of_multipliers():
    ind = L4Indices(off_stack=2.0, def_stack=1.5, off_time=1.1)
    assert math.isclose(ind.value, math.log(2.2) + math.log(1.5))


def test_heal_and_control_from_grid():
    """Soins : part de durabilité, meilleure cible seule pour une aptitude à cible unique ; contrôle : 2 meilleures."""
    from types import SimpleNamespace

    from aospy.analysis.layers.listgrid import GridRow
    from aospy.domain.models import Unit
    from aospy.l3.layer4 import heal_and_control

    a = Unit(name="A", army_id=1, move=5, save=4, health=2, control=1, models=10, points=100)
    b = Unit(name="B", army_id=1, move=5, save=4, health=2, control=1, models=10, points=100)
    heal = GridRow("Soin", "", "soin", "", "", None, None, (), gains=(("A", 0.5), ("B", 0.2)), scope="one_friendly")
    ctl = GridRow("Ctl", "", "controle", "", "", None, None, (), gains=(("A", 3.0), ("B", 3.0)), scope="army",
                  weight=0.5)
    h, c, _ht, _ct = heal_and_control(SimpleNamespace(grid=[heal, ctl]), [a, b, b])
    assert h == pytest.approx(0.5 / 3)
    assert c == pytest.approx(0.5 * 6.0)
