"""Tables d'analyse des aptitudes (`ability`, `ability_owner`, `ability_tag`, `ability_effect`)."""

from __future__ import annotations

from typing import Iterable, Optional

import duckdb

from ._sql import _insert_rows

# ----- Analyse des aptitudes (src/aospy/abilities/) ---------------------------

ABILITY_COLS = (
    "uid", "name", "source_kind", "group_name", "faction_id", "faction_name", "condition_text",
    "phase", "wahapedia_type", "is_reaction", "ability_keywords", "cost_type", "cost_value",
    "declare_text", "effect_text", "frequency", "turn_side", "scope", "range_inches",
    "wholly_within", "activation_prob", "variance", "scales_with_size", "target_keywords",
    "conditions", "ease", "power", "reliability", "interaction", "verdict", "rationale",
    "understood", "overridden", "analyzer_version", "analyzed_at",
    "resource_cost", "available_round", "friendly_target", "excludes_self", "family",
    "bearer_restriction",
)
ABILITY_OWNER_COLS = ("ability_uid", "faction_id", "faction_name", "owner_kind", "owner_name", "warscroll_id")
ABILITY_TAG_COLS = ("ability_uid", "tag")
ABILITY_EFFECT_COLS = ("ability_uid", "seq", "kind", "stat", "value", "dice", "side", "detail",
                       "weapon_scope", "weapon_name", "includes_companion", "target_keywords",
                       "target_condition", "requires", "duration", "family", "friendly_target")
_ABILITY_TABLES = ("ability_effect", "ability_tag", "ability_owner", "ability")



def replace_ability_analyses(
    con: duckdb.DuckDBPyConnection,
    abilities: list[tuple],
    owners: list[tuple],
    tags: list[tuple],
    effects: list[tuple],
) -> None:
    """Remplace tout le contenu des tables `ability*` (une transaction).

    Les tuples suivent `ABILITY_COLS`/`ABILITY_OWNER_COLS`/`ABILITY_TAG_COLS`/
    `ABILITY_EFFECT_COLS` ; la conversion depuis `AbilityAnalysis` vit dans
    `abilities/pipeline.py::to_rows` (la persistance ne connaît pas ce modèle).
    """
    con.execute("BEGIN TRANSACTION")
    try:
        for table in _ABILITY_TABLES:
            con.execute(f"DELETE FROM {table}")
        _insert_rows(con, "ability", ABILITY_COLS, abilities)
        _insert_rows(con, "ability_owner", ABILITY_OWNER_COLS, owners)
        _insert_rows(con, "ability_tag", ABILITY_TAG_COLS, tags)
        _insert_rows(con, "ability_effect", ABILITY_EFFECT_COLS, effects)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def search_abilities(
    con: duckdb.DuckDBPyConnection,
    *,
    name: Optional[str] = None,
    faction: Optional[str] = None,
    owner: Optional[str] = None,
    tags: Iterable[str] = (),
    verdict: Optional[str] = None,
    source_kind: Optional[str] = None,
    order_by: str = "power",
    limit: int = 50,
) -> list[dict]:
    """Aptitudes filtrées (tous les tags demandés doivent être présents), triées décroissant.

    `faction`/`owner`/`name` : sous-chaîne insensible à la casse ; `faction` et
    `owner` portent sur n'importe quel porteur (une aptitude partagée apparaît une fois).
    """
    if order_by not in ("power", "ease", "reliability", "interaction", "name"):
        raise ValueError(f"tri inconnu : {order_by}")
    where, params = ["TRUE"], []
    if name:
        where.append("lower(a.name) LIKE ?")
        params.append(f"%{name.lower()}%")
    if verdict:
        where.append("a.verdict = ?")
        params.append(verdict)
    if source_kind:
        where.append("a.source_kind = ?")
        params.append(source_kind)
    if faction or owner:
        sub, sp = ["o.ability_uid = a.uid"], []
        if faction:
            sub.append("(lower(o.faction_name) LIKE ? OR lower(o.faction_id) = ?)")
            sp += [f"%{faction.lower()}%", faction.lower()]
        if owner:
            sub.append("lower(o.owner_name) LIKE ?")
            sp.append(f"%{owner.lower()}%")
        where.append(f"EXISTS (SELECT 1 FROM ability_owner o WHERE {' AND '.join(sub)})")
        params += sp
    for tag in tags:
        where.append("EXISTS (SELECT 1 FROM ability_tag t WHERE t.ability_uid = a.uid AND t.tag = ?)")
        params.append(tag)
    order = "a.name" if order_by == "name" else f"a.{order_by} DESC, a.name"
    rows = con.execute(
        f"""
        SELECT a.*,
               (SELECT string_agg(tag, ',' ORDER BY tag) FROM ability_tag t WHERE t.ability_uid = a.uid) AS tags,
               (SELECT string_agg(DISTINCT owner_name, ' ; ') FROM ability_owner o WHERE o.ability_uid = a.uid) AS owners
        FROM ability a
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT ?
        """,
        params + [limit],
    )
    cols = [d[0] for d in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


def ability_stats(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple]]:
    """Décomptes pour piloter la qualité de l'analyse (verdicts, origines, tags)."""
    q = {
        "verdict": "SELECT verdict, count(*) FROM ability GROUP BY 1 ORDER BY 2 DESC",
        "source_kind": "SELECT source_kind, count(*), count(*) FILTER (WHERE NOT understood) "
                       "FROM ability GROUP BY 1 ORDER BY 2 DESC",
        "tag": "SELECT tag, count(*) FROM ability_tag GROUP BY 1 ORDER BY 2 DESC",
        "version": "SELECT analyzer_version, max(analyzed_at), count(*) FROM ability GROUP BY 1",
    }
    return {k: con.execute(sql).fetchall() for k, sql in q.items()}


