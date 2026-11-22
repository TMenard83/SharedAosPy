"""Effets chiffrés : modificateurs de caractéristiques (« Add 1 to hit rolls »...)."""

from __future__ import annotations

import re

from ..models import Effect

_STAT_NAMES = [
    (r"hit rolls? and wound rolls?", ("hit", "wound")),
    (r"run rolls? and charge rolls?", ("run", "charge")),
    (r"casting rolls? and (?:chanting|unbinding) rolls?", ("cast", "chant")),
    (r"hit rolls?", ("hit",)),
    (r"wound rolls?", ("wound",)),
    (r"save rolls?", ("save",)),
    (r"ward rolls?", ("ward",)),
    (r"charge rolls?", ("charge",)),
    (r"run rolls?", ("run",)),
    (r"casting rolls?", ("cast",)),
    (r"chanting rolls?", ("chant",)),
    (r"unbinding rolls?", ("unbind",)),
    (r"banishment rolls?", ("banish",)),
    (r"Attacks characteristics?", ("attacks",)),
    (r"Rend characteristics?", ("rend",)),
    (r"Damage characteristics?", ("damage",)),
    (r"Health characteristics?", ("health",)),
    (r"Move characteristics?", ("move",)),
    (r"control scores?|Control characteristics?", ("control",)),
    (r"power level", ("power_level",)),
]
_MOD_RE = re.compile(
    r"\b(Add|Subtract|add|subtract) (\d{1,2}|X|D3|D6|the current battle round number|"
    # v34 : le reste s'arrête avant « and add/subtract » pour que le modificateur suivant soit lu à son tour
    # (« add 1 to rampage rolls for the target and add 1 to hit rolls … », Creepy Cantrips)
    # v34 (C) : niveau de fureur de la saison Fléau d'Aqshy (« Add half your fury level (rounding up) to … »)
    r"the number of the current battle round|half your fury level(?: \(rounding up\))?|your fury level)\"? "
    r"(?:to|from) ((?:(?! and (?:add|subtract)\b)[^.;])*)"
)
#: Valeur retenue pour un modificateur variable (v22) : « X » (nombre d'unités, de dés dépensés…) = 1
#: par prudence, dés = leur moyenne.
_VAR_MOD = {
    "X": 1.0,
    "D3": 2.0,
    "D6": 3.5,
    # v29 : numéro du round en cours = 3 en moyenne sur la partie
    "the current battle round number": 3.0,
    "the number of the current battle round": 3.0,
    # v34 (C, validé) : niveau de fureur moyen de la saison Fléau d'Aqshy = 2 (`resources.FURY_LEVEL`)
    "your fury level": 2.0,
    "half your fury level": 1.0,
    "half your fury level (rounding up)": 1.0,
}
_ENEMY_ACTOR = re.compile(
    r"(?:made|used) by (?:enemy|that enemy|each enemy|an enemy|the enemy|those enemy)|"
    r"for (?:visible )?(?:enemy|each enemy|that enemy|those enemy|friendly and enemy)\b|"
    r"of (?:enemy|that enemy|each enemy)\b|enemy units?'s?",
    re.I,
)
#: « la cible » : ennemie ou amie selon la clause de cible de l'aptitude (default_side).
_TARGET_ACTOR = re.compile(
    r"made by (?:the target|that unit|them|those|units? in the target)|for (?:the target|that unit)\b|"
    r"(?:the target|target|each target|that unit)'s|of (?:the target|that unit)\b",
    re.I,
)
#: Terminologie GW : « this unit » = toujours l'UTILISATEUR de l'aptitude ; « the target » peut
#: être lui-même, une unité amie ou ennemie (défini par l'Annonce). « against this unit » = les
#: attaques ennemies qui visent l'utilisateur.
_TARGETS_US = re.compile(
    r"that target (?:this unit|(?:other |another |a |any |visible )*friendly|that friendly|it\b|your general|"
    r"the caster\b|the chanter\b|this general\b|them\b|that (?:TWIN|HERO)\b|those TWINS\b|"
    r"units? (?:that are )?wholly within|the target\b(?=[^.]*friendly)|units? in this)|"
    r"\bagainst (?:this unit|friendly)\b",
    re.I,
)
#: Lanceurs sans « friendly » (« for WIZARDS within 12" », « for that WIZARD ») : jet ennemi (v15).
_CASTER_ACTOR = re.compile(r"\bfor (?:that |each |any )?(?:WIZARDS?|PRIESTS?)\b")
_CASTER_STATS = ("cast", "chant", "unbind", "power_level", "banish")
#: « ward/save rolls for damage points inflicted by attacks made with this unit's X » : le jet est
#: celui de l'ennemi qui encaisse NOS attaques → buff offensif, pas malus (v15).
_OUR_ATTACKS_DEFENCE = re.compile(
    r"(?:inflicted by|for) (?:combat |shooting )?attacks made (?:by|with|as part of) (?:this unit|this model|"
    r"friendly|that (?:SHOOT|FIGHT))|inflicted by (?:this unit's|its) (?:combat |shooting )?attacks|"
    r"inflicted by abilities used by this unit",
    re.I,
)
#: « the target unit's » dans une phrase d'attaque = l'unité visée par l'attaque, donc ennemie (v15).
_ATTACK_TARGET = re.compile(
    r"\b(?:an?|each|the) (?:shooting |combat )?attack (?:made|that|scores)[^.]*\bthe target unit's\b"
)
#: Sous-aptitude qui (re)désigne une unité (« Prophecy of Exile: Pick a visible enemy WIZARD… »,
#: « If you picked an enemy unit: ») : le sens des phrases suivantes en dépend (v15).
_LOCAL_ENEMY = re.compile(
    r"\b[Pp]ick (?:a|an|one|up to \d+|\d+)? ?(?:other )?(?:visible )?enemy\b|"
    r"\bIf you picked (?:an )?enemy\b|\bIf the target is an enemy\b|"
    r"\b(?:If|While|Each time) (?:an|any|that) enemy unit\b|\ban enemy unit (?:is|becomes)\b|"
    r"\ballocated to (?:an|any) enemy units?\b|\bthe target unit becomes\b"
)
_LOCAL_FRIENDLY = re.compile(
    r"\b[Pp]ick (?:a|an|one|up to \d+|\d+)? ?(?:other )?(?:visible )?friendly\b|"
    r"\bIf you picked (?:a )?friendly\b|\bIf you picked this unit\b|"
    r"\bIf the target is a friendly\b"
)
#: « attaques qui ciblent la cible / cette unité » quand la cible est amie
_TARGETS_TARGET = re.compile(r"that target (?:the target|that unit|that friendly unit|each target)\b", re.I)


