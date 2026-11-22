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
    r"\bthe effect below that corresponds\b|\b[Cc]hoose (?:1|one)\b"
)
_OPTION_LABEL = re.compile(r"^(?:([A-Z][^:\n.]{2,45}): |- )")


def option_of(sentence: str, text: str) -> str:
    """Option exclusive qui porte la phrase (« Rune of Fury », « - Inflict … »), '' hors choix exclusif :
    seules comptent les lignes d'option/puce situées APRÈS l'annonce du choix."""
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
