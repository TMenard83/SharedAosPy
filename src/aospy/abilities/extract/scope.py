"""Portée et cible d'une aptitude (soi, une unité, aura, armée...)."""

from __future__ import annotations

import re
from typing import Optional

from ..models import Scope
from .conditions import _RANGE_RE, _WHOLLY_RE

_TARGET_PHRASE = re.compile(r"to be the (?:friendly |enemy )?targets?\b|to be the victim", re.I)
_FRIENDLY_AURA = re.compile(
    r"friendly\b[^.]*?\bunits\b[^.]*?(wholly )?within (\d+)\"|while they are (wholly )?within (\d+)\"", re.I
)
_ENEMY_AURA = re.compile(
    r"(?:each|all|any) enemy units? (?:that are |that is |while they are )?(wholly )?within (\d+)\"", re.I
)
#: « Friendly SKAVEN INFANTRY HEROES have WARD (5+) while they are within this unit's combat range » :
#: bulle autour du porteur pour des unités amies désignées par mot-clé au pluriel, sans le mot « units »
#: (analyseur v16 — lu jusque-là `self`, Elite Bodyguard donnait la protection aux Stormvermin).
#: Forme stricte : le groupe au pluriel est le SUJET (« Friendly X HEROES have/are/can … ») — un nom de
#: faction finissant par S (FYRESLAYERS) ne suffit pas.
_FRIENDLY_KW_AURA = re.compile(
    r"(?:^|\. )[Ff]riendly (?:[A-Z][A-Z'-]+ )*[A-Z][A-Z'-]+S (?:have|are|can|gain|count)\b[^.]*?"
    r"(?:(wholly )?within (\d+)\"|within (?:this unit's|this model's|its) combat range)"
)
#: v36 : « If a friendly BLOODBOUND unit wholly within 12" of this unit uses the 'Rally' command », « Each time a
#: friendly X unit wholly within 12" of this unit … » : bulle au singulier (lue `self`, le porteur semblait être
#: le seul bénéficiaire de ses bonus de Rally).
_FRIENDLY_SINGLE_AURA = re.compile(
    r"\b(?:[Ii]f|[Ee]ach time|[Ww]hile) an? (?:visible )?friendly (?:non-[A-Z]+ )?(?:[\w'’-]+ ){0,5}?unit "
    r"(?:that is )?(wholly )?within (\d+)\" of this (?:unit|model|HERO)\b"
)
_ARMY_WIDE = re.compile(r"\bfriendly [A-Z][A-Z' -]+ units\b|\bfriendly units\b")
#: « Friendly BONESPLITTERZ CAVALRY units have … », « each friendly DAUGHTERS OF KHAINE AELF INFANTRY
#: unit », « Friendly FLESH-EATER COURTS HEROES », « friendly Freeguild Steelhelms units » : toute
#: l'armée (restreinte par mot-clé, cf. `friendly_target`), sans rayon (analyseur v20).
_ARMY_KW = re.compile(
    # v38 : « within 12" of any friendly SKINK INFANTRY or SKINK CAVALRY units » = condition, pas les receveurs
    r"(?<![Aa] )(?<![Tt]he )(?<!that )(?<!other )(?<!another )(?<!visible )(?<!of any )"
    r"\b(?:[Ee]ach |[Aa]ll )?[Ff]riendly "
    # v38 : « friendly SKAVEN INFANTRY and CAVALRY units » (TOO QUICK TO HIT-HIT) : deux mots-clés coordonnés
    r"(?:non-[A-Z]+ )?(?:[A-Z][\w'’-]* )*(?:(?:and|or) (?:[A-Z][\w'’-]* )+)?"
    r"(?:units?'?|HEROES|WIZARDS|PRIESTS|MONSTERS|models)\b"
)
_REGIMENT = re.compile(r"\b(?:units|each unit|a unit) in this Regiment of Renown\b")
_COMBAT_RANGE = re.compile(r"combat range|in combat with|within 1\" ", re.I)
_PLACEMENT_RE = re.compile(r"(?:and )?more than \d+\" from all enemy units", re.I)
_SELF_SUBJECT = re.compile(
    r"(?:This (?:unit|model|HERO|MANIFESTATION|terrain feature)|Your general|Each time this unit|"
    r"While this unit)\b(?![^.]*friendly [^.]*units)"
)
_SELF_FIGHT_TWICE = re.compile(r"(?:If [^.]*?, )?(?:this unit|it) can use (?:2|two) FIGHT abilities", re.I)
_MULTI = re.compile(r"\b(?:each|all|any number of|up to \d+|up to \w+|\d+ other)\b", re.I)