#: « attacks that target that unit / the bet / its quarry / the condemned unit » quand la cible
#: désignée est ennemie. Marquage seulement si d'AUTRES unités amies en profitent (voir _stat_mods).
_MARKED_TARGET = re.compile(
    r"(?:attacks|weapons)[^.]*?that target (?!this unit|friendly|that friendly)(?:that|the|its|each|it)\b", re.I
)
#: Attaquant = l'utilisateur seul (« this unit's Templar Weapon », « attacks made by this unit »).
_SELF_ATTACKER = re.compile(r"\bthis (?:unit|model)\b|\bits\b|\b(?:his|her)\b")


def _stat_mods(sentence: str, default_side: str, declared_side: str = "") -> list[Effect]:
    out = []
    for m in _MOD_RE.finditer(sentence):
        verb, rest = m.group(1).lower(), m.group(3)
        n = _VAR_MOD[m.group(2)] if m.group(2) in _VAR_MOD else int(m.group(2))
        rest = re.split(r"\band (?:add|subtract)\b", rest)[0]
        if rest.startswith("the number of dice"):
            continue  # dé en plus / en moins (v28) : lu par `dice_count_of`, pas un ±1 au jet
        # la caractéristique visée est la PREMIÈRE citée après « to/from » (pas la première de la liste)
        stats: tuple[str, ...] = ()
        best = None
        for pat, names in _STAT_NAMES:
            sm = re.search(pat, rest)
            if sm and (best is None or sm.start() < best[0] or (sm.start() == best[0] and sm.end() > best[1])):
                best = (sm.start(), sm.end(), names)
        if best is not None and best[0] <= 40:
            stats = best[2]
        if not stats:
            continue
        target_actor = bool(_TARGET_ACTOR.search(rest))
        enemy_actor = bool(_ENEMY_ACTOR.search(rest)) or (
            default_side == "enemy"
            and (
                target_actor
                or not re.search(r"friendly|this unit|the caster|the chanter|units? you picked|in this Regiment", rest)
            )
        )
        # « the target's … » suit la cible DÉCLARÉE, même si la phrase cite une unité ennemie avant
        # (« if damage was allocated to an enemy unit by the target's attacks … the target's weapons »)
        if (
            declared_side == "friendly"
            and target_actor
            and not _ENEMY_ACTOR.search(rest)
            and re.search(r"\b(?:the target|each target|target)(?:'s|s')|(?:for|by) the target\b", rest)
        ):
            enemy_actor = False
        enemy_actor = (
            enemy_actor
            or bool(_ATTACK_TARGET.search(sentence))
            or (
                any(st in _CASTER_STATS for st in stats)
                and bool(_CASTER_ACTOR.search(rest))
                and not re.search(r"\bfriendly\b", rest)
            )
        )
        targets_us = bool(_TARGETS_US.search(rest)) or (
            default_side == "friendly" and bool(_TARGETS_TARGET.search(rest))
        )
        marks_target = False
        mk = _MARKED_TARGET.search(rest) if verb == "add" and default_side == "enemy" else None
        if mk:
            head = rest[: rest.find("that target", mk.start())]
            # « this unit's X » sans « friendly … » : seule l'utilisatrice en profite, pas un marquage
            marks_target = bool(re.search(r"\bfriendly\b", head)) or not _SELF_ATTACKER.search(head)
        for stat in stats:
            sign = 1 if verb == "add" else -1
            if marks_target and stat in ("hit", "wound", "attacks", "rend", "damage"):
                # « marquage » : bonus pour TOUTE attaque amie qui vise la cible ennemie désignée
                out.append(Effect("stat_mod", stat, sign * n, "", "friendly", "marquage"))
                continue
            if stat in ("save", "ward") and sign > 0 and targets_us:
                # « add 1 to save rolls for attacks made by that enemy unit that target this unit »
                out.append(Effect("stat_mod", stat, sign * n, "", "friendly", "defensif"))
                continue
            if stat in ("save", "ward") and sign < 0 and _OUR_ATTACKS_DEFENCE.search(rest):
                # protection/sauvegarde de l'ennemi contre nos attaques : buff offensif
                out.append(Effect("stat_mod", stat, sign * n, "", "enemy", "debuff"))
                continue
            if stat in ("hit", "wound", "attacks", "rend", "damage") and (enemy_actor or targets_us):
                # le jet est celui de l'ennemi : le diminuer protège nos unités
                side = "enemy"
                role = "defensif" if sign < 0 else "malus"
            elif (
                stat
                in (
                    "save",
                    "ward",
                    "control",
                    "cast",
                    "chant",
                    "unbind",
                    "charge",
                    "run",
                    "move",
                    "health",
                    "power_level",
                    "banish",
                )
                and enemy_actor
            ):
                side = "enemy"
                role = "debuff" if sign < 0 else "malus"
            else:
                side = "friendly"
                role = (
                    "offensif"
                    if stat in ("hit", "wound", "attacks", "rend", "damage")
                    else "defensif"
                    if stat in ("save", "ward", "health")
                    else "utilitaire"
                )
                if sign < 0:
                    role = "malus"
            value = sign * n
            if side == "enemy" and re.search(r"\bCompanion (?:melee |ranged )?weapons\b", rest):
                value /= 2  # débuff limité aux armes Compagnon : peu de poids dans un profil (v22)
            out.append(Effect("stat_mod", stat, value, "", side, role))
    return out
