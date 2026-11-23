"""Couche 4 — les grilles de mariage de la couche 3 rejouées sur les receveurs RÉELS d'une liste.

La couche 3 (`marriage.py`) juge une aptitude donnée contre tous les receveurs possibles de sa faction ; une liste
réelle les connaît. Pour chaque aptitude que le moteur ne traduit pas (soin, contrôle, mobilité, magie, débuffs…,
la section « à lire » de `roster analyze`), on relève :

* le **mariage du porteur** (couche 3, `ability_marriage`) ;
* le **suivi** : le porteur suit-il les receveurs de CETTE liste (son allonge ÷ allonge médiane des receveurs,
  plafonnée à 1 — règle des buffs donnés, validée par l'utilisateur pour toutes les familles) ;
* **ce que chaque receveur de la liste en tire**, avec la mesure de sa famille :
  - soin : rounds de survie gagnés (`marriage.heal_survival_gain`, même pression que S) ;
  - contrôle : P(l'emporter sur l'objectif contre une charte au hasard) gagnée (`marriage.ControlReference`) ;
  - magie : lancers ou prières servis par tour (niveau WIZARD/PRIEST du receveur) ;
  - débuff : qui en profite dans la liste (« off » : ses frappeurs, « def » : ses unités au contact) ;
  - autres : la liste des receveurs.

Les contreparties (« maximum control score of 1 », malus de niveau, coût auto-infligé) sortent de la lecture.
Des nombres pour l'analyse humaine, jamais l'analyse elle-même (mémoire `list-building-concept`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ...domain.models import Unit

#: Détails d'effet qui signalent une contrepartie sur sa propre armée (couches 1, v35-v37).
DRAWBACK_DETAILS = {"contrepartie", "malus", "auto-infligé"}
_GIVEN = ("one_friendly", "friendly_aura", "army")
#: Unités de la liste comptées comme frappeurs : dégâts ≥ cette part du meilleur (même seuil que `assault`).
HITTER_SHARE = 0.5


#: Sous-types de mobilité (`marriage.mobility_kind`) → ce que la liste en fait.
MOBILITY_NOTES = {
    "engagement": "aide à l'engagement : charges chiffrées dans « Assaut »",
    "dégagement": "dégagement : sortir du combat pour recharger ou survivre",
    "repositionnement": "repositionnement : réserve, téléportation, mouvement",
}


@dataclass(frozen=True)
class GridRow:
    """Une aptitude non traduite, rejouée sur la liste."""

    ability: str
    source: str
    family: str
    verdict: str
    bearer: str  # "" pour une règle d'armée
    bearer_marriage: Optional[float]
    keep_up: Optional[float]  # suivi des receveurs de la liste (aptitude donnée par une charte)
    receivers: tuple[tuple[str, str], ...]  # (receveur, ce qu'il en tire)
    note: str = ""


#: Restrictions posées sur sa propre unité (scorées 0 en couche 1) : des contreparties.
_OWN_RESTRICTIONS = {"restriction", "lockout", "strike_last", "move_debuff", "no_ward"}


def _drawback_effect(e) -> bool:
    return (
        e.detail in DRAWBACK_DETAILS
        or e.kind == "battle_damaged"
        or (e.kind in _OWN_RESTRICTIONS and e.side == "friendly")
    )


def is_drawback(ab) -> bool:
    """Aptitude réduite à des contreparties : tous ses effets en sont (Battle Damaged, « maximum control score of
    1 », The Pendulum Swings : la manifestation ne peut ni charger ni combattre)."""
    return bool(ab.effects) and all(_drawback_effect(e) for e in ab.effects)


def _e_tuple(e, family: str) -> tuple:
    """`EffectSpec` → tuple de `marriage.load_effects` (kind, requires, target_condition, target_keywords,
    duration, weapon_scope, stat, family, value, detail)."""
    return (
        e.kind,
        e.requires,
        e.target_condition,
        e.target_keywords,
        e.duration,
        e.weapon_scope,
        e.stat,
        family,
        e.value,
        e.detail,
    )


def keep_up(bearer_reach: Optional[float], receiver_reaches: list[float]) -> Optional[float]:
    """min(1, allonge du porteur ÷ allonge médiane des receveurs de la liste) ; None sans mesure."""
    vals = sorted(r for r in receiver_reaches if r)
    if not bearer_reach or not vals:
        return None
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    return round(min(1.0, bearer_reach / med), 2)


def _exposure(share_melee: float) -> str:
    return "contact" if share_melee >= 0.5 else "longue"


def heal_label(u: Unit, e_list, frequency: str, turn_side: str, incoming, share_melee: float) -> str:
    from .marriage import heal_points, heal_survival_gain

    pts = heal_points(u, e_list)
    if pts is None:
        return "non chiffré"
    if pts == 0:
        return "rien (1 PV par figurine ou figurine unique)"
    g = heal_survival_gain(u, e_list, frequency, turn_side, incoming, _exposure(share_melee))
    return f"survie {g:+.0%}" if g is not None else "non chiffré"


def control_label(u: Unit, bonus: Optional[float], ref) -> str:
    if bonus is None:
        return "non chiffré"
    base = u.models * u.control
    return f"objectif {ref.p_win(base):.0%} → {ref.p_win(base + bonus):.0%}"


def magic_label(u: Unit, stats: set[str]) -> str:
    from .marriage import caster_level

    wiz = caster_level(u, "WIZARD") if stats & {"cast", "unbind", "banish", "power_level"} else 0
    pri = caster_level(u, "PRIEST") if "chant" in stats else 0
    if not wiz and not pri:
        return "ne lance rien"
    parts = ([f"{wiz} sort(s)"] if wiz else []) + ([f"{pri} prière(s)"] if pri else [])
    return " + ".join(parts) + " par tour"


def grid_rows(
    abilities,
    units: list[Unit],
    vocab: frozenset[str],
    share_melee: dict[str, float],
    families: dict[str, str],
    bearer_marriage: dict[tuple[str, str], float],
    reach_in: dict[str, float],
    incoming: dict[int, tuple[float, float]],
    control_ref,
    damage: dict[str, float],
) -> tuple[list[GridRow], list]:
    """(lignes de la grille, contreparties écartées) pour les aptitudes `abilities` (déjà filtrées : à lire)."""
    from .listing import effect_ability, list_receivers
    from .marriage import control_bonus, debuff_polarity, mobility_kind

    best_dmg = max(damage.values(), default=0.0)
    hitters = {n for n, d in damage.items() if best_dmg and d >= HITTER_SHARE * best_dmg}
    rows: list[GridRow] = []
    drawbacks = []
    for ab in abilities:
        if is_drawback(ab):
            drawbacks.append(ab)
            continue
        fam = families.get(ab.uid, "autre")
        e_list = [_e_tuple(e, fam) for e in ab.effects]
        recv: list[tuple[Unit, str]] = []
        for ft in dict.fromkeys(e.friendly_target for e in ab.effects) or [""]:
            for u, rel in list_receivers(effect_ability(ab, ft), units, vocab):
                if u not in [r for r, _ in recv]:
                    recv.append((u, rel))
        given = ab.scope in _GIVEN
        bearer = ab.carriers[0] if ab.carriers else ""
        bm = bearer_marriage.get((bearer, ab.uid)) if bearer else None
        others = [u for u, rel in recv if rel != "porteur"] if given else []
        ku = keep_up(reach_in.get(bearer), [reach_in.get(u.name) for u in others]) if bearer and others else None
        labels: list[tuple[str, str]] = []
        note = ""
        if fam == "soin" and any(e[0] in ("heal", "return_models") for e in e_list):
            for u, _rel in recv:
                labels.append(
                    (u.name, heal_label(u, e_list, ab.frequency, ab.turn_side, incoming.get(u.id, (0.0, 0.0)),
                                        share_melee.get(u.name, 1.0)))
                )
        elif fam == "controle":
            bonus = control_bonus(e_list)
            labels = [(u.name, control_label(u, bonus, control_ref)) for u, _rel in recv]
        elif fam == "magie-ressource":
            stats = {e[6] for e in e_list if e[0] in ("stat_mod", "dice_count", "reroll") and e[8] > 0}
            stats &= {"cast", "chant", "unbind", "banish", "power_level"}
            if stats:
                labels = [(u.name, magic_label(u, stats)) for u, _rel in recv]
            else:
                labels = [(u.name, "") for u, _rel in recv]
                note = "ressource / anti-magie / remplacement : selon la liste et l'adversaire"
        elif fam == "debuff":
            pol = debuff_polarity(e_list)
            if pol == "off":
                note = "affaiblit la défense ennemie : sert " + (", ".join(sorted(hitters)) or "personne")
            elif pol == "def":
                melee = sorted(n for n, s in share_melee.items() if s >= 0.5)
                note = "affaiblit les attaques ennemies : protège " + (", ".join(melee) or "personne")
            else:
                note = "ordre, contrôle, magie ou mouvement ennemi : selon l'adversaire"
        elif fam == "degats-directs":
            note = "dégâts directs : selon la cible (couche 3, `mortals`)"
        else:
            labels = [(u.name, "") for u, _rel in recv]
            if fam == "mobilite":
                note = MOBILITY_NOTES.get(mobility_kind(e_list, ab.text), "")
            if any(e[0] == "reroll" and e[6] == "charge" for e in e_list):
                note = "relance des charges : chiffrée dans « Assaut »"
        rows.append(
            GridRow(ab.name, ab.source, fam, ab.verdict, bearer, bm, ku, tuple(labels), note)
        )
    return rows, drawbacks


def collect_grid(con, entries, rep) -> None:
    """Remplit `rep.grid` / `rep.drawbacks` depuis la base (lecture seule) pour `rep.unresolved`."""
    from .marriage import ControlReference, incoming_damage

    units = [u for _n, _p, u in entries if u is not None]
    distinct = list({u.name: u for u in units}.values())
    ids = {u.name: u.id for u in distinct}
    uids = [a.uid for a in rep.unresolved] or [""]
    families = dict(con.execute("SELECT uid, coalesce(family, 'autre') FROM ability WHERE uid IN ?", [uids]).fetchall())
    names = {v: k for k, v in ids.items()}
    bearer_marriage = {
        (names[uid], aid): m
        for uid, aid, m in con.execute(
            "SELECT unit_id, ability_uid, marriage FROM ability_marriage WHERE unit_id IN ? AND ability_uid IN ?",
            [list(ids.values()) or [-1], uids],
        ).fetchall()
    }
    # optimisation prise : mariage du porteur lu dans `enhancement_bearer`
    for uid, aid, m in con.execute(
        "SELECT unit_id, ability_uid, marriage FROM enhancement_bearer WHERE unit_id IN ? AND ability_uid IN ?",
        [list(ids.values()) or [-1], uids],
    ).fetchall():
        bearer_marriage.setdefault((names[uid], aid), m)
    reach_in = {
        names[uid]: r
        for uid, r in con.execute(
            "SELECT unit_id, reach_in FROM unit_realized WHERE unit_id IN ?", [list(ids.values()) or [-1]]
        ).fetchall()
    }
    sm, dmg = {}, {}
    for uid, s, d in con.execute(
        "SELECT unit_id, coalesce(share_melee, 1.0), coalesce(dmg_melee, 0) + coalesce(dmg_ranged, 0) "
        "FROM unit_chassis WHERE unit_id IN ?",
        [list(ids.values()) or [-1]],
    ).fetchall():
        sm[names[uid]], dmg[names[uid]] = s, d
    scores = [m * c for m, c in con.execute("SELECT models, control FROM unit WHERE points > 0").fetchall()]
    rep.grid, rep.drawbacks = grid_rows(
        rep.unresolved,
        distinct,
        rep.vocab,
        sm,
        families,
        bearer_marriage,
        reach_in,
        incoming_damage(con),
        ControlReference(scores),
        dmg,
    )
