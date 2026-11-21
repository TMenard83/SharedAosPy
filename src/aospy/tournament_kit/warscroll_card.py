"""Rendu « carte maison » d'un warscroll (`WarscrollData`), en remplacement de
la copie de page PDF du battletome — mise en forme validée sur une maquette
HTML (artefact partagé avec l'utilisateur) puis adaptée aux contraintes de
reportlab : bandeau de phase horizontal (pas de texte pivoté dans une
cellule à hauteur dynamique) et badges en texte coloré/gras (reportlab ne
peint pas de fond coloré à l'intérieur d'un `Paragraph`) plutôt qu'en
pastilles pleines — même organisation et même code couleur que la maquette,
juste une traduction honnête vers ce que le moteur de rendu sait faire.

Aucune traduction du texte de règle ni des noms (unité/aptitude/arme/mot-clé
CSV) — seuls les libellés qu'on invente nous-mêmes (Passif, Réaction,
Ma phase/Phase ennemi/Les 2 phases, noms de phase) sont en français, les
7 derniers vérifiés sur `data/Manuel du général/MdG26-27 Aptitudes.pdf`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace as _dc_replace
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Flowable, KeepTogether, Paragraph, Spacer, Table, TableStyle

from .translation.tactic_cards import SubTactic, TacticCard
from .translation.wahapedia_lookup import _ENHANCEMENT_CATEGORY_LABELS, AbilityEntry, WarscrollData, WeaponEntry

#: police des noms de carte (unité/règle/tactique) — Cinzel Bold, la même que
#: la maquette HTML (`font-family:"Cinzel"`, chargée depuis Google Fonts,
#: `.card .head h2{font-weight:700}`) plutôt que le Helvetica-Bold générique
#: utilisé avant : un vrai display serif capitalisé, cohérent avec
#: l'esthétique "tome" du reste de la carte (bandeau nom/rôle sombre,
#: parchemin). Embarqué en TTF plutôt que référencé par un chemin système
#: (`scratch/build_pdf.py` pointait vers `C:/Windows/Fonts/...`, un chemin
#: Windows qui ne marche que sur une machine précise) : Cinzel est sous SIL
#: Open Font License, librement redistribuable, donc le fichier vit dans le
#: paquet (`assets/Cinzel-Bold.ttf`, embarqué via `package-data` dans
#: `pyproject.toml`) et se charge par chemin relatif à ce module, portable
#: partout. Enregistré une seule fois, au niveau module (pas dans une
#: fonction appelée par carte) ; repli silencieux sur Helvetica-Bold si le
#: fichier venait à manquer (ex. install sans les données du paquet) plutôt
#: que de faire planter toute la génération de PDF pour une police décorative.
CARD_TITLE_FONT = "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("Cinzel-Bold", str(Path(__file__).parent / "assets" / "Cinzel-Bold.ttf")))
    CARD_TITLE_FONT = "Cinzel-Bold"
except Exception:
    pass

# -- Code couleur des phases : mêmes valeurs hex que la maquette HTML,
# échantillonnées au pixel sur le Manuel du général (cf. historique de
# conception) ; "any" (vert) est la 9e catégorie, hors des 8 bandeaux du
# livre, pour les réactions qui ne sont liées à aucune phase précise.
# "deploy" (Phase de Déploiement, avant le round 1 — pas l'une des 7 phases
# du cycle de round) échantillonné séparément sur le PDF « Armée de Renom »
# LRL fourni par l'utilisateur (bandeau noir de "Phase de Déploiement",
# proche mais pas identique au noir de "start") : une aptitude de
# déploiement (`ability_phase` Wahapedia vide côté `generic_core_abilities.json`/
# `season_rules.json`, ces règles n'étant pas dans le CSV Wahapedia)
# retombait sinon dans le bandeau vert "any", signalé par l'utilisateur.
_PHASE_COLORS: dict[str, tuple[str, str]] = {
    "deploy": ("#282d31", "#f2ecdb"),
    "round_start": ("#1f2d3d", "#eaf1f8"),
    "asterism": ("#2a2456", "#e8e6f5"),
    "start": ("#211e20", "#f2ecdb"),
    "hero": ("#a3862f", "#221a08"),
    "move": ("#7d7b86", "#1c1a22"),
    "shoot": ("#2c5964", "#eaf4f6"),
    "charge": ("#b8632f", "#241505"),
    "melee": ("#7c333c", "#fbeaec"),
    "end": ("#5f3f71", "#f4ecf9"),
    "any": ("#4f6b2e", "#eef2e2"),
}
_PHASE_LABELS: dict[str, str] = {
    "deploy": "Déploiement", "round_start": "Début de round", "asterism": "Astérisme",
    "start": "Début de tour", "hero": "Phase des héros",
    "move": "Phase de mouvement", "shoot": "Phase de tir", "charge": "Phase de charge", "melee": "Phase de mêlée",
    "end": "Fin de tour", "any": "N'importe quelle phase",
}
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
    "asterism", "deploy", "round_start", "start", "hero", "move", "shoot", "charge", "melee", "end", "any",
]

#: Ordre des cartes du mode `fr-split` (`pdf_builder`) : « N'importe quelle
#: phase » (vert) suit directement « Déploiement », les deux formant la
#: carte « Déploiement » (demande explicite de l'utilisateur) ; les cartes
#: de tour n'en ont donc plus, et « Fin de tour » y est le dernier bandeau,
#: suivi directement des cartes de tactique de bataille.
SPLIT_PHASE_ORDER = [
    "asterism", "deploy", "any", "round_start", "start", "hero", "move", "shoot", "charge", "melee", "end",
]

#: reportlab ne peint pas de fond derrière un texte qui coule dans un
#: `Paragraph` (pas de vraie pastille comme dans la maquette HTML) — les
#: teintes doivent donc être nettement plus saturées que le corps de texte
#: (gris/noir) pour continuer à se voir comme des badges plutôt que du texte
#: normal, avec un léger cadrage `[ ]` en plus pour rester lisibles même en
#: N&B.
_BADGE_NEUTRAL = "#2e5c8a"   # timing : fréquence, condition, passif — en contour (`outline`), pour ne pas se confondre avec le bleu de la phase de tir
_BADGE_KEYWORD = "#6e6259"   # classification : mot-clé d'aptitude sans couleur propre — taupe neutre, le jaune étant réservé à la phase des héros (demande de l'utilisateur)
_BADGE_MULTI_PHASE = "#56606b"  # mot-clé servant dans plusieurs phases (ATTACK, RAMPAGE) — ardoise, en contour
_BADGE_STAT = "#1f6b78"      # stat d'arme mise en avant : portée
_BADGE_REACT = "#8c1f1f"     # alerte : réaction
_BADGE_SPELL = "#5b3a8f"     # sort — valeur d'incantation (points_type "Spell")
_BADGE_PRAYER = "#2e6b4f"    # prière — valeur de prière (points_type "Prayer")
_BADGE_COMMAND = "#7a4a1f"   # point de commandement — coût en PC (points_type "Command")
_BADGE_RAGE = "#a3300f"      # dé de rage (Règles de Saison 2026-27) — cf. `_resource_badges`
_BADGE_FURY = "#d9620b"      # point de fureur (Règles de Saison 2026-27)
_BADGE_SEASON = "#c8451c"    # badge d'origine « Saison » (rouge orangé, demande de l'utilisateur)
_BADGE_BLOOD = "#7a1620"     # dime de sang — coût en points de sang (points_type "Blood tithe", Blades of Khorne)
_BADGE_FACTION = "#6b2545"   # mot-clé d'aptitude propre à une seule faction (ex. Delusion, Tidal) — cf. `_keyword_pills`
_BADGE_SOURCE = "#4a5260"    # source du texte (BT, FP, MdG, SIMPLE, Wahapedia...) — une seule couleur pour toutes (demande de l'utilisateur)
_BADGE_WARSCROLL = "#161a2b"  # warscroll porteur d'une aptitude sortie de sa carte (mode `fr-split`) — cf. `_warscroll_pills`

#: mots-clés d'aptitude (`AbilityEntry.keywords`) propres à une seule faction —
#: posé une fois par `set_faction_specific_keywords` (appelé par
#: `pdf_builder.build_roster_pdf` juste après avoir chargé `WahapediaLookup`,
#: cf. `WahapediaLookup.faction_specific_keywords`) plutôt que passé en
#: paramètre à travers la dizaine de fonctions qui construisent le tableau
#: d'aptitudes (`_ability_row_flowables` -> ... -> `_append_ability_groups`) :
#: un seul jeu de données pour toute la génération d'un PDF, jamais rechargé
#: ni recalculé par carte. Normalisé en minuscules, comme le renvoie
#: `faction_specific_keywords`.
_FACTION_KEYWORDS: frozenset[str] = frozenset()


#: Masque les pastilles « Ma phase »/« Phase ennemi »/« Les 2 phases » le
#: temps d'un `render_rule_card(..., hide_turn_qualifier=True)` — cartes du
#: mode `fr-split`, dont le titre dit déjà le tour et où une aptitude des 2
#: tours figure sur les 2 cartes (demande explicite de l'utilisateur).
#: Global plutôt que passé en
#: paramètre, pour la même raison que `_FACTION_KEYWORDS` : la pastille est
#: construite tout en bas d'une dizaine d'appels imbriqués.
_HIDE_TURN_QUALIFIER = False

#: `render_rule_card(..., sectioned=True)` — bandeaux de phase découpés en
#: sous-sections titrées (`_append_sectioned_ability_groups`) : le warscroll
#: porteur et l'origine « MdG » sont dans le titre de la sous-section, leurs
#: pastilles feraient doublon. Global pour la même raison que
#: `_HIDE_TURN_QUALIFIER`.
_SECTIONED = False
#: `render_rule_card(..., base_last=True)` : « Règles de base » en dernière
#: sous-section de chaque bandeau de phase (cf. `_sectioned_phase_items`).
_BASE_LAST = False


def set_faction_specific_keywords(keywords: frozenset[str]) -> None:
    """À appeler une fois par génération de PDF (cf. `pdf_builder.py`) avant
    tout rendu de carte — voir `_FACTION_KEYWORDS`."""
    global _FACTION_KEYWORDS
    _FACTION_KEYWORDS = keywords


#: Libellé français des mots-clés d'aptitude génériques (règles de base),
#: même vocabulaire que `generic_core_abilities.json`/`faction_rules_fr.json`
#: (« Base,Mouvement », « Sort, Convocation », « Saccage »...). Les mots-clés
#: propres à une faction (Delusion, Blood Tithe...) n'y sont pas : leur nom
#: français officiel se curate au cas par cas, jamais deviné.
_KEYWORD_LABELS_FR = {
    "core": "BASE", "attack": "ATTAQUE", "fight": "CORPS À CORPS", "shoot": "TIR",
    "move": "MOUVEMENT", "run": "COURSE", "retreat": "REPLI", "charge": "CHARGE",
    "rampage": "SACCAGE", "spell": "SORT", "prayer": "PRIÈRE", "summon": "CONVOCATION",
    "unbind": "DISSIPATION", "banish": "BANNISSEMENT", "deploy": "DÉPLOIEMENT",
    "deploy terrain": "DÉPLOIEMENT DE TERRAIN",
}

#: Traduit les pastilles de mots-clés (`_KEYWORD_LABELS_FR`) — posé par
#: `set_french_keywords` (modes `fr*`), global pour la même raison que
#: `_FACTION_KEYWORDS`.
_FRENCH_KEYWORDS = False


#: « Placer » (« Set up ») est un terme de règle (règles de base, Placer des
#: unités) : toujours en gras dans les modes français et `*-split-simple` (demande de
#: l'utilisateur, `set_bold_set_up`).
#: Pas « déplacer »/« remplacer »/« emplacement » (lettre avant le mot).
_SET_UP_RE = re.compile(
    r"(?<![A-Za-zÀ-ÿ])(?:[Rr]e)?[Pp]lac(?:er|ez|é|ée|és|ées|ent|ant|era|eront)(?![A-Za-zÀ-ÿ])"
    r"|\b(?:[Ss]et|[Ss]ets|[Ss]etting)(?: (?:it|them|that unit|this unit|the target|each unit))? up\b"
)
_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")


def _bold_set_up(description: str) -> str:
    """Met en gras chaque « placé(e)(s) / placez / replacez… » (« set up »)
    hors d'un passage déjà en gras."""
    out, bold = [], 0
    for part in _TAG_SPLIT_RE.split(description):
        if part.startswith("<"):
            tag = part.lower().replace(" ", "")
            if tag == "<b>":
                bold += 1
            elif tag == "</b>":
                bold = max(0, bold - 1)
            out.append(part)
        elif bold:
            out.append(part)
        else:
            out.append(_SET_UP_RE.sub(lambda m: f"<b>{m.group(0)}</b>", part))
    return "".join(out)


_BOLD_SET_UP = False


def set_bold_set_up(enabled: bool) -> None:
    """À appeler une fois par PDF (cf. `pdf_builder.py`) : met « placé(e) /
    placez / set up » en gras dans le texte des aptitudes (`_bold_set_up`)."""
    global _BOLD_SET_UP
    _BOLD_SET_UP = enabled


def set_french_keywords(enabled: bool) -> None:
    """À appeler une fois par génération de PDF (cf. `pdf_builder.py`) avant
    tout rendu de carte — voir `_FRENCH_KEYWORDS`."""
    global _FRENCH_KEYWORDS
    _FRENCH_KEYWORDS = enabled


#: Traduit les capacités d'arme (`weapon_abilities_fr`) — modes `fr*` et
#: `hybrid`, dont les noms d'arme sont aussi en français ; distinct de
#: `_FRENCH_KEYWORDS`, les pastilles de mots-clés d'aptitude restant
#: anglaises à côté du texte Wahapedia (EN) du mode `hybrid`.
_FRENCH_WEAPON_TAGS = False


def set_french_weapon_tags(enabled: bool) -> None:
    """Cf. `_FRENCH_WEAPON_TAGS` — même appel unique que `set_french_keywords`."""
    global _FRENCH_WEAPON_TAGS
    _FRENCH_WEAPON_TAGS = enabled


#: Libellés maison en anglais (mode `en-split-simple`, `set_english_labels`) —
#: global pour la même raison que `_FACTION_KEYWORDS`. Les données internes
#: (badges d'origine « Saison »/« MdG », sous-sections « Règles de base »...)
#: restent en français, la logique de tri s'appuie dessus : seul le texte
#: affiché passe par `tr`.
_ENGLISH_LABELS = False


def set_english_labels(enabled: bool) -> None:
    """À appeler une fois par génération de PDF (cf. `pdf_builder.py`) avant
    tout rendu de carte — voir `_ENGLISH_LABELS`."""
    global _ENGLISH_LABELS
    _ENGLISH_LABELS = enabled


def english_labels() -> bool:
    return _ENGLISH_LABELS


#: libellé maison français -> anglais (vocabulaire des Core Rules GW). Clés
#: exactes, telles qu'affichées (pastilles en majuscules, bandeaux et titres
#: en casse normale).
_EN_LABELS: dict[str, str] = {
    # bandeaux de phase
    "Déploiement": "Deployment", "Début de round": "Start of battle round", "Astérisme": "Asterism",
    "Début de tour": "Start of turn", "Phase des héros": "Hero phase", "Phase de mouvement": "Movement phase",
    "Phase de tir": "Shooting phase", "Phase de charge": "Charge phase", "Phase de mêlée": "Combat phase",
    "Fin de tour": "End of turn", "N'importe quelle phase": "Any phase",
    # catégories / sous-sections
    "Aptitudes": "Abilities", "Sorts": "Spells", "Prières": "Prayers", "Manifestations": "Manifestations",
    "Délires": "Delusions", "Dîme de Sang": "Blood Tithe", "Bénédictions de Khaine": "Blessings of Khaine",
    "Vocation au Chaos": "Pledge to Chaos",
    "Règles de base": "Core rules", "Règles d'armée": "Army rules",
    # pastilles de timing
    "Ma phase": "Your phase", "Les 2 phases": "Both turns", "Phase ennemi": "Enemy phase",
    "×1 / TOUR": "×1 / TURN", "×1 / BATAILLE": "×1 / BATTLE", "×1 / TOUR (ARMÉE)": "×1 / TURN (ARMY)",
    "×1 / BATAILLE (ARMÉE)": "×1 / BATTLE (ARMY)", "×1 / ROUND (ARMÉE)": "×1 / ROUND (ARMY)",
    "×1 / ROUND": "×1 / ROUND", "×1 / PHASE": "×1 / PHASE", "×1 / PHASE (ARMÉE)": "×1 / PHASE (ARMY)",
    "DÉBUT DU 1ER ROUND": "START OF FIRST BATTLE ROUND", "FIN DU 1ER ROUND": "END OF FIRST BATTLE ROUND",
    "PASSIF": "PASSIVE", "RÉACTION": "REACTION", "Réaction :": "Reaction:",
    "PHASE DE DÉPLOIEMENT": "DEPLOYMENT PHASE", "DÉBUT DU ROUND DE BATAILLE": "START OF BATTLE ROUND",
    "ILLIMITÉ": "UNLIMITED", "SORT": "SPELL", "PRIÈRE": "PRAYER", "ORDRE": "COMMAND",
    "DIME DE SANG": "BLOOD TITHE",
    # badges d'origine (`tag_ability_origin`, internes en français)
    "SAISON": "SEASON", "MDG": "GHB", "TACTIQUE": "TACTIC", "TRAITS DE BATAILLE": "BATTLE TRAITS",
    "TRAIT DE BATAILLE": "BATTLE TRAIT", "TRAIT HÉROÏQUE": "HEROIC TRAIT", "ARTEFACT DE POUVOIR": "ARTEFACT OF POWER",
    "TRAIT MONSTRUEUX": "MONSTROUS TRAIT", "MUTATION D'AIRAIN": "BRAZEN MUTATION",
    "MARQUE DES DIEUX SOMBRES": "BRAND OF THE DARK GODS", "BANNIÈRE ENSORCELÉE": "ENSORCELLED BANNER",
    "MÉDAILLE DE BRAVOURE": "DECORATION FOR VALOUR", "FABLE TERRIFIANTE": "TERRIFYING FOLK TALE",
    # carte d'unité
    "Portée": "Rng", "Invoquée": "Summoned",
    # cartes de tactique
    "ÉCHAUFFOURÉE": "AFFRAY", "FRAPPE": "STRIKE", "DOMINATION": "DOMINATION", "RÈGLE SPÉCIALE": "SPECIAL RULE",
    "PTS DE<br/>VICTOIRE": "VICTORY<br/>POINTS",
    # légende de la page de garde
    "Source du texte : MDG (Manuel du Général), BT (battletome), FP (faction pack), AQSHY, WAHAPEDIA "
    "(anglais). Traits de Bataille, Formation : catégorie de règles d'armée.":
        "Text source: GW APP (official Warhammer Age of Sigmar app), CORE RULES (GW Core Rules), GHB (General's Handbook), BT (battletome), "
        "FP (faction pack), AQSHY, WAHAPEDIA. Battle Traits, Formation: army rule category.",
    "Texte adapté, pas le verbatim : en cas de litige, revenir à la règle d'origine.":
        "Adapted text, not verbatim: in case of dispute, refer to the original rule.",
    "Aptitude de base du jeu (Core) ; règle de la saison en cours (MdG 2026-27).":
        "Core ability; current season rule (General's Handbook 2026-27).",
    "Fréquence — (ARMÉE) : une seule fois pour toute l'armée ; passif : toujours actif, rien à déclarer.":
        "Frequency — (ARMY): once for the whole army; passive: always active, nothing to declare.",
    "Réaction : utilisée en réponse à l'aptitude indiquée.": "Reaction: used in response to the stated ability.",
    "Mot-clé d'aptitude, à la couleur de sa phase (Mouvement, Tir, Charge, Corps à Corps).":
        "Ability keyword, in the colour of its phase (Move, Shoot, Charge, Fight).",
    "Mot-clé d'aptitude valable dans plusieurs phases.": "Ability keyword used in several phases.",
    "Magie (sort, manifestation, bannissement…) ; prière. Illimité : utilisable plusieurs fois par tour.":
        "Magic (spell, manifestation, banishment…); prayer. Unlimited: can be used several times per turn.",
    "Unité qui porte l'aptitude (pour un sort signature : son lanceur).":
        "Unit that has the ability (for a signature spell: its caster).",
    "Autre mot-clé d'aptitude (Tactique : règle spéciale d'une carte de tactique) ; bordeaux : propre à la faction.":
        "Other ability keyword (Tactic: special rule of a battle tactic card); burgundy: faction-specific.",
    "Aptitude : valeur de lancement. Warscroll : niveau de Sorcier ; manifestation : valeur de lancement de sa convocation.":
        "Ability: casting value. Warscroll: Wizard level; manifestation: casting value of its summoning.",
    "Aptitude : valeur de récitation. Warscroll : niveau de Prêtre.": "Ability: chanting value. Warscroll: Priest level.",
    "Ordre : coût en points d’ordre": "Command: command point cost",
    "Dîme de sang : coût en points de dîme de sang": "Blood tithe: blood tithe point cost",
    "Dés de rage : « +N » gagnés, sinon nombre dépensé": "Rage dice: “+N” gained, otherwise number spent",
    "Niveau de fureur : « +N » augmenté, sinon diminué": "Fury level: “+N” increased, otherwise decreased",
    "NOM D'UNITÉ": "UNIT NAME", "MOT-CLÉ": "KEYWORD", "ATTAQUE": "ATTACK", "SACCAGE": "RAMPAGE", "TIR": "SHOOT",
    "BASE": "CORE", "MOUVEMENT": "MOVE", "COURSE": "RUN", "REPLI": "RETREAT", "CORPS À CORPS": "FIGHT",
    "BANNISSEMENT": "BANISH", "DISSIPATION": "UNBIND", "CONVOCATION": "SUMMON", "DÉPLOIEMENT": "DEPLOY",
    "DÉPLOIEMENT DE TERRAIN": "DEPLOY TERRAIN",
    # cartes de règle / pages du roster (`pdf_builder`)
    "Mon tour": "My turn", "Tour adverse": "Opponent's turn", "Tour de l'adversaire": "Opponent's turn",
    "Traits de Bataille": "Battle Traits",
    "Battle Tactic Cards :": "Battle Tactic Cards:",
    "⚠ Profil non trouvé (ni battletome, ni Wahapedia) pour : ": "⚠ Profile not found (neither battletome nor Wahapedia) for: ",
    "⚠ Règle non trouvée (ni battletome, ni Wahapedia) pour : ": "⚠ Rule not found (neither battletome nor Wahapedia) for: ",
    "ℹ Complété en anglais via Wahapedia (voir annexe en fin de document) : ":
        "ℹ Completed from Wahapedia (see appendix at the end of the document): ",
    "Généré le ": "Generated on ", "Légende des pictos": "Icon legend",
    "ANNEXE — CONTENU WAHAPEDIA (ANGLAIS)": "APPENDIX — WAHAPEDIA CONTENT",
    "Ce qui suit n'existe dans aucun des PDF fournis (battletomes, Manuel du général) : "
    "domaines de sorts/manifestations génériques, règles d'armée de renom, Régiments de Renom. "
    "Repris tel quel depuis data/wahapedia/ (Wahapedia, en anglais) — non traduit pour éviter tout contresens sur des règles de jeu.":
        "Generic spell/manifestation lores, Army of Renown rules and Regiments of Renown not covered elsewhere, "
        "taken as-is from data/wahapedia/ (Wahapedia).",
}

