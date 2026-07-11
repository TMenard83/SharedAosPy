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
    UNIQUE(army_id, name)
);

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

-- Résultats persistés des duels unité vs unité (1 round, dégât espéré)
CREATE TABLE IF NOT EXISTS unit_benchmark (
    attacker_id         INTEGER NOT NULL REFERENCES unit(id),
    defender_id         INTEGER NOT NULL REFERENCES unit(id),
    attacker_reinforced BOOLEAN NOT NULL DEFAULT FALSE,
    defender_reinforced BOOLEAN NOT NULL DEFAULT FALSE,
    attacker_charged    BOOLEAN NOT NULL DEFAULT FALSE,
    defender_charged    BOOLEAN NOT NULL DEFAULT FALSE,
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
                 attacker_charged, defender_charged)
);
