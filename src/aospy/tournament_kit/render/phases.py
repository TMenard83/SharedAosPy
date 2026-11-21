"""Classement des aptitudes : phase (`classify_phase`), catégorie, fréquence, qualificatif de tour, côtés du tour, sections."""

from __future__ import annotations

import re
from dataclasses import replace as _dc_replace

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle

from ..sources.wahapedia_lookup import AbilityEntry, keyword_key
from .text import _clean_text, strip_flavor, tr
from .theme import (
    _BADGE_BLOOD,
    _BADGE_FACTION,
    _BADGE_PRAYER,
    _BADGE_SPELL,
    _BADGE_STAT,
)

#: ordre canonique du tour (cf. AoS4) — "deploy" avant "round_start" avant
#: "start" : le déploiement précède le round 1, et « Début de Round »
#: (déclenchement unique, avant qu'aucun des deux joueurs n'ait pris son
#: tour — cf. `classify_phase`) précède « Début de Tour » (déclenchement
#: propre à chaque tour, donc 2 fois par round) — 2 moments de règle
#: distincts que Wahapedia confond tous les deux sous `ability_phase`
#: = "Start of Turn". "any" toujours en dernier, catégorie hors séquence.
#: "asterism" (cf. `classify_phase`) tout en tête, avant même "deploy" :
#: les 4 Astérismes Séraphons (mot-clé Wahapedia "Asterism") ont chacun
#: leur propre `ability_phase` réel (Phase des Héros/Mêlée/Charge/Réaction
#: défensive) mais sont choisis/activés ensemble via "Le Grand Dessein"/
#: "Faites Avancer le Grand Dessein" (bandeaux "deploy"/"round_start" qui
#: suivent) — les séparer par bandeau de phase réel les éparpillerait sur
#: toute la carte alors qu'ils forment un seul bloc de règle thématique.
#: Placé en tête plutôt qu'entre "deploy" et "round_start" : sur une carte
#: fusionnée (`fr-extended`), "deploy"/"round_start" portent aussi des
#: règles de saison/du Manuel du général sans rapport, volumineuses au
#: point de pousser un bandeau "asterism" intercalé sur la page suivante
#: — en tête, les 4 Astérismes (courts) restent sur la même page que "Le
#: Grand Dessein"/"Faites Avancer le Grand Dessein" qui les suivent
#: directement, quitte à repousser le contenu générique sans rapport.
#: Cas localisé à ce mot-clé (propre à Seraphon) : ne change rien pour
#: aucune autre aptitude/faction.
_PHASE_ORDER = [
    "asterism",
    "deploy",
    "round_start",
    "start",
    "hero",
    "move",
    "shoot",
    "charge",
    "melee",
    "end",
    "any",
]

#: Ordre des cartes du mode `fr-split` (`pdf_builder`) : « N'importe quelle
#: phase » (vert) suit directement « Déploiement », les deux formant la
#: carte « Déploiement » (demande explicite de l'utilisateur) ; les cartes
#: de tour n'en ont donc plus, et « Fin de tour » y est le dernier bandeau,
#: suivi directement des cartes de tactique de bataille.
SPLIT_PHASE_ORDER = [
    "asterism",
    "deploy",
    "any",
    "round_start",
    "start",
    "hero",
    "move",
    "shoot",
    "charge",
    "melee",
    "end",
]


_PHASE_FIELD_TO_KEY = {
    "deployment phase": "deploy",
    "start of turn": "start",
    "hero phase": "hero",
    "movement phase": "move",
    "shooting phase": "shoot",
    "charge phase": "charge",
    "combat phase": "melee",
    "end of turn": "end",
}

