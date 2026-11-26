"""Exporte les 54 listes de la L3 Centre 2026-27 (aller) au format texte de l'App, puis (option)
génère leur aide de jeu `aospy roster pdf` (mode fr-split-simple par défaut).

Les listes adverses viennent du PDF de l'orga, où chaque joueur a collé un export différent
(App, Sigdex, saisie à la main) : on ne recopie pas son en-tête, on le reconstruit à partir de
ce qu'on sait (faction de `l3_matchups.PLAYERS`, formation et armée de renom reconnues dans les
noms Wahapedia de la faction, domaines, cartes de tactique), puis on recopie le corps (régiments,
unités, options, Régiments de Renom, terrain de faction). Nos 12 listes reprennent l'export
App déjà rangé dans `data/Proposition de listes/<équipe>/`.

  aospy l3 export-lists                 écrit les .txt dans `data/2026-27 L3 Aller/Listes texte/<équipe>/`
  aospy l3 export-lists --pdf [--mode M] [--player P ...]   + génère les PDF dans `Aides de jeu/<équipe>/`
"""

from __future__ import annotations

import argparse
import csv
import functools
import json
import re
import sys
import unicodedata
from pathlib import Path

from . import matchups as mx

TXT_DIR = mx.FOLDER / "Listes texte"
PDF_DIR = mx.FOLDER / "Aides de jeu"
OUR_LISTS = mx.ROOT / "data" / "Proposition de listes"
OUR_FOLDERS = {"Melusior": "Melusior", "Vae Victis Vernou": "Vae Victis Vernou"}
# Nom de fichier de nos listes quand il ne commence pas par le pseudo exact.
OUR_ALIASES = {"Sharowkyn": "Sharowkin", "Cartoone": "Cartoon", "Laytorne": "Laytorn", "MuaD_Dib": "Muad_Dib"}
# Faction en base -> ligne de faction de l'App (tomes multi-factions).
APP_FACTION = {"Kruleboyz": "Orruk Warclans | Kruleboyz", "Ironjawz": "Orruk Warclans | Ironjawz"}

_UNIT = re.compile(r"^(?:\d+x\s+)?(?P<name>.+?)\s*\((?P<pts>\d+)(?:\s*(?:pts|points))?\)\s*(?P<rest>.*)$", re.I)
_REGIMENT = re.compile(r"^[-=\s]*(General[’']s Regiment|Regiment #?\d+)\b", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("’", "'")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _faction_rows() -> list[dict]:
    csv.field_size_limit(10**8)
    with open(mx.WAHAPEDIA / "Faction_abilities.csv", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter="|"))


def _faction_ids() -> dict[str, str]:
    with open(mx.WAHAPEDIA / "Factions.csv", encoding="utf-8-sig") as fh:
        return {r["name"]: r["id"] for r in csv.DictReader(fh, delimiter="|")}


