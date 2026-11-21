"""Assemblage des effets d'une aptitude (`effects_of`) : annotation, sujet de chaque phrase."""

from __future__ import annotations

import dataclasses
import re

from ..models import Effect, Scope
from ..perimeter import perimeter_of, sentence_at
from .dice import dice_mean
from .qualitative import _HEAL_RE, _MORTAL_PER_ROLL, _MORTAL_RE, _MOVE_RE, _RETURN_RE, _WARD_RE, QUALITATIVE_RULES
from .rolls import _MAKE_MOVE_RE, dice_count_of, rerolls_of
from .stat_mods import _LOCAL_ENEMY, _LOCAL_FRIENDLY, _stat_mods
from .targets import effect_friendly_target

_OFFENSIVE_STATS = ("hit", "wound", "attacks", "rend", "damage")
#: effets qualitatifs qui portent sur des attaques (périmètre d'armes pertinent)
_WEAPON_KINDS = {"crit", "anti", "charge_bonus", "reroll", "no_crit", "no_weapon_abilities", "stat_set"}


def _annotate(
    e: Effect, sentence: str, text: str, passive: bool, enemy_target: bool = False, condition: str = ""
) -> Effect:
    """Ajoute le périmètre (armes, cible, prérequis, durée) lu dans la phrase source."""
    offensive = (e.kind == "stat_mod" and e.stat in _OFFENSIVE_STATS) or (
        e.kind in _WEAPON_KINDS and not (e.kind == "reroll" and e.stat not in ("hit", "wound", ""))
    )
    ft = effect_friendly_target(sentence, text) if e.side == "friendly" else ""
    return dataclasses.replace(
        e, friendly_target=ft, **perimeter_of(sentence, text, passive, offensive, e.kind, enemy_target, condition)
    )


#: Sujet de la proposition qui subit une restriction (v29) : « Enemy MONSTERS cannot… » = ennemi, « They cannot use
#: MOVE abilities » après une téléportation = contrepartie amie, « the target » suit la cible déclarée.
_SUBJ_ENEMY = re.compile(r"\b[Ee]nemy\b")
_SUBJ_TARGET = re.compile(r"\b(?:[Tt]he|[Tt]hat|[Ee]ach) target\b")
_SUBJ_SELF = re.compile(
    r"\b(?:[Tt]his (?:unit|model|terrain feature|MANIFESTATION)|[Yy]our general|"
    r"[Ff]riendly|[Tt]he Shrine Guardian|[Uu]nits in this Regiment)\b"
)
_SUBJ_PRONOUN = re.compile(r"\b(?:[Ii]t|[Tt]hey)\b")


def _subject_side(full: str, pos: int, default_side: str) -> str:
    before = full[max(0, pos - 160) : pos]
    clause = re.split(r"[.:;\n]|\bthen\b|, (?=[a-z])", before)[-1]
    if _SUBJ_ENEMY.search(clause):
        return "enemy"
    if _SUBJ_TARGET.search(clause):
        return default_side
    if _SUBJ_SELF.search(clause):
        return "friendly"
    if _SUBJ_PRONOUN.search(clause):
        # pronom : antécédent dans la même phrase (« If the target is an enemy unit, it has STRIKE-LAST »),
        # sinon la cible déclarée (« - It cannot use RUN abilities » sous une cible ennemie)
        sentence = re.split(r"[.:\n]", before)[-1]
        if _SUBJ_ENEMY.search(sentence):
            return "enemy"
        if re.search(r"\b(?:[Tt]his (?:unit|model)|[Ff]riendly)\b", sentence):
            return "friendly"
        return default_side
    return ""