#: `_qualifier_label` ne couvre que les phases qualifiées "Your/Any/Enemy" —
#: une condition combinant fréquence + timing sans qualificatif (ex. les
#: Règles de Saison 2026-27, `season_rules.py`, ou "MURDER-WON TROPHIES" des
#: Blades of Khorne côté Wahapedia) retombait sinon sur le texte brut anglais
#: en majuscules (`condition.upper()`) faute de correspondance exacte —
#: ajoutée ici au fil des cas rencontrés plutôt que devinée à l'avance.
_PLAIN_CONDITION_FR = {
    "deployment phase": "PHASE DE DÉPLOIEMENT",
    "once per battle (army), deployment phase": "PHASE DE DÉPLOIEMENT",
    "once per turn (army), start of battle round": "DÉBUT DU ROUND DE BATAILLE",
    "start of battle round": "DÉBUT DU ROUND DE BATAILLE",
    "start of the first battle round": "DÉBUT DU 1ER ROUND",
    "end of the first battle round": "FIN DU 1ER ROUND",
    # aptitude de synthèse passive rangée au début du round, sous le choix
    # de runes (`roster_simplifications.json`, ex. « L'Appel des Montagnes »)
    "passive, start of battle round": "PASSIF",
}

#: pastilles de condition qui ne font que redire le bandeau de phase où
#: l'aptitude est rangée (« Déploiement », « Début de Round ») : masquées
#: (demande de l'utilisateur, tous modes). Une fréquence éventuelle garde sa
#: propre pastille (`_freq_pill`).
_BAND_ONLY_CONDITIONS = frozenset({"PHASE DE DÉPLOIEMENT", "DÉBUT DU ROUND DE BATAILLE"})

_QUALIFIER_RE = re.compile(
    r"\b(Your|Any|Enemy)\b\s+(?:Hero Phase|Movement Phase|Shooting Phase|Charge Phase|Combat Phase|Turn|Battle Round)",
    re.IGNORECASE,
)
_QUALIFIER_FR = {"your": "Ma phase", "any": "Les 2 phases", "enemy": "Phase ennemi"}
#: « Once Per Battle Round » (une fois *par round*, peut se redéclencher à
#: chaque round) est essayé avant « Once Per Battle » (une fois pour toute la
#: bataille) : sinon la regex s'arrêtait au mot « Battle » et affichait
#: « ×1 / BATAILLE », faux. Le timing qui suit la fréquence (« Start of
#: Battle Round »...) est lu à part par `_plain_condition` — masqué quand il
#: ne fait que redire le bandeau (« Depict Rune » et 8 autres aptitudes).
_FREQ_RE = re.compile(r"Once Per (Turn|Battle Round|Battle|Phase)(?:\s*\((Army)\))?", re.IGNORECASE)

#: coquilles du `condition` Wahapedia (« Any Comhat Phase », « Your Hero
#: Quest »), corrigées avant toute lecture du timing — sinon ni la pastille
#: qualificatif ni `_PLAIN_CONDITION_FR` ne les reconnaissent et le texte
#: anglais brut s'affiche.
_CONDITION_TYPOS = {"comhat": "Combat", "hero quest": "Hero Phase", "first battle round": "the First Battle Round"}
_CONDITION_TYPO_RE = re.compile(r"\b(?:comhat|hero quest|(?<!the )first battle round)\b", re.IGNORECASE)


def _normalize_condition(condition: str) -> str:
    """`condition` Wahapedia nettoyé pour la lecture du timing : espaces
    (insécables compris) réduits, guillemet parasite de tête retiré
    (« ‘Once Per Turn... »), coquilles de `_CONDITION_TYPOS` corrigées."""
    text = re.sub(r"\s+", " ", condition or "").strip().lstrip("‘’'\"")
    return _CONDITION_TYPO_RE.sub(lambda m: _CONDITION_TYPOS[m.group(0).lower().removeprefix("the ")], text)


