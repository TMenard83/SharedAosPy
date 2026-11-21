import json

from aospy.tournament_kit.sources.roster_simplifications import load_roster_simplifications
from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry


def test_load_roster_simplifications(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"lists": {"Ma liste": {
        "units": {"Unit": {"add_abilities": [{"name": "Synthèse", "description": "+2", "note": "Source"}]}},
        "remove_abilities": ["Rune d’Enthlaï"],
    }}}), encoding="utf-8")
    simp = load_roster_simplifications("Ma liste", path)
    (added,) = simp.unit_abilities["Unit"]
    assert added.name == "Synthèse" and "Source" in added.description and "#8a8a8a" in added.description
    assert simp.is_removed(AbilityEntry(name="Rune d'Enthlaï", description="", legend=""))
    assert not simp.is_removed(added)
    assert load_roster_simplifications("Autre liste", path).unit_abilities == {}
    assert load_roster_simplifications("Ma liste", tmp_path / "absent.json").removed == frozenset()


def test_synthesis_ability_survives_its_own_removed_name(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"lists": {"L": {
        "units": {"Shrine": {"add_abilities": [{"name": "Gardien du Temple", "description": "résumé"}]}},
        "remove_abilities": ["Gardien du Temple"],
        "keep_on_warscroll": ["Plusieurs Parties"],
    }}}), encoding="utf-8")
    simp = load_roster_simplifications("L", path)
    (added,) = simp.unit_abilities["Shrine"]
    assert not simp.is_removed(added)
    assert simp.is_removed(AbilityEntry(name="Gardien du Temple", description="original", legend=""))
    assert simp.keeps_on_warscroll(AbilityEntry(name="Plusieurs Parties", description="", legend=""))


def test_all_lists_keywords_apply_to_any_list(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"all_lists": {"add_keywords": {"Placez le Champ de Bataille": "Simple"}}, "lists": {}}),
                    encoding="utf-8")
    simp = load_roster_simplifications("Liste inconnue", path)
    ab = simp.rewrite(AbilityEntry(name="Placez le Champ de Bataille", description="", legend="", keywords="MdG"))
    assert ab.keywords == "MdG, Simple"
    assert simp.rewrite(ab).keywords == "MdG, Simple"


def test_all_lists_description_overrides_apply_to_any_list(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({
        "all_lists": {"description_overrides": {"Éruption de Fureur": "court", "Autre": "commun"}},
        "lists": {"L": {"description_overrides": {"Autre": "propre à L"}}},
    }), encoding="utf-8")
    def text(list_name, name):
        simp = load_roster_simplifications(list_name, path)
        return simp.rewrite(AbilityEntry(name=name, description="long", legend="")).description
    assert text("Liste inconnue", "Éruption de Fureur") == "court"
    assert text("Liste inconnue", "Autre") == "commun"
    assert text("L", "Autre") == "propre à L"




def test_all_lists_merge_into_only_when_source_present(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"all_lists": {"merge_into": {
        "Musicien": {"into": "Ralliement", "description": "fusionné"},
    }}}), encoding="utf-8")
    simp = load_roster_simplifications("L", path)
    rally = AbilityEntry(name="Ralliement", description="seul", legend="")
    musician = AbilityEntry(name="Musicien", description="+1", legend="")
    (merged,) = simp.merge([rally, musician])
    assert merged.name == "Ralliement" and merged.description == "fusionné"
    assert simp.merge([rally]) == [rally]

