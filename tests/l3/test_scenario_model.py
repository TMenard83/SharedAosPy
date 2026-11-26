from aospy.l3.scenario_model import INDICATORS, Model, evaluate, load_models, note_of, standardize


def _pool():
    base = {k: 0.0 for k in INDICATORS}
    raws = {f"p{i}": {**base, "mobilite": float(i), "durabilite": float(-i)} for i in range(5)}
    return standardize(raws)


def test_standardize_centre_et_reduit():
    pool = _pool()
    vals = [i.z["mobilite"] for i in pool.values()]
    assert abs(sum(vals)) < 1e-9
    assert abs(sum(v * v for v in vals) / len(vals) - 1) < 1e-9
    assert all(i.z["controle"] == 0 for i in pool.values())  # indicateur constant : z nul


def test_evaluate_suit_les_poids():
    pool = _pool()
    rapide = Model("course", "scénario", {"mobilite": 1})
    solide = Model("tenir", "scénario", {"durabilite": 1})
    assert evaluate(rapide, pool["p4"], pool).note == "++"
    assert evaluate(solide, pool["p4"], pool).note == "−−"
    r = evaluate(rapide, pool["p2"], pool)
    assert r.note == "=" and abs(r.axes["mobilité"]) < 1e-9


def test_tactique_base_et_decalage_scenario():
    pool = _pool()
    t = Model("t", "tactique", {"mobilite": 1}, base=-0.6, per_scenario={"Nuées": -1.0})
    v = evaluate(t, pool["p2"], pool).value
    assert abs(v + 0.6) < 1e-9
    assert abs(evaluate(t, pool["p2"], pool, scenario="Nuées").value + 1.6) < 1e-9


def test_seuils_des_notes():
    assert [note_of(v) for v in (1.0, 0.5, 0.0, -0.5, -1.0)] == ["++", "+", "=", "−", "−−"]


def test_fichier_de_poids_complet():
    scen, tact = load_models()
    assert len(scen) == 12 and len(tact) == 18
