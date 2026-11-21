"""Prérequis de mise en place (axe « ease ») et séparation effet principal / secondaire."""

from __future__ import annotations

import re

from ..perimeter import charge_subjects

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