@functools.lru_cache(maxsize=1)
def _terrain_names() -> dict[str, set[str]]:
    """Décors de faction (rôle « Faction Terrain » dans Wahapedia), par id de faction."""
    out: dict[str, set[str]] = {}
    with open(mx.WAHAPEDIA / "Warscrolls.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter="|"):
            if r["role"] == "Faction Terrain":
                out.setdefault(r["faction_id"], set()).add(r["name"])
    return out


TACTIC_CARDS = [
    c["name_en"].replace("Smoke Screen", "Smokescreen")
    for c in json.loads((mx.ROOT / "data" / "json" / "battle_tactic_cards.json").read_text(encoding="utf-8"))
]
# Noms de terrain mal orthographiés dans les listes -> nom Wahapedia.
TERRAIN_ALIASES = {"Dawner's Triumph": "Dawners Triumph"}

STANDARD_TYPES = {
    "Battle Traits",
    "Battle Formations",
    "Heroic Traits",
    "Artefacts of Power",
    "Spell Lore",
    "Prayer Lore",
    "Manifestation Lore",
    "Enhancements",
    "Regiment Abilities",
    "Monstrous Traits",
}


BY_POINTS = mx.BY_POINTS  # homonymes départagés par le coût (Tzaangor Enlightened à pied)


def convert(player: str, lines: list[str], rows: list[dict], fids: dict[str, str]) -> tuple[str, list[str]]:
    """Texte au format App + notes (ce qui a été deviné)."""
    team, faction = mx.PLAYERS[player]
    fid = fids.get(faction)
    blob = _norm(" | ".join(lines))
    notes: list[str] = []
    formations = sorted(
        {
            r["subtype_name"].split("(")[0].strip()
            for r in rows
            if r["faction_id"] == fid and r["type_name"] == "Battle Formations"
        },
        key=len,
        reverse=True,
    )
    formation = next((f for f in formations if _norm(f) and _norm(f) in blob), None)
    renowns = sorted(
        {
            r["type_name"]
            for r in rows
            if r["faction_id"] == fid
            and r["type_name"] not in STANDARD_TYPES
            and r["type_name"] == r["type_name"].strip()
        },
        key=len,
        reverse=True,
    )
    renown = next((a for a in renowns if _norm(a) and len(_norm(a)) > 6 and _norm(a) in blob), None)
    fac_line = APP_FACTION.get(faction, faction) + (f" | {renown}" if renown else "")
    if not formation:
        notes.append("formation non reconnue")
    head = [f"{player} - {team}", "", fac_line] + ([formation] if formation else []) + ["General's Handbook 2026-27"]
    drops = next(
        (
            re.search(r"(\d+)\s*drops?|drops?\s*[:\-]\s*(\d+)", ln, re.I)
            for ln in lines
            if re.search(r"\bdrops?\b", ln, re.I)
        ),
        None,
    )
    if drops:
        head.append(f"Drops: {drops[1] or drops[2]}")
    for key in ("Spell Lore", "Prayer Lore", "Manifestation Lore"):
        line = next((ln for ln in lines if ln.lower().startswith(key.lower())), None)
        if line:
            value = line[len(key) :].strip(" -:–")
            if value.lower().startswith(key.lower()):  # « Spell Lore - Spell Lore: X »
                value = value[len(key) :].strip(" -:–")
            head.append(f"{key} - {value}")
    # Cartes de tactique : reconnues par leur nom dans tout l'en-tête (une ligne coupée en deux
    # dans le PDF, « Legend of the » / « Parch », ne doit pas les faire rater).
    cards = [c for c in TACTIC_CARDS if _norm(c).replace(" ", "") in _norm(" ".join(lines[:15])).replace(" ", "")]
    if cards:
        head.append("Battle Tactic Cards: " + ", ".join(cards))
    body: list[str] = []
    terrain: list[str] = []
    terrain_names = _terrain_names().get(fid, set())
    started = False
    section = None
    for raw in lines:
        ln = raw.strip().replace("’", "'")
        if not ln:
            continue
        if _REGIMENT.match(ln):
            started, section = True, "regiment"
            head_txt = _REGIMENT.match(ln)[1].replace("’", "'").replace("#", "")
            body += ["", "General's Regiment" if head_txt.lower().startswith("general") else head_txt.title()]
            continue
        if not started:
            continue
        if ln.lower().startswith("regiments of renown"):
            section = "renown"
            body += ["", "Regiments of Renown"]
            continue
        if ln.lower().startswith("faction terrain"):
            section = "terrain"
            rest = ln[len("faction terrain") :].strip(" :")
            if rest:
                terrain.append(re.sub(r"\s*\((\d+)\)$", r" (\1 Points)", rest))
            continue
        if ln.startswith(("Created with", "App:")) or any(
            _norm(team_name)[:12] in _norm(ln) for team_name in mx._TEAMS
        ):
            continue
        if section == "terrain":
            if not ln.startswith(("•", "-")) and len(terrain) < 2:
                terrain.append(TERRAIN_ALIASES.get(ln, re.sub(r"\s*\((\d+)\)$", r" (\1 Points)", ln)))
            continue
        if ln.startswith(("•", "~", "-")):
            opt = ln.lstrip("•~- ").strip()
            bare = re.sub(r"\s*\(\d+(?:\s*(?:pts|points))?\)$", "", opt, flags=re.I)
            if bare in terrain_names:  # décor de faction collé sous une unité (Zieg : Stormreach Portal)
                if bare not in terrain and len(terrain) < 2:
                    terrain.append(bare)
            elif opt:  # puce vide recopiée du PDF de l'orga (Kazerole) : ignorée
                body.append(" • " + opt)
            continue
        m = _UNIT.match(ln)
        if m:
            name = re.sub(r"^SoA\s+", "Scourge of Aqshy: ", m["name"].strip())
            name = mx.ALIASES.get(name, name)
            name = BY_POINTS.get((name, m["pts"]), name)
            body.append(f"{name} ({m['pts']})")
            for opt in (o.strip(" ,") for o in m["rest"].split("•")):
                if opt:
                    body.append(" • " + opt)
        elif section == "renown":
            body.append(ln)
    if not started:
        notes.append("aucun régiment trouvé")
    out = head + body
    if terrain:
        out += ["", "Faction Terrain", *terrain]
    return "\n".join(out) + "\n", notes


def our_file(player: str, team: str) -> Path | None:
    folder = OUR_LISTS / OUR_FOLDERS[team]
    prefix = OUR_ALIASES.get(player, player)
    hits = [p for p in folder.iterdir() if p.is_file() and p.name.lower().startswith(prefix.lower())]
    return sorted(hits)[0] if hits else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aospy l3 export-lists", description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--mode", default="fr-split-simple")
    ap.add_argument("--player", nargs="+")
    args = ap.parse_args(argv)
    rows, fids = _faction_rows(), _faction_ids()
    blocks = mx.parse_lists(mx.PDF)
    report = {}
    for player, lines in blocks.items():
        if args.player and player not in args.player:
            continue
        team = mx.PLAYERS[player][0]
        path = TXT_DIR / team / f"{player}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        src = our_file(player, team) if team in OUR_FOLDERS else None
        if src:
            path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            notes = [f"export App : {src.name}"]
        else:
            text, notes = convert(player, lines, rows, fids)
            path.write_text(text, encoding="utf-8")
        report[player] = {"txt": str(path.relative_to(mx.ROOT)), "notes": notes}
        if args.pdf:
            from aospy.tournament_kit.pdf_builder import build_roster_pdf

            out = PDF_DIR / team / f"{player} ({args.mode}).pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                res = build_roster_pdf(path, out, mode=args.mode)
                if res.scenario_output_path and Path(res.scenario_output_path).exists():
                    Path(res.scenario_output_path).unlink()  # variante avec les 12 scénarios : inutile ici
                cards = {
                    k: [
                        {
                            "name": ab.name,
                            "description": ab.description,
                            "condition": ab.condition,
                            "phase": ab.ability_phase,
                            "keywords": ab.keywords,
                            "cost": f"{ab.points_type}:{ab.points}",
                            "unites": list(ab.warscrolls),
                        }
                        for ab in v
                    ]
                    for k, v in res.ability_cards.items()
                }
                out.with_suffix(".json").write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
                report[player].update(
                    pdf=str(out.relative_to(mx.ROOT)),
                    units_unmatched=res.units_unmatched,
                    rules_unmatched=res.rules_unmatched,
                )
            except Exception as exc:  # une liste mal convertie ne doit pas bloquer les autres
                report[player]["erreur"] = f"{type(exc).__name__}: {exc}"
        r = report[player]
        print(
            f"{player:13s} {', '.join(r['notes']) or 'ok'}"
            + (f" | non trouvés : {r.get('units_unmatched')}" if r.get("units_unmatched") else "")
            + (f" | règles manquantes : {r.get('rules_unmatched')}" if r.get("rules_unmatched") else "")
            + (f" | ERREUR {r['erreur']}" if r.get("erreur") else ""),
            flush=True,
        )
    rapport = TXT_DIR / "rapport.json"
    if args.player and rapport.exists():  # run partiel : garder les autres joueurs
        report = {**json.loads(rapport.read_text(encoding="utf-8")), **report}
    rapport.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
