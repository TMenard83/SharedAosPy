"""Test d'intégration léger : assemblage du PDF avec une liste, l'index, le
battletome et le repli Wahapedia réels (nécessite l'extra [roster])."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("pypdf")

from pypdf import PdfReader

from aospy.tournament_kit.pdf_builder import build_roster_pdf, default_output_path


def test_build_roster_pdf_produces_cover_plus_rules_plus_unique_unit_pages(tmp_path):
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(
        "tests/fixtures/lists/LRL L3 Avengers Wardens.txt",
        out_path=out_path,
    )

    assert result.output_path == out_path
    assert result.units_unmatched == []
    assert result.rules_unmatched == []
    assert result.wahapedia_used == []
    # Traits de Bataille / la Formation choisie (Warhost of Duality) / le
    # domaine de sorts choisi / le domaine de manifestations choisi sont des
    # cartes maison Wahapedia, pas des pages de battletome copiées (cf.
    # `_WAHAPEDIA_RULE_CATEGORIES` + le bloc dédié pour les 2 derniers) —
    # seules les cartes de tactique restent des pages French copiées. Traits
    # Héroïques/Artefacts de Pouvoir n'apparaissent plus en bloc générique :
    # cette liste choisit "Flawless Commander" (Vanari Lord Regent) et
    # "Phoenix Stone" (Hurakan Windmage), résolus par unité et rattachés à
    # leur carte plutôt que listés pour toute la faction (cf.
    # `WahapediaLookup.find_unit_enhancement`).
    assert result.rules_included == [
        "Règles de Saison 2026-27",
        "Traits de Bataille",
        "Formation — Warhost of Duality",
        "Domaine de Sorts — Lore of Hysh",
        "Domaine de Manifestations — Manifestations of Hysh",
        "Burning for Vengeance",
        "Flanking Firestorm",
        "Trait Héroïque : FLAWLESS COMMANDER → Vanari Lord Regent",
        "Artefact de Pouvoir : PHOENIX STONE → Hurakan Windmage",
    ]
    assert out_path.exists()

    reader = PdfReader(str(out_path))
    # 1 couverture + 2 pages pour la carte "Aptitudes" (règles de saison —
    # cf. `season_rules.py` — + traits de bataille + formation + domaines,
    # fusionnés et triés par phase en une seule carte dessinée, pas une page
    # copiée — cf. `resolve_rules` ; « Inscription de Rune », Battle Trait
    # de début de round, reste dans son bandeau de phase normal malgré sa
    # longueur, répartie sur ses 2 colonnes plutôt que confinée à une seule —
    # cf. `warscroll_card._ability_group_body_columns_mixed` — vérifié
    # manuellement) + 1 page portant les 2 cartes de tactique citées
    # (dessinées elles aussi, cf. `tactic_cards.py` — elles tiennent toutes
    # les deux sur la même page) + N pages de cartes maison pour les profils
    # d'unité et les 3 manifestations invocables (2 par page) — vérifié
    # manuellement. La carte de règles occupe désormais toute la largeur
    # utile de la page (`_RULE_CARD_WIDTH`) et les cartes d'unité sont plus
    # larges (`_UNIT_CARD_WIDTH`) : moins de texte réenligné, donc des cartes
    # plus courtes et moins de pages qu'avant cet élargissement. Les cartes de
    # manifestation portent en plus leur note de pose (`summon_placement_note`),
    # d'où une page de plus. Cartes d'unité empilées en 2 colonnes
    # indépendantes (`pack_cards_two_columns`, avec comblement de page)
    # plutôt que par lignes de 2 : deux pages de moins.
    assert len(reader.pages) == 8


def test_build_roster_pdf_resolves_generic_manifestation_lore_as_a_card(tmp_path):
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(
        "tests/fixtures/lists/LRL L3 Montagne monstre 2 .txt",
        out_path=out_path,
    )
    # "Twilit Sorceries" est un domaine de manifestations générique
    # (`EnS` dans Faction_abilities.csv) : sa carte de domaine (les 3
    # aptitudes "SUMMON ...") et la charte complète de chacune de ses 3
    # manifestations sont désormais toutes trois résolues via Wahapedia —
    # plus de repli sur le PDF français ("Manuel du général/sorts persistants
    # - manifestations.pdf") pour ce cas, rien signalé comme non trouvé.
    assert result.rules_unmatched == []
    assert result.wahapedia_used == []
    assert "Domaine de Manifestations — Twilit Sorceries" in result.rules_included
    assert out_path.exists()

    text = "".join(p.extract_text() for p in PdfReader(str(out_path)).pages)
    assert "Twilit Sorceries" in text
    assert "SUMMON" in text


def test_build_roster_pdf_falls_back_to_wahapedia_for_army_of_renown(tmp_path):
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(
        "tests/fixtures/lists/STD L3 First Prince 1980.txt",
        out_path=out_path,
    )
    # "Legion of the First Prince" est une armée de renom : ni ses unités ni
    # ses règles ne sont dans le battletome Slaves to Darkness de base, mais
    # data/wahapedia/ les a toutes (Warscrolls.csv sous le nom nu de l'unité,
    # Faction_abilities.csv sous le nom de l'armée de renom). Les profils
    # d'unité passent tous par Wahapedia désormais (carte maison, plus de
    # copie de page) : "Bloodletters" n'a donc plus rien de spécial à
    # signaler dans `wahapedia_used`, seules les règles d'armée de renom
    # (pas une unité) y restent.
    assert result.units_unmatched == []
    assert "Legion of the First Prince Bloodletters" in result.units_matched
    assert result.rules_unmatched == []
    assert "Legion of the First Prince — Army of Renown Rules (EN, Wahapedia)" in result.wahapedia_used
    # "Legion of the First Prince" remplace les traits de bataille / traits
    # héroïques / artefacts de Slaves to Darkness (mais pas ses formations,
    # qu'elle ne fournit pas elle-même) : la page du battletome de base ne
    # doit pas apparaître à côté de la version de remplacement (Wahapedia).
    assert "Traits de Bataille" not in result.rules_included
    assert "Traits Héroïques et Artefacts de Pouvoir" not in result.rules_included
    assert "Formations de Bataille" in result.rules_included
    assert out_path.exists()


def test_build_roster_pdf_falls_back_to_wahapedia_for_regiment_of_renown(tmp_path):
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(
        "tests/fixtures/lists/STD L3 Prince Warriors Launcher.txt",
        out_path=out_path,
    )
    # "The Exiled One" (Skarbrand) est un Regiment of Renown : absent du
    # battletome Slaves to Darkness (il appartient nativement à Blades of
    # Khorne), résolu via data/wahapedia/ (Warscrolls.csv role == "Regiment
    # of Renown" + le warscroll complet de Skarbrand, rendu en carte).
    assert "Skarbrand" not in result.units_unmatched
    assert "Skarbrand" in result.units_matched
    assert "Regiment of Renown : The Exiled One (EN, Wahapedia)" in result.wahapedia_used
    assert out_path.exists()

    # "The Exiled One" n'a qu'un seul membre (Skarbrand) : son aptitude
    # propre ("HATRED FOR ALL") doit rejoindre la carte de Skarbrand plutôt
    # que rester dans une section "Regiment of Renown" à part.
    text = "".join(p.extract_text() for p in PdfReader(str(out_path)).pages)
    # 1re occurrence = la couverture (liste des membres du Regiment of
    # Renown) ; la carte de Skarbrand elle-même est la 2e.
    cover_idx = text.find("Skarbrand")
    assert cover_idx != -1
    skarbrand_idx = text.find("Skarbrand", cover_idx + 1)
    assert skarbrand_idx != -1
    # une seule occurrence : plus de section "Regiment of Renown" séparée,
    # seulement la note de provenance rattachée à la carte de Skarbrand.
    assert text.count("Regiment of Renown — The Exiled One") == 1
    assert "Regiment of Renown — The Exiled One" in text[skarbrand_idx:skarbrand_idx + 400]
    assert "HATRED FOR ALL" in text[skarbrand_idx:]


def test_build_roster_pdf_reports_truly_unmatched_content_gracefully(tmp_path):
    """Rien de ce qui n'existe ni dans le battletome ni dans Wahapedia ne doit
    faire planter la génération — juste être signalé."""
    list_path = tmp_path / "fake.txt"
    list_path.write_text(
        "Fake - Test 2000/2000 pts\n\n"
        "Lumineth Realm-lords\n"
        "General's Handbook 2026-27\n"
        "Drops: 1\n"
        "Spell Lore - This Lore Does Not Exist Anywhere\n\n"
        "General's Regiment\n"
        "This Unit Does Not Exist Anywhere (250)\n"
        " • General\n\n"
        "Created with Warhammer Age of Sigmar: The App\n"
        "App: 1.37.0 | Data: 476\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(str(list_path), out_path=out_path)

    assert "This Unit Does Not Exist Anywhere" in result.units_unmatched
    assert "Domaine de sorts : This Lore Does Not Exist Anywhere" in result.rules_unmatched
    assert out_path.exists()
    assert len(PdfReader(str(out_path)).pages) >= 1


#: Répertoire Wahapedia inexistant — force `WahapediaLookup.available` à
#: `False` (`self._dir.exists()`) sans avoir à démonter les CSV réels, pour
#: forcer la résolution des règles sur le repli page French (`hybrid`) et
#: vérifier qu'`en`/`fr` le sautent bien (cf. `pdf_builder.resolve_rules`,
#: `allow_page_copy`).
_LRL_LIST = "tests/fixtures/lists/LRL L3 Avengers Wardens.txt"


def test_build_roster_pdf_mode_hybrid_falls_back_to_french_page_copy_without_wahapedia(tmp_path):
    result = build_roster_pdf(
        _LRL_LIST, out_path=tmp_path / "out.pdf", wahapedia_dir=tmp_path / "no-such-wahapedia-dir", mode="hybrid",
    )
    assert result.rules_unmatched == []
    assert "Formations de Bataille" in result.rules_included
    assert "Traits Héroïques et Artefacts de Pouvoir" in result.rules_included


def test_build_roster_pdf_mode_en_skips_french_page_copy_fallback(tmp_path):
    result = build_roster_pdf(
        _LRL_LIST, out_path=tmp_path / "out.pdf", wahapedia_dir=tmp_path / "no-such-wahapedia-dir", mode="en",
    )
    assert "Formations de Bataille" not in result.rules_included
    assert "Traits Héroïques et Artefacts de Pouvoir" not in result.rules_included
    assert "Domaine de sorts : Lore of Hysh" in result.rules_unmatched
    assert "Domaine de manifestations : Manifestations of Hysh" in result.rules_unmatched


def test_build_roster_pdf_mode_fr_applies_verbatim_overrides_and_skips_page_copy(tmp_path):
    frf_path = tmp_path / "faction_rules_fr.json"
    frf_path.write_text(
        """{
            "factions": {
                "Lumineth Realm-lords": {
                    "rules": {
                        "battle_traits": [
                            {
                                "wahapedia_name": "DEPICT RUNE",
                                "name": "Vérité Française de Test",
                                "description": "<b>Texte vérifiant l'application du correctif.</b>",
                                "origin": "BT"
                            }
                        ]
                    },
                    "units": {}
                }
            }
        }""",
        encoding="utf-8",
    )
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(_LRL_LIST, out_path=out_path, mode="fr", faction_rules_fr_path=frf_path)

    assert result.rules_unmatched == []
    # aucune copie de page French même pour une catégorie non curée (Traits
    # Héroïques/Artefacts de Pouvoir n'a pas d'entrée dans le JSON de test) :
    # `fr` dégrade vers Wahapedia (EN), jamais une page.
    text = "".join(p.extract_text() for p in PdfReader(str(out_path)).pages)
    assert "Vérité Française de Test" in text
    assert "Texte vérifiant l'application du correctif" in text


def test_build_roster_pdf_mode_fr_extended_includes_generic_abilities_card(tmp_path):
    generic_path = tmp_path / "generic_core_abilities.json"
    generic_path.write_text(
        """[
            {"name": "Aptitude Générique de Test", "description": "Texte de test.", "condition": "Passive", "ability_phase": ""}
        ]""",
        encoding="utf-8",
    )
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(_LRL_LIST, out_path=out_path, mode="fr-extended", generic_core_abilities_path=generic_path)

    assert "Aptitudes Génériques — MdG26-27" in result.rules_included
    # carte sectionnée : un nom court peut tenir sur plusieurs lignes d'une
    # case de grille étroite
    text = " ".join("".join(p.extract_text() for p in PdfReader(str(out_path)).pages).split())
    assert "Aptitude Générique de Test" in text


def test_generic_core_abilities_requires_unit_keyword(tmp_path):
    from aospy.tournament_kit.translation.generic_core_abilities import load_generic_core_abilities

    path = tmp_path / "generic.json"
    path.write_text(
        """[
            {"name": "Musicien", "requires_unit_keyword": "MUSICIAN", "description": "", "condition": "Passive"},
            {"name": "Porte-Étendard", "requires_unit_keyword": "STANDARD BEARER", "description": "", "condition": "Passive"},
            {"name": "Champion", "requires_unit_keyword": "CHAMPION", "description": "", "condition": "Passive"},
            {"name": "Ralliement", "description": "", "condition": "Any Hero Phase"}
        ]""",
        encoding="utf-8",
    )
    names = lambda kws: [ab.name for ab in load_generic_core_abilities(path, unit_keywords=kws)]
    assert names(frozenset({"HERO", "INFANTRY"})) == ["Ralliement"]
    assert names(frozenset({"STANDARD BEARER"})) == ["Porte-Étendard", "Ralliement"]
    assert names(frozenset({"CHAMPION (1/9)"})) == ["Champion", "Ralliement"]
    assert names(None) == ["Musicien", "Porte-Étendard", "Champion", "Ralliement"]


def test_generic_core_abilities_requires_any_of_unit_keywords(tmp_path):
    from aospy.tournament_kit.translation.generic_core_abilities import load_generic_core_abilities

    path = tmp_path / "generic.json"
    path.write_text(
        """[
            {"name": "Dissipation", "requires_unit_keyword": "WIZARD", "description": "", "condition": "Passive"},
            {"name": "Intervention Magique", "requires_unit_keyword": ["WIZARD", "PRIEST"], "description": "", "condition": "Passive"},
            {"name": "Rites Sacrés", "requires_unit_keyword": "PRIEST", "description": "", "condition": "Passive"}
        ]""",
        encoding="utf-8",
    )
    names = lambda kws: [ab.name for ab in load_generic_core_abilities(path, unit_keywords=kws)]
    assert names(frozenset({"HERO"})) == []
    assert names(frozenset({"WIZARD (1)"})) == ["Dissipation", "Intervention Magique"]
    assert names(frozenset({"PRIEST"})) == ["Intervention Magique", "Rites Sacrés"]


def test_build_roster_pdf_mode_fr_extended_without_curated_generic_abilities_behaves_like_fr(tmp_path):
    """Fichier de règles génériques absent/vide (peu importe la curation
    réelle de `data/json/generic_core_abilities.json`) : le mode étendu ne doit ni
    planter ni ajouter de carte."""
    generic_path = tmp_path / "generic_core_abilities.json"
    generic_path.write_text("[]", encoding="utf-8")
    result = build_roster_pdf(
        _LRL_LIST, out_path=tmp_path / "out.pdf", mode="fr-extended", generic_core_abilities_path=generic_path
    )
    assert "Aptitudes Génériques — MdG26-27" not in result.rules_included


def test_classify_phase_prefers_condition_over_inconsistent_ability_phase():
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import classify_phase

    def phase(condition: str, ability_phase: str) -> str:
        return classify_phase(AbilityEntry("X", "", "", condition=condition, ability_phase=ability_phase))

    # Chalice of Ushoran (Wahapedia) : « Any Combat Phase » rangée à tort en "End of Turn"
    assert phase("Any Combat Phase", "End of Turn") == "melee"
    assert phase("Once Per Battle, Any Hero Phase", "Movement Phase") == "hero"
    assert phase("Passive", "End of Turn") == "end"
    assert phase("Reaction: Opponent declared a Charge ability", "Defensive reaction") == "any"


def test_ability_turn_sides_follows_condition_qualifier():
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import TURN_ENEMY, TURN_MINE, ability_turn_sides

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
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import is_profile_modifier

    en = "Effect: While this unit has 10 or more damage points, the Attacks characteristic of its Maw is 6."
    fr = "<b>Effet :</b> Tant que cette unité a 10 dégâts ou plus, la caractéristique d'Attaques de sa <b>Gueule</b> est 8."
    assert is_profile_modifier(AbilityEntry("Battle Damaged", en, "", condition="Passive"))
    assert is_profile_modifier(AbilityEntry("Stigmates de Guerre", fr, "", condition="Passive"))
    # même texte mais aptitude déclenchée : reste une aptitude de tour
    assert not is_profile_modifier(AbilityEntry("X", en, "", condition="Your Hero Phase"))
    # Wahapedia la range à tort en "Start of Turn" : bandeau vert, pas « Début de tour »
    from aospy.tournament_kit.warscroll_card import classify_phase
    assert classify_phase(AbilityEntry("Battle Damaged", en, "", condition="Passive", ability_phase="Start of Turn")) == "any"
    assert not is_profile_modifier(
        AbilityEntry("X", "Effect: Add 1 to the Damage characteristic of this unit's melee weapons.", "", condition="Passive")
    )


def test_warscroll_ability_pool_merges_identical_abilities_across_units():
    from dataclasses import replace

    from aospy.tournament_kit.pdf_builder import _warscroll_ability_pool
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry, WarscrollData

    shared = AbilityEntry("SHARED", "Same text.", "", condition="Passive")
    own = AbilityEntry("OWN", "Own text.", "", condition="Your Hero Phase")
    base = WarscrollData("A", "", "", "", "", "", "", "", "", "", "", [], [], [shared, own])
    pool = _warscroll_ability_pool([base, replace(base, name="B", abilities=[shared])])

    assert [(ab.name, ab.warscrolls) for ab in pool] == [("SHARED", ("A", "B")), ("OWN", ("A",))]


@pytest.mark.parametrize("cards_pages", [1, 2])
def test_build_roster_pdf_mode_fr_split_warscrolls_start_on_odd_page(tmp_path, monkeypatch, cards_pages):
    """La copie des warscrolls qui ouvre « Tour de l'adversaire » démarre sur
    une page impaire en `fr-split`, quelle que soit la parité de ce qui
    précède (`_pad_to_odd_page`)."""
    from io import BytesIO

    from pypdf import PdfWriter

    import aospy.tournament_kit.pdf_builder as pb

    def fake_cards(*_args, **_kwargs):
        w = PdfWriter()
        w.add_blank_page(width=595, height=842)
        out = BytesIO()
        w.write(out)
        return out.getvalue()

    real_rule_cards = pb._build_rule_cards_pdf

    def rule_cards_with_extra_page(cards, page_label=None, label_margin=False):
        data = real_rule_cards(cards, page_label=page_label, label_margin=label_margin)
        if page_label == "Mon tour" and cards_pages == 2 and data is not None:
            w = PdfWriter()
            for page in PdfReader(BytesIO(data)).pages:
                w.add_page(page)
            w.add_blank_page(width=595, height=842)
            out = BytesIO()
            w.write(out)
            return out.getvalue()
        return data

    marker_page = {}
    real_pad = pb._pad_to_odd_page

    def pad_and_record(writer):
        real_pad(writer)
        marker_page["next"] = len(writer.pages) + 1

    monkeypatch.setattr(pb, "_build_warscroll_cards_pdf", fake_cards)
    monkeypatch.setattr(pb, "_build_rule_cards_pdf", rule_cards_with_extra_page)
    monkeypatch.setattr(pb, "_pad_to_odd_page", pad_and_record)
    build_roster_pdf(_LRL_LIST, out_path=tmp_path / "out.pdf", mode="fr-split")

    # dernier appel = juste avant la copie des warscrolls du tour adverse
    assert marker_page["next"] % 2 == 1


def test_build_roster_pdf_mode_fr_split_two_turn_cards_and_stripped_warscrolls(tmp_path):
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(_LRL_LIST, out_path=out_path, mode="fr-split")

    assert result.units_unmatched == []
    pages = [p.extract_text() for p in PdfReader(str(out_path)).pages]
    deploy = next(i for i, t in enumerate(pages) if t.lstrip().startswith("Déploiement"))
    # en-tête discret « MON TOUR »/« TOUR DE L'ADVERSAIRE » sur chaque page
    # des cartes de tour, absent de la carte « Déploiement »
    mine = next(i for i, t in enumerate(pages) if t.lstrip().startswith("MON TOUR\nMon tour"))
    enemy = next(i for i, t in enumerate(pages) if t.lstrip().startswith("TOUR DE L'ADVERSAIRE\nTour adverse"))
    assert deploy < mine < enemy
    # warscrolls juste après la couverture, puis recopiés en tête de la
    # section « Tour de l'adversaire », qui démarre sur une page impaire
    # (recto), quitte à laisser une page blanche de remplissage juste avant
    windmage = [i for i, t in enumerate(pages) if "Hurakan Windmage" in t and "MV" in t]
    assert windmage[0] < deploy and mine < windmage[-1] < enemy
    copy_start = next(i for i in range(mine, enemy) if "MV" in pages[i] and not pages[i].lstrip().startswith("MON TOUR"))
    assert copy_start % 2 == 0
    assert all(t.lstrip().startswith("MON TOUR") or not t.strip() for t in pages[mine:copy_start])
    assert not pages[deploy].lstrip().startswith(("MON TOUR", "TOUR DE"))
    # déploiement + « N'importe quelle phase » sur leur propre carte,
    # absents des cartes de tour
    deploy_text = "".join(pages[deploy:mine])
    assert deploy_text.index("DÉPLOIEMENT\n") < deploy_text.index("N'IMPORTE QUELLE PHASE")
    assert "DÉPLOIEMENT\n" not in "".join(pages[mine:])
    assert "N'IMPORTE QUELLE PHASE" not in "".join(pages[mine:])
    # tactiques de bataille en fin de « Mon tour », après « Fin de tour »
    turn_text = "".join(pages[mine:enemy])
    assert turn_text.index("FIN DE TOUR") < turn_text.index("CARTE DE TACTIQUE")
    # le titre de carte dit déjà le tour : pas de pastille « Ma phase »/
    # « Phase ennemi »/« Les 2 phases » (une aptitude des 2 tours figure sur
    # les 2 cartes)
    all_turns = "".join(pages[mine:])
    assert "MA PHASE" not in all_turns and "PHASE ENNEMI" not in all_turns
    assert "LES 2 PHASES" not in all_turns
    # aptitude de warscroll déplacée sur les cartes de tour, avec le badge
    # du nom de son unité ; la carte d'unité elle-même n'en porte plus
    assert "HYSHIAN TWINSTONES" in turn_text
    unit_pages = [t for t in pages[:deploy] + pages[copy_start:enemy] if " MV\n" in t]
    assert unit_pages
    assert all("PHASE DES HÉROS" not in t and "PASSIF" not in t for t in unit_pages)


_STD_FIRST_PRINCE_LIST = "tests/fixtures/lists/STD L3 First Prince 1980.txt"

#: Les 9 aptitudes Wahapedia de l'Armée de Renom "Legion of the First
#: Prince" (`WahapediaLookup.find_renown_army_rules`) — la curation doit
#: couvrir les 9 pour que `_renown_army_pool` considère l'armée entièrement
#: traduite (cf. `test_build_roster_pdf_mode_fr_renown_army_full_coverage`).
_LEGION_OF_THE_FIRST_PRINCE_ABILITIES = [
    ("battle_traits", "FIRST-DAMNED PRINCE"),
    ("battle_traits", "DAEMONIC REINFORCEMENTS"),
    ("battle_traits", "STORM OF BLACKENED BLADES"),
    ("battle_traits", "BESTOW FAVOUR"),
    ("heroic_traits_artefacts", "DREAD MARSHAL"),
    ("heroic_traits_artefacts", "BLACK RITUAL DAGGER"),
    ("spell_lores", "DARK CANTRIP"),
    ("spell_lores", "SHROUD IN DARKNESS"),
    ("manifestation_lores", "SUMMON EIGHTFOLD DOOM-SIGIL"),
]


def _renown_army_frf_json(abilities: list[tuple[str, str]]) -> str:
    """Construit un `data/json/faction_rules_fr.json` de test avec, pour chaque
    `(catégorie, wahapedia_name)` de `abilities`, un correctif minimal sous
    `renown_armies."Legion of the First Prince"` — assez pour vérifier la
    plomberie (`_renown_army_pool`/`resolve_rules`), pas un vérbatim réel."""
    import json as _json

    by_category: dict[str, list[dict]] = {}
    for category, wahapedia_name in abilities:
        by_category.setdefault(category, []).append({
            "wahapedia_name": wahapedia_name,
            "name": f"FR : {wahapedia_name}",
            "description": f"<b>Texte français de test pour {wahapedia_name}.</b>",
            "origin": "BT",
        })
    return _json.dumps({
        "factions": {
            "Slaves to Darkness": {
                "renown_armies": {"Legion of the First Prince": by_category},
            },
        },
    })


def test_build_roster_pdf_mode_fr_renown_army_full_coverage(tmp_path):
    """Les 9 aptitudes de l'Armée de Renom sont curées : elle doit rejoindre
    la carte de règles fusionnée en français et disparaître de l'annexe
    anglaise (contrairement au mode `hybrid`, cf.
    `test_build_roster_pdf_falls_back_to_wahapedia_for_army_of_renown`)."""
    frf_path = tmp_path / "faction_rules_fr.json"
    frf_path.write_text(_renown_army_frf_json(_LEGION_OF_THE_FIRST_PRINCE_ABILITIES), encoding="utf-8")
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(_STD_FIRST_PRINCE_LIST, out_path=out_path, mode="fr", faction_rules_fr_path=frf_path)

    assert "Legion of the First Prince — Army of Renown Rules (EN, Wahapedia)" not in result.wahapedia_used
    assert "Armée de Renom — Legion of the First Prince" in result.rules_included
    # espaces normalisés : un titre d'aptitude long peut passer sur 2 lignes
    text = " ".join("".join(p.extract_text() for p in PdfReader(str(out_path)).pages).split())
    assert "FR : FIRST-DAMNED PRINCE" in text
    assert "Texte français de test pour SUMMON EIGHTFOLD DOOM-SIGIL" in text


def test_build_roster_pdf_mode_fr_renown_army_partial_coverage_keeps_wahapedia_fallback(tmp_path):
    """Curation incomplète (1 aptitude sur 9) : l'Armée de Renom entière doit
    rester dans l'annexe anglaise plutôt que de mélanger français patché et
    anglais non patché sur la carte fusionnée sans le signaler."""
    frf_path = tmp_path / "faction_rules_fr.json"
    frf_path.write_text(_renown_army_frf_json(_LEGION_OF_THE_FIRST_PRINCE_ABILITIES[:1]), encoding="utf-8")
    out_path = tmp_path / "out.pdf"
    result = build_roster_pdf(_STD_FIRST_PRINCE_LIST, out_path=out_path, mode="fr", faction_rules_fr_path=frf_path)

    assert "Legion of the First Prince — Army of Renown Rules (EN, Wahapedia)" in result.wahapedia_used
    assert "Armée de Renom — Legion of the First Prince" not in result.rules_included


def test_build_roster_pdf_mode_hybrid_ignores_renown_army_curation(tmp_path):
    """Le vérbatim français ne doit jamais s'appliquer en `hybrid`/`en` —
    même garantie que `_fr_patch` pour les autres catégories."""
    frf_path = tmp_path / "faction_rules_fr.json"
    frf_path.write_text(_renown_army_frf_json(_LEGION_OF_THE_FIRST_PRINCE_ABILITIES), encoding="utf-8")
    result = build_roster_pdf(
        _STD_FIRST_PRINCE_LIST, out_path=tmp_path / "out.pdf", mode="hybrid", faction_rules_fr_path=frf_path,
    )
    assert "Legion of the First Prince — Army of Renown Rules (EN, Wahapedia)" in result.wahapedia_used
    assert "Armée de Renom — Legion of the First Prince" not in result.rules_included


def test_delusion_cluster_groups_chooser_and_delusions_at_start_of_turn():
    from aospy.tournament_kit.pdf_builder import _CHOICE_CLUSTERS, _choice_cluster
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    spec = next(c for c in _CHOICE_CLUSTERS if c.category == "delusion")
    chooser = AbilityEntry("Royaume Délirant", "", "", keywords="BT", ability_phase="Start of Turn")
    combat = AbilityEntry("Banquet Glorieux", "", "", keywords="Delusion,BT", ability_phase="Combat Phase")
    other = AbilityEntry("Sang Royal", "", "", keywords="BT", ability_phase="Hero Phase")
    cluster = _choice_cluster([chooser, combat, other], spec)
    assert [ab.name for ab in cluster] == ["Royaume Délirant", "Banquet Glorieux"]
    assert all(ab.ability_phase == "Start of Turn" and ab.ability_category == "delusion" for ab in cluster)
    assert _choice_cluster([chooser, other], spec) == []


def test_blood_tithe_cluster_orders_skulls_then_blood_drenched_then_options_by_cost():
    from aospy.tournament_kit.pdf_builder import _apply_choice_clusters
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    def bt(name, phase, cost):
        return AbilityEntry(name, "", "", keywords="Blood Tithe", ability_phase=phase,
                            points_type="Blood tithe", points=cost)

    drenched = AbilityEntry("Trempés de Sang", "", "", ability_phase="Start of Turn", is_reaction=True)
    skulls = AbilityEntry("Des Crânes pour le Trône de Crânes", "", "", ability_phase="Start of Turn")
    slaughter = bt("Massacre Triomphal", "Combat Phase", "4")
    scorn = bt("Mépris Divin", "Start of Turn", "1")
    pool = [drenched, slaughter, skulls, scorn]

    out = _apply_choice_clusters(pool, "fr-extended")
    cluster = [ab for ab in out if ab.ability_category == "blood_tithe"]
    assert [ab.name for ab in cluster] == [
        "Des Crânes pour le Trône de Crânes", "Trempés de Sang", "Mépris Divin", "Massacre Triomphal",
    ]
    # l'option hors « Début de tour » reste aussi à sa place, les autres sont déplacées
    assert [ab.name for ab in out if ab.ability_category != "blood_tithe"] == ["Massacre Triomphal"]
    assert _apply_choice_clusters(pool, "fr") == pool


def test_cast_badge_shapes_are_unique():
    # règle : chaque type de coût (sort, prière, PC, dîme de sang...) a sa
    # propre silhouette, jamais partagée avec un autre type.
    from aospy.tournament_kit.warscroll_card import _CAST_BADGE_SHAPES

    shapes = list(_CAST_BADGE_SHAPES.values())
    assert len(shapes) == len(set(shapes))


def test_choice_cluster_copy_stays_at_start_of_turn_despite_condition_phase():
    from aospy.tournament_kit.pdf_builder import _CHOICE_CLUSTERS, _choice_cluster
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import classify_phase

    spec = next(c for c in _CHOICE_CLUSTERS if c.category == "blood_tithe")
    punish = AbilityEntry("Punissez les Pacifistes", "", "", keywords="Blood Tithe",
                          condition="Once Per Turn (Army), Your Combat Phase", ability_phase="Combat Phase")
    assert classify_phase(punish) == "melee"
    assert [classify_phase(ab) for ab in _choice_cluster([punish], spec)] == ["start"]


def test_khaine_blessing_cluster_moves_blood_rites_then_blessings_to_end_of_turn():
    from aospy.tournament_kit.pdf_builder import _apply_choice_clusters
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import classify_phase

    rites = AbilityEntry("Rites de Sang", "", "", condition="Passive", ability_phase="Start of Turn")
    blessings = AbilityEntry("Bénédictions de Khaine", "", "", condition="Once Per Turn (Army), End of Any Turn",
                             ability_phase="End of Turn")
    other = AbilityEntry("Ritualiste Consacrée", "", "", ability_phase="Start of Turn")

    out = _apply_choice_clusters([rites, other, blessings], "fr-split")
    assert [ab.name for ab in out] == ["Ritualiste Consacrée", "Rites de Sang", "Bénédictions de Khaine"]
    assert [ab.ability_category for ab in out] == ["", "khaine_blessing", "khaine_blessing"]
    assert {classify_phase(ab) for ab in out[1:]} == {"end"}
    assert _apply_choice_clusters([other], "fr-split") == [other]


def test_choice_cluster_moves_reactions_to_the_choice_ability():
    from aospy.tournament_kit.pdf_builder import _apply_choice_clusters
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    blessings = AbilityEntry("Bénédictions de Khaine", "", "", condition="Once Per Turn (Army), End of Any Turn",
                             ability_phase="End of Turn")
    offerings = AbilityEntry(
        "Offrandes Pourpres", "", "", is_reaction=True, ability_phase="End of Turn",
        condition="Once Per Turn (Army), Reaction: You declared the ‘%000021998Blessings of Khaine%’ ability",
    )
    redeploy = AbilityEntry("Autre", "", "", condition="Reaction: You declared the ‘%000009837Redeploy%’ command")

    out = _apply_choice_clusters([offerings, redeploy, blessings], "fr-extended")
    assert [(ab.name, ab.ability_category) for ab in out] == [
        ("Autre", ""), ("Bénédictions de Khaine", "khaine_blessing"), ("Offrandes Pourpres", "khaine_blessing"),
    ]


def test_delusion_cluster_also_applies_in_fr_extended():
    from aospy.tournament_kit.pdf_builder import _apply_choice_clusters
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    combat = AbilityEntry("Banquet Glorieux", "", "", keywords="Delusion", ability_phase="Combat Phase")
    out = _apply_choice_clusters([combat], "fr-extended")
    assert [ab.ability_category for ab in out] == ["", "delusion"]


def test_choice_section_is_its_own_chunk_with_a_taller_page_budget():
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import (
        _MAX_CHOICE_HEIGHT, _MAX_GROUP_HEIGHT, _choice_segments, _keyword_pills,
    )

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
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import is_self_profile_modifier

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


def test_mark_self_profile_survives_french_patch():
    """Décidé sur le texte Wahapedia, le marquage survit au correctif
    français qui traduit le nom de l'arme dans le texte seulement."""
    from aospy.tournament_kit.pdf_builder import _mark_self_profile
    from aospy.tournament_kit.translation.faction_rules_fr import apply_fr_overrides
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry, WarscrollData, WeaponEntry
    from aospy.tournament_kit.warscroll_card import is_self_profile_modifier

    en = "<b>Effect:</b> If this unit charged this turn, add 1 to the Rend characteristic of its <b>Cursed Lances</b>."
    weapon = WeaponEntry(*(["Cursed Lance"] + [""] * (len(WeaponEntry.__dataclass_fields__) - 1)))
    ws = WarscrollData(
        "Chaos Knights", "", "", "", "", "", "", "", "", "", "", [], [weapon],
        [AbilityEntry("Impaling Charge", en, "", condition="Passive")],
    )
    ws = _mark_self_profile(ws)
    fr = "<b>Effet :</b> Si cette unité a chargé à ce tour, ajoutez 1 à la Perforation de ses Lances Maudites."
    patched = apply_fr_overrides(ws.abilities, [{"wahapedia_name": "Impaling Charge", "name": "Charge Empaleuse", "description": fr}])
    assert is_self_profile_modifier(patched[0], [weapon.name])


