from aospy.tournament_kit.render import layout as render_layout
from aospy.tournament_kit.render import phases as render_phases
from aospy.tournament_kit.render import pills as render_pills
from aospy.tournament_kit.render import text as render_text
from aospy.tournament_kit.render import theme as render_theme
from aospy.tournament_kit.render.options import render_options_override, render_session
from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry


def test_weapon_abilities_fr():
    assert render_text.weapon_abilities_fr("Shoot in Combat, Anti-INFANTRY (+1 Rend)") == "Tir en Mêlée, Anti-Infanterie (+1 Perf.)"
    assert render_text.weapon_abilities_fr("Crit (Mortal)") == "Crit (Mortel)"
    assert render_text.weapon_abilities_fr("Crit (2 Hits), Charge (+1 Damage)") == "Crit (2 Touches), Charge (+1 Dégât)"
    assert render_text.weapon_abilities_fr("Anti-WAR MACHINE(+1 Rend), Companion") == "Anti-Machine de Guerre (+1 Perf.), Compagnon"
    # déjà français (profil d'arme curé) : inchangé
    assert render_text.weapon_abilities_fr("Tir en Mêlée, Crit (Mortel)") == "Tir en Mêlée, Crit (Mortel)"


def _ab(name: str, section: str = "", warscrolls: tuple[str, ...] = ()) -> AbilityEntry:
    return AbilityEntry(name=name, description="x", legend="", section=section, warscrolls=warscrolls)


def _section_titles(items) -> list[str]:
    return [it.title for it in items if it.is_header]


def test_base_rules_last_except_sequence_phases():
    group = [_ab("Tir", render_phases.SECTION_BASE), _ab("Esprit du Vent", warscrolls=("Sevireth",))]
    assert _section_titles(render_layout._sectioned_phase_items(group, 400, phase_key="shoot")) == [render_phases.SECTION_BASE, "Sevireth"]
    with render_options_override(base_last=True):
        assert _section_titles(render_layout._sectioned_phase_items(group, 400, phase_key="shoot")) == ["Sevireth", render_phases.SECTION_BASE]
        # Déploiement/Début de Round suivent le déroulé de la partie
        assert _section_titles(render_layout._sectioned_phase_items(group, 400, phase_key="round_start")) == [render_phases.SECTION_BASE, "Sevireth"]


def test_pill_legend_lists_only_drawn_families():
    with render_session():
        assert render_pills.pill_legend() == []
        render_pills._pill("SIMPLE", render_theme._BADGE_SOURCE, "#eef0f3")
        texts = [text for _row, _w, text in render_pills.pill_legend()]
        assert len(texts) == 2 and texts[1].startswith("Texte adapté")


def test_tr_translates_only_in_english_mode():
    assert render_text.tr("Mon tour") == "Mon tour"
    with render_options_override(english_labels=True):
        assert render_text.tr("Mon tour") == "My turn"
        assert render_text.tr("FORMATION : Warhost of Duality") == "FORMATION: Warhost of Duality"
        assert render_text.tr("Inconnu") == "Inconnu"
        assert render_phases._frequency_label("Once Per Turn (Army), Your Hero Phase") == "×1 / TURN (ARMY)"
    assert render_text.tr("Mon tour") == "Mon tour"


def _condition_text(condition: str) -> str | None:
    pill = render_pills._condition_pill(AbilityEntry(name="x", description="x", legend="", condition=condition), 400)
    return None if pill is None else pill[0]._cellvalues[0][0].text


def test_condition_pill_never_shows_raw_english_timing():
    # fréquence + timing de bandeau : la fréquence a sa pastille, le timing est masqué
    assert _condition_text("Once Per Battle, Deployment Phase") is None
    assert _condition_text("Once Per Battle Round, Start of Battle Round") is None
    assert render_phases._frequency_label("Once Per Battle Round, Start of Battle Round") == "×1 / ROUND"
    assert render_phases._frequency_label("Once Per Battle, Start of Battle Round") == "×1 / BATAILLE"
    assert render_phases._frequency_label("Once Per Phase (Army)") == "×1 / PHASE (ARMÉE)"
    assert _condition_text("Once Per Battle, Start of First Battle Round") == "DÉBUT DU 1ER ROUND"
    # coquilles Wahapedia
    assert render_phases._qualifier_label("Once Per Turn (Army), Any Comhat Phase") == "Les 2 phases"
    assert render_phases._qualifier_label("Your Hero Quest") == "Ma phase"


