"""Allocation des armes par modèle (chargement **optimisé**).

Port du `loadout.py` de StatHammer sur le modèle de données d'aospy. Règle AoS4 par
défaut : chaque figurine utilise **tous** ses profils d'arme. Seule `Unit.description`
(texte libre, rare) restreint cet usage. Le module la lit clause par clause selon un
modèle **base + gains/pertes par sous-groupe** :

* une **base** commune (« *Each model is armed with X and Y* » / « *This unit is armed
  with…* ») portée par toutes les figurines ;
* des **sous-groupes** (« *n/m models…* », « *N models…* », « *The champion…* », figurines
  nommées) qui **gagnent** une arme et, le cas échéant, en **perdent** :
  - « *armed with W instead of V* » → W remplace V ; « *instead of any/their other weapons* »
    (ou « *both their weapons* ») → W remplace **toute** la base de ces figurines ;
  - « *armed with W in addition to…* », « *n/m models can carry W* » → W s'**ajoute** ;
  - « *(can|must) replace V with W* » → idem remplacement.
* un **choix exclusif** « *N of the following options: A | B | C* » → on garde les ``N``
  meilleurs (par dégâts attendus contre une cible de référence, via `combat.expected_weapon_damage`).

Une arme « spéciale » (introduite par un sous-groupe) ne compte que ses porteurs ; les armes
de base partent de la taille d'unité, minorées des remplacements. Les profils non mentionnés
gardent la taille (règle « tous les profils »). C'est ce vecteur de comptes que pondère
`combat.py` (`unit_total = Σ nb_modèles_i × dégâts_par_modèle_i`).

Best-effort : description absente, ou clause non reconnue / pointant sur un profil
introuvable ⇒ défaut (tous les profils sur tous les modèles), **signalé** dans les notes.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .combat import CombatModifiers, expected_weapon_damage
from .models import Unit, Weapon

_TAG = re.compile(r"<[^>]+>")
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")  # parenthétique de fluff : « ... (Volley Gun or Skyhook) »

#: Cible de référence pour départager les options exclusives (rend modéré, comme le CV).
_REF_SAVE = 4

# Grammaires (sur texte nettoyé) ------------------------------------------------------------
_RE_CHOICE = re.compile(
    r"\b(\d+|one|a single)\s+of the following(?:\s+options?)?\s*:?\s*(.+)", re.I
)
_RE_QTY_FRAC = re.compile(r"^\s*(\d+)\s*/\s*\d+\b")          # « 1/11 … » → numérateur
_RE_QTY_N = re.compile(r"^\s*(\d+)\s+models?\b", re.I)       # « 4 models … » → N
_RE_REPLACE = re.compile(r"(?:can|must)\s+replace\s+(?:their\s+)?(.+?)\s+with\s+(.+)", re.I)
_RE_CARRY = re.compile(r"\bcan\s+(?:also\s+)?(?:carry|be armed with)\s+(.+)", re.I)
_RE_ARMED_IN = re.compile(r"\barmed with\s+(.+)", re.I)
_RE_FOLLOWING = re.compile(r"\s+and\s+(?:\d+|one|a single)\s+of the following.*$", re.I)
_GENERIC = re.compile(r"\b(?:each|every|all)\b[^.|]*\bmodels?\b|\bthis unit\b", re.I)
_ARTICLE = re.compile(r"^\s*(?:a|an|the)\s+", re.I)
_WORD_NUM = {"one": 1, "a single": 1}


def _clean(desc: str | None) -> str:
    """Texte de description sur une ligne : éléments de liste joints par « | ».

    Wahapedia met chaque option/clause dans un ``<li>`` distinct : on les sépare par
    « | » (et non par un saut de ligne) pour que les listes d'options « A | B | C »
    restent capturables d'un seul tenant par les expressions régulières."""
    if not desc:
        return ""
    t = re.sub(r"</li>|<br\s*/?>", " | ", desc)
    t = _TAG.sub(" ", t).replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s*\|\s*", " | ", t)  # espaces autour des séparateurs
    return re.sub(r"[ \t]+", " ", t).strip(" |")


def _norm(s: str | None) -> str:
    """Nom d'arme normalisé (sans balise, apostrophes/espaces unifiés, minuscules)."""
    s = _TAG.sub("", s or "").replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def _count_names(subject: str) -> int:
    """Nombre de figurines nommées dans un sujet (« The A, B and C » → 3)."""
    s = _ARTICLE.sub("", subject.strip())
    return sum(1 for p in re.split(r",|\band\b", s, flags=re.I) if p.strip())