def test_order_deploy_game_sequence_full_width():
    from aospy.tournament_kit.pdf_builder import _order_deploy
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    names = ["Autre", "Souffler sur les Braises", "Déploiement d’Unité", "Placez le Champ de Bataille"]
    out = _order_deploy([AbilityEntry(name=n, description="", legend="") for n in names])
    assert [ab.name for ab in out] == ["Placez le Champ de Bataille", "Déploiement d’Unité", "Souffler sur les Braises", "Autre"]
    assert [ab.full_width for ab in out] == [True, True, True, False]


def test_tactic_special_rules_join_deployment():
    from types import SimpleNamespace
    from aospy.tournament_kit.pdf_builder import _tactic_special_rules
    from aospy.tournament_kit.translation.tactic_cards import load_tactic_cards
    parsed = SimpleNamespace(battle_tactic_cards=["Blazing Onslaught", "Siege of Ashes"])
    (rule,) = _tactic_special_rules(parsed, load_tactic_cards())
    assert rule.name == "Assaut Flamboyant : Règle Spéciale" and "repaire" in rule.description
    assert rule.ability_phase == "Deployment Phase" and rule.full_width


def test_translate_reaction_trigger():
    from aospy.tournament_kit.warscroll_card import _translate_trigger
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
    from aospy.tournament_kit import warscroll_card as wc
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    labels = []
    monkeypatch.setattr(wc, "_pill", lambda text, *a, **k: labels.append(text))
    ability = AbilityEntry("X", "", "", keywords="Core, Move, Delusion, BT")
    try:
        wc.set_french_keywords(True)
        wc._keyword_pills(ability)
        assert labels == ["BASE", "MOUVEMENT", "DELUSION", "BT"]
        labels.clear()
        wc.set_french_keywords(False)
        wc._keyword_pills(ability)
        assert labels == ["CORE", "MOVE", "DELUSION", "BT"]
    finally:
        wc.set_french_keywords(False)