def _plain_condition(condition: str) -> str | None:
    """Libellé français d'une condition sans qualificatif (`_PLAIN_CONDITION_FR`),
    cherché sur le texte entier puis sans sa fréquence de tête — portée à
    part par `_freq_pill` (ex. « Once Per Battle, Deployment Phase » ->
    « PHASE DE DÉPLOIEMENT », masquée en bandeau Déploiement)."""
    low = condition.lower()
    if low in _PLAIN_CONDITION_FR:
        return _PLAIN_CONDITION_FR[low]
    m = _FREQ_RE.match(condition)
    if m:
        return _PLAIN_CONDITION_FR.get(condition[m.end() :].lstrip(" ,").lower())
    return None


#: Reclassifie en phase « Début de Round » (cf. `classify_phase`) toute
#: aptitude dont le `condition` mentionne « Start of (the) (First) Battle
#: Round » — Wahapedia ne distingue pas ce moment (unique, avant qu'aucun des
#: 2 joueurs n'ait pris son tour) de « Start of Turn » (2 fois par round, une
#: fois par tour) dans son propre champ `ability_phase`, qui vaut "Start of
#: Turn" pour les deux. Volontairement plus étroit que « contient "battle
#: round" » : ne doit pas matcher une simple fréquence sans déclencheur de
#: timing (ex. « Once Per Battle Round, Your Hero Phase », un vrai
#: déclenchement en phase des héros, cf. `classify_phase`).
_ROUND_START_RE = re.compile(r"\bstart of (?:the )?(?:first )?battle round\b", re.IGNORECASE)
#: Phase du cycle de round nommée par le `condition` d'une aptitude — prime
#: sur `ability_phase` quand elle est seule (cf. `classify_phase`) :
#: Wahapedia a parfois un `ability_phase` incohérent avec son propre
#: `condition` (« Chalice of Ushoran » / « Lampées de Délire » : condition
#: « Any Combat Phase » mais `ability_phase` = "End of Turn" ; « VISION OF
#: DEFIANT SUPREMACY » : « Any Hero Phase » mais "Movement Phase"), et c'est
#: le `condition` qui correspond à la charte imprimée.
_CONDITION_PHASE_RE = re.compile(
    r"\b(Hero Phase|Movement Phase|Shooting Phase|Charge Phase|Combat Phase)\b",
    re.IGNORECASE,
)
_WIELDER_RATIO_RE = re.compile(
    r"(\d+/\d+)\s+models?\s+can\s+replace\s+(?:their|its)\s+[\w\s'’-]+?\s+with\s+an?\s+([\w\s'’-]+?)\.",
    re.IGNORECASE,
)
#: `WIZARD (N)`/`PRIEST (N)` — cf. `WahapediaLookup.find_warscroll`, qui
#: reconstitue ce format à partir de la colonne `parameter` de
#: `Warscrolls_keywords.csv`. Utilisé à la fois pour extraire le badge
#: d'en-tête (`_caster_badges`) et pour l'exclure de la liste de mots-clés en
#: bas de carte (`_visible_keywords`), afin de ne pas doublonner l'info.
_CASTER_KW_RE = re.compile(r"^(WIZARD|PRIEST)\s*\((\d+)\)$", re.IGNORECASE)