def effects_of(
    declare: str, effect: str, scope: Scope, passive: bool = False, condition: str = ""
) -> tuple[list[Effect], list[str], bool]:
    """Effets reconnus (avec leur périmètre), mots-clés ciblés (Anti-X), dépendance à l'effectif."""
    default_side = "enemy" if scope in ("one_enemy", "enemy_aura", "all_enemies") else "friendly"
    out: list[Effect] = []

    enemy_target = default_side == "enemy"

    def add(e: Effect, text: str, pos: int) -> None:
        out.append(_annotate(e, sentence_at(text, pos), text, passive, enemy_target, condition))

    local_side = default_side
    # cible déclarée explicitement amie (pas « amie ou ennemie au choix », scope inconnu)
    declared = "friendly" if scope in ("self", "one_friendly", "friendly_aura", "army") else ""
    for sentence in re.split(r"(?<=[.:])\s+|\n", effect):
        if _LOCAL_ENEMY.search(sentence):
            local_side = "enemy"
            if re.search(r"\b[Pp]ick\b|\bIf you picked\b|\bIf the target is\b", sentence):
                declared = ""  # re-désignation explicite : « the target » est désormais ennemie
        elif _LOCAL_FRIENDLY.search(sentence):
            local_side = "friendly"
        out.extend(
            _annotate(e, sentence, effect, passive, local_side == "enemy", condition)
            for e in _stat_mods(sentence, local_side, declared)
        )

    seen_mortal = False
    for m in _MORTAL_PER_ROLL.finditer(effect):
        add(Effect("mortal_damage", "", 0.0, "par jet", "enemy", "binomial"), effect, m.start())
        seen_mortal = True
    for m in _MORTAL_RE.finditer(effect):
        expr = m.group(1) or ""
        if seen_mortal and not expr[:1].isdigit() and "D" not in expr:
            continue
        mean = dice_mean(expr.replace("+X", "+1")) if expr else None  # « D3+X » : X = 1 (v27)
        target_us = bool(
            re.search(r"mortal damage on (?:this unit|it|that friendly)", effect[m.start() : m.end() + 40])
        )
        add(
            Effect(
                "mortal_damage",
                "",
                mean or 0.0,
                expr if "D" in expr else "",
                "friendly" if target_us else "enemy",
                "auto-infligé" if target_us else ("variable" if mean is None else ""),
            ),
            effect,
            m.start(),
        )
    for m in re.finditer(r"[Aa]llocate (\d+|D\d) damage points? to (?:this unit|this MANIFESTATION|it)\b", effect):
        # v30 : dégâts que l'unité s'inflige (surchauffe, contrecoup) : contrepartie, poids nul
        add(
            Effect(
                "mortal_damage",
                "",
                dice_mean(m.group(1)) or 0.0,
                m.group(1) if "D" in m.group(1) else "",
                "friendly",
                "auto-infligé",
            ),
            effect,
            m.start(),
        )
    for m in re.finditer(
        r"[Aa]llocate (\d+|D\d(?:\+\d)?|a number of) damage points? to (?:the target|each target|"
        r"that enemy unit|each enemy unit|the enemy unit)\b",
        effect,
    ):
        expr = m.group(1)
        mean = dice_mean(expr) if expr != "a number of" else None
        add(
            Effect(
                "mortal_damage",
                "",
                mean or 0.0,
                expr if "D" in expr else "",
                "enemy",
                "variable" if mean is None else "",
            ),
            effect,
            m.start(),
        )
    fragile = bool(re.search(r"unmodified save roll of 1[^.]*remove", effect))
    for m in _WARD_RE.finditer(effect):
        side = (
            "enemy"
            if re.search(r"target[^.]*enemy|enemy units have", effect) and default_side == "enemy"
            else "friendly"
        )
        add(Effect("ward", "", int(m.group(1)), "", side, "fragile" if fragile else ""), effect, m.start())
    for m in _HEAL_RE.finditer(effect):
        mean = dice_mean(m.group(1))
        add(Effect("heal", "", mean or 0.0, m.group(1) if "D" in m.group(1) else "", "friendly"), effect, m.start())
    for m in _RETURN_RE.finditer(effect):
        expr = (m.group(1) or "").replace("up to ", "")
        mean = dice_mean(expr) if expr else None
        add(Effect("return_models", "", mean or 0.0, expr if "D" in expr else "", "friendly"), effect, m.start())
    for m in _MOVE_RE.finditer(effect):
        expr = m.group(1) or ""
        if re.search(r"cannot move|can move[^.]*but cannot", effect[m.start() - 10 : m.start() + 5]):
            continue
        mean = dice_mean(expr) if expr else None
        side = (
            "enemy"
            if re.search(r"the target can move|enemy", effect[max(0, m.start() - 40) : m.start()])
            and default_side == "enemy"
            else "friendly"
        )
        add(Effect("move", "", mean or 0.0, expr if "D" in expr else "", side), effect, m.start())

    for m in _MAKE_MOVE_RE.finditer(effect):  # v28 : « it can immediately make a D6" move »
        mean = dice_mean(m.group(1))
        add(Effect("move", "", mean or 0.0, m.group(1) if "D" in m.group(1) else "", "friendly"), effect, m.start())

    target_kw: list[str] = []
    full = f"{declare} {effect}"
    for e, pos in rerolls_of(full):
        add(e, full, pos)
    for e, pos in dice_count_of(full):
        add(e, full, pos)
    for pat, kind, stat in QUALITATIVE_RULES:
        for m in re.finditer(pat, full):
            if kind == "anti":
                target_kw.append(m.group(1).upper())
            if re.search(r"(?:casting|chanting) roll was \d+\+[^.]*$", full[max(0, m.start() - 160) : m.start()]):
                continue  # bonus sur un jet élevé (« If the chanting roll was 8+, in addition … ») : pas acquis
            if kind == "no_weapon_abilities" and re.search(
                r"The Companion weapon ability has no effect on", full[max(0, m.start() - 40) : m.end() + 5]
            ):
                continue  # contrainte sur nos propres unités (Monstrous Entourage), pas un débuff
            if kind == "stat_set" and re.search(
                r"(?:has|have) \d+ or more damage points|[Bb]attle [Dd]amaged",
                full[max(0, m.start() - 200) : m.start()],
            ):
                continue  # profil dégradé (v27) : une perte, déjà lue par battle_damaged
            if kind == "stat_set" and re.search(
                r"\b(?:[Ii]f|[Ww]hile|whose|[Uu]nless)\b[^.,:]*$", full[max(0, m.start() - 60) : m.start()]
            ):
                continue  # « If the target's Save characteristic is 3+ » : condition, pas un effet (v27)
            if kind == "warscroll_rule" and not passive and re.search(r"token", m.group(0)):
                continue  # v30 : jeton posé par une aptitude active (Bomb Rats…) : l'effet est ailleurs, à lire
            if (
                kind == "fly"
                and "FLY" not in m.group(0)
                and any(e.kind in ("move", "extra_move", "redeploy", "deep_strike") for e in out)
            ):
                continue  # « It can move through the combat ranges » : modalité du mouvement, pas un effet en plus
            side = default_side
            if kind in ("no_ward", "slay", "no_weapon_abilities", "no_crit", "no_buff"):
                side = "enemy"
            if kind in ("strike_last", "restriction", "lockout", "move_debuff", "untargetable"):
                side = _subject_side(full, m.start(), default_side) or (
                    "enemy" if re.search(r"target|enemy", full[max(0, m.start() - 80) : m.start()]) else "friendly"
                )
                if "has no effect" in m.group(0):
                    side = "enemy"  # v27 : on annule une capacité adverse
            if kind in ("taunt", "anti_heal", "strip_enhancement"):
                side = "enemy"
            if kind in (
                "strike_first",
                "run_and_charge",
                "run_and_shoot",
                "redeploy",
                "extra_fight",
                "fight_twice",
                "extra_shoot",
                "fly",
                "cp_gain",
                "crit",
                "shoot_in_combat",
                "charge_bonus",
                "summon",
                "anti_magic",
                "control",
                "pile_in",
                "damage_redirect",
                "anti",
                "extra_move",
                "deep_strike",
                "stat_set",
                "negate_attack",
                "keyword_gain",
                "damage_ignore",
                "resource",
                "extra_use",
                "battle_damaged",
                "free_retreat",
                "fixed_roll",
                "rally",
                "range_bonus",
                "ignore_debuff",
                "snipe",
                "profile_choice",
                "tactic_cards",
                "coherency",
                "warscroll_rule",
            ):
                side = "friendly"
            if kind not in _WEAPON_KINDS and any(e.kind == kind and e.stat == stat and e.side == side for e in out):
                break  # v28 : deux règles du même effet (ressource…) ne le doublent pas
            add(Effect(kind, stat, 0.0, "", side, m.group(0)[:80]), full, m.start())
            break  # un même effet qualitatif compte une fois

    for kw in re.findall(r"\b(MONSTER|HERO|INFANTRY|CAVALRY|WIZARD|PRIEST|WAR MACHINE|MANIFESTATION)S?\b", declare):
        if re.search(r"enemy " + kw, declare):
            target_kw.append(kw)

    scales = bool(re.search(r"for each model in (?:this|that|the target) unit|number of models in", full, re.I))
    return out, sorted(set(target_kw)), scales