def test_phase_keyword_pills_use_their_phase_band_color(monkeypatch):
    from aospy.tournament_kit import warscroll_card as wc
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    colors = {}
    monkeypatch.setattr(wc, "_pill", lambda text, bg, fg, **k: colors.__setitem__(text, (bg, fg)))
    wc._keyword_pills(AbilityEntry("X", "", "", keywords="Fight, Tir, Charge, Course, Repli, Core, Unbind, Bannissement, Attack, BT"))
    assert colors["FIGHT"] == wc._PHASE_COLORS["melee"]
    assert colors["TIR"] == wc._PHASE_COLORS["shoot"]
    assert colors["CHARGE"] == wc._PHASE_COLORS["charge"]
    assert colors["COURSE"] == colors["REPLI"] == wc._PHASE_COLORS["move"]
    assert colors["CORE"] == ("#141414", "#f2ecdb")
    assert colors["UNBIND"] == colors["BANNISSEMENT"] == (wc._BADGE_SPELL, wc._CAST_BADGE_FG["Spell"])
    assert colors["ATTACK"] == (wc._BADGE_MULTI_PHASE, "#eef0f3")


def test_no_keyword_pill_uses_hero_phase_yellow(monkeypatch):
    from aospy.tournament_kit import warscroll_card as wc
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    colors = {}
    monkeypatch.setattr(wc, "_pill", lambda text, bg, fg, **k: colors.__setitem__(text, (bg, fg)))
    wc._keyword_pills(AbilityEntry("X", "", "", keywords="Sort, Summon, Convocation, Prière, Prayer, Rampage, Saccage, Inconnu, BT"))
    spell = (wc._BADGE_SPELL, wc._CAST_BADGE_FG["Spell"])
    prayer = (wc._BADGE_PRAYER, wc._CAST_BADGE_FG["Prayer"])
    assert colors["SORT"] == colors["SUMMON"] == colors["CONVOCATION"] == spell
    assert colors["PRIÈRE"] == colors["PRAYER"] == prayer
    assert colors["RAMPAGE"] == colors["SACCAGE"] == (wc._BADGE_MULTI_PHASE, "#eef0f3")
    assert colors["INCONNU"] == (wc._BADGE_KEYWORD, "#f2eeea")


