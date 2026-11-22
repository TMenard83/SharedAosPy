"""Notation des quatre axes et verdict plan / correct / pari / bonus / anecdotique.

Toutes les notes vont de 0 à 3. Les poids sont des constantes de module
(`EFFECT_WEIGHTS`…), à ajuster en un seul endroit ; chaque note est accompagnée
d'une justification en français (`Score.rationale`) pour rester auditable.

Verdict (aptitude dont au moins un effet est reconnu) :

* **anecdotique** si puissance < `MIN_POWER` ;
* **bonus** si elle n'est disponible qu'à partir du round `LATE_ROUND` (ressource de
  faction qui s'accumule seule, ex. Dîme de Sang) et reste forte ;
* fiable (≥ `PLAN_RELIABILITY`) et facile (≥ `PLAN_EASE`) : **plan** si puissance ≥
  `PLAN_POWER`, sinon **correct** (fiable mais d'effet moyen) ;
* aléa de **dés** (fiabilité < `PLAN_RELIABILITY`) : **pari** si puissance ≥ `GAMBLE_POWER` ;
* aléa de **situation** (fiable mais mise en place difficile : coordination, kill
  préalable…) : **bonus** si puissance ≥ `GAMBLE_POWER` — gratuite, on en profite
  quand la situation se présente, on ne la provoque pas ;
* **anecdotique** sinon.

Typologie (validée par l'utilisateur) : le *pari* se tente (jet), le *bonus* arrive
(temps ou situation), le *plan* et le *correct* se construisent.

L'axe `interaction` (rayonnement sur l'armée) n'entre pas dans le verdict : une
aptitude « soi-même » peut être un excellent plan ; il sert aux combos.
"""

from __future__ import annotations

import re

from .extract.targets import DICE_ROW_CUMUL, DICE_ROW_PREFIX, OPPONENT_PICKS
from .models import Effect, Extraction, Score

MIN_POWER = 1.25  # en dessous : effet trop faible pour peser
PLAN_RELIABILITY = 2.25  # ≈ déclenchement ≥ 75 % : un 2+ passe, un 3+ non
PLAN_EASE = 1.75
GAMBLE_POWER = 1.5
PLAN_POWER = 1.75  # en dessous, fiable et facile = « correct »
#: Aptitude active utilisable aux DEUX tours (« Any … phase », « End of Any Turn ») :
#: deux occasions par round au lieu d'une.
BOTH_TURNS_MULT = 1.15
#: Marquage d'une cible ennemie (« +1 Perf. aux attaques qui la visent ») : une bulle centrée
#: sur l'ennemi, dont profite toute unité amie qui l'attaque — même valeur qu'une aura amie.
MARK_MULT = 1.2
#: Round de disponibilité à partir duquel une aptitude ne peut plus porter un plan.
LATE_ROUND = 3
#: Pénalité de mise en place par round d'attente au-delà du premier (plafonnée).
DELAY_PENALTY_PER_ROUND, DELAY_PENALTY_MAX = 0.5, 2.0

#: Poids de base (puissance) d'un modificateur de ±1 par caractéristique.
STAT_WEIGHTS: dict[str, float] = {
    "hit": 1.5,
    "wound": 1.5,
    "rend": 1.5,
    "attacks": 1.5,
    "damage": 2.0,
    "save": 1.5,
    "ward": 1.0,
    "health": 1.0,
    "cast": 1.0,
    # Provisoire : le contrôle est une caractéristique peu valorisée (avis utilisateur) ;
    # à recaler sur les coefficients du modèle de coût (`aospy cost fit`, extra [analysis]).
    "control": 0.6,
    "chant": 1.0,
    "unbind": 0.75,
    "banish": 0.5,
    "charge": 1.0,
    "run": 0.5,
    "move": 1.0,
    "power_level": 0.5,
}

