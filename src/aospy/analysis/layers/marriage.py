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

Les autres familles restent neutres (A = R = F = 1) : critères proposés dans analysis/README.md.

**Toutes les constantes ci-dessous sont des hypothèses de travail à challenger** (règle utilisateur :
signaler les classements contre-intuitifs et proposer de les réviser).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
BEARER_CONDITIONS = (
    "a chargé",
    "en territoire",
    "sur objectif",
    "au combat",
    "sans mouvement",
    "sans charge",
    "combat enchaîné",
)
#: « The target can be picked to fight immediately after this unit… If it is picked to do so, add 1… »
#: (Brawlerguts, Lead Da Brutes, Infantry Overseer…) : le bonus ne joue que si le héros et l'unité combattent
#: l'un après l'autre. Part des combats où c'est le cas : choix utilisateur 2026-11-22 (option « ×0,5 »,
#: hypothèse à calibrer) — ni plein (il faut être collés), ni nul (sinon tout l'archétype perd son soutien).
CHAINED_FIGHT_SHARE = 0.5
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
    others = [c for c in conds if c not in BEARER_CONDITIONS]
    p, start = 1.0, 1
    charged = "a chargé" in conds
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
    return Trigger(p=p, start=start, bearer_only=not others, charged=charged)


def exposure_of(scope: str, range_inches: Optional[int], requires: str, family: str) -> str:
    """Exposition imposée au porteur pour tenir l'effet."""
    if "au combat" in requires or "a chargé" in requires:
        return "contact"
    if range_inches is None:
        return "contact" if family == "debuff" else "longue"
    if range_inches <= 3:
        return "contact"
    return "courte" if range_inches <= 9 else "longue"


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
#: Familles notées par la grille (les autres : A = R = F = 1).
GRID_FAMILIES = ("buff-perso-offensif", "buff-perso-defensif", "buff-donne")
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


def effect_timing(family: str, e_list: list[tuple], bearer_share_melee: float) -> tuple[str, float]:
    """(polarité, part de mêlée) qui fixent les demi-tours utiles d'un effet (`timeline.relevance`).

    Buff perso : la famille donne la polarité, le porteur sa part de mêlée. Buff donné : lu dans les effets
    (une protection sert surtout au tour adverse, un buff de tir à mon seul tour) ; les armes visées
    (`weapon_scope`) fixent la part de mêlée — tir → 0, mêlée → 1, sinon celle du porteur."""
    pol = FAMILY_POLARITY.get(family, "autre")
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
    if family == "buff-donne" and prof.reach and receivers_reach:
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
    """ability_uid → [(kind, requires, target_condition, target_keywords, duration, weapon_scope, stat)]."""
    effs: dict[str, list[tuple]] = {}
    for uid, kind, req, tcond, tkw, dur, wscope, stat in con.execute(
        "SELECT ability_uid, kind, requires, target_condition, target_keywords, duration, weapon_scope, stat "
        "FROM ability_effect"
    ).fetchall():
        effs.setdefault(uid, []).append((kind, req or "", tcond or "", tkw or "", dur or "", wscope or "", stat or ""))
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
) -> Marriage:
    """Mariage d'une aptitude (ses effets `load_effects`) portée par `u` : D × S × F × A × R.

    `amplification` = A brut (`amplification_ratios`, None = non mesuré → neutre), `role` = R (`role_fit`)."""
    from .timeline import start_share

    reqs = " | ".join(dict.fromkeys(r for e in e_list for r in e[1].split(" | ") if r))
    conds = [c for e in e_list for c in (e[1].split(" | ") + e[2].split(" | ")) if c]
    conds += [f"vs {e[3]}" for e in e_list if e[3]]
    conds = list(dict.fromkeys(conds))
    kinds = {e[0] for e in e_list}
    melee = bool(e_list) and all(e[5] == "melee" for e in e_list if e[5])
    t = trigger(
        u,
        reqs,
        " | ".join(conds),
        share_melee,
        melee_effect=melee,
        kind="charge_bonus" if "charge_bonus" in kinds else "",
    )
    fam = family or "autre"
    if fam in ("buff-perso-offensif", "buff-perso-defensif"):
        expo = "contact" if share_melee >= 0.5 else "longue"
    else:
        expo = exposure_of(scope or "", rng, reqs, fam)
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
    pol, sm_t = effect_timing(fam, e_list, share_melee)
    f = tempo(fam, freq or "", dur, turn_side or "any", sm_t, pol)
    a = _bound(amplification) if amplification is not None and fam in GRID_FAMILIES else 1.0
    r = role if fam in GRID_FAMILIES else 1.0
    return Marriage(
        expo,
        t.p,
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
    abil = con.execute(
        """SELECT o.faction_name, lower(o.owner_name), a.uid, a.name, a.family, a.power, a.verdict, a.scope,
                  a.range_inches, a.frequency, a.turn_side
           FROM ability_owner o JOIN ability a ON a.uid = o.ability_uid
           WHERE o.owner_kind = 'warscroll' AND a.source_kind NOT IN ('manifestation')"""
    ).fetchall()
    rows: list[tuple] = []
    seen: set[tuple[int, str]] = set()
    for fac, owner, uid, name, family, power, verdict, scope, rng, freq, tside in abil:
        u = units.get((fac, owner))
        if u is None or (u.id, uid) in seen:
            continue
        seen.add((u.id, uid))
        fam = family or "autre"
        m = marriage_of(
            u,
            effs.get(uid, []),
            family or "autre",
            scope or "",
            rng,
            freq or "",
            chassis.get(u.id, 1.0),
            incoming.get(u.id, (0.0, 0.0)),
            tside or "any",
            amplification=amps.get((u.id, uid)),
            role=role_fit(fam, profiles.get(u.id, ChassisProfile(share_melee=chassis.get(u.id, 1.0))), recv.get(uid)),
        )
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