#: badges d'origine paramétrés (« Formation : X », « Optimisation (X) »...) :
#: préfixe français -> préfixe anglais, en majuscules comme la pastille.
_EN_LABEL_PREFIXES = (
    ("FORMATION : ", "FORMATION: "), ("RÉGIMENT DE RENOM : ", "REGIMENT OF RENOWN: "),
    ("OPTIMISATION (", "ENHANCEMENT ("),
    ("Drops : ", "Drops: "), ("Domaine de sorts : ", "Spell lore: "), ("Domaine de prières : ", "Prayer lore: "),
    ("Domaine de manifestations : ", "Manifestation lore: "), ("Carte de tactique : ", "Battle tactic card: "),
    ("Domaine de Sorts — ", "Spell Lore — "), ("Domaine de Prières — ", "Prayer Lore — "),
    ("Domaine de Manifestations — ", "Manifestation Lore — "),
)


def tr(text: str) -> str:
    """`text` (libellé maison français) en anglais en mode `en-split-simple`,
    inchangé sinon ou s'il n'a pas de traduction connue."""
    if not _ENGLISH_LABELS:
        return text
    if text in _EN_LABELS:
        return _EN_LABELS[text]
    for fr, en in _EN_LABEL_PREFIXES:
        if text.startswith(fr):
            return en + text[len(fr):]
    return text

#: mots-clés d'arme Wahapedia -> vocabulaire français déjà employé par les
#: entrées curées de `faction_rules_fr.json` (« Tir en Mêlée », « Crit
#: (Mortel) »...). « Blood-hungry »/« Wyrdflame », propres à une faction,
#: restent tels quels faute de verbatim (un profil d'arme curé les remplace).
_WEAPON_ABILITIES_FR = [
    (re.compile(r"\bShoot in Combat\b"), "Tir en Mêlée"),
    (re.compile(r"\bCrit \(Mortal\)"), "Crit (Mortel)"),
    (re.compile(r"\bCrit \(Auto-wound\)"), "Crit (Blessure Auto)"),
    (re.compile(r"\bCrit \(2 Hits\)"), "Crit (2 Touches)"),
    (re.compile(r"\(\+(\d+) Damage\)"), r"(+\1 Dégât)"),
    (re.compile(r"\(\+(\d+) Rend\)"), r"(+\1 Perf.)"),
    (re.compile(r"\bCompanion\b"), "Compagnon"),
]
_ANTI_TARGET_FR = {
    "infantry": "Infanterie", "monster": "Monstre", "hero": "Héros", "charge": "charge", "cavalry": "Cavalerie",
    "wizard": "Sorcier", "priest": "Prêtre", "manifestation": "Manifestation", "beast": "Bête",
    "war machine": "Machine de Guerre", "faction terrain": "Terrain de Faction", "daemon": "Démon",
    "unique": "Unique",
}
_ANTI_RE = re.compile(r"\bAnti-([A-Za-z ]+?)\s*(?=\()")


def weapon_abilities_fr(text: str) -> str:
    """Mots-clés d'un profil d'arme (« Shoot in Combat, Anti-INFANTRY (+1
    Rend) ») en français (modes `fr*`) ; un mot-clé inconnu reste tel quel."""
    for pattern, repl in _WEAPON_ABILITIES_FR:
        text = pattern.sub(repl, text)
    return _ANTI_RE.sub(
        lambda m: "Anti-" + _ANTI_TARGET_FR.get(m.group(1).strip().lower(), m.group(1).strip()) + " ", text,
    )


