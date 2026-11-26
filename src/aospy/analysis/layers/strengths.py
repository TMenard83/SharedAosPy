"""Couche 4 — synthèse automatique des forces et des faiblesses d'une liste.

Sortie pour `match-analysis` : chaque faiblesse dit **ce qui la punit** (profil adverse, en termes actionnables),
chaque force **ce qui la neutralise**. C'est une suggestion à confirmer à la lecture (skill `list-analysis` §4),
pas un verdict : elle ne voit ni le plan, ni les décors, ni les scénarios.

Mesures (points de la liste comme poids) et seuils calés le 2026-11-25 sur les quartiles des 54 listes de la L3
Centre (`REF` = médiane ligue, affichée à côté de la valeur) :

* activations (unités), contrôle par 100 pts, part de tir, part rapide (`roles.UnitRole.fast`) ;
* concentration des dégâts (part de la meilleure unité dans les dégâts « tout en place » de la liste) ;
* sauvegarde : 3+ ou mieux sans ward (punie par la perforation et les mortelles), 5+ ou pire sans ward (punie par le
  volume), ward 5+ ou mieux ;
* perforation moyenne des armes (pondérée par attaques × dégâts) ;
* mots-clés exposés aux Anti-X (MONSTER, CAVALRY, WAR MACHINE, HERO, INFANTRY) ; Anti-X portés par la liste ;
* dépendances : part des mariages sous condition de charge ou portés par un sort, donneurs peu fiables, supports
  fragiles, montée en puissance (`buildup.Curve.grows`).

Le round d'engagement (`UnitSheet.engage_round`) n'est pas utilisé : il vaut R1 pour 54 listes sur 54.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: médianes L3 (54 listes, 2026-11-25), affichées comme repère
REF = {"n": 9, "ctl": 3.0, "shoot": 0.11, "conc": 0.36, "fast": 0.65, "rend": 1.2}
FEW_UNITS, MANY_UNITS = 7, 11
LOW_CTL, HIGH_CTL = 2.3, 3.7
NO_SHOOT, SHOOT = 0.03, 0.3
CONCENTRATED = 0.45
SLOW, FAST = 0.25, 0.9
SAVE_STRONG, SAVE_WEAK, WARD = 0.5, 0.4, 0.4
LOW_REND, HIGH_REND = 1.0, 1.45
CHARGE_DEP, SPELL_DEP = 0.3, 0.3
#: donneur peu fiable / support fragile
WEAK_GIVER, FRAGILE_DEF_RANK = 0.6, 0.3
EXPOSED = {"MONSTER": 0.5, "CAVALRY": 0.4, "WAR MACHINE": 0.3, "HERO": 0.6, "INFANTRY": 0.8}
_KW_FR = {"MONSTER": "monstres", "CAVALRY": "cavalerie", "WAR MACHINE": "machines de guerre", "HERO": "héros",
          "INFANTRY": "infanterie"}
_ANTI = re.compile(r"Anti-([A-Z][A-Z ]*?[A-Z])\s*\(", re.I)


@dataclass(frozen=True)
class Trait:
    kind: str  # « force » | « faiblesse »
    axis: str
    text: str  # constat chiffré
    counter: str  # faiblesse : ce qui la punit ; force : ce qui la neutralise


def _pct(x: float) -> str:
    return f"{x:.0%}"


def measures(rep, roles) -> dict:
    """Mesures brutes de la liste (exposées pour les tests et le calage des seuils)."""
    from .roles import _shares

    us = [(p, u) for _n, p, u in rep.units if u is not None]
    total = sum(p for p, _u in us) or 1
    sheets = {s.name: s for s in rep.sheets}
    units = {u.name: u for _p, u in us}
    counts: dict[str, int] = {}
    for _p, u in us:
        counts[u.name] = counts.get(u.name, 0) + 1
    off, _dur = _shares(rep, units, {s.receiver: s for s in rep.stacks})
    off_tot = sum(off[k] * counts[k] for k in off) or 1.0
    top = max(off, key=lambda k: off[k] * counts[k]) if off else ""
    rend = 0.0
    for p, u in us:
        ws = [w for w in u.weapons if not w.is_companion]
        weight = sum(w.attacks * w.damage for w in ws) or 1
        rend += p * sum(w.attacks * w.damage * w.rend for w in ws) / weight
    warded = lambda u: bool(u.ward and u.ward <= 5)  # noqa: E731
    score = sum(m.score for m in rep.marriages) or 1.0
    spells = {a.name for a in rep.abilities if (a.cost_type or "").lower() == "spell"}
    anti = sorted({m.group(1).upper() for _p, u in us for w in u.weapons for m in _ANTI.finditer(w.abilities or "")})
    return {
        "total": total,
        "n": len(us),
        "ctl": 100 * sum(u.control * u.models for _p, u in us) / total,
        "shoot": sum(p * (1 - sheets[u.name].share_melee) for p, u in us if u.name in sheets) / total,
        "fast": sum(r.points for r in roles if r.fast) / total,
        "conc": off[top] * counts[top] / off_tot if top else 0.0,
        "top": top,
        "save_strong": sum(p for p, u in us if u.save <= 3 and not warded(u)) / total,
        "save_weak": sum(p for p, u in us if u.save >= 5 and not warded(u)) / total,
        "ward": sum(p for p, u in us if warded(u)) / total,
        "rend": rend / total,
        "kw": {k: sum(p for p, u in us if k in u.keywords) / total for k in EXPOSED},
        "anti": anti,
        "charge": sum(m.score for m in rep.marriages if "charg" in (m.conditions or "").lower()) / score,
        "spell": sum(m.score for m in rep.marriages if m.ability in spells) / score,
        "casts": rep.magic.casts_per_turn if rep.magic else 0,
    }


def synthesis(rep, roles=None, comps=None) -> list[Trait]:
    """Forces puis faiblesses de la liste (`listing.ListReport`), chacune avec sa parade."""
    from .roles import components, unit_roles

    roles = roles if roles is not None else unit_roles(rep)
    comps = comps if comps is not None else components(rep, roles)
    m = measures(rep, roles)
    F: list[Trait] = []
    W: list[Trait] = []
    f = lambda axis, text, counter: F.append(Trait("force", axis, text, counter))  # noqa: E731
    w = lambda axis, text, counter: W.append(Trait("faiblesse", axis, text, counter))  # noqa: E731

    # dégâts
    star = [c for c in comps if c.kind == "deathstar"]
    if star:
        f("dégâts", f"deathstar : {', '.join(star[0].units)} ({star[0].note})",
          "la bloquer (cordons, engagement par une enclume), la viser au tir ou aux mortelles avant qu'elle frappe, "
          "lui refuser la charge")
    if m["conc"] >= CONCENTRATED:
        w("dégâts", f"dégâts concentrés : {m['top']} porte {_pct(m['conc'])} des dégâts de la liste "
          f"(ligue : {_pct(REF['conc'])})",
          f"tuer ou neutraliser {m['top']} (tir, mortelles, -1 pour toucher, écran qui l'occupe) : "
          "le reste ne suit pas")
    if m["rend"] >= HIGH_REND:
        f("dégâts", f"perforation moyenne {m['rend']:.1f} (ligue : {REF['rend']:.1f})",
          "ward et protections contre les blessures plutôt que la sauvegarde")
    elif m["rend"] <= LOW_REND:
        w("dégâts", f"peu de perforation : {m['rend']:.1f} en moyenne (ligue : {REF['rend']:.1f})",
          "sauvegardes 3+/2+ et bonus de sauvegarde (couvert, +1 sauvegarde) l'émoussent")
    if m["anti"]:
        f("dégâts", "Anti-X dans la liste : " + ", ".join(m["anti"]),
          "ne pas lui présenter ces mots-clés, ou les présenter derrière un écran")
    # encaisse
    if m["save_strong"] >= SAVE_STRONG:
        f("encaisse", f"{_pct(m['save_strong'])} des points à 3+ ou mieux",
          "perforation 2+ et mortelles (la sauvegarde ne protège pas des mortelles)")
        w("encaisse", f"{_pct(m['save_strong'])} des points à 3+ ou mieux sans ward",
          "mortelles et forte perforation : la liste paie sa sauvegarde et n'a rien derrière")
    if m["save_weak"] >= SAVE_WEAK:
        w("encaisse", f"{_pct(m['save_weak'])} des points à 5+ ou pire sans ward",
          "le volume d'attaques, même sans perforation (tir de masse, grosses unités d'infanterie)")
    if m["ward"] >= WARD:
        f("encaisse", f"{_pct(m['ward'])} des points avec ward 5+ ou mieux",
          "gros dégâts fixes et perforation (la ward n'enlève qu'une part), contrôle plutôt que destruction")
    for kw, thr in EXPOSED.items():
        if m["kw"][kw] >= thr:
            w("mots-clés", f"{_pct(m['kw'][kw])} des points en {_KW_FR[kw]} ({kw})",
              f"armes Anti-{kw} et aptitudes contre les {_KW_FR[kw]}")
    # jeu / scénario
    if m["n"] <= FEW_UNITS:
        w("activations", f"{m['n']} unités seulement (ligue : {REF['n']})",
          "jeu large : plusieurs objectifs à la fois, tactiques qui demandent des unités, tuer une unité coûte cher")
    elif m["n"] >= MANY_UNITS:
        f("activations", f"{m['n']} unités (ligue : {REF['n']})",
          "unités qui tuent plusieurs petites cibles par tour, mortelles en zone")
    if m["ctl"] <= LOW_CTL:
        w("contrôle", f"contrôle {m['ctl']:.1f}/100 pts (ligue : {REF['ctl']:.1f})",
          "jouer les objectifs en nombre : la liste doit tuer pour reprendre")
    elif m["ctl"] >= HIGH_CTL:
        f("contrôle", f"contrôle {m['ctl']:.1f}/100 pts (ligue : {REF['ctl']:.1f})",
          "tuer les porteurs de contrôle (contrôle compté après les combats), contester avec des unités qui tiennent")
    if m["shoot"] >= SHOOT:
        f("portée", f"{_pct(m['shoot'])} des points en tir (ligue : {_pct(REF['shoot'])})",
          "se cacher derrière les décors, charger tôt les tireurs, -1 pour toucher au tir")
    elif m["shoot"] <= NO_SHOOT:
        w("portée", "pas de tir", "écrans et décors : la liste doit traverser la table ; tir à longue portée")
    if m["fast"] >= FAST:
        f("mobilité", f"{_pct(m['fast'])} des points rapides ou téléportés (ligue : {_pct(REF['fast'])})",
          "écrans à 9\" contre les arrivées, garder les objectifs arrière tenus")
    elif m["fast"] <= SLOW:
        w("mobilité", f"{_pct(m['fast'])} des points rapides (ligue : {_pct(REF['fast'])})",
          "scorer loin d'elle, la retarder avec des écrans, jouer les tactiques de déplacement")
    # dépendances
    if m["charge"] >= CHARGE_DEP:
        w("dépendance", f"{_pct(m['charge'])} de la valeur des aptitudes demande d'avoir chargé",
          "lui refuser la charge : charger en premier, écrans, rester hors de portée de charge")
    if m["spell"] >= SPELL_DEP:
        w("dépendance",
          f"{_pct(m['spell'])} de la valeur des aptitudes passe par des sorts ({m['casts']} lancers/tour)",
          "dissipation, unbind, tuer les sorciers")
    top_m = sorted((x for x in rep.marriages if x.giver < WEAK_GIVER), key=lambda x: -x.score)[:2]
    for x in top_m:
        if x.score >= 5:
            w("dépendance", f"{x.receiver} dépend de {x.ability} (fiabilité du donneur {x.giver:.2f})",
              "tuer ou isoler le donneur, couper la portée de l'aura")
    sheets = {s.name: s for s in rep.sheets}
    for r in roles:
        sh = sheets.get(r.name)
        if sh and (r.role == "support" or "support" in r.secondary) and sh.def_rank < FRAGILE_DEF_RANK:
            given = [s for s in r.reasons if s.startswith("donne ")]
            if given:
                w("dépendance", f"support fragile : {r.name} ({given[0]}), rang de durabilité {sh.def_rank:.2f}",
                  "le cibler en premier (tir, assassin, mortelles) : la liste perd ses bulles")
    if rep.curve is not None and rep.curve.grows:
        w("tempo", f"monte en puissance (pic au round {rep.curve.peak})",
          "la punir tôt : prendre l'initiative R1-R2, tuer avant que la liste soit en place")
    return F + W