#: Poids de base des effets qualitatifs.
EFFECT_WEIGHTS: dict[str, float] = {
    "strike_first": 2.0,
    "strike_last": 2.0,
    "run_and_charge": 2.0,
    "run_and_shoot": 1.5,
    "redeploy": 2.0,
    "extra_fight": 3.0,
    "fight_twice": 3.0,
    "extra_shoot": 2.5,
    "shoot_in_combat": 1.0,
    "crit": 1.5,
    "reroll": 1.5,
    "cp_gain": 1.5,
    "anti_magic": 1.0,
    "lockout": 2.0,
    "restriction": 1.5,
    "untargetable": 2.0,
    "fly": 1.0,
    "move_debuff": 1.0,
    "summon": 1.5,
    "control": 0.6,
    "anti": 1.0,
    "charge_bonus": 1.0,
    "no_crit": 1.5,
    "pile_in": 0.5,
    "damage_redirect": 1.5,
    "extra_move": 1.5,
    "deep_strike": 2.0,
    "no_ward": 2.0,
    "slay": 2.0,
    "stat_set": 1.5,
    "negate_attack": 2.0,
    "keyword_gain": 0.5,
    "damage_ignore": 1.5,
    "no_weapon_abilities": 1.5,
    "resource": 1.0,
    "extra_use": 1.0,
    "battle_damaged": 0.0,
    "free_retreat": 1.0,
    "fixed_roll": 1.5,
    "rally": 1.0,
    "no_buff": 1.0,
    # v27, validés par l'utilisateur (2026-11-20) : +N" de portée de tir, ignorer les malus, provocation
    "range_bonus": 1.0,
    "ignore_debuff": 0.5,
    "taunt": 1.0,
    # v28, validés par l'utilisateur (2026-11-20) : tir sur un héros protégé (« Guarded Hero » ignoré) = 1,0,
    # soins/retours de figurines interdits à l'ennemi = 1,0 (l'utilisateur a choisi plus haut que ma proposition 0,75)
    "snipe": 1.0,
    "anti_heal": 1.0,
    # v29, validés par l'utilisateur (2026-11-21) : choix de profil d'arme = règle de profil (0), cartes de tactique
    # 1,5 (plus haut que ma proposition 1,0 : le scoring décide la partie), cohésion 2" 0,25 (plus bas que 0,5)
    "profile_choice": 0.0,
    "tactic_cards": 1.5,
    "coherency": 0.25,
    # v30 : règle de fonctionnement (parties de manifestation, jetons, montée sur un décor) — même principe que le
    # choix de profil (validé à 0) : pas une aptitude
    "warscroll_rule": 0.0,
    # v31, validé par l'utilisateur (2026-11-21) : artefact retiré à un héros ennemi = 1,0 (plus bas que ma
    # proposition 1,5 : contre-combo, beaucoup de héros adverses n'en ont pas)
    "strip_enhancement": 1.0,
    # v34 (C), validé par l'utilisateur (2026-11-22) : −1 au niveau de fureur adverse = 0,5 (remise à 0 : 1,0)
    "fury_debuff": 0.5,
}
FURY_RESET_WEIGHT = 1.0

#: v34 (B) : effets dont la valeur est dans d'AUTRES aptitudes, résolue en seconde passe
#: (`abilities.references.resolve_references`, règles validées par l'utilisateur le 2026-11-22).
RESOLVED_KINDS: dict[str, str] = {
    "ability_ref": "modifie",
    "status_grant": "statut",
    "free_enhancement": "enhancement gratuit",
    "terrain_setup": "décor en plus",
}

#: Dé en plus / en moins sur un jet (analyseur v28, validé par l'utilisateur 2026-11-20). « garder » (3 dés, on en retire 1) ≈ une relance du jet
#: (charge à 9" : 28 % → 52 %, relance 48 %) ; « somme » (3D6) = plus fort (9" : 74 %, ×5/3). Un dé de moins
#: à la charge ENNEMIE (1D6) rend toute charge de plus de 6" impossible : dissuasion forte.
DICE_SUM_MULT = 5 / 3
DICE_ENEMY_WEIGHTS: dict[str, float] = {"charge": 2.0, "cast": 1.5, "unbind": 1.0, "run": 0.5, "": 1.0}