def classify_phase(ability: AbilityEntry) -> str:
    """Détermine le bandeau de phase d'une aptitude. `ability_phase` (CSV
    Wahapedia, ou valeur posée à la main dans `season_rules.json`/
    `generic_core_abilities.json` — ces règles de coeur de jeu ne sont dans
    aucun CSV Wahapedia) mappe directement sur 8 des 9 catégories (7 phases
    du cycle de round + "Deployment Phase", qui précède le round 1 donc
    n'est pas l'une d'elles) ; `"Defensive reaction"` n'a pas d'équivalent
    dans le livre (le CSV ne distingue pas "aptitude toujours liée à une
    phase précise" de "réaction générique") et se reclasse à partir du
    texte : mention de `Fight ability`/`combat attack` -> Mêlée, `shooting
    attack` -> Tir, sinon -> vert (N'importe quelle phase). Pattern-matching
    sur un vocabulaire fixe, jamais un jugement au cas par cas ni une
    paraphrase du texte de règle lui-même — ce filtre textuel vaut pour le
    texte anglais Wahapedia et pour son vérbatim FR patché
    (`_FR_MELEE_RE`/`_FR_SHOOT_RE`) ; une aptitude hors CSV (JSON
    hand-curated, texte déjà en français — cf. `generic_core_abilities.py`/
    `season_rules.py`) doit porter son `ability_phase` déjà résolu à la main
    (même mini-vocabulaire anglais interne) plutôt que de compter sur ce
    repli, qui ne la reconnaîtrait jamais.

    Exception avant tout ça : `ability_phase == "Start of Turn"` avec un
    `condition` qui mentionne « Start of (the) (First) Battle Round »
    (`_ROUND_START_RE`) reclasse en « Début de Round » plutôt que « Début de
    Tour » — 2 moments de règle distincts (le round démarre une fois, avant
    qu'aucun tour n'ait commencé ; le tour démarre 2 fois par round) que
    Wahapedia confond tous les deux sous cette même valeur de champ, faute de
    catégorie dédiée dans son propre schéma.

    Même genre d'exception pour `ability_phase == "Start of Turn"` avec un
    `condition` qui mentionne « Deployment Phase » (ex. Skaven « THE LURKING
    VERMINTIDE » / « Le Raz-de-Vermine Rampant », et sa variante « Gnawfeast
    Clawpack » dont le `condition` est « Once Per Battle, Deployment Phase »)
    : reclasse en « Déploiement » — Wahapedia laisse là aussi `ability_phase`
    à sa valeur par défaut "Start of Turn" au lieu de "Deployment Phase" pour
    cette aptitude, alors que le placement en réserve qu'elle décrit se fait
    explicitement pendant le déploiement, pas au début d'un tour.

    Hors réaction défensive, un `condition` qui nomme une seule phase du
    cycle (`_CONDITION_PHASE_RE`) prime sur `ability_phase` quand les deux
    divergent (cas du Calice d'Ushoran, mis en fin de tour à tort).

    Priorité absolue avant tout ce qui précède : le mot-clé Wahapedia
    "Asterism" (porté par les 4 Astérismes Séraphons, cf. `_PHASE_ORDER`)
    force le bandeau virtuel "asterism" quel que soit `ability_phase`.

    Même chose pour un passif pur (`condition` « Passive » seul) dont
    `ability_phase` vaut « Start of Turn » : valeur par défaut, pas un moment.

    Juste après : une aptitude de profil selon les dégâts subis
    (`is_profile_modifier`, ex. « Battle Damaged »/« Stigmates de Guerre »)
    va dans le bandeau vert "any" — Wahapedia lui donne `ability_phase` =
    "Start of Turn" (sa valeur par défaut pour un passif), alors qu'elle
    s'applique en permanence, pas au début du tour.

    Et tout en tête : une aptitude d'une sous-section de choix
    (`CHOICE_CATEGORIES`, cf. `split_pool._CHOICE_CLUSTERS`) va dans la
    phase de sa sous-section (`ability_phase`, posé par `pdf_builder`), même
    si son `condition` nomme une autre phase (« Your Combat Phase ») — c'est
    sa copie de choix, l'original reste à sa phase."""
    if ability.ability_category in CHOICE_CATEGORIES:
        return _PHASE_FIELD_TO_KEY[ability.ability_phase.strip().lower()]
    if any(keyword_key(kw) == "asterism" for kw in (ability.keywords or "").split(",") if kw.strip()):
        return "asterism"
    if is_profile_modifier(ability):
        return "any"
    phase = (ability.ability_phase or "").strip().lower()
    # passif pur : « Start of Turn » n'est que la valeur par défaut de
    # Wahapedia, il s'applique en permanence (ex. « L'Appel des Montagnes »,
    # « Gardien du Temple ») -> bandeau vert, comme `is_profile_modifier`.
    if phase == "start of turn" and (ability.condition or "").strip().lower() == "passive":
        return "any"
    if phase == "start of turn" and _ROUND_START_RE.search(ability.condition or ""):
        return "round_start"
    if phase == "start of turn" and "deployment phase" in (ability.condition or "").lower():
        return "deploy"
    named = {m.lower() for m in _CONDITION_PHASE_RE.findall(ability.condition or "")}
    if phase != "defensive reaction" and len(named) == 1:
        return _PHASE_FIELD_TO_KEY[named.pop()]
    if phase != "defensive reaction":
        return _PHASE_FIELD_TO_KEY.get(phase, "any")
    text = (ability.description or "").lower()
    if "fight ability" in text or "combat attack" in text or _FR_MELEE_RE.search(text):
        return "melee"
    if "shooting attack" in text or _FR_SHOOT_RE.search(text):
        return "shoot"
    return "any"


