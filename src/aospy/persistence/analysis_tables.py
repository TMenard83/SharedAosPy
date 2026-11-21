"""Colonnes des tables de résultats d'analyse (couches 3-4).

Définies ici, dans `persistence/`, pour que `repository.py` n'importe pas une couche supérieure ;
`analysis/` les réimporte pour construire ses tuples."""

#: Colonnes de `ability_encounter`, dans l'ordre des tuples produits par `analysis/encounter.py`.
ENCOUNTER_COLS = (
    "ability_uid", "seq", "unit_id", "relation", "source", "off_before", "off_after", "off_gain_pct", "off_gain_per_100",
    "def_before", "def_after", "def_gain_pct", "def_gain_per_100", "conditions", "duration",
)


#: Colonnes de `unit_realized`, dans l'ordre des tuples produits par `analysis/realized.py`.
REALIZED_COLS = (
    "unit_id", "off_chassis", "def_chassis", "off_realized", "def_realized", "off_good_case", "def_good_case",
    "off_realized_per_100", "def_realized_per_100", "off_good_per_100", "def_good_per_100",
    "off_pct_rank", "def_pct_rank", "n_effects", "n_conditional", "abilities",
    "combined_per_100", "combined_pct_rank",
    "off_fit", "def_fit", "off_fit_per_100", "def_fit_per_100", "combined_fit_per_100", "combined_fit_pct_rank",
    "reach_in", "mobility", "score_per_100", "score_pct_rank", "score_fit_per_100",
)


#: Colonnes de `ability_marriage`, dans l'ordre des tuples produits par `analysis/marriage.py`.
MARRIAGE_COLS = (
    "unit_id", "ability_uid", "ability_name", "family", "power", "verdict", "exposure", "p_trigger",
    "start_round", "bearer_only", "rounds_alive", "survival", "marriage", "good_case_conditions",
)


#: Colonnes de `enhancement_bearer`, dans l'ordre des tuples produits par `analysis/bearers.py`.
BEARER_COLS = (
    "ability_uid", "ability_name", "source_kind", "faction_name", "unit_id", "off_gain_pct", "def_gain_pct",
    "delta_combined", "coverage", "p_trigger", "survival", "marriage", "value", "bearer_combined",
    "good_case_conditions",
)
