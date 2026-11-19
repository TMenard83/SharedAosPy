# Simulateur de bonus

IHM Streamlit pour tester en direct l'effet d'un bonus (règle d'armée ou libre)
sur une unité : profil avant/après, impact sur un duel de référence, et
position dans les classements combat×coût — sans jamais écrire en base ni
régénérer de PDF. Inspiré de [aos-statshammer](https://aos-statshammer.herokuapp.com/).

## Installation

```bash
pip install -e ".[gui]"   # installe streamlit + l'extra [analysis] (pandas/statsmodels)
```

## Lancement

```bash
streamlit run src/aospy/bonus_simulator/app.py
```

Streamlit affiche une URL locale (par défaut `http://localhost:8501`) et tente
d'ouvrir le navigateur automatiquement.

**Premier lancement** : Streamlit demande une adresse e-mail (onboarding). Pour
répondre en une fois et ne plus être interrompu (utile en lancement
non-interactif, ex. arrière-plan) :

```bash
mkdir -p ~/.streamlit
printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
```

**Prérequis pour la section « Classement »** : elle lit la table `unit_benchmark`
(via `whatif.rank_against_pool`), donc il faut l'avoir peuplée au moins une
fois, avec les mêmes modes que ceux attendus par `whatif.py` :

```bash
aospy unit benchmark-all --charge none --attacker-mode floor66 --defender-mode mean --include-heroes
```

Sans ça, l'IHM reste utilisable (profil et impact duel fonctionnent toujours)
mais affiche un avertissement à la place du classement.

## Utilisation

1. **Armée** puis **Unité** (barre latérale, deux menus déroulants en cascade).
2. **Bonus d'armée** : coche une ou plusieurs règles listées pour l'armée
   sélectionnée (curatées dans `data/json/army_rules.json` — voir plus bas).
3. **Bonus libre** : ajuste toucher/blesser/rend/save/ward/dégât/attaques à la
   main (cumulable avec les règles cochées).
4. **Profil avant/après** : tableau des profils d'arme + save/ward, avant et
   après application du bonus net.
5. **Impact en duel** : ROI moyen (plancher 66%) et points nets moyens contre
   toutes les unités des autres armées, avant vs après.
6. **Classement combat × coût** : rang de l'unité (avec/sans bonus) dans le
   même pool que le « Panthéon des Champions » (`reports/best_unites.py`/
   `best_heros.py`), troupes et héros séparés, avec les rangs voisins.

## Ajouter une règle d'armée

Éditer `data/json/army_rules.json` (liste plate, un objet par règle) :

```json
{
  "army": "Nom exact de l'armée (colonne `army.name`)",
  "name": "Nom de la règle",
  "description": "Texte affiché à côté de la case à cocher",
  "delta": {"wound": 1, "save": 1}
}
```

`delta` accepte n'importe quel sous-ensemble des champs de `bonus.StatDelta` :
`hit`, `wound`, `rend`, `save`, `ward`, `damage`, `attacks` (tous par défaut à
0). Rechargé à chaque lancement de l'IHM — pas de redémarrage de la base
nécessaire.

## Voir aussi

`CLAUDE.md` (section « Bonus simulator ») pour le détail d'architecture — quel
module fait quoi, pourquoi `DuelRules` est fixé explicitement, comment
`cost_model.predict_one` évite de ré-implémenter l'encodage catégoriel à la
main, etc.