def test_long_hyphenated_name_breaks_after_hyphen():
    from aospy.tournament_kit.render.text import _break_long_name

    assert _break_long_name("Porte-Étendard", 60) == "Porte-<br/>Étendard"
    assert _break_long_name("Porte-Étendard", 300) == "Porte-Étendard"
    assert _break_long_name("Descendez-les vite", 300) == "Descendez-les vite"


def test_reaction_limited_to_your_phase_is_mine_only():
    from aospy.tournament_kit.render.phases import TURN_MINE, ability_turn_sides

    for condition in (
        "Once Per Turn (Army), Reaction: You declared a non-<ky>CHARGE MOVE</ky> ability "
        "for this unit in your %000009719movement% phase",
        "Once Per Turn (Army), Reaction: Vous avez annoncé une aptitude de Mouvement "
        "autre que de Charge pour cette unité dans votre phase de mouvement",
    ):
        ab = AbilityEntry(name="Plough the Icepath", description="", legend="",
                          ability_phase="Movement Phase", condition=condition)
        assert ability_turn_sides(ab) == frozenset({TURN_MINE})


def test_classify_phase_prefers_condition_over_inconsistent_ability_phase():
    from aospy.tournament_kit.render.phases import classify_phase
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    def phase(condition: str, ability_phase: str) -> str:
        return classify_phase(AbilityEntry("X", "", "", condition=condition, ability_phase=ability_phase))

    # Chalice of Ushoran (Wahapedia) : « Any Combat Phase » rangée à tort en "End of Turn"
    assert phase("Any Combat Phase", "End of Turn") == "melee"
    assert phase("Once Per Battle, Any Hero Phase", "Movement Phase") == "hero"
    assert phase("Passive", "End of Turn") == "end"
    assert phase("Reaction: Opponent declared a Charge ability", "Defensive reaction") == "any"


def test_ability_turn_sides_follows_condition_qualifier():
    from aospy.tournament_kit.render.phases import TURN_ENEMY, TURN_MINE, ability_turn_sides
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    def sides(condition: str, phase: str = "Hero Phase") -> set[str]:
        return set(ability_turn_sides(AbilityEntry("X", "", "", condition=condition, ability_phase=phase)))

    assert sides("Your Hero Phase") == {TURN_MINE}
    assert sides("Once Per Turn (Army), End of Your Turn", "End of Turn") == {TURN_MINE}
    assert sides("Enemy Movement Phase", "Movement Phase") == {TURN_ENEMY}
    assert sides("Once Per Turn (Army), Any Combat Phase", "Combat Phase") == {TURN_MINE, TURN_ENEMY}
    assert sides("Passive", "Combat Phase") == {TURN_MINE, TURN_ENEMY}
    assert sides("Reaction: Opponent declared a Charge ability", "Charge Phase") == {TURN_MINE, TURN_ENEMY}
    assert sides("Once Per Battle Round (Army), Start of Battle Round", "Start of Turn") == {TURN_MINE, TURN_ENEMY}
    # le déploiement précède le round 1 : montré une seule fois, côté « Mon tour »
    assert sides("Once Per Battle (Army), Deployment Phase", "Start of Turn") == {TURN_MINE}


