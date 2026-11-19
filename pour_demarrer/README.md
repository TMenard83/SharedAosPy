# Démarrer avec AoSPy (sans lire le code)

Ce dossier est le point d'entrée pour quelqu'un qui veut juste **utiliser** aospy,
sans connaître Python ni la CLI complète.

## 1. Installation (une seule fois)

Depuis la racine du projet :

```bash
pip install -e ".[dev,analysis,roster]"
aospy init
aospy import bsdata --all          # télécharge toutes les armées connues
```

(`aospy import bsdata --all` prend quelques minutes la première fois — il télécharge
les profils depuis GitHub.)

## 2. Lancer le script

```bash
python pour_demarrer/demarrer.py
```

Un menu s'affiche et pose les questions nécessaires :

1. **Générer le PDF d'une liste de tournoi** — choisit un fichier dans
   `data/Proposition de listes/`, choisit un mode de traduction, produit le PDF
   dans `scratch/output/roster/<équipe>/<liste>/`.
2. **Comparer deux unités en duel** — choisit une armée puis une unité pour
   l'attaquant et le défenseur, affiche le résultat détaillé du duel.
3. **Comparer une unité contre toutes les autres (benchmark)** — choisit une
   unité attaquante, l'affronte contre toutes les unités des autres armées.

Le script ne fait qu'appeler les commandes `aospy` existantes avec les réponses
données au clavier — il n'y a pas de logique dupliquée ici.

## 3. Pour aller plus loin (utilisateurs avancés)

Le menu ci-dessus ne couvre que les cas les plus courants, avec les valeurs par
défaut de la CLI. Beaucoup d'autres paramètres existent et restent accessibles
uniquement via la CLI complète (`aospy --help`, `aospy <commande> --help`) :

- **All-out Attack / All-out Defense** (`--aoa`, `--aod`) et **course + charge**
  (`--ran-and-charged`) sur `aospy unit duel`/`benchmark`.
- **Plancher de confiance plutôt que la moyenne** : `--attacker-mode`/
  `--defender-mode floor66|floor80|floor95` (lit la distribution exacte de dégâts
  plutôt que l'espérance).
- **Réglage fin des règles de charge/tir** : `--rule-double-shoot`/
  `--rule-charge-threshold` (activables/désactivables), `--charge-dist`,
  `--run-dist`.
- **Limiter le benchmark à une armée** (`--vs-army`), **trier les résultats**
  (`--sort-by pts-net|roi|net|atb|bta|points|army`), **limiter aux N premiers**
  (`--top`).
- **Persister tous les duels de toutes les unités** :
  `aospy unit benchmark-all --charge both --attacker-mode floor95 --defender-mode floor95`.
- **Simuler une bataille complète entre deux compositions** :
  `aospy battle simulate --a <comp_id> --b <comp_id> --charge both`.
- **Modèle de coût** (nécessite `[analysis]`) : `aospy cost fit`,
  `aospy cost residuals --top 20 --direction under`.
- **PDF de roster plus précis** : `--out <chemin>` pour choisir le fichier de
  sortie, `--mode fr`/`fr-extended` pour un vérbatim français plus complet.
- **Import ciblé ou alternatif** : `aospy import bsdata --army "<nom>"`,
  `aospy import wahapedia --faction "<nom>"`, `--clean-stale` pour purger les
  unités retirées d'une armée.

Pour le détail complet de chaque commande et de son fonctionnement interne, voir
le `CLAUDE.md` à la racine du projet.
