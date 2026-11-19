from aospy.tournament_kit import warscroll_card as wc
from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry


def test_weapon_abilities_fr():
    assert wc.weapon_abilities_fr("Shoot in Combat, Anti-INFANTRY (+1 Rend)") == "Tir en Mêlée, Anti-Infanterie (+1 Perf.)"
    assert wc.weapon_abilities_fr("Crit (Mortal)") == "Crit (Mortel)"
    assert wc.weapon_abilities_fr("Crit (2 Hits), Charge (+1 Damage)") == "Crit (2 Touches), Charge (+1 Dégât)"
    assert wc.weapon_abilities_fr("Anti-WAR MACHINE(+1 Rend), Companion") == "Anti-Machine de Guerre (+1 Perf.), Compagnon"
    # déjà français (profil d'arme curé) : inchangé
    assert wc.weapon_abilities_fr("Tir en Mêlée, Crit (Mortel)") == "Tir en Mêlée, Crit (Mortel)"


def _ab(name: str, section: str = "", warscrolls: tuple[str, ...] = ()) -> AbilityEntry:
    return AbilityEntry(name=name, description="x", legend="", section=section, warscrolls=warscrolls)


def _section_titles(items) -> list[str]:
    return [it.title for it in items if it.is_header]


def test_base_rules_last_except_sequence_phases():
    group = [_ab("Tir", wc.SECTION_BASE), _ab("Esprit du Vent", warscrolls=("Sevireth",))]
    assert _section_titles(wc._sectioned_phase_items(group, 400, phase_key="shoot")) == [wc.SECTION_BASE, "Sevireth"]
    wc._BASE_LAST = True
    try:
        assert _section_titles(wc._sectioned_phase_items(group, 400, phase_key="shoot")) == ["Sevireth", wc.SECTION_BASE]
        # Déploiement/Début de Round suivent le déroulé de la partie
        assert _section_titles(wc._sectioned_phase_items(group, 400, phase_key="round_start")) == [wc.SECTION_BASE, "Sevireth"]
    finally:
        wc._BASE_LAST = False


def test_pill_legend_lists_only_drawn_families():
    wc.reset_drawn_pills()
    assert wc.pill_legend() == []
    wc._pill("SIMPLE", wc._BADGE_SOURCE, "#eef0f3")
    texts = [text for _row, _w, text in wc.pill_legend()]
    assert len(texts) == 2 and texts[1].startswith("Texte adapté")
    wc.reset_drawn_pills()


def test_tr_translates_only_in_english_mode():
    assert wc.tr("Mon tour") == "Mon tour"
    wc.set_english_labels(True)
    try:
        assert wc.tr("Mon tour") == "My turn"
        assert wc.tr("FORMATION : Warhost of Duality") == "FORMATION: Warhost of Duality"
        assert wc.tr("Inconnu") == "Inconnu"
        assert wc._frequency_label("Once Per Turn (Army), Your Hero Phase") == "×1 / TURN (ARMY)"
    finally:
        wc.set_english_labels(False)


def _condition_text(condition: str) -> str | None:
    pill = wc._condition_pill(AbilityEntry(name="x", description="x", legend="", condition=condition), 400)
    return None if pill is None else pill[0]._cellvalues[0][0].text


def test_condition_pill_never_shows_raw_english_timing():
    # fréquence + timing de bandeau : la fréquence a sa pastille, le timing est masqué
    assert _condition_text("Once Per Battle, Deployment Phase") is None
    assert _condition_text("Once Per Battle Round, Start of Battle Round") is None
    assert wc._frequency_label("Once Per Battle Round, Start of Battle Round") == "×1 / ROUND"
    assert wc._frequency_label("Once Per Battle, Start of Battle Round") == "×1 / BATAILLE"
    assert wc._frequency_label("Once Per Phase (Army)") == "×1 / PHASE (ARMÉE)"
    assert _condition_text("Once Per Battle, Start of First Battle Round") == "DÉBUT DU 1ER ROUND"
    # coquilles Wahapedia
    assert wc._qualifier_label("Once Per Turn (Army), Any Comhat Phase") == "Les 2 phases"
    assert wc._qualifier_label("Your Hero Quest") == "Ma phase"


def test_long_hyphenated_name_breaks_after_hyphen():
    from aospy.tournament_kit.warscroll_card import _break_long_name

    assert _break_long_name("Porte-Étendard", 60) == "Porte-<br/>Étendard"
    assert _break_long_name("Porte-Étendard", 300) == "Porte-Étendard"
    assert _break_long_name("Descendez-les vite", 300) == "Descendez-les vite"


def test_reaction_limited_to_your_phase_is_mine_only():
    from aospy.tournament_kit.warscroll_card import TURN_MINE, ability_turn_sides

    for condition in (
        "Once Per Turn (Army), Reaction: You declared a non-<ky>CHARGE MOVE</ky> ability "
        "for this unit in your %000009719movement% phase",
        "Once Per Turn (Army), Reaction: Vous avez annoncé une aptitude de Mouvement "
        "autre que de Charge pour cette unité dans votre phase de mouvement",
    ):
        ab = AbilityEntry(name="Plough the Icepath", description="", legend="",
                          ability_phase="Movement Phase", condition=condition)
        assert ability_turn_sides(ab) == frozenset({TURN_MINE})
