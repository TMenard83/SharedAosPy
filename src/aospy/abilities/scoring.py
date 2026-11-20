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

from .models import Effect, Extraction, Score

MIN_POWER = 1.25   # en dessous : effet trop faible pour peser
PLAN_RELIABILITY = 2.25   # ≈ déclenchement ≥ 75 % : un 2+ passe, un 3+ non
PLAN_EASE = 1.75
GAMBLE_POWER = 1.5
PLAN_POWER = 1.75   # en dessous, fiable et facile = « correct »
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
    "hit": 1.5, "wound": 1.5, "rend": 1.5, "attacks": 1.5, "damage": 2.0,
    "save": 1.5, "ward": 1.0, "health": 1.0, "cast": 1.0,
    # Provisoire : le contrôle est une caractéristique peu valorisée (avis utilisateur) ;
    # à recaler sur les coefficients du modèle de coût (`aospy cost fit`, extra [analysis]).
    "control": 0.6,
    "chant": 1.0, "unbind": 0.75, "banish": 0.5, "charge": 1.0, "run": 0.5,
    "move": 1.0, "power_level": 0.5,
}

#: Poids de base des effets qualitatifs.
EFFECT_WEIGHTS: dict[str, float] = {
    "strike_first": 2.0, "strike_last": 2.0, "run_and_charge": 2.0, "run_and_shoot": 1.5,
    "redeploy": 2.0, "extra_fight": 3.0, "fight_twice": 3.0, "extra_shoot": 2.5, "shoot_in_combat": 1.0,
    "crit": 1.5, "reroll": 1.5, "cp_gain": 1.5, "anti_magic": 1.0, "lockout": 2.0,
    "restriction": 1.5, "untargetable": 2.0, "fly": 1.0, "move_debuff": 1.0, "summon": 1.5,
    "control": 0.6, "anti": 1.0, "charge_bonus": 1.0, "no_crit": 1.5, "pile_in": 0.5, "damage_redirect": 1.5,
    "extra_move": 1.5, "deep_strike": 2.0, "no_ward": 2.0, "slay": 2.0, "stat_set": 1.5,
    "negate_attack": 2.0, "keyword_gain": 0.5,
    "damage_ignore": 1.5, "no_weapon_abilities": 1.5, "resource": 1.0, "extra_use": 1.0,
    "battle_damaged": 0.0,
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
    "self": 1.0, "one_friendly": 1.0, "friendly_aura": 1.2, "army": 1.4,
    "one_enemy": 1.0, "enemy_aura": 1.2, "all_enemies": 1.4, "battlefield": 1.0, "unknown": 1.0,
}
_FREQ_MULT = {"once_per_battle": 0.6, "once_per_battle_army": 0.6,
              "once_per_round": 0.9, "once_per_round_army": 0.9}

_FR_STAT = {"hit": "touche", "wound": "blessure", "save": "sauvegarde", "ward": "protection",
            "attacks": "Attaques", "rend": "Perforation", "damage": "Dégâts", "charge": "charge",
            "run": "course", "cast": "lancement", "chant": "psalmodie", "unbind": "dissipation",
            "banish": "bannissement", "control": "contrôle", "health": "PV", "move": "Mouvement",
            "power_level": "niveau de puissance"}


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
        if e.value:
            return min(3.0, 0.5 * e.value + 0.3), f"{e.dice or int(e.value)} BM (moy. {e.value:g})"
        return 1.5, "BM variables"
    if e.kind == "ward":
        if e.detail == "fragile":
            return (_WARD_WEIGHTS.get(int(e.value), 1.0) * FRAGILE_MULT,
                    f"Protection {int(e.value)}+ perdue au 1er jet de sauvegarde de 1")
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
        return (1.75 if e.value >= 6 else 1.5), f"mouvement {e.dice or (int(e.value) if e.value else '')}\""
    if e.kind == "battle_damaged":
        return 0.0, ""
    if e.kind in ("strike_last", "restriction", "lockout", "move_debuff", "untargetable"):
        if e.kind == "untargetable" and e.side == "friendly":
            return 2.0, "inciblable"
        if e.side == "friendly" and e.kind != "untargetable":
            return 0.0, ""   # contrepartie sur sa propre unité
    w = EFFECT_WEIGHTS.get(e.kind, 0.5)
    return w, e.kind.replace("_", " ")


