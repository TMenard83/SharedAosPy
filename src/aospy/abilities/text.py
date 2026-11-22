"""Nettoyage du HTML Wahapedia en texte brut exploitable par des regex."""

from __future__ import annotations

import html
import re

_TOOLTIP_RE = re.compile(r"%\d+([^%]*)%")  # « %000010870<ky>FIGHT</ky> ability% »
_ORPHAN_ID_RE = re.compile(r"[%$]\d{5,}\|?")  # marqueur d'infobulle orphelin
_TAG_RE = re.compile(r"<[^>]*>?")
_SPACES_RE = re.compile(r"[ \t ]+")
_DESIGNER_RE = re.compile(r"Designer[’']s Note:.*", re.S)
_SECTION_RE = re.compile(r"\b(Declare|Effect):", re.I)


def clean(raw: str) -> str:
    """HTML → texte brut sur une ligne par paragraphe, guillemets normalisés."""
    t = raw or ""
    t = _TOOLTIP_RE.sub(r"\1", t)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n- ", t, flags=re.I)
    t = _TAG_RE.sub("", t)
    t = _ORPHAN_ID_RE.sub("", t)
    t = html.unescape(t)
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("″", '"').replace("”", '"')
    t = _SPACES_RE.sub(" ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


#: Fautes de l'export Wahapedia (analyseur v28) : ligatures « fi »/« fl »/« ff » perdues (« battleeld »,
#: « inict », « modiers », « eect »), « I »/« l » à la place du chiffre 1, « to » oublié.
_TYPOS = [
    (re.compile(r"\bbattleeld"), "battlefield"),
    (re.compile(r"\binict"), "inflict"),
    (re.compile(r"\bInict"), "Inflict"),  # v34 : en tête de phrase (LAVA STORM)
    (re.compile(r"\bmodier"), "modifier"),
    (re.compile(r"\beect"), "effect"),
    (re.compile(r"\b([Aa]dd|[Ss]ubtract) I (to|from)\b"), r"\1 1 \2"),
    (re.compile(r"\broll l additional\b"), "roll 1 additional"),
    (re.compile(r"\bAAdd\b"), "Add"),
    (re.compile(r"\b([Aa]dd \d+) the (\w+ characteristic)\b"), r"\1 to the \2"),
]


def fix_typos(t: str) -> str:
    """Corrige les fautes récurrentes de l'export, APRÈS le calcul de l'uid (qui reste stable)."""
    for pat, rep in _TYPOS:
        t = pat.sub(rep, t)
    return t


def split_declare_effect(text: str) -> tuple[str, str]:
    """Sépare « Declare: … Effect: … » ; note de concepteur retirée.

    Sans balise « Effect: », tout le texte est l'effet (aptitudes passives
    anciennes). Le texte d'avant « Declare: » (rare) est rattaché à l'effet.
    """
    text = _DESIGNER_RE.sub("", text).strip()
    declare, effect = "", text
    parts = _SECTION_RE.split(text)
    if len(parts) > 1:
        chunks: dict[str, str] = {}
        prefix = parts[0].strip()
        for label, body in zip(parts[1::2], parts[2::2]):
            chunks[label.lower()] = (chunks.get(label.lower(), "") + " " + body).strip()
        declare = chunks.get("declare", "")
        effect = " ".join(x for x in (prefix, chunks.get("effect", "")) if x).strip()
    return declare.strip(), effect.strip()
