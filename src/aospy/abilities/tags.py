"""Tags d'utilité (kebab-case, français) dérivés de l'extraction et du score.

Les tags sont le point d'entrée des analyses de niveau supérieur : chercher les
aptitudes `blessures-mortelles` + `fiable`, les `bulle-12` qui donnent du
`buff-offensif`, etc. Le vocabulaire complet est `ALL_TAGS` (documenté dans
`aospy ability tags`) ; un test garantit qu'aucun tag hors vocabulaire n'est émis.
"""

from __future__ import annotations

from .models import Extraction, RawAbility, Score

#: tag → description courte (affichée par la CLI).
ALL_TAGS: dict[str, str] = {
    # effet
    "degats": "inflige ou augmente des dégâts",
    "blessures-mortelles": "inflige des blessures mortelles",
    "buff-offensif": "améliore touche/blessure/perfo/attaques/dégâts amis",
    "buff-defensif": "améliore sauvegarde/protection/PV amis ou gêne les attaques ennemies",
    "protection": "accorde une protection (ward) ou rend inciblable",
    "soin": "soigne des points de dégâts",
    "resurrection": "ramène des figurines tuées",
    "mobilite": "mouvement supplémentaire, vol, course + charge",
    "teleportation": "retire et replace une unité",
    "charge": "aide à charger (jet, course + charge, bonus de charge)",
    "frappe-en-premier": "accorde Frappe en premier",
    "frappe-en-dernier": "impose Frappe en dernier à l'ennemi",
    "combat-supplementaire": "combat ou tir supplémentaire",
    "tir": "concerne le tir",
    "controle": "score de contrôle / objectifs",
    "debuff": "affaiblit l'ennemi",
    "restriction": "empêche l'ennemi d'agir (charge, ordres, sorts…)",
    "magie": "lancement, dissipation, sorts",
    "priere": "prières / psalmodie",
    "commandement": "génère ou économise des PC",
    "invocation": "met en jeu une unité ou une manifestation",
    "critique": "modifie les critiques",
    "relance": "accorde une relance",
    "anti-cible": "bonus contre un mot-clé (Anti-X)",
    "anti-tir": "protection limitée aux attaques de tir ennemies (concept de liste anti-tir)",
    "anti-melee": "protection limitée aux attaques de mêlée ennemies",
    "anti-deathstar": "neutralise l'offensive d'une unité ennemie (Death-Star : unité surboostée)",
    "coordination": "exige que le porteur et une unité amie restent au contact",
    "marquage": "désigne une cible ennemie : toute attaque amie qui la vise est boostée",
    "dissuasion": "contraint surtout les choix adverses (Frappe en dernier, interdiction d'agir) sans servir de plan",
    "manifestation": "portée par une manifestation qu'il faut d'abord invoquer",
    "ressource-faction": "génère une ressource propre à la faction (points, dés, accords…)",
    "profil-degrade": "profil dégradé par les dégâts subis (Battle Damaged)",
    # portée / interaction
    "soi-meme": "ne profite qu'à l'unité porteuse",
    "une-unite-amie": "profite à une autre unité amie",
    "armee": "profite à toute l'armée",
    "une-cible-ennemie": "vise une unité ennemie",
    "aura-ennemie": "touche plusieurs unités ennemies",
    "bulle-courte": "bulle amie ≤ 6\"",
    "bulle-9": "bulle amie de 7 à 11\"",
    "bulle-12": "bulle amie de 12 à 17\"",
    "bulle-18": "bulle amie ≥ 18\"",
    # fiabilité / usage
    "fiable": "déclenchement automatique et effet fixe",
    "aleatoire": "déclenchement < 70 % ou effet très variable",
    "une-fois-par-bataille": "utilisable une fois par bataille",
    "passif": "toujours actif",
    "reaction": "réaction à un déclencheur",
    "deploiement": "joue au déploiement",
    "cout-pc": "coûte des points de commandement",
    "requiert-charge": "exige d'avoir chargé",
    "requiert-objectif": "exige une position (objectif, territoire, décor)",
    "depend-effectif": "dépend du nombre de figurines",
    "tardive": "disponible seulement à partir du round 3 (ressource de faction)",
    # verdict
    "plan": "verdict : on construit autour",
    "correct": "verdict : fiable et facile mais d'effet moyen",
    "pari": "verdict : forte mais à jet de déclenchement aléatoire",
    "bonus": "verdict : forte et gratuite mais tardive ou situationnelle, jamais un plan",
    "anecdotique": "verdict : à oublier",
    "a-revoir": "aucun effet reconnu, à revoir",
}

_OFFENSIVE = {"hit", "wound", "rend", "attacks", "damage"}