def test_is_profile_modifier_detects_damage_dependent_characteristics_in_both_languages():
    from aospy.tournament_kit.render.phases import is_profile_modifier
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    en = "Effect: While this unit has 10 or more damage points, the Attacks characteristic of its Maw is 6."
    fr = "<b>Effet :</b> Tant que cette unité a 10 dégâts ou plus, la caractéristique d'Attaques de sa <b>Gueule</b> est 8."
    assert is_profile_modifier(AbilityEntry("Battle Damaged", en, "", condition="Passive"))
    assert is_profile_modifier(AbilityEntry("Stigmates de Guerre", fr, "", condition="Passive"))
    # même texte mais aptitude déclenchée : reste une aptitude de tour
    assert not is_profile_modifier(AbilityEntry("X", en, "", condition="Your Hero Phase"))
    # Wahapedia la range à tort en "Start of Turn" : bandeau vert, pas « Début de tour »
    from aospy.tournament_kit.render.phases import classify_phase
    assert classify_phase(AbilityEntry("Battle Damaged", en, "", condition="Passive", ability_phase="Start of Turn")) == "any"
    assert not is_profile_modifier(
        AbilityEntry("X", "Effect: Add 1 to the Damage characteristic of this unit's melee weapons.", "", condition="Passive")
    )


def test_cast_badge_shapes_are_unique():
    # règle : chaque type de coût (sort, prière, PC, dîme de sang...) a sa
    # propre silhouette, jamais partagée avec un autre type.
    from aospy.tournament_kit.render.pills import _CAST_BADGE_SHAPES

    shapes = list(_CAST_BADGE_SHAPES.values())
    assert len(shapes) == len(set(shapes))


def test_choice_section_is_its_own_chunk_with_a_taller_page_budget():
    from aospy.tournament_kit.render.layout import _MAX_CHOICE_HEIGHT, _MAX_GROUP_HEIGHT, _choice_segments
    from aospy.tournament_kit.render.pills import _keyword_pills
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    choice = AbilityEntry("Mépris Divin", "", "", keywords="Blood Tithe,BT", ability_category="blood_tithe")
    other = AbilityEntry("Autre", "", "", keywords="BT")
    assert _choice_segments([choice, other]) == [([choice], _MAX_CHOICE_HEIGHT), ([other], _MAX_GROUP_HEIGHT)]
    assert _choice_segments([other]) == [([other], _MAX_GROUP_HEIGHT)]
    # le mot-clé qui définit la sous-section n'y est pas répété en pastille
    assert len(_keyword_pills(choice)) == 1


def test_is_self_profile_modifier_keeps_own_weapon_and_characteristic_changes_only():
    """Une aptitude passive qui ne change que le profil de sa propre unité
    (une de ses armes, ou une caractéristique de « cette unité ») reste sur
    la carte du warscroll en `fr-split` ; une aptitude qui touche la cible ou
    d'autres unités, non."""
    from aospy.tournament_kit.render.phases import is_self_profile_modifier
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    weapons = ["Cursed Lance", "Warsteed’s Hooves"]
    impaling = (
        "<b>Effect:</b> If this unit charged this turn, for the rest of the turn, "
        "add 1 to the Rend characteristic of its <b>Cursed Lances</b>."
    )
    assert is_self_profile_modifier(AbilityEntry("Impaling Charge", impaling, "", condition="Passive"), weapons)
    wings = "<b>Effect:</b> If this unit has <b>Wings</b>, it has a Move characteristic of 10\" and has <b>FLY</b>."
    assert is_self_profile_modifier(AbilityEntry("Airborne Horror", wings, "", condition="Passive"), [])
    # pas passive
    assert not is_self_profile_modifier(AbilityEntry("Impaling Charge", impaling, "", condition="Your Combat Phase"), weapons)
    # effet sur la cible de l'attaque
    smash = (
        "<b>Effect:</b> If an attack made with this unit’s <b>Cursed Lance</b> scores a hit, "
        "the target has the <b>WARD-SMASHED</b> keyword for the rest of the battle."
    )
    assert not is_self_profile_modifier(AbilityEntry("Smash", smash, "", condition="Passive"), weapons)
    # touche d'autres unités
    aura = "<b>Effect:</b> Add 1 to the Rend characteristic of melee weapons used by friendly units wholly within 12\" of this unit."
    assert not is_self_profile_modifier(AbilityEntry("Aura", aura, "", condition="Passive"), weapons)