def get_ability_effects(con: duckdb.DuckDBPyConnection, ability_uid: str) -> list[dict]:
    """Effets chiffrés d'une aptitude, avec leur périmètre, dans l'ordre d'extraction."""
    rows = con.execute(
        f"SELECT {','.join(ABILITY_EFFECT_COLS)} FROM ability_effect WHERE ability_uid = ? ORDER BY seq",
        [ability_uid],
    ).fetchall()
    return [dict(zip(ABILITY_EFFECT_COLS, r)) for r in rows]


#: Familles de cas suspects à revoir avec l'utilisateur (`aospy ability review`) : clé →
#: (libellé, condition SQL sur `a` = ability). L'ordre est celui de la revue.
ABILITY_REVIEW_CATEGORIES: dict[str, tuple[str, str]] = {
    "contresens": ("effet ami sur une cible ennemie (sens mal lu ?)",
                   "a.scope = 'one_enemy' AND EXISTS (SELECT 1 FROM ability_effect e WHERE e.ability_uid = a.uid "
                   # un buff offensif de « this unit » contre la cible qu'elle désigne est le cas normal
                   "AND e.kind = 'stat_mod' AND e.side = 'friendly' "
                   "AND coalesce(e.detail, '') NOT IN ('marquage', 'offensif'))"),
    "malus": ("malus détecté (vraie contrepartie ou contresens ?)",
              "EXISTS (SELECT 1 FROM ability_effect e WHERE e.ability_uid = a.uid AND e.detail = 'malus')"),
    "duree": ("buff ami dont la durée n'est pas écrite",
              "EXISTS (SELECT 1 FROM ability_effect e WHERE e.ability_uid = a.uid AND e.kind = 'stat_mod' "
              "AND e.side = 'friendly' AND e.duration = 'non précisée')"),
    "portee": ("effet reconnu mais portée inconnue", "a.scope = 'unknown' AND a.understood"),
    "a-revoir": ("aucun effet reconnu", "a.verdict = 'a-revoir'"),
}


def ability_review_queue(con: duckdb.DuckDBPyConnection, category: str,
                         exclude_uids: Iterable[str] = (), limit: int = 15) -> tuple[int, list[dict]]:
    """(nombre restant, lot d'aptitudes) d'une famille de cas suspects, hors uids déjà revus."""
    if category not in ABILITY_REVIEW_CATEGORIES:
        raise ValueError(f"famille inconnue : {category} ({', '.join(ABILITY_REVIEW_CATEGORIES)})")
    where = ABILITY_REVIEW_CATEGORIES[category][1]
    excluded = list(exclude_uids)
    not_in = f" AND a.uid NOT IN (SELECT unnest(?::VARCHAR[]))" if excluded else ""
    params = [excluded] if excluded else []
    total = con.execute(f"SELECT count(*) FROM ability a WHERE {where}{not_in}", params).fetchone()[0]
    rows = con.execute(
        f"SELECT a.uid, a.name, a.faction_id, a.verdict, a.condition_text, a.declare_text, a.effect_text "
        f"FROM ability a WHERE {where}{not_in} ORDER BY a.faction_id, a.name LIMIT ?", params + [limit])
    cols = [d[0] for d in rows.description]
    return total, [dict(zip(cols, r)) for r in rows.fetchall()]