#: équivalents français du repli textuel de `classify_phase`, pour une
#: réaction défensive dont le texte a été remplacé par un vérbatim FR
#: (`faction_rules_fr.json`, ex. « Lumière Aveuglante » -> Tir, pas vert)
_FR_MELEE_RE = re.compile(r"aptitude de (?:<b>)?corps à corps|attaques? de mêlée")
_FR_SHOOT_RE = re.compile(r"attaques? de tir")


#: ordre d'affichage des 4 catégories d'aptitude au sein d'un même bandeau de
#: phase — aptitudes normales d'abord, puis sorts/prières/manifestations,
#: dans cet ordre demandé par l'utilisateur. Les sous-sections de choix
#: (`CHOICE_CATEGORIES` : Délires Flesh-eater Courts, Dîme de Sang Blades of
#: Khorne, Bénédictions de Khaine Daughters of Khaine, Vocation au Chaos
#: Slaves to Darkness, cf.
#: `split_pool._CHOICE_CLUSTERS`) passent en tête de leur bandeau.
CHOICE_CATEGORIES = frozenset({"delusion", "blood_tithe", "khaine_blessing", "chaos_pledge"})
_CHOICE_CATEGORY_KEYWORDS = {"delusion": "delusion", "blood_tithe": "blood tithe"}
_CATEGORY_ORDER = [
    "delusion",
    "blood_tithe",
    "khaine_blessing",
    "chaos_pledge",
    "normal",
    "spell",
    "prayer",
    "manifestation",
]
_CATEGORY_LABELS_FR = {
    "normal": "Aptitudes",
    "spell": "Sorts",
    "prayer": "Prières",
    "manifestation": "Manifestations",
    "delusion": "Délires",
    "blood_tithe": "Dîme de Sang",
    "khaine_blessing": "Bénédictions de Khaine",
    "chaos_pledge": "Vocation au Chaos",
}
_CATEGORY_COLORS = {
    "normal": "#6b6555",
    "spell": _BADGE_SPELL,
    "prayer": _BADGE_PRAYER,
    "manifestation": _BADGE_STAT,
    "delusion": _BADGE_FACTION,
    "blood_tithe": _BADGE_BLOOD,
    "khaine_blessing": _BADGE_FACTION,
    "chaos_pledge": _BADGE_FACTION,
}


def _ability_category(ability: AbilityEntry) -> str:
    """Catégorie d'affichage d'une aptitude au sein de son bandeau de phase —
    `ability_category` (posé explicitement par `set_ability_category`, cf.
    plus bas) prime quand présent : le `points_type` d'une aptitude de
    convocation d'un domaine de manifestations vaut lui-même "Spell" ou
    "Prayer" côté Wahapedia (identique à un sort/une prière ordinaire), donc
    `points_type` seul ne peut jamais distinguer une manifestation d'un sort/
    d'une prière — seul l'appelant (`pdf_builder.resolve_rules`, qui sait de
    quel domaine chaque aptitude vient) peut trancher. En l'absence de ce
    marquage, `points_type` suffit à distinguer un sort/une prière d'une
    aptitude normale."""
    if ability.ability_category == "manifestation" or ability.ability_category in CHOICE_CATEGORIES:
        return ability.ability_category
    pts = (ability.points_type or "").strip()
    if pts == "Spell":
        return "spell"
    if pts == "Prayer":
        return "prayer"
    return "normal"