def tags_for(raw: RawAbility, ex: Extraction, sc: Score) -> list[str]:
    t: set[str] = {sc.verdict}
    kinds = {e.kind for e in ex.effects}
    for e in ex.effects:
        if e.kind == "stat_mod":
            if e.side == "friendly" and e.stat in _OFFENSIVE and e.value > 0:
                t |= {"buff-offensif", "degats"}
            elif e.side == "friendly" and e.stat in ("save", "ward", "health") and e.value > 0:
                t.add("buff-defensif")
            elif e.side == "enemy" and e.detail == "defensif":
                t.add("buff-defensif")
                if e.weapon_scope == "ranged":
                    t.add("anti-tir")
                elif e.weapon_scope == "melee":
                    t.add("anti-melee")
            elif e.side == "enemy" and e.detail == "debuff":
                t.add("debuff")
            if e.stat in ("charge",) and e.value > 0:
                t.add("charge")
            if e.stat in ("move", "run") and e.value > 0 and e.side == "friendly":
                t.add("mobilite")
            if e.stat == "control":
                t.add("controle")
            if e.stat in ("cast", "unbind", "banish", "power_level"):
                t.add("magie")
            if e.stat == "chant":
                t.add("priere")
            if e.side == "enemy" and e.stat in _OFFENSIVE and e.value < 0:
                t.add("debuff")
        elif e.kind == "mortal_damage" and e.side == "enemy":
            t |= {"blessures-mortelles", "degats"}
        elif e.kind == "ward":
            t |= {"protection", "buff-defensif"}
        elif e.kind == "heal":
            t.add("soin")
        elif e.kind == "return_models":
            t.add("resurrection")
        elif e.kind == "move" and e.side == "friendly":
            t.add("mobilite")
        elif e.kind == "move" and e.side == "enemy":
            t.add("debuff")
    mapping = {
        "strike_first": "frappe-en-premier", "redeploy": "teleportation", "run_and_charge": "charge",
        "run_and_shoot": "tir", "free_retreat": "mobilite", "fixed_roll": "relance", "rally": "resurrection", "no_buff": "debuff", "extra_fight": "combat-supplementaire", "fight_twice": "combat-supplementaire", "extra_shoot": "combat-supplementaire",
        "shoot_in_combat": "tir", "crit": "critique", "reroll": "relance", "cp_gain": "commandement",
        "anti_magic": "magie", "summon": "invocation", "control": "controle", "anti": "anti-cible",
        "charge_bonus": "charge", "fly": "mobilite", "extra_move": "mobilite",
        "deep_strike": "teleportation", "no_ward": "debuff", "slay": "degats", "negate_attack": "buff-defensif",
        "damage_ignore": "buff-defensif", "no_weapon_abilities": "debuff", "resource": "ressource-faction",
        "battle_damaged": "profil-degrade", "range_bonus": "tir", "taunt": "debuff",
        "snipe": "tir", "anti_heal": "debuff",   # v28
    }
    for k, tag in mapping.items():
        if k in kinds:
            t.add(tag)
    if kinds & {"run_and_charge", "redeploy", "deep_strike"}:
        t.add("mobilite")
    if "extra_shoot" in kinds:
        t.add("tir")
    for e in ex.effects:
        if e.kind == "strike_last" and e.side == "enemy":
            t |= {"frappe-en-dernier", "debuff"}
        if e.kind in ("restriction", "lockout", "move_debuff") and e.side == "enemy":
            t |= {"restriction", "debuff"}
        if e.kind == "untargetable" and e.side == "friendly":
            t.add("protection")
        if e.kind == "dice_count":   # v28 : dé en plus (ami) / en moins (ennemi)
            if e.side == "enemy":
                t.add("debuff")
            elif e.value > 0:
                t.add("charge" if e.stat == "charge" else "magie" if e.stat in ("cast", "unbind", "banish")
                      else "mobilite" if e.stat == "run" else "relance")
    if raw.wahapedia_type == "Shooting" or raw.phase == "Shooting Phase":
        t.add("tir")
    if raw.cost_type == "Spell" or raw.source_kind in ("spell", "manifestation"):
        t.add("magie")
    if raw.cost_type == "Prayer" or raw.source_kind == "prayer":
        t.add("priere")

    scope_tags = {"self": "soi-meme", "one_friendly": "une-unite-amie", "army": "armee",
                  "one_enemy": "une-cible-ennemie", "enemy_aura": "aura-ennemie",
                  "all_enemies": "aura-ennemie"}
    if ex.scope in scope_tags:
        t.add(scope_tags[ex.scope])
    if ex.scope == "friendly_aura" and ex.range_inches:
        r = ex.range_inches
        t.add("bulle-courte" if r <= 6 else "bulle-9" if r < 12 else "bulle-12" if r < 18 else "bulle-18")

    if ex.activation_prob >= 0.999 and ex.variance == "fixe":
        t.add("fiable")
    if ex.activation_prob < 0.7 or (ex.variance == "binomial"):
        t.add("aleatoire")
    if ex.frequency.startswith("once_per_battle"):
        t.add("une-fois-par-bataille")
    if ex.frequency == "passive":
        t.add("passif")
    if raw.is_reaction:
        t.add("reaction")
    if ex.turn == "deployment":
        t.add("deploiement")
    if raw.cost_type == "Command":
        t.add("cout-pc")
    if "doit avoir chargé" in ex.conditions:
        t.add("requiert-charge")
    if "position (objectif/territoire/décor)" in ex.conditions:
        t.add("requiert-objectif")
    if ex.scales_with_size or "effectif minimal" in ex.conditions:
        t.add("depend-effectif")
    offense = [e for e in ex.effects if e.side == "enemy" and (
        e.kind in ("no_crit", "strike_last", "no_weapon_abilities")
        or (e.kind == "stat_mod" and e.detail == "defensif"))]
    if any(e.detail == "marquage" for e in ex.effects):
        t |= {"marquage", "buff-offensif", "degats"}
    if ex.scope == "one_enemy" and len(offense) >= 2:
        t.add("anti-deathstar")
    if "no_crit" in kinds:
        t.add("debuff")
    if any(e.side == "enemy" and e.kind in ("strike_last", "restriction") for e in ex.effects):
        t.add("dissuasion")
    if any(c.startswith("manifestation") for c in ex.conditions):
        t.add("manifestation")
    if any(c.startswith("coordination") for c in ex.conditions):
        t.add("coordination")
    if ex.available_round and ex.available_round >= 3:
        t.add("tardive")
    if ex.target_keywords:
        t.add("anti-cible")
    return sorted(t)
