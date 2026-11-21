"""Effets : regex des blessures mortelles, ward, soin, retour de figurines, mouvement, et règles qualitatives."""

from __future__ import annotations

import re

_MORTAL_RE = re.compile(
    r"[Ii]nflict (\d+|\d?D[36](?:\+[\dX])?|an amount of|a number of|that many|X)?\s*(?:mortal )?damage\b(?! point)")
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
     r"can still use CHARGE|can use CHARGE abilities[^.]*(?:run|retreat)|can still charge|"
     r"can use (?:RUN|RETREAT) abilities and still use (?:SHOOT and/or )?CHARGE",
     "run_and_charge", ""),
    (r"can (?:still )?use (?:'?SHOOT(?: and/or CHARGE)?'? abilities|shoot)[^.]*(?:[Rr]un|RUN|[Rr]etreat|RETREAT)|"
     r"can still use SHOOT|can use (?:RUN|RETREAT) abilities and still use SHOOT",
     "run_and_shoot", ""),
    (r"[Rr]emove (?:this|that|the target|it)[^.]*?from the battlefield[^.]*?set (?:it|them|that unit|this unit) up again|"
     r"[Ss]et (?:it|this unit|that unit|them) up again|set up again|set up it again", "redeploy", ""),
    # Vrai double combat (« can use 2 FIGHT abilities this phase », Gunnar Brand, Battle-fury…), à ne pas
    # confondre avec `extra_fight` ci-dessous (« can be picked to use a FIGHT ability immediately after » :
    # enchaînement d'activations) ni avec « pick 2 units instead of 1 » (Lightning Reactions).
    (r"(?i)\bcan use (?:2|two) FIGHT abilities", "fight_twice", ""),
    (r"can (?:immediately )?use (?:a|another) ?'?FIGHT'? abilit|fight (?:again|immediately|a second time)|"
     r"can be picked to use a FIGHT ability|(?:immediately )?resolve (?:combat|shooting) attacks|"
     r"immediately (?:make|resolve) [^.]*attacks|\bResolve combat attacks for this unit against", "extra_fight", ""),
    (r"can use (?:the )?'?(?:Normal Move|Run|Retreat)'? ability|can use a (?:RUN|MOVE) ability|"
     r"as if it (?:were|was) your movement phase|use a (?:RETREAT|RUN|MOVE) ability|"
     r"can (?:immediately )?use a CHARGE ability as if it were|"   # v28 : charge hors phase
     r"can use (?:a )?CHARGE abilit(?:y|ies) even (?:if|though) (?:it is|they are) in combat|"   # v29
     r"can use the 'Charge' ability even if it is not your charge phase", "extra_move", ""),
    (r"[Ss]et up (?:that|the target|this|the) unit (?:on the battlefield )?(?:again )?wholly within|"
     r"[Ss]et up (?:each target|the targets?|the substitute) wholly within|"   # v29
     r"[Ss]et (?:them|it|the targets?) up in reserve|"
     r"[Ss]et (?:up )?(?:the targets?|those units|that unit|this unit|it|them) (?:up )?on the battlefield|"
     r"[Ss]et up [^.]*?\bin reserve\b|in reserve[^.]*?can be set up", "deep_strike", ""),
    (r"(?i)ignore (?:all )?(?:negative )?(?:and positive )?modifiers to (?:save|ward)|ignore the first damage point|"
     r"ignore the Rend characteristic|"
     r"ignore (?:the first )?\d+ damage points?", "damage_ignore", ""),
    (r"weapon abilities [^.]*?have no effect|cannot (?:use|benefit from) [^.]*?weapon abilities|"
     r"weapon ability has no effect|cannot be affected by weapon abilities", "no_weapon_abilities", ""),
    # v21 : « ignore positive modifiers to save rolls for the target » (anti-buff ennemi)
    (r"(?:the target's|target's) (?:melee )?weapons have the Companion weapon ability|"   # v29
     r"[Ii]gnore positive modifiers to (?:save|ward|hit|wound) rolls for (?:the target|that unit|those units|"
     r"enemy|each target)", "no_buff", ""),
    (r"(?i)\b(?:gain|receive|generate) (?:\d+|d3|an?|one|1 extra) (?:extra |additional )?"
     r"(?:fate points?|chords?|rage dice|momentum points?|tokens?|ritual points?|blood tithe points?|"
     r"[a-z]+ points?)", "resource", ""),
    (r"twice per (?:turn|phase)|additional target|does not count towards|be a second target|"
     r"pick (?:2|two) [^.]*? instead of (?:1|one)\b", "extra_use", ""),
    (r"While this unit has \d+ or more damage points\b", "battle_damaged", ""),   # v27 : toute forme
    (r"cannot score critical hits", "no_crit", ""),
    (r"[Ww]ard rolls cannot be made for (?!(?:that|those|the) damage point)", "no_ward", ""),
    (r"(?:automatically|immediately) (?:destroyed|slain)|\bis slain\b(?=[^.]*target)|"
     r"\bmodels? in the target unit (?:is|are) slain", "slay", ""),
    (r"[Dd]ouble the (?:Attacks|Damage|Rend|Move)|characteristic of (?:[^.]*?(?:is|of) )?(?:\d?D)?\d+ instead|"
     r"[Ss]et the (?:Attacks|Damage|Rend|Move|Health|Control) characteristic of [^.]*? to (?:\d?D\d(?:\+\d)?|\d+)|"
     r"has a (?:Health|Move|Save|Control) characteristic of \d+", "stat_set", ""),
    (r"the attack fails|attack sequence ends", "negate_attack", ""),
    (r"(?:has|gains?) the [A-Z][A-Z -]+ keyword", "keyword_gain", ""),
    # v28 : niveau de lanceur gagné (« This unit has PRIEST (1) ») ; « as if it had WIZARD (1) » ne donne que
    # l'usage cité (dissipation, sort unique), lu par ses propres règles
    (r"\b(?:has|have|gains?) (?:WIZARD|PRIEST) \(\d\)", "keyword_gain", "caster"),
    (r"can use (?:a|another) ?'?SHOOT'? abilit|shoot (?:again|a second time)|"
     r"can (?:immediately )?use (?:a|the) '?(?:SHOOT|Shoot)'? ability as if", "extra_shoot", ""),
    # v21 : jet remplacé par une valeur fixe (« use a value of 6 for the roll that cannot be modified »)
    (r"(?:you )?can use a value of \d+ (?:for (?:the|it|that)|instead)|"
     r"use it as the roll|replaced with the roll on the destiny dice|"   # v25 : dés du destin
     r"(?<!If )(?<!if )the (?:casting|chanting) roll is \d+\b|"   # v28 : « the casting roll is 9 »
     r"roll for that spell to a value of \d+", "fixed_roll", ""),   # v29 : « change the casting roll … to a value of 12 »
    # v21 : relances de ralliement supplémentaires (« make 3 additional rally rolls of D6 »)
    (r"(?:make|makes?) (?:\d+|D\d|an?) additional rally rolls?|additional rally roll", "rally", ""),
    # v21 : sort hors phase des héros (« can use a SPELL ability as if it were your hero phase »)
    (r"can use (?:a|another) (?:non-SUMMON )?(?:SPELL|PRAYER) ability as if|"
     r"can immediately use a (?:non-SUMMON )?SPELL ability", "extra_use", ""),   # v29 : sort immédiat
    (r"Shoot in Combat", "shoot_in_combat", ""),
    # --- v27 (revue « a-revoir » par faction, LRL) ---
    # « The Rend characteristic of your general's melee weapons is 2 », « this unit's Save characteristic is 3+ »
    (r"(?:Attacks|Damage|Rend|Save|Health|Control|Move) characteristic (?:of [^.]*? )?is (?:\d?D\d|\d+\+?)",
     "stat_set", ""),
    # v29, validés par l'utilisateur (2026-11-21) : choix de profil d'arme = règle de profil (0, la valeur est
    # dans le châssis), manipulation des cartes de tactique 1,5, portée de cohésion 0,25
    (r"pick either (?:the )?[^.]*? weapon (?:characteristics|profiles)|pick either of the (?:ranged |melee )?weapon "
     r"profiles", "profile_choice", ""),
    (r"draw 1 additional battle tactic|(?:top|bottom) of your battle tactic deck|return the card to your hand|"
     r"reveal 1 battle tactic card|place it face-down separately", "tactic_cards", ""),
    (r"coherency range of \d+\"", "coherency", ""),
    # v31, validé par l'utilisateur (2026-11-21) : un héros ennemi perd son artefact de pouvoir = 1,0
    (r"no longer has (?:that|any|the|its) artefacts? of power|no longer has any artefacts", "strip_enhancement", ""),
    # v30 : règles de fonctionnement sans effet propre (comme le choix de profil, validé à 0 par l'utilisateur) :
    # manifestation en plusieurs parties, jetons, héros qui monte sur / descend d'un décor de faction
    (r"MANIFESTATION is destroyed and (?:all|both) (?:of )?its parts are removed|"
     r"(?:'s|') [A-Z][\w' -]+ (?:is a token|are tokens|are [A-Z][\w -]+ tokens)|"
     r"[Pp]lace the target on this terrain feature|That unit is no longer (?:a|an|the) [A-Z]", "warscroll_rule", ""),
    (r"[Aa]dd \d+\" to the Range characteristic", "range_bonus", ""),          # validé : +6" = 1,0
    # v28 : relais de sort (« Measure the range and visibility of the next SPELL ability … from the target »)
    (r"[Mm]easure (?:the )?range and visibility (?:of (?:that|the next|the) [^.]*?SPELL|from (?:this|the target|either))",
     "range_bonus", "spell"),
    (r"[Ii]gnore (?:all )?negative (?:and positive )?modifiers", "ignore_debuff", ""),           # validé : 0,5
    (r"must target this unit", "taunt", ""),                                    # validé : 1,0
    # « that MOVE ability has no effect » : capacité ENNEMIE annulée (sur un jet, via le déclenchement)
    (r"(?:FIGHT|MOVE|CHARGE|MOVE or CHARGE) ability has no effect", "restriction", ""),
    (r"(?:command|RAMPAGE|command or RAMPAGE) ability has no effect|(?:that|the) command has no effect|"
     r"picked to use an ability, roll[^.]*\. On a \d\+, that ability has no effect", "lockout", ""),
    (r"SPELL ability has no effect", "anti_magic", ""),
    (r"that ability has no effect on (?:this|that) unit", "negate_attack", ""),
    (r"cast that spell a second time|can (?:use|issue) the '(?!Rally')[^']+' command[^.]*even if", "extra_use", ""),
    # v28 : « even if another friendly unit has used it this turn », « for a second time this phase »
    (r"even if (?:another friendly [^.]*?(?:has|have) used|that (?:command|ability) has (?:already )?been used|"
     r"a friendly unit has used)|for a second time this (?:phase|turn)|regardless of whether another friendly",
     "extra_use", ""),
    # v28 : protection contre un sort/une prière adverse, sort raté
    (r"ignore the effects? of that spell|that spell or prayer fails|the prayer fails|the spell is miscast|"
     r"[Ii]gnore the effects? of (?:enemy )?SPELL abilities|\bis banished\b",
     "anti_magic", ""),
    # v28 : tir sur un héros protégé (« ignore the effects of the 'Guarded Hero' ability »)
    (r"ignore the effects? of the 'Guarded Hero'|cannot be affected by the 'Guarded Hero'", "snipe", ""),
    # v28 : soins et retours de figurines interdits à l'ennemi
    (r"cannot be healed|cannot (?:have slain models|be) returned|[Mm]odels cannot be returned to enemy",
     "anti_heal", ""),
    # v28 : gains de ressource de faction (points, ingrédients, morceaux…) hors PC/dégâts/PV de victoire
    (r"(?i)\b(?:gains?|earn|give(?: (?:this|that|the|each) [a-z]+| it)?|add)\s+(?:\d+|d3\+3|d3|d6|an?|one|"
     r"a number of|up to \d+)\s+(?!command|damage|victory)(?:[a-z-]+ ){0,3}?(?:points?|ingredients?|morsels?|tokens?)\b",
     "resource", ""),
    (r"use the 'Rally' command even if", "rally", ""),
    (r"[Ii]gnore the effect of the Charge \(\+1 \w+\) ability", "no_buff", ""),
    (r"(?:score )?critical hits? on (?:unmodified )?hit rolls? of \d\+|(?i:Crit \((?:2 Hits|Auto-wound|Mortal)\))|"
     r"score critical hits", "crit", ""),
    (r"(?:gain|receive) (?:\d|D3|an extra|1 extra|one extra|an additional) (?:extra )?command points?|"
     r"command points? (?:is|are) (?:gained|received)|gain a command point|no command points are spent|"
     r"without spending (?:a |any )?command points?|[Nn]o command points? (?:is|are) spent|"
     r"without any command points being spent", "cp_gain", ""),
    (r"\bcan(?:not)? use (?:the )?'?(?:Unbind|Banish|UNBIND|BANISH)'?|\bunbind\b|\bbanish\b|spell is unbound",
     "anti_magic", ""),
    (r"cannot (?:use|be picked to use) (?:commands|any commands|SPELL|PRAYER|abilities)|"
     r"cannot issue commands|cannot receive commands|cannot use the '[^']+' command|"
     r"cannot use (?:RAMPAGE abilities|reactions)|can only use CORE abilities|"   # v29
     r"unless your opponent spends \d+ (?:additional|extra) command point", "lockout", ""),
    (r"cannot (?:use )?(?:CHARGE|charge|RUN|run|RETREAT|retreat|SHOOT|shoot|move|MOVE|be set up|contest)|"
     r"cannot (?:end|finish) a charge move",
     "restriction", ""),
    # « cannot be picked to be the target of this ability again » est une limite d'usage, pas un effet
    (r"cannot be (?:picked as the )?target(?! of this)|cannot be picked to be the target of (?:attacks|shooting|"
     r"combat|SPELL|PRAYER|BANISH|abilities used by enemy|abilities used by the target|enemy)|"
     r"not visible to|is not visible",
     "untargetable", ""),
    (r"\bFLY\b|can pass through (?:enemy )?(?:models|the combat ranges)|can move through (?:the combat ranges|models|terrain)",
     "fly", ""),
    # v21 (revue « a-revoir ») : retraite sans blessures mortelles
    (r"[Nn]o mortal damage is inflicted on [^.]*?(?:RETREAT|Retreat)|(?:RETREAT|Retreat) abilit[^.]*?no mortal damage",
     "free_retreat", ""),
    (r"[Hh]alve (?:the|its|their|the target's|that unit's) Move|subtract \d\" from[^.]*Move|[Hh]alve (?:run|charge) rolls", "move_debuff", ""),
    (r"[Ss]et up (?:a|an|one|\d+|up to \d+)? ?(?:new |replacement )?[^.]*?(?:unit|manifestation|ENDLESS SPELL)"
     r"[^.]*?(?:wholly within|within|on the battlefield)|[Ss]et up (?:a|an) [A-Z][^.]*?within \d+\" of the (?:caster|chanter)|"
     r"[Ss]et up a (?:single )?replacement [^.]*?more than \d+\" from (?:all )?enemy|"
     r"[Ss]et up (?:a|an|the|The) [A-Z][^.]*?within \d+\" of (?:and visible to )?the (?:caster|chanter)|"
     r"set it up wholly within \d+\" of the caster|"
     r"[Ss]et up the (?:first part of the [A-Z]|MANIFESTATION you picked)|"   # v28 : manifestations
     r"pick 1 of the (?:friendly )?MANIFESTATIONS (?:below|from the list below) that is not on the battlefield",
     "summon", ""),
    (r"control score|contest objectives|\bcontrol (?:that|the) objective|gain control|"
     r"[Yy]ou control the (?:target )?objective|cannot control the target objective", "control", ""),
    (r"(?i:Anti)-([A-Za-z -]+?) \(\+1 (\w+)\)", "anti", ""),
    # « ignore the effect of the Charge (+1 Damage) ability for … enemy units » (Anticipated Strike) :
    # c'est l'anti-charge d'un bonus ENNEMI, pas un bonus de charge pour nous (analyseur v18).
    (r"(?<!effect of the )Charge \(\+1 (?:Damage|Rend|Attacks)\)(?! weapon ability has no effect)",
     "charge_bonus", ""),
    (r"pile-in move|pile in", "pile_in", ""),
    (r"[Ss]ubtract \d+ from the number of (?:wounds|damage points)|damage points? (?:to|on) [^.]*?is reduced|"
     r"allocate[^.]*? to (?:this|that|another) unit instead", "damage_redirect", ""),
]
