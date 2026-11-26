from types import SimpleNamespace as NS

from aospy.analysis.layers import roles
from aospy.domain.models import Unit, Weapon


def _unit(name, move=5, models=10, control=1, hero=False, kw=(), points=150):
    w = Weapon(name="arme", kind="melee", attacks=2, hit=3, wound=3, rend=1, damage=1)
    return Unit(name=name, army_id=1, move=move, save=4, health=1 if models > 1 else 8, control=control,
                models=models, points=points, is_hero=hero, keywords=frozenset(kw), weapons=[w])


def _sheet(name, points, off_rank=0.5, def_rank=0.5, fly=False, engage=3):
    return NS(name=name, points=points, copies=1, off_rank=off_rank, def_rank=def_rank, share_melee=1.0, fly=fly,
              engage_round=engage)


def _rep(units, sheets, abilities=(), marriages=(), stacks=()):
    return NS(units=[(u.name, s.points, u) for u, s in zip(units, sheets)], sheets=list(sheets),
              abilities=list(abilities), marriages=list(marriages), stacks=list(stacks), vocab=frozenset())


def test_roles_cordon_scoring_and_support():
    troops = _unit("Clanrats", models=20, points=120)
    hero = _unit("Héros", models=1, hero=True, kw=("HERO", "WIZARD (2)"), points=140)
    boss = _unit("Monstre", move=12, models=1, control=5, hero=False, points=400)
    sheets = [_sheet("Clanrats", 120, off_rank=0.2), _sheet("Héros", 140, off_rank=0.2),
              _sheet("Monstre", 400, off_rank=0.95, def_rank=0.3)]
    aura = NS(name="Aura", carriers=("Héros",), scope="friendly_aura", effects=())
    m = [NS(ability="Aura", receiver=n, off_gain_pct=20.0, def_gain_pct=0.0) for n in ("Clanrats", "Monstre")]
    rep = _rep([troops, hero, boss], sheets, [aura], m)
    by = {r.name: r for r in roles.unit_roles(rep)}
    assert by["Clanrats"].role in ("cordon", "scoring")
    assert by["Héros"].role == "support"
    assert by["Monstre"].role == "marteau"
    assert not by["Clanrats"].fast and by["Monstre"].fast


def test_components_castle_and_wing():
    slow = [_unit(f"Bloc{i}", models=10, points=150) for i in range(2)]
    hero = _unit("Prêtre", models=1, hero=True, kw=("HERO", "PRIEST"), points=100)
    fast = _unit("Cavalerie", move=12, models=5, points=300)
    units = slow + [hero, fast]
    sheets = [_sheet(u.name, u.points, off_rank=0.9 if u is fast else 0.3) for u in units]
    aura = NS(name="Bulle", carriers=("Prêtre",), scope="friendly_aura", effects=())
    m = [NS(ability="Bulle", receiver=u.name, off_gain_pct=0.0, def_gain_pct=30.0) for u in slow]
    rep = _rep(units, sheets, [aura], m)
    comps = roles.components(rep, roles.unit_roles(rep))
    kinds = {c.kind: c for c in comps}
    assert set(kinds["château lent"].units) == {"Bloc0", "Bloc1", "Prêtre"}
    assert kinds["aile rapide"].units == ("Cavalerie",)
    assert roles.pattern(comps).startswith("château lent + aile rapide")
