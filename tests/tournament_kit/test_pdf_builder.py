"""Test d'intégration léger : assemblage du PDF avec une liste, l'index, le
battletome et le repli Wahapedia réels (nécessite l'extra [roster])."""

from __future__ import annotations

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
    # cf. `render/layout._ability_group_body_columns_mixed` — vérifié
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
    assert "Regiment of Renown — The Exiled One" in text[skarbrand_idx : skarbrand_idx + 400]
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
        _LRL_LIST,
        out_path=tmp_path / "out.pdf",
        wahapedia_dir=tmp_path / "no-such-wahapedia-dir",
        mode="hybrid",
    )
    assert result.rules_unmatched == []
    assert "Formations de Bataille" in result.rules_included
    assert "Traits Héroïques et Artefacts de Pouvoir" in result.rules_included


def test_build_roster_pdf_mode_en_skips_french_page_copy_fallback(tmp_path):
    result = build_roster_pdf(
        _LRL_LIST,
        out_path=tmp_path / "out.pdf",
        wahapedia_dir=tmp_path / "no-such-wahapedia-dir",
        mode="en",
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
    result = build_roster_pdf(
        _LRL_LIST, out_path=out_path, mode="fr-extended", generic_core_abilities_path=generic_path
    )

    assert "Aptitudes Génériques — MdG26-27" in result.rules_included
    # carte sectionnée : un nom court peut tenir sur plusieurs lignes d'une
    # case de grille étroite
    text = " ".join("".join(p.extract_text() for p in PdfReader(str(out_path)).pages).split())
    assert "Aptitude Générique de Test" in text


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
    copy_start = next(
        i for i in range(mine, enemy) if "MV" in pages[i] and not pages[i].lstrip().startswith("MON TOUR")
    )
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
        by_category.setdefault(category, []).append(
            {
                "wahapedia_name": wahapedia_name,
                "name": f"FR : {wahapedia_name}",
                "description": f"<b>Texte français de test pour {wahapedia_name}.</b>",
                "origin": "BT",
            }
        )
    return _json.dumps(
        {
            "factions": {
                "Slaves to Darkness": {
                    "renown_armies": {"Legion of the First Prince": by_category},
                },
            },
        }
    )


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
        _STD_FIRST_PRINCE_LIST,
        out_path=tmp_path / "out.pdf",
        mode="hybrid",
        faction_rules_fr_path=frf_path,
    )
    assert "Legion of the First Prince — Army of Renown Rules (EN, Wahapedia)" in result.wahapedia_used
    assert "Armée de Renom — Legion of the First Prince" not in result.rules_included


def test_default_output_path_groups_by_team_then_list(tmp_path):
    lists_dir = tmp_path / "listes"
    out_dir = tmp_path / "roster"
    in_team = lists_dir / "Melusior" / "KB L3 Ruze.txt"
    assert default_output_path(in_team, "fr-split-simple", lists_dir, out_dir) == (
        out_dir / "Melusior" / "KB L3 Ruze" / "KB L3 Ruze (fr-split-simple).pdf"
    )
    # hybrid -> « defaut » ; liste hors du dossier des listes -> pas d'équipe
    elsewhere = tmp_path / "ailleurs" / "STD Nath.txt"
    assert default_output_path(elsewhere, "hybrid", lists_dir, out_dir) == (
        out_dir / "STD Nath" / "STD Nath (defaut).pdf"
    )


def test_default_output_path_en_split_simple(tmp_path):
    lists = tmp_path / "lists"
    (lists / "Equipe").mkdir(parents=True)
    path = default_output_path(
        lists / "Equipe" / "Ma liste.txt", "en-split-simple", lists_dir=lists, output_dir=tmp_path / "out"
    )
    assert path == tmp_path / "out" / "Equipe" / "Ma liste" / "Ma liste (en-split-simple).pdf"


def test_build_roster_pdf_mode_en_split_simple_uses_english_labels(tmp_path):
    from aospy.tournament_kit.render import text as render_text

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
    assert not render_text.english_labels()


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


def test_split_enemy_turn_card_drops_at_the_double(tmp_path, monkeypatch):
    import aospy.tournament_kit.pdf_builder as pb

    cards = []
    real = pb.render_rule_card
    monkeypatch.setattr(
        pb, "render_rule_card", lambda t, a, *x, **k: (cards.append((t, list(a or []))), real(t, a, *x, **k))[1]
    )
    build_roster_pdf(_LRL_LIST, out_path=tmp_path / "out.pdf", mode="fr-split")
    names = {title: {ab.name for ab in abilities} for title, abilities in cards}
    assert "Au Pas de Course" in names["Mon tour"]
    assert "Au Pas de Course" not in names["Tour adverse"]


def test_compact_export_army_of_renown_becomes_full_form():
    from types import SimpleNamespace

    from aospy.tournament_kit.list_parser import ParsedList
    from aospy.tournament_kit.pdf_builder import compact_renown

    def parsed(faction, allegiance):
        return ParsedList("t", faction, allegiance, None, None, None, None, [], [], [], [])

    wh = SimpleNamespace(
        available=True,
        find_renown_army_rules=lambda n: {"Battle Traits": [1]} if n in ("Zainthar Kai", "Lords of the Clan") else None,
        find_faction_category=lambda f, t, s: [1] if s == "Lords of the Clan" else None,
    )
    p = compact_renown(parsed("Daughters of Khaine", "Zainthar Kai"), wh)
    assert (p.faction, p.allegiance, p.army_of_renown) == ("Daughters of Khaine | Zainthar Kai", None, "Zainthar Kai")
    # formation de base homonyme : la formation l'emporte
    p = compact_renown(parsed("Sylvaneth", "Lords of the Clan"), wh)
    assert (p.faction, p.allegiance) == ("Sylvaneth", "Lords of the Clan")
    # format complet : inchangé
    p = compact_renown(parsed("Sylvaneth | Lords of the Clan", "Lords of the Clan"), wh)
    assert p.allegiance == "Lords of the Clan"