def _match(name: str, names_norm: list[str]) -> int | None:
    """Index du profil d'arme désigné par ``name`` (égalité, sinon préfixe). ``None`` sinon."""
    profs = _match_profiles(name, names_norm)
    return profs[0] if profs else None


def _match_profiles(name: str, names_norm: list[str]) -> list[int]:
    """**Tous** les index de profils désignés par ``name`` (une arme = parfois plusieurs lignes).

    Une même arme (ex. *Hunter Javelin*) porte souvent un profil tir **et** un profil mêlée :
    les descriptions raisonnent par **arme**, le vecteur de comptes par **profil**. On renvoie
    donc tous les profils d'égal nom (cas javelot/arme de jet) ; à défaut, le premier préfixe
    (comportement historique, pour ne pas sur-capturer des armes distinctes)."""
    n = _PAREN.sub("", _norm(_ARTICLE.sub("", name))).strip(" .,;:")
    if not n:
        return []
    exact = [i for i, wn in enumerate(names_norm) if wn == n]
    if exact:
        return exact
    for i, wn in enumerate(names_norm):
        if wn.startswith(n) or n.startswith(wn):
            return [i]
    return []


def _ref_expected(weapons: list[Weapon]) -> list[float]:
    """Dégâts attendus par profil contre la cible de référence (pour classer les options)."""
    probe = Unit(
        name="_probe", army_id=0, move=0, save=_REF_SAVE, health=1, control=0,
        models=1, points=0,
    )
    mods = CombatModifiers()
    out: list[float] = []
    for w in weapons:
        try:
            out.append(expected_weapon_damage(w, 1, probe, mods))
        except Exception:
            out.append(0.0)
    return out


def _qty(clause: str, size: int) -> int:
    """Nombre de figurines visées par une clause : numérateur de « n/m », « N models »,
    champion → 1, sujet générique → taille, sinon figurines nommées."""
    m = _RE_QTY_FRAC.match(clause)
    if m:
        return int(m.group(1))
    m = _RE_QTY_N.match(clause)
    if m:
        return int(m.group(1))
    if _GENERIC.search(clause):
        return size
    if re.search(r"\bchampion\b", clause, re.I):
        return 1
    subject = re.split(r"\b(?:is|are)\b", clause, maxsplit=1, flags=re.I)[0]
    return _count_names(subject)


def _is_all_weapons(text: str) -> bool:
    """Vrai si ``text`` désigne « toutes les autres armes » (any/their/both/other weapons)."""
    return bool(
        re.search(r"\b(?:any|their|both|other)\b[^.|]*\bweapons?\b|^\s*(?:both\s+)?weapons?\s*$",
                  text.strip(), re.I)
    )