def test_translate_reaction_trigger():
    from aospy.tournament_kit.render.pills import _translate_trigger
    assert _translate_trigger("You declared an UNLIMITED SPELL ability for this unit") == (
        "Vous avez annoncé une aptitude de Sort Illimité pour cette unité"
    )
    assert _translate_trigger("You declared an ATTACK ability") == "Vous avez annoncé une aptitude d’Attaque"
    # schéma inconnu : laissé en anglais, jamais à moitié traduit
    odd = 'You declared a Fight ability for a friendly Pestilens unit wholly within 13" of this unit'
    assert _translate_trigger(odd) == odd
    # réaction à une aptitude nommée (Sanguinaires de Scourge of Aqshy)
    assert _translate_trigger(
        "You or your opponent declared the ‘Eruption of Fury’ ability for a unit within 12\" of this unit"
    ) == "Vous ou l’adversaire avez annoncé « Éruption de Fureur » pour une unité à 12\" de cette unité"


def test_generic_keyword_pills_are_french_only_in_french_modes(monkeypatch):
    """CORE -> BASE, MOVE -> MOUVEMENT... en modes `fr*` seulement ; un
    mot-clé propre à une faction reste tel quel (nom français non curé)."""
    from aospy.tournament_kit.render import pills as pills_mod
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    labels = []
    monkeypatch.setattr(pills_mod, "_pill", lambda text, *a, **k: labels.append(text))
    ability = AbilityEntry("X", "", "", keywords="Core, Move, Delusion, BT")
    from aospy.tournament_kit.render.options import render_options_override

    with render_options_override(french_keywords=True):
        render_pills._keyword_pills(ability)
    assert labels == ["BASE", "MOUVEMENT", "DELUSION", "BT"]
    labels.clear()
    render_pills._keyword_pills(ability)
    assert labels == ["CORE", "MOVE", "DELUSION", "BT"]


def test_phase_keyword_pills_use_their_phase_band_color(monkeypatch):
    from aospy.tournament_kit.render import pills as pills_mod
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    colors = {}
    monkeypatch.setattr(pills_mod, "_pill", lambda text, bg, fg, **k: colors.__setitem__(text, (bg, fg)))
    render_pills._keyword_pills(AbilityEntry("X", "", "", keywords="Fight, Tir, Charge, Course, Repli, Core, Unbind, Bannissement, Attack, BT"))
    assert colors["FIGHT"] == render_theme._PHASE_COLORS["melee"]
    assert colors["TIR"] == render_theme._PHASE_COLORS["shoot"]
    assert colors["CHARGE"] == render_theme._PHASE_COLORS["charge"]
    assert colors["COURSE"] == colors["REPLI"] == render_theme._PHASE_COLORS["move"]
    assert colors["CORE"] == ("#141414", "#f2ecdb")
    assert colors["UNBIND"] == colors["BANNISSEMENT"] == (render_theme._BADGE_SPELL, render_pills._CAST_BADGE_FG["Spell"])
    assert colors["ATTACK"] == (render_theme._BADGE_MULTI_PHASE, "#eef0f3")


def test_no_keyword_pill_uses_hero_phase_yellow(monkeypatch):
    from aospy.tournament_kit.render import pills as pills_mod
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    colors = {}
    monkeypatch.setattr(pills_mod, "_pill", lambda text, bg, fg, **k: colors.__setitem__(text, (bg, fg)))
    render_pills._keyword_pills(AbilityEntry("X", "", "", keywords="Sort, Summon, Convocation, Prière, Prayer, Rampage, Saccage, Inconnu, BT"))
    spell = (render_theme._BADGE_SPELL, render_pills._CAST_BADGE_FG["Spell"])
    prayer = (render_theme._BADGE_PRAYER, render_pills._CAST_BADGE_FG["Prayer"])
    assert colors["SORT"] == colors["SUMMON"] == colors["CONVOCATION"] == spell
    assert colors["PRIÈRE"] == colors["PRAYER"] == prayer
    assert colors["RAMPAGE"] == colors["SACCAGE"] == (render_theme._BADGE_MULTI_PHASE, "#eef0f3")
    assert colors["INCONNU"] == (render_theme._BADGE_KEYWORD, "#f2eeea")


