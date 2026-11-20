"""Extraction par règles (regex) des caractéristiques d'une aptitude.

Volontairement déterministe et sans contexte d'unité : on lit le timing
(`condition`), le coût (sort/prière/ordre), le jet de déclenchement, les
prérequis, la cible et les effets chiffrés. Tout ce qui n'est pas reconnu reste
absent (jamais deviné) ; `pipeline.py` signale une aptitude sans effet reconnu
comme « à revoir » plutôt que de lui inventer une note.

Probabilités de déclenchement (hors contexte, sans relance ni bonus) :

* sort de valeur N : P(2D6 ≥ N), dissipation adverse ignorée ;
* prière de valeur N : P(D6 ≥ N), points rituels ignorés (sous-estime un peu) ;
* « Roll a dice. On a N+ » : (7 − N)/6 ; « Roll 2D6. On a N+ » : P(2D6 ≥ N) ;
* ordre, Blood Tithe, Fate : automatique (coût noté à part).
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional

from .models import Effect, Extraction, Frequency, RawAbility, Scope, TurnSide
from .perimeter import charge_subjects, perimeter_of, sentence_at

# ----- probabilités ------------------------------------------------------------

_P_2D6_AT_LEAST = {n: sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= n) / 36
                   for n in range(2, 13)}


def p_2d6(n: int) -> float:
    return 1.0 if n <= 2 else 0.0 if n > 12 else _P_2D6_AT_LEAST[n]


def p_d6(n: int) -> float:
    return max(0.0, min(1.0, (7 - n) / 6))


_DICE_MEAN = {"D3": 2.0, "D6": 3.5, "2D3": 4.0, "2D6": 7.0, "3D6": 10.5, "D3+1": 3.0,
              "D3+3": 5.0, "D6+1": 4.5, "D6+3": 6.5, "D3+2": 4.0}


def dice_mean(expr: str) -> Optional[float]:
    """« 3 » → 3, « D3 » → 2, « 2D6 » → 7 ; None si non numérique (X, any…)."""
    e = expr.strip().upper().replace(" ", "")
    if e.isdigit():
        return float(e)
    return _DICE_MEAN.get(e)


# ----- timing --------------------------------------------------------------------

_FREQ_PATTERNS: list[tuple[str, Frequency]] = [
    (r"once per battle round \(army\)", "once_per_round_army"),
    (r"once per battle round", "once_per_round"),
    (r"once per battle \(army\)", "once_per_battle_army"),
    (r"once per battle", "once_per_battle"),
    (r"once per turn \(army\)", "once_per_turn_army"),
    (r"once per turn", "once_per_turn"),
    (r"once per phase \(army\)", "once_per_phase_army"),
]


def frequency_of(condition: str) -> Frequency:
    c = condition.lower()
    if c.startswith("passive"):
        return "passive"
    if re.search(r"first battle round", c):
        return "once_per_battle"      # un seul déclenchement : début du premier round
    if "deployment" in c:
        # La phase de déploiement n'a lieu qu'une fois : « Once Per Battle » y est un garde-fou
        # redondant de GW (avis utilisateur), pas une limite qui coûte de la puissance.
        return "unlimited"
    for pat, freq in _FREQ_PATTERNS:
        if re.search(pat, c):
            return freq
    return "unlimited"


def turn_of(condition: str, phase: str) -> TurnSide:
    c = condition.lower()
    if "deployment" in c:
        return "deployment"
    if re.search(r"start of (?:the )?(?:first )?battle round", c):
        return "round_start"
    if re.search(r"\byour\b", c) and not re.search(r"\bany\b|opponent|enemy", c):
        return "yours"
    if re.search(r"\benemy\b.*phase|opponent", c):
        return "enemy"
    return "any"


# ----- prérequis de mise en place (axe « ease ») ---------------------------------

#: (regex sur Annonce+Effet+condition, libellé FR, pénalité d'ease)
#: La charge est lue à part (`perimeter.charge_subjects`) : qui a chargé, nous ou l'ennemi ?
CHARGE_OURS = ("doit avoir chargé", 1.0)
#: Réagit à une charge ennemie (Fateful Reverse, Anticipated Strike) : situationnel, pas un effort.
CHARGE_ENEMY = ("dépend d'une charge ennemie", 0.5)
CONDITION_RULES: list[tuple[str, str, float]] = [
    (r"\bin ambush\b|\bin reserve\b", "unité en réserve", 0.25),
    (r"friendly [^.]*?(?:within (?:this unit's|its|the) combat range(?: of this unit)?|within [1-3]\" of this unit)",
     "coordination rapprochée (déplacements et charges liés, porteur exposé)", 1.0),
    (r"(?:were|was|has been|is) (?:slain|destroyed) (?:this turn |this phase )?by|"
     r"if any (?:enemy )?models? (?:were|was) slain|if (?:it|this unit) destroyed",
     "dépend d'un kill préalable", 0.75),
    (r"[Ii]n the first battle round|[Ii]n battle rounds? \d(?: and \d)?\b|[Ii]n the (?:third|fourth|fifth) battle round",
     "limité à certains rounds", 0.5),
    (r"contesting an objective|within \d+\" of an objective|objectives? you control|"
     r"objective you do not control|wholly within (?:friendly|enemy) territory|"
     r"(?:on|within) (?:an? )?(?:objective|terrain feature)",
     "position (objectif/territoire/décor)", 0.5),
    (r"\b(\d+) or more models\b", "effectif minimal", 0.5),
    (r"\bnot in combat\b", "hors combat", 0.25),
    (r"ha(?:s|ve) not (?:used|moved|shot|charged)|did not (?:use|move|run|retreat|charge)|"
     r"has not been picked", "contrainte d'action préalable", 0.25),
    (r"(?:is|was|has been) destroyed|is slain|was slain|last model", "déclenché par une mort", 0.75),
    (r"damage points? allocated|has (?:\d+|any) damage points|damaged this", "doit avoir subi des dégâts", 0.5),
    (r"you must use this ability|cannot be used again|for the rest of the battle,? (?:this|that) unit cannot",
     "contrepartie / usage contraint", 0.25),
    (r"\bset up\b.*\bmore than (\d+)\" from all enemy", "placement hors de portée ennemie", 0.0),
]

_RANGE_RE = re.compile(r"within (\d+)\"")
_WHOLLY_RE = re.compile(r"wholly within (\d+)\"")


#: « Pick an enemy unit on the battlefield or in reserve » / « You can pick a unit that has been
#: deployed in reserve » : la réserve élargit le choix de la CIBLE, ce n'est pas une contrainte.
_RESERVE_TARGET_RE = re.compile(
    r"[^.]*\bpick\b[^.]*\benemy\b[^.]*\bin reserve\b[^.]*\.?|"
    r"you can (?:also )?pick (?:a|an enemy) unit that (?:has been|is) (?:deployed )?in reserve[^.]*\.?", re.I)
#: Segment secondaire d'un texte en plusieurs lignes/puces : « If the target is destroyed… ».
_SECONDARY_IF_RE = re.compile(r"^\s*(?:-\s*)?If\b")


def conditions_of(text: str, enemy_target: bool = False) -> tuple[list[str], float]:
    text = _RESERVE_TARGET_RE.sub(" ", text)
    labels, penalty = [], 0.0
    who = charge_subjects(text, enemy_target)
    for key, (label, pen) in (("nous", CHARGE_OURS), ("ennemi", CHARGE_ENEMY)):
        if key in who:
            labels.append(label)
            penalty += pen
    for pat, label, pen in CONDITION_RULES:
        if re.search(pat, text, re.I):
            labels.append(label)
            penalty += pen
    return labels, penalty


def split_main_secondary(effect: str) -> tuple[str, str]:
    """(texte principal, segments secondaires conditionnels).

    Un texte d'aptitude se lit comme une liste de sous-aptitudes : une ligne ou une puce qui
    commence par « If … », après la première, est un effet en plus dont la condition ne
    concerne qu'elle (Un Trophée Exquis : le Crit sur 5+ est inconditionnel, seul le +1 Attaque
    des démons voisins dépend du kill). Ses prérequis ne pénalisent donc pas l'aptitude entière.

    Seul le bloc de lignes « If … » en FIN de texte est secondaire : un « If » suivi d'une ligne
    ordinaire est une étape du mécanisme (Primal Rage : « If this unit fought, place a rage
    token » puis « +1 Attaque par jeton »), donc une vraie condition.
    """
    lines = [ln for ln in effect.split("\n") if ln.strip()]
    cut = len(lines)
    while cut > 1 and _SECONDARY_IF_RE.match(lines[cut - 1]):
        cut -= 1
    return "\n".join(lines[:cut]), "\n".join(lines[cut:])


# ----- portée / cible ---------------------------------------------------------------

_TARGET_PHRASE = re.compile(r"to be the (?:friendly |enemy )?targets?\b|to be the victim", re.I)
_FRIENDLY_AURA = re.compile(
    r"friendly\b[^.]*?\bunits\b[^.]*?(wholly )?within (\d+)\"|while they are (wholly )?within (\d+)\"", re.I)
_ENEMY_AURA = re.compile(
    r"(?:each|all|any) enemy units? (?:that are |that is |while they are )?(wholly )?within (\d+)\"", re.I)
#: « Friendly SKAVEN INFANTRY HEROES have WARD (5+) while they are within this unit's combat range » :
#: bulle autour du porteur pour des unités amies désignées par mot-clé au pluriel, sans le mot « units »
#: (analyseur v16 — lu jusque-là `self`, Elite Bodyguard donnait la protection aux Stormvermin).
#: Forme stricte : le groupe au pluriel est le SUJET (« Friendly X HEROES have/are/can … ») — un nom de
#: faction finissant par S (FYRESLAYERS) ne suffit pas.
_FRIENDLY_KW_AURA = re.compile(
    r"(?:^|\. )[Ff]riendly (?:[A-Z][A-Z'-]+ )*[A-Z][A-Z'-]+S (?:have|are|can|gain|count)\b[^.]*?"
    r"(?:(wholly )?within (\d+)\"|within (?:this unit's|this model's|its) combat range)")
_ARMY_WIDE = re.compile(r"\bfriendly [A-Z][A-Z' -]+ units\b|\bfriendly units\b")
#: « Friendly BONESPLITTERZ CAVALRY units have … », « each friendly DAUGHTERS OF KHAINE AELF INFANTRY
#: unit », « Friendly FLESH-EATER COURTS HEROES », « friendly Freeguild Steelhelms units » : toute
#: l'armée (restreinte par mot-clé, cf. `friendly_target`), sans rayon (analyseur v20).
_ARMY_KW = re.compile(
    r"(?<![Aa] )(?<![Tt]he )(?<!that )(?<!other )(?<!another )(?<!visible )\b(?:[Ee]ach |[Aa]ll )?[Ff]riendly "
    r"(?:non-[A-Z]+ )?(?:[A-Z][\w'’-]* )*(?:units?'?|HEROES|WIZARDS|PRIESTS|MONSTERS|models)\b")
_REGIMENT = re.compile(r"\b(?:units|each unit|a unit) in this Regiment of Renown\b")
_COMBAT_RANGE = re.compile(r"combat range|in combat with|within 1\" ", re.I)
_PLACEMENT_RE = re.compile(r"(?:and )?more than \d+\" from all enemy units", re.I)
_SELF_SUBJECT = re.compile(r"(?:This (?:unit|model|HERO|MANIFESTATION|terrain feature)|Your general|Each time this unit|"
                           r"While this unit)\b(?![^.]*friendly [^.]*units)")
_SELF_FIGHT_TWICE = re.compile(r"(?:If [^.]*?, )?(?:this unit|it) can use (?:2|two) FIGHT abilities", re.I)
_MULTI = re.compile(r"\b(?:each|all|any number of|up to \d+|up to \w+|\d+ other)\b", re.I)


def _target_clause(declare: str) -> str:
    """Segment « Pick … to be the target » (le dernier pick avant la formule) ; sinon le 1er « Pick … ». """
    m = _TARGET_PHRASE.search(declare)
    if m:
        start = max(declare.rfind("Pick", 0, m.start()), declare.rfind("pick", 0, m.start()))
        return declare[max(start, 0):m.start()]
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
        return True   # « each unit (friendly and enemy) within 3" » : effet indiscriminé, lu côté ennemi
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
        picks = re.findall(r"\b[Pp]ick ((?:(?!\b[Pp]ick\b)[^.;])*?)\bto be the targets?\b(?! of this)",
                           declare or effect)
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
        tail = effect[m.end():end if end != -1 else len(effect)]
        rm = re.search(r"(wholly )?within (\d+)\"", tail)
        if rm:
            return "friendly_aura", int(rm.group(2)), bool(rm.group(1))
        if re.search(r"within (?:this unit's|this model's|its|their) combat range", tail):
            return "friendly_aura", 1, False
    if _ARMY_WIDE.search(full) or re.search(r"\b(?:your|friendly) units\b", full) \
            or m or _REGIMENT.search(effect):
        return "army", None, False
    if re.match(r"\s*Used By:", effect):
        return "one_friendly", None, False   # réaction : l'unité qui a déclaré l'aptitude
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
    if re.search(r"\b(?:for|by|to|target) the (?:caster|chanter)\b|\bthe (?:caster|chanter)'s\b|"
                 r"\bthe unit using (?:this|that)\b|\b[Tt]he unit in this Regiment of Renown\b", effect):
        return "self"
    # personnage nommé : « the friendly Sigvald », « While a friendly Brokk Grungsson is … »
    if re.search(r"(?:\b[Tt]he|\b(?:While|If) a) friendly [A-Z][a-z][\w'’-]*(?: [A-Z][a-z][\w'’-]*)*\b(?! units)",
                 effect):
        return "self"
    if re.search(r"\b(?:for|by|of) enemy (?:[A-Z][\w'’-]* )*units\b|\benemy (?:[A-Z][\w'’-]* )*units have\b",
                 effect):
        return "all_enemies"
    if re.search(r"\byou (?:receive|gain) (?:\d+|D\d|an?|one)\b", effect):
        return "army"   # ressource de faction : profite au joueur
    if re.search(r"\b(?:[Ee]ach time an?|[Ee]ach) friendly (?:non-[A-Z]+ )?[A-Z][\w'’-]*", effect):
        return "army"
    if re.search(r"\b(?:re-roll|[Rr]e-roll 1 dice in) (?:the|that) (?:charge|casting|chanting|unbinding|delusion) "
                 r"roll\b|\bthat (?:charge|casting|chanting|unbinding) roll\b|for that (?:ability|spell)\b", effect):
        return "one_friendly"   # réaction : l'unité qui fait le jet
    return None


# ----- déclenchement ---------------------------------------------------------------

_GATE_D6 = re.compile(r"\b[Rr]oll a dice\b(?! for each)[^.]*\.(?:[^.]*?)\b[Oo]n an? (\d)\+")
_GATE_2D6 = re.compile(r"\b[Rr]oll 2D6\b[^.]*\.(?:[^.]*?)\b[Oo]n an? (\d{1,2})\+")
_GATE_VS_STAT = re.compile(
    r"Roll (?:2D6|a dice|D3|3D6)\. If (?:the )?(?:roll|result) (?:exceeds|is (?:equal to or )?greater than|"
    r"equals or exceeds|is (?:equal to or )?less than)", re.I)
#: Probabilité forfaitaire d'un test contre une caractéristique de la cible inconnue.
OPPOSED_TEST_PROB = 0.5
#: Par caractéristique visée : « D6 > Contrôle » (Contrôle 1-2 en général : 83 %/67 %),
#: « 2D6 > PV » d'un héros (~6 PV : 42 %).
OPPOSED_TEST_PROBS = {"control": 0.75, "health": 0.42}
_BINOMIAL = re.compile(
    r"roll a (?:number of )?dice (?:for each|equal to)|roll a number of dice|"
    r"for each (?:\d\+|roll of)|for each (?:model|enemy model|point)", re.I)
_DICE_IN_EFFECT = re.compile(r"\b\d?D[36](?:\+\d)?\b")


def p_prayer_banked(n: int) -> float:
    """P(prière à `n` exaucée au round clé), points rituels stockés au tour précédent (Core Rules 19.0).

    Un 1 naturel échoue (et retire D3 points : la réserve d'une seule tentative est alors vide) ; un jet
    de 2+ peut être stocké en points rituels, puis ajouté au jet suivant. Deux tentatives : on stocke au
    round 1 et on prie au round clé — ou on prie directement si c'est plus sûr (petite valeur).
    Une prière ne se dissipe pas, contrairement à un sort.
    """
    banked = 0.0
    for d1 in range(1, 7):
        rp = d1 if d1 >= 2 else 0
        banked += sum(1 for d2 in range(2, 7) if d2 + rp >= n) / 36.0
    return max(p_d6(n), banked)


def activation_of(raw: RawAbility, effect: str) -> tuple[float, list[str], str]:
    """(probabilité de déclenchement, notes FR, variance de l'effet)."""
    p, notes = 1.0, []
    cost = raw.cost_type.lower()
    val = re.match(r"\d+", raw.cost_value or "")
    if cost == "spell" and val:
        n = int(val.group())
        p *= p_2d6(n)
        notes.append(f"sort à {n} : {p_2d6(n):.0%} au lancer (dissipation ignorée)")
    elif cost == "prayer" and val:
        n = int(val.group())
        p *= p_prayer_banked(n)
        notes.append(f"prière à {n} : {p_prayer_banked(n):.0%} au round clé (points rituels stockés au round 1 ; "
                     f"{p_d6(n):.0%} d'un seul jet ; pas de dissipation)")
    elif cost == "command":
        notes.append(f"ordre : {raw.cost_value or 1} PC")
    elif cost:
        notes.append(f"coût {raw.cost_type} {raw.cost_value}")

    m = _GATE_D6.search(effect)
    if m and not _BINOMIAL.search(effect[: m.start() + 40]):
        n = int(m.group(1))
        p *= p_d6(n)
        note = f"jet de déclenchement {n}+ : {p_d6(n):.0%}"
        if re.search(r"[Aa]dd 1 to the roll", effect):
            note += " (bonus possible)"
        notes.append(note)
    else:
        m = _GATE_2D6.search(effect)
        if m:
            n = int(m.group(1))
            p *= p_2d6(n)
            notes.append(f"test 2D6 à {n}+ : {p_2d6(n):.0%}")
        elif _GATE_VS_STAT.search(effect):
            m = _GATE_VS_STAT.search(effect)
            stat = re.search(r"(Control|Health|Save|Move)\b", effect[m.end():m.end() + 60])
            key = stat.group(1).lower() if stat else ""
            prob = OPPOSED_TEST_PROBS.get(key, OPPOSED_TEST_PROB)
            p *= prob
            label = {"control": "le Contrôle", "health": "les PV", "save": "la Sauvegarde", "move": "le Mouvement"}
            notes.append(f"test contre {label.get(key, 'une caractéristique')} de la cible : "
                         f"~{prob:.0%} hors contexte")

    if _BINOMIAL.search(effect):
        variance = "binomial"
    elif _DICE_IN_EFFECT.search(effect):
        variance = "des"
    else:
        variance = "fixe"
    return p, notes, variance


# ----- effets ----------------------------------------------------------------------

_STAT_NAMES = [
    (r"hit rolls? and wound rolls?", ("hit", "wound")),
    (r"run rolls? and charge rolls?", ("run", "charge")),
    (r"casting rolls? and (?:chanting|unbinding) rolls?", ("cast", "chant")),
    (r"hit rolls?", ("hit",)), (r"wound rolls?", ("wound",)), (r"save rolls?", ("save",)),
    (r"ward rolls?", ("ward",)), (r"charge rolls?", ("charge",)), (r"run rolls?", ("run",)),
    (r"casting rolls?", ("cast",)), (r"chanting rolls?", ("chant",)),
    (r"unbinding rolls?", ("unbind",)), (r"banishment rolls?", ("banish",)),
    (r"Attacks characteristics?", ("attacks",)), (r"Rend characteristics?", ("rend",)),
    (r"Damage characteristics?", ("damage",)), (r"Health characteristics?", ("health",)),
    (r"Move characteristics?", ("move",)), (r"control scores?", ("control",)),
    (r"power level", ("power_level",)),
]
_MOD_RE = re.compile(r"\b(Add|Subtract|add|subtract) (\d{1,2}|X|D3|D6)\"? (?:to|from) ([^.;]*)")
#: Valeur retenue pour un modificateur variable (v22) : « X » (nombre d'unités, de dés dépensés…) = 1
#: par prudence, dés = leur moyenne.
_VAR_MOD = {"X": 1.0, "D3": 2.0, "D6": 3.5}
_ENEMY_ACTOR = re.compile(
    r"(?:made|used) by (?:enemy|that enemy|each enemy|an enemy|the enemy|those enemy)|"
    r"for (?:visible )?(?:enemy|each enemy|that enemy|those enemy|friendly and enemy)\b|"
    r"of (?:enemy|that enemy|each enemy)\b|enemy units?'s?", re.I)
#: « la cible » : ennemie ou amie selon la clause de cible de l'aptitude (default_side).
_TARGET_ACTOR = re.compile(
    r"made by (?:the target|that unit|them|those|units? in the target)|for (?:the target|that unit)\b|"
    r"(?:the target|target|each target|that unit)'s|of (?:the target|that unit)\b", re.I)
#: Terminologie GW : « this unit » = toujours l'UTILISATEUR de l'aptitude ; « the target » peut
#: être lui-même, une unité amie ou ennemie (défini par l'Annonce). « against this unit » = les
#: attaques ennemies qui visent l'utilisateur.
_TARGETS_US = re.compile(
    r"that target (?:this unit|(?:other |another |a |any |visible )*friendly|that friendly|it\b|your general|"
    r"the caster\b|the chanter\b|this general\b|them\b|that (?:TWIN|HERO)\b|those TWINS\b|"
    r"units? (?:that are )?wholly within|the target\b(?=[^.]*friendly)|units? in this)|"
    r"\bagainst (?:this unit|friendly)\b", re.I)
#: Lanceurs sans « friendly » (« for WIZARDS within 12" », « for that WIZARD ») : jet ennemi (v15).
_CASTER_ACTOR = re.compile(r"\bfor (?:that |each |any )?(?:WIZARDS?|PRIESTS?)\b")
_CASTER_STATS = ("cast", "chant", "unbind", "power_level", "banish")
#: « ward/save rolls for damage points inflicted by attacks made with this unit's X » : le jet est
#: celui de l'ennemi qui encaisse NOS attaques → buff offensif, pas malus (v15).
_OUR_ATTACKS_DEFENCE = re.compile(
    r"(?:inflicted by|for) (?:combat |shooting )?attacks made (?:by|with|as part of) (?:this unit|this model|"
    r"friendly|that (?:SHOOT|FIGHT))|inflicted by (?:this unit's|its) (?:combat |shooting )?attacks|"
    r"inflicted by abilities used by this unit", re.I)
#: « the target unit's » dans une phrase d'attaque = l'unité visée par l'attaque, donc ennemie (v15).
_ATTACK_TARGET = re.compile(
    r"\b(?:an?|each|the) (?:shooting |combat )?attack (?:made|that|scores)[^.]*\bthe target unit's\b")
#: Sous-aptitude qui (re)désigne une unité (« Prophecy of Exile: Pick a visible enemy WIZARD… »,
#: « If you picked an enemy unit: ») : le sens des phrases suivantes en dépend (v15).
_LOCAL_ENEMY = re.compile(r"\b[Pp]ick (?:a|an|one|up to \d+|\d+)? ?(?:other )?(?:visible )?enemy\b|"
                          r"\bIf you picked (?:an )?enemy\b|\bIf the target is an enemy\b|"
                          r"\b(?:If|While|Each time) (?:an|any|that) enemy unit\b|\ban enemy unit (?:is|becomes)\b|"
                          r"\ballocated to (?:an|any) enemy units?\b|\bthe target unit becomes\b")
_LOCAL_FRIENDLY = re.compile(r"\b[Pp]ick (?:a|an|one|up to \d+|\d+)? ?(?:other )?(?:visible )?friendly\b|"
                             r"\bIf you picked (?:a )?friendly\b|\bIf you picked this unit\b|"
                             r"\bIf the target is a friendly\b")
#: « attaques qui ciblent la cible / cette unité » quand la cible est amie
_TARGETS_TARGET = re.compile(r"that target (?:the target|that unit|that friendly unit|each target)\b", re.I)


#: « attacks that target that unit / the bet / its quarry / the condemned unit » quand la cible
#: désignée est ennemie. Marquage seulement si d'AUTRES unités amies en profitent (voir _stat_mods).
_MARKED_TARGET = re.compile(
    r"(?:attacks|weapons)[^.]*?that target (?!this unit|friendly|that friendly)(?:that|the|its|each|it)\b", re.I)
#: Attaquant = l'utilisateur seul (« this unit's Templar Weapon », « attacks made by this unit »).
_SELF_ATTACKER = re.compile(r"\bthis (?:unit|model)\b|\bits\b|\b(?:his|her)\b")


def _stat_mods(sentence: str, default_side: str, declared_side: str = "") -> list[Effect]:
    out = []
    for m in _MOD_RE.finditer(sentence):
        verb, rest = m.group(1).lower(), m.group(3)
        n = _VAR_MOD[m.group(2)] if m.group(2) in _VAR_MOD else int(m.group(2))
        rest = re.split(r"\band (?:add|subtract)\b", rest)[0]
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
            default_side == "enemy" and (target_actor or not re.search(
                r"friendly|this unit|the caster|the chanter|units? you picked|in this Regiment", rest)))
        # « the target's … » suit la cible DÉCLARÉE, même si la phrase cite une unité ennemie avant
        # (« if damage was allocated to an enemy unit by the target's attacks … the target's weapons »)
        if declared_side == "friendly" and target_actor and not _ENEMY_ACTOR.search(rest) \
                and re.search(r"\b(?:the target|each target|target)(?:'s|s')|(?:for|by) the target\b", rest):
            enemy_actor = False
        enemy_actor = enemy_actor or bool(_ATTACK_TARGET.search(sentence)) or (
            any(st in _CASTER_STATS for st in stats) and bool(_CASTER_ACTOR.search(rest))
            and not re.search(r"\bfriendly\b", rest))
        targets_us = bool(_TARGETS_US.search(rest)) or (
            default_side == "friendly" and bool(_TARGETS_TARGET.search(rest)))
        marks_target = False
        mk = _MARKED_TARGET.search(rest) if verb == "add" and default_side == "enemy" else None
        if mk:
            head = rest[:rest.find("that target", mk.start())]
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
            elif stat in ("save", "ward", "control", "cast", "chant", "unbind", "charge", "run",
                          "move", "health", "power_level", "banish") and enemy_actor:
                side = "enemy"
                role = "debuff" if sign < 0 else "malus"
            else:
                side = "friendly"
                role = ("offensif" if stat in ("hit", "wound", "attacks", "rend", "damage")
                        else "defensif" if stat in ("save", "ward", "health") else "utilitaire")
                if sign < 0:
                    role = "malus"
            value = sign * n
            if side == "enemy" and re.search(r"\bCompanion (?:melee |ranged )?weapons\b", rest):
                value /= 2   # débuff limité aux armes Compagnon : peu de poids dans un profil (v22)
            out.append(Effect("stat_mod", stat, value, "", side, role))
    return out


_MORTAL_RE = re.compile(
    r"[Ii]nflict (\d+|\d?D[36](?:\+\d)?|an amount of|a number of|that many|X)?\s*mortal damage")
_MORTAL_PER_ROLL = re.compile(r"[Ff]or each (?:\d\+|roll[^,]*|dice[^,]*),[^.]*?inflict (\d+) mortal damage")
_WARD_RE = re.compile(r"WARD \((\d)\+\)", re.I)
_HEAL_RE = re.compile(r"\b[Hh]eal \(?(\d+|\d?D[36](?:\+\d)?|X)\)?")
_RETURN_RE = re.compile(
    r"\b[Rr]eturn (\d+|\d?D[36]|a number of|any number of|up to \d+)? ?(?:[^.]*?slain models?|slain\b)")
_MOVE_RE = re.compile(r"can (?:immediately )?move (?:up to |a distance (?:in inches )?(?:up to |equal to )?(?:the value of )?)?(\d+|\d?D[36])?\"?")

#: (regex, kind, stat, poids de base) pour les effets qualitatifs
QUALITATIVE_RULES: list[tuple[str, str, str]] = [
    (r"STRIKE-FIRST", "strike_first", ""),
    (r"STRIKE-LAST", "strike_last", ""),
    (r"can (?:still )?use (?:a )?(?:'?(?:SHOOT and/or )?CHARGE'? abilities|charge)[^.]*(?:after|even though|even if)"
     r"[^.]*(?:[Rr]un|RUN|[Rr]etreat|RETREAT)|"
     r"can still use CHARGE|can use CHARGE abilities[^.]*(?:run|retreat)|can still charge",
     "run_and_charge", ""),
    (r"can (?:still )?use (?:'?SHOOT(?: and/or CHARGE)?'? abilities|shoot)[^.]*(?:[Rr]un|RUN|[Rr]etreat|RETREAT)|"
     r"can still use SHOOT",
     "run_and_shoot", ""),
    (r"[Rr]emove (?:this|that|the target|it)[^.]*?from the battlefield[^.]*?set (?:it|them|that unit|this unit) up again|"
     r"set (?:it|this unit|that unit|them) up again|set up again", "redeploy", ""),
    # Vrai double combat (« can use 2 FIGHT abilities this phase », Gunnar Brand, Battle-fury…), à ne pas
    # confondre avec `extra_fight` ci-dessous (« can be picked to use a FIGHT ability immediately after » :
    # enchaînement d'activations) ni avec « pick 2 units instead of 1 » (Lightning Reactions).
    (r"(?i)\bcan use (?:2|two) FIGHT abilities", "fight_twice", ""),
    (r"can (?:immediately )?use (?:a|another) ?'?FIGHT'? abilit|fight (?:again|immediately|a second time)|"
     r"can be picked to use a FIGHT ability|(?:immediately )?resolve (?:combat|shooting) attacks|"
     r"immediately (?:make|resolve) [^.]*attacks|\bResolve combat attacks for this unit against", "extra_fight", ""),
    (r"can use (?:the )?'?(?:Normal Move|Run|Retreat)'? ability|can use a (?:RUN|MOVE) ability|"
     r"as if it (?:were|was) your movement phase|use a (?:RETREAT|RUN|MOVE) ability", "extra_move", ""),
    (r"[Ss]et up (?:that|the target|this|the) unit (?:on the battlefield )?(?:again )?wholly within|"
     r"[Ss]et (?:up )?(?:the targets?|those units|that unit|this unit|it|them) (?:up )?on the battlefield|"
     r"[Ss]et up [^.]*?\bin reserve\b|in reserve[^.]*?can be set up", "deep_strike", ""),
    (r"(?i)ignore (?:negative )?modifiers to (?:save|ward)|ignore the first damage point|"
     r"ignore (?:the first )?\d+ damage points?", "damage_ignore", ""),
    (r"weapon abilities [^.]*?have no effect|cannot (?:use|benefit from) [^.]*?weapon abilities|"
     r"weapon ability has no effect", "no_weapon_abilities", ""),
    # v21 : « ignore positive modifiers to save rolls for the target » (anti-buff ennemi)
    (r"[Ii]gnore positive modifiers to (?:save|ward|hit|wound) rolls for (?:the target|that unit|those units|"
     r"enemy|each target)", "no_buff", ""),
    (r"(?i)\b(?:gain|receive|generate) (?:\d+|d3|an?|one|1 extra) (?:extra |additional )?"
     r"(?:fate points?|chords?|rage dice|momentum points?|tokens?|ritual points?|blood tithe points?|"
     r"[a-z]+ points?)", "resource", ""),
    (r"twice per (?:turn|phase)|additional target|does not count towards|be a second target|"
     r"pick (?:2|two) [^.]*? instead of (?:1|one)\b", "extra_use", ""),
    (r"While this unit has \d+ or more damage points, the [^.]*?(?:characteristic|keyword) [^.]*?is \d",
     "battle_damaged", ""),
    (r"cannot score critical hits", "no_crit", ""),
    (r"ward rolls cannot be made for (?!(?:that|those|the) damage point)", "no_ward", ""),
    (r"(?:automatically|immediately) (?:destroyed|slain)|\bis slain\b(?=[^.]*target)|"
     r"\bmodels? in the target unit (?:is|are) slain", "slay", ""),
    (r"[Dd]ouble the (?:Attacks|Damage|Rend|Move)|characteristic of [^.]*?(?:is|of) \d+ instead|"
     r"has a (?:Health|Move|Save|Control) characteristic of \d+", "stat_set", ""),
    (r"the attack fails|attack sequence ends", "negate_attack", ""),
    (r"(?:has|gains?) the [A-Z][A-Z -]+ keyword", "keyword_gain", ""),
    (r"can use (?:a|another) ?'?SHOOT'? abilit|shoot (?:again|a second time)|"
     r"can (?:immediately )?use (?:a|the) '?SHOOT'? ability as if", "extra_shoot", ""),
    # v21 : jet remplacé par une valeur fixe (« use a value of 6 for the roll that cannot be modified »)
    (r"(?:you )?can use a value of \d+ (?:for (?:the|it|that)|instead)|"
     r"use it as the roll|replaced with the roll on the destiny dice", "fixed_roll", ""),   # v25 : dés du destin
    # v21 : relances de ralliement supplémentaires (« make 3 additional rally rolls of D6 »)
    (r"(?:make|makes?) (?:\d+|D\d|an?) additional rally rolls?|additional rally roll", "rally", ""),
    # v21 : sort hors phase des héros (« can use a SPELL ability as if it were your hero phase »)
    (r"can use (?:a|another) (?:non-SUMMON )?(?:SPELL|PRAYER) ability as if", "extra_use", ""),
    (r"Shoot in Combat", "shoot_in_combat", ""),
    (r"(?:score )?critical hits? on (?:unmodified )?hit rolls? of \d\+|Crit \((?:2 Hits|Auto-wound|Mortal)\)|"
     r"score critical hits", "crit", ""),
    (r"(?:gain|receive) (?:\d|D3|an extra|1 extra|one extra|an additional) (?:extra )?command points?|"
     r"command points? (?:is|are) (?:gained|received)|gain a command point|no command points are spent|"
     r"without spending (?:a |any )?command points?", "cp_gain", ""),
    (r"\bcan(?:not)? use (?:the )?'?(?:Unbind|Banish)'?|\bunbind\b|\bbanish\b|spell is unbound",
     "anti_magic", ""),
    (r"cannot (?:use|be picked to use) (?:commands|any commands|SPELL|PRAYER|abilities)|"
     r"cannot issue commands|cannot receive commands|cannot use the '[^']+' command|"
     r"unless your opponent spends \d+ (?:additional|extra) command point", "lockout", ""),
    (r"cannot (?:use )?(?:CHARGE|charge|RUN|run|RETREAT|retreat|SHOOT|shoot|move|be set up|contest)",
     "restriction", ""),
    # « cannot be picked to be the target of this ability again » est une limite d'usage, pas un effet
    (r"cannot be (?:picked as the )?target(?! of this)|cannot be picked to be the target of (?:attacks|shooting|"
     r"combat|SPELL|PRAYER|BANISH|abilities used by enemy|enemy)|not visible to|is not visible",
     "untargetable", ""),
    (r"\bFLY\b|can pass through (?:models|the combat ranges)|can move through (?:the combat ranges|models|terrain)",
     "fly", ""),
    # v21 (revue « a-revoir ») : retraite sans blessures mortelles
    (r"[Nn]o mortal damage is inflicted on [^.]*?(?:RETREAT|Retreat)|(?:RETREAT|Retreat) abilit[^.]*?no mortal damage",
     "free_retreat", ""),
    (r"[Hh]alve (?:the|its|their) Move|subtract \d\" from[^.]*Move|[Hh]alve (?:run|charge) rolls", "move_debuff", ""),
    (r"[Ss]et up (?:a|an|one|\d+|up to \d+)? ?(?:new |replacement )?[^.]*?(?:unit|manifestation|ENDLESS SPELL)"
     r"[^.]*?(?:wholly within|within|on the battlefield)|[Ss]et up (?:a|an) [A-Z][^.]*?within \d+\" of the (?:caster|chanter)",
     "summon", ""),
    (r"control score|contest objectives|\bcontrol (?:that|the) objective|gain control", "control", ""),
    (r"Anti-([A-Za-z -]+?) \(\+1 (\w+)\)", "anti", ""),
    # « ignore the effect of the Charge (+1 Damage) ability for … enemy units » (Anticipated Strike) :
    # c'est l'anti-charge d'un bonus ENNEMI, pas un bonus de charge pour nous (analyseur v18).
    (r"(?<!effect of the )Charge \(\+1 (?:Damage|Rend|Attacks)\)(?! weapon ability has no effect)",
     "charge_bonus", ""),
    (r"pile-in move|pile in", "pile_in", ""),
    (r"[Ss]ubtract \d+ from the number of (?:wounds|damage points)|damage points? (?:to|on) [^.]*?is reduced|"
     r"allocate[^.]*? to (?:this|that|another) unit instead", "damage_redirect", ""),
]


#: Relances (analyseur v25) : verbe « re-roll » seul — « cannot be re-rolled », « after any re-rolls »,
#: « each hit roll that is re-rolled » ne sont pas des relances accordées. « re roll » (sans tiret) existe.
_REROLL_RE = re.compile(r"\b[Rr]e[- ]?roll\b(?![- ]?(?:ed|s)\b)([^.:\n]*)")
_REROLL_STATS = (("charge", r"charge rolls?"), ("run", r"run rolls?"), ("hit", r"hit rolls?"),
                 ("wound", r"wound rolls?"), ("save", r"save rolls?"), ("cast", r"casting rolls?"),
                 ("chant", r"chanting rolls?"), ("unbind", r"unbinding rolls?"), ("ward", r"ward rolls?"))
#: Relance partielle (validé utilisateur : moitié d'une relance complète) : 1 seul jet, 1 seul dé, les 1.
_REROLL_PARTIAL = re.compile(r"^\s*(?:\d+|a|one) (?:of the )?(?:dice|[a-z']+ rolls?)\b|\brolls? of 1\b")


def rerolls_of(full: str) -> list[tuple[Effect, int]]:
    """Une relance par jet relancé (« re-roll run rolls and charge rolls » = 2 effets), stat '' si le
    jet n'est pas nommé (« re-roll the dice »). `value` = 1 (complète) ou 0,5 (partielle)."""
    found: dict[str, tuple[Effect, int]] = {}
    for m in _REROLL_RE.finditer(full):
        if re.search(r"(?:casting|chanting) roll was \d+\+[^.]*$", full[max(0, m.start() - 160):m.start()]):
            continue   # bonus sur un jet élevé : pas acquis (v21)
        clause = m.group(1)
        # « re-roll 1 hit roll, or 1 wound roll » : chaque jet de l'énumération est partiel
        partial = bool(_REROLL_PARTIAL.search(clause))
        stats = [st for st, pat in _REROLL_STATS if re.search(r"\b" + pat + r"\b", clause)] or [""]
        for st in stats:
            e = Effect("reroll", st, 0.5 if partial else 1.0, "", "friendly",
                       "relance partielle" if partial else "relance")
            if st not in found or e.value > found[st][0].value:
                found[st] = (e, m.start())
    return list(found.values())


_OFFENSIVE_STATS = ("hit", "wound", "attacks", "rend", "damage")
#: effets qualitatifs qui portent sur des attaques (périmètre d'armes pertinent)
_WEAPON_KINDS = {"crit", "anti", "charge_bonus", "reroll", "no_crit", "no_weapon_abilities", "stat_set"}


def _annotate(e: Effect, sentence: str, text: str, passive: bool, enemy_target: bool = False,
              condition: str = "") -> Effect:
    """Ajoute le périmètre (armes, cible, prérequis, durée) lu dans la phrase source."""
    offensive = (e.kind == "stat_mod" and e.stat in _OFFENSIVE_STATS) or (
        e.kind in _WEAPON_KINDS and not (e.kind == "reroll" and e.stat not in ("hit", "wound", "")))
    ft = effect_friendly_target(sentence, text) if e.side == "friendly" else ""
    return dataclasses.replace(e, friendly_target=ft, **perimeter_of(sentence, text, passive, offensive, e.kind,
                                                                      enemy_target, condition))


def effects_of(declare: str, effect: str, scope: Scope, passive: bool = False, condition: str = ""
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
                declared = ""   # re-désignation explicite : « the target » est désormais ennemie
        elif _LOCAL_FRIENDLY.search(sentence):
            local_side = "friendly"
        out.extend(_annotate(e, sentence, effect, passive, local_side == "enemy", condition)
                   for e in _stat_mods(sentence, local_side, declared))

    seen_mortal = False
    for m in _MORTAL_PER_ROLL.finditer(effect):
        add(Effect("mortal_damage", "", 0.0, "par jet", "enemy", "binomial"), effect, m.start())
        seen_mortal = True
    for m in _MORTAL_RE.finditer(effect):
        expr = m.group(1) or ""
        if seen_mortal and not expr[:1].isdigit() and "D" not in expr:
            continue
        mean = dice_mean(expr) if expr else None
        target_us = bool(re.search(r"mortal damage on (?:this unit|it|that friendly)", effect[m.start():m.end() + 40]))
        add(Effect("mortal_damage", "", mean or 0.0, expr if "D" in expr else "",
                   "friendly" if target_us else "enemy",
                   "auto-infligé" if target_us else ("variable" if mean is None else "")), effect, m.start())
    for m in re.finditer(r"[Aa]llocate (\d+|D\d(?:\+\d)?|a number of) damage points? to (?:the target|each target|"
                         r"that enemy unit|each enemy unit|the enemy unit)\b", effect):
        expr = m.group(1)
        mean = dice_mean(expr) if expr != "a number of" else None
        add(Effect("mortal_damage", "", mean or 0.0, expr if "D" in expr else "", "enemy",
                   "variable" if mean is None else ""), effect, m.start())
    fragile = bool(re.search(r"unmodified save roll of 1[^.]*remove", effect))
    for m in _WARD_RE.finditer(effect):
        side = "enemy" if re.search(r"target[^.]*enemy|enemy units have", effect) and default_side == "enemy" else "friendly"
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
        if re.search(r"cannot move|can move[^.]*but cannot", effect[m.start() - 10:m.start() + 5]):
            continue
        mean = dice_mean(expr) if expr else None
        side = "enemy" if re.search(r"the target can move|enemy", effect[max(0, m.start() - 40):m.start()]) \
            and default_side == "enemy" else "friendly"
        add(Effect("move", "", mean or 0.0, expr if "D" in expr else "", side), effect, m.start())

    target_kw: list[str] = []
    full = f"{declare} {effect}"
    for e, pos in rerolls_of(full):
        add(e, full, pos)
    for pat, kind, stat in QUALITATIVE_RULES:
        for m in re.finditer(pat, full):
            if kind == "anti":
                target_kw.append(m.group(1).upper())
            if re.search(r"(?:casting|chanting) roll was \d+\+[^.]*$", full[max(0, m.start() - 160):m.start()]):
                continue   # bonus sur un jet élevé (« If the chanting roll was 8+, in addition … ») : pas acquis
            if kind == "no_weapon_abilities" and re.search(r"The Companion weapon ability has no effect on",
                                                            full[max(0, m.start() - 40):m.end() + 5]):
                continue   # contrainte sur nos propres unités (Monstrous Entourage), pas un débuff
            if kind == "fly" and "FLY" not in m.group(0) \
                    and any(e.kind in ("move", "extra_move", "redeploy", "deep_strike") for e in out):
                continue   # « It can move through the combat ranges » : modalité du mouvement, pas un effet en plus
            side = default_side
            if kind in ("no_ward", "slay", "no_weapon_abilities", "no_crit", "no_buff"):
                side = "enemy"
            if kind in ("strike_last", "restriction", "lockout", "move_debuff", "untargetable"):
                side = "enemy" if re.search(r"target|enemy", full[max(0, m.start() - 80):m.start()]) else "friendly"
            if kind in ("strike_first", "run_and_charge", "run_and_shoot", "redeploy", "extra_fight", "fight_twice",
                        "extra_shoot", "fly", "cp_gain", "crit", "shoot_in_combat", "charge_bonus",
                        "summon", "anti_magic", "control", "pile_in", "damage_redirect", "anti", "extra_move",
                        "deep_strike", "stat_set", "negate_attack", "keyword_gain", "damage_ignore",
                        "resource", "extra_use", "battle_damaged", "free_retreat", "fixed_roll", "rally"):
                side = "friendly"
            add(Effect(kind, stat, 0.0, "", side, m.group(0)[:80]), full, m.start())
            break  # un même effet qualitatif compte une fois

    for kw in re.findall(r"\b(MONSTER|HERO|INFANTRY|CAVALRY|WIZARD|PRIEST|WAR MACHINE|MANIFESTATION)S?\b", declare):
        if re.search(r"enemy " + kw, declare):
            target_kw.append(kw)

    scales = bool(re.search(r"for each model in (?:this|that|the target) unit|number of models in", full, re.I))
    return out, sorted(set(target_kw)), scales


_UNLOCK_RE = re.compile(r"if you have unlocked (?:already )?((?:'[^']+'(?:,? or |, )?)+)", re.I)


def unlock_prereqs_of(effect: str) -> list[str]:
    """Aptitudes dont l'une doit déjà être débloquée (« unlocked 'X' or 'Y' »)."""
    m = _UNLOCK_RE.search(effect)
    return re.findall(r"'([^']+)'", m.group(1)) if m else []


#: Mots en minuscules tolérés dans une restriction de cible amie (états, pas des mots-clés).
_FRIENDLY_FILLERS = {"or", "and", "unified", "anointed", "other", "damaged", "visible"}
_FRIENDLY_STOPS = {"unit", "units", "model", "models"}


_OTHER_FRIENDLY = re.compile(r"\b(?:another|other) friendly\b|friendly [^.]*?\bother than (?:this|that) (?:unit|model)",
                             re.I)


def excludes_self_of(declare: str, effect: str) -> bool:
    """« another / other friendly unit » : le porteur ne peut pas être sa propre cible."""
    seg = _target_clause(declare) or (_target_clause(effect) if _TARGET_PHRASE.search(effect) else "")
    return bool(_OTHER_FRIENDLY.search(seg or f"{declare} {effect}"))


def friendly_target_of(declare: str, effect: str) -> str:
    """Restriction de mots-clés/nom de la cible amie, telle qu'écrite (« non-HERO WARRIORS OF CHAOS
    INFANTRY », « Crypt Horrors », « DEATHRATTLE or DEADWALKERS »), '' si aucune.

    Lit d'abord la clause « Pick … to be the target », puis le reste du texte (auras « friendly X units
    wholly within ») ; ignore le choix du lanceur (« friendly WIZARD to cast this spell »). La couche 3
    (`analysis/encounter.py`) la résout contre les mots-clés des unités.
    """
    seg = _target_clause(declare) or (_target_clause(effect) if _TARGET_PHRASE.search(effect) else "")
    for text in (seg, declare, effect):
        for m in re.finditer(r"\b[Ff]riendly\b", text):
            words = text[m.end():].split()
            out: list[str] = []
            for w in words[:12]:
                wc = w.strip(",;:.")
                if wc.lower() in _FRIENDLY_STOPS:
                    break
                if not (wc[:1].isupper() or wc.startswith("non-") or wc.lower() in _FRIENDLY_FILLERS):
                    break
                out.append(wc)
                if wc != w:
                    break
            rest = " ".join(words[len(out):len(out) + 2]).lower()
            if rest.startswith(("to cast", "to chant", "to use", "to summon")):
                continue
            while out and out[-1].lower() in _FRIENDLY_FILLERS:
                out.pop()
            return " ".join(out) if any(t[:1].isupper() or t.startswith("non-") for t in out) else ""
    return ""


#: Ligne d'option (« Commander of Vermin: Add 1 … ») ou de puce (« - You can … ») d'une aptitude à choix.
_OPTION_LINE = re.compile(r"^(?:- |[A-Z][^:\n.]{2,45}: )")
#: « within 12" of a friendly Gnawhole », « of the friendly Sigvald » : repère de position, pas un receveur.
_FRIENDLY_LANDMARK = re.compile(r"\b(?:of|from|by|with|near) (?:an?|the|any|each|another|that|this|\d+) $")


def _line_of(sentence: str, text: str) -> str:
    i = text.find(sentence[:40])
    if i < 0:
        return sentence
    start = text.rfind("\n", 0, i) + 1
    end = text.find("\n", i)
    return text[start:end if end >= 0 else len(text)]


def effect_friendly_target(sentence: str, text: str) -> str:
    """Cible amie propre à un effet (analyseur v26) : « friendly X » de sa phrase, hors repères de position.
    Marquée « option: » quand la phrase est une ligne d'option/puce, pour que `extract` sache si elle
    doit l'emporter sur la cible de l'aptitude."""
    kept = sentence
    for m in re.finditer(r"\b[Ff]riendly\b", kept):
        if _FRIENDLY_LANDMARK.search(kept[max(0, m.start() - 20):m.start()]):
            continue
        ft = friendly_target_of("", kept[m.start():])
        if ft:
            return ("option:" if _OPTION_LINE.match(_line_of(sentence, text)) else "") + ft
        return ""
    return ""


def extract(raw: RawAbility) -> tuple[Extraction, float]:
    """Extraction complète + pénalité de mise en place cumulée (utilisée par scoring)."""
    main, secondary = split_main_secondary(raw.effect)
    scope, rng, wholly = scope_of(raw.declare, raw.effect)
    enemy_target = scope in ("one_enemy", "enemy_aura", "all_enemies")
    conditions, penalty = conditions_of(f"{raw.condition} {raw.declare} {main}", enemy_target)
    if secondary:
        # prérequis propres à un effet secondaire : notés, sans pénalité de mise en place
        conditions += [f"{c} (effet secondaire seulement)" for c in conditions_of(secondary, enemy_target)[0]
                       if c not in conditions]
    p, notes, variance = activation_of(raw, raw.effect)
    effects, target_kw, scales = effects_of(raw.declare, raw.effect, scope,
                                            passive=raw.condition.lower().startswith("passive"),
                                            condition=raw.condition)
    # condition de charge portée par l'Annonce (« Pick up to 3 friendly Verminus units that charged this
    # turn ») : elle vaut pour tous les effets amis, pas seulement pour la phrase qui les porte (v23)
    if "nous" in charge_subjects(raw.declare, enemy_target):
        effects = [e if e.side != "friendly" or "a chargé" in (e.requires or "")
                   else dataclasses.replace(e, requires=" | ".join(filter(None, ["a chargé", e.requires])))
                   for e in effects]
    # cible amie par effet (v26) : une ligne d'option l'emporte ; ailleurs, seulement si l'aptitude n'en a pas
    ability_ft = friendly_target_of(raw.declare, raw.effect)
    effects = [dataclasses.replace(e, friendly_target=(
        e.friendly_target[7:] if e.friendly_target.startswith("option:")
        else ("" if ability_ft else e.friendly_target)))
        for e in effects]
    effects = [e if e.friendly_target != ability_ft else dataclasses.replace(e, friendly_target="")
               for e in effects]
    ex = Extraction(
        frequency=frequency_of(raw.condition),
        turn=turn_of(raw.condition, raw.phase),
        scope=scope,
        range_inches=rng,
        wholly_within=wholly,
        activation_prob=round(p, 4),
        activation_notes=notes,
        conditions=conditions,
        effects=effects,
        variance=variance,  # type: ignore[arg-type]
        target_keywords=target_kw,
        scales_with_size=scales,
        unlock_prereqs=unlock_prereqs_of(raw.effect),
        # marquage : unités amies qui profitent de la cible désignée (« Hobgrot Slittaz », « NIGHTHAUNT »)
        excludes_self=scope in ("one_friendly", "friendly_aura", "army") and excludes_self_of(raw.declare, raw.effect),
        friendly_target=friendly_target_of(raw.declare, raw.effect)
        if scope in ("one_friendly", "friendly_aura", "army")
        or any(e.detail == "marquage" for e in effects) else "",
    )
    return ex, penalty