_PHASE_FIELD_TO_KEY = {
    "deployment phase": "deploy",
    "start of turn": "start", "hero phase": "hero", "movement phase": "move",
    "shooting phase": "shoot", "charge phase": "charge", "combat phase": "melee",
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
        return _PLAIN_CONDITION_FR.get(condition[m.end():].lstrip(" ,").lower())
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
    r"\b(Hero Phase|Movement Phase|Shooting Phase|Charge Phase|Combat Phase)\b", re.IGNORECASE,
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
    (`CHOICE_CATEGORIES`, cf. `pdf_builder._CHOICE_CLUSTERS`) va dans la
    phase de sa sous-section (`ability_phase`, posé par `pdf_builder`), même
    si son `condition` nomme une autre phase (« Your Combat Phase ») — c'est
    sa copie de choix, l'original reste à sa phase."""
    if ability.ability_category in CHOICE_CATEGORIES:
        return _PHASE_FIELD_TO_KEY[ability.ability_phase.strip().lower()]
    if any(_keyword_key(kw) == "asterism" for kw in (ability.keywords or "").split(",") if kw.strip()):
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
#: `pdf_builder._CHOICE_CLUSTERS`) passent en tête de leur bandeau.
CHOICE_CATEGORIES = frozenset({"delusion", "blood_tithe", "khaine_blessing", "chaos_pledge"})
_CHOICE_CATEGORY_KEYWORDS = {"delusion": "delusion", "blood_tithe": "blood tithe"}
_CATEGORY_ORDER = ["delusion", "blood_tithe", "khaine_blessing", "chaos_pledge", "normal", "spell", "prayer", "manifestation"]
_CATEGORY_LABELS_FR = {
    "normal": "Aptitudes", "spell": "Sorts", "prayer": "Prières", "manifestation": "Manifestations",
    "delusion": "Délires", "blood_tithe": "Dîme de Sang", "khaine_blessing": "Bénédictions de Khaine",
    "chaos_pledge": "Vocation au Chaos",
}
_CATEGORY_COLORS = {
    "normal": "#6b6555", "spell": _BADGE_SPELL, "prayer": _BADGE_PRAYER, "manifestation": _BADGE_STAT,
    "delusion": _BADGE_FACTION, "blood_tithe": _BADGE_BLOOD, "khaine_blessing": _BADGE_FACTION,
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


#: Police/taille des badges pleins (fréquence, condition, mot-clé...),
#: partagée par `_pill_natural_width` pour mesurer un texte *avant* de
#: construire la pastille — `Table.wrap(0, 0)` avait été essayé pour ça, mais
#: `wrap` avec une largeur disponible nulle force un `Paragraph` à se
#: réenligner sur son mot le plus long (le seul moyen pour lui de tenir dans
#: 0pt de large), ce qui renvoyait une largeur "naturelle" bien plus petite
#: que la vraie largeur sur une ligne — le badge gardait alors `width=None`
#: (jugé à tort assez court pour `max_width`) mais se faisait quand même
#: réenligner au rendu final, cette fois contraint par la vraie largeur de
#: colonne disponible (ex. "MA PHASE" coupé en "MA PH"/"ASE"). Mesurer la
#: largeur d'une ligne non enroulée avec `stringWidth` directement (comme
#: `_min_rail_height` le fait déjà pour le bandeau de phase) évite le
#: problème : jamais de `wrap()` avant que la largeur réelle ne soit connue.
_PILL_FONT = "Helvetica"
_PILL_FONT_SIZE = 6.6
_PILL_H_PADDING = 10  # LEFTPADDING + RIGHTPADDING de `_pill` (5 + 5)
_PILL_RADIUS = 4  # rayon des coins arrondis d'une pastille (`ROUNDEDCORNERS`)
#: marge de sécurité ajoutée à `_pill_natural_width` : sans elle, la largeur
#: passée en `colWidths` au `Paragraph` interne (largeur - `_PILL_H_PADDING`)
#: retombe exactement sur `stringWidth`, et une simple erreur d'arrondi flottant
#: (`36.4066 - 10 == 26.406599999999997 < 26.4066`) suffit alors à faire
#: réenligner le texte sur 2 lignes ("FRAPPE" -> "FRAPP"/"E") alors qu'il tient
#: très exactement sur une — vu en le comparant à un rendu sans cette marge.
_PILL_WIDTH_SLACK = 0.75


def _pill_natural_width(text: str) -> float:
    return stringWidth(text, _PILL_FONT, _PILL_FONT_SIZE) + _PILL_H_PADDING + _PILL_WIDTH_SLACK


def _reaction_trigger(ability: AbilityEntry) -> str | None:
    """Déclencheur d'une réaction (texte après « Reaction: »), `None` si
    l'aptitude n'en est pas une. Le préfixe de fréquence précède parfois
    "Reaction:" dans le même champ (ex. "Once Per Turn (Army), Reaction:
    ...") — la fréquence est déjà extraite à part par `_freq_pill`, tout ce
    qui précède "Reaction:" est jeté plutôt que de le montrer en double."""
    condition = (ability.condition or "").strip()
    if not condition or not (ability.is_reaction or "reaction:" in condition.lower()):
        return None
    return _translate_trigger(_clean_text(re.sub(r"^.*?reaction:\s*", "", condition, flags=re.IGNORECASE)).strip())


#: types d'aptitude cités par un déclencheur de réaction Wahapedia
_TRIGGER_ABILITY_FR = {
    "fight": "Corps à Corps", "shoot": "Tir", "charge": "Charge", "move": "Mouvement", "run": "Course",
    "retreat": "Repli", "spell": "Sort", "unlimited spell": "Sort Illimité", "prayer": "Prière",
    "attack": "Attaque", "rampage": "Rampage",
}
_TRIGGER_HEADS = [
    (re.compile(r"^You declared an? (?P<kw>[\w ]+?) ability", re.IGNORECASE), "Vous avez annoncé une aptitude"),
    (re.compile(r"^Opponent declared an? (?P<kw>[\w ]+?) ability", re.IGNORECASE),
     "L’adversaire a annoncé une aptitude"),
]
_TRIGGER_TAILS = [
    (re.compile(r"^ for this unit\.?$"), " pour cette unité"),
    (re.compile(r"^ for your general\.?$"), " pour votre général"),
    (re.compile(r'^ for a unit within (\d+)" of this unit\.?$'), r' pour une unité à \1" de cette unité'),
    (re.compile(r'^ for a friendly unit wholly within (\d+)" of this unit\.?$'),
     r' pour une unité amie entièrement à \1" de cette unité'),
    (re.compile(r"^\.?$"), ""),
]


def _translate_trigger(text: str) -> str:
    """Déclencheur anglais de Wahapedia (« You declared a FIGHT ability for
    this unit ») traduit quand il suit entièrement un schéma connu (début +
    type d'aptitude + fin) ; sinon laissé tel quel — jamais de
    demi-traduction."""
    if _ENGLISH_LABELS:
        return text
    plain = re.sub(r"<[^>]+>", "", text).strip()
    for head_re, head_fr in _TRIGGER_HEADS:
        m = head_re.match(plain)
        if not m:
            continue
        kw = _TRIGGER_ABILITY_FR.get(m.group("kw").strip().lower())
        rest = plain[m.end():]
        for tail_re, tail_fr in _TRIGGER_TAILS:
            if kw is not None and tail_re.match(rest):
                of = "d’" if kw[0] in "AEIOUÉ" else "de "
                return f"{head_fr} {of}{kw}{tail_re.sub(tail_fr, rest)}"
        return text
    m = _NAMED_TRIGGER_RE.match(plain)
    if m:
        name = _TRIGGER_NAMED_FR.get(m.group("name").strip().lower())
        rest = plain[m.end():]
        for tail_re, tail_fr in _TRIGGER_TAILS:
            if name is not None and tail_re.match(rest):
                return f"{_TRIGGER_WHO_FR[m.group('who').lower()]} « {name} »{tail_re.sub(tail_fr, rest)}"
    return text


#: réaction à une aptitude *nommée* (« You or your opponent declared the
#: ‘Eruption of Fury’ ability… ») : traduite seulement si le nom est connu
_NAMED_TRIGGER_RE = re.compile(
    r"^(?P<who>You or your opponent|You|Your opponent|Opponent) declared the [‘'’\"](?P<name>[^‘'’\"]+)[‘'’\"] ability",
    re.IGNORECASE)
_TRIGGER_WHO_FR = {
    "you or your opponent": "Vous ou l’adversaire avez annoncé", "you": "Vous avez annoncé",
    "your opponent": "L’adversaire a annoncé", "opponent": "L’adversaire a annoncé",
}
_TRIGGER_NAMED_FR = {"eruption of fury": "Éruption de Fureur"}


def _condition_pill(ability: AbilityEntry, max_width: float) -> tuple[Table, float] | None:
    """Le pendant `condition` (passif / réaction / qualificatif / brut) de
    `_freq_pill` — une seule pastille pleine, en pastille à liseré pour la
    réaction (elle reste la seule à porter *toujours* du texte de règle
    verbatim, donc potentiellement long — forcée à `max_width` pour se
    réenligner au lieu de déborder). Les autres badges (PASSIF, qualificatif,
    brut) se taillent d'abord sur leur propre contenu, comme les pastilles de
    mot-clé (`_keyword_pills`) — sans quoi le fond peint de la pastille
    s'étirait sur toute `max_width` même pour un texte court ("PASSIF").
    `max_width` ne sert de garde-fou (repli sur la même largeur forcée que la
    réaction) que si ce contenu se révèle malgré tout trop large une fois
    mesuré — un `condition` brut hors du vocabulaire couvert par
    `_PLAIN_CONDITION_FR` peut en théorie être long. La largeur renvoyée à
    côté de la pastille est celle réellement occupée (`max_width` si forcée,
    sinon la largeur naturelle) — c'est ce que `_pack_badges` utilise pour
    décider si la pastille suivante tient sur la même ligne."""
    condition = (ability.condition or "").strip()
    if not condition:
        return None
    trigger = _reaction_trigger(ability)
    if trigger is not None:
        if _SECTIONED:
            return None  # ligne en tête du texte, cf. `_ability_row_flowables`
        pill = _pill(f"<b>{tr('Réaction :')}</b> {trigger}", _BADGE_REACT, "#fbeaec", width=max_width, outline=True)
        return pill, max_width
    if condition.lower() == "passive" or condition.lower().startswith("passive ("):
        text = "PASSIF"
    elif _FREQ_RE.fullmatch(_normalize_condition(condition)):
        return None  # fréquence seule, déjà portée par `_freq_pill` (ex. « Light A Pyre »)
    else:
        qual = _qualifier_label(condition)
        if qual and _HIDE_TURN_QUALIFIER:
            return None
        text = qual.upper() if qual else (_plain_condition(_normalize_condition(condition)) or condition.upper())
    if text in _BAND_ONLY_CONDITIONS:
        return None
    text = tr(text)
    natural = _pill_natural_width(text)
    if natural > max_width:
        return _pill(text, _BADGE_NEUTRAL, "#eaf1f8", width=max_width, outline=True), max_width
    return _pill(text, _BADGE_NEUTRAL, "#eaf1f8", width=None, outline=True), natural


def _freq_pill(ability: AbilityEntry, max_width: float) -> tuple[Table, float] | None:
    freq = _frequency_label(ability.condition or "")
    if not freq:
        return None
    natural = _pill_natural_width(freq)
    if natural > max_width:
        return _pill(freq, _BADGE_NEUTRAL, "#eaf1f8", width=max_width, outline=True), max_width
    return _pill(freq, _BADGE_NEUTRAL, "#eaf1f8", width=None, outline=True), natural


#: Traduction du `points_type` d'une aptitude (Warscrolls_abilities.csv /
#: Faction_abilities.csv) vers le libellé de repli de sa pastille (utilisé
#: seulement quand l'aptitude ne porte aucune valeur numérique, cf.
#: `_cast_pill`) et vers la forme/couleur de son badge sinon — le
#: cercle/losange/hexagone de l'éditeur BattleScribe/Warhammer Age of
#: Sigmar: The App (cf. `_CastBadge`), qu'aucun badge ne portait encore ici
#: (perdu en repartant du prototype HTML, qui n'avait qu'une pastille
#: rectangulaire générique). `points` est la valeur d'incantation/de prière
#: ("7" -> "7+" à lancer) pour les deux premiers, un coût brut (en PC ou en
#: points de sang) pour "Command"/"Blood tithe" — jamais un seuil "+".
#: RÈGLE : chaque `points_type` a sa propre silhouette — deux types ne
#: partagent jamais une forme (vérifié par
#: `test_cast_badge_shapes_are_unique`), sinon un joueur les confond d'un
#: coup d'oeil. La couleur seule ne suffit pas (impression N&B, daltonisme).
#: "Blood tithe" (points_type de Faction_abilities.csv, propre aux Blades of
#: Khorne) n'a pas encore de faction important son armée depuis Wahapedia,
#: mais la donnée existe déjà dans le CSV — le badge est câblé par
#: anticipation plutôt que laissé en `_BADGE_KEYWORD` générique.
#: "Rage"/"Fury" (dés de rage/points de fureur des Règles de Saison 2026-27)
#: ne sont pas des `points_type` mais des ressources gagnées ou dépensées
#: (`AbilityEntry.resources`, cf. `_resource_badges`) — même règle de
#: silhouette unique : dé (carré arrondi) et flamme.
_CAST_BADGE_LABELS = {"Spell": "SORT", "Prayer": "PRIÈRE", "Command": "ORDRE", "Blood tithe": "DIME DE SANG"}
_CAST_BADGE_COLORS = {
    "Spell": _BADGE_SPELL, "Prayer": _BADGE_PRAYER, "Command": _BADGE_COMMAND, "Blood tithe": _BADGE_BLOOD,
    "Rage": _BADGE_RAGE, "Fury": _BADGE_FURY,
}
_CAST_BADGE_SHAPES = {
    "Spell": "circle", "Prayer": "diamond", "Command": "hexagon", "Blood tithe": "drop",
    "Rage": "die", "Fury": "flame",
}
_CAST_BADGE_FG = {
    "Spell": "#f3eefa", "Prayer": "#e6f3ec", "Command": "#f7ecd6", "Blood tithe": "#f9e3e3",
    "Rage": "#fff1ea", "Fury": "#fff6e5",
}


def _resource_badges(ability: AbilityEntry) -> list[tuple[Flowable, float]]:
    """Icônes dé de rage / point de fureur (`AbilityEntry.resources`), valeur
    inscrite au centre (« +2 » gagné, « 1-3 »/« X » dépensé)."""
    out = []
    for kind, value in ability.resources:
        badge = _CastBadge(_CAST_BADGE_SHAPES[kind], value, _CAST_BADGE_COLORS[kind], _CAST_BADGE_FG[kind])
        out.append((badge, badge.size))
    return out


def _cast_pill(ability: AbilityEntry, max_width: float) -> tuple[Flowable, float] | None:
    pts_type = (ability.points_type or "").strip()
    if not pts_type:
        return None
    value = (ability.points or "").strip()
    bg = _CAST_BADGE_COLORS.get(pts_type, _BADGE_KEYWORD)
    fg = _CAST_BADGE_FG.get(pts_type, "#f7ecd6")
    if value:
        text = f"{value}+" if pts_type in ("Spell", "Prayer") else value
        shape = _CAST_BADGE_SHAPES.get(pts_type, "circle")
        badge = _CastBadge(shape, text, bg, fg)
        return badge, badge.size
    # aucune valeur à inscrire au centre d'un badge : un sigle ("PC") n'a pas
    # sa place dans une forme aussi petite, on retombe sur la pastille
    # rectangulaire générique avec le libellé complet.
    label = tr(_CAST_BADGE_LABELS.get(pts_type, pts_type.upper()))
    natural = _pill_natural_width(label)
    if natural > max_width:
        return _pill(label, bg, fg, width=max_width), max_width
    return _pill(label, bg, fg, width=None), natural


#: mots-clés d'aptitude à couleur propre (demande de l'utilisateur) : SPELL
#: du même violet que le cercle de valeur de lancement d'un sort. Les badges
#: source (`_TEXT_SOURCE_KEYWORDS`, SIMPLE compris) ont tous `_BADGE_SOURCE`.
_KEYWORD_PILL_COLORS: dict[str, tuple[str, str]] = {
    # un sort, une manifestation ou une convocation (qui se lance comme un
    # sort) : même violet (demande de l'utilisateur) — EN et FR curé
    **{kw: (_BADGE_SPELL, _CAST_BADGE_FG["Spell"])
       for kw in ("spell", "sort", "manifestation", "summon", "convocation")},
    # prière sans valeur (avec valeur, le losange vert la masque) : vert prière
    **{kw: (_BADGE_PRAYER, _CAST_BADGE_FG["Prayer"]) for kw in ("prayer", "prière")},
    "saison": (_BADGE_SEASON, "#fff1ea"),
    # mot-clé d'aptitude liée à une phase : couleur du bandeau de cette phase
    # (demande de l'utilisateur) — EN Wahapedia et FR curé. ATTACK/RAMPAGE
    # servent dans plusieurs phases : pas de couleur de phase, cf.
    # `_MULTI_PHASE_KEYWORDS`.
    **{kw: _PHASE_COLORS[phase] for phase, kws in {
        "move": ("move", "mouvement", "run", "course", "retreat", "repli"),
        "shoot": ("shoot", "tir"),
        "charge": ("charge",),
        "melee": ("fight", "corps à corps"),
        "deploy": ("deploy", "déploiement", "deploy terrain", "déploiement de terrain"),
    }.items() for kw in kws},
    # bannissement/dissipation relèvent de la magie : violet des sorts
    # (demande de l'utilisateur)
    **{kw: (_BADGE_SPELL, _CAST_BADGE_FG["Spell"])
       for kw in ("banish", "bannissement", "unbind", "dissipation")},
    # aptitude de base (CORE) : noir (demande de l'utilisateur)
    "core": ("#141414", "#f2ecdb"),
    "base": ("#141414", "#f2ecdb"),
}


#: badge « source » du texte d'une aptitude (`origin` de
#: `faction_rules_fr.json`, « MdG » des règles génériques/de saison/de
#: tactique, « Simple » d'une compression, « Wahapedia » par défaut) — un
#: par aptitude, cf. `_keyword_pills`.
#: mots-clés servant dans plusieurs phases : ardoise en contour, sans lien
#: avec aucune phase (demande de l'utilisateur).
_MULTI_PHASE_KEYWORDS = frozenset({"attack", "attaque", "rampage", "saccage"})
_TEXT_SOURCE_KEYWORDS = frozenset({"bt", "bt (trad.)", "fp", "aqshy", "mdg", "core rules", "gw app", "simple", "wahapedia"})
_DEFAULT_TEXT_SOURCE = "Wahapedia"
#: badges d'origine « sous-source » (catégorie de règles d'armée dont vient
#: l'aptitude, cf. `tag_ability_origin`) : même couleur que les badges source
#: (demande de l'utilisateur), sans compter comme source exclusive.
_SUB_SOURCE_PREFIXES = ("trait de bataille", "traits de bataille", "formation")
#: mot-clé redit par le badge de valeur d'un sort/d'une prière (`_cast_pill`)
_CAST_TYPE_KEYWORDS = {"Spell": frozenset({"spell", "sort"}), "Prayer": frozenset({"prayer", "prière"})}


def _keyword_pills(ability: AbilityEntry) -> list[tuple[Table, float]]:
    # toute aptitude porte un badge source ; sans source curée, son texte
    # vient tel quel de Wahapedia (anglais)
    keywords = [kw.strip() for kw in (ability.keywords or "").split(",") if kw.strip()]
    if not any(kw.lower() in _TEXT_SOURCE_KEYWORDS for kw in keywords):
        ability = _dc_replace(ability, keywords=", ".join(keywords + [_DEFAULT_TEXT_SOURCE]))
    # "Deploy"/"Deployment" fait doublon avec la pastille de condition quand
    # celle-ci vaut déjà "Deployment Phase" (`_PLAIN_CONDITION_FR`) — ex.
    # Skaven « THE LURKING VERMINTIDE » affichait à la fois « DEPLOY » (brut,
    # non traduit, cf. absence d'équivalent à `_PLAIN_CONDITION_FR` ici) et
    # « PHASE DE DÉPLOIEMENT » côte à côte pour le même concept.
    is_deployment_condition = "deployment phase" in (ability.condition or "").lower()
    # dans sa sous-section de choix, le mot-clé qui la définit (« DELUSION »,
    # « BLOOD TITHE ») redit le titre de la sous-section : une ligne de
    # pastilles en moins par aptitude, pour qu'elle tienne sur une page.
    # La copie restée dans sa phase d'usage garde la pastille.
    section_keyword = _CHOICE_CATEGORY_KEYWORDS.get(ability.ability_category)
    # badge « source » du texte, un par aptitude et exclusif : vérbatim d'une
    # source (BT, FP, Aqshy, MdG...) ou compressé par nous (SIMPLE) — un texte
    # compressé n'est plus le vérbatim de sa source, SIMPLE la remplace
    # (demande de l'utilisateur). SAISON/BASE ne sont pas des sources.
    is_simple = any(kw.strip().lower() == "simple" for kw in ability.keywords.split(","))
    # le badge de valeur (cercle violet « 7+ », losange vert) dit déjà sort/
    # prière : la pastille SPELL/PRAYER ferait doublon (demande de l'utilisateur)
    pts_type = (ability.points_type or "").strip()
    cast_keywords = (
        _CAST_TYPE_KEYWORDS.get(pts_type, frozenset()) if (ability.points or "").strip() else frozenset()
    )
    out = []
    for kw in ability.keywords.split(","):
        kw = kw.strip().upper()
        if not kw:
            continue
        if is_simple and kw.lower() in _TEXT_SOURCE_KEYWORDS and kw.lower() != "simple":
            continue
        # « DÉPLOIEMENT »/« DÉPLOIEMENT DE TERRAIN » redisent le bandeau
        # « Déploiement » ; une aptitude jouée une fois par partie se lit en
        # entier (demande de l'utilisateur)
        if is_deployment_condition and kw.lower() in (
            "deploy", "deployment", "déploiement", "déploiement de terrain", "deploy terrain",
        ):
            continue
        if kw.lower() == section_keyword:
            continue
        if kw.lower() in cast_keywords:
            continue
        if kw.lower() in ("unlimited", "illimité"):
            # « Illimité » en français, couleur de son type de lancement (violet
            # pour un sort, vert pour une prière) — demande de l'utilisateur
            kw = tr("ILLIMITÉ")
            pts = (ability.points_type or "").strip()
            kinds = {k.strip().lower() for k in ability.keywords.split(",")}
            if pts == "Prayer" or kinds & {"prayer", "prière"}:
                bg, fg = _BADGE_PRAYER, _CAST_BADGE_FG["Prayer"]
            else:
                bg, fg = _BADGE_SPELL, _CAST_BADGE_FG["Spell"]
        elif kw.lower() in _TEXT_SOURCE_KEYWORDS or kw.lower().startswith(_SUB_SOURCE_PREFIXES):
            bg, fg = _BADGE_SOURCE, "#eef0f3"
        elif kw.lower() in _KEYWORD_PILL_COLORS:
            bg, fg = _KEYWORD_PILL_COLORS[kw.lower()]
        elif kw.lower() in _FACTION_KEYWORDS:
            bg, fg = _BADGE_FACTION, "#f7e6ee"
        elif kw.lower() in _MULTI_PHASE_KEYWORDS:
            bg, fg = _BADGE_MULTI_PHASE, "#eef0f3"
        else:
            bg, fg = _BADGE_KEYWORD, "#f2eeea"
        outline = kw.lower() in _MULTI_PHASE_KEYWORDS
        if _FRENCH_KEYWORDS:
            kw = _KEYWORD_LABELS_FR.get(kw.lower(), kw)
        kw = tr(kw)
        out.append((_pill(kw, bg, fg, outline=outline) if outline else _pill(kw, bg, fg), _pill_natural_width(kw)))
    return out


def _warscroll_pills(ability: AbilityEntry, max_width: float) -> list[tuple[Table, float]]:
    """Un badge par warscroll porteur (`AbilityEntry.warscrolls`, posé
    uniquement en mode `fr-split`) — même bleu nuit que l'en-tête des cartes
    d'unité, pour se lire comme « renvoi vers la carte X » et se distinguer
    d'un coup d'œil des mots-clés. Un nom d'unité peut être long
    ("Lord-Celestant on Gryph-Charger") : borné à `max_width` comme les
    autres pastilles plutôt que de déborder de la colonne de badges."""
    # en mode sectionné, le titre de sous-section dit déjà l'unité — sauf
    # dans « Sorts »/« Manifestations »/« Prières », qui mélangent domaine
    # d'armée et sorts/prières signature (propres à un warscroll) : la
    # pastille y désigne le lanceur — ni dans une sous-section de choix
    # (« Délires »...), dont le titre ne nomme pas l'unité : la pastille dit
    # que l'option dépend d'elle (ex. « Épicentre de l'Illusion », Ushoran).
    category = _ability_category(ability)
    if _SECTIONED and category not in _CAST_SECTIONS and category not in CHOICE_CATEGORIES:
        return []
    out = []
    for name in ability.warscrolls:
        text = name.upper()
        natural = _pill_natural_width(text)
        if natural > max_width:
            out.append((_pill(text, _BADGE_WARSCROLL, "#f2ecdb", width=max_width), max_width))
        else:
            out.append((_pill(text, _BADGE_WARSCROLL, "#f2ecdb", width=None), natural))
    return out


#: Aptitude passive qui fait varier une caractéristique du profil selon les
#: dégâts subis par l'unité (« Battle Damaged »/« Stigmates de Guerre »,
#: « Necromantic Limits », « Runic Power »...) — cf. `is_profile_modifier`.
#: Bilingue : le texte est l'anglais Wahapedia ou le français patché
#: (`faction_rules_fr.json`, qui garde le `condition` Wahapedia).
_DAMAGE_STATE_RE = re.compile(
    r"while this unit has [^.]*?damage points?|tant qu(?:e cette unité|['’]elle) a [^.]*?dégâts?", re.IGNORECASE,
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
    r"\b(?:declare|annonce|friendly|enemy|amie?s?|ennemie?s?|other units?|autres? unités?)\b", re.IGNORECASE,
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


_IN_YOUR_PHASE_RE = re.compile(
    r"\bin your\b[^,.]*?\bphase\b|\bdans votre phase\b", re.IGNORECASE
)


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


def _wielder_ratios(description: str) -> dict[str, str]:
    """`{nom d'arme (normalisé, minuscules) -> "N/M"}` à partir du texte
    libre de restriction du warscroll (ex. « 1/5 models can replace their
    Warhammer with a Grandhammer » -> {"grandhammer": "1/5"}). Même source
    que `engine/loadout.py` lit déjà côté moteur de combat."""
    text = re.sub(r"<[^>]+>", " ", description or "")
    out: dict[str, str] = {}
    for ratio, weapon in _WIELDER_RATIO_RE.findall(text):
        out[weapon.strip().lower()] = ratio
    return out


def _safe_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Comme `Paragraph(text, style)`, mais tolérant : `data/wahapedia/*.csv`
    est une donnée externe scrapée, parfois corrompue (ex. une balise HTML
    tronquée en plein milieu d'un champ, cf. `pdf_builder._safe_paragraph` —
    même pattern, dupliqué ici pour éviter un import circulaire avec
    `pdf_builder.py`) — on retombe sur le texte brut plutôt que de faire
    planter toute la génération pour une seule entrée abîmée."""
    try:
        return Paragraph(text, style)
    except Exception:
        stripped = re.sub(r"<[^>]*>", " ", text).replace("<", " ").replace(">", " ")
        return Paragraph(re.sub(r"\s+", " ", stripped).strip(), style)


def _clean_text(html: str) -> str:
    """Nettoyage minimal du HTML-ish Wahapedia pour `Paragraph` : `<a>`
    déballé, `<span class="kwb...">` -> `<b>`, listes -> puces, entités mal
    formées échappées. Même logique que `pdf_builder.clean_html` (pas
    dupliquée pour éviter toute divergence de rendu texte)."""
    from .pdf_builder import clean_html
    return clean_html(html)


# -- Styles --------------------------------------------------------------

#: fond de page du kit de tournoi (couvertures/cartes) — jaune pâle façon
#: parchemin, c'était le fond des cartes elles-mêmes avant que celles-ci ne
#: passent en blanc (cf. `_CARD_BG` ci-dessous) ; exporté (pas de préfixe
#: `_`) pour que `pdf_builder.py` en peigne le fond de chaque page.
PAGE_BG = colors.HexColor("#f8f2e3")
#: fond des cartes elles-mêmes — blanc plutôt que `PAGE_BG`, pour qu'une
#: carte se détache nettement du fond de page jaune pâle (demande explicite
#: de l'utilisateur : plus lisible que l'ancien parchemin sur parchemin).
_CARD_BG = colors.white
_STEEL_LINE = colors.HexColor("#c9bd9a")
_STEEL = colors.HexColor("#4a4536")
_INK = colors.HexColor("#14172a")

#: titre d'une aptitude — 10,5 pt pour se détacher nettement des sous-titres
#: en gras 8 pt du texte (Annonce/Effet, Entrée/Sortie...), demande de
#: l'utilisateur.
_NAME_STYLE = ParagraphStyle("wc_name", fontName="Helvetica", fontSize=10.5, leading=13, textColor=_INK)
_TEXT_STYLE = ParagraphStyle("wc_text", fontName="Helvetica", fontSize=8, leading=10.5, textColor=_STEEL, spaceBefore=1)
#: titres d'en-tête de carte — blancs sur le bandeau nuit (`#161a2b`) plutôt
#: que crème : demande explicite de l'utilisateur, plus lisible.
_HEAD_STYLE = ParagraphStyle("wc_head", fontName=CARD_TITLE_FONT, fontSize=13, leading=15, textColor=colors.white)
_ROLE_STYLE = ParagraphStyle("wc_role", fontName="Helvetica", fontSize=7, leading=9, textColor=colors.white)
#: nom français sous le nom anglais d'une carte d'unité (`WarscrollData.subtitle`) :
#: petit et estompé, le nom anglais (celui de l'App) reste le repère.
_SUBTITLE_STYLE = ParagraphStyle("wc_subtitle", fontName="Helvetica-Oblique", fontSize=7, leading=8.5, textColor=colors.HexColor("#a9adbd"))
_STAT_STYLE = ParagraphStyle("wc_stat", fontName="Helvetica", fontSize=6.5, leading=17, textColor=_STEEL, alignment=1)
_META_STYLE = ParagraphStyle("wc_meta", fontName="Helvetica", fontSize=7.5, leading=10, textColor=_STEEL)
_WHD_STYLE = ParagraphStyle("wc_whd", fontName="Helvetica", fontSize=6.5, leading=8, textColor=_STEEL, alignment=1)
_WNAME_STYLE = ParagraphStyle("wc_wname", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=_INK)
_WTAG_STYLE = ParagraphStyle("wc_wtag", fontName="Helvetica-Oblique", fontSize=6.5, leading=8, textColor=_STEEL)
_WVAL_STYLE = ParagraphStyle("wc_wval", fontName="Helvetica", fontSize=7.5, leading=9, textColor=_INK, alignment=1)
_KW_STYLE = ParagraphStyle("wc_kw", fontName="Helvetica", fontSize=6, leading=8, textColor=_STEEL)
_PROV_STYLE = ParagraphStyle("wc_prov", fontName="Helvetica-Oblique", fontSize=6, leading=8, textColor=_STEEL, alignment=2)


def _pill(text: str, bg_hex: str, fg_hex: str, width: float | None = None, outline: bool = False) -> Table:
    """Une vraie pastille pleine — une mini-`Table` à une cellule avec un
    fond peint (`Paragraph` seul ne peint jamais de fond derrière son texte,
    même en HTML-ish reportlab) : c'est le même principe que `_phase_band`
    utilisait déjà pour son bandeau, appliqué à chaque badge individuel
    plutôt qu'à un texte coloré entre crochets. `width=None` laisse la
    pastille se tailler sur son contenu (badges courts : fréquence,
    qualificatif, mot-clé) ; un `width` fixe force le retour à la ligne
    (la réaction, seule à porter une phrase complète et potentiellement
    longue). `outline=True` — la réaction seule — garde un fond transparent
    et un liseré coloré plutôt qu'un aplat, pour rester l'exception qui
    attire l'œil comme une alerte plutôt qu'une classification de plus.

    `width` est toujours résolu à une valeur explicite avant de bâtir la
    `Table` (jamais `colWidths=[None]`) : un `Paragraph` compte comme un
    contenu "à largeur variable" pour reportlab, donc une colonne laissée
    `None` ne se taille pas sur son texte mais s'étire pour occuper toute la
    largeur disponible dans la cellule englobante (`_ability_row_flowables`
    empile plusieurs pastilles dans une même cellule alignée à droite) — la
    pastille perdait alors sa largeur naturelle et s'étalait sur toute la
    colonne, ce qui rendait l'alignement à droite invisible (toutes bord à
    bord) plutôt que de faire ressortir chaque pastille par sa propre
    largeur."""
    _DRAWN_PILL_COLORS.add(bg_hex.lower())
    if width is None:
        width = _pill_natural_width(text)
    style = ParagraphStyle(
        f"wc_pill_{bg_hex}_{outline}", fontName="Helvetica", fontSize=6.6, leading=8.4,
        textColor=colors.HexColor(bg_hex if outline else fg_hex),
    )
    inner = _safe_paragraph(text, style)
    t = Table([[inner]], colWidths=[width])
    cell_style = [
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROUNDEDCORNERS", [_PILL_RADIUS] * 4),
    ]
    if outline:
        cell_style.append(("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(bg_hex)))
    else:
        cell_style.append(("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg_hex)))
    t.setStyle(TableStyle(cell_style))
    return t


#: espace laissé entre deux pastilles d'une même ligne par `_pill_row`
#: (`RIGHTPADDING` ci-dessous) — repris tel quel par `_pack_badges` pour que
#: son budget de largeur par ligne corresponde exactement à ce que la ligne
#: assemblée occupera réellement.
_PILL_GAP = 4

#: espace vertical ajouté entre deux lignes de badges empilées par
#: `_pack_badges` (via `spaceBefore`, respecté par Platypus même quand le
#: contenu d'une cellule est une simple liste de Flowables plutôt qu'un
#: Frame — cf. le commentaire sur `_CastBadge.spaceBefore`) — un peu d'air
#: pour que les pastilles ne se touchent pas verticalement.
_BADGE_ROW_GAP = 2


def _pack_badges(items: list[tuple[Flowable, float]], max_width: float) -> list[Table]:
    """Empile des pastilles de badge de toute nature (sort/fréquence/
    condition/mot-clé) sur autant de lignes que nécessaire, plusieurs
    pastilles par ligne quand leur largeur cumulée tient dans `max_width` —
    remplace l'ancien traitement à deux vitesses (fréquence/condition
    empilées une par ligne dans la colonne de droite, mots-clés sur une
    ligne séparée pleine largeur en dessous) par une seule grille commune,
    pour que par ex. « MA PHASE » (condition) et « TRAITS DE BATAILLE »
    (mot-clé/origine) puissent partager la même ligne au lieu de toujours
    s'empiler chacune sur la sienne. Chaque pastille va dans la première
    ligne où elle tient encore (et non seulement la dernière) : une pastille
    courte comme SIMPLE remonte dans un trou plutôt que d'ouvrir une ligne de
    plus (demande de l'utilisateur)."""
    rows: list[list[tuple[Flowable, float]]] = []
    row_widths: list[float] = []
    for fl, w in items:
        for i, used in enumerate(row_widths):
            if used + _PILL_GAP + w <= max_width:
                rows[i].append((fl, w))
                row_widths[i] += _PILL_GAP + w
                break
        else:
            rows.append([(fl, w)])
            row_widths.append(w)
    packed = [row for row in (_pill_row(r) for r in rows) if row is not None]
    for row in packed[1:]:
        row.spaceBefore = _BADGE_ROW_GAP
    return packed


def _pill_row(pills: list[tuple[Flowable, float]]) -> Table | None:
    """Plusieurs pastilles côte à côte (mots-clés d'aptitude, fréquence...) —
    une ligne à N colonnes, chacune taillée sur son contenu."""
    if not pills:
        return None
    # `colWidths` doit être donné explicitement (largeur déjà connue de
    # chaque pastille, cf. `_pill_natural_width`/`_CastBadge.size`) plutôt que
    # laissé à `None` ("auto") : reportlab ne sait calculer une largeur de
    # colonne "auto" qu'en interrogeant `Flowable._fixedWidth` de son contenu,
    # qui vaut 0 par défaut pour *toute* pastille (ce sont elles-mêmes des
    # `Table`/`Flowable` imbriquées) — jugée "non calculable rapidement",
    # reportlab bascule alors sur `_calcPreliminaryWidths`, qui étire la
    # colonne pour occuper toute la largeur disponible au lieu de la tailler
    # sur son contenu. Conséquence concrète : une fois cette ligne replacée
    # dans la cellule `cond_col` de `_ability_row_flowables`, sa largeur
    # mesurée valait `cond_col` pour *toutes* les lignes quel que soit leur
    # contenu réel, rendant l'alignement à droite (`ALIGN "RIGHT"` sur cette
    # cellule) indiscernable d'un alignement à gauche — repéré en comparant
    # les rects mesurés de plusieurs pastilles empilées (bords gauches
    # identiques, jamais les bords droits). Des `colWidths` explicites
    # évitent ce chemin de code entièrement.
    widths = [w + (_PILL_GAP if i < len(pills) - 1 else 0) for i, (_, w) in enumerate(pills)]
    t = Table([[fl for fl, _ in pills]], colWidths=widths)
    t.setStyle(TableStyle([
        # le petit espace entre 2 pastilles voisines est réservé dans `widths`
        # ci-dessus (colonnes 0..avant-dernière) puis rendu visible ici via
        # RIGHTPADDING sur ces mêmes colonnes — jamais sur la dernière, dont
        # le bord droit doit rester exactement au bord de la ligne (repère de
        # l'alignement à droite de `_ability_row_flowables`).
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-2, -1), _PILL_GAP),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "LEFT"),
    ]))
    return t


#: silhouettes de `_CastBadge` réellement dessinées depuis le dernier
#: `reset_drawn_badge_shapes` — la légende des pictos de la couverture
#: (`pdf_builder._build_cover_pdf`) n'explique que celles-là. Relevé au
#: dessin (`draw`) et non à la construction : les cartes de warscroll/
#: l'annexe sont construites tard, au moment de leur propre rendu PDF.
_DRAWN_BADGE_SHAPES: set[str] = set()


def reset_drawn_badge_shapes() -> None:
    _DRAWN_BADGE_SHAPES.clear()


def drawn_badge_shapes() -> frozenset[str]:
    return frozenset(_DRAWN_BADGE_SHAPES)


#: couleurs de fond des pastilles (`_pill`) construites depuis le dernier
#: `reset_drawn_pills` — la légende des pastilles de la couverture
#: (`pill_legend`) n'explique que les familles réellement présentes. Relevé
#: à la construction (les pastilles sont des `Table`, sans `draw` propre) :
#: à remettre à zéro avant de construire la moindre carte.
_DRAWN_PILL_COLORS: set[str] = set()


def reset_drawn_pills() -> None:
    _DRAWN_PILL_COLORS.clear()


