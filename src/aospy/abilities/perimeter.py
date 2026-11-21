"""Périmètre d'un effet : sur quelles armes, contre quelle cible, sous quel prérequis, combien de temps.

Couche 1 (aptitude ex-nihilo) de l'architecture « aptitude ≠ châssis » : on ne chiffre PAS la
valeur de l'effet sur une unité (c'est la couche 3, rencontre aptitude × châssis, via le moteur
de combat) ; on décrit seulement ce qu'il faudra savoir pour l'y appliquer. Exemple : « +1 au
Damage des armes de mêlée de cette unité, contre HERO ou MONSTER, si elle a chargé, pour le
reste du tour » → weapon_scope=melee, target_keywords=HERO,MONSTER, requires=a chargé, duration=tour.

Règles de lecture (Wahapedia, AoS4) :

* « combat attacks » / « melee weapons » → mêlée ; « shooting attacks » / « ranged weapons » → tir ;
  « that weapon » / « the target weapon » → arme choisie ; « this unit's <Nom propre> » → arme nommée ;
* les armes Compagnon ne profitent d'un effet que si le texte dit « including … Companion » ;
* la durée est lue dans la phrase, sinon dans l'en-tête de liste qui la précède
  (« For the rest of the turn: - … »), sinon dans le reste du texte ; à défaut « permanent »
  (aptitude passive), « immédiat » (dégâts, soin, mouvement…) ou « non précisée » (en
  général la phase ou l'attaque en cours).
"""

from __future__ import annotations

import re

_CHOSEN = re.compile(r"made with that weapon|the target weapon|\bthat weapon\b|picked weapon", re.I)
_MELEE = re.compile(r"melee weapons?|combat attacks?", re.I)
_RANGED = re.compile(r"ranged weapons?|shooting attacks?", re.I)
_NAMED = re.compile(
    r"(?:this unit's|the target's|its|your general's|that unit's|the targets'|each target's|"
    r"this model's|the target unit's) "
    r"((?:[A-Z][\w'’-]*)(?: (?:and |of |the |with )?[A-Z][\w'’-]*)*)"
)
_NOT_A_WEAPON = {"Companion", "Attacks", "Damage", "Rend", "Health", "Move", "Save", "Control"}
_COMPANION_IN = re.compile(r"including[^.]*Companion", re.I)

_TARGET_KW = re.compile(
    # « If this unit is in combat with any enemy HEROES, it can use 2 FIGHT abilities » (Engine of
    # Domination) : condition sur la cible, comme « against HEROES » (analyseur v16).
    r"(?:that target|targeting|if the target is an?|against|"
    r"(?:[Ii]f|[Ww]hile) (?:this unit|it|this model) is in combat with (?:any|an?|one or more)? ?enemy) "
    # « attacks that target an enemy HERO » (Master of Assassins) : article ET « enemy » (analyseur v24)
    r"(?:an? |the )?(?:enemy )?"
    r"((?:[A-Z][A-Z'-]{2,}(?: [A-Z][A-Z'-]{2,})*)(?:,? (?:or|and) [A-Z][A-Z'-]{2,}(?: [A-Z][A-Z'-]{2,})*)*)"
)
_SINGULAR = {
    "HEROES": "HERO",
    "MONSTERS": "MONSTER",
    "WIZARDS": "WIZARD",
    "PRIESTS": "PRIEST",
    "MANIFESTATIONS": "MANIFESTATION",
    "WAR MACHINES": "WAR MACHINE",
}
_TARGET_CONDITIONS: list[tuple[str, str]] = [
    (
        r"that target an enemy unit that has (\d+) or more models|target (?:unit )?has (\d+) or more models",
        "cible ≥{n} figurines",
    ),
    (r"(?:target|enemy unit)[^.]*?contesting an objective", "cible sur objectif"),
    (r"(?:target|enemy unit)[^.]*?in combat with (?:this|that) unit", "cible au contact du porteur"),
    (
        r"\bquarry\b|\bmarked\b|\bHUNTED\b|\bprey\b|that target (?:that unit|that enemy unit|each target)\b",
        "cible désignée (proie/marquée)",
    ),
    (r"(?:target|enemy unit)[^.]*?(?:damaged|has (?:any )?damage points)", "cible blessée"),
    (r"(?:target|enemy unit)[^.]*?within \d+\" of (?:this|a) terrain", "cible près d'un décor"),
]
_CHARGED = re.compile(r"\bcharged\b", re.I)
_NEGATED = re.compile(r"\b(?:has|have|had|did)\s+not\s*$|\bnot\s*$", re.I)
_TARGET_SUBJECT = re.compile(r"\b(?:the target|that unit|that enemy|each target|target's)\b|\btarget\b", re.I)


