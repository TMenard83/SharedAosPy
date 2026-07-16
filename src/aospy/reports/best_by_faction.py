"""Décline les deux registres « Panthéon des Champions » (best_heros.py/best_unites.py)
par faction : un sous-dossier `scratch/output/<armée>/` par armée, contenant l'extrait
(héros et unités) des lignes de cette armée dans le classement combat × coût. Le rang
affiché (colonne ``#``) est celui du registre global, pas une renumérotation locale —
`compute_ranked()` l'a déjà figé dans chaque ligne avant tout filtrage."""
import os

from . import best_heros, best_unites


def _write_by_faction(joined: list[dict], module, filename: str) -> None:
    universe_n = len(joined)
    by_faction: dict[str, list[dict]] = {}
    for r in joined:
        by_faction.setdefault(r["army"], []).append(r)

    for faction, rows in by_faction.items():
        out_dir = os.path.join("scratch", "output", faction)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, filename)
        module.render(rows, out_path, faction=faction, universe_n=universe_n)


_write_by_faction(best_heros.compute_ranked(), best_heros, "AoS_heros_best_TM.pdf")
_write_by_faction(best_unites.compute_ranked(), best_unites, "AoS_unites_best_TM.pdf")