#: une ligne de légende par famille de pastilles : (couleurs qui la
#: déclenchent, pastilles d'exemple (texte, fond, texte, contour),
#: explication). Ordre : source, propriétés, timing, mots-clés.
_PILL_LEGEND: list[tuple[frozenset[str], list[tuple[str, str, str, bool]], str]] = [
    (frozenset({_BADGE_SOURCE}), [("MDG", _BADGE_SOURCE, "#eef0f3", False)],
     "Source du texte : MDG (Manuel du Général), BT (battletome), FP (faction pack), AQSHY, WAHAPEDIA "
     "(anglais). Traits de Bataille, Formation : catégorie de règles d'armée."),
    (frozenset({_BADGE_SOURCE}), [("SIMPLE", _BADGE_SOURCE, "#eef0f3", False)],
     "Texte adapté, pas le verbatim : en cas de litige, revenir à la règle d'origine."),
    (frozenset({"#141414", _BADGE_SEASON}), [("BASE", "#141414", "#f2ecdb", False),
                                            ("SAISON", _BADGE_SEASON, "#fff1ea", False)],
     "Aptitude de base du jeu (Core) ; règle de la saison en cours (MdG 2026-27)."),
    (frozenset({_BADGE_NEUTRAL}), [("×1 / TOUR (ARMÉE)", _BADGE_NEUTRAL, "#eaf1f8", True),
                                   ("PASSIF", _BADGE_NEUTRAL, "#eaf1f8", True)],
     "Fréquence — (ARMÉE) : une seule fois pour toute l'armée ; passif : toujours actif, rien à déclarer."),
    (frozenset({_BADGE_REACT}), [("RÉACTION", _BADGE_REACT, "#fbeaec", False)],
     "Réaction : utilisée en réponse à l'aptitude indiquée."),
    (frozenset(_PHASE_COLORS[k][0] for k in ("move", "shoot", "charge", "melee")),
     [("TIR", *_PHASE_COLORS["shoot"], False), ("CHARGE", *_PHASE_COLORS["charge"], False)],
     "Mot-clé d'aptitude, à la couleur de sa phase (Mouvement, Tir, Charge, Corps à Corps)."),
    (frozenset({_BADGE_MULTI_PHASE}), [("ATTAQUE", _BADGE_MULTI_PHASE, "#eef0f3", True),
                                       ("SACCAGE", _BADGE_MULTI_PHASE, "#eef0f3", True)],
     "Mot-clé d'aptitude valable dans plusieurs phases."),
    (frozenset({_BADGE_SPELL, _BADGE_PRAYER}), [("SORT", _BADGE_SPELL, "#f3eefb", False),
                                                ("PRIÈRE", _BADGE_PRAYER, "#eaf5ef", False)],
     "Magie (sort, manifestation, bannissement…) ; prière. Illimité : utilisable plusieurs fois par tour."),
    (frozenset({_BADGE_WARSCROLL}), [("NOM D'UNITÉ", _BADGE_WARSCROLL, "#f2ecdb", False)],
     "Unité qui porte l'aptitude (pour un sort signature : son lanceur)."),
    (frozenset({_BADGE_KEYWORD, _BADGE_FACTION}), [("TACTIQUE", _BADGE_KEYWORD, "#f2eeea", False),
                                                   ("MOT-CLÉ", _BADGE_FACTION, "#f7e6ee", False)],
     "Autre mot-clé d'aptitude (Tactique : règle spéciale d'une carte de tactique) ; bordeaux : propre à la faction."),
]


def pill_legend() -> list[tuple[Flowable, float, str]]:
    """(rangée de pastilles d'exemple, sa largeur, explication) pour chaque
    famille de `_PILL_LEGEND` dont une pastille a été construite depuis
    `reset_drawn_pills`."""
    drawn = set(_DRAWN_PILL_COLORS)
    out = []
    for colors_, samples, text in _PILL_LEGEND:
        if not drawn & {c.lower() for c in colors_}:
            continue
        pills = [
            (_pill(tr(t), bg, fg, outline=outline) if outline else _pill(tr(t), bg, fg), _pill_natural_width(tr(t)))
            for t, bg, fg, outline in samples
        ]
        width = sum(w for _p, w in pills) + _PILL_GAP * len(pills)
        out.append((_pill_row(pills), width, tr(text)))
    return out


class _CastBadge(Flowable):
    """Badge géométrique (cercle/losange/hexagone/goutte), valeur inscrite au
    centre — reprend le code visuel de l'éditeur BattleScribe/Warhammer Age
    of Sigmar: The App pour un coût de Sort/Prière/Point de Commandement/
    Dime de Sang (une forme par type, cf. `_CAST_BADGE_SHAPES`), plutôt que
    la pastille rectangulaire générique de `_pill` utilisée ici avant —
    celle-ci ne distinguait ces types que par leur couleur et un préfixe
    textuel ("SORT 5+"), quand l'original les distingue d'abord par leur
    silhouette. `_cast_pill` retombe sur `_pill` (silhouette rectangulaire)
    quand l'aptitude ne porte aucune valeur numérique à inscrire au centre —
    un simple sigle ("PC") n'a pas sa place dans une forme aussi petite."""

    def __init__(self, shape: str, text: str, bg_hex: str, fg_hex: str, size: float = 14):
        super().__init__()
        self.shape = shape
        self.text = text
        self.bg = colors.HexColor(bg_hex)
        self.fg = colors.HexColor(fg_hex)
        self.size = size
        self.spaceBefore = 2  # même respiration que le `TOPPADDING` des pastilles voisines dans la pile

    def wrap(self, availWidth, availHeight):
        return (self.size, self.size)

    def _path(self, cx: float, cy: float, r: float):
        p = self.canv.beginPath()
        if self.shape == "circle":
            p.circle(cx, cy, r)
        elif self.shape == "diamond":
            p.moveTo(cx, cy + r)
            p.lineTo(cx + r, cy)
            p.lineTo(cx, cy - r)
            p.lineTo(cx - r, cy)
            p.close()
        elif self.shape == "die":  # dé de rage : carré aux coins arrondis
            side = r * 1.7
            p.roundRect(cx - side / 2, cy - side / 2, side, side, side * 0.22)
        elif self.shape == "flame":  # point de fureur : flamme, pointe en haut
            body_r = r * 0.72
            body_cy = cy - r + body_r
            k = 0.5523 * body_r
            p.moveTo(cx + r * 0.1, cy + r)
            p.curveTo(cx + body_r * 0.2, cy + r * 0.55, cx + body_r * 1.05, cy + r * 0.25, cx + body_r, body_cy)
            p.curveTo(cx + body_r, body_cy - k, cx + k, body_cy - body_r, cx, body_cy - body_r)
            p.curveTo(cx - k, body_cy - body_r, cx - body_r, body_cy - k, cx - body_r, body_cy)
            p.curveTo(cx - body_r, cy + r * 0.2, cx - body_r * 0.55, cy + r * 0.45, cx - body_r * 0.35, cy + r * 0.7)
            p.curveTo(cx - body_r * 0.2, cy + r * 0.35, cx + r * 0.05, cy + r * 0.6, cx + r * 0.1, cy + r)
            p.close()
        elif self.shape == "drop":  # goutte de sang, pointe en haut : la Dime de Sang
            body_r = r * 0.68
            body_cy = cy - r + body_r
            k = 0.5523 * body_r  # approximation de Bézier d'un quart de cercle
            p.moveTo(cx, cy + r)
            p.curveTo(cx + body_r * 0.35, cy + r * 0.45, cx + body_r, body_cy + k, cx + body_r, body_cy)
            p.curveTo(cx + body_r, body_cy - k, cx + k, body_cy - body_r, cx, body_cy - body_r)
            p.curveTo(cx - k, body_cy - body_r, cx - body_r, body_cy - k, cx - body_r, body_cy)
            p.curveTo(cx - body_r, body_cy + k, cx - body_r * 0.35, cy + r * 0.45, cx, cy + r)
            p.close()
        else:  # hexagone à sommet plat (2 côtés horizontaux) — le jeton PC de l'éditeur
            for i in range(6):
                angle = math.radians(60 * i)
                x, y = cx + r * math.cos(angle), cy + r * math.sin(angle)
                (p.moveTo if i == 0 else p.lineTo)(x, y)
            p.close()
        return p

    def draw(self):
        _DRAWN_BADGE_SHAPES.add(self.shape)
        c = self.canv
        cx = cy = self.size / 2.0
        r = self.size / 2.0 - 0.4  # laisse la place au liseré sans le faire déborder du cadre alloué
        c.setFillColor(self.bg)
        c.setStrokeColor(_STEEL_LINE)
        c.setLineWidth(0.6)
        c.drawPath(self._path(cx, cy, r), fill=1, stroke=1)
        c.setFillColor(self.fg)
        if self.shape == "die":  # 2 points en coins opposés : se lit comme un dé
            off = r * 0.66
            for dx, dy in ((-off, off), (off, -off)):
                c.circle(cx + dx, cy + dy, 0.75, stroke=0, fill=1)
        # « 1-3 » dans un dé : police réduite, pour ne pas toucher ses points
        c.setFont("Helvetica-Bold", 6 if len(self.text) >= 3 else 7.2)
        # dans la goutte, la valeur se centre sur son corps rond, plus bas que
        # le centre du cadre
        text_y = cy - 2.6 - (r * 0.32 if self.shape in ("drop", "flame") else 0)
        c.drawCentredString(cx, text_y, self.text)


#: légende de chaque silhouette de `_CastBadge` (couverture du roster, cf.
#: `cast_badge_legend`), dans l'ordre de `_CAST_BADGE_SHAPES`, avec la
#: valeur d'exemple inscrite dans le picto.
_CAST_BADGE_LEGEND = {
    "Spell": ("7+", "Aptitude : valeur de lancement. Warscroll : niveau de Sorcier ; manifestation : valeur de lancement de sa convocation."),
    "Prayer": ("4+", "Aptitude : valeur de récitation. Warscroll : niveau de Prêtre."),
    "Command": ("1", "Ordre : coût en points d’ordre"),
    "Blood tithe": ("2", "Dîme de sang : coût en points de dîme de sang"),
    "Rage": ("+2", "Dés de rage : « +N » gagnés, sinon nombre dépensé"),
    "Fury": ("+2", "Niveau de fureur : « +N » augmenté, sinon diminué"),
}


def cast_badge_legend(shapes: frozenset[str]) -> list[tuple[Flowable, str]]:
    """(picto d'exemple, explication) pour chaque silhouette de `shapes`."""
    return [
        (_CastBadge(shape, _CAST_BADGE_LEGEND[kind][0], _CAST_BADGE_COLORS[kind], _CAST_BADGE_FG[kind]),
         tr(_CAST_BADGE_LEGEND[kind][1]))
        for kind, shape in _CAST_BADGE_SHAPES.items() if shape in shapes
    ]


#: taille du badge Sorcier/Prêtre en en-tête — plus grand que le badge de
#: coût d'une aptitude (`_CastBadge` par défaut, 14pt) : il n'est plus
#: accolé à un texte de règle qui porte lui-même l'info, il doit se
#: distinguer tout seul près du nom de l'unité, comme sur l'éditeur
#: BattleScribe/l'App.
_CASTER_BADGE_SIZE = 16


def _caster_badges(keywords: list[str]) -> list[_CastBadge]:
    """Badges géométriques Sorcier/Prêtre (même silhouette que `_CastBadge`,
    cercle violet pour un sort/un sorcier, losange vert pour une prière/un
    prêtre) construits à partir des mots-clés `WIZARD (N)`/`PRIEST (N)` du
    warscroll — le niveau de magie/de prière de l'unité, reconstitué par
    `WahapediaLookup.find_warscroll` à partir de la colonne `parameter` de
    Warscrolls_keywords.csv. Affichés dans l'en-tête de carte plutôt que dans
    la liste de mots-clés en bas (cf. `_visible_keywords`) : un joueur
    cherche ce niveau au même endroit que sur l'éditeur BattleScribe/l'App,
    près du nom de l'unité, pas noyé dans une liste de mots-clés."""
    badges = []
    for kw in keywords:
        m = _CASTER_KW_RE.match(kw.strip())
        if not m:
            continue
        kind, level = m.group(1).upper(), m.group(2)
        if kind == "WIZARD":
            badges.append(_CastBadge("circle", level, _BADGE_SPELL, _CAST_BADGE_FG["Spell"], size=_CASTER_BADGE_SIZE))
        else:
            badges.append(_CastBadge("diamond", level, _BADGE_PRAYER, _CAST_BADGE_FG["Prayer"], size=_CASTER_BADGE_SIZE))
    return badges


def _visible_keywords(keywords: list[str]) -> list[str]:
    """`keywords` moins `WIZARD (N)`/`PRIEST (N)` — ceux-ci rejoignent le
    badge d'en-tête (`_caster_badges`) plutôt que la liste de mots-clés en
    bas de carte, pour ne pas doublonner l'information."""
    return [kw for kw in keywords if not _CASTER_KW_RE.match(kw.strip())]


def _caster_badge_row(badges: list[_CastBadge]) -> tuple[Table, float]:
    """Aligne 1+ badges Sorcier/Prêtre côte à côte (une unité peut, en
    théorie, être à la fois Sorcier et Prêtre) avec un petit espace entre eux
    — même schéma `(flowable, largeur occupée)` que le reste du fichier
    utilise pour composer des lignes de badges (cf. `_pack_badges`)."""
    gap = 3
    cells: list = []
    col_widths: list[float] = []
    for i, b in enumerate(badges):
        if i:
            cells.append(Spacer(gap, 0))
            col_widths.append(gap)
        cells.append(b)
        col_widths.append(b.size)
    t = Table([cells], colWidths=col_widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t, sum(col_widths)


class _PhaseRail(Flowable):
    """Bandeau de phase vertical, texte pivoté — le rendu que la maquette
    HTML utilisait et que la première passe avait abandonné (bandeau
    horizontal) faute d'un moyen simple de connaître, par avance, la
    hauteur qu'un `Flowable` occupera une fois posé. En réalité rien
    n'empêche de la calculer nous-même : le corps du groupe (les lignes
    d'aptitude) est construit et mesuré via son propre `.wrap()` *avant*
    d'instancier ce bandeau (cf. `_append_ability_groups`), avec cette
    hauteur déjà connue passée ici en dur plutôt que redemandée à
    `wrap()` — ce `Flowable` n'a donc plus qu'à dessiner un rectangle
    plein et un texte pivoté à 90° dans un espace dont la taille est fixée
    d'avance, ce que `canvas.rotate()` fait très bien."""

    def __init__(self, label: str, bg_hex: str, fg_hex: str, height: float, width: float = 5.2 * mm):
        super().__init__()
        self.label = label
        self.bg = colors.HexColor(bg_hex)
        self.fg = colors.HexColor(fg_hex)
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.saveState()
        c.setFillColor(self.fg)
        c.translate(self.width / 2.0, self.height / 2.0)
        c.rotate(90)
        c.setFont("Helvetica-Bold", 6.6)
        c.drawCentredString(0, -2.3, self.label)
        c.restoreState()


def _rail_label_min_height(label: str) -> float:
    """Largeur réelle (mesurée, pas devinée) de `label` à la police/taille du
    bandeau, plus une marge — un bandeau pivoté à 90° (`_PhaseRail`, gros
    bandeau de phase comme sous-bandeau de catégorie) a besoin d'au moins
    cette hauteur pour ne pas se faire couper."""
    return stringWidth(label, "Helvetica-Bold", 6.6) + 8


def _min_rail_height(phase_key: str) -> float:
    return _rail_label_min_height(tr(_PHASE_LABELS[phase_key]).upper())


_PLACEMENT_STYLE = ParagraphStyle("wc_placement", fontName="Helvetica", fontSize=7.5, leading=9.5)
_NOTE_STYLE = ParagraphStyle("wc_note", fontName="Helvetica-Oblique", fontSize=6.5, leading=8.5, textColor=_STEEL)


_RAIL_WIDTH = 5.2 * mm

#: sous-bandeau de catégorie (Aptitudes/Sorts/Prières/Manifestations, cf.
#: `_ability_group_body`) — même principe que `_PhaseRail`/`_RAIL_WIDTH` mais
#: plus étroit, pour se lire comme une subdivision du grand bandeau de phase
#: plutôt qu'un bandeau de même rang.
_CATEGORY_RAIL_WIDTH = 4.2 * mm

#: (fond, texte) de chaque sous-bandeau de catégorie — mêmes couleurs que
#: leurs pastilles (`_CATEGORY_COLORS`/`_CAST_BADGE_FG`) pour rester
#: reconnaissable d'un coup d'œil (le violet d'un sort, le vert d'une
#: prière...), avec un texte clair choisi pour le contraste plutôt que
#: réutilisé tel quel.
_CATEGORY_RAIL_COLORS: dict[str, tuple[str, str]] = {
    "normal": ("#6b6555", "#f5f2ea"),
    "spell": (_BADGE_SPELL, _CAST_BADGE_FG["Spell"]),
    "prayer": (_BADGE_PRAYER, _CAST_BADGE_FG["Prayer"]),
    "manifestation": (_BADGE_STAT, "#e8f5f7"),
    "delusion": (_BADGE_FACTION, "#f7e6ee"),
    "blood_tithe": (_BADGE_BLOOD, _CAST_BADGE_FG["Blood tithe"]),
    "khaine_blessing": (_BADGE_FACTION, "#f7e6ee"),
    "chaos_pledge": (_BADGE_FACTION, "#f7e6ee"),
}


#: Texte d'ambiance en tête de description : un bloc `<i>...</i>` suivi de
#: sauts de ligne puis du texte de règle (« Annonce : », « Effet : »,
#: « Utilisé par : »...) — forme de toutes les descriptions françaises
#: transcrites des battletomes (`faction_rules_fr.json`, ~1900 entrées,
#: vérifiées une à une) et des règles de saison. Wahapedia, lui, range
#: l'ambiance à part (`AbilityEntry.legend`, jamais rendu). Retiré au rendu,
#: tous modes confondus — les cartes ne portent que les règles (demande
#: explicite de l'utilisateur) ; le JSON garde le verbatim complet. Un
#: italique *dans* le texte de règle (ex. nom d'option « <i>Suprématie
#: Magique :</i> ») n'est jamais en tête, donc jamais touché.
_FLAVOR_PREFIX_RE = re.compile(r"^\s*<i>.*?</i>\s*(?:<br\s*/?>\s*)+", re.IGNORECASE | re.DOTALL)


def strip_flavor(description: str) -> str:
    stripped = _FLAVOR_PREFIX_RE.sub("", description or "", count=1)
    # garde-fou : un texte entièrement en italique n'est jamais vidé
    return stripped if stripped.strip() else description


def _break_long_name(name: str, width: float) -> str:
    """Un mot de titre plus large que la colonne de nom (« Porte-Étendard »)
    est coupé après un trait d'union plutôt qu'au milieu d'une syllabe
    (reportlab coupe sinon le mot n'importe où : « Porte-Étend / ard »)."""
    font, size = "Helvetica-Bold", _NAME_STYLE.fontSize
    words = []
    for word in name.split(" "):
        if "-" not in word or stringWidth(word, font, size) <= width:
            words.append(word)
            continue
        parts, line = word.split("-"), ""
        lines: list[str] = []
        for i, part in enumerate(parts):
            piece = part + ("-" if i < len(parts) - 1 else "")
            if line and stringWidth(line + piece, font, size) > width:
                lines.append(line)
                line = piece
            else:
                line += piece
        lines.append(line)
        words.append("<br/>".join(lines))
    return " ".join(words)


def _ability_row_flowables(ab: AbilityEntry, name_col: float, cond_col: float, first: bool) -> list[tuple[list, tuple]]:
    """Les 2 lignes d'une aptitude (nom+badges, texte), chacune comme
    `(cellules_de_ligne, style_supplémentaire_ou_None)` — `_ability_group_body`
    les assemble en lignes de la sous-table du groupe, en gardant le
    numérotage d'index à sa charge."""
    entries: list[tuple[list, tuple | None]] = []

    name_cell: list = [_safe_paragraph(f"<b>{_break_long_name(ab.name, name_col)}</b>", _NAME_STYLE)]

    # logo sort/prière/point de commandement, fréquence ("×1 / TOUR"),
    # condition (passif/qualificatif/réaction) et mots-clés (dont le badge
    # d'origine, cf. `tag_ability_origin`) rejoignent tous la même grille de
    # droite — une seule pastille par nature de badge n'existe pas : elles
    # sont toutes packées ensemble par `_pack_badges`, plusieurs par ligne
    # quand leur largeur le permet, plutôt que les badges "condition"
    # empilés un par ligne dans la colonne de droite et les mots-clés sur
    # une ligne séparée pleine largeur en dessous (deux traitements
    # différents qui ne s'alignaient jamais entre eux). Le logo avait
    # d'abord été mis à côté du nom (même traitement que la portée d'une
    # arme) mais, contrairement à un nom d'arme (toujours court), un nom
    # d'aptitude peut être long ("EXCOMMUNICATION!", "DERANGED
    # TRANSFORMATION") — sur une carte de règles à 2 colonnes
    # (`render_rule_card`), la colonne de nom rétrécie ne laissait alors
    # plus assez de place aux deux sur une ligne, et reportlab réenlignait
    # le badge en 2-3 lignes ("PRIÈRE 4+" -> "PRI"/"ÈRE"/"4+"). La colonne
    # de droite a une largeur fixe indépendante du nom, jamais ce conflit.
    badge_items: list[tuple[Flowable, float]] = _warscroll_pills(ab, cond_col)
    cast_pill = _cast_pill(ab, cond_col)
    if cast_pill is not None:
        badge_items.append(cast_pill)
    badge_items.extend(_resource_badges(ab))
    freq = _freq_pill(ab, cond_col)
    if freq is not None:
        badge_items.append(freq)
    cond_pill = _condition_pill(ab, cond_col)
    if cond_pill is not None:
        badge_items.append(cond_pill)
    badge_items.extend(_keyword_pills(ab))
    badge_cell: list = _pack_badges(badge_items, cond_col)
    # une seule colonne pour la table extérieure (cf. `_ability_group_body`)
    # : nom et badges de droite restent 2 colonnes côte à côte, mais
    # imbriqués dans une mini-table qui, elle, tient toute seule dans cette
    # cellule.
    name_cond = Table([[name_cell, badge_cell if badge_cell else ""]], colWidths=[name_col, cond_col])
    name_cond.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    entries.append(([name_cond], "top" if first else "top-rule"))

    text = _clean_text(strip_flavor(_bold_set_up(ab.description) if _BOLD_SET_UP else ab.description))
    if _SECTIONED:
        # pas de ligne vide avant « Effet : »/« Utilisée par : » : le
        # libellé en gras sépare déjà les parties (cartes plus compactes)
        text = _BLANK_BEFORE_LABEL_RE.sub("<br/>", text)
    trigger = _reaction_trigger(ab) if _SECTIONED else None
    if trigger:
        # mode sectionné : le déclencheur de réaction en 1re ligne du texte,
        # pleine largeur, plutôt qu'une pastille haute et étroite à droite
        # (demande de l'utilisateur, cartes plus compactes).
        text = f'<font color="{_BADGE_REACT}"><b>{tr("Réaction :")}</b> {trigger}</font><br/>{text}'
    entries.append(([_ability_text_flowable(text, name_col + cond_col)], "text"))
    return entries


_BLANK_BEFORE_LABEL_RE = re.compile(r"<br/>\s*<br/>\s*(?=<b>[^<]{1,80}?\s*:\s*</b>)")

#: début d'une section titrée dans un texte d'aptitude (« <b>Effet :</b> »,
#: « <b>Varinor, la Rune de Force :</b> »), en début de ligne.
_TEXT_SECTION_SPLIT_RE = re.compile(r"(?:<br/>\s*)+(?=<b>[^<]{1,80}?\s*:\s*</b>)")
#: à partir de combien de sections titrées un texte est découpé (cf.
#: `_ability_text_flowable`) — une aptitude ordinaire n'en a que 2
#: (Annonce/Effet), qui restent un seul paragraphe.
_MIN_TEXT_SECTIONS = 3
#: section d'étape numérotée (« <b>1 :</b> ») : dès 2 étapes, le texte est
#: découpé lui aussi (ex. « Début de Round de Bataille »).
_STEP_SECTION_RE = re.compile(r"^\s*<b>\d+\s*:\s*</b>")
_SECTION_RULE = colors.HexColor("#e2d9bf")


def _ability_text_flowable(text: str, width: float, min_sections: int = _MIN_TEXT_SECTIONS) -> Flowable:
    """Texte d'une aptitude (déjà passé par `_clean_text`). Un gros texte à
    plusieurs sections titrées (`_MIN_TEXT_SECTIONS`+, ex. « Inscription de
    Rune » : l'effet puis une section par rune) est rendu section par section,
    séparées par un filet fin, pour la lisibilité (demande de l'utilisateur,
    tous modes) ; de même pour 2+ étapes numérotées (`_STEP_SECTION_RE`) ;
    sinon un seul paragraphe."""
    sections = [sec for sec in _TEXT_SECTION_SPLIT_RE.split(text) if sec.strip()]
    steps = len(sections) >= 2 and all(_STEP_SECTION_RE.match(sec) for sec in sections)
    if len(sections) < min_sections and not steps:
        return _safe_paragraph(text, _TEXT_STYLE)
    t = Table([[_safe_paragraph(sec, _TEXT_STYLE)] for sec in sections], colWidths=[width])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, 0), 0), ("BOTTOMPADDING", (0, -1), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _SECTION_RULE),
    ]))
    return t