def power_of(ex: Extraction, effect_text: str) -> tuple[float, list[str]]:
    best: dict[str, tuple[float, str]] = {}   # un même type d'effet ne compte qu'une fois (le meilleur)
    for e in ex.effects:
        w = _effect_weight(e)
        key = f"{e.kind}:{e.stat}:{e.side}"
        if w[0] > best.get(key, (0.0, ""))[0]:
            best[key] = w
    weights = sorted(best.values(), key=lambda t: -t[0])
    if not weights:
        return 0.0, ["aucun effet chiffrable"]
    offense_debuffs = sum(
        1 for e in ex.effects
        if e.side == "enemy" and (e.kind in _OFFENSE_DEBUFF_KINDS
                                  or (e.kind == "stat_mod" and e.detail == "defensif")))
    factor = OFFENSE_STACK_FACTOR if offense_debuffs >= 2 and ex.scope == "one_enemy" else STACK_FACTOR
    raw = weights[0][0] + factor * sum(w for w, _ in weights[1:])
    lasting = "rest of the battle" in effect_text and "rest of the battle round" not in effect_text
    # « Once Per Battle » + effet « for the rest of the battle » : la limite n'est qu'un déclencheur
    # (garde-fou anti-cumul, cf. deux Warqueen dans la même armée), l'effet est permanent une
    # fois lancé → ni pénalité de fréquence ni bonus de durée, comme une passive (avis utilisateur).
    once_lasting = lasting and ex.frequency.startswith("once_per_battle")
    freq = 1.0 if once_lasting else _FREQ_MULT.get(ex.frequency, 1.0)
    mult = _SCOPE_MULT.get(ex.scope, 1.0) * freq
    notes = [f"effets : {', '.join(lbl for _, lbl in weights[:4] if lbl)}"]
    if any(e.detail == "marquage" for e in ex.effects):
        mult *= MARK_MULT
        notes.append("marquage : profite à toute unité amie qui attaque la cible")
    if ex.turn == "any" and ex.frequency not in ("passive", "once_per_battle", "once_per_battle_army"):
        mult *= BOTH_TURNS_MULT
        notes.append("utilisable aux deux tours")
    if once_lasting:
        notes.append("une fois par bataille = déclencheur, effet jusqu'à la fin de la bataille")
    elif lasting:   # « rest of the battle round » ne dure qu'un round : pas de bonus
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
            notes.append(f"cible à {ex.range_inches}\"")
        elif ex.range_inches <= 6 and ex.scope == "one_enemy" and ex.range_inches > 1:
            pen += 0.25
            notes.append(f"cible ennemie à {ex.range_inches}\"")
    if ex.available_round and ex.available_round > 1:
        pen += min(DELAY_PENALTY_MAX, DELAY_PENALTY_PER_ROUND * (ex.available_round - 1))
        notes.append(f"{ex.resource_cost} pts de {cost_type.lower()} cumulés → dispo. ~round {ex.available_round}")
    if ex.scope == "friendly_aura" and ex.range_inches is not None and ex.range_inches <= 6:
        pen += 0.5 if ex.wholly_within else 0.25
        notes.append(f"bulle courte ({ex.range_inches}\")")
    return round(max(0.0, 3.0 - pen), 2), notes or ["aucun prérequis notable"]


def interaction_of(ex: Extraction) -> tuple[float, str]:
    s, r = ex.scope, ex.range_inches
    if s == "army":
        return 3.0, "toute l'armée"
    if s == "friendly_aura":
        v = 1.5 + (1.0 if (r or 0) >= 18 else 0.75 if (r or 0) >= 12 else 0.25 if (r or 0) >= 9 else 0.0)
        return v, f"bulle {'entièrement ' if ex.wholly_within else ''}à {r}\""
    if s == "one_friendly":
        return 1.0, "une unité amie" + (f" à {r}\"" if r else "")
    if s in ("enemy_aura", "all_enemies"):
        return 2.0, "affaiblit plusieurs ennemis (profite à toute l'armée)"
    if s == "one_enemy" and any(e.detail == "marquage" for e in ex.effects):
        ft = ex.friendly_target
        if ft and not any(w.isupper() for w in ft.split()):
            # nom propre de charte (« Hobgrot Slittaz ») : un seul type d'unité en profite
            return 1.5, f"marquage restreint : les {ft} amis qui attaquent la cible en profitent"
        return 2.0, "marquage : " + (f"les unités {ft} amies" if ft else "toute unité amie") + \
            " qui attaquent la cible en profitent"
    if s == "one_enemy":
        if any(e.kind == "stat_mod" and e.side == "enemy" for e in ex.effects) or any(
                e.kind in ("strike_last", "lockout", "restriction") for e in ex.effects):
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
