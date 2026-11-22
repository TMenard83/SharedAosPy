"""Ressources de faction : rythmes d'accumulation et facteur d'usage (analyseur v34, chantier C).

Rythmes en points par round, validés par l'utilisateur le 2026-11-22 (tableau proposé accepté tel quel).
Deux mécaniques :

* **déblocage cumulatif** (Dîme de Sang) : `RESOURCE_RATES`, clé = `RawAbility.cost_type` en minuscules ;
  `pipeline.resolve_resource_costs` en tire le round de disponibilité ;
* **dépense à chaque usage** (« Spend 2 relentless discipline points », coût « Fate ») : facteur d'usage
  = min(1, rythme / coût) sur la puissance (validé). La concurrence entre aptitudes sur la même réserve est
  laissée à la couche 4, comme le budget de PC. Colonne `ability.resource_usage` pour la couche 3.
"""

from __future__ import annotations

import re

from .extract.timing import frequency_of
from .models import RawAbility

#: Rounds d'une partie : une aptitude « une fois par bataille » se finance sur toute la partie, pas sur un round
#: (sinon un coût 3 à 1,5/round serait pénalisé deux fois : par la fréquence et par l'usage).
BATTLE_ROUNDS = 5

#: Niveau de fureur moyen (saison Fléau d'Aqshy, validé) : départ 1 (attaquant) ou 2 (défenseur), monte
#: d'1 sur les 6 des Éruptions adverses, descend d'1 par dé de rage dépensé à Braver la Douleur.
FURY_LEVEL = 2.0

#: Déblocage cumulatif (clé = `cost_type` en minuscules).
RESOURCE_RATES: dict[str, float] = {"blood tithe": 2.0}

#: Dépense à chaque usage : nom de la ressource (singulier, minuscules) → points gagnés par round.
SPEND_RATES: dict[str, float] = {
    "rage dice": FURY_LEVEL,  # = niveau de fureur au début du round (saison)
    "relentless discipline point": 3.0,  # OB, IMMORTAL ELITE : N du mot-clé du général, perdus en fin de round
    "fate point": 1.5,  # DoT : priorité perdue, sort dissipé, fiasco… (max 9)
    "raw ingredient": 8.0,  # OM : PV × figurines de départ par unité ennemie détruite
    "oath point": 1.0,  # StD Snow Peaks : +1 par serment résolu
    "asydrazor point": 2.0,  # ID : D3 par phase des héros
    "noble deeds point": 3.0,  # FEC : dégâts alloués par le combat du héros (max 6)
    "disease point": 3.0,  # MoN : +1 par critique ami (max 7)
    "blood tithe point": 2.0,  # BoK, quand une aptitude en dépense (en plus des déblocages)
}
#: `cost_type` Wahapedia dépensé à chaque usage → ressource de `SPEND_RATES`.
_SPEND_COST_TYPES = {"fate": "fate point"}

_SPEND = re.compile(
    r"\b[Ss]pend (\d+|D3|any number of|up to \d+|a number of|X) (?:additional |your |of your )?"
    r"((?:rage dice)|[a-z][a-z' -]*? point|raw ingredient)s?\b"
)


def _cost(token: str) -> float:
    if token.isdigit():
        return float(token)
    return 2.0 if token == "D3" else 1.0  # « any number of / up to N / a number of » : au moins 1 point


def resource_usage(raw: RawAbility) -> tuple[float | None, str]:
    """Facteur d'usage min(1, rythme/coût) de la ressource dépensée (None si aucune ressource au rythme connu)."""
    ct = raw.cost_type.lower()
    if ct in _SPEND_COST_TYPES:
        m = re.match(r"\d+", raw.cost_value or "")
        name, cost = _SPEND_COST_TYPES[ct], float(m.group()) if m else 1.0
    else:
        m = next(
            (m for m in _SPEND.finditer(f"{raw.declare} {raw.effect}") if m.group(2).strip() in SPEND_RATES), None
        )
        if not m:
            return None, ""
        name, cost = m.group(2).strip(), _cost(m.group(1))
    rate, per = SPEND_RATES[name], "round"
    if frequency_of(raw.condition).startswith("once_per_battle"):
        rate, per = rate * BATTLE_ROUNDS, "bataille"
    usage = round(min(1.0, rate / cost), 3) if cost else 1.0
    return usage, f"dépense {cost:g} {name} (rythme {rate:g}/{per}) → usage ×{usage:.2g}"