def _ability_rows_body(abilities: list[AbilityEntry], width: float) -> Table:
    """Empile les lignes (nom+badges, texte) de chaque aptitude de
    `abilities`, sans aucun repère de catégorie — le corps brut qu'utilise
    directement `_ability_group_body` pour un groupe à une seule catégorie
    (l'écrasante majorité des cartes), et que cette même fonction réutilise
    une fois par grappe de catégorie pour un groupe qui en mélange plusieurs
    (cf. `_ability_group_body`)."""
    # les cellules de cette table portent 8pt de marge de chaque côté (style
    # ci-dessous) : le contenu de chaque ligne — notamment la mini-table
    # nom+condition, dont la largeur est fixée d'avance — doit se caler sur
    # `width` *moins* cette marge, sans quoi elle déborde du cadre de la
    # carte (elle-même dimensionnée exactement à `width`).
    content_width = width - 16
    name_col = content_width * 0.56
    cond_col = content_width - name_col
    rows: list[list] = []
    styles: list[tuple] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, ab in enumerate(abilities):
        for cells, kind in _ability_row_flowables(ab, name_col, cond_col, first=(i == 0)):
            rows.append(cells)
            r = len(rows) - 1
            # mode sectionné : marges resserrées, pour qu'un bandeau de phase
            # tienne plus souvent sur une page (demande de l'utilisateur)
            top_pad, text_bottom_pad = (3, 3) if _SECTIONED else (5, 6)
            if kind == "top" or kind == "top-rule":
                styles += [("TOPPADDING", (0, r), (-1, r), top_pad), ("BOTTOMPADDING", (0, r), (-1, r), 1)]
                if kind == "top-rule":
                    styles.append(("LINEABOVE", (0, r), (-1, r), 0.4, _STEEL_LINE))
            else:  # text
                styles += [("TOPPADDING", (0, r), (-1, r), 2), ("BOTTOMPADDING", (0, r), (-1, r), text_bottom_pad)]
    body = Table(rows, colWidths=[width])
    # une seule colonne pour la table extérieure : la 1re ligne (nom+condition)
    # a en réalité 2 "colonnes" logiques (nom, condition) mais elles sont déjà
    # fusionnées dans une cellule de liste + un flowable pilule, donc `rows`
    # reste à 1 colonne partout — SPAN inutile.
    body.setStyle(TableStyle(styles))
    return body


def _category_cluster_row(category: str, abilities: list[AbilityEntry], width: float) -> Table:
    """Une grappe d'aptitudes de même catégorie, accolée à son propre
    sous-bandeau vertical (même principe que `_PhaseRail`, mais plus étroit
    et coloré par catégorie plutôt que par phase) — remplace l'ancien
    intitulé de catégorie posé en ligne au-dessus de la grappe (« APTITUDES »/
    « SORTS »/« PRIÈRES » en petit texte), qui ne se lisait pas comme
    appartenant au même bloc que le nom+les badges de la 1re aptitude."""
    body_width = width - _CATEGORY_RAIL_WIDTH
    body = _ability_rows_body(abilities, body_width)
    _, body_height = body.wrap(body_width, 0xFFFF)
    rail_height = max(body_height, _rail_label_min_height(tr(_CATEGORY_LABELS_FR.get(category, category)).upper()))
    bg, fg = _CATEGORY_RAIL_COLORS.get(category, _CATEGORY_RAIL_COLORS["normal"])
    rail = _PhaseRail(tr(_CATEGORY_LABELS_FR.get(category, category)).upper(), bg, fg, rail_height, width=_CATEGORY_RAIL_WIDTH)
    row = Table([[rail, body]], colWidths=[_CATEGORY_RAIL_WIDTH, body_width])
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return row


def _category_clusters(group: list[AbilityEntry]) -> list[tuple[str, list[AbilityEntry]]]:
    """Découpe `group` en grappes consécutives de même catégorie (`(catégorie,
    aptitudes)`) — partagé par `_ability_group_body` (pour poser un
    sous-bandeau par grappe) et `_chunk_group` (pour ne jamais couper une
    grappe entre deux pages/tronçons, cf. `_chunk_group`). `group` est supposé
    déjà trié par catégorie (cf. `_append_ability_groups`), jamais réordonné
    ici."""
    clusters: list[tuple[str, list[AbilityEntry]]] = []
    for ab in group:
        category = _ability_category(ab)
        if clusters and clusters[-1][0] == category:
            clusters[-1][1].append(ab)
        else:
            clusters.append((category, [ab]))
    return clusters


def _ability_group_body(group: list[AbilityEntry], width: float, show_category_headers: bool = False) -> Table:
    """La sous-table d'un groupe de phase (tout sauf le bandeau de phase
    lui-même) — isolée dans sa propre `Table` pour pouvoir mesurer sa hauteur
    réelle avant de construire le bandeau vertical à sa gauche, cf.
    `_append_ability_groups`. `show_category_headers` (calculé une fois pour
    tout le groupe de phase, avant tronçonnage/mise en colonnes, cf.
    `_append_ability_groups`) découpe le groupe en grappes consécutives de
    même catégorie (`_category_clusters`), chacune accolée à son propre
    sous-bandeau (cf. `_category_cluster_row`) — seulement utile quand le
    groupe mélange effectivement plusieurs catégories (ex. un sort et un
    trait de bataille tous deux en phase des héros)."""
    if not show_category_headers:
        return _ability_rows_body(group, width)
    clusters = _category_clusters(group)
    rows: list[list] = []
    styles: list[tuple] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, (category, abilities) in enumerate(clusters):
        rows.append([_category_cluster_row(category, abilities, width)])
        # pas de TOPPADDING ici : ce padding pousserait vers le bas la ligne
        # entière (sous-bandeau de catégorie inclus, pas seulement le texte),
        # ouvrant un blanc visible entre deux sous-bandeaux de couleurs
        # différentes (ex. le gris "APTITUDES" et le violet "SORTS") — ils
        # doivent au contraire se toucher, seul le `LINEABOVE` marque la
        # frontière entre grappes.
        if i > 0:
            styles.append(("LINEABOVE", (0, i), (-1, i), 0.4, _STEEL_LINE))
    body = Table(rows, colWidths=[width])
    body.setStyle(TableStyle(styles))
    return body


#: hauteur maximale d'un seul groupe de phase (bandeau + corps) — une seule
#: ligne de la table extérieure de la carte, donc une seule ligne du PDF
#: final : reportlab ne sait pas la couper à un saut de page. Un groupe
#: normal (une carte d'unité, une seule catégorie de règle) ne l'atteint
#: jamais ; seule une carte de règles *fusionnées* (plusieurs catégories
#: réunies dans la même phase, cf. `pdf_builder.resolve_rules`) le peut —
#: `_chunk_group` le fractionne alors en plusieurs segments qui reprennent
#: chacun le même bandeau (couleur + nom de phase), l'un sous l'autre,
#: plutôt que de tenter une seule ligne trop grande pour tenir sur une page.
#: Marge sous la hauteur utile d'une page A4 portrait avec les marges de
#: `pdf_builder._build_rule_cards_pdf`/`_build_warscroll_cards_pdf` (~11mm).
_MAX_GROUP_HEIGHT = 240 * mm

#: hauteur utile d'une page A4 portrait avec les marges de
#: `pdf_builder._build_warscroll_cards_pdf` (~5.5mm de chaque côté), moins la
#: marge de sécurité empirique entre `A4[1] - 2*marge` et la hauteur de cadre
#: réellement disponible que reportlab rapporte dans une `LayoutError` (le
#: padding interne par défaut d'un `Frame`, ~6pt de chaque côté). Sert de
#: seuil pour `build_warscroll_cards_flow` : une carte pairée à demi-largeur
#: (`_UNIT_CARD_WIDTH`) dont une aptitude est exceptionnellement longue (ex.
#: Skaven's Lord Skreech Verminking, "Le Rat aux Treize Têtes") peut dépasser
#: une page entière et faire échouer tout le PDF avec un
#: `reportlab.platypus.doctemplate.LayoutError` — jamais le cas en dessous de
#: ce seuil.
_MAX_CARD_HEIGHT = A4[1] - 2 * (5.5 * mm) - 20


def _chunk_group(
    group: list[AbilityEntry], body_width: float, show_category_headers: bool = False, n_cols: int = 1,
    max_height: float = _MAX_GROUP_HEIGHT,
) -> list[list[AbilityEntry]]:
    """Découpe `group` en tronçons dont le corps assemblé (cf.
    `_ability_group_body`) tient sous `max_height` (`_MAX_GROUP_HEIGHT` par
    défaut, cf. `_choice_segments` pour l'exception) — jamais une
    aptitude coupée en deux, seulement la frontière entre deux aptitudes
    consécutives. Une aptitude seule plus haute que la limite (texte de
    règle exceptionnellement long) reste seule dans son propre tronçon,
    trop grande malgré tout plutôt que tronquée. `show_category_headers` doit
    être le même que celui passé au rendu final (cf. `_append_ability_groups`)
    pour que la hauteur mesurée ici — qui doit rester un majorant sûr sous
    `_MAX_GROUP_HEIGHT` — ne sous-estime pas les intitulés de catégorie
    effectivement rendus.

    Quand `show_category_headers` est vrai, la coupe se fait au niveau de la
    grappe de catégorie (`_category_clusters`), pas de l'aptitude individuelle
    — une grappe (ex. les 3 aptitudes "Sorts" d'un même bandeau de phase) ne
    peut donc jamais se retrouver scindée en deux tronçons. Sans cette
    contrainte, une coupe pouvait tomber entre deux aptitudes de la *même*
    catégorie : chaque tronçon obtenait alors son propre sous-bandeau
    (`_category_cluster_row`), correctement dimensionné sur sa portion
    tronquée mais donc plus court que la grappe complète visible une fois les
    deux tronçons empilés sans saut de page entre eux (symptôme : le
    sous-bandeau "Sorts" ne couvrant pas toute la hauteur de ses 3 aptitudes)
    — et, si les deux tronçons tombaient de part et d'autre d'un saut de page,
    la grappe se retrouvait visuellement coupée en plein milieu. Une grappe
    entière plus haute que la limite (cas extrême, jamais vu en pratique tant
    les grappes restent petites) reste malgré tout seule dans son propre
    tronçon, comme une aptitude isolée trop longue — pas de repli plus fin sur
    un découpage par aptitude à l'intérieur de la grappe.

    La hauteur est mesurée sur le rendu réel à `n_cols` colonnes
    (`_ability_group_body_columns`), pas sur 1 colonne : une colonne plus
    étroite allonge chaque aptitude, et le partage par aptitude entière entre
    colonnes n'est jamais parfaitement équilibré — mesurer à 1 colonne n'est
    donc *pas* un majorant sûr. Les grosses phases du mode `fr-split` (règles
    + aptitudes de tous les warscrolls réunies) dépassaient ainsi une page
    (`LayoutError`)."""
    def height(abilities: list[AbilityEntry]) -> float:
        return _ability_group_body_columns(abilities, body_width, n_cols, show_category_headers).wrap(body_width, 0xFFFF)[1]

    if show_category_headers:
        # une grappe plus haute qu'une page à elle seule (jamais vu avant le
        # mode `fr-split`, où la grappe « Aptitudes » de la phase des héros
        # réunit celles de tous les warscrolls) est découpée par aptitude
        # malgré tout : un sous-bandeau scindé vaut mieux qu'une `LayoutError`.
        units = []
        for _category, abilities in _category_clusters(group):
            units.extend([[ab] for ab in abilities] if height(abilities) > max_height else [abilities])
    else:
        units = [[ab] for ab in group]
    chunks: list[list[AbilityEntry]] = []
    current: list[AbilityEntry] = []
    for unit in units:
        candidate = current + unit
        if height(candidate) > max_height and current:
            chunks.append(current)
            current = list(unit)
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


#: Espace entre les deux colonnes d'un groupe de phase sur la carte de règles
#: combinée (cf. `_ability_group_body_columns`) — assez pour rester lisible
#: comme un vrai intervalle plutôt qu'un simple accolement des cadres.
_COLUMN_GAP = 4 * mm


def _split_group_columns(group: list[AbilityEntry], col_width: float, n_cols: int) -> list[list[AbilityEntry]]:
    """Répartit `group` (dans l'ordre, jamais réordonné) en `n_cols` colonnes
    équilibrées par hauteur rendue à `col_width` — pas par nombre
    d'aptitudes, une aptitude au texte long ne doit pas peser autant qu'une
    courte. Choisit, pour chaque frontière entre 2 colonnes, l'index qui
    rapproche le plus la hauteur cumulée de sa part du total (`i/n_cols`) —
    pas un seuil glouton "colonne courante pleine, passe à la suivante" :
    celui-ci pouvait faire déborder toutes les aptitudes dans la première
    colonne dès que la dernière pesait à elle seule plus que la moitié du
    total (ex. 2 aptitudes, la 2e nettement plus longue que la 1re : la
    hauteur cumulée après la 1re restait sous la cible, donc la 2e
    rejoignait quand même la colonne 1 au lieu de basculer en colonne 2).
    Jamais plus de colonnes que d'aptitudes ; un groupe à une seule aptitude
    reste seul en colonne 1, les suivantes vides."""
    columns: list[list[AbilityEntry]] = [[] for _ in range(n_cols)]
    if not group:
        return columns
    # jamais plus de colonnes "actives" que d'aptitudes — les colonnes en
    # trop restent vides (`columns` garde `n_cols` éléments, la forme que
    # `_ability_group_body_columns` attend pour zipper avec `col_widths`).
    active_cols = max(1, min(n_cols, len(group)))
    if active_cols <= 1:
        columns[0] = list(group)
        return columns
    # mesurée sans intitulé de catégorie (même si le groupe en affichera) :
    # cette hauteur ne sert qu'à équilibrer les colonnes par proportion, pas
    # de garde-fou à respecter au pt près comme `_chunk_group` — l'écart
    # (quelques pt par frontière de catégorie, répartis sur tout le groupe)
    # est négligeable pour cet usage.
    heights = [_ability_group_body([ab], col_width).wrap(col_width, 0xFFFF)[1] for ab in group]
    cumulative = [0.0]
    for h in heights:
        cumulative.append(cumulative[-1] + h)
    total = cumulative[-1]
    n = len(group)
    boundaries = [0]
    for i in range(1, active_cols):
        target = total * i / active_cols
        lo = boundaries[-1] + 1  # au moins 1 aptitude dans la colonne précédente
        hi = n - (active_cols - i)  # au moins 1 aptitude par colonne restante
        best_idx = min(range(lo, hi + 1), key=lambda idx: abs(cumulative[idx] - target))
        boundaries.append(best_idx)
    boundaries.append(n)
    for i in range(active_cols):
        columns[i] = group[boundaries[i]:boundaries[i + 1]]
    return columns


def _ability_text_chunks(text: str) -> list[str]:
    """Découpe `text` (déjà passé par `_clean_text`) en blocs au niveau de ses
    `<br/>` de premier niveau — jamais à l'intérieur d'une liste `<ul>...
    </ul>` (profondeur suivie), pour ne jamais couper une balise en 2. Sert
    de points de coupe sûrs à `_split_long_ability_columns` pour répartir une
    aptitude trop longue sur plusieurs colonnes."""
    depth = 0
    chunks: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("<ul>", i):
            depth += 1
            buf.append("<ul>")
            i += 4
        elif text.startswith("</ul>", i):
            depth -= 1
            buf.append("</ul>")
            i += 5
        elif depth == 0 and text.startswith("<br/>", i):
            piece = "".join(buf).strip()
            if piece:
                chunks.append(piece)
            buf = []
            i += 5
        else:
            buf.append(text[i])
            i += 1
    tail = "".join(buf).strip()
    if tail:
        chunks.append(tail)
    return chunks


#: Au-delà de ce volume de texte (caractères de la description, une seule
#: aptitude), une aptitude seule dans son bandeau de phase bénéficie d'une
#: mise en page à colonnes dédiée (`_split_long_ability_columns`) plutôt que
#: de tomber en repli pleine-largeur (`_ability_group_body_columns`) —
#: demande explicite de l'utilisateur : une aptitude au texte long doit
#: rester à sa place chronologique normale (pas de section/page dédiée) mais
#: profiter des mêmes colonnes que le reste de la carte. Calibré sur
#: `data/json/faction_rules_fr.json` : l'aptitude la plus longue observée
#: (« Inscription de Rune », Lumineth Realm-lords, ~3470 caractères) le
#: dépasse largement, la suivante (« Éruption de Fureur », règle de saison
#: partagée par plusieurs factions, ~1281 caractères) reste confortablement
#: en-dessous.
_LONG_ABILITY_THRESHOLD = 2000


