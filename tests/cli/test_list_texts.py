from types import SimpleNamespace as NS

from aospy.cli.report import format_list_texts


def test_list_texts_flags_unknown_units_and_prints_ability_texts():
    w = NS(name="Claws", kind="melee", range_in=None, attacks=3, hit=4, wound=3, rend=1, damage=2, abilities="Crit")
    u = NS(name="Rat", move=6, save=5, ward=None, health=1, models=10, control=1, keywords={"INFANTRY"}, weapons=[w])
    abilities = [NS(uid="b", name="Zap", source="charte : Rat"), NS(uid="a", name="Aura", source="charte : Rat")]
    texts = {"a": {"condition_text": "Passive", "effect_text": "Add 1.", "cost_type": None, "cost_value": None,
                   "ability_keywords": None, "declare_text": None},
             "b": {"condition_text": "Your Hero Phase", "declare_text": "Pick.", "effect_text": "Boom.",
                   "cost_type": "Spell", "cost_value": 7, "ability_keywords": "Spell, Unlimited"}}
    text = format_list_texts("Liste", "export", [("Rat", 100, u), ("Gotrek", 200, None)], abilities, texts)
    assert "- Gotrek (200) : NON RECONNUE EN BASE" in text
    assert "- Claws [melee] A3 4+/3+ P1 D2 Crit" in text
    assert "### Zap — charte : Rat — coût Spell 7 — mots-clés : Spell, Unlimited" in text
    assert text.index("### Aura") < text.index("### Zap")  # ordre stable : source puis nom