def test_cast_badge_legend_lists_only_drawn_shapes_in_canonical_order():
    from aospy.tournament_kit.warscroll_card import cast_badge_legend

    legend = cast_badge_legend(frozenset({"drop", "circle"}))
    assert [badge.shape for badge, _text in legend] == ["circle", "drop"]
    assert legend[0][1].startswith("Aptitude : valeur de lancement")
    assert cast_badge_legend(frozenset()) == []


def test_default_output_path_groups_by_team_then_list(tmp_path):
    lists_dir = tmp_path / "listes"
    out_dir = tmp_path / "roster"
    in_team = lists_dir / "Melusior" / "KB L3 Ruze.txt"
    assert default_output_path(in_team, "fr-split-simple", lists_dir, out_dir) == (
        out_dir / "Melusior" / "KB L3 Ruze" / "KB L3 Ruze (fr-split-simple).pdf")
    # hybrid -> « defaut » ; liste hors du dossier des listes -> pas d'équipe
    elsewhere = tmp_path / "ailleurs" / "STD Nath.txt"
    assert default_output_path(elsewhere, "hybrid", lists_dir, out_dir) == (
        out_dir / "STD Nath" / "STD Nath (defaut).pdf")


def test_enemy_turn_drops_charge_reroll_unless_charge_keyword():
    """« En Avant, vers la Victoire » quitte « Tour adverse », sauf si une
    autre aptitude de cette carte porte le mot-clé Charge."""
    from aospy.tournament_kit.pdf_builder import _drop_enemy_charge_reroll
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    reroll = AbilityEntry("En Avant, vers la Victoire", "", "", ability_phase="Charge Phase")
    counter = AbilityEntry("Contre-Charge", "", "", condition="Enemy Charge Phase")
    assert _drop_enemy_charge_reroll([reroll, counter]) == [counter]
    ambush = AbilityEntry("Drawn to Magic", "", "", keywords="Core, Move, Charge", condition="Any Charge Phase")
    assert _drop_enemy_charge_reroll([reroll, counter, ambush]) == [reroll, counter, ambush]
    glued = AbilityEntry("Paramount Hunter", "", "", keywords="Core, Move, Charge Rampage")
    assert reroll in _drop_enemy_charge_reroll([reroll, glued])