def charge_subjects(text: str, enemy_target: bool) -> set[str]:
    """Qui doit avoir chargé, d'après le sujet de chaque « charged » du texte.

    Terminologie GW : « this unit » est toujours l'utilisatrice ; « the target » peut être amie
    ou ennemie (fixé par l'Annonce, `enemy_target`). Renvoie « nous » (l'utilisatrice ou des
    unités amies ont chargé) et/ou « ennemi » (Fateful Reverse : « if the target charged » avec
    une cible ennemie). « has not charged » est ignoré : c'est une contrainte d'action, pas
    une charge.
    """
    out: set[str] = set()
    for m in _CHARGED.finditer(text):
        pre = text[max(0, m.start() - 80) : m.start()]
        if _NEGATED.search(pre) or re.search(r"\bhaving\s*$", pre):
            continue  # « has not charged » (contrainte d'action) / « count as having charged » (conséquence)
        post = text[m.end() : m.end() + 12]
        if (
            re.search(r"\b(?:has|have)\s*$", pre)
            and not re.match(r"\s*(?:this|in the same) turn", post)
            and not re.search(r"\bif\b[^.,]*$", pre, re.I)
        ):
            continue  # « If it does so, this unit has charged. » : conséquence, pas condition
        clause = re.split(r"[.,:;(\n]|\bthen\b|\bif\b|\bwhile\b", pre)[-1]
        # le sujet est la mention la plus PROCHE de « charged » (« an enemy unit in combat with a
        # friendly GITMOB unit that has charged » : c'est l'unité amie qui a chargé)
        last = None
        for pat, who in (
            (r"\benemy\b(?! territory)", "ennemi"),
            (_TARGET_SUBJECT.pattern, "cible"),
            (r"\bfriendly\b|\bthis (?:unit|model|MANIFESTATION|HERO)\b|\byour\b", "nous"),
        ):
            for mm in re.finditer(pat, clause, re.I):
                if last is None or mm.start() >= last[0]:
                    last = (mm.start(), who)
        who = last[1] if last else "nous"
        out.add(("ennemi" if enemy_target else "nous") if who == "cible" else who)
    return out


