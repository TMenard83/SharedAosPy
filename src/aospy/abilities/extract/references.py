"""Mécaniques de faction dont la valeur est dans d'AUTRES aptitudes (analyseur v34, chantier B).

Règles validées par l'utilisateur le 2026-11-22 (questions de valeur, une par mécanique) :

* **méta** (`ability_ref`) — modifie une aptitude nommée (« Add 1 to rolls for 'Ritual of the Creeping
  Mist' », « pick up to 2 targets instead of 1 ») : fraction de la puissance de l'aptitude citée, graduée —
  +1 au jet / portée accrue = 1/3 (`boost`), usage, cible ou éligibilité en plus = 1/2 (`extend`), effet
  appliqué en entier (« as if it were active », sans coût) = 1 (`full`) ;
* **statut** (`status_grant`) — sous ordres, unifié, oint, VOUÉ À…, proie, marque… : moyenne des puissances
  des aptitudes de la faction qui lisent ce statut ;
* **enhancement gratuit** (`free_enhancement`) — « Give the target 1 artefact of power from the 'X' » :
  moyenne de la table citée × nombre de héros (plafond 3), sans malus « une fois par bataille » ;
* **décor en plus** (`terrain_setup`) — Gnarlmaw, Wyldwood, Sépulcre… : 1/2 × moyenne des aptitudes de la
  charte du décor (un décor de plus étend la couverture sans doubler l'effet) ;
* **jeton posé** par une aptitude active et **règles-cadres** (jet de Délire, Faces de la Lune, capacité de
  transport…) : `warscroll_rule` = 0, la valeur est dans l'aptitude-sœur / les aptitudes sélectionnées ;
* **moteurs de rotation** (`engine_factors`) : un Délire n'est cru qu'à certains tours (×5/6), un Cycle MoN
  n'est mûr qu'un round sur plusieurs (×1/3) ; un Sale Tour KB exige un jet de réussite (P = 2/3).

La détection ne porte que sur les aptitudes sans autre effet reconnu (les « a-revoir ») ; les valeurs sont
résolues en seconde passe par `abilities.references.resolve_references`, qui a besoin de toute la base.
"""

from __future__ import annotations

import re

from ..models import Effect, RawAbility

#: Fractions de la puissance de l'aptitude citée (validées : « graduée »).
REF_FRACTIONS: dict[str, float] = {"boost": 1 / 3, "extend": 1 / 2, "full": 1.0}
#: Décor de faction en plus : moitié de ce que vaut le décor (validé).
TERRAIN_FRACTION = 0.5
#: Moteurs de rotation (validés « moins sévère ») : mot-clé d'aptitude (minuscules) → (facteur, note).
ROTATION_FACTORS: dict[str, tuple[float, str]] = {
    "delusion": (5 / 6, "Délire : cru seulement aux tours où le jet de Délire le permet (×5/6)"),
    "cycle": (1 / 3, "Cycle : mûr seulement certains rounds de la séquence (×1/3)"),
}
#: Sale Tour Kruleboyz : jet de réussite dont le seuil monte avec le nombre de tours joués (table coupée par
#: Wahapedia, BT non scanné) — probabilité moyenne validée par l'utilisateur.
DIRTY_TRICK_P = 2 / 3

_Q = "['‘’]"
_QUOTED = re.compile(rf"(?<![A-Za-z]){_Q}([^'‘’\n]{{3,60}}?){_Q}")
#: Nom cité suivi de son genre (« 'Eat 'Em Alive' ability ») : tolère une apostrophe dans le nom.
_QUOTED_ABILITY = re.compile(
    rf"(?<![A-Za-z]){_Q}([^\n]{{3,60}}?){_Q} (?:abilit(?:y|ies)|command|effect|DELUSION|spell|prayer)\b"
)