def test_generic_core_abilities_english_layer_replaces_matched_entries(tmp_path):
    from aospy.tournament_kit.translation.generic_core_abilities import load_generic_core_abilities

    fr_path = tmp_path / "generic.json"
    fr_path.write_text(json.dumps([
        {"name": "Dissipation", "requires_unit_keyword": "WIZARD", "description": "fr",
         "condition": "Reaction: L’adversaire a annoncé une aptitude de Sort", "ability_phase": "Hero Phase"},
        {"name": "Attaque en Règle", "description": "fr", "points_type": "Command", "points": "1"},
    ]), encoding="utf-8")
    en_path = tmp_path / "generic_en.json"
    en_path.write_text(json.dumps([
        {"fr_name": "Dissipation", "name": "Unbind", "description": "en",
         "condition": "Reaction: Opponent declared a Spell ability", "keywords": "Unbind"},
    ]), encoding="utf-8")
    unbind, all_out = load_generic_core_abilities(fr_path, en_path=en_path)
    assert (unbind.name, unbind.description, unbind.condition) == ("Unbind", "en", "Reaction: Opponent declared a Spell ability")
    assert unbind.keywords == "Unbind, Core Rules" and unbind.ability_phase == "Hero Phase"
    # sans ligne anglaise : l'entrée française reste telle quelle
    assert (all_out.name, all_out.points) == ("Attaque en Règle", "1")
    # `requires_unit_keyword` vient de l'entrée française
    assert [ab.name for ab in load_generic_core_abilities(fr_path, frozenset({"HERO"}), en_path=en_path)] == ["Attaque en Règle"]