#: Relance complète d'un type de jet (analyseur v25, validé utilisateur 2026-11-20) : relancer une charge
#: à 9" (28 % → 48 %) vaut mieux qu'un +1 charge (42 %). Relance partielle (1 jet, 1 dé, les 1) = moitié.
REROLL_WEIGHTS: dict[str, float] = {
    "hit": 1.5,
    "wound": 1.5,
    "save": 1.5,
    "charge": 1.5,
    "ward": 1.0,
    "run": 0.5,
    "cast": 1.0,
    "chant": 1.0,
    "unbind": 0.75,
    "": 1.0,
}

_WARD_WEIGHTS = {6: 1.0, 5: 2.0, 4: 2.5, 3: 3.0, 2: 3.0}
#: Protection perdue au premier jet de sauvegarde de 1 (jeton type Gryph-hound) : P(tenir
#: n dés) = (5/6)^n, elle disparaît en général dès la première attaque sérieuse.
FRAGILE_MULT = 0.35
#: Critique sur N+ (au lieu de 6+) : poids selon le seuil.
_CRIT_THRESHOLD_WEIGHTS = {5: 2.5, 4: 3.0, 3: 3.0}
#: Effets qui neutralisent l'offensive d'UNE unité ennemie : cumulés sur la même cible,
#: ils transforment une Death-Star en unité moyenne — facteur de cumul plus fort.
_OFFENSE_DEBUFF_KINDS = {"no_crit", "strike_last", "no_weapon_abilities"}
OFFENSE_STACK_FACTOR = 0.7
STACK_FACTOR = 0.35

_SCOPE_MULT = {
    "self": 1.0,
    "one_friendly": 1.0,
    "friendly_aura": 1.2,
    "army": 1.4,
    "one_enemy": 1.0,
    "enemy_aura": 1.2,
    "all_enemies": 1.4,
    "battlefield": 1.0,
    "unknown": 1.0,
}
_FREQ_MULT = {"once_per_battle": 0.6, "once_per_battle_army": 0.6, "once_per_round": 0.9, "once_per_round_army": 0.9}

_FR_STAT = {
    "hit": "touche",
    "wound": "blessure",
    "save": "sauvegarde",
    "ward": "protection",
    "attacks": "Attaques",
    "rend": "Perforation",
    "damage": "Dégâts",
    "charge": "charge",
    "run": "course",
    "cast": "lancement",
    "chant": "psalmodie",
    "unbind": "dissipation",
    "banish": "bannissement",
    "redeploy": "Redeploy",
    "control": "contrôle",
    "health": "PV",
    "move": "Mouvement",
    "power_level": "niveau de puissance",
}