def set_ability_category(abilities: list[AbilityEntry], category: str) -> list[AbilityEntry]:
    """Marque explicitement la catégorie d'affichage de chaque aptitude — cf.
    `_ability_category` pour pourquoi c'est nécessaire (uniquement pour un
    domaine de manifestations, à ce jour)."""
    return [_dc_replace(ab, ability_category=category) for ab in abilities]


def _frequency_label(condition: str) -> str | None:
    m = _FREQ_RE.search(_normalize_condition(condition))
    if not m:
        return None
    label = {"turn": "×1 / TOUR", "battle round": "×1 / ROUND", "battle": "×1 / BATAILLE", "phase": "×1 / PHASE"}[
        re.sub(r"\s+", " ", m.group(1).lower())
    ]
    if m.group(2):
        label += " (ARMÉE)"
    return tr(label)


def _qualifier_label(condition: str) -> str | None:
    m = _QUALIFIER_RE.search(_normalize_condition(condition))
    if not m:
        return None
    qual = _QUALIFIER_FR.get(m.group(1).lower())
    return tr(qual) if qual else None


#: Aptitude passive qui fait varier une caractéristique du profil selon les
#: dégâts subis par l'unité (« Battle Damaged »/« Stigmates de Guerre »,
#: « Necromantic Limits », « Runic Power »...) — cf. `is_profile_modifier`.
#: Bilingue : le texte est l'anglais Wahapedia ou le français patché
#: (`faction_rules_fr.json`, qui garde le `condition` Wahapedia).
_DAMAGE_STATE_RE = re.compile(
    r"while this unit has [^.]*?damage points?|tant qu(?:e cette unité|['’]elle) a [^.]*?dégâts?",
    re.IGNORECASE,
)
_CHARACTERISTIC_RE = re.compile(r"\bcharacteristic\b|\bcaractéristique\b", re.IGNORECASE)


def is_profile_modifier(ability: AbilityEntry) -> bool:
    """Vrai pour une aptitude passive qui modifie le profil même de l'unité
    selon ses dégâts subis (ex. Attaques d'une arme réduites à partir de 10
    dégâts). En mode `fr-split`, elle reste sur la carte du warscroll, à côté
    des armes qu'elle modifie, au lieu de partir sur les cartes de tour :
    c'est une information de profil, pas une aptitude qu'on déclenche
    (demande explicite de l'utilisateur). Un `condition` vide compte comme
    passif : c'est le cas d'un ajout autonome de `faction_rules_fr.json`
    sans condition renseignée."""
    if (ability.condition or "").strip().lower() not in ("passive", ""):
        return False
    text = _clean_text(ability.description or "")
    return bool(_DAMAGE_STATE_RE.search(text) and _CHARACTERISTIC_RE.search(text))


#: une aptitude qui fait choisir/cibler ou qui touche d'autres unités ne
#: modifie pas que le profil de son unité — cf. `is_self_profile_modifier`.
#: note de provenance d'une aptitude de synthèse (`roster_simplifications._NOTE_MARKUP`).
_PROVENANCE_NOTE_RE = re.compile(r'<br/><font size="6" color="#8a8a8a">.*?</font>', re.S)
_OTHER_UNITS_RE = re.compile(
    r"\b(?:declare|annonce|friendly|enemy|amie?s?|ennemie?s?|other units?|autres? unités?)\b",
    re.IGNORECASE,
)
#: effet porté sur la cible d'une attaque (« the target has the WARD-SMASHED
#: keyword », « that HERO is automatically destroyed ») : touche une autre
#: unité, pas le profil de celle-ci.
_TARGET_EFFECT_RE = re.compile(
    r"\bthe target (?:has|is|cannot|can't)\b|\bautomatically destroyed\b|\bla cible (?:a|est|ne)\b|\best automatiquement détruit",
    re.IGNORECASE,
)
_SELF_RE = re.compile(r"\bthis unit\b|\bcette unité\b", re.IGNORECASE)