def test_generic_core_abilities_english_file_matches_french_names():
    """Chaque ligne de `generic_core_abilities_en.json` remplace une entrée
    française existante (une faute de `fr_name` la rendrait silencieusement inopérante)."""
    from aospy.tournament_kit.translation.generic_core_abilities import (
        DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE, DEFAULT_GENERIC_CORE_ABILITIES_FILE,
    )

    fr_names = {row["name"] for row in json.loads(DEFAULT_GENERIC_CORE_ABILITIES_FILE.read_text(encoding="utf-8"))}
    en_rows = json.loads(DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE.read_text(encoding="utf-8"))
    assert {row["fr_name"] for row in en_rows} <= fr_names


def test_english_layers_cover_every_french_entry():
    """Season rules, tactic cards and generic abilities: every French entry
    has its English counterpart (`en-split-simple` stays fully English)."""
    from aospy.tournament_kit.translation.generic_core_abilities import load_generic_core_abilities
    from aospy.tournament_kit.translation.season_rules import DEFAULT_SEASON_RULES_EN_FILE, load_season_rules
    from aospy.tournament_kit.translation.tactic_cards import DEFAULT_TACTIC_CARDS_EN_FILE, load_tactic_cards
    from aospy.tournament_kit.translation.generic_core_abilities import DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE

    fr_season = {ab.name for ab in load_season_rules()}
    en_season = {ab.name for ab in load_season_rules(en_path=DEFAULT_SEASON_RULES_EN_FILE)}
    assert not fr_season & en_season
    en_names = {row["name"] for row in json.loads(DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE.read_text(encoding="utf-8"))}
    assert {ab.name for ab in load_generic_core_abilities(en_path=DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE)} <= en_names
    cards = load_tactic_cards(en_path=DEFAULT_TACTIC_CARDS_EN_FILE)
    assert cards and all(card.english for card in cards.values())
    # clés = noms de l'export de liste, inchangées ; type et points du français
    assert cards.keys() == load_tactic_cards().keys()
    first = cards["Blazing Onslaught"]
    assert first.sub_tactics[0].name == "Master of Arms" and first.sub_tactics[0].kind == "Échauffourée"
    assert "hideout" in first.special_rule