def _effect_weight(e: Effect) -> tuple[float, str]:
    if e.kind == "stat_mod":
        if e.detail == "malus":
            return 0.0, ""
        w = STAT_WEIGHTS.get(e.stat, 0.5) * (1.6 if abs(e.value) >= 2 else 1.0)
        sign = "+" if e.value > 0 else "−"
        who = "ennemi" if e.side == "enemy" else "ami"
        return w, f"{sign}{abs(int(e.value))} {_FR_STAT.get(e.stat, e.stat)} ({who}, {e.detail})"
    if e.kind == "mortal_damage":
        if e.side == "friendly":
            return 0.0, ""
        if e.detail == "par dé":  # v33 : nombre de dés selon la cible/le contexte, `value` = par dé
            return 1.5, f"BM par dé ({e.value:.2g} par dé)"
        if e.value:
            return min(3.0, 0.5 * e.value + 0.3), f"{e.dice or int(e.value)} BM (moy. {e.value:g})"
        return 1.5, "BM variables"
    if e.kind == "ward":
        if e.detail == "fragile":
            return (
                _WARD_WEIGHTS.get(int(e.value), 1.0) * FRAGILE_MULT,
                f"Protection {int(e.value)}+ perdue au 1er jet de sauvegarde de 1",
            )
        return _WARD_WEIGHTS.get(int(e.value), 1.0), f"Protection {int(e.value)}+"
    if e.kind == "crit":
        import re as _re

        m = _re.search(r"of (\d)\+", e.detail)
        if m:
            n = int(m.group(1))
            return _CRIT_THRESHOLD_WEIGHTS.get(n, 1.5), f"critique sur {n}+"
        return EFFECT_WEIGHTS["crit"], "aptitude de critique"
    if e.kind == "heal":
        return (min(2.0, 0.4 * e.value + 0.4) if e.value else 1.0), f"soin {e.dice or int(e.value) or 'X'}"
    if e.kind == "return_models":
        return 2.0, "retour de figurines"
    if e.kind == "move":
        if e.side == "enemy":
            return 0.5, "déplace une unité ennemie"
        return (1.75 if e.value >= 6 else 1.5), f'mouvement {e.dice or (int(e.value) if e.value else "")}"'
    if e.kind == "reroll":
        w = REROLL_WEIGHTS.get(e.stat, 1.0) * (0.5 if e.value < 1 else 1.0)
        return w, f"{e.detail} {_FR_STAT.get(e.stat, e.stat) or 'de dés'}".strip()
    if e.kind == "battle_damaged":
        return 0.0, ""
    if e.kind == "dice_count":
        name = _FR_STAT.get(e.stat, e.stat) or "jet"
        if e.side == "enemy":
            return DICE_ENEMY_WEIGHTS.get(e.stat, 1.0), f"un dé de moins ({name}, ennemi)"
        if e.value < 0:
            return 0.0, ""  # contrepartie sur sa propre unité
        base = 0.5 if e.stat == "redeploy" else REROLL_WEIGHTS.get(e.stat, 1.0)  # Redeploy ≈ course
        w = base * (DICE_SUM_MULT if e.detail == "somme" else 1.0)  # « max » (dé bas = dé haut) ≈ « garder »
        how = {"somme": "tous comptent", "max": "le plus bas devient le plus haut"}.get(e.detail, "on en retire un")
        return w, f"un dé de plus ({name}, {how})"
    if e.kind == "fury_debuff" and "to 0" in e.detail:
        return FURY_RESET_WEIGHT, "fureur adverse remise à 0"
    if e.kind in RESOLVED_KINDS:
        # v34 (B) : valeur résolue par `abilities.references` d'après les aptitudes citées (0 si non retrouvées)
        return e.value, f"{RESOLVED_KINDS[e.kind]} {e.detail} ({e.value:.2g})"
    if e.kind in ("strike_last", "restriction", "lockout", "move_debuff", "untargetable"):
        if e.kind == "untargetable" and e.side == "friendly":
            return 2.0, "inciblable"
        if e.side == "friendly" and e.kind != "untargetable":
            return 0.0, ""  # contrepartie sur sa propre unité
    if e.kind == "no_ward" and e.side == "friendly":
        return 0.0, ""  # v35 : contrepartie sur sa propre unité (Elite Guardians)
    w = EFFECT_WEIGHTS.get(e.kind, 0.5)
    return w, e.kind.replace("_", " ")


def power_of(ex: Extraction, effect_text: str) -> tuple[float, list[str]]:
    """Puissance ; une aptitude à options exclusives (« pick 1 of the following », runes de Master of the
    Runes, analyseur v33 : `Effect.option_group`) vaut sa meilleure option, pas leur somme."""
    value, notes = _options_power(ex, effect_text)
    if ex.power_factor != 1.0:
        value = round(value * ex.power_factor, 2)
        notes = notes + [ex.power_factor_note]
    return value, notes


def _options_power(ex: Extraction, effect_text: str) -> tuple[float, list[str]]:
    groups = list(dict.fromkeys(e.option_group for e in ex.effects if e.option_group))
    if groups and all(g.startswith(DICE_ROW_PREFIX) for g in groups):
        return _table_power(ex, groups, effect_text)
    if len(groups) < 2:
        return _power(ex, ex.effects, effect_text)
    variants = [_power(ex, [e for e in ex.effects if e.option_group in ("", g)], effect_text) for g in groups]
    if OPPONENT_PICKS.search(effect_text):
        # v34 (B1, proposition de l'utilisateur) : l'adversaire choisit → l'option la plus faible pour nous
        value, notes = min(variants, key=lambda v: v[0])
        return value, notes + [f"options exclusives choisies par l'adversaire : la plus faible des {len(groups)}"]
    value, notes = max(variants, key=lambda v: v[0])
    return value, notes + [f"options exclusives : la meilleure des {len(groups)}"]