def test_compress_spell_declare():
    from aospy.tournament_kit.sources.roster_simplifications import _compress_spell_declare as compress

    assert compress(
        '<i>f</i><br/><br/><b>Annonce :</b> Choisissez un <b>Sorcier Suzerain Lumineth</b> ami pour lancer ce sort, '
        'choisissez comme cible une unité ennemie visible et à 18" de lui, puis faites un jet de lancement de 2D6.'
        '<br/><br/><b>Effet :</b> X'
    ) == '<i>f</i><br/><br/><b>Cible :</b> une unité ennemie visible et à 18" du lanceur.<br/><br/><b>Effet :</b> X'
    assert compress(
        "<b>Annonce :</b> S'il n'y a pas d'<b>Incarnation</b> amie sur le champ de bataille, choisissez un "
        "<b>Sorcier</b> ami pour lancer ce sort, puis faites un jet de lancement de 2D6.<br/><br/><b>Effet :</b> Placez"
    ) == "<b>Effet :</b> Placez"
    # « …ce sort, puis choisissez… » et jet de lancement dans sa propre phrase (Salve d'Éclairs)
    assert compress(
        "<b>Annonce :</b> Choisissez un <b>Sorcier</b> ami pour lancer ce sort, puis choisissez comme cible l'unité "
        "ennemie la plus proche de lui. Si égalité, choisissez. Puis faites un jet de lancement de 2D6.<br/><br/><b>Effet :</b> X"
    ) == "<b>Cible :</b> l'unité ennemie la plus proche du lanceur. Si égalité, choisissez.<br/><br/><b>Effet :</b> X"
    # Annonce réduite au seul jet (Embruns Nébuleux) : elle disparaît
    assert compress("<b>Annonce :</b> Faites un jet de lancement de 2D6.<br/><br/><b>Effet :</b> X") == "<b>Effet :</b> X"
    other_roll = "<b>Annonce :</b> Choisissez un Sorcier ami, puis faites un jet de lancement de 3D6.<br/><br/><b>Effet :</b> Z"
    assert compress(other_roll) == other_roll


def test_compress_prayer_declare():
    from aospy.tournament_kit.sources.roster_simplifications import _compress_prayer_declare as compress

    assert compress(
        "<b>Annonce :</b> Choisissez un <b>Prêtre Sylvaneth</b> ami pour réciter cette prière, choisissez comme cible "
        "une unité de <b>Sylvaneths</b> amie visible et entièrement à 12\" de lui, puis faites un jet de récitation de D6."
        "<br/><br/><b>Effet :</b> X"
    ) == "<b>Cible :</b> une unité de <b>Sylvaneths</b> amie visible et entièrement à 12\" du Prêtre.<br/><br/><b>Effet :</b> X"
    # le point avant la suite de l'Annonce est conservé
    assert compress(
        "<b>Annonce :</b> Choisissez un <b>Prêtre</b> ami pour réciter cette prière, choisissez comme cible une unité "
        "amie entièrement à 12\" de lui, puis faites un jet de récitation d'un D6. Si le jet est de 10+, Y."
        "<br/><br/><b>Effet :</b> X"
    ) == "<b>Cible :</b> une unité amie entièrement à 12\" du Prêtre. Si le jet est de 10+, Y.<br/><br/><b>Effet :</b> X"
    # pas de cible : la phrase suivante ouvre l'Annonce, sans « . » orphelin (Rites Sacrés)
    assert compress(
        "<b>Annonce :</b> Choisissez un Prêtre ami pour qu’il récite cette prière, puis faites un jet de récitation "
        "d’un D6. Sur 1, Z.<br/><br/><b>Effet :</b> X"
    ) == "<b>Annonce :</b> Sur 1, Z.<br/><br/><b>Effet :</b> X"
    # convocation : l'Annonce entière disparaît
    assert compress(
        "<b>Annonce :</b> S'il n'y a aucune <b>Hache de Rage</b> amie sur le champ de bataille, choisissez un "
        "<b>Prêtre Lame de Khorne</b> ami pour réciter cette prière, puis faites un jet de récitation d'un D6."
        "<br/><br/><b>Effet :</b> Placez"
    ) == "<b>Effet :</b> Placez"
    # un Prêtre précis (régiment de renom) n'est pas sous-entendu
    named = ("<b>Annonce :</b> Choisissez le Prêtre du Carnage de ce Régiment de Renom pour réciter cette prière, "
             "puis faites un jet de récitation d'un D6.<br/><br/><b>Effet :</b> Z")
    assert compress(named) == named


