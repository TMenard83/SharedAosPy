"""Éligibilité et gain des optimisations (analysis/layers/bearers.py)."""

from __future__ import annotations

from aospy.abilities.source import bearer_restriction_of
from aospy.analysis.layers.bearers import eligible
from aospy.domain.models import Unit

VOCAB = frozenset({"HERO", "INFANTRY", "CAVALRY", "MONSTER", "BEAST", "WAR MACHINE", "UNIQUE", "WIZARD",
                   "BLADES OF KHORNE", "IRONJAWZ", "OGOR", "IRONSUNZ", "SLAVES TO DARKNESS", "STANDARD BEARER"})


def _u(name: str, *kws: str, hero: bool = False) -> Unit:
    k = set(kws) | ({"HERO"} if hero else set())
    return Unit(id=1, army_id=1, name=name, move=5, save=4, control=1, health=5, ward=None, points=100,
                models=1, is_hero=hero, keywords=frozenset(k), weapons=[])


def test_unique_units_never_take_enhancements():
    """Core Rules p. 37 : « UNIQUE units cannot be given enhancements »."""
    assert not eligible(_u("Skarbrand", "UNIQUE", "MONSTER", hero=True), "HERO only", "heroic_trait", VOCAB)
    assert eligible(_u("Bloodsecrator", "INFANTRY", hero=True), "HERO only", "heroic_trait", VOCAB)


def test_default_is_a_hero():
    assert eligible(_u("Lord", hero=True), "", "artefact", VOCAB)
    assert not eligible(_u("Warriors", "INFANTRY"), "", "artefact", VOCAB)
    assert not eligible(_u("Lord", "INFANTRY", hero=True), "", "monstrous_trait", VOCAB)


def test_non_hero_troop_enhancements():
    r = bearer_restriction_of("Brazen Mutations are unique enhancements that can be given to non-Hero Blades of "
                              "Khorne Infantry or Cavalry units. A unit can only have 1 Brazen Mutation.")
    assert eligible(_u("Bloodreavers", "BLADES OF KHORNE", "INFANTRY"), r, "enhancement", VOCAB)
    assert not eligible(_u("Slaughterpriest", "BLADES OF KHORNE", "INFANTRY", hero=True), r, "enhancement", VOCAB)
    assert not eligible(_u("Khorgorath", "BLADES OF KHORNE", "MONSTER"), r, "enhancement", VOCAB)


def test_keyword_and_exclusions():
    assert not eligible(_u("Tyrant", "OGOR", "IRONSUNZ", hero=True), "Non-OGOR IRONSUNZ HERO only", "artefact", VOCAB)
    assert eligible(_u("Megaboss", "IRONJAWZ", "MONSTER", hero=True), "IRONJAWZ MONSTER only", "artefact", VOCAB)
    excl = "HERO only excluding Cannonade Cogfort and Conqueror Cogfort"
    assert not eligible(_u("Cannonade Cogfort", hero=True), excl, "artefact", VOCAB)
    assert eligible(_u("Daemonsmith", hero=True), excl, "artefact", VOCAB)


def test_named_units_and_keyword_holders():
    r = "Cracked Heels are unique enhancements that can be given to Mancrusher Gargants"
    assert eligible(_u("Mancrusher Gargant", "MONSTER"), r, "enhancement", VOCAB)
    assert not eligible(_u("Gatebreaker", "MONSTER", hero=True), r, "enhancement", VOCAB)
    r = ("An Ensorcelled Banner is a unique enhancement that can be given to SLAVES TO DARKNESS INFANTRy and CAVALRy "
         "units with the STANDARD BEARER keyword")
    assert eligible(_u("Chaos Warriors", "SLAVES TO DARKNESS", "INFANTRY", "STANDARD BEARER"), r, "enhancement", VOCAB)
    assert not eligible(_u("Chaos Warriors", "SLAVES TO DARKNESS", "INFANTRY"), r, "enhancement", VOCAB)


def test_stray_space_after_non():
    r = ("Scars of War are unique enhancements that can be given to non- HERO non- BEAST STORMCAST ETERNALS units")
    vocab = VOCAB | {"STORMCAST ETERNALS"}
    assert eligible(_u("Liberators", "STORMCAST ETERNALS", "INFANTRY"), r, "enhancement", vocab)
    assert not eligible(_u("Lord-Celestant", "STORMCAST ETERNALS", "INFANTRY", hero=True), r, "enhancement", vocab)
    assert not eligible(_u("Gryph-hounds", "STORMCAST ETERNALS", "BEAST"), r, "enhancement", vocab)
