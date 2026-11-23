"""Couche 3 — qualité du mariage châssis × aptitude : le châssis déclenche-t-il l'effet, le fait-il durer ?

Recadrage utilisateur (2026-11-20, mémoire `ability-marriage-quality`) : une bonne aptitude peut être mal
mariée (Oath of Supremacy sur la Darkoath Warqueen : 5" de mouvement, 5 PV — « si ça se met en place c'est
cool, mais ça n'arrive jamais »). Deux facteurs s'ajoutent à l'amplification déjà mesurée par
`encounter.py` :

* **D — déclenchement** : probabilité que le châssis remplisse une condition qui pèse sur **le porteur**
  (« a chargé », « en territoire », « sur objectif », « au combat », « sans mouvement »), et round où il le
  peut au plus tôt. Les conditions tenues par un allié (« près d'une unité amie », couche 4), par
  l'adversaire (« vs HERO », « cible ≥10 figurines », « charge ennemie » : matchups) ou par une ressource
  restent dans la colonne « bon cas » — partage validé par l'utilisateur ;
* **S — survie** : part des rounds pendant lesquels le porteur reste en vie pour tenir l'effet (bulle,
  aura), selon l'exposition qu'impose la portée — au contact (≤ 3"), courte (≤ 9"), longue (≥ 10",
  le porteur reste derrière un écran) — et les dégâts qu'il subit d'une unité ennemie moyenne
  (`unit_benchmark`, réparti mêlée/tir selon le profil de l'attaquant, `unit_chassis.share_melee`).

Grille par famille (2026-11-21, recommandations validées par l'utilisateur, buffs d'abord) — mariage =
D × S × F × A × R, `bearing` = D × S seul :

* **F — tempo** (0-1) : la fenêtre de l'effet tombe-t-elle quand ce châssis agit ? Relatif, à fréquence
  égale (la fréquence elle-même est pondérée en couche 1) ;
* **A — amplification** (borné 0,5-1,5) : gain sur ce châssis / gain médian du même effet sur tous les
  châssis mesurés (`ability_encounter`) ; neutre si l'effet n'est pas traduit ;
* **R — rôle** (borné 0,5-1,5) : rang offensif pour un buff offensif, rang défensif et contact pour un buff
  défensif, « le porteur suit ses receveurs » (allonge) pour un buff donné.

Débuffs (2026-11-22, réponses utilisateur) : D × P(au combat) au contact, F règle des buffs selon la
polarité du débuff, R selon qui en profite (rang défensif / offensif au contact, neutre à distance), A neutre.
Dégâts directs (2026-11-22, réponses utilisateur) : D × P(au combat) au contact, survol par l'allonge, riposte au
contact avec R = 0,5 + rang défensif, BM sur ses attaques jugées comme un buff offensif perso ; F et A neutres.
Mobilité (2026-11-23, réponses utilisateur) : mobilité perso exposée comme un buff perso, R = 0,5 + rang offensif
(dégagement : max(rang off., fragilité)), A = gain relatif (P(charge) gagnée, sinon allonge) ; donnée : le porteur suit
ses receveurs ; F neutre.
Les autres familles restent neutres (A = R = F = 1) : critères proposés dans analysis/README.md.

**Toutes les constantes ci-dessous sont des hypothèses de travail à challenger** (règle utilisateur :
signaler les classements contre-intuitifs et proposer de les réviser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ...abilities.perimeter import CHARGE_EITHER, ON_OWN_ATTACKS, ONCE_TRIGGER, RETALIATION, SHOT_BY_BEARER
from ...domain.models import Unit

#: Géométrie de la table PAR SAISON (remarque utilisateur, 2026-11-20 : « ça dépend des saisons » — plans de
#: bataille et règle de déploiement changent avec le Manuel du général). Pour une nouvelle saison : relire ses
#: plans de bataille et sa règle « Deploy Unit », ajouter une entrée, changer `SEASON`.
#: 2026-27, vérifié le 2026-11-20 sur les 12 plans du MdG 2026-27 (`MdG26-27 Scenarii.pdf`) et « Deploy Unit »
#: (Core Rules p. 13, MdG FR : « entièrement en territoire ami et à plus de 9" du territoire ennemi ») : sur
#: toutes les cartes les deux territoires SE TOUCHENT (0" entre eux) → armées à ≥ 18" au départ.
SEASON_GEOMETRY = {
    "2026-27": {"territory_gap": 0.0, "deploy_gap": 9.0},
}
SEASON = "2026-27"
_GEO = SEASON_GEOMETRY[SEASON]
#: Distance minimale entre le déploiement et le territoire ennemi.
DEPLOY_GAP = _GEO["deploy_gap"]
#: Écart à couvrir (mouvement + charge) pour charger : au round 1, les armées partent à
#: 2 × déploiement + écart entre territoires (18" en 2026-27) ; ensuite 14" (hypothèse de milieu de partie,
#: non fixée par les cartes). Une charge à 9" après 5" de mouvement reste un pari (`charge-9-is-a-gamble`).
ENGAGE_GAP_ROUND1 = 2 * DEPLOY_GAP + _GEO["territory_gap"]
ENGAGE_GAP = 14.0
#: Distance à parcourir pour finir ENTIÈREMENT en territoire ennemi : déploiement + ~2" d'emprise.
TERRITORY_GAP = DEPLOY_GAP + 2.0
#: Bonus de distance effectif du vol (ignore décors et écrans).
FLY_BONUS = 2.0
RUN_MEAN = 3.5
CHARGE_MEAN = 7.0

#: Conditions tenues par le porteur → probabilité estimée d'après le châssis. Les autres libellés
#: (`perimeter._REQUIRES` / `_TARGET_CONDITIONS`) ne dépendent pas de lui.
OVERFLY = "a survolé la cible"
BEARER_CONDITIONS = (
    "a chargé",
    "en territoire",
    "sur objectif",
    "au combat",
    "sans mouvement",
    "sans charge",
    "combat enchaîné",
    # v34 (Brutal Troof) : notre charge OU une charge ennemie = le combat d'un tour de charge, quel que
    # soit le camp ; ne dépend pas de la réussite d'une charge du porteur.
    CHARGE_EITHER,
    # v35 : débuff posé par les tirs du porteur — il tire (p = 1), l'exposition suit sa portée de tir
    SHOT_BY_BEARER,
    # v35 (dégâts directs, réponses utilisateur du 2026-11-22) : survoler la cible → `p_overfly` ; riposte et BM
    # sur ses attaques : p = 1 ici, le contact et le rôle sont lus dans `marriage_of`
    OVERFLY,
    RETALIATION,
    ON_OWN_ATTACKS,
)
#: Épaisseur de cible à dépasser pour la survoler (« an enemy unit that this unit passed across »).
OVERFLY_DEPTH = 3.0
#: « The target can be picked to fight immediately after this unit… If it is picked to do so, add 1… »
#: (Brawlerguts, Lead Da Brutes, Infantry Overseer…) : le bonus ne joue que si le héros et l'unité combattent
#: l'un après l'autre. Part des combats où c'est le cas : choix utilisateur 2026-11-22 (option « ×0,5 »,
#: hypothèse à calibrer) — ni plein (il faut être collés), ni nul (sinon tout l'archétype perd son soutien).
CHAINED_FIGHT_SHARE = 0.5
#: Déclencheur unique sans entrée en territoire (charge, kill, objectif) : round où l'effet est en général
#: acquis — le round 1 est un pari (charge à 18", mémoire « charge à 9" = pari »). Hypothèse v34, à calibrer.
ONCE_TRIGGER_START = 2
#: Un bonus « a chargé » ne joue qu'au combat du tour de charge ; une unité au corps à corps combat aussi
#: au tour adverse et en combat prolongé → environ la moitié de ses combats (choix utilisateur, 2026-11-20 :
#: « il faut mitiger les dégâts »).
CHARGE_FIGHT_SHARE = 0.5
#: Sans charge ce tour : part des combats d'une unité de mêlée hors de son tour de charge (combat
#: prolongé, tour adverse) ; un tireur qui ne charge pas l'est presque toujours.
P_NOT_CHARGED_MELEE, P_NOT_CHARGED_SHOOTER = 0.6, 0.9
#: Sur objectif : une troupe (≥ 3 figurines) tient un objectif par nature, un héros seul beaucoup moins.
P_OBJECTIVE_TROOP, P_OBJECTIVE_HERO = 0.75, 0.4
#: Au combat (effet non offensif de mêlée) : unité de mêlée / de tir.
P_IN_COMBAT_MELEE, P_IN_COMBAT_SHOOTER = 0.8, 0.3
#: Sans mouvement : un tireur reste volontiers immobile, une unité de mêlée rarement.
P_STILL_SHOOTER, P_STILL_MELEE = 0.6, 0.2

#: Exposition (part des dégâts de mêlée / de tir d'une unité ennemie moyenne subis par round).
EXPOSURE = {
    "contact": (1.0, 1.0),
    "courte": (0.5, 1.0),
    "longue": (0.15, 0.6),  # derrière un écran : chargé rarement, visé seulement si visible
}

ROUND_WEIGHTS = (1 / 3, 1.0, 1.0, 1 / 3, 1 / 3)


def p_2d6_at_least(n: float) -> float:
    n = int(-(-n // 1))  # plafond
    if n <= 2:
        return 1.0
    if n > 12:
        return 0.0
    return sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= n) / 36.0


def reach(unit: Unit) -> float:
    return unit.move + (FLY_BONUS if "FLY" in unit.keywords else 0.0)


def p_charge(unit: Unit, start: int = 1) -> float:
    """P(réussir la charge), moyenne pondérée des rounds `start`..5 : 2D6 ≥ écart − mouvement, l'écart
    valant `ENGAGE_GAP_ROUND1` au round 1 (armées à ≥ 18") puis `ENGAGE_GAP`."""
    rounds = range(max(start, 1), 6)
    tot = sum(ROUND_WEIGHTS[r - 1] for r in rounds)
    if not tot:
        return 0.0
    return (
        sum(
            ROUND_WEIGHTS[r - 1] * p_2d6_at_least((ENGAGE_GAP_ROUND1 if r == 1 else ENGAGE_GAP) - reach(unit))
            for r in rounds
        )
        / tot
    )


def p_overfly(unit: Unit) -> float:
    """P(passer au-dessus d'une cible ennemie dans un round), pondérée par les rounds (réponse utilisateur,
    2026-11-22) : possible quand mouvement (+ vol) + course + `OVERFLY_DEPTH` ≥ l'écart — 18" au round 1, 14"
    ensuite. Ironclad (12" de vol) 1,0 ; Hellflayer (10", sans vol) 0,89, le round 1 lui est hors de portée."""
    span = reach(unit) + RUN_MEAN + OVERFLY_DEPTH
    ok = [1.0 if span >= (ENGAGE_GAP_ROUND1 if r == 1 else ENGAGE_GAP) else 0.0 for r in range(1, 6)]
    return sum(w * k for w, k in zip(ROUND_WEIGHTS, ok)) / sum(ROUND_WEIGHTS)


def territory_round(unit: Unit, with_charge: bool) -> int:
    """Premier round où l'unité peut finir entièrement en territoire ennemi (après charge si exigée)."""
    step = reach(unit) + RUN_MEAN
    last = reach(unit) + (CHARGE_MEAN if with_charge else RUN_MEAN)
    for r in range(1, 6):
        if (r - 1) * step + last >= TERRITORY_GAP:
            return r
    return 6


@dataclass(frozen=True)
class Trigger:
    """Facteur D : probabilité de remplir les conditions du porteur, à partir du round `start`."""

    p: float
    start: int = 1
    bearer_only: bool = True  # False : une condition ne dépend pas du porteur (reste « bon cas »)
    #: « a chargé » : l'effet ne joue qu'au combat du tour de charge, donc à MON tour. Sur la frise
    #: (`timeline`), forcer `turn_side="yours"` ; hors frise, multiplier par `CHARGE_FIGHT_SHARE`.
    charged: bool = False

    def turn_side(self, default: str) -> str:
        return "yours" if self.charged else default

    @property
    def p_off_timeline(self) -> float:
        """P sans frise : la part des combats d'une unité qui suivent sa charge en plus."""
        return self.p * (CHARGE_FIGHT_SHARE if self.charged else 1.0)


def trigger(
    unit: Unit, requires: str, conditions: str, share_melee: float, melee_effect: bool, kind: str = ""
) -> Trigger:
    """D pour un effet : `requires` = prérequis de l'effet, `conditions` = toutes ses conditions.

    Un « Charge (+N) » (`kind == "charge_bonus"`) n'existe que si l'unité a chargé, même sans
    prérequis écrit."""
    conds = [c for c in conditions.split(" | ") if c]
    if kind == "charge_bonus" and "a chargé" not in conds and "charge ennemie" not in conds:
        conds.append("a chargé")
    others = [c for c in conds if c not in BEARER_CONDITIONS and not c.startswith(ONCE_TRIGGER)]
    p, start = 1.0, 1
    for c in conds:
        if c.startswith(ONCE_TRIGGER):
            # v34 (Oath of Supremacy) : conditions réussies une fois, puis effet jusqu'à la fin de la bataille →
            # pas de probabilité par combat, seulement un round de départ (entrée en territoire ennemi, sinon
            # première charge réaliste au round 2)
            if "en territoire" in c:
                start = max(start, territory_round(unit, with_charge="charge" in c))
            else:
                start = max(start, ONCE_TRIGGER_START)
    charged = "a chargé" in conds or CHARGE_EITHER in conds
    melee_unit = share_melee >= 0.5
    if "en territoire" in conds:
        start = max(start, territory_round(unit, with_charge=charged))
    for c in conds:
        if c == "a chargé":
            p *= p_charge(unit, start)
        elif c == "sur objectif":
            p *= P_OBJECTIVE_HERO if unit.is_hero or unit.models < 3 else P_OBJECTIVE_TROOP
        elif c == "au combat":
            if not (melee_effect or charged):  # un buff de mêlée ne joue de toute façon qu'au combat
                p *= P_IN_COMBAT_MELEE if melee_unit else P_IN_COMBAT_SHOOTER
        elif c == "sans charge":
            p *= P_NOT_CHARGED_MELEE if melee_unit else P_NOT_CHARGED_SHOOTER
        elif c == "sans mouvement":
            p *= P_STILL_MELEE if melee_unit else P_STILL_SHOOTER
        elif c == "combat enchaîné":
            p *= CHAINED_FIGHT_SHARE
        elif c == OVERFLY:
            p *= p_overfly(unit)
    return Trigger(p=p, start=start, bearer_only=not others, charged=charged)


def _range_exposure(inches: float) -> str:
    if inches <= 3:
        return "contact"
    return "courte" if inches <= 9 else "longue"


def exposure_of(
    scope: str, range_inches: Optional[int], requires: str, family: str, shoot_range: Optional[float] = None
) -> str:
    """Exposition imposée au porteur pour tenir l'effet.

    v35 : un débuff posé par les tirs du porteur (`SHOT_BY_BEARER`) l'expose à la portée de sa plus longue
    arme de tir (`shoot_range`), pas au contact faute de portée écrite."""
    if "au combat" in requires or "a chargé" in requires or RETALIATION in requires:
        return "contact"
    if SHOT_BY_BEARER in requires and shoot_range:
        return _range_exposure(shoot_range)
    if range_inches is None:
        # une règle d'armée (The One True King : −1 charge aux ennemis) ne demande pas d'aller au contact
        return "contact" if family == "debuff" and scope != "army" else "longue"
    return _range_exposure(range_inches)


#: Nombre d'unités ennemies qui frappent le porteur à chaque round (choix utilisateur, 2026-11-20) :
#: 1 au round 1 (prise de contact), 2 aux rounds 2-3 (cœur de la bataille), 1 aux rounds 4-5.
ATTACKERS_PER_ROUND = (1, 2, 2, 1, 1)


def damage_per_round(melee_in: float, ranged_in: float, exposure: str) -> float:
    """Dégâts subis d'UNE unité ennemie moyenne en un round, à cette exposition."""
    km, kr = EXPOSURE[exposure]
    return km * melee_in + kr * ranged_in


def alive_profile(hp_total: float, dmg_one_unit: float, start: int = 1) -> list[float]:
    """Part de vie en jeu au début de chaque round 1..5 (1 = intact au round `start`, 0 = mort).

    Les dégâts s'accumulent à partir du round `start` (le porteur s'expose quand il agit), avec
    `ATTACKERS_PER_ROUND` unités ennemies par round. La part d'un round est la fraction du round
    vécue (mort en cours de round = fraction)."""
    out, taken = [], 0.0
    for r in range(1, 6):
        if r < start:
            out.append(1.0)
            continue
        d = dmg_one_unit * ATTACKERS_PER_ROUND[r - 1]
        left = hp_total - taken
        out.append(1.0 if d <= 0 else max(0.0, min(1.0, left / d)))
        taken += d
    return out


def rounds_alive(hp_total: float, melee_in: float, ranged_in: float, exposure: str, start: int = 1) -> float:
    """Rounds de survie attendus à partir de `start` (somme des parts de vie), sous la pression par étapes."""
    prof = alive_profile(hp_total, damage_per_round(melee_in, ranged_in, exposure), start)
    return sum(prof[start - 1 :]) if start <= 5 else 0.0


def survival_coverage(profile: list[float], start: int = 1, lasting: bool = True) -> float:
    """S : part (pondérée par round) des rounds `start`..5 où le porteur tient encore l'effet.

    `profile` = `alive_profile`. Effet court (`lasting=False`) : seul le round de déclenchement compte."""
    if start > 5:
        return 0.0
    rounds = range(start, 6) if lasting else range(start, start + 1)
    nominal = sum(ROUND_WEIGHTS[r - 1] for r in rounds)
    held = sum(ROUND_WEIGHTS[r - 1] * profile[r - 1] for r in rounds)
    return held / nominal if nominal else 0.0


def incoming_damage(con) -> dict[int, tuple[float, float]]:
    """unit_id → (dégâts de mêlée, dégâts de tir) subis par round d'une unité ennemie moyenne.

    `unit_benchmark.raw_b_to_a` = riposte du défenseur, lue à la moyenne (`defender_mode='mean'`),
    après sauvegarde/protection de l'unité ; répartie selon `unit_chassis.share_melee` du défenseur."""
    rows = con.execute(
        """SELECT b.attacker_id,
                  avg(b.raw_b_to_a * coalesce(c.share_melee, 1.0)),
                  avg(b.raw_b_to_a * (1 - coalesce(c.share_melee, 1.0)))
           FROM unit_benchmark b JOIN unit_chassis c ON c.unit_id = b.defender_id
           WHERE b.defender_mode = 'mean' AND b.attacker_mode = 'floor66'
             AND NOT b.attacker_reinforced AND NOT b.defender_reinforced
             AND NOT b.attacker_charged AND NOT b.defender_charged
           GROUP BY b.attacker_id"""
    ).fetchall()
    out = {uid: (m or 0.0, r or 0.0) for uid, m, r in rows}
    # Unités absentes du benchmark (héros hors `--include-heroes`, Scourge of Aqshy…) : estimées depuis
    # leurs PV effectifs (`unit_chassis.effective_wounds`, coups à porter) — dégâts subis ≈ PV × C / coups,
    # C et la part de mêlée étant les médianes des unités mesurées. Sans ça, l'absence de données passait
    # pour une immortalité (5 rounds de survie).
    chassis = con.execute("SELECT unit_id, health * models, effective_wounds FROM unit_chassis").fetchall()
    ratios, melee_shares = [], []
    for uid, hp, ew in chassis:
        if uid in out and hp and ew:
            m, r = out[uid]
            if m + r > 0:
                ratios.append((m + r) * ew / hp)
                melee_shares.append(m / (m + r))
    if ratios:
        c_hits = sorted(ratios)[len(ratios) // 2]
        sm = sorted(melee_shares)[len(melee_shares) // 2]
        for uid, hp, ew in chassis:
            if uid not in out and hp and ew:
                tot = hp * c_hits / ew
                out[uid] = (tot * sm, tot * (1 - sm))
    return out


# ----- table du mariage (aptitude de charte × porteur) ---------------------------------------------

#: « conditionnelle » (v19, effet d'état « While … ») : tient tant que l'état dure, donc tant que le porteur vit.
_LASTING_DURATIONS = {"bataille", "permanent", "conditionnelle"}
_LASTING_FREQUENCIES = {"passive"}


def _lasting(frequency: str, durations: set[str]) -> bool:
    """Le porteur doit-il rester en vie sur plusieurs rounds pour que l'aptitude rapporte ?

    Oui pour un passif, un effet durable, ET une aptitude réutilisable (chaque tour/phase) : il faut être
    vivant pour la rejouer. Non seulement pour une fois par bataille à effet court (joué au kairos)."""
    once = (frequency or "").startswith("once_per_battle")
    return not once or (frequency or "") in _LASTING_FREQUENCIES or bool(durations & _LASTING_DURATIONS)


# ----- grille par famille : tempo F, amplification A, rôle R -------------------------------------------
#
# Grille co-construite avec l'utilisateur (2026-11-21, « en avant » sur le brouillon) ; on commence par les
# buffs, les autres familles restent neutres (A = R = 1) — leurs critères proposés sont dans le README.
#
# * D × S restent des probabilités (« ça arrive ? ») ; F aussi (part de la fenêtre utile couverte) ;
# * A et R sont des « mieux / moins bien que d'habitude » : multiplicateurs bornés autour de 1
#   (`FACTOR_BOUNDS`), pas des probabilités — un seul facteur faible ne tue pas le mariage ;
# * F est RELATIF au châssis : la fréquence elle-même (1/bataille = 1/2…) est déjà pondérée en couche 1 et
#   dans `realized` ; F ne mesure que le décalage entre la fenêtre de l'effet et le moment où ce châssis agit
#   (un buff de mêlée « pour le reste du tour » ne couvre que la moitié des combats d'une unité qui riposte
#   aussi au tour adverse ; « jusqu'au prochain tour » les couvre tous) ;
# * R est un axe simple propre à la famille (pas les rôles de `listing.suggest_role`, qui restent couche 4).

#: Bornes des multiplicateurs A et R (choix de travail, à challenger).
FACTOR_BOUNDS = (0.5, 1.5)
#: Buffs : grille complète (A mesuré dans `ability_encounter`).
BUFF_FAMILIES = ("buff-perso-offensif", "buff-perso-defensif", "buff-donne")
#: Familles notées par la grille (les autres : A = R = F = 1). Dégâts directs (2026-11-22, réponses utilisateur) :
#: D × P(au combat) au contact, survol par l'allonge (`p_overfly`), riposte : contact + R = 0,5 + rang défensif,
#: BM sur ses attaques : exposition et R d'un buff offensif perso ; F et A neutres (effets immédiats).
#: Débuffs (2026-11-22, réponses utilisateur) :
#: D × P(au combat) au contact, F règle des buffs selon la polarité, R selon qui en profite ; A neutre
#: (débuffs non traduits par le moteur).
#: Soins (v36, réponses utilisateur du 2026-11-23) : soin sur soi exposé comme un buff perso, A = rounds de survie
#: gagnés (`heal_survival_gain`) ÷ gain médian, R règle du buff défensif ; soin/Rally donné : R règle des buffs
#: donnés, A neutre ; soin déclenché par le combat : D × P(au combat), cible à éliminer listée en « bon cas ».
#: Contrôle (v36, réponses utilisateur du 2026-11-23) : contrôle sur soi toujours au contact (un objectif tenu se fait
#: frapper), A = P(l'emporter sur une unité ennemie au hasard) gagnée ÷ gain médian, R = 0,5 + moyenne(rang du score
#: de contrôle, rang défensif) ; contrôle donné : R règle des buffs donnés, A neutre ; contrôle ennemi = débuff.
GRID_FAMILIES = (*BUFF_FAMILIES, "debuff", "degats-directs", "mobilite", "soin", "controle")
#: Polarité de la frise (`timeline.relevance`) par famille notée.
FAMILY_POLARITY = {"buff-perso-offensif": "off", "buff-perso-defensif": "def", "buff-donne": "autre"}
#: Durées courtes dont la fenêtre peut manquer une partie de ce que fait le châssis ; la durée « idéale » de
#: comparaison couvre le tour joué ET le tour suivant.
_SHORT_DURATIONS = {"tour", "phase", "action", "non précisée", ""}
_IDEAL_DURATION = "jusqu'au prochain tour"
#: Nombre minimal de mesures positives d'un même effet pour en tirer une médiane de référence (A).
MIN_REFERENCE_SAMPLES = 10


def _bound(x: float) -> float:
    lo, hi = FACTOR_BOUNDS
    return max(lo, min(hi, x))


_DEF_KINDS = {"ward", "damage_ignore", "negate_attack", "untargetable", "damage_redirect"}
_DEF_STATS = {"save", "ward", "health"}


#: Débuff des ATTAQUES ennemies : il nous protège (polarité « def » de la frise : 70 % des coups au tour adverse).
_DEBUFF_ENEMY_OFFENCE_KINDS = {"strike_last", "no_crit", "no_weapon_abilities"}
_ENEMY_OFFENCE_STATS = {"hit", "wound", "attacks", "damage", "rend"}
#: Débuff de la DÉFENSE ennemie : il sert nos attaques (polarité « off »).
_ENEMY_DEFENCE_STATS = {"save", "ward"}


def debuff_polarity(e_list: list[tuple]) -> str:
    """Polarité d'un débuff d'après ses effets de famille « debuff » (index 7 de `load_effects`).

    « def » = il affaiblit les attaques ennemies (il protège) ; « off » = il affaiblit leur défense (il sert nos
    coups) ; "" = ni l'un ni l'autre (ordres, contrôle, magie, mouvement) ou égalité → tempo et rôle neutres."""
    n_off = n_def = 0
    for e in e_list:
        if len(e) <= 7 or e[7] != "debuff":
            continue
        kind, wscope, stat = e[0], e[5], e[6]
        if kind in _DEBUFF_ENEMY_OFFENCE_KINDS or (kind == "stat_mod" and stat in _ENEMY_OFFENCE_STATS):
            n_def += 1
        elif kind == "no_buff" and wscope == "melee":  # Charge (+1 Damage) ennemi ignoré (Anticipated Strike)
            n_def += 1
        elif kind in ("no_ward", "no_buff") or (kind == "stat_mod" and stat in _ENEMY_DEFENCE_STATS):
            n_off += 1
    if n_def > n_off:
        return "def"
    return "off" if n_off > n_def else ""


def debuff_role_fit(polarity: str, exposure: str, prof: ChassisProfile) -> float:
    """R d'un débuff (réponse utilisateur, 2026-11-22) : au contact, il profite surtout au porteur.

    * débuff des attaques ennemies : c'est lui qu'elles frappent → 0,5 + rang défensif ;
    * débuff de la défense ennemie : ce sont ses coups qui en profitent → 0,5 + rang offensif ;
    * à distance (sorts à 12-18"…) ou autre effet : 1, le bénéficiaire se choisit dans la liste (couche 4)."""
    if exposure != "contact":
        return 1.0
    if polarity == "def" and prof.def_rank is not None:
        return _bound(0.5 + prof.def_rank)
    if polarity == "off" and prof.off_rank is not None:
        return _bound(0.5 + prof.off_rank)
    return 1.0


#: Conditions qui disent déjà comment le porteur arrive au combat (D × P(au combat) ne s'y ajoute pas).
_ENGAGED_CONDITIONS = ("a chargé", "au combat", CHARGE_EITHER, "charge ennemie", SHOT_BY_BEARER, OVERFLY)
#: Familles dont un effet « une unité ennemie au combat avec cette unité » exige d'être au combat.
_CONTACT_FAMILIES = ("debuff", "degats-directs")


def direct_damage_role_fit(requires: str, prof: ChassisProfile) -> float:
    """R d'un dégât direct (réponses utilisateur, 2026-11-22) : une riposte vaut par la durabilité du porteur
    (0,5 + rang défensif : une enclume riposte plus souvent), des BM sur ses attaques par son offense (0,5 + rang
    offensif, comme un buff offensif perso) ; sinon 1."""
    if RETALIATION in requires and prof.def_rank is not None:
        return _bound(0.5 + prof.def_rank)
    if ON_OWN_ATTACKS in requires and prof.off_rank is not None:
        return _bound(0.5 + prof.off_rank)
    return 1.0


# ----- mobilité (2026-11-23, réponses utilisateur, toutes = propositions) ----------------------------------
#
# Mobilité du porteur lui-même : exposition d'un buff perso (il va là où il se bat), puis selon le sous-type —
# * engagement / repositionnement (aide à la charge, réserve, téléportation, mouvement en plus) : R = 0,5 + rang
#   offensif (« ce que fait le châssis en arrivant ») ; A = gain relatif — P(charge) gagnée sur ce châssis ÷ la
#   médiane de la même aide sur tous les châssis, sinon allonge médiane ÷ allonge du porteur (un lent gagne plus) ;
# * dégagement (retraite, bouger après avoir tiré, se retirer après avoir chargé) : R = 0,5 + max(rang offensif,
#   1 − rang défensif) — il recharge (marteau) ou il survit (fragile) ; A neutre.
# Mobilité donnée : règle des buffs donnés (le porteur suit ses receveurs), sauf au déploiement ; A neutre.
# F neutre (un mouvement est instantané).

MOBILITY_ENGAGE, MOBILITY_DISENGAGE, MOBILITY_REPOSITION = "engagement", "dégagement", "repositionnement"
_DISENGAGE_KINDS = {"free_retreat", "run_and_shoot"}
_DISENGAGE_TEXT = re.compile(
    r"cannot (?:end (?:that|the) move in combat|move into combat)|"
    r"\buse (?:a|the) (?:RETREAT|'Retreat') ability|'Retreat' ability as if",
    re.I,
)
_ENGAGE_TEXT = re.compile(
    r"must end (?:that|the) (?:charge )?move (?:in combat|within (?:½|1/2|1)\")|can (?:move|end that move) into combat|"
    r"\bin combat with (?:the target|that enemy unit)\b|\bthis unit has charged\b|can be set up in combat|"
    r"set (?:it|this unit) up again within 1\" of the target",
    re.I,
)
_AFTER_KILL = re.compile(r"\bmodels? (?:were|was) slain (?:this turn )?by this unit", re.I)
_MOVE_KINDS = {"move", "redeploy", "deep_strike", "extra_move", "fly", "pile_in"}


def _charge_aid(e_list: list[tuple]) -> Optional[tuple[float, bool, str]]:
    """(bonus, relance complète, mode de dés) d'une aide à la charge lue dans les effets, sinon None.

    Index 0 kind, 6 stat, 8 value, 9 detail (`load_effects`). « Course + charge » = la course (`RUN_MEAN`) en bonus."""
    bonus, reroll, dice = 0.0, False, "2d6"
    for e in e_list:
        kind, stat = e[0], e[6]
        value = e[8] if len(e) > 8 else 0.0
        detail = e[9] if len(e) > 9 else ""
        if kind == "stat_mod" and stat == "charge" and value > 0:
            bonus += value
        elif kind == "dice_count" and stat == "charge" and value > 0:
            dice = {"somme": "3d6", "garder": "3k2", "max": "max"}.get(detail, "3d6")
        elif kind == "reroll" and stat == "charge" and value >= 1:
            reroll = True
        elif kind == "run_and_charge":
            bonus += RUN_MEAN
    return (bonus, reroll, dice) if bonus or reroll or dice != "2d6" else None


def mobility_kind(e_list: list[tuple], text: str = "") -> str:
    """Sous-type d'une mobilité : engagement, dégagement ou repositionnement (effets + texte de l'aptitude)."""
    kinds = {e[0] for e in e_list}
    if _charge_aid(e_list) or "pile_in" in kinds:
        return MOBILITY_ENGAGE
    details = " ".join(e[9] for e in e_list if len(e) > 9 and e[9])
    if kinds & _DISENGAGE_KINDS or "RETREAT" in details.upper() or _DISENGAGE_TEXT.search(text):
        return MOBILITY_DISENGAGE
    if _ENGAGE_TEXT.search(text) or any("au combat" in e[1] for e in e_list):
        return MOBILITY_ENGAGE
    # bouger / se téléporter après avoir chargé ou tué (Strike and Fade, Sudden Translocation) : frapper et partir
    if kinds & _MOVE_KINDS and (any("a chargé" in e[1] for e in e_list) or _AFTER_KILL.search(text)):
        return MOBILITY_DISENGAGE
    return MOBILITY_REPOSITION


def charge_gain(unit: Unit, aid: tuple[float, bool, str]) -> float:
    """Gain de P(charge) qu'apporte l'aide sur ce châssis, moyenne pondérée des rounds (écart 18" puis 14")."""
    from .assault import p_roll

    bonus, reroll, dice = aid
    tot = 0.0
    for r in range(1, 6):
        need = (ENGAGE_GAP_ROUND1 if r == 1 else ENGAGE_GAP) - reach(unit)
        tot += ROUND_WEIGHTS[r - 1] * (p_roll(need, bonus, reroll, dice) - p_roll(need))
    return tot / sum(ROUND_WEIGHTS)


@dataclass
class MobilityReference:
    """Références du gain relatif A : allonge médiane des châssis ; gain médian de P(charge) des porteurs d'une aide
    à la charge (`charge_reference`, toutes aides confondues, +12 points en 2026-27 : règle présentée à l'utilisateur
    et validée le 2026-11-23). Sans elle, repli sur la médiane de la même aide sur tous les châssis."""

    units: list[Unit]
    median_reach: float = 8.0
    charge_reference: Optional[float] = None
    _charge: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        reaches = sorted(reach(u) for u in self.units)
        if reaches:
            self.median_reach = reaches[len(reaches) // 2]
        self._charge = {}

    def charge_median(self, aid: tuple[float, bool, str]) -> float:
        if self.charge_reference:
            return self.charge_reference
        if aid not in self._charge:
            gains = sorted(g for g in (charge_gain(u, aid) for u in self.units) if g > 0)
            self._charge[aid] = gains[len(gains) // 2] if gains else 0.0
        return self._charge[aid]


def bearer_charge_reference(con, units: dict, effs: dict[str, list[tuple]]) -> Optional[float]:
    """Gain médian (> 0) de P(charge) sur leurs porteurs des aptitudes de charte de mobilité qui aident la charge."""
    gains = []
    for fac, owner, uid in con.execute(
        """SELECT DISTINCT o.faction_name, lower(o.owner_name), a.uid
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           WHERE o.owner_kind = 'warscroll' AND a.family = 'mobilite'"""
    ).fetchall():
        u, aid = units.get((fac, owner)), _charge_aid(effs.get(uid, []))
        if u is not None and aid:
            g = charge_gain(u, aid)
            if g > 0:
                gains.append(g)
    gains.sort()
    return gains[len(gains) // 2] if gains else None


def mobility_amplification(unit: Unit, e_list: list[tuple], kind: str, ref: MobilityReference) -> Optional[float]:
    """A brut d'une mobilité perso (None = neutre : dégagement, référence absente)."""
    if kind == MOBILITY_DISENGAGE:
        return None
    aid = _charge_aid(e_list)
    if aid:
        med = ref.charge_median(aid)
        return charge_gain(unit, aid) / med if med > 0 else None
    r = reach(unit)
    return ref.median_reach / r if r > 0 else None


def mobility_role_fit(kind: str, prof: ChassisProfile) -> float:
    """R d'une mobilité perso : 0,5 + rang offensif ; dégagement : 0,5 + max(rang off., 1 − rang déf.)."""
    if prof.off_rank is None:
        return 1.0
    if kind == MOBILITY_DISENGAGE and prof.def_rank is not None:
        return _bound(0.5 + max(prof.off_rank, 1.0 - prof.def_rank))
    return _bound(0.5 + prof.off_rank)


#: Prérequis qui imposent déjà le contact (`exposure_of`).
_CONTACT_REQS = ("au combat", "a chargé", RETALIATION)


def _personal_mobility(scope: str, rng: Optional[int]) -> bool:
    """Mobilité du porteur lui-même (pas donnée à une autre unité) ; une cible ennemie est sa destination
    (Drawn By Blood, Terminate Their Command : se poser au contact d'un héros ennemi)."""
    return scope in ("self", "one_enemy", "enemy_aura", "all_enemies") or (scope == "unknown" and rng is None)


# ----- soins (v36) -------------------------------------------------------------------------------------------

_HEAL_KINDS = ("heal", "return_models")


def _self_heal(scope: str, rng: Optional[int]) -> bool:
    """Soin du porteur lui-même (pas donné à une autre unité)."""
    return scope == "self" or (scope == "unknown" and rng is None)


def heal_points(unit: Unit, e_list: list[tuple]) -> Optional[float]:
    """Points de vie rendus par usage sur CE châssis (meilleure option), None si non chiffré (« Heal (X) »).

    Règle de jeu : un soin ne retire que les dégâts de la figurine entamée — nul sur des figurines à 1 PV,
    plafonné à PV − 1 sur une unité de plusieurs figurines ; un retour de figurines vaut N × PV de la
    figurine, nul sur une figurine unique (une unité détruite ne revient pas)."""
    best: Optional[float] = None
    for e in e_list:
        if e[0] not in _HEAL_KINDS or not e[8] or e[9] == "bonus aux soins":
            continue
        if e[0] == "heal":
            v = e[8] if unit.models == 1 else (0.0 if unit.health <= 1 else min(e[8], unit.health - 1))
        else:
            v = 0.0 if unit.models == 1 else e[8] * unit.health
        best = v if best is None else max(best, v)
    return best


def heal_uses_per_round(frequency: str, turn_side: str) -> Optional[int]:
    """Usages par round : 2 pour « chaque tour » (fin/début de chaque tour, chaque phase des héros), 1 pour son seul
    tour ou un passif ; None pour une fois par bataille (jouée une fois, au round 2)."""
    if (frequency or "").startswith("once_per_battle"):
        return None
    if (frequency or "") == "passive":
        return 1
    return 2 if (turn_side or "any") == "any" else 1


def _rounds_alive_healed(hp: float, dmg: float, heal_per_round: float, once: bool = False) -> float:
    """Rounds de survie (`alive_profile`) quand le porteur se soigne de `heal_per_round` après chaque round
    survécu (une seule fois, au round 2, si `once`), sans jamais retirer plus que les dégâts subis."""
    taken, total = 0.0, 0.0
    for r in range(1, 6):
        d = dmg * ATTACKERS_PER_ROUND[r - 1]
        left = hp - taken
        total += 1.0 if d <= 0 else max(0.0, min(1.0, left / d))
        taken += d
        if taken >= hp:
            break
        if not once or r == 2:
            taken = max(0.0, taken - heal_per_round)
    return total


def heal_survival_gain(
    unit: Unit, e_list: list[tuple], frequency: str, turn_side: str, incoming: tuple[float, float], exposure: str
) -> Optional[float]:
    """Gain relatif de rounds de survie qu'apporte le soin sur soi (0 = rien, 1 = deux fois plus de rounds),
    sous la même pression que S (`damage_per_round`, `ATTACKERS_PER_ROUND`) ; None si non chiffré."""
    pts = heal_points(unit, e_list)
    if pts is None:
        return None
    uses = heal_uses_per_round(frequency, turn_side)
    hp = unit.health * unit.models
    dmg = damage_per_round(incoming[0], incoming[1], exposure)
    base = _rounds_alive_healed(hp, dmg, 0.0)
    if base <= 0:
        return 0.0
    return _rounds_alive_healed(hp, dmg, pts * (uses or 1), once=uses is None) / base - 1.0


def positive_median(gains: list[float]) -> Optional[float]:
    """Médiane des gains strictement positifs : la référence de A (soins sur soi, contrôle sur soi)."""
    pos = sorted(g for g in gains if g and g > 0)
    if not pos:
        return None
    n = len(pos)
    return pos[n // 2] if n % 2 else (pos[n // 2 - 1] + pos[n // 2]) / 2


# ----- contrôle (v36) -----------------------------------------------------------------------------------------

_GIVEN_SCOPES = ("one_friendly", "friendly_aura", "army")


def _personal_control(scope: str) -> bool:
    """Contrôle du porteur lui-même (pas donné) ; « For each enemy unit … this unit gains » (Annelid Engorgement,
    lu `all_enemies`) reste personnel."""
    return scope not in (*_GIVEN_SCOPES, "battlefield")  # « You control the target objective » : aucune unité ne tient


def control_bonus(e_list: list[tuple]) -> Optional[float]:
    """Bonus de score de contrôle ami (meilleure option), None si non chiffré."""
    vals = [e[8] for e in e_list if e[0] == "stat_mod" and e[6] == "control" and e[8] and e[8] > 0]
    return max(vals) if vals else None


@dataclass
class ControlReference:
    """Scores de contrôle (figurines × Contrôle) de toutes les chartes : l'unité ennemie « au hasard » sur un
    objectif, et la référence de A (gain médian des contrôles sur soi)."""

    scores: list[float]
    gain_median: Optional[float] = None

    def __post_init__(self) -> None:
        self.scores = sorted(self.scores)

    def p_win(self, score: float) -> float:
        """P(score > celui d'une charte au hasard), égalité à moitié ; c'est aussi le rang centile du score."""
        import bisect

        if not self.scores:
            return 0.5
        lo, hi = bisect.bisect_left(self.scores, score), bisect.bisect_right(self.scores, score)
        return (lo + 0.5 * (hi - lo)) / len(self.scores)

    def gain(self, unit: Unit, bonus: float) -> float:
        base = unit.models * unit.control
        return self.p_win(base + bonus) - self.p_win(base)


def control_role_fit(unit: Unit, prof: ChassisProfile, ref: ControlReference) -> float:
    """R (réponse utilisateur) : tenir = nombre et durée → 0,5 + moyenne(rang du score de contrôle, rang défensif)."""
    rank = ref.p_win(unit.models * unit.control)
    return _bound(0.5 + (rank + (prof.def_rank if prof.def_rank is not None else 0.5)) / 2)


def p_in_combat(share_melee: float) -> float:
    """P(le porteur est au combat) quand l'effet l'exige : mêmes constantes que les buffs « au combat »
    (réponse utilisateur 2026-11-22 pour les débuffs « une unité ennemie au combat avec cette unité »)."""
    return P_IN_COMBAT_MELEE if share_melee >= 0.5 else P_IN_COMBAT_SHOOTER


def shoot_range(u: Unit) -> Optional[float]:
    """Portée de la plus longue arme de tir du porteur (None sans arme de tir)."""
    return max((w.range_in for w in u.weapons if w.kind == "ranged"), default=None)


def effect_timing(family: str, e_list: list[tuple], bearer_share_melee: float) -> tuple[str, float]:
    """(polarité, part de mêlée) qui fixent les demi-tours utiles d'un effet (`timeline.relevance`).

    Buff perso : la famille donne la polarité, le porteur sa part de mêlée. Buff donné : lu dans les effets
    (une protection sert surtout au tour adverse, un buff de tir à mon seul tour) ; les armes visées
    (`weapon_scope`) fixent la part de mêlée — tir → 0, mêlée → 1, sinon celle du porteur."""
    pol = FAMILY_POLARITY.get(family, "autre")
    if family in ("degats-directs", "mobilite", "soin", "controle"):
        return "", bearer_share_melee  # effet immédiat : pas de fenêtre à couvrir, F = 1
    if family == "debuff":
        dpol = debuff_polarity(e_list)
        scopes = {e[5] for e in e_list if len(e) > 7 and e[7] == "debuff" and e[5]}
        if dpol == "off" and scopes <= {"melee"} and scopes:
            return dpol, 1.0
        return dpol, bearer_share_melee
    if family == "buff-donne" and e_list:
        n_def = sum(1 for e in e_list if e[0] in _DEF_KINDS or (len(e) > 6 and e[6] in _DEF_STATS))
        pol = "def" if 2 * n_def > len(e_list) else "off"
    scopes = {e[5] for e in e_list if e[5]}
    if scopes == {"ranged"}:
        return pol, 0.0
    if scopes == {"melee"}:
        return pol, 1.0
    return pol, bearer_share_melee


def tempo(family: str, frequency: str, duration: str, turn_side: str, share_melee: float, polarity: str = "") -> float:
    """F : part de la fenêtre utile du châssis que couvre l'effet, à fréquence égale (0-1, 1 = rien ne manque).

    = couverture de la frise avec la durée écrite / couverture avec une durée « jusqu'au prochain tour »,
    même fréquence, même tour joué, pertinence lue avec la polarité et la part de mêlée (`effect_timing`)."""
    from .timeline import coverage

    pol = polarity or FAMILY_POLARITY.get(family)
    if family not in GRID_FAMILIES or pol is None or (frequency or "") == "passive" or duration not in _SHORT_DURATIONS:
        return 1.0
    side = turn_side or "any"
    ideal = coverage(frequency or "", _IDEAL_DURATION, side, pol, share_melee)
    if ideal <= 0:
        return 1.0
    return min(1.0, coverage(frequency or "", duration, side, pol, share_melee) / ideal)


def amplification_ratios(con) -> dict[tuple[int, str], float]:
    """(unit_id, ability_uid) → A brut : gain de l'aptitude sur son porteur / gain médian des mêmes effets.

    Lu dans `ability_encounter` (relation « porteur »). Un « même effet » = même (kind, stat, value,
    weapon_scope) ; sa médiane de référence porte sur toutes les mesures positives (porteurs et alliés), dès
    `MIN_REFERENCE_SAMPLES`. Gain offensif pour un buff offensif, défensif pour un buff défensif. Les effets
    non traduits (pas de ligne) n'entrent pas : l'aptitude reste neutre (absente du dict)."""
    rows = con.execute(
        """SELECT DISTINCT en.ability_uid, en.seq, en.unit_id, en.relation, en.off_gain_pct, en.def_gain_pct,
                  e.kind, coalesce(e.stat, ''), coalesce(e.value, 0), coalesce(e.weapon_scope, ''), a.family
           FROM ability_encounter en
           JOIN ability_effect e ON e.ability_uid = en.ability_uid AND e.seq = en.seq
           JOIN ability a ON a.uid = en.ability_uid"""
    ).fetchall()
    samples: dict[tuple, dict[str, list[float]]] = {}
    for _uid, _seq, _unit, _rel, og, dg, *sig, _fam in rows:
        d = samples.setdefault(tuple(sig), {"off": [], "def": []})
        if og and og > 0:
            d["off"].append(og)
        if dg and dg > 0:
            d["def"].append(dg)
    ref: dict[tuple[tuple, str], float] = {}
    for sig, d in samples.items():
        for pol, vals in d.items():
            if len(vals) >= MIN_REFERENCE_SAMPLES:
                vals.sort()
                n = len(vals)
                ref[(sig, pol)] = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    here: dict[tuple[int, str], list[float]] = {}
    for uid, _seq, unit_id, rel, og, dg, *sig, fam in rows:
        pol = FAMILY_POLARITY.get(fam or "")
        if rel != "porteur" or pol not in ("off", "def"):
            continue
        r = ref.get((tuple(sig), pol))
        if r is None:
            continue
        acc = here.setdefault((unit_id, uid), [0.0, 0.0])
        acc[0] += (og if pol == "off" else dg) or 0.0
        acc[1] += r
    return {k: g / r for k, (g, r) in here.items() if r > 0}


def receiver_reach(con) -> dict[str, float]:
    """ability_uid → allonge médiane (`unit_realized.reach_in`) des receveurs alliés de l'aptitude."""
    return dict(
        con.execute(
            """SELECT en.ability_uid, median(r.reach_in)
               FROM (SELECT DISTINCT ability_uid, unit_id FROM ability_encounter WHERE relation = 'allié') en
               JOIN unit_realized r ON r.unit_id = en.unit_id
               WHERE r.reach_in IS NOT NULL GROUP BY 1"""
        ).fetchall()
    )


def mobility_receiver_reach(con, family: str = "mobilite") -> dict[str, float]:
    """ability_uid → allonge médiane (`unit_realized.reach_in`) des receveurs alliés d'une mobilité donnée.

    Les mobilités (et les soins, `family="soin"`, v36) ne sont pas traduites par le moteur (pas de ligne
    `ability_encounter`) : receveurs relus avec
    `encounter.receivers` (restriction de cible amie de l'aptitude)."""
    from ...persistence import repository
    from .encounter import receivers

    by_faction = {
        army: [u for u in us if u.points > 0] for army, us in _units_by_army_name(con, repository).items()
    }
    vocab = frozenset(k for us in by_faction.values() for u in us for k in u.keywords)
    reach_in = dict(con.execute("SELECT unit_id, reach_in FROM unit_realized WHERE reach_in IS NOT NULL").fetchall())
    out: dict[str, float] = {}
    for uid, source_kind, scope, ftarget, excl, owner, faction in con.execute(
        """SELECT DISTINCT a.uid, a.source_kind, a.scope, coalesce(a.friendly_target, ''), a.excludes_self,
                  o.owner_name, o.faction_name
           FROM ability a JOIN ability_owner o ON o.ability_uid = a.uid
           WHERE a.family = ? AND a.scope IN ('one_friendly', 'friendly_aura', 'army')
             AND o.owner_kind = 'warscroll'""",
        [family],
    ).fetchall():
        rc = receivers(source_kind, scope, "warscroll", owner, by_faction.get(faction, []), ftarget, vocab, bool(excl))
        vals = sorted(reach_in[u.id] for u, rel in rc if rel == "allié" and u.id in reach_in)
        if vals:
            n = len(vals)
            out[uid] = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return out


@dataclass(frozen=True)
class ChassisProfile:
    """Ce que la grille lit du porteur : rangs centiles couche 3, part de mêlée, allonge."""

    off_rank: Optional[float] = None
    def_rank: Optional[float] = None
    share_melee: float = 1.0
    reach: Optional[float] = None


def chassis_profiles(con) -> dict[int, ChassisProfile]:
    sm = share_melee_by_unit(con)
    return {
        uid: ChassisProfile(off, dfn, sm.get(uid, 1.0), reach)
        for uid, off, dfn, reach in con.execute(
            "SELECT unit_id, off_pct_rank, def_pct_rank, reach_in FROM unit_realized"
        ).fetchall()
    }


def role_fit(family: str, prof: ChassisProfile, receivers_reach: Optional[float] = None) -> float:
    """R : l'aptitude colle-t-elle au rôle du porteur ? (multiplicateur borné, 1 = neutre)

    * buff offensif : 0,5 + rang offensif — un buff offensif sur un marteau, pas sur une unité qui frappe peu
      (+100 % d'un petit chiffre reste petit : A est relatif, R donne le poids absolu) ;
    * buff défensif : 0,5 + moyenne(rang défensif, part de mêlée) — une unité faite pour encaisser, ou qui va
      au contact, s'en sert ; une artillerie restée derrière un écran beaucoup moins ;
    * buff donné : le porteur **suit-il ses receveurs** ? min(1, allonge du porteur / allonge médiane des
      receveurs) — un héros à 5" qui doit tenir une bulle sur de la cavalerie la perd (jamais un bonus) ;
    * autres familles : 1."""
    if family == "buff-perso-offensif" and prof.off_rank is not None:
        return _bound(0.5 + prof.off_rank)
    if family == "buff-perso-defensif" and prof.def_rank is not None:
        return _bound(0.5 + (prof.def_rank + min(max(prof.share_melee, 0.0), 1.0)) / 2)
    if family in ("buff-donne", "mobilite", "soin", "controle") and prof.reach and receivers_reach:
        # mobilité donnée (v36, réponse utilisateur) : même règle ; la mobilité perso est jugée dans `marriage_of`
        return _bound(min(1.0, prof.reach / receivers_reach))
    return 1.0


@dataclass(frozen=True)
class Marriage:
    exposure: str
    p_trigger: float
    start_round: int
    bearer_only: bool
    rounds_alive: float
    survival: float
    marriage: float  # D × S × F × A × R
    others: tuple[str, ...]
    tempo: float = 1.0  # F
    amplification: float = 1.0  # A (borné)
    role_fit: float = 1.0  # R (borné)
    bearing: float = 0.0  # D × S : le porteur déclenche et tient l'effet (sans la grille)


def load_effects(con) -> dict[str, list[tuple]]:
    """ability_uid → [(kind, requires, target_condition, target_keywords, duration, weapon_scope, stat, family,
    value, detail)] (value et detail : v36, aides à la charge de la grille mobilité)."""
    effs: dict[str, list[tuple]] = {}
    for uid, kind, req, tcond, tkw, dur, wscope, stat, fam, value, detail in con.execute(
        "SELECT ability_uid, kind, requires, target_condition, target_keywords, duration, weapon_scope, stat, family, "
        "value, detail FROM ability_effect"
    ).fetchall():
        effs.setdefault(uid, []).append(
            (
                kind,
                req or "",
                tcond or "",
                tkw or "",
                dur or "",
                wscope or "",
                stat or "",
                fam or "",
                value or 0.0,
                detail or "",
            )
        )
    return effs


def marriage_of(
    u: Unit,
    e_list: list[tuple],
    family: str,
    scope: str,
    rng: Optional[int],
    freq: str,
    share_melee: float,
    incoming: tuple[float, float],
    turn_side: str = "any",
    amplification: Optional[float] = None,
    role: float = 1.0,
    chassis_profile: Optional[ChassisProfile] = None,
    text: str = "",
    mobility_ref: Optional[MobilityReference] = None,
    heal_ref: Optional[float] = None,
    control_ref: Optional[ControlReference] = None,
) -> Marriage:
    """Mariage d'une aptitude (ses effets `load_effects`) portée par `u` : D × S × F × A × R.

    `amplification` = A brut (`amplification_ratios`, None = non mesuré → neutre), `role` = R (`role_fit`).
    Débuff : R est calculé ici (`debuff_role_fit`, il dépend de l'exposition et de la polarité) depuis
    `chassis_profile` ; sans profil, R = 1."""
    from .timeline import start_share

    reqs = " | ".join(dict.fromkeys(r for e in e_list for r in e[1].split(" | ") if r))
    conds = [c for e in e_list for c in (e[1].split(" | ") + e[2].split(" | ")) if c]
    conds += [f"vs {e[3]}" for e in e_list if e[3]]
    conds = list(dict.fromkeys(conds))
    kinds = {e[0] for e in e_list}
    # « au combat » n'est gratuit que pour un effet sur les armes de mêlée ; sans aucune portée d'arme (Share The
    # Pain, « If this unit is in combat, it can move 3" ») il se paie P(au combat) — all() vide valait vrai (v36)
    scoped = [e for e in e_list if e[5]]
    # v36 : un soin « après ses attaques de mêlée » ne vaut pas buff de mêlée : se battre se paie (P(au combat))
    melee = bool(scoped) and all(e[5] == "melee" for e in scoped) and family != "soin"
    t = trigger(
        u,
        reqs,
        " | ".join(conds),
        share_melee,
        melee_effect=melee,
        kind="charge_bonus" if "charge_bonus" in kinds else "",
    )
    fam = family or "autre"
    if (
        fam in ("buff-perso-offensif", "buff-perso-defensif")
        or (fam == "degats-directs" and ON_OWN_ATTACKS in reqs)
        or (fam == "mobilite" and _personal_mobility(scope, rng) and not any(c in reqs for c in _CONTACT_REQS))
        or (fam == "soin" and _self_heal(scope, rng) and not any(c in reqs for c in _CONTACT_REQS))
    ):
        # mobilité du porteur lui-même (dés de charge, réserve, téléportation…) : il s'expose là où il va se battre,
        # comme pour un buff perso — au contact pour une unité de mêlée, derrière un écran pour un tireur
        expo = "contact" if share_melee >= 0.5 else "longue"
    elif (
        fam == "soin"
        and scope in ("one_friendly", "friendly_aura")
        and rng is not None
        and rng <= 3
        and not any(c in reqs for c in _CONTACT_REQS)
    ):
        # v36 : soigner une unité AMIE au contact (Mobile Repairs : « within this unit's combat range ») colle le
        # porteur à son allié, pas à l'ennemi
        expo = "courte"
    elif fam == "controle" and _personal_control(scope or ""):
        expo = "contact"  # v36 (réponse utilisateur) : un objectif tenu se fait toujours frapper
    else:
        expo = exposure_of(scope or "", rng, reqs, fam, shoot_range(u))
    m_in, r_in = incoming
    lasting = _lasting(freq, {e[4] for e in e_list})
    # une fois par bataille courte : jouée au kairos (round 2 au plus tôt, cf. realized.py)
    use = t.start if lasting else max(t.start, 2)
    hp = u.health * u.models
    profile = alive_profile(hp, damage_per_round(m_in, r_in, expo), start=t.start)
    alive = rounds_alive(hp, m_in, r_in, expo, start=t.start)
    surv = survival_coverage(profile, use, lasting=lasting)
    dur = next((e[4] for e in e_list if e[4]), "permanent" if lasting else "")
    d = t.p_off_timeline * start_share(freq or "", dur, turn_side or "any", t.start)
    p_trig = t.p
    contact_target = rng is not None and rng <= 3
    if fam == "degats-directs" and RETALIATION in reqs:
        contact_target = True  # riposte : il faut se faire frapper au combat
    if fam in _CONTACT_FAMILIES and contact_target and not any(c in conds for c in _ENGAGED_CONDITIONS):
        # débuff « une unité ennemie au combat avec cette unité » : ne sert que si le porteur est au combat
        d *= p_in_combat(share_melee)
        p_trig *= p_in_combat(share_melee)
    pol, sm_t = effect_timing(fam, e_list, share_melee)
    f = tempo(fam, freq or "", dur, turn_side or "any", sm_t, pol)
    a = _bound(amplification) if amplification is not None and fam in BUFF_FAMILIES else 1.0
    if fam == "mobilite" and _personal_mobility(scope or "", rng):
        mkind = mobility_kind(e_list, text)
        raw = mobility_amplification(u, e_list, mkind, mobility_ref) if mobility_ref is not None else None
        a = _bound(raw) if raw is not None else 1.0
        r = mobility_role_fit(mkind, chassis_profile) if chassis_profile is not None else 1.0
    elif fam == "soin" and _self_heal(scope or "", rng):
        gain = heal_survival_gain(u, e_list, freq or "", turn_side or "any", incoming, expo)
        a = _bound(gain / heal_ref) if gain is not None and heal_ref else 1.0
        r = role_fit("buff-perso-defensif", chassis_profile) if chassis_profile is not None else 1.0
    elif fam == "controle" and _personal_control(scope or "") and control_ref is not None:
        bonus = control_bonus(e_list)
        g = control_ref.gain(u, bonus) if bonus is not None else None
        a = _bound(g / control_ref.gain_median) if g is not None and control_ref.gain_median else 1.0
        r = control_role_fit(u, chassis_profile or ChassisProfile(), control_ref)
    elif fam == "debuff":
        r = debuff_role_fit(pol, expo, chassis_profile) if chassis_profile is not None else 1.0
    elif fam == "degats-directs":
        r = direct_damage_role_fit(reqs, chassis_profile) if chassis_profile is not None else 1.0
    else:
        r = role if fam in GRID_FAMILIES else 1.0
    return Marriage(
        expo,
        p_trig,
        t.start,
        t.bearer_only,
        alive,
        surv,
        d * surv * f * a * r,
        tuple(c for c in conds if c not in BEARER_CONDITIONS),
        tempo=f,
        amplification=a,
        role_fit=r,
        bearing=d * surv,
    )


def build_marriage_rows(con) -> list[tuple]:
    """Tuples `persistence.analysis_tables.MARRIAGE_COLS` : chaque aptitude de charte jugée sur le châssis
    de chacun de ses porteurs.

    mariage = D (P(conditions du porteur) × part des rounds encore possibles) × S (rounds tenus / rounds
    nominaux) × F (tempo) × A (amplification) × R (rôle) — grille par famille ci-dessus. Les conditions
    tenues par d'autres (allié, adversaire, ressource) ne sont pas chiffrées : elles sont listées
    (`good_case_conditions`) et relèvent de la couche 4 / des matchups."""
    from ...persistence import repository

    units = {
        (army, u.name.lower()): u
        for army, us in _units_by_army_name(con, repository).items()
        for u in us
        if u.points > 0
    }
    chassis = share_melee_by_unit(con)
    incoming = incoming_damage(con)
    effs = load_effects(con)
    amps = amplification_ratios(con)
    profiles = chassis_profiles(con)
    recv = receiver_reach(con)
    recv.update(mobility_receiver_reach(con))
    recv.update(mobility_receiver_reach(con, family="soin"))
    recv.update(mobility_receiver_reach(con, family="controle"))
    ctl_ref = ControlReference([u.models * u.control for u in units.values()])
    mob_ref = MobilityReference(list(units.values()))
    mob_ref.charge_reference = bearer_charge_reference(con, units, effs)
    abil = con.execute(
        """SELECT o.faction_name, lower(o.owner_name), a.uid, a.name, a.family, a.power, a.verdict, a.scope,
                  a.range_inches, a.frequency, a.turn_side,
                  coalesce(a.declare_text, '') || ' ' || coalesce(a.effect_text, '')
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           WHERE o.owner_kind = 'warscroll' AND a.source_kind NOT IN ('manifestation')"""
    ).fetchall()
    rows: list[tuple] = []
    seen: set[tuple[int, str]] = set()
    calls = []
    for fac, owner, uid, name, family, power, verdict, scope, rng, freq, tside, text in abil:
        u = units.get((fac, owner))
        if u is None or (u.id, uid) in seen:
            continue
        seen.add((u.id, uid))
        fam = family or "autre"
        prof = profiles.get(u.id, ChassisProfile(share_melee=chassis.get(u.id, 1.0)))
        args = (
            u,
            effs.get(uid, []),
            family or "autre",
            scope or "",
            rng,
            freq or "",
            chassis.get(u.id, 1.0),
            incoming.get(u.id, (0.0, 0.0)),
            tside or "any",
        )
        kw = dict(
            amplification=amps.get((u.id, uid)),
            # mobilité donnée posée au déploiement (réserve, transport) : le porteur n'a pas à suivre (v36)
            role=role_fit(fam, prof, None if fam == "mobilite" and tside == "deployment" else recv.get(uid)),
            chassis_profile=prof,
            text=text,
            mobility_ref=mob_ref,
        )
        calls.append((uid, name, family, power, verdict, args, kw))
    # v36 : référence de A des soins sur soi = gain de survie médian des soins sur leurs porteurs
    heal_gains = []
    for _uid, _n, family, _p, _v, args, kw in calls:
        if family == "soin" and _self_heal(args[3], args[4]):
            expo = marriage_of(*args, **kw).exposure
            heal_gains.append(heal_survival_gain(args[0], args[1], args[5], args[8], args[7], expo))
    heal_ref = positive_median([g for g in heal_gains if g is not None])
    ctl_gains = [
        ctl_ref.gain(args[0], b)
        for _uid, _n, family, _p, _v, args, _kw in calls
        if family == "controle" and _personal_control(args[3]) and (b := control_bonus(args[1])) is not None
    ]
    ctl_ref.gain_median = positive_median(ctl_gains)
    for uid, name, family, power, verdict, args, kw in calls:
        u = args[0]
        m = marriage_of(*args, **kw, heal_ref=heal_ref, control_ref=ctl_ref)
        rows.append(
            (
                u.id,
                uid,
                name,
                family or "autre",
                power,
                verdict,
                m.exposure,
                round(m.p_trigger, 3),
                m.start_round,
                m.bearer_only,
                round(m.rounds_alive, 2),
                round(m.survival, 3),
                round(m.marriage, 3),
                " | ".join(m.others) or None,
                round(m.tempo, 3),
                round(m.amplification, 3),
                round(m.role_fit, 3),
                round(m.bearing, 3),
            )
        )
    return rows


def share_melee_by_unit(con) -> dict[int, float]:
    return {
        uid: (sm if sm is not None else 1.0)
        for uid, sm in con.execute("SELECT unit_id, share_melee FROM unit_chassis").fetchall()
    }


def _units_by_army_name(con, repository) -> dict[str, list[Unit]]:
    by_id = repository.load_all_units_with_weapons(con)
    names = dict(con.execute("SELECT id, name FROM army").fetchall())
    return {names[aid]: us for aid, us in by_id.items()}