def _p_range(lo: int, hi: int, two_d6: bool) -> float:
    if two_d6:
        return sum(1 for a in range(1, 7) for b in range(1, 7) if lo <= a + b <= hi) / 36
    return max(0, min(hi, 6) - max(lo, 1) + 1) / 6


def _table_power(ex: Extraction, groups: list[str], effect_text: str) -> tuple[float, list[str]]:
    """v34 : table de résultats aléatoires (« Roll a dice and apply the corresponding effect: 1 - …, 2-4 - … »)
    → espérance des lignes, chacune pondérée par la probabilité de sa plage (D6, ou 2D6 si une plage dépasse 6).
    Une ligne « In addition to the effect of … » reprend les effets de la ligne précédente. Les lignes sans
    effet reconnu (« No effect », contrepartie) valent 0."""
    def _range(g: str) -> tuple[int, int]:
        lo, hi = g[len(DICE_ROW_PREFIX) :].split(" ")[0].split("-")
        return int(lo), int(hi)

    groups = sorted(groups, key=_range)  # ordre du dé : « +préc » reprend la ligne juste en dessous
    ranges = [_range(g) for g in groups]
    two_d6 = max(hi for _, hi in ranges) > 6
    common = [e for e in ex.effects if not e.option_group]
    rows, prev = [], []
    for g, (lo, hi) in zip(groups, ranges):
        row = [e for e in ex.effects if e.option_group == g]
        effects = common + row + (prev if g.endswith(DICE_ROW_CUMUL) else [])
        rows.append((lo, hi, _power(ex, effects, effect_text)[0]))
        prev = row + (prev if g.endswith(DICE_ROW_CUMUL) else [])
    # v34 (B3) : ligne « Pick any other effect » (Aura of Mutation) = la meilleure des autres lignes, au lieu de 0
    for lo, hi in _free_pick_rows(effect_text):
        if not any(r[0] == lo and r[1] == hi for r in rows):
            ranges.append((lo, hi))
        best = max((v for a, b, v in rows if (a, b) != (lo, hi)), default=0.0)
        rows = [r for r in rows if (r[0], r[1]) != (lo, hi)] + [(lo, hi, best)]
    two_d6 = max(hi for _, hi in ranges) > 6
    _, notes = _power(ex, ex.effects, effect_text)
    k = _picked_dice(effect_text)
    if k > 1 and not two_d6:
        # « Roll 2 dice, pick either result » (Radiant Transmogrification) : meilleur des k dés
        face = sorted((next((v for lo, hi, v in rows if lo <= f <= hi), 0.0) for f in range(1, 7)), reverse=True)
        value = sum(v * ((1 - ((6 - i - 1) / 6) ** k) - (1 - ((6 - i) / 6) ** k)) for i, v in enumerate(face))
        return round(value, 2), notes + [f"table aléatoire (meilleur de {k} dés) : espérance des {len(groups)} lignes"]
    value = sum(_p_range(lo, hi, two_d6) * v for lo, hi, v in rows)
    die = "2D6" if two_d6 else "D6"
    return round(value, 2), notes + [f"table aléatoire ({die}) : espérance des {len(groups)} lignes"]


_FREE_PICK_ROW = re.compile(
    r"^\s*(?:-\s*)?(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\b[^\n]*?\b(?:[Pp]ick|[Cc]hoose) "
    r"(?:any other|1 of the other|one of "
    r"the other|another) (?:effect|result|row)",
    re.M,
)


def _free_pick_rows(text: str) -> list[tuple[int, int]]:
    """Lignes de table « 6 - Mutant Tide: Pick any other effect » : plages (lo, hi)."""
    return [(int(m.group(1)), int(m.group(2) or m.group(1))) for m in _FREE_PICK_ROW.finditer(text)]


#: « Roll 2 dice, pick either result » / « Roll 3 dice. You must pick 1 of those dice » ; un « you can roll 2 dice
#: instead » conditionnel (Aura of Mutation, près d'un sorcier de Tzeentch) n'en est pas un : « Roll » en tête.
_PICK_DICE = re.compile(r"\bRoll (\d|two|three) dice\b(?:\.\s*)?[^.]*?\bpick (?:either|1|one)\b")