def test_default_output_path_en_split_simple(tmp_path):
    lists = tmp_path / "lists"
    (lists / "Equipe").mkdir(parents=True)
    path = default_output_path(lists / "Equipe" / "Ma liste.txt", "en-split-simple", lists_dir=lists, output_dir=tmp_path / "out")
    assert path == tmp_path / "out" / "Equipe" / "Ma liste" / "Ma liste (en-split-simple).pdf"


def test_build_roster_pdf_mode_en_split_simple_uses_english_labels(tmp_path):
    from aospy.tournament_kit import warscroll_card as wc

    out_path = tmp_path / "out.pdf"
    build_roster_pdf(_LRL_LIST, out_path=out_path, mode="en-split-simple")
    text = "\n".join(page.extract_text() for page in PdfReader(str(out_path)).pages)
    assert "MY TURN" in text and "OPPONENT'S TURN" in text
    assert "MON TOUR" not in text and "Mon tour" not in text
    # verbatim Core Rules anglais pour une aptitude générique couverte
    assert "Normal Move" in text and "Mouvement Normal" not in text
    assert "Simmering Rage" in text and "Rage Bouillonnante" not in text
    # l'état global des libellés ne fuit pas vers le PDF suivant
    build_roster_pdf(_LRL_LIST, out_path=tmp_path / "fr.pdf", mode="fr-split")
    assert not wc.english_labels()


@pytest.mark.parametrize("mode", ["hybrid", "fr-extended"])
def test_build_roster_pdf_non_split_modes_put_warscrolls_before_rule_card(tmp_path, mode):
    # hors modes split, les warscrolls suivent directement la couverture,
    # avant la carte de règles fusionnée « Aptitudes »
    out_path = tmp_path / "out.pdf"
    build_roster_pdf(_LRL_LIST, out_path=out_path, mode=mode)
    pages = [" ".join(p.extract_text().split()).upper() for p in PdfReader(str(out_path)).pages]
    first_warscroll = next(i for i, t in enumerate(pages) if "HURAKAN WINDMAGE" in t and i > 0)
    rule_card = next(i for i, t in enumerate(pages) if t.startswith("APTITUDES"))
    assert first_warscroll < rule_card


def test_build_roster_pdf_hybrid_applies_fr_names_but_keeps_ability_text(tmp_path):
    # mode par défaut : sous-titre français sous le nom anglais (politique de
    # noms FR/EN), mais le texte des aptitudes reste celui de Wahapedia (EN)
    out_path = tmp_path / "out.pdf"
    build_roster_pdf(_LRL_LIST, out_path=out_path, mode="hybrid")
    text = " ".join("".join(p.extract_text() for p in PdfReader(str(out_path)).pages).split())
    assert "Sevireth, Lord of the Seventh Wind" in text
    assert "Sevireth, Seigneur du Septième Vent" in text
    assert "Effect:" in text


def test_provenance_note_does_not_make_a_synthesis_a_profile_modifier():
    """La note grise d'une synthèse peut citer une aptitude homonyme d'une
    arme (« Staff of the Horned Rat ») : la synthèse part quand même sur les
    cartes de tour."""
    from aospy.tournament_kit.translation.roster_simplifications import _NOTE_MARKUP
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import is_self_profile_modifier

    synthesis = AbilityEntry(
        "Casting Roll", "+1 to casting rolls." + _NOTE_MARKUP.format("Staff of the Horned Rat"), "", condition="Passive",
    )
    assert not is_self_profile_modifier(synthesis, ["Staff of the Horned Rat"])


def test_clean_html_unwraps_escaped_keyword_span():
    # FEC « The One True King » : balise de mot-clé échappée dans le scrape
    from aospy.tournament_kit.pdf_builder import clean_html
    raw = ('While you believe this <a href="/x"><span class="kwb2 kwbu">&lt;<span class="kwb3">S</span>PAN</span> '
           '<span class="kwb kwbu">CLASS="KWB</span> <span class="kwb kwbu">KWBU"&gt;DELUSION&lt;/SPAN&gt;</span></a>:')
    assert clean_html(raw) == "While you believe this <b>DELUSION</b>:"


def test_clean_html_fixes_known_wahapedia_typos():
    from aospy.tournament_kit.pdf_builder import clean_html
    assert "effect of that DELUSION applies" in clean_html("In such cases, the eect of that D  applies as if")


def test_identical_warscroll_abilities_merge_ignoring_flavor_text():
    from aospy.tournament_kit.pdf_builder import _warscroll_ability_pool
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry, WarscrollData

    def ws(name, flavor):
        ab = AbilityEntry("Descendez-les", f"<i>{flavor}</i><br/><br/><b>Effet :</b> +1 touche.", "",
                          condition="Your Shooting Phase", ability_phase="Shooting Phase")
        return WarscrollData(name, "KB", "", "", "", "", "", "", "", "", "", [], [], [ab])

    pool = _warscroll_ability_pool([ws("Boltboyz", "Tirs ajustés."), ws("Killbow", "Tirs mortels.")])
    assert [(ab.name, ab.warscrolls) for ab in pool] == [("Descendez-les", ("Boltboyz", "Killbow"))]