def test_compress_tactic_conditions():
    from aospy.tournament_kit.sources.tactic_cards import SubTactic, TacticCard, compress_tactic_conditions
    sub = SubTactic(kind="Frappe", name="X", flavor="", points=5,
                    condition="Vous exécutez cette tactique de bataille à la fin de votre tour si vous contrôlez A.")
    card = compress_tactic_conditions(TacticCard(1, "En", "Fr", "", None, (sub,)))
    assert card.sub_tactics[0].condition == "Fin de votre tour, si vous contrôlez A."


def test_compressed_spell_declare_gets_simple_badge(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"all_lists": {"compress_spell_declare": True, "base_rules_last": True}, "lists": {}}),
                    encoding="utf-8")
    simp = load_roster_simplifications("L", path)
    assert simp.base_rules_last
    summon = AbilityEntry(
        name="Convocation", legend="", keywords="MdG", points_type="Spell",
        description="<b>Annonce :</b> Choisissez un <b>Sorcier</b> ami pour lancer ce sort, puis faites un jet de "
                    "lancement de 2D6.<br/><br/><b>Effet :</b> Placez",
    )
    assert simp.rewrite(summon).keywords == "MdG, Simple"
    # Annonce intacte (jet autre que 2D6) : pas de compression, pas de badge
    other = AbilityEntry(name="X", legend="", keywords="MdG", points_type="Spell",
                         description="<b>Annonce :</b> jet de lancement de 3D6.<br/><br/><b>Effet :</b> Z")
    assert simp.rewrite(other).keywords == "MdG"


def test_load_roster_simplifications_english_section(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({
        "all_lists": {"base_rules_last": True, "add_keywords": {"Course": "Simple"}},
        "lists": {"L": {"remove_abilities": ["Rune"]}},
        "en": {"all_lists": {"compress_spell_declare": True}, "lists": {"L": {"remove_abilities": ["Run"]}}},
    }), encoding="utf-8")
    simp = load_roster_simplifications("L", path, lang="en")
    assert simp.compress_spell_declare and not simp.base_rules_last and simp.add_keywords == {}
    assert simp.is_removed(AbilityEntry(name="Run", description="", legend=""))
    assert not simp.is_removed(AbilityEntry(name="Rune", description="", legend=""))


def test_unit_alias_renames_only_the_entry_with_its_options(tmp_path):
    from aospy.tournament_kit.list_parser import parse_list
    from aospy.tournament_kit.split_pool import _apply_unit_aliases

    path = tmp_path / "s.json"
    path.write_text(json.dumps({"lists": {"L": {"unit_aliases": {
        "Warbringer riche": {"unit": "Verminlord Warbringer", "options": ["Foulhide"]},
    }}}}), encoding="utf-8")
    parsed = parse_list(
        "L\n\nSkaven\nClaw-horde\n\nGeneral's Regiment\nVerminlord Warbringer (260)\n• Foulhide\n\n"
        "Regiment 1\nVerminlord Warbringer (260)\n",
    )
    renamed, sources = _apply_unit_aliases(parsed, load_roster_simplifications("L", path))
    assert [u.name for r in renamed.regiments for u in r.units] == ["Warbringer riche", "Verminlord Warbringer"]
    assert sources == {"Warbringer riche": "Verminlord Warbringer"}


def test_phase_overrides_move_ability_out_of_any_phase(tmp_path):
    from aospy.tournament_kit.render.phases import classify_phase
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"lists": {"L": {"phase_overrides": {
        "A Splendid Pageant": "Movement Phase", "The One True King": ["Movement Phase", "Charge Phase"],
    }}}}), encoding="utf-8")
    simp = load_roster_simplifications("L", path)
    pageant = AbilityEntry(name="A SPLENDID PAGEANT", description="", legend="", condition="Passive",
                           ability_phase="Start of Turn")
    king = AbilityEntry(name="The One True King", description="", legend="", condition="Passive",
                        ability_phase="Start of Turn")
    assert classify_phase(pageant) == "any"
    out = simp.expand_phases([pageant, king], lambda ab: False)
    assert [classify_phase(ab) for ab in out] == ["move", "move", "charge"]
    # copie de sous-section de choix : intacte
    assert simp.expand_phases([king], lambda ab: True) == [king]



