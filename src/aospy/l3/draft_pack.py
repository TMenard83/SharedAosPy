"""Brouillons stratégiques en un passage : « paquet de liste » préparé par script, puis un seul appel `claude -p`.

Remplace l'agent à outils de `strategie_agent.md` (≈ 160 k tokens/liste, 35 tours) : tout ce que l'agent allait
lire est assemblé d'avance, le modèle ne fait que rédiger.

* **Méthode** (identique pour toutes les listes, en invite système → réutilisable en cache) : consigne
  `strategie_agent.md`, skill `list-analysis`, sections « Principes stratégiques » et « Règles de jeu » du skill
  `l3-matchups`, mémoires de méthode, scénarios de la ligue, exemple de profondeur (stratégie de Cromba).
* **Paquet** (par liste) : export de l'App, fiche couche 4 et textes (`scratch/list_dossier.py`), aide de jeu FR
  compactée, les 2 cartes de tactique de l'export (verbatim FR), `aospy l3 diag --player`, contrôles automatiques
  (unités non reconnues, cartes inconnues), puis l'entrée combos existante (pour `desaccords_combos` seulement).
* **Sortie** : JSON validé (clés, noms exacts des sous-tactiques, niveaux) → `Données/auto/<équipe>/<joueur>.json`,
  fiche `Listes/Brouillons <équipe>.md` régénérée (`l3.drafts`), consommation notée dans `Données/auto/_usage.jsonl`.

usage : python -m aospy.l3.draft_pack (--player P | --team T | --ronde N) [--force] [--jobs 3] [--model opus]
                                      [--pack-only] [--list]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import drafts

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "data" / "2026-27 L3 Aller"
DATA = FOLDER / "Données"
AUTO = DATA / "auto"
SKILLS = ROOT / ".claude" / "skills"
MEMORY = Path.home() / ".claude" / "projects" / "-home-tmenard-Dev-Python-aospy" / "memory"
MEMORIES = ("list-building-concept", "aos-set-up-rules", "charge-9-is-a-gamble", "aos-battle-tactics-rules",
            "aos-objectives-control-reading", "player-jargon", "ability-weighting-rules")
OURS = ("Melusior", "Vae_Victis_Vernou")
LEVELS = {"facile", "moyen-facile", "moyen", "difficile", "abandon"}
REQUIRED = ("equipe", "joueur", "faction", "confiance", "controles", "strategie", "tactiques", "note_plan_proposee")
PY = str(ROOT / ".venv" / "bin" / "python")


# --------------------------------------------------------------------------- index des listes

def index() -> list[dict]:
    """Toutes les listes : équipe affichée, fichier combos, joueur, export texte, aide de jeu."""
    combos = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in (DATA / "combos").glob("*.json")}
    out = []
    for team_dir in sorted((FOLDER / "Listes texte").iterdir()):
        if not team_dir.is_dir():
            continue
        for txt in sorted(team_dir.glob("*.txt")):
            player = txt.stem
            stem = next((s for s, d in combos.items() if player in d), None)
            out.append({"team": team_dir.name, "file": stem, "player": player, "txt": txt,
                        "aide": FOLDER / "Aides de jeu" / team_dir.name / f"{player} (fr-split-simple).json",
                        "combos": (combos.get(stem) or {}).get(player, {})})
    return out


def opponents_of_round(n: int) -> set[str]:
    """Équipes (nom affiché) rencontrées par nos équipes à la ronde n (dossiers `Matchups/Matchups <équipe>/`)."""
    teams = set()
    for d in (FOLDER / "Matchups").glob(f"Matchups */Ronde {n} — contre *"):
        teams.add(d.name.split(" — contre ", 1)[1])
    return teams


# --------------------------------------------------------------------------- méthode (invite système)

def _strip_front(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()


def _section(md: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}.*?(?=^## |\Z)", md, flags=re.S | re.M)
    return m.group(0).strip() if m else ""


def method() -> str:
    l3 = (SKILLS / "l3-matchups" / "SKILL.md").read_text(encoding="utf-8")
    example = json.loads((DATA / "combos" / "Limoges_Wargame.json").read_text(encoding="utf-8"))["Cromba"]["strategie"]
    scen = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
    parts = [
        "Tu es un analyste expert d'Age of Sigmar 4e édition (ligue par équipes L3 Centre AOSFF 2026-27). "
        "Tu rédiges le brouillon d'analyse stratégique et de tactiques de bataille d'UNE liste, en français. "
        "Tu n'as AUCUN outil : toutes les entrées que la consigne demande de lire sont fournies, la méthode "
        "ci-dessous et la liste dans le message. Quand la consigne dit « lire tel fichier », il est fourni ici ou "
        "dans le paquet ; un point que ces textes ne tranchent pas devient une question dans `strategie.questions`, "
        "pas une invention. Réponds UNIQUEMENT par le JSON de sortie, dans un bloc ```json, sans texte autour.",
        "# Consigne de sortie\n\n" + _strip_front((SKILLS / "l3-matchups" / "strategie_agent.md").read_text("utf-8")),
        "# Méthode d'analyse de liste\n\n" + _strip_front((SKILLS / "list-analysis" / "SKILL.md").read_text("utf-8")),
        "# Principes et règles de jeu (utilisateur)\n\n" + _section(l3, "Principes stratégiques") + "\n\n"
        + _section(l3, "Règles de jeu"),
    ]
    for name in MEMORIES:
        p = MEMORY / f"{name}.md"
        if p.exists():
            parts.append(f"# Mémoire `{name}`\n\n" + _strip_front(p.read_text(encoding="utf-8")))
    parts.append("# Scénarios de la ligue (scenarios.json)\n\n" + json.dumps(scen, ensure_ascii=False))
    parts.append("# Exemple de profondeur attendue (analyse de l'utilisateur sur Cromba — ton et niveau, "
                 "ne pas recopier)\n\n" + json.dumps(example, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- paquet (par liste)

def _aide(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        return "*Aide de jeu FR absente.*", ["aide de jeu FR absente"]
    data = json.loads(path.read_text(encoding="utf-8"))
    seen, lines = set(), []
    for section, cards in data.items():
        for c in cards:
            key = (c.get("name"), (c.get("description") or "")[:80])
            dup = key[0] in {k[0] for k in seen}
            if key in seen:
                continue
            seen.add(key)
            meta = " ; ".join(x for x in (c.get("phase"), c.get("cost"), c.get("keywords")) if x)
            cond = f" [{c['condition']}]" if c.get("condition") else ""
            who = f" — unités : {', '.join(c['unites'])}" if c.get("unites") else ""
            lines.append(f"- ({section}) **{c.get('name')}**{' (2e version)' if dup else ''} ({meta}){cond} : "
                         f"{(c.get('description') or '').strip()}{who}")
    return "\n".join(lines), []


def _cards(export: str) -> tuple[str, list[str], list[str]]:
    m = re.search(r"Battle Tactic Cards:\s*(.+)", export)
    names = [n.strip() for n in m.group(1).split(",")] if m else []
    all_cards = json.loads((ROOT / "data" / "json" / "battle_tactic_cards.json").read_text(encoding="utf-8"))
    def key(n: str) -> str:  # l'App écrit « Smokescreen », la carte « Smoke Screen »
        return n.casefold().replace(" ", "")

    by = {key(c["name_en"]): c for c in all_cards}
    found = [by[key(n)] for n in names if key(n) in by]
    issues = [f"carte de tactique inconnue : {n}" for n in names if key(n) not in by]
    if not names:
        issues.append("ligne « Battle Tactic Cards: » absente de l'export")
    subs = [s["name"] for c in found for s in c["sub_tactics"]]
    text = json.dumps(found, ensure_ascii=False, indent=1)
    return text, subs, issues


def build_pack(entry: dict, work: Path) -> tuple[str, list[str]]:
    """Message utilisateur de la liste, et noms exacts des sous-tactiques attendus dans `niveaux`."""
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([PY, str(ROOT / "scratch" / "list_dossier.py"), str(entry["txt"]), str(work)], cwd=ROOT,
                   check=True, capture_output=True)
    stem = entry["txt"].name.split(" ")[0].strip()
    c4 = (work / f"{stem} - couche 4.md").read_text(encoding="utf-8")
    textes = (work / f"{stem} - textes.md").read_text(encoding="utf-8")
    diag = subprocess.run([PY, "-m", "aospy", "l3", "diag", "--player", entry["player"]], cwd=ROOT,
                          capture_output=True, text=True).stdout
    export = entry["txt"].read_text(encoding="utf-8")
    aide, issues = _aide(entry["aide"])
    cards, subs, card_issues = _cards(export)
    issues += card_issues
    issues += [ln.strip("- ") for ln in textes.splitlines() if "NON RECONNUE" in ln]
    existing = {k: v for k, v in entry["combos"].items() if k != "strategie"}
    msg = [
        f"# Liste à analyser : équipe « {entry['team']} », joueur « {entry['player']} » "
        f"(fichier combos `{entry['file']}.json`), date du jour {dt.date.today().isoformat()}",
        "## Contrôles automatiques\n\n" + ("\n".join(f"- {i}" for i in issues) or "- rien à signaler "
                                           "(toutes les unités reconnues, cartes connues)"),
        "## Export de l'App\n\n```\n" + export + "\n```",
        "## Cartes de tactique de l'export (verbatim FR, battle_tactic_cards.json)\n\n"
        f"Noms exacts des sous-tactiques, à reprendre tels quels dans `tactiques.niveaux` : {subs}\n\n"
        "```json\n" + cards + "\n```",
        "## Fiche couche 4 (moteur)\n\n" + c4,
        "## Textes et profils (Wahapedia en base)\n\n" + textes,
        "## Aide de jeu FR (fait foi ; cartes deploy/any/mine/enemy/warscrolls)\n\n" + aide,
        "## Diagnostic `aospy l3 diag --player`\n\n```\n" + diag + "\n```",
        "## Entrée combos existante — ne la lire qu'APRÈS avoir fait ton analyse, pour `desaccords_combos` "
        "seulement\n\n```json\n" + json.dumps(existing, ensure_ascii=False, indent=1) + "\n```",
    ]
    return "\n\n".join(msg), subs


# --------------------------------------------------------------------------- appel et validation

def _extract(text: str) -> dict:
    m = re.search(r"```json\s*(\{.*\})\s*```", text, flags=re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw, strict=False)  # strict=False : retours à la ligne bruts dans les chaînes
    except json.JSONDecodeError:
        return json.loads(re.sub(r",(\s*[\]}])", r"\1", raw), strict=False)  # virgules finales


def validate(d: dict, subs: list[str]) -> list[str]:
    errs = [f"clé manquante : {k}" for k in REQUIRED if k not in d]
    niv = (d.get("tactiques") or {}).get("niveaux") or {}
    errs += [f"niveau manquant : {s}" for s in subs if s not in niv]
    errs += [f"sous-tactique inconnue : {k}" for k in niv if k not in subs]
    errs += [f"niveau invalide : {k} = {v}" for k, v in niv.items() if v not in LEVELS]
    if not (d.get("strategie") or {}).get("analyse"):
        errs.append("strategie.analyse vide")
    return errs


def run_one(entry: dict, sys_file: Path, model: str, work_root: Path, pack_only: bool,
            reparse: bool = False) -> str:
    work = work_root / entry["player"]
    user, subs = build_pack(entry, work)
    (work / "paquet.md").write_text(user, encoding="utf-8")
    if pack_only:
        return f"{entry['player']} : paquet {len(user) // 1000} ko → {work / 'paquet.md'}"
    saved = work / "reponse.json"
    if reparse and saved.exists():
        stdout = saved.read_text(encoding="utf-8")
    else:
        cmd = ["claude", "-p", "--model", model, "--tools", "", "--output-format", "json",
               "--system-prompt-file", str(sys_file)]
        res = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=work, timeout=1800)
        stdout = res.stdout or res.stderr
        saved.write_text(stdout, encoding="utf-8")
    try:
        meta = json.loads(stdout)
        d = _extract(meta["result"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        return f"{entry['player']} : ÉCHEC lecture de la réponse ({e}) → {work / 'reponse.json'}"
    d.setdefault("equipe", entry["team"])
    d.setdefault("joueur", entry["player"])
    d["auteur"] = f"claude {model} (brouillon un passage, à valider)"
    errs = validate(d, subs)
    if errs:
        d.setdefault("controles", []).extend(f"[validation] {e}" for e in errs)
    out = AUTO / entry["file"] / f"{entry['player']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    u = meta.get("usage", {})
    log = {"date": dt.datetime.now().isoformat(timespec="seconds"), "joueur": entry["player"], "model": model,
           "input": u.get("input_tokens"), "cache_creation": u.get("cache_creation_input_tokens"),
           "cache_read": u.get("cache_read_input_tokens"), "output": u.get("output_tokens"),
           "cost_usd": meta.get("total_cost_usd"), "duration_s": round((meta.get("duration_ms") or 0) / 1000),
           "errors": errs}
    with (AUTO / "_usage.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")
    tok = sum(x or 0 for x in (log["input"], log["cache_creation"], log["cache_read"], log["output"]))
    flag = f" — {len(errs)} erreur(s) de validation" if errs else ""
    return f"{entry['player']} : ok, {tok // 1000} k tokens, {log['duration_s']} s{flag}"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Brouillons stratégiques des listes L3 en un passage (claude -p).")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--player", nargs="+", help="joueur(s)")
    sel.add_argument("--team", nargs="+", help="équipe(s) : nom affiché ou fichier combos (ex. Limoges_Wargame)")
    sel.add_argument("--ronde", type=int, nargs="+", help="adversaires de nos équipes à ces rondes")
    sel.add_argument("--all", action="store_true", help="toutes les listes adverses")
    ap.add_argument("--force", action="store_true", help="refaire même si un brouillon ou une stratégie validée existe")
    ap.add_argument("--jobs", type=int, default=3, help="appels en parallèle (défaut 3)")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--pack-only", action="store_true", help="écrire les paquets sans appeler le modèle")
    ap.add_argument("--list", action="store_true", help="afficher la sélection sans rien faire")
    ap.add_argument("--reparse", action="store_true",
                    help="relire la réponse déjà reçue (reponse.json) au lieu de rappeler le modèle")
    args = ap.parse_args(argv)

    entries = index()
    if args.player:
        entries = [e for e in entries if e["player"] in args.player]
    elif args.team:
        entries = [e for e in entries if e["team"] in args.team or e["file"] in args.team]
    else:
        teams = (set().union(*(opponents_of_round(n) for n in args.ronde)) if args.ronde
                 else {e["team"] for e in entries if e["file"] not in OURS})
        entries = [e for e in entries if e["team"] in teams]
    if not args.force:
        entries = [e for e in entries if not (AUTO / (e["file"] or "?") / f"{e['player']}.json").exists()
                   and "strategie" not in e["combos"]]
    missing = [e["player"] for e in entries if not e["file"]]
    entries = [e for e in entries if e["file"]]
    if missing:
        print("sans fichier combos (ignorés) :", ", ".join(missing))
    print(f"{len(entries)} liste(s) : " + ", ".join(f"{e['player']} ({e['team']})" for e in entries))
    if args.list or not entries:
        return
    work_root = Path(tempfile.gettempdir()) / "aospy-draft-pack"
    work_root.mkdir(exist_ok=True)
    sys_file = work_root / "methode.md"
    sys_file.write_text(method(), encoding="utf-8")
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        def job(e: dict) -> str:
            return run_one(e, sys_file, args.model, work_root, args.pack_only, args.reparse)

        for line in ex.map(job, entries):
            print(line, flush=True)
    if not args.pack_only:
        for team in sorted({e["file"] for e in entries}):
            drafts.render_team(AUTO / team)


if __name__ == "__main__":
    sys.exit(main())
