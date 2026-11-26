"""Réécrit la section « 10. Scénarios » des 54 analyse.md depuis notes_scenarios.json (même rendu que
scratch/fusion_notes_scenarios.py), sans toucher aux notes. Usage : python scratch/scenario_model/rafraichir_section10.py"""
import importlib.util, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fusion", ROOT / "scratch" / "fusion_notes_scenarios.py")
fusion = importlib.util.module_from_spec(spec); spec.loader.exec_module(fusion)
N = json.loads((fusion.BASE / "notes_scenarios.json").read_text(encoding="utf-8"))
order = [s["cle"] for s in json.loads((fusion.BASE / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]]
ALIAS = {"Sharowkyn": "Sharowkin", "Cartoone": "Cartoon", "Laytorne": "Laytorn", "MuaD_Dib": "Muad_Dib"}  # noms de dossier
done, miss = 0, []
for eq, T in N["equipes"].items():
    for j, e in T["joueurs"].items():
        paths = [p for p in (ROOT / "scratch/output/liste_analyse" / eq).glob("*/*/analyse.md") if p.parts[-3].startswith(ALIAS.get(j, j) + "-")]
        if len(paths) != 1:
            miss.append(f"{eq}/{j} : {len(paths)} fichier(s)"); continue
        p = paths[0]; txt = p.read_text(encoding="utf-8")
        if "\n## 10. Scénarios\n" not in txt:
            miss.append(f"{eq}/{j} : pas de section 10"); continue
        new = re.sub(r"\n## 10\. Scénarios\n.*?(?=\n## |\Z)", "\n" + fusion.section(order, e).rstrip("\n"), txt, flags=re.S)
        if not new.endswith("\n"): new += "\n"
        if new != txt: p.write_text(new, encoding="utf-8"); done += 1
print("réécrits :", done); print("\n".join(miss) or "aucun manque")
