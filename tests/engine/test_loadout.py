"""Tests de l'allocation des armes par modèle (``loadout.model_counts``).

Port des cas de StatHammer (mêmes clauses de description), adapté aux dataclasses
`Unit`/`Weapon` déjà typées d'aospy (pas de dés/texte à parser côté caractéristiques)."""

from __future__ import annotations

from aospy.engine.loadout import model_counts
from aospy.domain.models import Unit, Weapon


def _w(name, kind="melee", attacks=2, hit=3, wound=3, rend=0, damage=1):
    return Weapon(name=name, kind=kind, attacks=attacks, hit=hit, wound=wound,
                  rend=rend, damage=damage)


def _unit(description=None, models=1):
    return Unit(
        name="U", army_id=1, move=5, save=4, health=1, control=1,
        models=models, points=100, description=description,
    )


def test_default_every_model_carries_all_profiles():
    # Pas de description → règle AoS4 : tous les profils sur tous les modèles.
    weapons = [_w("Sword"), _w("Bow", "ranged")]
    counts, notes = model_counts(_unit(models=5), weapons)
    assert counts == [5, 5]
    assert notes == []


def test_fractional_replace_limits_special_weapon():
    weapons = [_w("Warhammer"), _w("Grandhammer", damage=2)]
    desc = ("<ul><li>Each model is armed with a Warhammer.</li>"
            "<li>1/5 models can replace their Warhammer with a Grandhammer.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=5), weapons)
    assert counts == [4, 1]  # 1 upgrade, 4 gardent le warhammer


def test_replace_both_weapons_drops_all_base():
    # 1/10 échange ses DEUX armes de base (pistolet + arme de main) contre une pique.
    weapons = [_w("Privateer Pistol", "ranged"), _w("Hand Weapon"),
               _w("Heavy Weapon", "ranged", damage=2, rend=1), _w("Skypike", damage=2, rend=1)]
    desc = ("<ul><li>Each model is armed with a Privateer Pistol and Hand Weapon.</li>"
            "<li>2/10 models can replace their Privateer Pistol with a Heavy Weapon.</li>"
            "<li>1/10 models can replace both their weapons with a Skypike.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=10), weapons)
    # pistolet : 10 − 2 (heavy) − 1 (skypike) ; main : 10 − 1 ; heavy : 2 ; skypike : 1
    assert counts == [7, 9, 2, 1]


def test_replace_credits_all_profiles_of_a_twin_weapon():
    # Une arme à DEUX profils (tir + mêlée, ex. un javelot) nommée dans un remplacement :
    # les deux profils suivent les porteurs, pas seulement le premier index.
    weapons = [_w("Hunter Javelin", "ranged", attacks=1, damage=2, rend=1),
               _w("Starstone Bolas", "ranged", attacks=1),
               _w("Hunter Javelin", "melee", attacks=3, wound=4, damage=2, rend=1),
               _w("Moonstone Club", attacks=2, wound=5)]
    desc = ("<ul><li>Each model is armed with Starstone Bolas and a Moonstone Club.</li>"
            "<li>1/5 models can replace their weapons with a Hunter Javelin.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=5), weapons)
    # 1 figurine prend le javelot (tir ET mêlée) ; 4 gardent bolas + club.
    assert counts == [1, 4, 1, 4]


def test_exclusive_choice_keeps_best_option():
    weapons = [_w("Whip"), _w("Great Weapon", damage=2, rend=1), _w("Hooves")]
    desc = ("<ul><li>This unit is armed with a Whip, Hooves and 1 of the following options:"
            "</li><li>Great Weapon</li><li>Whip</li></ul>")
    # Le « Great Weapon » (rend 1, dmg 2) domine ; les armes de base restent à size.
    counts, _ = model_counts(_unit(desc, models=1), weapons)
    assert counts[1] == 1  # great weapon retenu


def test_named_roster_one_weapon_per_model():
    weapons = [_w("Great Weapon", damage=2), _w("Rapier", damage=3), _w("Assortment"),
               _w("Bite")]
    desc = ("The Herald, Surgeon and Shepherd are each armed with an Assortment. "
            "The Knight is armed with a Great Weapon. "
            "The Blade is armed with a Rapier. "
            "The Mascot is armed with a Bite.")
    counts, _ = model_counts(_unit(desc, models=6), weapons)
    assert counts == [1, 1, 3, 1]  # 3 Assortment, 1 chacun des autres


def test_champion_replace_one_model():
    weapons = [_w("Drakegun", "ranged"), _w("Plated Fists"),
               _w("Grudgehammer Torpedo", "ranged", damage=2)]
    desc = ("<ul><li>Each model is armed with a Drakegun and Plated Fists.</li>"
            "<li>The champion can replace their Drakegun with a Grudgehammer Torpedo.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=10), weapons)
    assert counts == [9, 10, 1]  # 1 champion troque le drakegun


def test_additive_carry_does_not_remove_base():
    weapons = [_w("Punch Dagger"), _w("Saboteur Bombs", "ranged")]
    desc = ("<ul><li>Each model is armed with a Punch Dagger.</li>"
            "<li>1/10 models can be armed with Saboteur Bombs.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=10), weapons)
    assert counts == [10, 1]  # la base reste, les bombes s'ajoutent sur 1 modèle


def test_must_replace_their_weapons_drops_base():
    weapons = [_w("Vulkyn Weapons"), _w("Emberteeth", damage=2)]
    desc = ("<ul><li>Each model is armed with Vulkyn Weapons.</li><li>1/9 models is a "
            "Kyndledroth and must replace their weapons with Emberteeth.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=9), weapons)
    assert counts == [8, 1]


def test_numerator_is_the_count_for_named_subgroup():
    # « 1/2 Wardens can also be armed with X » → 1 figurine (numérateur), pas round(1/2·size).
    weapons = [_w("Twistroot Weapons"), _w("Warden's Bow", "ranged")]
    desc = ("<ul><li>Each model is armed with Twistroot Weapons.</li>"
            "<li>1/2 Twistroot Wardens can also be armed with a Warden's Bow.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=8), weapons)
    assert counts == [8, 1]


def test_armed_with_instead_of_and_in_addition():
    # Profil composite (type Wildercorps Hunters) : base + remplacements « instead of » +
    # arme additive du champion « in addition to ». La fraction « 1/11 » doit valoir 1 (pas 11).
    weapons = [_w("Crossbow", "ranged"), _w("Arbalest", "ranged", damage=2, rend=2),
               _w("Hunting Weapons"), _w("Ferocious Bite")]
    desc = ("<ul><li>Each model in this unit is armed with a Crossbow and Hunting Weapons.</li>"
            "<li>The champion is armed with a Ferocious Bite in addition to their other "
            "weapons.</li><li>1/11 models is an Arbalester and is armed with an Arbalest "
            "instead of a Crossbow.</li><li>4/11 models are Trailhounds and are armed with a "
            "Ferocious Bite instead of any other weapons.</li></ul>")
    counts, _ = model_counts(_unit(desc, models=11), weapons)
    # Crossbow : 11 − 1 (arbalester) − 4 (trailhounds) = 6 ; Arbalest : 1 ; Hunting Weapons :
    # 11 − 4 = 7 ; Bite : 4 trailhounds + 1 champion = 5.
    assert counts == [6, 1, 7, 5]


def test_exclusive_weapon_modes_keep_best():
    # « Arme: ModeA » / « Arme: ModeB » = modes exclusifs d'une même arme → 1 seul retenu,
    # même sans description. Le mode le plus dommageable gagne.
    weapons = [_w("Great Cannon: Cannonball", "ranged", attacks=1, damage=4, rend=1),
               _w("Great Cannon: Grapeshot", "ranged", attacks=6, damage=1, rend=0),
               _w("Crew Tools")]
    counts, notes = model_counts(_unit(models=1), weapons)
    assert counts[2] == 1                      # arme de base intacte
    assert sum(counts[:2]) == 1                # un seul mode de canon compté
    assert any("mode" in n for n in notes)


def test_unparsed_description_falls_back_to_default():
    weapons = [_w("Sword"), _w("Axe")]
    desc = "Models can replace weapons following arcane rites of the forge."
    counts, notes = model_counts(_unit(desc, models=4), weapons)
    assert counts == [4, 4]  # défaut conservé
    assert any("non reconnue" in n for n in notes)