def _weapon_name_re(name: str) -> re.Pattern[str]:
    # pluriel toléré sur chaque mot : l'aptitude dit « ses Lances Maudites »
    # pour l'arme « Lance Maudite »
    words = [re.escape(w.rstrip("sx")) for w in re.split(r"\s+", name.replace("’", "'").strip()) if w]
    return re.compile(r"\b" + r"\s+".join(w + r"[sx]?" for w in words) + r"\b", re.IGNORECASE)


def is_self_profile_modifier(ability: AbilityEntry, weapon_names: list[str]) -> bool:
    """`is_profile_modifier`, ou plus largement toute aptitude passive qui
    ne change que le profil de sa propre unité — une de ses armes
    (`weapon_names`, ex. « Charge Empaleuse » : +1 Perf. aux Lances
    Maudites) ou une de ses caractéristiques (« cette unité ») — sans
    rien faire choisir ni toucher d'autre unité. En mode `fr-split`, elle
    reste sur la carte du warscroll, là où on lit le profil (demande de
    l'utilisateur). `AbilityEntry.self_profile` (décidé sur le texte
    Wahapedia d'origine, avant que le correctif français ne traduise le nom
    de l'arme dans le texte mais pas dans le profil) suffit."""
    if ability.self_profile or is_profile_modifier(ability):
        return True
    if (ability.condition or "").strip().lower() not in ("passive", ""):
        return False
    # la note de provenance d'une synthèse `fr-split-simple` cite des noms
    # d'aptitude qui peuvent être aussi des noms d'arme (« Staff of the
    # Horned Rat ») : elle ne décrit pas l'effet, on ne la lit pas.
    text = _clean_text(_PROVENANCE_NOTE_RE.sub("", ability.description or "")).replace("’", "'")
    if _OTHER_UNITS_RE.search(text) or _TARGET_EFFECT_RE.search(text):
        return False
    if any(_weapon_name_re(name).search(text) for name in weapon_names if name.strip()):
        return True
    return bool(_CHARACTERISTIC_RE.search(text) and _SELF_RE.search(text))


#: Tours où une aptitude est utilisable — cf. `ability_turn_sides`.
TURN_MINE = "mine"
TURN_ENEMY = "enemy"
_BOTH_TURNS = frozenset({TURN_MINE, TURN_ENEMY})


_IN_YOUR_PHASE_RE = re.compile(r"\bin your\b[^,.]*?\bphase\b|\bdans votre phase\b", re.IGNORECASE)