def test_condition_override_changes_timing(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"lists": {"L": {"condition_overrides": {"Faim Dévorante": "Your Charge Phase"}}}}),
                    encoding="utf-8")
    simp = load_roster_simplifications("L", path)
    jaws = AbilityEntry(name="Faim Dévorante", description="", legend="", condition="Any Charge Phase")
    assert simp.rewrite(jaws).condition == "Your Charge Phase"


def test_add_unit_keywords(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"lists": {"L": {"units": {"Kin": {"add_unit_keywords": ["WIZARD (1)"]}}}}}),
                    encoding="utf-8")
    assert load_roster_simplifications("L", path).unit_keywords == {"Kin": ("WIZARD (1)",)}


def test_unit_weapon_overrides(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"lists": {"L": {"units": {"Knights": {
        "weapons": {"Cursed Lance": {"attacks": 4, "colour": "red"}}}}}}}), encoding="utf-8")
    assert load_roster_simplifications("L", path).unit_weapons == {"Knights": {"Cursed Lance": {"attacks": "4"}}}


def test_compress_declare_any_ability(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"all_lists": {"compress_declare": True}, "lists": {}}), encoding="utf-8")
    simp = load_roster_simplifications("L", path)
    roar = AbilityEntry(name="Rugissement", legend="", keywords="BT",
                        description="<b>Annonce :</b> Choisissez comme cible un Héros ennemi.<br/><br/><b>Effet :</b> Z")
    out = simp.rewrite(roar)
    assert out.description == "<b>Cible :</b> un Héros ennemi.<br/><br/><b>Effet :</b> Z"
    assert out.keywords == "BT, Simple"
    many = AbilityEntry(name="X", legend="", description="<b>Annonce :</b> Choisissez comme cibles toutes les unités.")
    assert simp.rewrite(many).description == "<b>Cibles :</b> toutes les unités."
    # cible qualifiée (Pennon de Majesté Azyrite) : le qualificatif passe dans le libellé
    banner = AbilityEntry(name="P", legend="", description="<b>Annonce :</b> Choisissez comme cible ennemie une unité ennemie.")
    assert simp.rewrite(banner).description == "<b>Cible ennemie :</b> une unité ennemie."
    # Annonce qui ne commence pas par la cible : intacte, pas de badge
    other = AbilityEntry(name="Y", legend="", keywords="BT",
                         description="<b>Annonce :</b> Choisissez un Prince Démon ami pour utiliser cette aptitude.")
    assert simp.rewrite(other) == other


def test_line_break_after_target_sentence():
    from aospy.tournament_kit.sources.roster_simplifications import _break_after_target

    assert _break_after_target("<b>Cible :</b> une unité amie. Sur 3+ : effet.") == "<b>Cible :</b> une unité amie.<br/>Sur 3+ : effet."
    assert _break_after_target("<b>Cible :</b> une unité à 6\". <b>Effet</b> : x.") == "<b>Cible :</b> une unité à 6\".<br/><b>Effet</b> : x."
    already = "<b>Cible :</b> une unité amie.<br/><br/><b>Effet :</b> x."
    assert _break_after_target(already) == already
    assert _break_after_target("<b>Cible :</b> une unité.<ul><li>x. Y.</li></ul>") == "<b>Cible :</b> une unité.<ul><li>x. Y.</li></ul>"
    assert _break_after_target("<b>Target:</b> an enemy unit. On 3+, x.") == "<b>Target:</b> an enemy unit.<br/>On 3+, x."


def test_set_up_is_always_bold():
    from aospy.tournament_kit.render.text import _bold_set_up

    assert _bold_set_up("Ni <b>Mouvement</b> ni placée à ce tour.") == "Ni <b>Mouvement</b> ni <b>placée</b> à ce tour."
    assert _bold_set_up("Replacez-la à 9\".") == "<b>Replacez</b>-la à 9\"."
    assert _bold_set_up("déjà <b>placé</b> ; se déplacer ; remplacer ; emplacement") == "déjà <b>placé</b> ; se déplacer ; remplacer ; emplacement"
    assert _bold_set_up("Set it up again.") == "<b>Set it up</b> again."