def _collapse_modes(
    weapons: list[Weapon], names: list[str], counts: list[int], notes: list[str]
) -> None:
    """Effondre les **modes d'arme exclusifs** (« Arme: ModeA » / « Arme: ModeB »).

    Une arme à plusieurs lignes de tir (boulet/mitraille, tir visé/hâtif…) n'utilise **qu'un**
    mode par tour : on ne garde que le meilleur (dégâts de référence), les autres tombant à 0.
    Indépendant de la description : le motif vit dans le **nom** (préfixe avant « : »)."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, nm in enumerate(names):
        if ":" in nm:
            groups[nm.split(":", 1)[0].strip()].append(i)
    expected = None
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        if expected is None:
            expected = _ref_expected(weapons)
        best = max(idxs, key=lambda i: expected[i])
        for i in idxs:
            if i != best:
                counts[i] = 0
        notes.append(f"modes d'arme exclusifs → {names[best]} retenu")


def model_counts(unit: Unit, weapons: list[Weapon]) -> tuple[list[int], list[str]]:
    """Nombre de modèles portant chaque profil (chargement optimisé), aligné sur ``weapons``.

    Lit `unit.description` (best-effort) et `unit.models` (taille de base) ; sans
    description, retombe sur le défaut (tous les profils sur tous les modèles).
    Renvoie ``(counts, notes)`` : ``counts[i]`` = modèles portant ``weapons[i]`` à la
    taille de **base** (à l'appelant de scaler en cas de renforcement, cf. `combat.py`).
    """
    size = unit.models
    n = len(weapons)
    counts = [size] * n
    notes: list[str] = []
    if n == 0:
        return counts, notes
    names = [_norm(w.name) for w in weapons]
    desc = _clean(unit.description)
    if not desc:
        _collapse_modes(weapons, names, counts, notes)
        return counts, notes
    expected = None  # dégâts de référence, calculés paresseusement (seulement pour un choix)

    def match_all(phrase: str) -> list[int]:
        """Index(es) des profils nommés dans ``phrase`` (essai entier, sinon « A and B »).

        Une arme à plusieurs profils (tir + mêlée) ramène **tous** ses profils."""
        whole = _match_profiles(phrase, names)
        if whole:
            return whole
        out = []
        for p in re.split(r",|\band\b", phrase, flags=re.I):
            out.extend(_match_profiles(p, names))
        return out

    base_idx: set[int] = set()                   # armes de base (portées par toute l'unité)
    special: dict[int, int] = defaultdict(int)   # arme de sous-groupe → nombre de porteurs
    subtract: dict[int, int] = defaultdict(int)  # arme de base → figurines qui la lâchent
    all_base_drop = 0          # figurines lâchant TOUTE leur base (« instead of any other »)
    touched = False

    # 1. Choix exclusif (sur la description entière) : « N of the following options: A | B ».
    for num_raw, tail in _RE_CHOICE.findall(desc):
        keep = _WORD_NUM.get(num_raw.lower()) or (int(num_raw) if num_raw.isdigit() else 1)
        opts = [o.strip() for o in tail.split("|") if o.strip()]
        idxs = [i for i in (_match(o, names) for o in opts) if i is not None]
        if len(idxs) < 2:
            continue
        if expected is None:
            expected = _ref_expected(weapons)
        best = sorted(idxs, key=lambda i: expected[i], reverse=True)[:keep]
        for i in idxs:
            special[i] = size if i in best else 0
        notes.append(f"choix exclusif ({len(idxs)} options) → "
                     + ", ".join(names[i] for i in best) + " retenu(s)")
        touched = True

    # 2. Clauses par sous-groupe (une par « phrase » : séparateurs « | » ou fin de phrase).
    for raw in re.split(r"\s*\|\s*|(?<=[a-zA-Z])\.\s+", desc):
        clause = raw.strip()
        low = clause.lower()
        if not clause or "of the following" in low or "cannot" in low or "can not" in low:
            continue
        qty = _qty(clause, size)
        is_base = bool(_GENERIC.search(clause)) and not _RE_QTY_FRAC.match(clause) \
            and not _RE_QTY_N.match(clause)

        mrep = _RE_REPLACE.search(clause)
        mcarry = _RE_CARRY.search(clause)
        marmed = _RE_ARMED_IN.search(clause)
        if mrep:  # « (can|must) replace V with W »
            old, gained = mrep.group(1), match_all(mrep.group(2))
            for gi in gained:
                special[gi] += qty
            if _is_all_weapons(old):
                all_base_drop += qty
            else:
                for oi in _match_profiles(old, names):
                    subtract[oi] += qty
            touched = touched or bool(gained)
        elif mcarry:  # « can (also) carry / be armed with W » → additif
            for gi in match_all(mcarry.group(1)):
                special[gi] += qty
                touched = True
        elif marmed:
            wp = marmed.group(1)
            if re.search(r"in addition to", wp, re.I):  # arme additive (base conservée)
                for gi in match_all(re.split(r"in addition to", wp, flags=re.I)[0]):
                    special[gi] += qty
                    touched = True
            elif re.search(r"instead of", wp, re.I):  # remplacement
                main, rest = re.split(r"instead of", wp, maxsplit=1, flags=re.I)
                for gi in match_all(main):
                    special[gi] += qty
                    touched = True
                if _is_all_weapons(rest):
                    all_base_drop += qty
                else:
                    for oi in _match_profiles(rest, names):
                        subtract[oi] += qty
            else:  # « armed with W » simple : base (sujet générique) ou roster (sous-groupe)
                idxs = match_all(_RE_FOLLOWING.sub("", wp))
                if is_base:
                    base_idx.update(idxs)
                else:
                    for gi in idxs:
                        special[gi] += qty
                touched = touched or bool(idxs)

    # 3. Finalisation. Spéciale (sous-groupe) → ses porteurs ; base / non mentionnée → taille
    # minorée des remplacements spécifiques et des figurines ayant lâché toute leur base.
    for i in range(n):
        if i in special and i not in base_idx:
            counts[i] = max(0, min(size, special[i]))
        else:
            counts[i] = max(0, size - subtract.get(i, 0) - all_base_drop)

    if not touched and re.search(
        r"can (?:replace|carry|be armed)|following options?:|armed with", desc, re.I
    ):
        notes.append("description d'armement non reconnue → défaut (tous profils)")

    _collapse_modes(weapons, names, counts, notes)
    return counts, notes