#: Règles-cadres : définissent un mécanisme dont la valeur est dans les aptitudes qu'il sélectionne.
_FRAMEWORK = re.compile(
    r"\bcan transport (?:up to )?\d|\bThis unit is either full or empty\b|"
    r"\bThe effect of an? [A-Z][A-Z' ]+ ability is only applied if\b|\bYou perform a blood rite each time\b|"
    r"\bimmediately loses the [A-Z]+ keyword when\b|\byou believe the DELUSION you picked\b|"
    r"\bpick the starting face of the Bad Moon\b|\broll a dice to determine which CYCLE ability is ripe\b|"
    r"\bcan be used (?:for the rest of the battle|this battle round),? but the others? (?:two )?cannot\b|"
    r"\bThat battlefield edge is leeward\b|\bSet up this Regiment of Renown's\b|"
    r"\bYou must use this ability to set up\b|\bis automatically removed from play\b|"
    r"\bspend the number of blood tithe points required to unlock\b"
)
#: Jeton posé par une aptitude active (« Place this unit's Grype next to the target »).
_TOKEN = re.compile(
    r"\b[Pp]lace (?:this unit's|1 of this unit's|1 of those|an?|1|each) [^.]*?\bnext to\b|"
    r"\b(?:is a token|are tokens|accomplice tokens)\b"
)

#: (libellé, motif qui DONNE le statut, motif des aptitudes qui le LISENT).
STATUSES: tuple[tuple[str, str, str], ...] = (
    ("sous ordres", r"\b(?:is|are) under orders\b", r"\bunder orders\b"),
    ("unifié", r"\b(?:is|are) unified\b", r"\bunified\b"),
    ("oint", r"\bis anointed\b", r"\banointed\b"),
    ("Vocation au Chaos", r"Pledge to Chaos keyword", r"\bPLEDGED TO\b"),
    ("POWER OF THE WAAAGH!", r"\bPOWER OF THE WAAAGH! keyword\b", r"\bPOWER OF THE WAAAGH\b"),
    ("proie", r"\b(?:becomes|is) the quarry\b|\bto be (?:this unit's |the )quarry\b", r"\bquarry\b"),
    ("marque", r"\bis the mark\b", r"\bmark\b"),
    ("objectif de quête", r"\bconsidered by you to be questmarked\b", r"\bquestmarked\b"),
    ("amphithéâtre", r"\bconsidered by you to be the amphitheatre\b", r"\bamphitheatre\b"),
    ("lien d'âme", r"\bsoul-bonded charge\b", r"\bsoul-bonded\b"),
    ("Feastmaster", r"\bto be the Feastmaster\b", r"\bFeastmaster\b"),
    ("pollué", r"\bconsidered by you to be POLLUTED\b", r"\bPOLLUTED\b"),
    ("jumeaux", r"\bhave the TWIN keyword\b", r"\bTWIN\b"),
    ("plein", r"\b(?:it becomes|this unit is) full\b", r"\bis full\b"),
    (
        "végétation envahissante",
        r"\bhave a friendly overgrown token\b|\bcreeping overgrowth \(referenced by other abilities\) extends\b",
        r"\bcreeping overgrowth\b|\bovergrown\b",
    ),
    ("bord sous le vent", r"\bleeward battlefield edge\b", r"\bleeward\b"),
    (
        "rune",
        r"\bDepict a rune\b|\bto your library\b|\bReplace 1 instance of a rune\b|\badditional instance of\b",
        r"\b[Rr]une\b",
    ),
)
_COND_BEFORE = re.compile(r"\b(?:[Ii]f|[Ww]hile|[Uu]nless|[Ee]ach time)\b[^.,:]*$")