#: Sujet d'une condition de position portant sur le porteur (« while/if this unit is … », « while each
#: model in this unit is … ») — analyseur v16 : « If », « each model », objectif qualifié (questmarked).
_SUBJ = r"(?:while|if) (?:it is|they are|this unit is|each model in this unit is|all models in this unit are)"
_REQUIRES: list[tuple[str, str]] = [
    (r"did not use a MOVE|has not (?:used a MOVE|moved)|if (?:it|they) (?:did not|has not) move", "sans mouvement"),
    # « While this unit is in combat and has not charged this turn » (Warriors of the Woods) : joue hors
    # tour de charge — combat prolongé ou tour adverse (analyseur v18).
    (r"(?:has|have|had|did) not charged", "sans charge"),
    (_SUBJ + r" contesting (?:an?|any)(?: [\w-]+)? objective", "sur objectif"),
    (_SUBJ + r" in combat", "au combat"),
    (_SUBJ + r" (?:wholly )?within (?:friendly|enemy) territory", "en territoire"),
    (r"(?:has|have) (?:\d+|any)(?: or more)? damage points?|while (?:it|this unit) is damaged", "porteur blessé"),
    (
        _SUBJ + r" (?:wholly )?within [^.:]*?\bof (?:a|any|another) (?:visible )?(?:damaged )?friendly",
        "près d'une unité amie",
    ),
    # « within the combat ranges of any damaged friendly FYRESLAYERS HEROES » ; « while this unit's
    # soul-bonded charge is within this unit's combat range » (héros lié, Questor Soulsworn)
    (
        _SUBJ + r" (?:wholly )?within the combat ranges? of [^.:]*?\bfriendly|"
        r"while this unit's [\w' -]+ is (?:wholly )?within",
        "près d'une unité amie",
    ),
]
#: Prérequis « dépense une ressource de faction » (pondéré par la couche 3, pas une condition de jeu).
SPENDS_RESOURCE = "dépense une ressource"
#: Effet proportionnel à une ressource possédée (« For each daemonic power point this unit has: +1
#: Attacks ») : la valeur dépend de l'allocation entre unités, décidée au niveau de la liste (couche 4).
#: Pondéré comme une ressource au rythme inconnu (analyseur v16).
RESOURCE_SCALED = "selon ressource allouée"
_PER_RESOURCE = re.compile(
    r"\bfor each [\w' -]{0,40}?\bpoints? (?:this unit|it|that unit|this model) has\b|"
    r"\bnumber of [\w' -]{0,40}?\bpoints? this unit has\b",
    re.I,
)
_SPEND = re.compile(r"\b[Ss]pend (?:a number of |\d+ |up to \d+ |any number of )?[\w' -]{0,40}?\bpoints?\b")
#: Protection (ou réduction) limitée à une source de dégâts : ne joue pas contre les attaques d'armes.
_DAMAGE_SOURCES: list[tuple[str, str]] = [
    (
        r"against (?:mortal )?damage(?: points)? inflicted by (?:SPELL|PRAYER|abilities used by MANIFESTATIONS?)",
        "vs sorts/manifestations",
    ),
    (r"against mortal damage\b", "vs blessures mortelles"),
]
_DURATIONS: list[tuple[str, str]] = [
    (
        r"for the rest of the battle round|until the end of the battle round|"
        r"until the start of the next battle round",
        "round",
    ),
    (r"for the rest of the battle", "bataille"),
    (r"until the start of (?:your|the) next turn", "jusqu'au prochain tour"),
    (r"for the rest of (?:the )?turn|until the end of the turn|this turn\b", "tour"),
    (r"for the rest of the phase|until the end of (?:the|that) phase|this phase\b", "phase"),
]


def _implicit_duration(scope_text: str, text: str, condition: str) -> str:
    """Durée sans formule explicite (analyseur v19, revue « duree »).

    * « action » : réaction qui modifie le jet/l'aptitude déclencheurs (dure le temps de l'action) ;
    * « bataille » : choix fait au déploiement ou au début du 1er round (serment, pari, cible
      désignée) et sans autre limite ;
    * « conditionnelle » : effet d'état (« While … ») actif tant que la condition tient ;
    * sinon « non précisée ».
    """
    if "reaction" in condition.lower() and _TRIGGER_ROLL.search(text):
        return "action"
    if _SETUP_CONDITION.search(condition):
        return "bataille"
    if re.search(r"\bWhile\b", scope_text) or re.search(r"\bWhile\b", text):
        return "conditionnelle"
    return "non précisée"


def sentence_at(text: str, pos: int) -> str:
    """Phrase (ou puce de liste) de `text` contenant la position `pos`."""
    dot = text.rfind(". ", 0, pos)
    # (sans « . » avant pos, rfind vaut -1 : ne pas sauter la 1re lettre du texte, « While » → « hile »)
    start = max(dot + 2 if dot != -1 else 0, text.rfind("\n", 0, pos) + 1)
    ends = [i for i in (text.find(". ", pos), text.find("\n", pos)) if i != -1]
    return text[start : min(ends) + 1 if ends else len(text)].strip()


def _list_header(text: str, sentence: str) -> str:
    """En-tête « … : » de la liste à puces qui contient `sentence` (durée commune aux puces)."""
    i = text.find(sentence)
    if i <= 0 or not sentence.startswith("-"):
        return ""
    head = text.rfind(":", 0, i)
    if head == -1:
        return ""
    dot = text.rfind(". ", 0, head)
    return text[max(text.rfind("\n", 0, head) + 1, dot + 2 if dot != -1 else 0) : head + 1]


#: Effets ponctuels par nature : sans formule de durée, ils sont « immédiats ».
INSTANT_KINDS = {
    "mortal_damage",
    "heal",
    "return_models",
    "move",
    "summon",
    "redeploy",
    "deep_strike",
    "extra_fight",
    "fight_twice",
    "extra_shoot",
    "extra_move",
    "pile_in",
    "slay",
    "cp_gain",
    "resource",
    "rally",
    "fixed_roll",
}


