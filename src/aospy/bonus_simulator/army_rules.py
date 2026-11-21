"""Chargement de `data/json/army_rules.json` — liste curatée de bonus d'armée nommés
(ex. « Heure de Gloire », Stormcast Eternals). Chargeur pur, pas de DB : cette
liste n'a pas besoin d'être persistée, elle est relue à chaque lancement de
l'IHM (`app.py`) — même esprit que `persistence/seed.py` pour la convention
JSON, mais sans écriture en base.

Volontairement pas encore alimenté au-delà de l'exemple donné : ni BSData ni
Wahapedia ne capturent le texte des règles d'armée aujourd'hui (voir bonus_simulator/README.md).
`data/wahapedia/Faction_abilities.csv` (`type_name == "Battle Traits"`) contient
déjà ce texte pour les factions Wahapedia — future source d'auto-import, hors
scope ici.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .bonus import Bonus, StatDelta

DEFAULT_ARMY_RULES_FILE = Path("data") / "json" / "army_rules.json"


def load_army_rules(path: str | Path = DEFAULT_ARMY_RULES_FILE) -> dict[str, list[Bonus]]:
    """Renvoie les bonus d'armée du fichier JSON, groupés par nom d'armée.
    Fichier absent ou vide → dict vide (l'IHM reste utilisable, panneau « bonus
    d'armée » simplement vide, le bonus libre fonctionne toujours).
    """
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        rows = json.load(f)

    by_army: dict[str, list[Bonus]] = defaultdict(list)
    for row in rows:
        delta = StatDelta(**row.get("delta", {}))
        by_army[row["army"]].append(Bonus(name=row["name"], description=row.get("description", ""), delta=delta))
    return dict(by_army)
