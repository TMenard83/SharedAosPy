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
    wielders        INTEGER NOT NULL DEFAULT 0, -- nb de modèles porteurs (0 = tous)
    is_companion    BOOLEAN NOT NULL DEFAULT FALSE -- hérité d'une sous-entrée gratuite fusionnée (BSData)
);

-- Migration : ajoute wielders si la table existait sans elle
-- (DuckDB n'autorise pas NOT NULL sur ADD COLUMN ; le DEFAULT suffit en pratique)
ALTER TABLE weapon ADD COLUMN IF NOT EXISTS wielders INTEGER DEFAULT 0;
-- is_companion (BOOLEAN) n'a volontairement PAS son propre ADD COLUMN IF NOT EXISTS
-- ici : contrairement à wielders (INTEGER) ou keywords/description (VARCHAR),
-- une colonne BOOLEAN réinitialise silencieusement sa valeur à sa DEFAULT quand
-- cette instruction est ré-exécutée sur une colonne déjà existante (constaté
-- empiriquement, cf. db.py::_migrate_weapon_is_companion) — la migration est donc
-- gardée en Python (exécutée une seule fois, jamais réémise une fois la colonne
-- présente) plutôt que placée ici.

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
-- `defender_mode` ('mean'/'floor66'/'floor80'/'floor95') contrôlent indépendamment
-- la lecture du dégât de chaque sens : 'mean' = dégât espéré, 'floor66'/'floor80'/
-- 'floor95' = plancher de dégât à 66%/80%/95% de confiance
-- (combat.py::damage_floor66/damage_floor80/damage_floor95, moyenne − z·σ) — un
-- duel n'est donc pas nécessairement symétrique dans sa lecture.
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

-- ----- Analyse des aptitudes (`aospy ability analyze`, src/aospy/abilities/) -----
-- Reconstruites en entier à chaque analyse (DELETE + INSERT), à partir des CSV
-- Wahapedia : aucune clé étrangère vers `unit` (les aptitudes existent même
-- pour des warscrolls non importées) — la jointure passe par la vue
-- `unit_ability` ci-dessous (nom de warscroll + nom de faction).
-- Axes notés 0-3 (3 = facile / fort / fiable / profite à toute l'armée) ;
-- `verdict` ∈ plan / pari / anecdotique / a-revoir.
CREATE TABLE IF NOT EXISTS ability (
    uid              VARCHAR PRIMARY KEY,   -- empreinte stable nom+condition+texte
    name             VARCHAR NOT NULL,
    source_kind      VARCHAR NOT NULL,      -- warscroll, battle_trait, spell…
    group_name       VARCHAR,               -- formation / domaine / sous-type
    faction_id       VARCHAR,               -- premier porteur
    faction_name     VARCHAR,
    condition_text   VARCHAR,               -- timing Wahapedia nettoyé
    phase            VARCHAR,
    wahapedia_type   VARCHAR,
    is_reaction      BOOLEAN,
    ability_keywords VARCHAR,
    cost_type        VARCHAR,               -- Spell / Prayer / Command / …
    cost_value       VARCHAR,
    declare_text     VARCHAR,
    effect_text      VARCHAR,
    frequency        VARCHAR,               -- passive, once_per_turn_army…
    turn_side        VARCHAR,               -- yours / enemy / any / deployment / round_start
    scope            VARCHAR,               -- self, one_friendly, friendly_aura, army…
    range_inches     INTEGER,
    wholly_within    BOOLEAN,
    activation_prob  DOUBLE,                -- P(déclenchement) hors contexte
    variance         VARCHAR,               -- fixe / des / binomial
    scales_with_size BOOLEAN,
    target_keywords  VARCHAR,               -- Anti-X, séparés par des virgules
    conditions       VARCHAR,               -- prérequis, séparés par ' | '
    ease             DOUBLE,
    power            DOUBLE,
    reliability      DOUBLE,
    interaction      DOUBLE,
    verdict          VARCHAR,
    rationale        VARCHAR,               -- justification, une ligne par axe
    understood       BOOLEAN,
    overridden       BOOLEAN,
    analyzer_version INTEGER,
    analyzed_at      TIMESTAMP
);

-- Porteurs d'une aptitude : warscroll(s), ou groupe de règle de faction.
CREATE TABLE IF NOT EXISTS ability_owner (
    ability_uid  VARCHAR NOT NULL,
    faction_id   VARCHAR NOT NULL,
    faction_name VARCHAR NOT NULL,
    owner_kind   VARCHAR NOT NULL,          -- warscroll / faction_rule
    owner_name   VARCHAR NOT NULL,
    warscroll_id VARCHAR,
    PRIMARY KEY (ability_uid, faction_id, owner_kind, owner_name)
);

-- Tags d'utilité (vocabulaire : `aospy ability tags`, abilities/tags.py::ALL_TAGS).
CREATE TABLE IF NOT EXISTS ability_tag (
    ability_uid VARCHAR NOT NULL,
    tag         VARCHAR NOT NULL,
    PRIMARY KEY (ability_uid, tag)
);

-- Effets chiffrés reconnus (abilities/extract.py).
CREATE TABLE IF NOT EXISTS ability_effect (
    ability_uid VARCHAR NOT NULL,
    seq         INTEGER NOT NULL,
    kind        VARCHAR NOT NULL,           -- stat_mod, mortal_damage, ward, heal…
    stat        VARCHAR,
    value       DOUBLE,
    dice        VARCHAR,
    side        VARCHAR,                    -- friendly / enemy
    detail      VARCHAR,
    PRIMARY KEY (ability_uid, seq)
);

-- Unité importée ↔ aptitudes de sa warscroll (jointure par nom, insensible à la casse).
CREATE OR REPLACE VIEW unit_ability AS
SELECT u.id AS unit_id, u.name AS unit_name, ar.name AS army_name, a.*
FROM unit u
JOIN army ar ON ar.id = u.army_id
JOIN ability_owner o ON o.owner_kind = 'warscroll'
                    AND lower(o.owner_name) = lower(u.name)
                    AND o.faction_name = ar.name
JOIN ability a ON a.uid = o.ability_uid;

-- Analyseur v2 : coût cumulé en ressource de faction (Dîme de Sang…) et round de
-- disponibilité estimé. ADD COLUMN IF NOT EXISTS sans danger ici : la table est
-- entièrement reconstruite par chaque `aospy ability analyze`.
ALTER TABLE ability ADD COLUMN IF NOT EXISTS resource_cost INTEGER;
ALTER TABLE ability ADD COLUMN IF NOT EXISTS available_round INTEGER;
-- Analyseur v6 : restriction de la cible amie telle qu'écrite (« non-HERO WARRIORS OF CHAOS INFANTRY »),
-- résolue contre les mots-clés d'unité par la couche 3 (analysis/encounter.py). Table reconstruite à
-- chaque analyse : ADD COLUMN IF NOT EXISTS sans danger.
ALTER TABLE ability ADD COLUMN IF NOT EXISTS friendly_target VARCHAR;
-- Analyseur v10 : « another/other friendly » — le porteur ne peut pas recevoir l'effet (couche 3).
ALTER TABLE ability ADD COLUMN IF NOT EXISTS excludes_self BOOLEAN;

-- Analyseur v5 : périmètre de chaque effet (abilities/perimeter.py) — ce qu'il faut savoir
-- pour l'appliquer à un châssis (couche 3) : armes visées, cible exigée, prérequis, durée.
-- ADD COLUMN IF NOT EXISTS sans danger : `ability_effect` est reconstruite à chaque analyse.
ALTER TABLE ability_effect ADD COLUMN IF NOT EXISTS weapon_scope VARCHAR;       -- melee/ranged/named/chosen/all
ALTER TABLE ability_effect ADD COLUMN IF NOT EXISTS weapon_name VARCHAR;
ALTER TABLE ability_effect ADD COLUMN IF NOT EXISTS includes_companion BOOLEAN; -- Compagnon exclues par défaut
ALTER TABLE ability_effect ADD COLUMN IF NOT EXISTS target_keywords VARCHAR;    -- ex. 'HERO,MONSTER'
ALTER TABLE ability_effect ADD COLUMN IF NOT EXISTS target_condition VARCHAR;
ALTER TABLE ability_effect ADD COLUMN IF NOT EXISTS requires VARCHAR;           -- prérequis propre à l'effet
ALTER TABLE ability_effect ADD COLUMN IF NOT EXISTS duration VARCHAR;           -- permanent/tour/phase/round/bataille…

-- Couche 2 — châssis (analysis/chassis.py, `aospy chassis build`) : la charte nue, sans aptitudes.
-- Reconstruite en entier à chaque build (DELETE + INSERT). `*_pct_rank` : rang centile (0-1)
-- au sein du même segment (héros / troupes). `cost_residual_pct` < 0 = moins cher que ce que le
-- modèle de coût prédit pour ce châssis ; `duel_roi_pct` = avg_floor_roi_pct des duels
-- (unit_benchmark, floor66/mean, sans charge) — NULL si non calculés.
CREATE TABLE IF NOT EXISTS unit_chassis (
    unit_id               INTEGER PRIMARY KEY,
    name                  VARCHAR NOT NULL,
    army_id               INTEGER NOT NULL,
    points                INTEGER NOT NULL,
    is_hero               BOOLEAN NOT NULL,
    unit_type             VARCHAR,
    models                INTEGER,
    health                INTEGER,
    save                  INTEGER,
    ward                  INTEGER,
    move                  INTEGER,
    is_flying             BOOLEAN,
    dmg_melee             DOUBLE,      -- dégâts moyens / round vs sauvegarde 4+
    dmg_ranged            DOUBLE,
    effective_wounds      DOUBLE,      -- coups à porter pour tuer l'unité
    dmg_per_100           DOUBLE,
    ewounds_per_100       DOUBLE,
    attacks_total         DOUBLE,
    share_melee           DOUBLE,      -- part des dégâts (0-1)
    share_damage1         DOUBLE,      -- … venant d'armes à 1 dégât
    share_companion       DOUBLE,      -- … venant d'armes Compagnon
    crit_type             VARCHAR,
    dmg_pct_rank          DOUBLE,
    ewounds_pct_rank      DOUBLE,
    cost_residual_pct     DOUBLE,
    duel_roi_pct          DOUBLE,
    built_at              TIMESTAMP
);

-- Couche 3 — rencontre aptitude × châssis (analysis/encounter.py, `aospy encounter build`) : gain
-- d'un effet ami (`ability_effect`) sur le châssis de chaque receveur possible, mesuré au moteur
-- (dégâts d'un round vs save 4+ ; coups à porter pour tuer). Valeurs « si l'effet s'applique » :
-- fiabilité/durée/prérequis restent à pondérer au-dessus. Reconstruite en entier à chaque build.
CREATE TABLE IF NOT EXISTS ability_encounter (
    ability_uid       VARCHAR NOT NULL,
    seq               INTEGER NOT NULL,     -- rang de l'effet dans ability_effect
    unit_id           INTEGER NOT NULL,
    relation          VARCHAR,              -- porteur / allié
    source            VARCHAR,              -- charte porteuse, ou « <origine>: <groupe> » (formation, AoR…)
    off_before        DOUBLE,
    off_after         DOUBLE,
    off_gain_pct      DOUBLE,               -- NULL si le châssis ne fait aucun dégât
    off_gain_per_100  DOUBLE,               -- dégâts gagnés pour 100 pts du receveur
    def_before        DOUBLE,
    def_after         DOUBLE,
    def_gain_pct      DOUBLE,
    def_gain_per_100  DOUBLE,
    conditions        VARCHAR,              -- prérequis/ciblage de l'effet (« a chargé | vs HERO »)
    duration          VARCHAR,
    PRIMARY KEY (ability_uid, seq, unit_id)
);

-- Couche 3 — valeur réalisée par unité (analysis/realized.py) : châssis + ses propres aptitudes qui la
-- boostent, pondérées (rounds 2-3 = 1, 1/4/5 = 1/3 ; une fois par bataille courte = 1/2 ; × P(déclenchement)).
-- `*_realized` sans les effets conditionnels, `*_good_case` avec (« dans le bon cas »).
-- off = dégâts d'un round vs save 4+ ; def = coups à porter pour tuer. Reconstruite à chaque build.
CREATE TABLE IF NOT EXISTS unit_realized (
    unit_id               INTEGER PRIMARY KEY,
    off_chassis           DOUBLE,
    def_chassis           DOUBLE,
    off_realized          DOUBLE,
    def_realized          DOUBLE,
    off_good_case         DOUBLE,
    def_good_case         DOUBLE,
    off_realized_per_100  DOUBLE,
    def_realized_per_100  DOUBLE,
    off_good_per_100      DOUBLE,
    def_good_per_100      DOUBLE,
    off_pct_rank          DOUBLE,      -- centile au sein des héros / des troupes
    def_pct_rank          DOUBLE,
    n_effects             INTEGER,
    n_conditional         INTEGER,
    abilities             VARCHAR      -- aptitudes propres prises en compte, séparées par ' | '
);