#: Réaction qui modifie le jet ou l'aptitude déclencheurs (« add 1 to the casting roll for that
#: spell », « attacks made as part of that FIGHT ability ») : dure le temps de cette action.
_TRIGGER_ROLL = re.compile(
    r"\bthat (?:spell|prayer|roll|ability|[A-Z]+ ability)\b|\bthe (?:casting|chanting|unbinding|charge|run) roll\b|"
    r"\b(?:casting|chanting|unbinding|charge|run) roll for that\b|\bas part of that\b|\bthat (?:casting|chanting|"
    r"unbinding|charge|run) roll\b",
    re.I,
)
#: Choix fait une fois pour toutes avant la bataille (serment, pari, cible désignée au déploiement).
_SETUP_CONDITION = re.compile(r"deployment phase|start of the first battle round", re.I)


def perimeter_of(
    sentence: str,
    text: str,
    passive: bool,
    offensive: bool,
    kind: str = "",
    enemy_target: bool = False,
    condition: str = "",
) -> dict:
    """Champs de périmètre (`Effect.weapon_scope` … `Effect.duration`) pour un effet."""
    out: dict = {}
    if offensive or _MELEE.search(sentence) or _RANGED.search(sentence):
        named = next(
            (
                m.group(1)
                for m in _NAMED.finditer(sentence)
                if m.group(1).split()[0] not in _NOT_A_WEAPON and not re.match(r"(?:melee|ranged)", m.group(1), re.I)
            ),
            "",
        )
        if _CHOSEN.search(sentence):
            out["weapon_scope"] = "chosen"
        elif _MELEE.search(sentence) and not _RANGED.search(sentence):
            out["weapon_scope"] = "melee"
        elif _RANGED.search(sentence) and not _MELEE.search(sentence):
            out["weapon_scope"] = "ranged"
        elif named:
            out["weapon_scope"], out["weapon_name"] = "named", named
        else:
            out["weapon_scope"] = "all"
        out["includes_companion"] = bool(_COMPANION_IN.search(sentence))

    kws = [
        _SINGULAR.get(k.strip(), k.strip())
        for m in _TARGET_KW.finditer(sentence)
        for k in re.split(r",? (?:or|and) |, ", m.group(1))
    ]
    if kws:
        out["target_keywords"] = ",".join(dict.fromkeys(kws))

    conds = []
    for pat, label in _TARGET_CONDITIONS:
        m = re.search(pat, sentence, re.I)
        if m:
            n = next((g for g in m.groups() if g), "") if m.groups() else ""
            conds.append(label.format(n=n))
    source = next((label for pat, label in _DAMAGE_SOURCES if re.search(pat, sentence, re.I)), "")
    if source:
        conds.append(source)
    if conds:
        out["target_condition"] = " | ".join(conds)

    who = charge_subjects(sentence, enemy_target)
    reqs = (["a chargé"] if "nous" in who else []) + (["charge ennemie"] if "ennemi" in who else [])
    # prérequis lus aussi dans l'en-tête de liste (« While this unit is within … of a friendly X: - … »)
    req_text = f"{_list_header(text, sentence)} {sentence}"
    reqs += [label for pat, label in _REQUIRES if re.search(pat, req_text, re.I)]
    if _SPEND.search(text) and not re.search(r"blood tithe", text, re.I):
        # coût en ressource de faction (points de discipline, d'oath…) ; la Dîme de Sang a son propre
        # calcul de disponibilité (`pipeline.RESOURCE_RATES` → `available_round`).
        reqs.append(SPENDS_RESOURCE)
    if _PER_RESOURCE.search(req_text):
        reqs.append(RESOURCE_SCALED)
    if reqs:
        out["requires"] = " | ".join(reqs)

    scope_text = f"{_list_header(text, sentence)} {sentence}"
    out["duration"] = next(
        (label for pat, label in _DURATIONS if re.search(pat, scope_text, re.I)),
        next(
            (label for pat, label in _DURATIONS if re.search(pat, text, re.I)),
            "permanent"
            if passive
            else "immédiat"
            if kind in INSTANT_KINDS
            else _implicit_duration(scope_text, text, condition),
        ),
    )
    return out