def _picked_dice(text: str) -> int:
    """Nombre de dés lancés parmi lesquels on choisit le résultat de la table (1 = tirage simple)."""
    m = _PICK_DICE.search(text)
    if not m:
        return 1
    n = m.group(1).lower()
    return {"two": 2, "three": 3}.get(n) or int(n)


def _power(ex: Extraction, effects: list[Effect], effect_text: str) -> tuple[float, list[str]]:
    best: dict[str, tuple[float, str]] = {}  # un même type d'effet ne compte qu'une fois (le meilleur)
    for e in effects:
        w = _effect_weight(e)
        key = f"{e.kind}:{e.stat}:{e.side}"
        if w[0] > best.get(key, (0.0, ""))[0]:
            best[key] = w
    weights = sorted(best.values(), key=lambda t: -t[0])
    if not weights:
        return 0.0, ["aucun effet chiffrable"]
    offense_debuffs = sum(
        1
        for e in effects
        if e.side == "enemy" and (e.kind in _OFFENSE_DEBUFF_KINDS or (e.kind == "stat_mod" and e.detail == "defensif"))
    )
    factor = OFFENSE_STACK_FACTOR if offense_debuffs >= 2 and ex.scope == "one_enemy" else STACK_FACTOR
    raw = weights[0][0] + factor * sum(w for w, _ in weights[1:])
    lasting = "rest of the battle" in effect_text and "rest of the battle round" not in effect_text
    # « Once Per Battle » + effet « for the rest of the battle » : la limite n'est qu'un déclencheur
    # (garde-fou anti-cumul, cf. deux Warqueen dans la même armée), l'effet est permanent une
    # fois lancé → ni pénalité de fréquence ni bonus de durée, comme une passive (avis utilisateur).
    # v34 : un enhancement donné au déploiement reste toute la partie (validé : pas de malus « une fois »)
    once_lasting = (lasting or any(e.kind == "free_enhancement" for e in effects)) and ex.frequency.startswith(
        "once_per_battle"
    )
    freq = 1.0 if once_lasting else _FREQ_MULT.get(ex.frequency, 1.0)
    scope_mult = _SCOPE_MULT.get(ex.scope, 1.0)
    if ex.scope in ("enemy_aura", "all_enemies") and all(e.kind in RESOLVED_KINDS for e in effects):
        scope_mult = 1.0  # v34 : statut/renvoi donné à NOS unités, la portée ennemie n'est qu'un décompte
    mult = scope_mult * freq
    notes = [f"effets : {', '.join(lbl for _, lbl in weights[:4] if lbl)}"]
    if any(e.detail == "marquage" for e in effects):
        mult *= MARK_MULT
        notes.append("marquage : profite à toute unité amie qui attaque la cible")
    if ex.turn == "any" and ex.frequency not in ("passive", "once_per_battle", "once_per_battle_army"):
        mult *= BOTH_TURNS_MULT
        notes.append("utilisable aux deux tours")
    if once_lasting:
        notes.append("une fois par bataille = déclencheur, effet jusqu'à la fin de la bataille")
    elif lasting:  # « rest of the battle round » ne dure qu'un round : pas de bonus
        mult *= 1.3
        notes.append("durable (reste de la bataille)")
    elif ex.frequency.startswith("once_per_battle"):
        notes.append("une fois par bataille")
    return round(min(3.0, raw * mult), 2), notes


def reliability_of(ex: Extraction) -> tuple[float, list[str]]:
    p = ex.activation_prob
    pen = {"fixe": 0.0, "des": 0.25, "binomial": 0.4}[ex.variance]
    rel = max(0.0, min(3.0, 3 * p - pen))
    notes = list(ex.activation_notes)
    if ex.variance != "fixe":
        notes.append("effet " + ("à jets multiples" if ex.variance == "binomial" else "à valeur aléatoire"))
    if p >= 0.999 and ex.variance == "fixe":
        notes.append("automatique")
    return round(rel, 2), notes