_BOOST = re.compile(
    r"\b[Aa]dd (?:1|D3|\d) to (?:each dice roll|the roll|rolls|the number|[\w' -]{0,40}?\brolls?)\b|"
    r"\b[Ii]ncrease the range of\b|\bwithin \d+\" of this unit instead of within \d+\"|"
    r"\b[Ss]ubtract 1 from the number of [\w ]+ points\b|\badd 1 to the amount of\b"
)
_FULL = re.compile(
    r"\bas if (?:it|they|that ability) (?:were|was|had been) (?:active|unlocked|on their warscrolls)\b|"
    r"\b(?:apply|applies) to (?:this unit|the target|that unit) as if\b|\bthe effects of (?:the )?['‘’][^'‘’]+['‘’]"
    r" ability apply to\b|\bNo [\w-]+ points are spent\b|\baffected by all\b|"
    r"\bcounts as (?:a )?(?:friendly )?[\w ]+ for the purposes? of\b|\btreated as having 1 additional instance\b|"
    r"\bYou believe the\b|\bIts effects apply in addition to\b|\bare the targets of that ability instead\b|"
    r"\bgains? the ['‘’][^'‘’]+['‘’] ability\b"
)
_EXTEND = re.compile(
    r"\beven if\b|\binstead of (?:1|a|an|only|within|those|the)\b|\bcan (?:also )?pick\b|\bcan be picked\b|"
    r"\bcan use 2\b|\bMore than 1 effect\b|\bimmediately use\b|\bdoes not have to\b|\banywhere on the battlefield\b|"
    r"\bcan immediately roll\b|\bon a [\w ]+ roll of \d\+ instead of\b|\bpick 2 targets instead\b|"
    r"\bis ripe for the rest of the battle round instead\b|\bmoves to the next face\b|\bstays in its current\b|"
    r"\bThat blessing is now active\b|\bas if it were a unit\b|\breplace ['‘’]|\bpick a new face\b"
)
#: Groupe d'aptitudes cité par mot-clé (« CYCLE ability », « WARPSHATTER THROES abilities », « DELUSION »).
_KW_GROUP = re.compile(
    r"\b((?:[A-Z][A-Z'-]+ ){0,3}[A-Z][A-Z'-]{2,}) (?:abilit(?:y|ies)|DELUSION)\b|\b(DELUSION|ASTERISM)\b"
)
#: Jet propre à la faction (« shield bash rolls », « legion roll », « dirty trick rolls ») → aptitudes qui le font.
_ROLL_WORD = re.compile(r"\b((?:[a-z]+ ){0,2}[a-z]+) rolls? (?:you make|for|made|when)\b|\bto ([a-z]+ [a-z]+) rolls\b")
_ROLL_STOPWORDS = {"to", "the", "a", "add", "each", "for", "of", "and", "1", "any"}
_GENERIC_ROLLS = {"hit", "wound", "save", "charge", "run", "casting", "chanting", "unbinding", "ward", "dice"}

_ENHANCEMENT = re.compile(
    r"\b[Gg]ive (?:the target|each target|that Hero|that HERO|each HERO|the HERO)s? 1 "
    r"(artefact of power|heroic trait|enhancement)\b(.*)"
)
_TABLE_NAMES = re.compile(rf"{_Q}([^'‘’]+?){_Q}|\bfrom the ([A-Z][\w!' ]+?) (?:heroic traits|artefacts)")
_TERRAIN = re.compile(
    r"\b[Ss]et up (?:up to \d+ |\d+ |an? |1 )(?:additional |replacement )?(?:friendly )?"
    r"([A-Z][\w'-]+?(?:(?:es|s)? (?:of (?:the )?)?[A-Z][\w'-]+?){0,3})(?:e?s)?\b"
    r"(?= on| wholly| within| more|,|\.| \(| next)"
)
_SUMMON_FREE = re.compile(r"\bset up one of the following MANIFESTATIONS\b", re.I)


def engine_factors(raw: RawAbility) -> tuple[float, str, float, str]:
    """(facteur de puissance, note, facteur de déclenchement, note) des moteurs de rotation et Sales Tours."""
    kws = {k.strip().lower() for k in raw.keywords.split(",") if k.strip()}
    factor, note = 1.0, ""
    for kw, (f, n) in ROTATION_FACTORS.items():
        if kw in kws:
            factor, note = f, n
    act, act_note = 1.0, ""
    if "dirty trick" in kws:
        act, act_note = DIRTY_TRICK_P, f"jet de Sale Tour à réussir (P moyenne {DIRTY_TRICK_P:.0%})"
    return factor, note, act, act_note


def _granted(pattern: str, text: str) -> bool:
    """Le statut est DONNÉ (et pas seulement lu : « While this unit is under orders, … »)."""
    for m in re.finditer(pattern, text):
        if not _COND_BEFORE.search(text[max(0, m.start() - 60) : m.start()]):
            return True
    return False