def _split_long_ability_columns(ab: AbilityEntry, body_width: float, n_cols: int) -> Table | None:
    """Répartit le corps d'une seule aptitude longue sur `n_cols` colonnes
    côte à côte — nom+badges en tête de la 1re colonne seulement, texte
    scindé au niveau de ses coupures `<br/>` de premier niveau
    (`_ability_text_chunks`), équilibré par hauteur rendue comme
    `_split_group_columns` mais entre morceaux d'une même aptitude plutôt
    qu'entre aptitudes voisines. `None` si le texte n'a pas assez de
    coupures de premier niveau pour remplir `n_cols` colonnes — l'appelant
    retombe alors sur le rendu pleine-largeur habituel plutôt que de risquer
    une colonne vide ou coupée au mauvais endroit."""
    text = _clean_text(strip_flavor(_bold_set_up(ab.description) if _BOLD_SET_UP else ab.description))
    sectioned = len([sec for sec in _TEXT_SECTION_SPLIT_RE.split(text) if sec.strip()]) >= _MIN_TEXT_SECTIONS
    chunks = _ability_text_chunks(text)
    if len(chunks) < n_cols:
        return None
    col_width = (body_width - _COLUMN_GAP * (n_cols - 1)) / n_cols
    content_width = col_width - 16
    heights = [_safe_paragraph(c, _TEXT_STYLE).wrap(content_width, 0xFFFF)[1] for c in chunks]
    cumulative = [0.0]
    for h in heights:
        cumulative.append(cumulative[-1] + h)
    total = cumulative[-1]
    n = len(chunks)
    boundaries = [0]
    for i in range(1, n_cols):
        target = total * i / n_cols
        lo = boundaries[-1] + 1
        hi = n - (n_cols - i)
        best_idx = min(range(lo, hi + 1), key=lambda idx: abs(cumulative[idx] - target))
        boundaries.append(best_idx)
    boundaries.append(n)

    name_col = content_width * 0.56
    cond_col = content_width - name_col
    header_cells, _kind = _ability_row_flowables(ab, name_col, cond_col, first=True)[0]

    cells: list = []
    col_widths: list[float] = []
    for i in range(n_cols):
        seg_text = "<br/><br/>".join(chunks[boundaries[i]:boundaries[i + 1]])
        seg_rows: list[list] = []
        seg_styles: list[tuple] = [
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if i == 0:
            seg_rows.append(header_cells)
            seg_styles += [("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 0), (-1, 0), 1)]
            text_row = 1
        else:
            text_row = 0
        # une colonne n'est qu'un morceau du texte : filets dès 2 sections
        # quand le texte entier est sectionné, pour rester homogène
        seg_rows.append([_ability_text_flowable(seg_text, col_width - 16, min_sections=2 if sectioned else _MIN_TEXT_SECTIONS)])
        seg_styles += [
            ("TOPPADDING", (0, text_row), (-1, text_row), 2 if i == 0 else 5),
            ("BOTTOMPADDING", (0, text_row), (-1, text_row), 6),
        ]
        seg_table = Table(seg_rows, colWidths=[col_width])
        seg_table.setStyle(TableStyle(seg_styles))
        cells.append(seg_table)
        col_widths.append(col_width)
        if i < n_cols - 1:
            cells.append(Spacer(_COLUMN_GAP, 0))
            col_widths.append(_COLUMN_GAP)
    t = Table([cells], colWidths=col_widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _ability_group_body_columns(
    chunk: list[AbilityEntry], body_width: float, n_cols: int, show_category_headers: bool = False,
) -> Table:
    """Comme `_ability_group_body`, mais réparti sur `n_cols` colonnes côte à
    côte plutôt qu'empilé dans une seule — la carte de règles fusionnée
    (`render_rule_card`) peut réunir jusqu'à une dizaine d'aptitudes dans le
    même bandeau de phase (ex. tous les Traits Héroïques d'une faction) ;
    les étaler sur 2 colonnes exploite la largeur, plus généreuse que celle
    d'une carte d'unité, au lieu d'une longue colonne unique. `n_cols=1`
    retombe exactement sur `_ability_group_body`. `show_category_headers` est
    propagé tel quel à chaque colonne plutôt que recalculé par colonne : une
    catégorie qui déborde d'une colonne à l'autre doit répéter son intitulé
    en haut de la colonne suivante, comme un en-tête de tableau qui se répète
    à chaque page/colonne, pour rester lisible sans remonter à la colonne
    précédente. Réduit d'abord `n_cols` au nombre d'aptitudes du tronçon
    (`_split_group_columns` ne remplit de toute façon jamais plus de colonnes
    « actives » que ça) : sans ça, un tronçon plus court que `n_cols` (ex. un
    unique trait de bataille, particulièrement long) restait confiné dans une
    seule colonne à *moitié* de `body_width`, la ou les colonnes voisines
    restant vides — un gâchis de largeur qui aggrave le texte long au lieu de
    l'aider. Une exception : une aptitude dont le texte dépasse
    `_LONG_ABILITY_THRESHOLD` n'entre jamais dans ce partage par aptitude
    entière (que ce tronçon en compte une seule ou plusieurs) — déléguée à
    `_ability_group_body_columns_mixed`, elle obtient sa propre bande pleine
    largeur répartie sur ses colonnes (`_split_long_ability_columns`,
    nom+badges dans la 1re colonne, texte réparti sur les suivantes) plutôt
    que de monopoliser toute une colonne face à une aptitude courte voisine
    qui, elle, n'a rien à gagner à être étalée."""
    if n_cols > 1 and any(_is_long_ability(ab) for ab in chunk):
        return _ability_group_body_columns_mixed(chunk, body_width, n_cols, show_category_headers)
    n_cols = max(1, min(n_cols, len(chunk))) if chunk else n_cols
    if n_cols <= 1:
        return _ability_group_body(chunk, body_width, show_category_headers)
    col_width = (body_width - _COLUMN_GAP * (n_cols - 1)) / n_cols
    columns = _split_group_columns(chunk, col_width, n_cols)
    cells: list = []
    col_widths: list[float] = []
    for i, col in enumerate(columns):
        cells.append(_ability_group_body(col, col_width, show_category_headers) if col else Spacer(col_width, 0))
        col_widths.append(col_width)
        if i < n_cols - 1:
            cells.append(Spacer(_COLUMN_GAP, 0))
            col_widths.append(_COLUMN_GAP)
    t = Table([cells], colWidths=col_widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _is_long_ability(ab: AbilityEntry) -> bool:
    return len(_clean_text(ab.description)) > _LONG_ABILITY_THRESHOLD


def _ability_group_body_columns_mixed(
    chunk: list[AbilityEntry], body_width: float, n_cols: int, show_category_headers: bool,
) -> Table:
    """Repli de `_ability_group_body_columns` pour un tronçon qui mélange au
    moins une aptitude longue (cf. `_LONG_ABILITY_THRESHOLD`) avec d'autres
    aptitudes — découpe `chunk` en tronçons consécutifs (une aptitude longue
    toujours seule dans le sien, plusieurs aptitudes courtes regroupées dans
    le leur), empilés dans l'ordre d'origine plutôt que réordonnés. Un
    tronçon "longue" est rendu par `_split_long_ability_columns` (ses
    propres colonnes) ; un tronçon "courtes" repasse par
    `_ability_group_body_columns` (jamais d'aptitude longue dedans, donc
    jamais de récursion vers cette fonction) pour garder le même partage par
    hauteur qu'un bandeau sans aptitude longue. Sans ce découpage,
    `_split_group_columns` traiterait la longue comme une aptitude entière
    parmi d'autres et lui donnerait une colonne entière pour elle seule, face
    à une aptitude courte livrée à elle-même dans l'autre — la longue reste
    cramponnée à la largeur d'une seule colonne au lieu de profiter des deux
    (demande explicite de l'utilisateur)."""
    runs: list[list[AbilityEntry]] = []
    for ab in chunk:
        if _is_long_ability(ab) or not runs or _is_long_ability(runs[-1][0]):
            runs.append([ab])
        else:
            runs[-1].append(ab)

    rows: list[list] = []
    styles: list[tuple] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    for i, run in enumerate(runs):
        if len(run) == 1 and _is_long_ability(run[0]):
            body = _split_long_ability_columns(run[0], body_width, n_cols)
            if body is None:
                body = _ability_group_body(run, body_width, show_category_headers)
        else:
            body = _ability_group_body_columns(run, body_width, n_cols, show_category_headers)
        rows.append([body])
        if i > 0:
            styles.append(("LINEABOVE", (0, i), (-1, i), 0.4, _STEEL_LINE))
    t = Table(rows, colWidths=[body_width])
    t.setStyle(TableStyle(styles))
    return t


#: hauteur maximale d'une sous-section de choix, plus généreuse que
#: `_MAX_GROUP_HEIGHT` (marge de sécurité commune à tous les bandeaux) : le
#: cadre réel d'une page de cartes fait ~273mm (A4 moins la marge haute de
#: `pdf_builder._PAGE_LABEL_MARGIN`, la marge basse et le padding du
#: `Frame`). Garder ~8mm de marge sous ce cadre évite la `LayoutError`.
#: Mesuré : la Dîme de Sang des Blades of Khorne fait ~246mm en
#: `fr-extended`, au-dessus des 240mm communs.
_MAX_CHOICE_HEIGHT = 265 * mm


def _choice_segments(group: list[AbilityEntry]) -> list[tuple[list[AbilityEntry], float]]:
    """Sépare une sous-section de choix (`CHOICE_CATEGORIES`, toujours en
    tête de son bandeau, cf. `_CATEGORY_ORDER`) du reste du bandeau, avec sa
    propre hauteur maximale (`_MAX_CHOICE_HEIGHT`) : demande de
    l'utilisateur, elle doit tenir sur une seule page. Seule dans son
    tronçon, elle part entière sur la page suivante plutôt que d'être
    coupée (cf. `_chunk_group`). Plus haute que ça malgré tout,
    `_chunk_group` la découpe, plutôt qu'une `LayoutError`. (3 colonnes au
    lieu de 2 a été essayé : plus haut, les pastilles s'empilent dans des
    colonnes trop étroites.)"""
    choice = [ab for ab in group if _ability_category(ab) in CHOICE_CATEGORIES]
    if not choice:
        return [(group, _MAX_GROUP_HEIGHT)]
    rest = [ab for ab in group if _ability_category(ab) not in CHOICE_CATEGORIES]
    return [(choice, _MAX_CHOICE_HEIGHT)] + ([(rest, _MAX_GROUP_HEIGHT)] if rest else [])


def _append_ability_groups(
    rows: list[list], styles: list[tuple], abilities: list[AbilityEntry], width: float, columns: int = 1,
    phase_order: list[str] | None = None,
) -> None:
    """Ajoute au corps de carte (unité ou règle) un groupe par bandeau de
    phase, dans l'ordre canonique du tour — partagé par `render_warscroll_card`
    et `render_rule_card` pour ne garder qu'une seule implémentation du
    tableau d'aptitudes. Bandeau vertical (`_PhaseRail`) à gauche du groupe,
    sa hauteur mesurée sur le corps du groupe avant de le construire.
    `columns` (>1 seulement pour `render_rule_card`, cf.
    `_ability_group_body_columns`) répartit chaque groupe de phase sur
    plusieurs colonnes côte à côte plutôt qu'une seule colonne empilée.

    Au sein d'un même bandeau de phase, les aptitudes sont triées par
    catégorie (`_CATEGORY_ORDER` : normales, sorts, prières, manifestations —
    tri stable, jamais réordonnées à l'intérieur d'une même catégorie) plutôt
    que laissées dans l'ordre de `abilities` — sans quoi, ex., un sort et un
    trait de bataille qui se déclenchent tous deux en phase des héros
    resteraient entremêlés dans cette phase plutôt que regroupés par type. Un
    intitulé de catégorie (cf. `_category_header`) n'est affiché que si la
    phase mélange effectivement plusieurs catégories — une carte d'unité sans
    sort/prière, l'écrasante majorité des cas, ne montre donc jamais
    "Aptitudes" en tête de sa phase des héros."""
    grouped: dict[str, list[AbilityEntry]] = {}
    for ab in abilities:
        grouped.setdefault(classify_phase(ab), []).append(ab)

    body_width = width - _RAIL_WIDTH
    first_phase_row: int | None = None
    for key in phase_order or _PHASE_ORDER:
        group = grouped.get(key)
        if not group:
            continue
        group = sorted(group, key=lambda ab: _CATEGORY_ORDER.index(_ability_category(ab)))
        categories = {_ability_category(ab) for ab in group}
        # une sous-section de choix (« Délires », « Dîme de Sang ») est
        # toujours titrée, même seule dans sa phase : c'est un regroupement
        # demandé en tant que tel.
        show_headers = len(categories) > 1 or bool(categories & CHOICE_CATEGORIES)
        bg, fg = _PHASE_COLORS[key]
        # le découpage page-safe (`_chunk_group`) est mesuré sur le même
        # nombre de colonnes que le rendu (cf. sa docstring).
        # une aptitude pleine largeur (`AbilityEntry.full_width`, ordre de
        # déroulé du Déploiement) : toute sa phase sur une seule colonne.
        n_cols = 1 if any(ab.full_width for ab in group) else columns
        chunks = [
            chunk
            for segment, max_height in _choice_segments(group)
            for chunk in _chunk_group(segment, body_width, show_headers, n_cols=n_cols, max_height=max_height)
        ]
        for chunk_i, chunk in enumerate(chunks):
            body = _ability_group_body_columns(chunk, body_width, n_cols, show_headers)
            _, body_height = body.wrap(body_width, 0xFFFF)
            # un groupe très court (une seule aptitude sans texte long) peut
            # être plus bas que ce qu'il faut pour loger le nom de la phase
            # pivoté à 90° — sans plancher, le texte déborde du bandeau et se
            # fait recouvrir par la ligne suivante. `_min_rail_height` mesure
            # la largeur réelle du libellé le plus long à cette police/taille
            # plutôt que de deviner une marge.
            rail_height = max(body_height, _min_rail_height(key))
            rail = _PhaseRail(tr(_PHASE_LABELS[key]).upper(), bg, fg, height=rail_height, width=_RAIL_WIDTH)

            group_row = Table([[rail, body]], colWidths=[_RAIL_WIDTH, body_width])
            group_row.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            # Un tronçon de phase (déjà garanti tenir sous `_MAX_GROUP_HEIGHT`,
            # donc sous une page pleine, cf. `_chunk_group`) est une ligne à
            # part entière de la table extérieure (`rows`) : `Table.split()`
            # ne coupe jamais une ligne en deux, seulement entre deux lignes —
            # ce tronçon ne peut donc déjà pas se retrouver coupé au milieu de
            # ses aptitudes à un saut de page, il part entier sur la page
            # suivante s'il ne rentre pas dans l'espace restant (`KeepTogether`
            # a été essayé ici pour le rendre plus explicite, mais échoue :
            # imbriqué dans une cellule de `Table`, `KeepTogether.wrap()`
            # renvoie une hauteur sentinelle énorme que la table extérieure
            # interprète comme une ligne à dimensionner en conséquence —
            # `reportlab.platypus.doctemplate.LayoutError` dès qu'un tronçon
            # atterrit en page 2+. `KeepTogether` ne fonctionne qu'au niveau
            # du flux de document (`story`), jamais imbriqué dans une cellule).
            rows.append([group_row])
            r = len(rows) - 1
            styles += [
                ("LEFTPADDING", (0, r), (-1, r), 0), ("RIGHTPADDING", (0, r), (-1, r), 0),
                ("TOPPADDING", (0, r), (-1, r), 0), ("BOTTOMPADDING", (0, r), (-1, r), 0),
            ]
            if chunk_i == 0 and first_phase_row is not None:
                # filet épais à la couleur de la phase qui commence : le
                # changement de phase se lit sur toute la largeur, pas
                # seulement sur le bandeau vertical (cf. `_PHASE_HEADER_HEIGHT`,
                # même problème en mode sectionné).
                styles.append(("LINEABOVE", (0, r), (-1, r), 2.2, colors.HexColor(bg)))
            if first_phase_row is None:
                first_phase_row = r
            if chunk_i == len(chunks) - 1:
                styles.append(("LINEBELOW", (0, r), (-1, r), 0.6, _STEEL_LINE))


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
    "wc_section", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white,
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


def _pack_section_rows(abilities: list[AbilityEntry]) -> list[list[tuple[AbilityEntry, int]]]:
    """Range les aptitudes d'une sous-section en lignes de `_SECTION_COLUMNS`
    colonnes, chacune occupant 1 à 3 colonnes (`_ability_span`). Remplissage
    « première ligne où ça rentre » dans l'ordre, puis la place restante d'une
    ligne incomplète est redonnée à ses aptitudes les plus longues — jamais de
    case vide."""
    rows: list[list[tuple[AbilityEntry, int]]] = []
    for ab in abilities:
        span = _ability_span(ab)
        for row in rows:
            if sum(sp for _a, sp in row) + span <= _SECTION_COLUMNS:
                row.append((ab, span))
                break
        else:
            rows.append([(ab, span)])
    for row in rows:
        spare = _SECTION_COLUMNS - sum(sp for _a, sp in row)
        while spare > 0:
            i = max(range(len(row)), key=lambda k: len(_clean_text(row[k][0].description)) / row[k][1])
            row[i] = (row[i][0], row[i][1] + 1)
            spare -= 1
    return rows


def _section_header(title: str, width: float) -> Table:
    t = Table([[Paragraph(tr(title).upper(), _SECTION_HEADER_STYLE)]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _SECTION_HEADER_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    t._aospy_section_header = True
    return t


def _is_section_header(flow: Flowable) -> bool:
    return getattr(flow, "_aospy_section_header", False)


#: largeur minimale d'une case de grille, en fraction de la ligne — sous ce
#: seuil, nom + pastilles ne tiennent plus.
_MIN_CELL_FRACTION = 0.24


def _balanced_widths(row: list[tuple[AbilityEntry, int]], width: float) -> list[float]:
    """Largeurs des cases d'une ligne de grille : d'abord proportionnelles à
    leur nombre de colonnes, puis rééquilibrées selon la surface de texte de
    chaque case (hauteur × largeur mesurées) pour que les cases d'une même
    ligne aient des hauteurs proches — la ligne prend la hauteur de sa case la
    plus haute, tout écart est de la place perdue."""
    base = [width * span / _SECTION_COLUMNS for _ab, span in row]
    if len(row) < 2:
        return base
    areas = [_ability_rows_body([ab], w).wrap(w, 0xFFFF)[1] * w for (ab, _span), w in zip(row, base)]
    total = sum(areas)
    widths = [width * a / total for a in areas]
    floor = width * _MIN_CELL_FRACTION
    short = [i for i, w in enumerate(widths) if w < floor]
    if short:
        rest = width - floor * len(short)
        others = sum(areas[i] for i in range(len(row)) if i not in short)
        widths = [floor if i in short else rest * areas[i] / others for i in range(len(row))]
    return widths


def _section_row(row: list[tuple[AbilityEntry, int]], width: float) -> Table:
    """Une ligne de la grille : chaque aptitude dans sa case, de largeur
    proportionnelle à son nombre de colonnes, séparée de la voisine par un
    filet vertical."""
    widths = _balanced_widths(row, width)
    cells = [_ability_rows_body([ab], w) for (ab, _span), w in zip(row, widths)]
    t = Table([cells], colWidths=widths)
    styles = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if len(row) > 1:
        styles.append(("LINEBEFORE", (1, 0), (-1, -1), 0.4, _STEEL_LINE))
    t.setStyle(TableStyle(styles))
    return t


@dataclass
class _SectionItem:
    """Un élément du corps d'un bandeau de phase sectionné : titre de
    sous-section ou ligne de grille, avec le titre de sa sous-section (pour
    reprendre « (suite) » après une coupe de page)."""
    flow: Flowable
    title: str
    is_header: bool
    is_choice: bool


#: bandeaux qui suivent le déroulé de la partie étape par étape (« Placez le
#: Champ de Bataille », jet de priorité...) : jamais réordonnés par `_BASE_LAST`.
_SEQUENCE_PHASES = frozenset({"deploy", "round_start"})


def _sectioned_phase_items(
    group: list[AbilityEntry], body_width: float, phase_key: str = "",
) -> list[_SectionItem]:
    """Corps d'un bandeau de phase en sous-sections (titre noir + grille), à
    plat : `_SectionedPhaseGroup` se charge des coupes de page."""
    sections: dict[str, list[AbilityEntry]] = {}
    for ab in group:
        sections.setdefault(ability_section(ab), []).append(ab)
    base_last = _BASE_LAST and phase_key not in _SEQUENCE_PHASES

    # `AbilityEntry.section_rank` (aptitude de synthèse `fr-split-simple`,
    # ex. « Jet de Lancement » juste avant les Sorts) prime sur le rang du titre.
    # `base_last` (`fr-split-simple`) : les règles de base, que le joueur
    # connaît, passent après celles de son armée (demande de l'utilisateur).
    def rank(kv: tuple[str, list[AbilityEntry]]) -> int:
        if base_last and kv[0] == SECTION_BASE:
            return max(_SECTION_RANK.values()) + 2
        return min(
            (ab.section_rank for ab in kv[1] if ab.section_rank is not None), default=_section_rank(kv[0]),
        )

    ordered = sorted(sections.items(), key=rank)  # tri stable
    items: list[_SectionItem] = []
    for title, abilities in ordered:
        abilities = sorted(abilities, key=lambda ab: _CATEGORY_ORDER.index(_ability_category(ab)))
        is_choice = title in _CATEGORY_LABELS_FR.values() and title not in _CAST_SECTIONS.values()
        items.append(_SectionItem(_section_header(title, body_width), title, True, is_choice))
        for row in _pack_section_rows(abilities):
            items.append(_SectionItem(_section_row(row, body_width), title, False, is_choice))
    return items


#: hauteur utile d'une page de cartes de règles (cadre de
#: `pdf_builder._build_rule_cards_pdf` avec la marge haute du libellé de page,
#: ~273mm) moins une marge de sécurité — cf. `_MAX_CHOICE_HEIGHT`.
_FULL_PAGE_HEIGHT = 265 * mm


#: sous-sections gardées sur une même page (cf. `_SectionedPhaseGroup.split`).
_CONTIGUOUS_CAST_SECTIONS = ("Sorts", "Manifestations")

#: en-tête horizontal d'un bandeau de phase (cf. `_SectionedPhaseGroup`) et
#: espace entre deux bandeaux : sans eux, deux phases consécutives n'étaient
#: séparées que par le changement de couleur du bandeau vertical, la nouvelle
#: phase s'ouvrant sur un titre de sous-section noir identique aux autres —
#: changement de phase peu visible (signalé par l'utilisateur).
_PHASE_HEADER_HEIGHT = 3.4 * mm
_PHASE_HEADER_FONT_SIZE = 7.2
_PHASE_GAP = 2.2 * mm


#: un bandeau de phase sectionné qui manque la place restante de peu (au
#: moins ce ratio de sa hauteur tient) est réduit uniformément pour y tenir
#: au lieu de partir à la page suivante (demande de l'utilisateur).
_SHRINK_TO_FIT = 0.95


class _ShrunkFlowable(Flowable):
    """`flowable` réduit uniformément d'un facteur `scale` (< 1), centré
    horizontalement sur `width` (par défaut sa largeur réduite)."""

    def __init__(self, flowable: Flowable, scale: float, width: float | None = None):
        super().__init__()
        self._flowable = flowable
        self._scale = scale
        self.spaceBefore = getattr(flowable, "spaceBefore", 0)
        self.hAlign = getattr(flowable, "hAlign", "CENTER")
        self.width = flowable.width * scale if width is None else width
        self.height = flowable.height * scale

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate((self.width - self._flowable.width * self._scale) / 2, 0)
        c.scale(self._scale, self._scale)
        self._flowable.drawOn(c, 0, 0)
        c.restoreState()


class _SectionedPhaseGroup(Flowable):
    """Un bandeau de phase sectionné, posé directement dans le flux du
    document (pas dans une cellule de `Table`, que reportlab ne sait pas
    couper) : s'il ne rentre pas dans la place restante, part à la page
    suivante ; plus haut qu'une page, il se coupe alors entre deux lignes de
    grille (`split`) à partir de ce haut de page. Chaque
    morceau redessine le bandeau de phase à gauche ; une sous-section coupée
    reprend son titre « (suite) ». Une sous-section de choix (« Délires »...)
    n'est jamais coupée si elle tient sur une page (demande de
    l'utilisateur, cf. `_choice_segments`). Dessine aussi les bords gauche/
    droit/bas de la carte, que porte ailleurs la `Table` de `render_rule_card`."""

    def __init__(
        self, phase_key: str, items: list[_SectionItem], width: float,
        space_before: float = 0.0, continued: bool = False,
    ):
        super().__init__()
        self.phase_key = phase_key
        self.items = items
        self.width = width
        # ignoré par le `Frame` en haut de page : ne sépare que deux bandeaux
        # posés l'un sous l'autre.
        self.spaceBefore = space_before
        self.continued = continued
        #: recompose ce bandeau à une autre largeur (`_sectioned_phase_groups`,
        #: bandeau entier seulement — jamais un morceau déjà coupé)
        self.rebuild = None
        # centré comme la `Table` d'en-tête de carte (hAlign par défaut de
        # reportlab) : la carte est plus large que la zone utile du `Frame`
        # (padding de 6pt de chaque côté), un flowable aligné à gauche serait
        # décalé de 12pt vers la droite par rapport à son en-tête.
        self.hAlign = "CENTER"
        self.body_width = width - _RAIL_WIDTH
        self._heights = [it.flow.wrap(self.body_width, 0xFFFF)[1] for it in items]
        self.height = max(sum(self._heights), _min_rail_height(phase_key)) + _PHASE_HEADER_HEIGHT

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def split(self, availWidth, availHeight):
        # un bandeau qui ne rentre pas dans la place restante part sur la page
        # suivante, même s'il est plus haut qu'une page : il n'est alors coupé
        # qu'à partir d'un haut de page, jamais en laissant un petit morceau en
        # bas de la page précédente (demande de l'utilisateur). Sauf s'il est
        # déjà en haut de page (`availHeight` ≈ une page pleine), sans quoi
        # reportlab bouclerait.
        if self.rebuild is not None and _SHRINK_TO_FIT * self.height <= availHeight < self.height:
            # il ne manque presque rien : plutôt que de partir à la page
            # suivante en laissant un grand blanc, le bandeau est recomposé
            # plus large puis réduit à la largeur de la carte (texte un peu
            # plus petit, même largeur que les autres bandeaux).
            scale = availHeight / self.height
            for _ in range(6):
                wide = self.rebuild(self.width / scale)
                if wide.height * scale <= availHeight + 0.01:
                    return [_ShrunkFlowable(wide, scale, self.width)]
                scale *= availHeight / (wide.height * scale)
                if scale < _SHRINK_TO_FIT:
                    break
        if availHeight < _FULL_PAGE_HEIGHT:
            return []
        cumulative = _PHASE_HEADER_HEIGHT
        k = 0
        for h in self._heights:
            if cumulative + h > availHeight:
                break
            cumulative += h
            k += 1
        # jamais finir sur un titre de sous-section orphelin
        while k > 0 and self.items[k - 1].is_header:
            k -= 1
        if 0 < k < len(self.items) and self.items[k].is_choice and not self.items[k].is_header:
            # coupe au milieu d'une sous-section de choix : elle part entière
            start = k
            while start > 0 and not self.items[start].is_header:
                start -= 1
            k = start
        # plus haut qu'une page : coupé de préférence entre deux
        # sous-sections plutôt qu'au milieu de l'une d'elles.
        section_cut = max((i for i in range(1, k + 1) if i < len(self.items) and self.items[i].is_header), default=0)
        if section_cut > 0:
            k = section_cut
        # Sorts et Manifestations restent sur la même page quand ils y
        # tiennent ensemble (demande de l'utilisateur) : une coupe entre/dans
        # eux recule au titre « Sorts ».
        cast = [i for i, it in enumerate(self.items) if it.title in _CONTIGUOUS_CAST_SECTIONS]
        if cast and 0 < cast[0] < k <= cast[-1] and sum(self._heights[cast[0]:cast[-1] + 1]) <= _FULL_PAGE_HEIGHT:
            k = cast[0]
        if k <= 0 or sum(self._heights[:k]) < _min_rail_height(self.phase_key) and _min_rail_height(self.phase_key) > availHeight:
            return []
        head, rest = self.items[:k], self.items[k:]
        if not rest:
            return [self]
        if not rest[0].is_header:
            title = rest[0].title
            rest = [_SectionItem(_section_header(f"{title} (suite)", self.body_width), title, True, rest[0].is_choice)] + rest
        return [
            _SectionedPhaseGroup(self.phase_key, head, self.width, self.spaceBefore, self.continued),
            _SectionedPhaseGroup(self.phase_key, rest, self.width, continued=True),
        ]

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(_CARD_BG)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        bg, fg = _PHASE_COLORS[self.phase_key]
        label = tr(_PHASE_LABELS[self.phase_key]).upper()
        # bandeau vertical + en-tête horizontal de même couleur, en « L » : le
        # libellé se lit sans tourner la tête et le début de phase se repère
        # d'un coup d'œil sur toute la largeur de la carte.
        rail = _PhaseRail(label, bg, fg, height=self.height, width=_RAIL_WIDTH)
        rail.wrap(_RAIL_WIDTH, self.height)
        rail.drawOn(c, 0, 0)
        c.setFillColor(colors.HexColor(bg))
        c.rect(0, self.height - _PHASE_HEADER_HEIGHT, self.width, _PHASE_HEADER_HEIGHT, fill=1, stroke=0)
        c.setFillColor(colors.HexColor(fg))
        c.setFont("Helvetica-Bold", _PHASE_HEADER_FONT_SIZE)
        c.drawString(
            _RAIL_WIDTH + 2, self.height - _PHASE_HEADER_HEIGHT / 2 - _PHASE_HEADER_FONT_SIZE * 0.35,
            f"{label} (SUITE)" if self.continued else label,
        )
        y = self.height - _PHASE_HEADER_HEIGHT
        prev_header = True
        for it, h in zip(self.items, self._heights):
            y -= h
            it.flow.drawOn(c, _RAIL_WIDTH, y)
            if not it.is_header and not prev_header:
                # filet entre deux lignes de grille d'une même sous-section
                c.setStrokeColor(_STEEL_LINE)
                c.setLineWidth(0.4)
                c.line(_RAIL_WIDTH, y + h, self.width, y + h)
            prev_header = it.is_header
        c.setStrokeColor(_STEEL_LINE)
        c.setLineWidth(0.8)
        c.line(0, 0, 0, self.height)
        c.line(self.width, 0, self.width, self.height)
        c.setLineWidth(0.6)
        c.line(0, 0, self.width, 0)
        c.restoreState()


def _with_render_flags(flags: tuple[bool, bool, bool], fn):
    """Exécute `fn` avec les drapeaux de rendu de `render_rule_card` tels
    qu'au moment de la composition — une recomposition (`rebuild`) a lieu à
    la mise en page, après leur remise à zéro."""
    global _HIDE_TURN_QUALIFIER, _SECTIONED, _BASE_LAST
    saved = (_HIDE_TURN_QUALIFIER, _SECTIONED, _BASE_LAST)
    _HIDE_TURN_QUALIFIER, _SECTIONED, _BASE_LAST = flags
    try:
        return fn()
    finally:
        _HIDE_TURN_QUALIFIER, _SECTIONED, _BASE_LAST = saved


def _sectioned_phase_groups(
    abilities: list[AbilityEntry], width: float, phase_order: list[str] | None = None,
) -> list[Flowable]:
    """Variante de `_append_ability_groups` (mode `fr-split`) : même bandeau
    de phase vertical à gauche, mais le corps est découpé en sous-sections
    horizontales — règles de base (génériques), règles d'armée, puis une par
    unité — chacune titrée dans un bandeau noir (plutôt qu'une pastille par
    aptitude) au-dessus d'une grille de 1 à 3 colonnes (`_pack_section_rows`).
    Un `_SectionedPhaseGroup` par phase, à poser dans le flux du document."""
    grouped: dict[str, list[AbilityEntry]] = {}
    for ab in abilities:
        grouped.setdefault(classify_phase(ab), []).append(ab)
    body_width = width - _RAIL_WIDTH
    keys = [key for key in phase_order or _PHASE_ORDER if grouped.get(key)]
    def build(key: str, w: float, space_before: float, with_rebuild: bool) -> _SectionedPhaseGroup:
        group = _SectionedPhaseGroup(
            key, _sectioned_phase_items(grouped[key], w - _RAIL_WIDTH, phase_key=key), w,
            space_before=space_before,
        )
        if with_rebuild:
            flags = (_HIDE_TURN_QUALIFIER, _SECTIONED, _BASE_LAST)
            group.rebuild = lambda new_w: _with_render_flags(flags, lambda: build(key, new_w, space_before, False))
        return group

    return [build(key, width, _PHASE_GAP if i else 0.0, True) for i, key in enumerate(keys)]


def _keyword_key(kw: str) -> str:
    # ignore la casse et un simple "s" de pluriel — une aptitude "Ensorcelled
    # Banners" (StD) porte déjà "Ensorcelled Banner" (singulier) dans son
    # propre `keywords` Wahapedia ; sans ce rapprochement, l'étiquetage
    # d'origine ajoutait un second badge quasi identique à côté du premier.
    return kw.strip().lower().rstrip("s")


def tag_ability_origin(abilities: list[AbilityEntry], origin_label: str) -> list[AbilityEntry]:
    """Ajoute `origin_label` (« Traits de Bataille », « Formation »...) au
    champ `keywords` de chaque aptitude — il en ressort comme un badge doré
    de plus à côté des mots-clés d'aptitude déjà présents, cf. `_name_line`/
    `_ability_row_flowables`. Un badge de carte aurait disparu si les
    aptitudes de plusieurs catégories se retrouvent réunies sur une seule
    carte (cf. `render_rule_card`) ou rejoignent la carte d'un héros ; un
    badge d'aptitude, lui, survit au déplacement. N'ajoute rien si un
    mot-clé quasi identique (cf. `_keyword_key`) figure déjà — une aptitude
    dont Wahapedia porte déjà le nom de catégorie en mot-clé ne doit pas
    aussi le recevoir en badge d'origine, sous peine de deux badges
    redondants côte à côte."""
    target = _keyword_key(origin_label)
    # mot-clé anglais Wahapedia dont `origin_label` est la traduction (ex.
    # « Ensorcelled Banner » pour « Bannière Ensorcelée ») : remplacé par le
    # badge d'origine plutôt que gardé à côté (même redondance, en 2 langues).
    translated = {
        _keyword_key(en) for en, spec in _ENHANCEMENT_CATEGORY_LABELS.items() if _keyword_key(spec["label"]) == target
    }
    result = []
    for ab in abilities:
        existing = [kw.strip() for kw in ab.keywords.split(",") if kw.strip()] if ab.keywords else []
        if any(_keyword_key(kw) == target for kw in existing):
            result.append(ab)
            continue
        kept = [kw for kw in existing if _keyword_key(kw) not in translated]
        result.append(_dc_replace(ab, keywords=",".join(kept + [origin_label])))
    return result


#: en-deçà de ce volume de texte cumulé (caractères des descriptions, tous
#: bandeaux de phase confondus), une carte de règles fusionnée tient
#: confortablement sur une seule colonne — l'étaler sur 2 colonnes n'aidait
#: alors qu'à rétrécir chaque bandeau sans rien gagner en compacité (ex. une
#: Armée de Renom sans Formation propre, ou une faction dont seuls 2-3
#: Traits de Bataille courts sont couverts). Au-delà, la carte réunit assez
#: de contenu (Traits de Bataille + Formation + Traits Héroïques/Artefacts +
#: domaines...) pour qu'un bandeau de phase chargé (ex. tous les Traits
#: Héroïques) bénéficie vraiment des 2 colonnes — cas de figure le plus
#: courant en pratique, une faction pleinement curée dépassant largement ce
#: seuil (généralement >15000 caractères).
_RULE_CARD_TWO_COLUMN_THRESHOLD = 2000


def _rule_card_columns(abilities: list[AbilityEntry]) -> int:
    total_chars = sum(len(_clean_text(ab.description)) for ab in abilities)
    return 2 if total_chars > _RULE_CARD_TWO_COLUMN_THRESHOLD else 1


def render_rule_card(
    title: str, abilities: list[AbilityEntry], width: float = 88 * mm, subtitle: str | None = None,
    phase_order: list[str] | None = None, hide_turn_qualifier: bool = False, sectioned: bool = False,
    base_last: bool = False,
) -> Flowable | list[Flowable] | None:
    """Carte de règle — même grammaire visuelle que `render_warscroll_card`
    mais sans bandeau de stats ni armes, ces cartes ne sont pas des unités.
    `abilities` est déjà étiqueté par catégorie (`tag_ability_origin`) côté
    appelant, avant d'être éventuellement fusionné avec d'autres catégories
    sur une seule carte triée par phase (cf. `pdf_builder.resolve_rules`) —
    ce n'est plus la responsabilité de cette fonction de le faire.  `None`
    si `abilities` est vide (rien à afficher)."""
    if not abilities:
        return None
    rows: list[list] = []
    styles: list[tuple] = []

    header_cell = [Paragraph(title, _HEAD_STYLE)]
    if subtitle:
        header_cell.append(Paragraph(subtitle, _ROLE_STYLE))
    rows.append([header_cell])
    styles.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161a2b")))
    styles.append(("TOPPADDING", (0, 0), (-1, 0), 5))
    styles.append(("BOTTOMPADDING", (0, 0), (-1, 0), 5))
    styles.append(("LEFTPADDING", (0, 0), (-1, 0), 8))

    # jusqu'à 2 colonnes par bandeau de phase (cf. `_rule_card_columns`) :
    # cette carte réunit plusieurs catégories (Traits de Bataille,
    # Formation, Traits Héroïques...) triées ensemble par phase, donc un
    # bandeau peut compter beaucoup d'aptitudes — sa largeur (130mm, contre
    # 88mm pour une carte d'unité) s'y prête mieux qu'une longue colonne
    # unique, mais seulement si le contenu total le justifie.
    # `sectioned` (mode `fr-split`) : sous-sections titrées par origine puis
    # par unité, grille de 1 à 3 colonnes (`_append_sectioned_ability_groups`).
    # Rendu sectionné : une liste de flowables (en-tête de carte puis un
    # `_SectionedPhaseGroup` par phase) plutôt qu'une seule `Table`, pour que
    # chaque bandeau de phase puisse se couper entre deux pages.
    global _HIDE_TURN_QUALIFIER, _SECTIONED, _BASE_LAST
    _HIDE_TURN_QUALIFIER = hide_turn_qualifier
    _SECTIONED = sectioned
    _BASE_LAST = base_last
    try:
        if sectioned:
            header = Table(rows, colWidths=[width])
            header.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                *styles,
            ]))
            # l'en-tête de carte ne reste jamais seul en bas de page
            header.keepWithNext = True
            return [header] + _sectioned_phase_groups(abilities, width, phase_order=phase_order)
        _append_ability_groups(rows, styles, abilities, width, columns=_rule_card_columns(abilities), phase_order=phase_order)
    finally:
        _HIDE_TURN_QUALIFIER = False
        _SECTIONED = False
        _BASE_LAST = False

    card = Table(rows, colWidths=[width])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        *styles,
    ]))
    return card


#: Marge de la cellule qui contient le tableau d'armes — utilisée à la fois
#: pour dimensionner `col_widths` (cf. `content_width` ci-dessous) et pour
#: poser le style de padding de cette cellule, afin que les deux ne puissent
#: pas diverger de nouveau.
_WEAPON_ROW_LEFT_PAD = 8
_WEAPON_ROW_RIGHT_PAD = 6


_PLACE_WHOLLY_RE = re.compile(r"entièrement à (\d+)\"|wholly within (\d+)\"", re.I)
_PLACE_WITHIN_RE = re.compile(r"\bà (\d+)\"|\bwithin (\d+)\"", re.I)
_PLACE_EDGE_RE = re.compile(r"d['’]un bord|battlefield edge", re.I)
_PLACE_ENEMY_RE = re.compile(r"à plus de (\d+)\" (?:de toutes les |des )unités ennemies|more than (\d+)\" from all enemy units", re.I)
_PLACE_PARTS_RE = re.compile(
    r"(?:a|se compose de) (\d+) parties qui doivent être placées à (\d+)\" l['’]une de l['’]autre"
    r"|has (\d+) parts that must be set up within (\d+)\" of each other", re.I,
)
_PLACE_EACH_PART_RE = re.compile(
    r"(?:a|se compose de) (\d+) parties chacune devant être placée à (\d+)\" d['’]au moins 1 autre partie"
    r"|has (\d+) parts that must each be set up within (\d+)\" of at least 1 other part", re.I,
)
_PLACE_CIRCLE_RE = re.compile(r"(\d+) parties qui doivent être placées en contact|(\d+) parts that must be set up touching", re.I)
_PLACE_TRIANGLE_RE = re.compile(r"exactement (\d+)\" de la première|exactly (\d+)\" from the first part", re.I)


def _first(m: re.Match | None) -> list[str]:
    return [g for g in m.groups() if g is not None] if m else []


def summon_placement_note(summon: AbilityEntry) -> list[str]:
    """Règle de pose d'une convocation de manifestation en puces courtes
    (« Entièrement à 12" et visible du lanceur », « À plus de 9" de
    l'ennemi », « 2 parties à 9" l'une de l'autre »), lue sur l'effet du sort
    de convocation lui-même (pas sur l'encadré « Référence de convocation »
    des chartes GW, qui en oublie parfois, ex. les 2 parties des Géminides
    d'Uhl-Gysh). Français (`faction_rules_fr.json`, formulations variables :
    « visible et entièrement à 18" du Prêtre », « entièrement à 12" du
    lanceur et visible de lui »...) ou anglais (Wahapedia). Rien si aucune
    distance n'est reconnue (mieux vaut pas de note qu'une note fausse). La
    valeur de lancement n'y figure pas : badge dédié."""
    text = re.sub(r"<[^>]+>", " ", summon.description or "").replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    effect = re.split(r"Effet ?:|Effect:", text, maxsplit=1)[-1].strip()
    first_sentence = effect.split(". ", 1)[0]
    lines: list[str] = []

    en = _ENGLISH_LABELS
    is_priest = re.search(r"prêtre|chanter|priest", first_sentence, re.I)
    if en:
        who = "of the priest" if is_priest else "of the caster"
        visible = " and visible to" if re.search(r"visible", first_sentence, re.I) else ""
        who = ("the priest" if is_priest else "the caster") if visible else who
    else:
        who = "du prêtre" if is_priest else "du lanceur"
        visible = " et visible" if re.search(r"visible", first_sentence, re.I) else ""
    if _PLACE_EDGE_RE.search(first_sentence) and (n := _first(_PLACE_WHOLLY_RE.search(first_sentence))):
        lines.append(f'Wholly within {n[0]}" of a battlefield edge' if en else f'Entièrement à {n[0]}" d\'un bord de table')
    elif n := _first(_PLACE_WHOLLY_RE.search(first_sentence)):
        lines.append(f'Wholly within {n[0]}"{visible} {who}' if en else f'Entièrement à {n[0]}"{visible} {who}')
    elif n := _first(_PLACE_WITHIN_RE.search(first_sentence)):
        lines.append(f'Within {n[0]}"{visible} {who}' if en else f'À {n[0]}"{visible} {who}')
    if not lines:
        return []
    if n := _first(_PLACE_ENEMY_RE.search(effect)):
        lines.append(f'More than {n[0]}" from the enemy' if en else f'À plus de {n[0]}" de l\'ennemi')
    if n := _first(_PLACE_PARTS_RE.search(effect)):
        lines.append(f'{n[0]} parts within {n[1]}" of each other' if en else f'{n[0]} parties à {n[1]}" l\'une de l\'autre')
    elif n := _first(_PLACE_EACH_PART_RE.search(effect)):
        lines.append(f'{n[0]} parts, each within {n[1]}" of another' if en else f'{n[0]} parties, chacune à {n[1]}" d\'une autre')
    elif n := _first(_PLACE_CIRCLE_RE.search(effect)):
        lines.append(f"{n[0]} parts touching, in a circle" if en else f"{n[0]} parties en contact, en cercle")
    elif n := _first(_PLACE_TRIANGLE_RE.search(effect)):
        lines.append(f'3 parts exactly {n[0]}" from each other, in a triangle' if en else f'3 parties à exactement {n[0]}" l\'une de l\'autre, en triangle')
    return lines


def _summon_badge(summon: AbilityEntry) -> _CastBadge | None:
    pts_type = (summon.points_type or "").strip()
    value = (summon.points or "").strip()
    if pts_type not in ("Spell", "Prayer") or not value:
        return None
    return _CastBadge(
        _CAST_BADGE_SHAPES[pts_type], f"{value}+", _CAST_BADGE_COLORS[pts_type], _CAST_BADGE_FG[pts_type],
        size=_CASTER_BADGE_SIZE,
    )


def render_warscroll_card(ws: WarscrollData, width: float = 88 * mm, regiment_note: str | None = None) -> Flowable:
    """Construit la carte d'une unité en un seul `Flowable` composite (table
    imbriquée) : bandeau nom/rôle, stats, armes, aptitudes groupées par
    bandeau de phase (ordre canonique du tour), mots-clés. Verbatim anglais,
    aucune page de battletome copiée."""
    rows: list[list] = []
    styles: list[tuple] = []

    # Pas de sous-titre de rôle ("INFANTRY", "INFANTRY HERO"...) sous le nom :
    # `ws.role` ne fait que redire un mot-clé déjà affiché dans la liste de
    # mots-clés en pied de carte (`ws.keywords` porte toujours "Infantry"/
    # "Hero" séparément, cf. Wahapedia) — un vrai nom français y prendrait sa
    # place plus tard (cf. la maquette HTML), mais aucune source de données
    # fiable n'existe encore pour ça.
    name_role_cell: list = [Paragraph(ws.name, _HEAD_STYLE)]
    if ws.subtitle:
        name_role_cell.append(Paragraph(ws.subtitle, _SUBTITLE_STYLE))

    # badge Sorcier/Prêtre en haut à droite de l'en-tête (cf.
    # `_caster_badges`) : seulement construit un en-tête à 2 colonnes quand
    # l'unité en porte un, pour ne rien changer à la mise en page de
    # l'écrasante majorité des unités (aucun niveau de magie/de prière).
    caster_badges = _caster_badges(ws.keywords)
    # manifestation : valeur de lancement de sa convocation, même place
    summon_badge = _summon_badge(ws.summon) if ws.summon is not None else None
    if summon_badge is not None:
        caster_badges.append(summon_badge)
    if caster_badges:
        badge_flow, badge_w = _caster_badge_row(caster_badges)
        name_col_w = width - 8 - 8 - badge_w - 6  # 8+8 = LEFTPADDING/RIGHTPADDING posés plus bas sur cette ligne
        header_inner = Table([[name_role_cell, badge_flow]], colWidths=[name_col_w, badge_w + 6])
        header_inner.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        header_cell = [header_inner]
    else:
        header_cell = name_role_cell
    rows.append([header_cell])
    styles.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor("#161a2b")))
    styles.append(("TOPPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 5))
    styles.append(("BOTTOMPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 5))
    styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))
    styles.append(("RIGHTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))

    stat_labels = ["MV", "CT", "SV", "WD", "HP"]
    stat_values = [ws.move or "—", ws.control or "—", ws.save or "—", ws.ward or "—", ws.health or "—"]
    stat_cells = [
        Paragraph(f'{k}<br/><font size=12 color="#14172a"><b>{v}</b></font>', _STAT_STYLE)
        for k, v in zip(stat_labels, stat_values)
    ]
    stat_table = Table([stat_cells], colWidths=[width / 5] * 5)
    stat_table.setStyle(TableStyle([
        ("LINEAFTER", (0, 0), (-2, 0), 0.4, _STEEL_LINE),
        ("LINEBEFORE", (2, 0), (2, 0), 1, _STEEL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    rows.append([stat_table])
    styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    meta_left = f"{ws.unit_size} model" + ("s" if ws.unit_size not in ("1", "") else "") if ws.unit_size else ""
    # une manifestation/un sort vivant n'a pas de coût en points (invoqué en
    # jeu, jamais acheté dans la liste) — `ws.points` y est vide.
    meta_right = f"{ws.points} pts" if ws.points else tr("Invoquée")
    meta_table = Table([[Paragraph(meta_left, _META_STYLE), Paragraph(meta_right, ParagraphStyle("wc_metar", parent=_META_STYLE, alignment=2))]], colWidths=[width / 2] * 2)
    meta_table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    rows.append([meta_table])
    styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    placement = summon_placement_note(ws.summon) if ws.summon is not None else []
    if placement:
        rows.append([Paragraph("<br/>".join(f"• {line}" for line in placement), _PLACEMENT_STYLE)])
        styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))
        styles.append(("TOPPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 3))
        styles.append(("BOTTOMPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 4))
        styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    if regiment_note:
        rows.append([Paragraph(regiment_note, _NOTE_STYLE)])
        styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 8))
        styles.append(("TOPPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 2))
        styles.append(("BOTTOMPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), 2))
        styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    if ws.weapons:
        ratios = _wielder_ratios(ws.description)
        # une colonne Portée dédiée seulement si l'unité porte au moins une
        # arme de tir — sinon elle serait vide sur toute la carte (toutes
        # armes de mêlée) et ne ferait que grignoter la colonne Nom pour
        # rien. Une arme de mêlée sur une carte qui en a une la laisse vide
        # plutôt que d'y répéter un tiret.
        has_ranged = any(w.range for w in ws.weapons)
        whd = ["", tr("Portée"), "Atk", "Hit", "Wnd", "Rnd", "Dmg"] if has_ranged else ["", "Atk", "Hit", "Wnd", "Rnd", "Dmg"]
        wrows = [[Paragraph(h, _WHD_STYLE) for h in whd]]
        stat_col_w = 9 * mm
        n_stat_cols = 6 if has_ranged else 5
        # `width` est la largeur pleine de la carte, mais cette table est
        # posée dans une cellule qui porte elle-même `_WEAPON_ROW_LEFT_PAD` +
        # `_WEAPON_ROW_RIGHT_PAD` de marge (cf. plus bas) — sans en tenir
        # compte ici, `colWidths` sommait à `width` plein alors que l'espace
        # réellement disponible dans la cellule est plus étroit, et une
        # valeur de dégât large ("D3+3") débordait du cadre de la carte
        # (repéré sur Terrorgheist's Fanged Maw, FEC). Même correction que
        # `_ability_group_body.content_width` applique déjà pour son propre
        # padding.
        content_width = width - _WEAPON_ROW_LEFT_PAD - _WEAPON_ROW_RIGHT_PAD
        col_widths = [content_width - n_stat_cols * stat_col_w] + [stat_col_w] * n_stat_cols
        # souligne chaque ligne d'arme dans la couleur de sa phase (même
        # palette que les bandeaux d'aptitude, `_PHASE_COLORS`) — mêlée en
        # rouge, tir en bleu — pour la distinguer au premier coup d'œil sans
        # avoir à lire la colonne Portée, et sépare visuellement les entrées
        # quand l'unité porte plusieurs profils d'arme.
        row_underlines: list[tuple[int, str]] = []
        for w in ws.weapons:
            name_para = _safe_paragraph(f"<b>{w.name}</b>", _WNAME_STYLE)
            ratio = ratios.get(w.name.strip().lower())
            ratio_pill = _pill(ratio, _BADGE_NEUTRAL, "#eaf1f8") if ratio else None
            if ratio_pill is not None:
                # ratio de porteurs à côté du nom, sur la même ligne
                # (colonnes auto-taillées, pas de `colWidths` fixe) — pas en
                # dessous, pour ne pas désaligner le nom par rapport aux
                # colonnes Atk/Hit/Wnd/Rnd/Dmg de la même ligne.
                name_line = Table([[name_para, ratio_pill]])
                name_line.setStyle(TableStyle([
                    ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 5),
                    ("RIGHTPADDING", (1, 0), (1, 0), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]))
                name_cell: list = [name_line]
            else:
                name_cell = [name_para]
            if w.abilities:
                tags = _clean_text(w.abilities)
                if _FRENCH_WEAPON_TAGS:
                    tags = weapon_abilities_fr(tags)
                name_cell.append(_safe_paragraph(tags, _WTAG_STYLE))
            row = [name_cell]
            if has_ranged:
                row.append(Paragraph(w.range, _WVAL_STYLE) if w.range else Paragraph("", _WVAL_STYLE))
            row += [
                Paragraph(w.attacks, _WVAL_STYLE), Paragraph(w.hit, _WVAL_STYLE), Paragraph(w.wound, _WVAL_STYLE),
                Paragraph(w.rend, _WVAL_STYLE), Paragraph(w.damage, _WVAL_STYLE),
            ]
            wrows.append(row)
            underline_color = _PHASE_COLORS["shoot"][0] if w.range else _PHASE_COLORS["melee"][0]
            row_underlines.append((len(wrows) - 1, underline_color))
        weapons_table = Table(wrows, colWidths=col_widths)
        weapon_styles: list[tuple] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (1, 0), (-1, -1), 1), ("RIGHTPADDING", (1, 0), (-1, -1), 1),
            ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 3),
        ]
        for row_i, color in row_underlines:
            weapon_styles.append(("LINEBELOW", (0, row_i), (-1, row_i), 1, colors.HexColor(color)))
        weapons_table.setStyle(TableStyle(weapon_styles))
        rows.append([weapons_table])
        styles.append(("LEFTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), _WEAPON_ROW_LEFT_PAD))
        styles.append(("RIGHTPADDING", (0, len(rows) - 1), (-1, len(rows) - 1), _WEAPON_ROW_RIGHT_PAD))
        styles.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.6, _STEEL_LINE))

    _append_ability_groups(rows, styles, ws.abilities, width)

    visible_keywords = _visible_keywords(ws.keywords)
    if visible_keywords:
        kw_text = " · ".join(k.upper() for k in visible_keywords)
        kw_table = Table([[Paragraph(kw_text, _KW_STYLE), Paragraph("Wahapedia (EN)", _PROV_STYLE)]], colWidths=[width * 0.75, width * 0.25])
        kw_table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        rows.append([kw_table])

    card = Table(rows, colWidths=[width])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        *styles,
    ]))
    return card


def build_warscroll_cards_flow(
    warscrolls: list[WarscrollData], width: float = 88 * mm, gap: float = 5 * mm,
    regiment_notes: dict[str, str] | None = None,
) -> list:
    """`regiment_notes` (clé = `WarscrollData.name`) ajoute la petite note de
    provenance d'un Regiment of Renown à une seule unité membre — cf.
    `pdf_builder.py`."""
    regiment_notes = regiment_notes or {}
    full_width = width * 2 + gap
    cards: list[Flowable] = []
    heights: list[float] = []
    solo: list[bool] = []
    # chartes de manifestation : toutes sur une même page (demande de
    # l'utilisateur), cf. `pack_cards_two_columns(groups=...)`
    groups: list[str | None] = [
        "manifestation" if any(kw.strip().upper() == "MANIFESTATION" for kw in ws.keywords) else None
        for ws in warscrolls
    ]
    for ws in warscrolls:
        note = regiment_notes.get(ws.name)
        card = render_warscroll_card(ws, width=width, regiment_note=note)
        _, height = card.wrap(width, 0xFFFF)
        oversized = height > _MAX_CARD_HEIGHT
        if oversized:
            # à demi-largeur, cette carte ne tiendrait sur aucune page (cf.
            # `_MAX_CARD_HEIGHT`) ; redessinée en pleine largeur, le même
            # texte s'enroule sur bien moins de lignes et repasse sous la
            # hauteur d'une page — posée seule sur toute la largeur, cf.
            # `pack_cards_two_columns`.
            card = render_warscroll_card(ws, width=full_width, regiment_note=note)
            _, height = card.wrap(full_width, 0xFFFF)
        cards.append(card)
        heights.append(height)
        solo.append(oversized)
    return pack_cards_two_columns(cards, heights, width=width, gap=gap, solo=solo, groups=groups)


def _two_columns_block(columns: list[list[Flowable]], width: float, gap: float) -> Table:
    """Une table d'une ligne, une colonne d'écart dédiée entre les 2 colonnes
    de cartes empilées (une cellule reportlab accepte une liste de
    `Flowable`) : un padding sur la cellule forcerait seulement la table à
    s'élargir, chaque carte ayant sa largeur interne fixe."""
    return Table([[columns[0], "", columns[1]]], colWidths=[width, gap, width], style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))


def pack_cards_two_columns(
    cards: list[Flowable], heights: list[float], width: float = 88 * mm, gap: float = 5 * mm,
    solo: list[bool] | None = None, page_height: float = _MAX_CARD_HEIGHT,
    groups: list[str | None] | None = None,
) -> list:
    """Empile des cartes en 2 colonnes indépendantes, page par page (demande
    de l'utilisateur : une carte courte ne laisse plus un grand vide à côté
    d'une carte haute, comme avec des lignes de 2). Dans l'ordre d'entrée,
    chaque carte va dans la colonne la moins haute de la page en cours où
    elle tient (sinon l'autre) ; sinon elle passe à la page suivante, et les
    cartes suivantes qui tiennent encore comblent la page en cours. `solo[i]` marque
    une carte redessinée en pleine largeur (`width * 2 + gap`, cf.
    `build_warscroll_cards_flow`) : elle clôt les colonnes en cours et prend
    toute la largeur. `heights[i]` = hauteur de `cards[i]` à sa largeur ;
    `page_height` = hauteur utile d'une page (cadre `_CARD_PAGE_MARGIN`).
    `groups[i]` : les cartes d'un même groupe (non `None`, ex. toutes les
    chartes de manifestation) sont posées ensemble sur une même page, à la
    place de la première d'entre elles — sinon le groupe entier passe à la
    page suivante."""
    solo = solo or [False] * len(cards)
    groups = groups or [None] * len(cards)
    story: list = []
    used = 0.0  # hauteur déjà occupée sur la page en cours (blocs clos)
    columns: list[list[Flowable]] = [[], []]
    col_h = [0.0, 0.0]

    def block_height() -> float:
        return max(col_h)

    def close_block() -> None:
        nonlocal used, columns, col_h
        if not any(columns):
            return
        if story and used > 0:
            story.append(Spacer(1, gap))
            used += gap
        story.append(_two_columns_block(columns, width, gap))
        used += block_height()
        columns, col_h = [[], []], [0.0, 0.0]

    def new_page() -> None:
        nonlocal used
        story.append(PageBreak())
        used = 0.0

    def try_place(item: list[tuple[Flowable, float]]) -> bool:
        # toutes les cartes de `item` ou aucune (groupe d'une même page)
        room = page_height - used - (gap if used > 0 else 0)
        sim_h = list(col_h)
        plan = []
        for _card, h in item:
            for c in sorted((0, 1), key=lambda c: sim_h[c]):
                add = h + (gap if (columns[c] or any(p == c for p in plan)) else 0)
                if sim_h[c] + add <= room:
                    sim_h[c] += add
                    plan.append(c)
                    break
            else:
                return False
        for (card, h), c in zip(item, plan):
            if columns[c]:
                columns[c].append(Spacer(1, gap))
            columns[c].append(card)
        col_h[:] = sim_h
        return True

    def place_run(run: list[list[tuple[Flowable, float]]]) -> None:
        # premier emplacement libre : une carte (ou un groupe) qui ne tient
        # plus passe à la page suivante, mais les suivantes qui tiennent
        # encore comblent la page en cours (l'ordre ne bouge que d'une page
        # au plus).
        while run:
            deferred = [item for item in run if not try_place(item)]
            if len(deferred) == len(run) and used == 0 and not any(columns):
                if len(deferred[0]) > 1:
                    # groupe trop haut même pour une page vide : ses cartes
                    # reprennent le placement normal, une à une
                    run = [[pair] for pair in deferred[0]] + deferred[1:]
                    continue
                # page vide et une carte plus haute qu'une page : posée
                # quand même, reportlab la coupera
                columns[0].append(deferred[0][0][0])
                col_h[0] = deferred[0][0][1]
                deferred = deferred[1:]
            if deferred:
                close_block()
                new_page()
            run = deferred

    run: list[list[tuple[Flowable, float]]] = []
    group_items: dict[str, list[tuple[Flowable, float]]] = {}
    for card, h, is_solo, group in zip(cards, heights, solo, groups):
        if not is_solo:
            if group is None:
                run.append([(card, h)])
            elif group in group_items:
                group_items[group].append((card, h))
            else:
                group_items[group] = [(card, h)]
                run.append(group_items[group])
            continue
        place_run(run)
        run = []
        close_block()
        if used > 0 and used + gap + h > page_height:
            new_page()
        elif used > 0:
            story.append(Spacer(1, gap))
            used += gap
        story.append(card)
        used += h
    place_run(run)
    close_block()
    return story


# -- Cartes de tactique de bataille --------------------------------------
# Transcription manuelle, verbatim en français (`tactic_cards.py`) — même
# grammaire visuelle (pastilles pleines, pas de texte coloré entre crochets)
# que les cartes d'unité/de règle, adaptée : pas de bandeau de phase ici (une
# tactique se déclenche « à la fin de votre tour », pas liée à une phase
# précise du Manuel du général), 3 sous-tactiques (Échauffourée / Frappe /
# Domination) à la place, chacune avec sa propre pastille de type et sa
# pastille de points de victoire.

#: une couleur de pastille par type de sous-tactique — l'échelle de gravité
#: de la carte source (échauffourée -> frappe -> domination, en principe de
#: plus en plus difficile à déclencher) mappée sur l'échelle de sévérité déjà
#: en place pour les badges d'aptitude (neutre -> stat mise en avant ->
#: alerte), pas une nouvelle palette inventée pour l'occasion.
_TACTIC_KIND_COLORS: dict[str, tuple[str, str]] = {
    "Échauffourée": (_BADGE_NEUTRAL, "#eaf1f8"),
    "Frappe": (_BADGE_STAT, "#eaf4f6"),
    "Domination": (_BADGE_REACT, "#fbeaec"),
}
#: pastille de points de victoire — un aplat doré plus riche que
#: `_BADGE_KEYWORD` (réservé aux mots-clés) : ce badge doit se repérer d'un
#: coup d'œil même sans lire le texte, comme la médaille dorée de la carte
#: source, pas se confondre avec une classification de plus.
_POINTS_GOLD = "#c9a227"
_POINTS_INK = "#2a2005"

_TACTIC_HEAD_STYLE = ParagraphStyle("tc_head", fontName=CARD_TITLE_FONT, fontSize=13, leading=15, textColor=colors.white)
_TACTIC_SPECIAL_STYLE = ParagraphStyle("tc_special", fontName="Helvetica", fontSize=7.8, leading=10, textColor=_STEEL)
_TACTIC_NAME_STYLE = ParagraphStyle("tc_name", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=_INK)
_TACTIC_COND_STYLE = ParagraphStyle("tc_cond", fontName="Helvetica", fontSize=7.8, leading=10, textColor=_STEEL)
_TACTIC_POINTS_STYLE = ParagraphStyle("tc_points", fontName="Helvetica-Bold", fontSize=13, leading=15, textColor=colors.HexColor(_POINTS_INK), alignment=1)
_TACTIC_POINTS_LABEL_STYLE = ParagraphStyle("tc_points_lbl", fontName="Helvetica-Bold", fontSize=5.4, leading=6.4, textColor=colors.HexColor(_POINTS_INK), alignment=1)


def _points_badge(points: int, width: float) -> Table:
    """Pastille « points de victoire » dédiée, plus grande que `_pill` — la
    valeur numérique doit rester lisible même isolée dans sa propre colonne,
    c'est le seul badge de la carte que le lecteur doit pouvoir repérer sans
    lire le texte qui l'entoure."""
    inner = Table(
        [[Paragraph(str(points), _TACTIC_POINTS_STYLE)], [Paragraph(tr("PTS DE<br/>VICTOIRE"), _TACTIC_POINTS_LABEL_STYLE)]],
        colWidths=[width],
    )
    inner.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    box = Table([[inner]], colWidths=[width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_POINTS_GOLD)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return box


def _sub_tactic_block(sub: SubTactic, width: float) -> Table:
    """Un encadré par sous-tactique (Échauffourée/Frappe/Domination) : nom +
    pastille de type à gauche, pastille de points de victoire à droite —
    même schéma « contenu + badge dans sa propre colonne » que les cartes
    d'unité/de règle, décliné à l'échelle de la carte entière plutôt que
    d'une seule aptitude."""
    kind_bg, kind_fg = _TACTIC_KIND_COLORS.get(sub.kind, (_BADGE_NEUTRAL, "#eaf1f8"))
    points_col = 22 * mm
    left_width = width - points_col
    # `block` (plus bas) peint 7+6pt de marge autour de sa colonne de gauche
    # — `left`, construite ici avec une largeur fixe, doit s'y caler *après*
    # déduction de cette marge, sans quoi son contenu (notamment la ligne
    # nom+condition) déborde dans la colonne de la pastille de points voisine
    # (même bug que `_ability_group_body` avait déjà rencontré, cf. son
    # commentaire — même cause, même correctif).
    left_content_width = left_width - 13
    kind_col = 26 * mm
    name_col = left_content_width - kind_col

    header = Table(
        [[_pill(tr(sub.kind.upper()), kind_bg, kind_fg), _safe_paragraph(f"<b>{sub.name}</b>", _TACTIC_NAME_STYLE)]],
        colWidths=[kind_col, name_col],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    # pas de ligne d'ambiance (`sub.flavor`, gardé dans le JSON) : les
    # cartes ne portent que les règles (demande explicite de l'utilisateur).
    left = Table(
        [[header], [_safe_paragraph(sub.condition, _TACTIC_COND_STYLE)]],
        colWidths=[left_content_width],
    )
    left.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (0, 1), 1), ("BOTTOMPADDING", (0, 1), (0, 1), 0),
    ]))

    block = Table([[left, _points_badge(sub.points, points_col - 4 * mm)]], colWidths=[left_width, points_col])
    block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.7, _STEEL_LINE),
        ("LEFTPADDING", (0, 0), (0, -1), 7), ("RIGHTPADDING", (0, 0), (0, -1), 6),
        ("LEFTPADDING", (1, 0), (1, -1), 2), ("RIGHTPADDING", (1, 0), (1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return block


def render_tactic_card(card: TacticCard, width: float = 188 * mm) -> Flowable:
    """Carte de tactique de bataille — remplace la copie de page PDF
    (`Manuel du général/MdG26-27 Tactiques.pdf`) par un rendu « maison »
    verbatim (texte français transcrit à la main, `tactic_cards.py`). Plus
    large que les cartes d'unité/de règle (`width` par défaut = la largeur
    utile d'une page A4 portrait) : elle n'est jamais mise en paire, cf.
    `pdf_builder._build_tactic_cards_pdf` qui les empile simplement, assez
    compactes pour que les 2 tactiques citées par une liste tiennent
    normalement sur une seule page."""
    rows: list[list] = []
    styles: list[tuple] = []

    header_cell = [
        Paragraph(card.title_fr, _TACTIC_HEAD_STYLE),
        Paragraph(f"CARTE DE TACTIQUE {card.number} · {card.name_en}", _ROLE_STYLE),
    ] if not card.english else [
        Paragraph(card.name_en, _TACTIC_HEAD_STYLE),
        Paragraph(f"BATTLE TACTIC CARD {card.number}", _ROLE_STYLE),
    ]
    rows.append([header_cell])
    styles += [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161a2b")),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LEFTPADDING", (0, 0), (-1, 0), 8),
    ]

    # pas de ligne d'ambiance (`card.flavor`, gardé dans le JSON) — cf.
    # `_sub_tactic_block`.

    if card.special_rule:
        special_box = Table(
            [[_pill(tr("RÈGLE SPÉCIALE"), _BADGE_NEUTRAL, "#eaf1f8")], [_safe_paragraph(card.special_rule, _TACTIC_SPECIAL_STYLE)]],
            colWidths=[width - 16],
        )
        special_box.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 3),
            ("TOPPADDING", (0, 1), (0, 1), 0), ("BOTTOMPADDING", (0, 1), (0, 1), 0),
        ]))
        rows.append([special_box])
        r = len(rows) - 1
        styles += [
            ("LEFTPADDING", (0, r), (-1, r), 8), ("RIGHTPADDING", (0, r), (-1, r), 8),
            ("TOPPADDING", (0, r), (-1, r), 5), ("BOTTOMPADDING", (0, r), (-1, r), 5),
            ("LINEBELOW", (0, r), (-1, r), 0.5, _STEEL_LINE),
        ]

    for sub in card.sub_tactics:
        rows.append([_sub_tactic_block(sub, width - 16)])
        r = len(rows) - 1
        styles += [
            ("LEFTPADDING", (0, r), (-1, r), 8), ("RIGHTPADDING", (0, r), (-1, r), 8),
            ("TOPPADDING", (0, r), (-1, r), 4), ("BOTTOMPADDING", (0, r), (-1, r), 4),
        ]

    card_table = Table(rows, colWidths=[width])
    card_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, _STEEL_LINE),
        ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        *styles,
    ]))
    return card_table