def ease_of(ex: Extraction, penalty: float, cost_type: str, is_reaction: bool) -> tuple[float, list[str]]:
    pen, notes = penalty, list(ex.conditions)
    if cost_type.lower() == "command":
        pen += 0.5
        notes.append("coûte un PC")
    if is_reaction:
        pen += 0.25
        notes.append("réaction (dépend d'un déclencheur)")
    if ex.scope in ("one_enemy", "one_friendly") and ex.range_inches is not None:
        if ex.range_inches <= 3 and ex.scope == "one_friendly":
            pen += 0.5
            notes.append(f'cible à {ex.range_inches}"')
        elif ex.range_inches <= 6 and ex.scope == "one_enemy" and ex.range_inches > 1:
            pen += 0.25
            notes.append(f'cible ennemie à {ex.range_inches}"')
    if ex.available_round and ex.available_round > 1:
        pen += min(DELAY_PENALTY_MAX, DELAY_PENALTY_PER_ROUND * (ex.available_round - 1))
        notes.append(f"{ex.resource_cost} pts de {cost_type.lower()} cumulés → dispo. ~round {ex.available_round}")
    if ex.scope == "friendly_aura" and ex.range_inches is not None and ex.range_inches <= 6:
        pen += 0.5 if ex.wholly_within else 0.25
        notes.append(f'bulle courte ({ex.range_inches}")')
    return round(max(0.0, 3.0 - pen), 2), notes or ["aucun prérequis notable"]


def interaction_of(ex: Extraction) -> tuple[float, str]:
    s, r = ex.scope, ex.range_inches
    if s == "army":
        return 3.0, "toute l'armée"
    if s == "friendly_aura":
        v = 1.5 + (1.0 if (r or 0) >= 18 else 0.75 if (r or 0) >= 12 else 0.25 if (r or 0) >= 9 else 0.0)
        return v, f'bulle {"entièrement " if ex.wholly_within else ""}à {r}"'
    if s == "one_friendly":
        return 1.0, "une unité amie" + (f' à {r}"' if r else "")
    if s in ("enemy_aura", "all_enemies"):
        return 2.0, "affaiblit plusieurs ennemis (profite à toute l'armée)"
    if s == "one_enemy" and any(e.detail == "marquage" for e in ex.effects):
        ft = ex.friendly_target
        if ft and not any(w.isupper() for w in ft.split()):
            # nom propre de charte (« Hobgrot Slittaz ») : un seul type d'unité en profite
            return 1.5, f"marquage restreint : les {ft} amis qui attaquent la cible en profitent"
        return 2.0, "marquage : " + (
            f"les unités {ft} amies" if ft else "toute unité amie"
        ) + " qui attaquent la cible en profitent"
    if s == "one_enemy":
        if any(e.kind == "stat_mod" and e.side == "enemy" for e in ex.effects) or any(
            e.kind in ("strike_last", "lockout", "restriction") for e in ex.effects
        ):
            return 1.0, "affaiblit une cible pour toute l'armée"
        return 0.0, "effet direct sur une cible"
    return 0.0, "unité porteuse seule"


def score(ex: Extraction, penalty: float, cost_type: str, is_reaction: bool, effect_text: str) -> Score:
    power, p_notes = power_of(ex, effect_text)
    rel, r_notes = reliability_of(ex)
    ease, e_notes = ease_of(ex, penalty, cost_type, is_reaction)
    inter, i_note = interaction_of(ex)
    if not ex.effects:
        verdict = "a-revoir"
    elif power < MIN_POWER:
        verdict = "anecdotique"
    elif ex.available_round and ex.available_round >= LATE_ROUND:
        verdict = "bonus" if power >= GAMBLE_POWER else "anecdotique"
    elif rel >= PLAN_RELIABILITY and ease >= PLAN_EASE:
        verdict = "plan" if power >= PLAN_POWER else "correct"
    elif rel < PLAN_RELIABILITY:
        verdict = "pari" if power >= GAMBLE_POWER else "anecdotique"
    else:
        verdict = "bonus" if power >= GAMBLE_POWER else "anecdotique"
    rationale = [
        f"Puissance {power:.1f} — {'; '.join(p_notes)}",
        f"Fiabilité {rel:.1f} — {'; '.join(r_notes) or 'automatique'}",
        f"Mise en place {ease:.1f} — {'; '.join(e_notes)}",
        f"Interaction {inter:.1f} — {i_note}",
    ]
    return Score(ease, power, rel, inter, verdict, rationale)  # type: ignore[arg-type]