def ability_turn_sides(ability: AbilityEntry) -> frozenset[str]:
    """Dans quel(s) tour(s) — le sien (`TURN_MINE`), celui de l'adversaire
    (`TURN_ENEMY`) — une aptitude peut servir, pour la répartir entre les 2
    cartes du mode `fr-split`. Lu sur le qualificatif de `condition`
    (`_QUALIFIER_RE` : "Your"/"Enemy"/"Any" + phase ou tour), le même que la
    pastille « Ma phase »/« Phase ennemi »/« Les 2 phases ». Tout ce qui n'en
    porte pas va dans les 2 tours plutôt que d'en manquer un : passif,
    réaction (une réaction à une aptitude de combat ou de tir se déclenche
    dans les 2 tours), « Début de round » (précède le tour de chacun, quel
    que soit le joueur qui commence), condition sans qualificatif. Le
    déploiement (avant le round 1, dans aucun tour) renvoie `TURN_MINE` pour
    ne jamais être dupliqué, mais `pdf_builder` le sort de toute façon des
    cartes de tour pour sa propre carte « Déploiement »."""
    if classify_phase(ability) == "deploy":
        return frozenset({TURN_MINE})
    # sous-section « Dîme de Sang » : le déverrouillage (« Des Crânes pour le
    # Trône de Crânes ») a lieu au début de *n'importe quel* tour, toutes les
    # options doivent donc figurer sur les 2 cartes, quel que soit le tour où
    # elles s'utilisent ensuite.
    if ability.ability_category == "blood_tithe":
        return _BOTH_TURNS
    condition = ability.condition or ""
    # réaction limitée à votre phase (« … for this unit in your movement
    # phase », ex. « Avancer dans la Trace » du Thundertusk) : votre tour seul
    if ("reaction:" in condition.lower() or ability.is_reaction) and _IN_YOUR_PHASE_RE.search(condition):
        return frozenset({TURN_MINE})
    if ability.is_reaction or "reaction:" in condition.lower() or condition.strip().lower() == "passive":
        return _BOTH_TURNS
    m = _QUALIFIER_RE.search(condition)
    if m is None:
        return _BOTH_TURNS
    qualifier = m.group(1).lower()
    if qualifier == "your":
        return frozenset({TURN_MINE})
    if qualifier == "enemy":
        return frozenset({TURN_ENEMY})
    return _BOTH_TURNS


#: titres et rang des sous-sections fixes d'un bandeau de phase en mode
#: sectionné (cf. `ability_section`) — les sous-sections d'unité suivent,
#: dans l'ordre de première apparition (celui des cartes, héros d'abord).
SECTION_BASE = "Règles de base"
SECTION_ARMY = "Règles d'armée"
#: sorts, manifestations (convocations) et prières ont chacun leur propre
#: sous-section, quelle que soit leur origine (domaine d'armée ou warscroll) —
#: sorts et manifestations contigus (demande de l'utilisateur).
_CAST_SECTIONS = {"spell": "Sorts", "manifestation": "Manifestations", "prayer": "Prières"}
_SECTION_RANK = {SECTION_BASE: 0, SECTION_ARMY: 1, "Sorts": 3, "Manifestations": 4, "Prières": 5}

#: nombre de colonnes de la grille d'une sous-section, et seuils de longueur
#: de texte (caractères, après `_clean_text`) au-delà desquels une aptitude
#: occupe 2 puis 3 colonnes plutôt qu'une.
_SECTION_COLUMNS = 3
_SPAN_2_THRESHOLD = 450
_SPAN_3_THRESHOLD = 1100

_SECTION_HEADER_STYLE = ParagraphStyle(
    "wc_section",
    fontName="Helvetica-Bold",
    fontSize=8,
    leading=10,
    textColor=colors.white,
)
_SECTION_HEADER_BG = colors.black


def ability_section(ability: AbilityEntry) -> str:
    """Sous-section d'une aptitude dans son bandeau de phase (mode
    sectionné) : sous-section de choix (« Délires », « Dîme de Sang »...),
    puis `AbilityEntry.section` posé par `pdf_builder` (« Règles de base »/
    « Règles d'armée »), sinon le nom de son/ses warscroll(s)."""
    category = _ability_category(ability)
    if category in CHOICE_CATEGORIES:
        return _CATEGORY_LABELS_FR[category]
    if category in _CAST_SECTIONS:
        return _CAST_SECTIONS[category]
    if ability.section:
        return ability.section
    if ability.warscrolls:
        return " / ".join(ability.warscrolls)
    return SECTION_ARMY


def _section_rank(title: str) -> int:
    if title in _SECTION_RANK:
        return _SECTION_RANK[title]
    if title in _CATEGORY_LABELS_FR.values():
        return 2  # sous-section de choix : une règle d'armée, juste après
    return 6


def _ability_span(ab: AbilityEntry) -> int:
    if ab.full_width:
        return _SECTION_COLUMNS
    n = len(_clean_text(strip_flavor(ab.description)))
    return 3 if n > _SPAN_3_THRESHOLD else 2 if n > _SPAN_2_THRESHOLD else 1