def _count(declare: str) -> int:
    ups = re.findall(r"\bup to (\d|D3)\b", declare)
    if not ups:
        return 1
    return max(1, sum(2 if u == "D3" else int(u) for u in ups))


#: Renvois sans nom cité : tournure → cible (Faces de la Lune, jet de Délire, table de l'Œil des Dieux).
_REF_ALIASES: tuple[tuple[str, str], ...] = (
    (r"\bface of the Bad Moon\b|\bfaces of the Bad Moon\b", "nom:UNDER THE LIGHT OF THE BAD MOON"),
    (r"\bdelusion roll\b", "mc:DELUSION"),
    (r"\bEye of the Gods (?:table|passive)\b", "nom:EYE OF THE GODS"),
)


def _ref_targets(text: str) -> list[str]:
    aliases = [t for rx, t in _REF_ALIASES if re.search(rx, text)]
    if aliases:
        return aliases
    names = []
    for c in _QUOTED_ABILITY.findall(text):
        # « 'Heavy Bomb Racks', 'Medium Bomb Racks' or 'Light Bomb Racks' ability » : une liste, pas un nom
        names += _QUOTED.findall(f"'{c}'") if re.search(r"['‘’],? (?:or |and )?['‘’]|['‘’], ", c) else [c]
    names = [n.strip() for n in names] or [
        n.strip() for n in _QUOTED.findall(text) if not n.strip().lower().startswith("s ")
    ]
    if names:
        return [f"nom:{n}" for n in dict.fromkeys(names)]
    out = []
    for m in _KW_GROUP.finditer(text):
        kw = (m.group(1) or m.group(2)).strip()
        if kw not in ("SPELL", "UNBIND", "MOVE", "CHARGE", "FIGHT", "SHOOT", "RAMPAGE", "ATTACK", "CORE"):
            out.append(f"mc:{kw}")
    for m in _ROLL_WORD.finditer(text):
        words = (m.group(1) or m.group(2) or "").split()
        while words and words[0] in _ROLL_STOPWORDS:
            words = words[1:]
        word = " ".join(words)
        if word and words[-1] not in _GENERIC_ROLLS | _ROLL_STOPWORDS:
            out.append(f"jet:{word}")
    return list(dict.fromkeys(out))


def reference_effects(raw: RawAbility) -> list[Effect]:
    """Effets « résolus ailleurs » d'une aptitude sans autre effet reconnu (liste vide si rien ne s'applique)."""
    text = f"{raw.declare}\n{raw.effect}".strip()
    if _FRAMEWORK.search(text):
        return [Effect("warscroll_rule", "", 0.0, "", "friendly", "règle-cadre")]
    spell = raw.source_kind == "manifestation" or raw.cost_type.lower() == "spell"
    if (spell and raw.name.upper().startswith("SUMMON ")) or _SUMMON_FREE.search(text):
        return [Effect("summon", "", 0.0, "", "friendly", "manifestation posée")]
    m = _ENHANCEMENT.search(text)
    if m:
        kind = {"artefact of power": "artefact", "heroic trait": "heroic_trait"}.get(m.group(1), "enhancement")
        tables = [a or b for a, b in _TABLE_NAMES.findall(m.group(2))]
        return [Effect("free_enhancement", kind, 0.0, str(_count(raw.declare)), "friendly", "|".join(tables))]
    for label, give, _reader in STATUSES:
        if _granted(give, text):
            return [Effect("status_grant", "", 0.0, "", "friendly", label)]
    m = _TERRAIN.search(raw.effect)
    if m and "MANIFESTATION" not in m.group(1):
        return [Effect("terrain_setup", "", 0.0, "", "friendly", m.group(1))]
    if _TOKEN.search(text):
        return [Effect("warscroll_rule", "", 0.0, "", "friendly", "jeton posé")]
    targets = _ref_targets(raw.effect) or _ref_targets(text) or _ref_targets(raw.condition)
    if not targets:
        return []
    for how, rx in (("full", _FULL), ("boost", _BOOST), ("extend", _EXTEND)):
        if rx.search(text):
            return [Effect("ability_ref", how, 0.0, "", "friendly", "|".join(targets))]
    return []
