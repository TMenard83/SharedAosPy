"""Famille fonctionnelle d'un effet : ce qu'il FAIT, base de la qualité du mariage châssis × aptitude.

Couche 1 (hors contexte). Recadrage utilisateur du 2026-11-20 : chaque famille a ses propres critères de
mariage avec le châssis du porteur (couche 3) — un buff donné vaut par la capacité du porteur à tenir sa
bulle, un débuff ennemi par sa capacité à aller au contact, une mobilité par ce que le châssis fait en
arrivant… Familles (validées par l'utilisateur) :

* ``buff-perso-offensif`` / ``buff-perso-defensif`` : le porteur se boost lui-même (y compris « −1 pour
  toucher contre cette unité ») ;
* ``buff-donne`` : bulle, ordre, une unité amie, armée — le porteur boost d'autres unités (il peut aussi
  en profiter) ;
* ``debuff`` : affaiblit ou contraint une/des unités ennemies (il faut en général s'en approcher) ;
* ``degats-directs`` : blessures mortelles, élimination ;
* ``mobilite`` : mouvement, vol, téléportation, course + charge ;
* ``soin`` : soin, retour de figurines ;
* ``controle`` : score de contrôle, objectifs ;
* ``magie-ressource`` : lancement/prière/dissipation, PC, ressource de faction, invocation ;
* ``autre`` : le reste (auto-infligé, effets non classés).

Une aptitude porte une famille par effet (The Light of Sigmar : débuff OU soin) et une famille principale.
« Une fois par bataille avec condition sur le porteur » n'est pas une famille : c'est un trait transversal,
traité par les facteurs déclenchement × survie de la couche 3.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import Effect

FAMILIES: dict[str, str] = {
    "buff-perso-offensif": "le porteur améliore ses propres attaques",
    "buff-perso-defensif": "le porteur améliore sa propre durabilité",
    "buff-donne": "le porteur boost d'autres unités amies (bulle, ordre, cible amie, armée)",
    "debuff": "affaiblit ou contraint l'ennemi",
    "degats-directs": "blessures mortelles, élimination",
    "mobilite": "mouvement, vol, téléportation, course + charge",
    "soin": "soin, retour de figurines",
    "controle": "score de contrôle, objectifs",
    "magie-ressource": "magie, prière, PC, ressource de faction, invocation",
    "autre": "non classé",
}

_SELF_SCOPES = {"self"}
_FRIENDLY_SCOPES = {"one_friendly", "friendly_aura", "army"}
_ENEMY_SCOPES = {"one_enemy", "enemy_aura", "all_enemies"}

_OFF_STATS = {"hit", "wound", "attacks", "rend", "damage"}
_DEF_STATS = {"save", "ward", "health"}
_MOVE_STATS = {"move", "run", "charge"}
_MAGIC_STATS = {"cast", "chant", "unbind", "banish", "power_level"}

_OFF_KINDS = {
    "crit",
    "anti",
    "charge_bonus",
    "reroll",
    "strike_first",
    "extra_fight",
    "fight_twice",
    "extra_shoot",
    "shoot_in_combat",
    "stat_set",
    "keyword_gain",
    "range_bonus",
    "ignore_debuff",
    "snipe",
}
_DEF_KINDS = {"ward", "damage_ignore", "negate_attack", "untargetable", "damage_redirect"}
_DEBUFF_KINDS = {
    "strike_last",
    "restriction",
    "lockout",
    "move_debuff",
    "no_crit",
    "no_ward",
    "no_weapon_abilities",
    "taunt",
    "anti_heal",
    "strip_enhancement",
    "fury_debuff",
}
_MOBILITY_KINDS = {
    "move",
    "redeploy",
    "deep_strike",
    "run_and_charge",
    "run_and_shoot",
    "fly",
    "extra_move",
    "pile_in",
    "free_retreat",
}
_MAGIC_KINDS = {"anti_magic", "cp_gain", "resource", "summon", "extra_use", "tactic_cards"}

#: Départage de la famille principale à égalité d'effets (ordre d'importance pour le mariage).
_PRIORITY = (
    "buff-donne",
    "debuff",
    "degats-directs",
    "buff-perso-offensif",
    "buff-perso-defensif",
    "mobilite",
    "soin",
    "controle",
    "magie-ressource",
    "autre",
)


def _buff(scope: str, offensive: bool) -> str:
    if scope in _FRIENDLY_SCOPES:
        return "buff-donne"
    return "buff-perso-offensif" if offensive else "buff-perso-defensif"


def effect_family(e: Effect, scope: str) -> str:
    """Famille d'un effet, d'après sa nature, son camp et la portée de l'aptitude."""
    k, st, side = e.kind, e.stat, e.side
    if k == "stat_mod":
        if side == "enemy":
            # « −1 pour toucher aux attaques qui ciblent cette unité » : protection du porteur/des amis,
            # pas un débuff qu'il faut aller poser ; idem débuff de sauvegarde contre NOS attaques (offensif).
            if e.detail == "defensif" and scope not in _ENEMY_SCOPES:
                return _buff(scope, offensive=False)
            if e.detail == "debuff" and st in ("save", "ward") and scope not in _ENEMY_SCOPES:
                return _buff(scope, offensive=True)
            if st in _OFF_STATS and e.value > 0:
                # v35 : +1 pour toucher aux attaques ennemies contre cette unité (Dark Temptations) : une
                # contrepartie, pas un débuff à aller poser
                return "autre"
            return "debuff"
        if e.detail == "marquage":
            return "buff-donne"
        if st in _OFF_STATS:
            return _buff(scope, offensive=True) if e.value > 0 else "autre"
        if st in _DEF_STATS:
            return _buff(scope, offensive=False) if e.value > 0 else "autre"
        if st in _MOVE_STATS:
            return "mobilite"
        if st == "control":
            return "controle"
        if st in _MAGIC_STATS:
            # v37 : « subtract 1 from its power level » (Battle Damaged) : une contrepartie, pas de la magie
            return "magie-ressource" if e.value > 0 else "autre"
        return "autre"
    if k == "mortal_damage":
        return "degats-directs" if side == "enemy" else "autre"
    if k == "slay":
        # v35 : « If this unit would be automatically destroyed, it is not » : protection du porteur
        if side == "friendly" and e.detail == "auto-infligé":
            return "autre"  # v36 : figurines amies sacrifiées (Father of Necromancy) : un coût
        return "degats-directs" if side == "enemy" else "buff-perso-defensif"
    if k == "no_buff":  # v21 : ignorer les modificateurs positifs de la cible
        return "debuff"
    if k in ("heal", "return_models", "rally"):
        return "soin"
    if k == "control":
        # v36 : « This unit has a maximum control score of 1 » : une contrepartie, pas une aptitude de contrôle
        # v36 : contrôle ennemi réduit/plafonné (Omens of Decay, Scorched Remains) : un débuff (réponse utilisateur)
        if e.detail == "contrepartie":
            return "autre"
        return "debuff" if side == "enemy" else "controle"
    if k in ("no_weapon_abilities", "no_crit") and scope == "one_friendly":
        # v35 : « weapon abilities for attacks that target that friendly unit have no effect » (Miasma of
        # Pestilence, Weapon Curse) : protection donnée à une unité amie
        return "buff-donne"
    if k in _DEBUFF_KINDS and side == "enemy":
        return "debuff"
    if k in _MOBILITY_KINDS:
        return "debuff" if side == "enemy" else "mobilite"
    if k == "range_bonus" and st == "spell":  # v28 : relais de sort
        return "magie-ressource"
    if k == "keyword_gain" and st == "caster":  # v28 : niveau de lanceur gagné
        return "magie-ressource"
    if k == "dice_count":  # v28 : dé en plus (ami) / en moins (ennemi)
        if side == "enemy":
            return "debuff"
        if e.value < 0:
            return "autre"
        return (
            "mobilite"
            if st in _MOVE_STATS | {"redeploy"}
            else "magie-ressource"
            if st in _MAGIC_STATS | {"chant"}
            else "autre"
        )
    if k == "reroll" and st in _MOVE_STATS:  # v25 : relance de course/charge
        return "mobilite"
    if k == "reroll" and st in ("save", "ward"):
        return _buff(scope, offensive=False)
    if k == "reroll" and st in ("cast", "chant", "unbind"):
        return "magie-ressource"
    if k in _OFF_KINDS:
        return _buff(scope, offensive=True)
    if k in _DEF_KINDS:
        return _buff(scope, offensive=False)
    if k in _MAGIC_KINDS:
        return "magie-ressource"
    return "autre"


def main_family(families: Iterable[str]) -> str:
    """Famille principale : la plus fréquente parmi les effets (« autre » seulement s'il n'y a qu'elle)."""
    counts = Counter(f for f in families if f != "autre")
    if not counts:
        return "autre"
    top = max(counts.values())
    return next(f for f in _PRIORITY if counts.get(f) == top)
