#!/bin/bash
# Régénère couche 4 + textes + diag + scenario_model des listes L3 (sans toucher analyse.md).
# Saute les dossiers dont la fiche couche 4 est plus récente que le fichier repère $1 (optionnel).
cd /home/tmenard/Dev/Python/aospy
REF="$1"
L="data/2026-27 L3 Aller/Listes texte"
for f in "$L"/*/*.txt; do
  team=$(basename "$(dirname "$f")"); p=$(basename "$f" .txt)
  d=$(ls -d "scratch/output/liste_analyse/$team/$p-"*/"L3 aller" 2>/dev/null | head -1)
  [ -z "$d" ] && d=$(ls -d "scratch/output/liste_analyse/$team/"*/*/ 2>/dev/null | grep -i "/${p:0:6}" | head -1)
  [ -z "$d" ] && { echo "$team|$p|SANS DOSSIER"; continue; }
  if [ -n "$REF" ] && [ -n "$(find "$d" -maxdepth 1 -name '*couche 4.md' -newer "$REF" | head -1)" ]; then echo "$team|$p|déjà fait"; continue; fi
  .venv/bin/python -m aospy roster dossier --list "$f" --out "$d" > "$d/dossier.log" 2>&1; rc=$?
  .venv/bin/python -m aospy l3 diag --player "$p" > "$d/diag.txt" 2>&1
  .venv/bin/python -m aospy l3 scenario-model --player "$p" --tactiques > "$d/scenario_model.txt" 2>&1
  echo "$team|$p|rc=$rc|$d"
done
