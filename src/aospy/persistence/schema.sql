-- Schéma DuckDB pour AoSPy (AoS 4e édition)
-- Phase 1 : armées, unités, armes
-- Phase 2 : traits héroïques, artefacts, compositions

CREATE SEQUENCE IF NOT EXISTS seq_army_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_unit_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_weapon_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_heroic_trait_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_artefact_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_composition_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_composition_unit_id START 1;

CREATE TABLE IF NOT EXISTS army (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_army_id'),
    name            VARCHAR NOT NULL UNIQUE,
    grand_alliance  VARCHAR NOT NULL CHECK (grand_alliance IN ('Order', 'Chaos', 'Death', 'Destruction'))
);

CREATE TABLE IF NOT EXISTS unit (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_unit_id'),
    army_id         INTEGER NOT NULL REFERENCES army(id),
    name            VARCHAR NOT NULL,
    move            INTEGER NOT NULL,           -- pouces
    save            INTEGER NOT NULL,           -- ex: 4 pour 4+
    health          INTEGER NOT NULL,           -- par modèle
    control         INTEGER NOT NULL,           -- par modèle
    models          INTEGER NOT NULL,           -- taille d'unité de base
    points          INTEGER NOT NULL,
    is_hero         BOOLEAN NOT NULL DEFAULT FALSE,
    ward            INTEGER,                    -- ex: 5 pour 5+, NULL si aucun
    keywords        VARCHAR NOT NULL DEFAULT '', -- mots-clés joints par virgule (MAJUSCULES)
    description     VARCHAR,                    -- texte libre de restriction d'armement (cf. loadout.py)
    imported_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, -- rafraîchi à chaque import (cf. replace_unit) ; permet de purger les lignes qu'un import n'a plus touchées
    UNIQUE(army_id, name)
);
-- NB : imported_at est dans le CREATE TABLE (pas un ALTER ADD COLUMN IF NOT
-- EXISTS comme keywords/description ci-dessous) — un ALTER ADD COLUMN IF NOT
-- EXISTS ré-exécuté sur une colonne déjà existante réinitialise silencieusement
-- sa valeur à sa DEFAULT à chaque connect() (bug DuckDB constaté), ce qui
-- viderait `imported_at` de son sens à chaque commande.

-- Migration : ajoute keywords/description si la table existait sans elles
ALTER TABLE unit ADD COLUMN IF NOT EXISTS keywords VARCHAR DEFAULT '';
ALTER TABLE unit ADD COLUMN IF NOT EXISTS description VARCHAR;

CREATE TABLE IF NOT EXISTS weapon (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_weapon_id'),
    unit_id         INTEGER NOT NULL REFERENCES unit(id),
    name            VARCHAR NOT NULL,
    kind            VARCHAR NOT NULL CHECK (kind IN ('melee', 'ranged')),
    range_in        INTEGER NOT NULL DEFAULT 1, -- pouces (1 pour mêlée standard)
    attacks         INTEGER NOT NULL,
    hit             INTEGER NOT NULL,           -- ex: 3 pour 3+
    wound           INTEGER NOT NULL,
    rend            INTEGER NOT NULL DEFAULT 0, -- valeur positive (0,1,2…) appliquée en -X
    damage          INTEGER NOT NULL,
    abilities       VARCHAR,                    -- texte libre (crit/anti/…)
    wielders        INTEGER NOT NULL DEFAULT 0  -- nb de modèles porteurs (0 = tous)
);