def _target_clause(declare: str) -> str:
    """Segment « Pick … to be the target » (le dernier pick avant la formule) ; sinon le 1er « Pick … »."""
    m = _TARGET_PHRASE.search(declare)
    if m:
        start = max(declare.rfind("Pick", 0, m.start()), declare.rfind("pick", 0, m.start()))
        return declare[max(start, 0) : m.start()]
    m = re.search(r"[Pp]ick [^.]*", declare)
    return m.group(0) if m else ""


def _enemy_first(seg: str) -> bool:
    """La cible est ennemie : « enemy » cité AVANT « friendly » dans la clause de cible.

    « Pick a friendly BONESPLITTERZ unit in combat with an enemy MONSTER to be the target » : la
    cible est l'unité amie, « in combat with an enemy … » ne fait que la qualifier (analyseur v15).
    """
    # « Pick a friendly WIZARD to cast this spell, pick a visible enemy unit … to be the target » :
    # seul le dernier « pick … to be the target(s) » désigne la cible.
    picks = re.findall(r"\b[Pp]ick ((?:(?!\b[Pp]ick\b)[^.;])*?)\bto be the targets?\b", seg)
    if picks:
        seg = picks[-1]
    if re.search(r"friendly (?:and|or) enemy|enemy (?:and|or) friendly", seg):
        return True  # « each unit (friendly and enemy) within 3" » : effet indiscriminé, lu côté ennemi
    e, f = re.search(r"\benemy\b", seg), re.search(r"\bfriendly\b", seg)
    return bool(e) and (not f or e.start() < f.start())


def scope_of(declare: str, effect: str) -> tuple[Scope, Optional[int], bool]:
    """Qui reçoit l'effet, rayon principal, « wholly within » ou non."""
    # « more than 9" from all enemy units » est une contrainte de placement, pas une cible
    declare = _PLACEMENT_RE.sub("", declare)
    effect = _PLACEMENT_RE.sub("", effect)
    full = f"{declare} {effect}"
    # réaction sans « Declare: » : la clause de cible est en tête de l'effet
    # « This unit can use 2 FIGHT abilities … must pick an enemy HERO to be the target » : la cible
    # citée ensuite est celle des attaques, le bénéficiaire est le porteur.
    if not _target_clause(declare) and _SELF_FIGHT_TWICE.match(effect):
        return "self", None, False
    seg = _target_clause(declare) or (_target_clause(effect) if _TARGET_PHRASE.search(effect) else "")
    if seg and (re.search(r"to (?:cast|chant|use) this", seg) or len(seg.split()) < 3):
        # « Pick a friendly PRIEST to chant this prayer, pick a visible friendly X … that has not been
        # picked to be the target of this ability … to be the target » : la cible est la dernière
        # clause « pick … to be the target » de l'Annonce (analyseur v20)
        picks = re.findall(
            r"\b[Pp]ick ((?:(?!\b[Pp]ick\b)[^.;])*?)\bto be the targets?\b(?! of this)", declare or effect
        )
        seg = picks[-1] if picks and not re.search(r"to (?:cast|chant|use) this", picks[-1]) else ""
    if seg:
        rm = _RANGE_RE.search(seg)
        rng = int(rm.group(1)) if rm else (1 if _COMBAT_RANGE.search(seg) else None)
        wholly = bool(_WHOLLY_RE.search(seg))
        multi = bool(_MULTI.search(seg))
        if _enemy_first(seg):
            return ("enemy_aura" if multi else "one_enemy"), rng, wholly
        if re.search(r"\bfriendly\b|unit in this|units in this", seg):
            return ("friendly_aura" if multi and rng else "one_friendly"), rng, wholly
        if re.search(r"this unit|this model", seg):
            return "self", None, False
    m = _FRIENDLY_AURA.search(effect) or _FRIENDLY_AURA.search(declare)
    if m:
        wholly, rng = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
        return "friendly_aura", int(rng), bool(wholly)
    m = _FRIENDLY_KW_AURA.search(effect)
    if m:
        return "friendly_aura", int(m.group(2)) if m.group(2) else 1, bool(m.group(1))
    m = _FRIENDLY_SINGLE_AURA.search(effect)
    if m:
        return "friendly_aura", int(m.group(2)), bool(m.group(1))
    if _SELF_SUBJECT.match(effect):
        return "self", None, False
    m = _ENEMY_AURA.search(full)
    if m:
        return "enemy_aura", int(m.group(2)), bool(m.group(1))
    if re.search(r"\beach enemy unit\b|\ball enemy units\b", full, re.I):
        return "all_enemies", None, False
    m = _ARMY_KW.search(effect)
    if m:
        # « each friendly X unit wholly within 12" of this unit » : bulle, pas armée
        end = effect.find(".", m.end())
        tail = effect[m.end() : end if end != -1 else len(effect)]
        rm = re.search(r"(wholly )?within (\d+)\"", tail)
        if rm:
            return "friendly_aura", int(rm.group(2)), bool(rm.group(1))
        if re.search(r"within (?:this unit's|this model's|its|their) combat range", tail):
            return "friendly_aura", 1, False
    if _ARMY_WIDE.search(full) or re.search(r"\b(?:your|friendly) units\b", full) or m or _REGIMENT.search(effect):
        return "army", None, False
    # v38 : « While a friendly non-HERO FLESH-EATER COURTS MONSTER or BEAST is wholly within 12" of any friendly … :
    # - That non-HERO unit can … » (INDULGE, MY PRETTIES) : les receveurs sont ces unités-là, pas le porteur
    first = re.split(r"(?<=[.:])\s", effect, maxsplit=1)[0]
    subject = re.search(
        r"\b(?:[Ww]hile|[Ii]f|[Ee]ach time) an? friendly (?:non-)?[A-Z][\w'’ -]*? (?:is|are|uses) ", first
    )
    if subject and not re.search(r"\bthis (?:unit|model)\b", first) and not re.search(r"\benemy units?\b", effect):
        return "army", None, False
    if re.match(r"\s*Used By:", effect):
        return "one_friendly", None, False  # réaction : l'unité qui a déclaré l'aptitude
    if _enemy_first(seg or "") or re.search(r"\bthe target\b", effect) and _enemy_first(declare):
        return "one_enemy", None, False
    if re.search(r"\b(?:this|that) (?:unit|model|HERO|MANIFESTATION)\b|\bit\b|your general", full):
        return "self", None, False
    m = _fallback_scope(effect)
    if m:
        return m, None, False
    if re.search(r"battlefield|terrain feature|objective", full, re.I):
        return "battlefield", None, False
    return "unknown", None, False