def test_chaos_pledge_cluster_in_hero_phase_keeps_pledges_where_used():
    from aospy.tournament_kit.pdf_builder import _apply_choice_clusters, _fold_warscroll_copies, _turn_sides
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry
    from aospy.tournament_kit.warscroll_card import TURN_ENEMY, TURN_MINE, classify_phase

    pledge = AbilityEntry("Vocation au Chaos", "", "", condition="Once Per Turn (Army), Your Hero Phase",
                          ability_phase="Hero Phase")
    khorne = AbilityEntry("Voué à Khorne", "<b>Effet :</b> +1 A.", "", condition="Passive", ability_phase="Combat Phase")
    khorne_ws = AbilityEntry("Voué à Khorne", "<i>Rage.</i><br/><br/><b>Effet :</b> +1 A.", "", condition="Passive",
                             ability_phase="Combat Phase", warscrolls=("Chaos Knights",))
    nurgle = AbilityEntry("Voué à Nurgle", "", "", condition="Passive", ability_phase="Defensive reaction")

    folded = _fold_warscroll_copies([pledge, khorne, nurgle, khorne_ws])
    assert [(ab.name, ab.warscrolls) for ab in folded] == [
        ("Vocation au Chaos", ()), ("Voué à Khorne", ("Chaos Knights",)), ("Voué à Nurgle", ()),
    ]
    out = _apply_choice_clusters(folded, "fr-split")
    cluster = [ab for ab in out if ab.ability_category == "chaos_pledge"]
    assert [ab.name for ab in cluster] == ["Vocation au Chaos", "Voué à Khorne", "Voué à Nurgle"]
    assert {classify_phase(ab) for ab in cluster} == {"hero"}
    # chaque vœu reste aussi dans sa phase d'usage
    assert [classify_phase(ab) for ab in out if ab.ability_category == ""] == ["melee", "any"]
    # la sous-section suit le tour de « Vocation au Chaos » (votre phase des héros)
    assert all(_turn_sides(ab, out) == {TURN_MINE} for ab in cluster)
    assert _turn_sides(out[0], out) == {TURN_MINE, TURN_ENEMY}


def test_two_column_packing_fills_short_column_and_backfills_page():
    from reportlab.platypus import PageBreak, Spacer, Table

    from aospy.tournament_kit.warscroll_card import pack_cards_two_columns

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

    from aospy.tournament_kit.warscroll_card import pack_cards_two_columns

    cards = [Spacer(1, h) for h in (600, 500, 150, 150, 150)]
    groups = [None, None, "manifestation", "manifestation", "manifestation"]
    story = pack_cards_two_columns(cards, [c.height for c in cards], page_height=760, groups=groups)
    # les 3 manifestations (450 + écarts) ne tiennent plus ensemble sur la
    # page 1 (reste 160 et 246) : elles partent toutes sur la page 2
    assert [type(x) for x in story] == [Table, PageBreak, Table]
    page2 = [c for col in story[2]._cellvalues[0] if isinstance(col, list) for c in col if c in cards]
    assert sorted(page2, key=cards.index) == cards[2:]


def test_split_enemy_turn_card_drops_at_the_double(tmp_path, monkeypatch):
    import aospy.tournament_kit.pdf_builder as pb

    cards = []
    real = pb.render_rule_card
    monkeypatch.setattr(pb, "render_rule_card", lambda t, a, *x, **k: (cards.append((t, list(a or []))), real(t, a, *x, **k))[1])
    build_roster_pdf(_LRL_LIST, out_path=tmp_path / "out.pdf", mode="fr-split")
    names = {title: {ab.name for ab in abilities} for title, abilities in cards}
    assert "Au Pas de Course" in names["Mon tour"]
    assert "Au Pas de Course" not in names["Tour adverse"]


def test_scenario_cards_go_four_per_a4_page(tmp_path):
    from pypdf import PdfWriter

    from aospy.tournament_kit.pdf_builder import _append_scenario_pages

    src = PdfWriter()
    for _ in range(5):
        src.add_blank_page(width=308, height=464)
    path = tmp_path / "scen.pdf"
    with open(path, "wb") as fh:
        src.write(fh)
    out = PdfWriter()
    _append_scenario_pages(out, path)
    assert len(out.pages) == 2
    assert round(float(out.pages[0].mediabox.width)) == 595
    _append_scenario_pages(out, tmp_path / "absent.pdf")
    assert len(out.pages) == 2


def test_scenario_variant_path():
    from pathlib import Path

    from aospy.tournament_kit.pdf_builder import scenario_variant_path

    assert scenario_variant_path(Path("d/L (fr-split-simple).pdf")) == Path("d/L (fr-split-simple-scenar).pdf")
    assert scenario_variant_path(Path("d/out.pdf")) == Path("d/out (scenar).pdf")


def test_split_drops_alias_card_identical_to_its_unit():
    from dataclasses import replace

    from aospy.tournament_kit.pdf_builder import _drop_identical_alias_cards
    from aospy.tournament_kit.translation.wahapedia_lookup import WarscrollData

    base = WarscrollData("Verminlord Warbringer", "ST", "", "", '10"', "4+", "5", "13", "5+", "1", "260", ["HERO"], [], [])
    alias = replace(base, name="Warbringer riche", subtitle="Verminlord Warbringer")
    sources = {"Warbringer riche": "Verminlord Warbringer"}
    assert _drop_identical_alias_cards([base, alias], sources) == [base]
    # une différence (points d'une optimisation payante) garde la carte
    paid = replace(alias, points="260+10")
    assert _drop_identical_alias_cards([base, paid], sources) == [base, paid]


def test_section_order_puts_named_unit_section_first_in_its_phase():
    from dataclasses import replace

    from aospy.tournament_kit.pdf_builder import _apply_section_order
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    base = AbilityEntry(name="X", description="d", legend="", condition="Your Hero Phase", ability_phase="Hero Phase")
    skreech = replace(base, name="Rat", warscrolls=("Lord Skreech Verminking",))
    thanquol = replace(base, name="Jet", warscrolls=("Thanquol on Boneripper",))
    out = _apply_section_order([thanquol, skreech], {"hero": ("Lord Skreech Verminking",)})
    assert out[1].section_rank is not None and out[1].section_rank < 0
    assert out[0].section_rank is None


def test_alias_pill_dropped_when_base_unit_also_carries_the_ability():
    from aospy.tournament_kit.pdf_builder import _collapse_alias_pills
    from aospy.tournament_kit.translation.wahapedia_lookup import AbilityEntry

    both = AbilityEntry(name="Coup", description="d", legend="", warscrolls=("Rich", "Verminlord Warbringer"))
    alone = AbilityEntry(name="Soupe", description="d", legend="", warscrolls=("Rich",))
    out = _collapse_alias_pills([both, alone], {"Rich": "Verminlord Warbringer"})
    assert out[0].warscrolls == ("Verminlord Warbringer",)
    assert out[1].warscrolls == ("Rich",)


def test_added_caster_level_replaces_existing_one():
    from aospy.tournament_kit.pdf_builder import _merge_unit_keywords

    assert _merge_unit_keywords(["HERO", "WIZARD (1)"], ["WIZARD (2)"]) == ["HERO", "WIZARD (2)"]
    assert _merge_unit_keywords(["HERO", "PRIEST (1)"], ["WIZARD (1)"]) == ["HERO", "PRIEST (1)", "WIZARD (1)"]