-- Migration : ajoute la colonne wielders si la table existait sans elle
-- (DuckDB n'autorise pas NOT NULL sur ADD COLUMN ; le DEFAULT 0 suffit en pratique)
ALTER TABLE weapon ADD COLUMN IF NOT EXISTS wielders INTEGER DEFAULT 0;

-- Traits héroïques (spécifiques à une armée en AoS 4)
CREATE TABLE IF NOT EXISTS heroic_trait (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_heroic_trait_id'),
    army_id         INTEGER NOT NULL REFERENCES army(id),
    name            VARCHAR NOT NULL,
    description     VARCHAR,
    UNIQUE(army_id, name)
);

-- Artefacts de pouvoir (spécifiques à une armée en AoS 4)
CREATE TABLE IF NOT EXISTS artefact (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_artefact_id'),
    army_id         INTEGER NOT NULL REFERENCES army(id),
    name            VARCHAR NOT NULL,
    description     VARCHAR,
    UNIQUE(army_id, name)
);

-- Composition d'armée (liste). kind = tournament | custom
CREATE TABLE IF NOT EXISTS composition (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_composition_id'),
    army_id         INTEGER NOT NULL REFERENCES army(id),
    name            VARCHAR NOT NULL,
    kind            VARCHAR NOT NULL CHECK (kind IN ('tournament', 'custom')),
    format_points   INTEGER NOT NULL,                       -- ex: 2000
    total_points    INTEGER NOT NULL,                       -- somme des points
    source          VARCHAR,                                -- URL / tournoi / auteur
    notes           VARCHAR,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(army_id, name)
);

-- Entrées d'une composition : 1 ligne = 1 unité sur la liste
CREATE TABLE IF NOT EXISTS composition_unit (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_composition_unit_id'),
    composition_id  INTEGER NOT NULL REFERENCES composition(id),
    unit_id         INTEGER NOT NULL REFERENCES unit(id),
    reinforced      BOOLEAN NOT NULL DEFAULT FALSE,         -- double modèles + double points
    is_general      BOOLEAN NOT NULL DEFAULT FALSE,
    heroic_trait_id INTEGER REFERENCES heroic_trait(id),
    artefact_id     INTEGER REFERENCES artefact(id)
);

-- Résultats persistés des duels unité vs unité (1 round). `attacker_mode`/
-- `defender_mode` ('mean'/'floor80'/'floor95') contrôlent indépendamment la
-- lecture du dégât de chaque sens : 'mean' = dégât espéré, 'floor80'/'floor95' =
-- plancher de dégât à 80%/95% de confiance (combat.py::damage_floor80/damage_floor95,
-- moyenne − z·σ) — un duel n'est donc pas nécessairement symétrique dans sa lecture.
-- Les variantes coexistent (clé incluant les deux modes), calculées par
-- `benchmark.py::unit_duel(..., mode_a=..., mode_b=...)`.
CREATE TABLE IF NOT EXISTS unit_benchmark (
    attacker_id         INTEGER NOT NULL REFERENCES unit(id),
    defender_id         INTEGER NOT NULL REFERENCES unit(id),
    attacker_reinforced BOOLEAN NOT NULL DEFAULT FALSE,
    defender_reinforced BOOLEAN NOT NULL DEFAULT FALSE,
    attacker_charged    BOOLEAN NOT NULL DEFAULT FALSE,
    defender_charged    BOOLEAN NOT NULL DEFAULT FALSE,
    attacker_mode       VARCHAR NOT NULL DEFAULT 'mean',
    defender_mode       VARCHAR NOT NULL DEFAULT 'mean',
    raw_a_to_b          DOUBLE NOT NULL,
    expected_a_to_b     DOUBLE NOT NULL,
    raw_b_to_a          DOUBLE NOT NULL,
    expected_b_to_a     DOUBLE NOT NULL,
    pts_destroyed       DOUBLE NOT NULL,
    pts_lost            DOUBLE NOT NULL,
    pts_net             DOUBLE NOT NULL,
    roi                 DOUBLE NOT NULL,
    computed_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (attacker_id, defender_id,
                 attacker_reinforced, defender_reinforced,
                 attacker_charged, defender_charged,
                 attacker_mode, defender_mode)
);
-- Pas d'ALTER TABLE ADD COLUMN IF NOT EXISTS ici (contrairement à wielders/keywords
-- ci-dessus) : `attacker_mode`/`defender_mode` font déjà partie du CREATE TABLE. Un
-- ALTER ADD COLUMN IF NOT EXISTS réexécuté à chaque connect() sur une colonne déjà
-- présente réinitialise silencieusement toutes les valeurs à sa DEFAULT (bug DuckDB
-- constaté) — inutile de toute façon puisqu'aucune base existante ne préexistait
-- sans ces colonnes. La migration `floor80` (colonne booléenne) -> `floor95` puis
-- `floor95` -> `attacker_mode`/`defender_mode` (reconstruction de la table, clé
-- primaire changée) est gérée dans db.py::connect() avant l'exécution de ce schéma.