def _fallback_scope(effect: str) -> Optional[Scope]:
    """Bénéficiaire lu dans des tournures sans clause de cible (analyseur v20, revue « portee »)."""
    # « within 18" of the caster » (convocation) n'est qu'un repère de placement
    if re.search(
        r"\b(?:for|by|to|target) the (?:caster|chanter)\b|\bthe (?:caster|chanter)'s\b|"
        r"\bthe unit using (?:this|that)\b|\b[Tt]he unit in this Regiment of Renown\b",
        effect,
    ):
        return "self"
    # personnage nommé : « the friendly Sigvald », « While a friendly Brokk Grungsson is … »
    if re.search(
        r"(?:\b[Tt]he|\b(?:While|If) a) friendly [A-Z][a-z][\w'’-]*(?: [A-Z][a-z][\w'’-]*)*\b(?! units)", effect
    ):
        return "self"
    if re.search(r"\b(?:for|by|of) enemy (?:[A-Z][\w'’-]* )*units\b|\benemy (?:[A-Z][\w'’-]* )*units have\b", effect):
        return "all_enemies"
    if re.search(r"\byou (?:receive|gain) (?:\d+|D\d|an?|one)\b", effect):
        return "army"  # ressource de faction : profite au joueur
    if re.search(r"\b(?:[Ee]ach time an?|[Ee]ach) friendly (?:non-[A-Z]+ )?[A-Z][\w'’-]*", effect):
        return "army"
    if re.search(
        r"\b(?:re-roll|[Rr]e-roll 1 dice in) (?:the|that) (?:charge|casting|chanting|unbinding|delusion) "
        r"roll\b|\bthat (?:charge|casting|chanting|unbinding) roll\b|for that (?:ability|spell)\b",
        effect,
    ):
        return "one_friendly"  # réaction : l'unité qui fait le jet
    return None
