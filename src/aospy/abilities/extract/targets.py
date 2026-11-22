"""Prérequis de déblocage et cible amie désignée (marquage, options)."""

from __future__ import annotations

import re

from .scope import _TARGET_PHRASE, _target_clause

_UNLOCK_RE = re.compile(r"if you have unlocked (?:already )?((?:'[^']+'(?:,? or |, )?)+)", re.I)


def unlock_prereqs_of(effect: str) -> list[str]:
    """Aptitudes dont l'une doit déjà être débloquée (« unlocked 'X' or 'Y' »)."""
    m = _UNLOCK_RE.search(effect)
    return re.findall(r"'([^']+)'", m.group(1)) if m else []


#: Mots en minuscules tolérés dans une restriction de cible amie (états, pas des mots-clés).
_FRIENDLY_FILLERS = {"or", "and", "unified", "anointed", "other", "damaged", "visible"}
_FRIENDLY_STOPS = {"unit", "units", "model", "models"}


_OTHER_FRIENDLY = re.compile(
    r"\b(?:another|other) friendly\b|friendly [^.]*?\bother than (?:this|that) (?:unit|model)", re.I
)


def excludes_self_of(declare: str, effect: str) -> bool:
    """« another / other friendly unit » : le porteur ne peut pas être sa propre cible."""
    seg = _target_clause(declare) or (_target_clause(effect) if _TARGET_PHRASE.search(effect) else "")
    return bool(_OTHER_FRIENDLY.search(seg or f"{declare} {effect}"))


def friendly_target_of(declare: str, effect: str) -> str:
    """Restriction de mots-clés/nom de la cible amie, telle qu'écrite (« non-HERO WARRIORS OF CHAOS
    INFANTRY », « Crypt Horrors », « DEATHRATTLE or DEADWALKERS »), '' si aucune.

    Lit d'abord la clause « Pick … to be the target », puis le reste du texte (auras « friendly X units
    wholly within ») ; ignore le choix du lanceur (« friendly WIZARD to cast this spell »). La couche 3
    (`analysis/layers/encounter.py`) la résout contre les mots-clés des unités.
    """
    seg = _target_clause(declare) or (_target_clause(effect) if _TARGET_PHRASE.search(effect) else "")
    for text in (seg, declare, effect):
        for m in re.finditer(r"\b[Ff]riendly\b", text):
            words = text[m.end() :].split()
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
            rest = " ".join(words[len(out) : len(out) + 2]).lower()
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
    return text[start : end if end >= 0 else len(text)]


#: Annonce d'un choix exclusif entre les lignes qui suivent (analyseur v33).
_EXCLUSIVE = re.compile(
    r"\b[Pp]ick (?:1|one)(?: of the following)?(?: effects?)?:|\b(?:1|one) of the following\b|"
    r"\bthe effect below that corresponds\b|\b[Cc]hoose (?:1|one)\b|"
    r"\b(?:1|one) of the effects below\b"  # v34 : Tentations HoS (« pick 1 of the effects below »)
)
_OPTION_LABEL = re.compile(r"^(?:([A-Z][^:\n.]{2,45}): |- )")
#: v34 : défi « accept or decline » (You First, I Insist...) : chaque réponse est une option, puces comprises.
_CHALLENGE = re.compile(r"\baccept or decline\b")
_CHALLENGE_ANSWER = re.compile(r"^If they (accept|decline)\b", re.M)
#: v34 : l'adversaire choisit l'option (« your opponent must pick 1 of the effects below », « Your opponent must
#: decide whether … accept or decline ») : il prend la plus faible pour nous → `scoring.power_of` prend le minimum.
OPPONENT_PICKS = re.compile(r"\b[Yy]our opponent must (?:pick (?:1|one) of the|decide whether)\b")


#: v34 : ligne d'une table de résultats aléatoires (« - 2-4 - Unholy Wall of Sound: … », « 1: No effect. »).
#: Les paliers cumulatifs « 4+ : … » n'en sont pas (pas de « + »).
_DICE_ROW = re.compile(r"^\s*(?:-\s*)?(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*(?:[-–—:]|\s(?=[A-Z]))")
#: Préfixe d'une option de table aléatoire : `scoring.power_of` en prend l'espérance, pas le maximum.
DICE_ROW_PREFIX = "dé "
#: Ligne qui reprend l'effet d'une ligne précédente (« In addition to the effect of 'More Power!' »).
DICE_ROW_CUMUL = " +préc"
_ROLL_TABLE = re.compile(r"\b[Rr]oll (?:a dice|a D6|2D6|the dice|\d dice)\b|\bcorresponding\b")
_ROW_CUMUL = re.compile(r"\bin addition to the effect of\b|\bthe effect of '[^']+' applies\b", re.I)


def dice_row_of(line: str, text: str) -> str:
    """Option « dé 2-4 » d'une ligne de table aléatoire (≥ 2 lignes de plages de dé dans le texte), sinon ""."""
    m = _DICE_ROW.match(line)
    # un jet doit annoncer la table : « 1 Launch Countermeasures! » des Cogforts est un coût en jetons de chaleur
    if not m or not _ROLL_TABLE.search(text) or sum(1 for ln in text.split("\n") if _DICE_ROW.match(ln)) < 2:
        return ""
    lo, hi = m.group(1), m.group(2) or m.group(1)
    return f"{DICE_ROW_PREFIX}{lo}-{hi}" + (DICE_ROW_CUMUL if _ROW_CUMUL.search(line) else "")


def option_of(sentence: str, text: str) -> str:
    """Option exclusive qui porte la phrase (« Rune of Fury », « - Inflict … »), '' hors choix exclusif :
    seules comptent les lignes d'option/puce situées APRÈS l'annonce du choix. Une ligne de table de
    résultats aléatoires est une option « dé N-M » (v34)."""
    row = dice_row_of(_line_of(sentence, text), text)
    if row:
        return row
    if _CHALLENGE.search(text):
        i = text.find(_line_of(sentence, text))
        answers = [m for m in _CHALLENGE_ANSWER.finditer(text) if m.start() <= i]
        return answers[-1].group(1) if answers else ""
    ex = _EXCLUSIVE.search(text)
    if not ex:
        return ""
    line = _line_of(sentence, text)
    if text.find(line) <= ex.start():
        return ""
    m = _OPTION_LABEL.match(line)
    if not m:
        return ""
    return m.group(1) or line[2:42].strip()


def effect_friendly_target(sentence: str, text: str) -> str:
    """Cible amie propre à un effet (analyseur v26) : « friendly X » de sa phrase, hors repères de position.
    Marquée « option: » quand la phrase est une ligne d'option/puce, pour que `extract` sache si elle
    doit l'emporter sur la cible de l'aptitude."""
    kept = sentence
    for m in re.finditer(r"\b[Ff]riendly\b", kept):
        if _FRIENDLY_LANDMARK.search(kept[max(0, m.start() - 20) : m.start()]):
            continue
        ft = friendly_target_of("", kept[m.start() :])
        option = bool(_OPTION_LINE.match(_line_of(sentence, text)))
        if not ft and option and re.match(r"friendly units?\b", kept[m.start() :], re.I):
            ft = "*"  # v27 : « for friendly units » sur une ligne d'option = toute unité amie (≠ repli)
        if ft:
            return ("option:" if option else "") + ft
        return ""
    return ""