def test_cast_badge_legend_lists_only_drawn_shapes_in_canonical_order():
    from aospy.tournament_kit.render.pills import cast_badge_legend

    legend = cast_badge_legend(frozenset({"drop", "circle"}))
    assert [badge.shape for badge, _text in legend] == ["circle", "drop"]
    assert legend[0][1].startswith("Aptitude : valeur de lancement")
    assert cast_badge_legend(frozenset()) == []


def test_provenance_note_does_not_make_a_synthesis_a_profile_modifier():
    """La note grise d'une synthèse peut citer une aptitude homonyme d'une
    arme (« Staff of the Horned Rat ») : la synthèse part quand même sur les
    cartes de tour."""
    from aospy.tournament_kit.render.phases import is_self_profile_modifier
    from aospy.tournament_kit.sources.roster_simplifications import _NOTE_MARKUP
    from aospy.tournament_kit.sources.wahapedia_lookup import AbilityEntry

    synthesis = AbilityEntry(
        "Casting Roll", "+1 to casting rolls." + _NOTE_MARKUP.format("Staff of the Horned Rat"), "", condition="Passive",
    )
    assert not is_self_profile_modifier(synthesis, ["Staff of the Horned Rat"])


def test_clean_html_unwraps_escaped_keyword_span():
    # FEC « The One True King » : balise de mot-clé échappée dans le scrape
    from aospy.tournament_kit.render.text import clean_html
    raw = ('While you believe this <a href="/x"><span class="kwb2 kwbu">&lt;<span class="kwb3">S</span>PAN</span> '
           '<span class="kwb kwbu">CLASS="KWB</span> <span class="kwb kwbu">KWBU"&gt;DELUSION&lt;/SPAN&gt;</span></a>:')
    assert clean_html(raw) == "While you believe this <b>DELUSION</b>:"


def test_clean_html_fixes_known_wahapedia_typos():
    from aospy.tournament_kit.render.text import clean_html
    assert "effect of that DELUSION applies" in clean_html("In such cases, the eect of that D  applies as if")


def test_two_column_packing_fills_short_column_and_backfills_page():
    from reportlab.platypus import PageBreak, Spacer, Table

    from aospy.tournament_kit.render.layout import pack_cards_two_columns

    cards = [Spacer(1, h) for h in (500, 200, 250, 400, 100)]
    story = pack_cards_two_columns(cards, [c.height for c in cards], page_height=760)
    # page 1 : 500 à gauche ; 200 puis 250 à droite (colonne la plus courte) ;
    # 400 ne tient plus -> page 2, mais 100 comble encore la page 1
    assert [type(x) for x in story] == [Table, PageBreak, Table]
    left, _gap, right = story[0]._cellvalues[0]
    assert left == [cards[0]]
    assert [c for c in right if c in cards] == [cards[1], cards[2], cards[4]]
    assert story[2]._cellvalues[0][0] == [cards[3]]


def test_two_column_packing_keeps_a_group_on_one_page():
    from reportlab.platypus import PageBreak, Spacer, Table

    from aospy.tournament_kit.render.layout import pack_cards_two_columns

    cards = [Spacer(1, h) for h in (600, 500, 150, 150, 150)]
    groups = [None, None, "manifestation", "manifestation", "manifestation"]
    story = pack_cards_two_columns(cards, [c.height for c in cards], page_height=760, groups=groups)
    # les 3 manifestations (450 + écarts) ne tiennent plus ensemble sur la
    # page 1 (reste 160 et 246) : elles partent toutes sur la page 2
    assert [type(x) for x in story] == [Table, PageBreak, Table]
    page2 = [c for col in story[2]._cellvalues[0] if isinstance(col, list) for c in col if c in cards]
    assert sorted(page2, key=cards.index) == cards[2:]
