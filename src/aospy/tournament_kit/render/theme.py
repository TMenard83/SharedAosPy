"""Thème des cartes maison : police des titres, couleurs des phases et des pastilles, styles de paragraphe."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

#: police des noms de carte (unité/règle/tactique) — Cinzel Bold, la même que
#: la maquette HTML (`font-family:"Cinzel"`, chargée depuis Google Fonts,
#: `.card .head h2{font-weight:700}`) plutôt que le Helvetica-Bold générique
#: utilisé avant : un vrai display serif capitalisé, cohérent avec
#: l'esthétique "tome" du reste de la carte (bandeau nom/rôle sombre,
#: parchemin). Embarqué en TTF plutôt que référencé par un chemin système
#: (l'ancien `scratch/build_pdf.py` pointait vers `C:/Windows/Fonts/...`, un chemin
#: Windows qui ne marche que sur une machine précise) : Cinzel est sous SIL
#: Open Font License, librement redistribuable, donc le fichier vit dans le
#: paquet (`tournament_kit/assets/Cinzel-Bold.ttf`, embarqué via `package-data` dans
#: `pyproject.toml`) et se charge par chemin relatif à ce module, portable
#: partout. Enregistré une seule fois, au niveau module (pas dans une
#: fonction appelée par carte) ; repli silencieux sur Helvetica-Bold si le
#: fichier venait à manquer (ex. install sans les données du paquet) plutôt
#: que de faire planter toute la génération de PDF pour une police décorative.
CARD_TITLE_FONT = "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("Cinzel-Bold", str(Path(__file__).parents[1] / "assets" / "Cinzel-Bold.ttf")))
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
    "deploy": "Déploiement",
    "round_start": "Début de round",
    "asterism": "Astérisme",
    "start": "Début de tour",
    "hero": "Phase des héros",
    "move": "Phase de mouvement",
    "shoot": "Phase de tir",
    "charge": "Phase de charge",
    "melee": "Phase de mêlée",
    "end": "Fin de tour",
    "any": "N'importe quelle phase",
}

#: reportlab ne peint pas de fond derrière un texte qui coule dans un
#: `Paragraph` (pas de vraie pastille comme dans la maquette HTML) — les
#: teintes doivent donc être nettement plus saturées que le corps de texte
#: (gris/noir) pour continuer à se voir comme des badges plutôt que du texte
#: normal, avec un léger cadrage `[ ]` en plus pour rester lisibles même en
#: N&B.
_BADGE_NEUTRAL = "#2e5c8a"  # timing : fréquence, condition, passif — en contour (`outline`), pour ne pas se confondre avec le bleu de la phase de tir
_BADGE_KEYWORD = "#6e6259"  # classification : mot-clé d'aptitude sans couleur propre — taupe neutre, le jaune étant réservé à la phase des héros (demande de l'utilisateur)
_BADGE_MULTI_PHASE = "#56606b"  # mot-clé servant dans plusieurs phases (ATTACK, RAMPAGE) — ardoise, en contour
_BADGE_STAT = "#1f6b78"  # stat d'arme mise en avant : portée
_BADGE_REACT = "#8c1f1f"  # alerte : réaction
_BADGE_SPELL = "#5b3a8f"  # sort — valeur d'incantation (points_type "Spell")
_BADGE_PRAYER = "#2e6b4f"  # prière — valeur de prière (points_type "Prayer")
_BADGE_COMMAND = "#7a4a1f"  # point de commandement — coût en PC (points_type "Command")
_BADGE_RAGE = "#a3300f"  # dé de rage (Règles de Saison 2026-27) — cf. `_resource_badges`
_BADGE_FURY = "#d9620b"  # point de fureur (Règles de Saison 2026-27)
_BADGE_SEASON = "#c8451c"  # badge d'origine « Saison » (rouge orangé, demande de l'utilisateur)
_BADGE_BLOOD = "#7a1620"  # dime de sang — coût en points de sang (points_type "Blood tithe", Blades of Khorne)
_BADGE_FACTION = "#6b2545"  # mot-clé d'aptitude propre à une seule faction (ex. Delusion, Tidal) — cf. `_keyword_pills`
_BADGE_SOURCE = "#4a5260"  # source du texte (BT, FP, MdG, SIMPLE, Wahapedia...) — une seule couleur pour toutes (demande de l'utilisateur)
_BADGE_WARSCROLL = (
    "#161a2b"  # warscroll porteur d'une aptitude sortie de sa carte (mode `fr-split`) — cf. `_warscroll_pills`
)


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
_SUBTITLE_STYLE = ParagraphStyle(
    "wc_subtitle", fontName="Helvetica-Oblique", fontSize=7, leading=8.5, textColor=colors.HexColor("#a9adbd")
)
_STAT_STYLE = ParagraphStyle("wc_stat", fontName="Helvetica", fontSize=6.5, leading=17, textColor=_STEEL, alignment=1)
_META_STYLE = ParagraphStyle("wc_meta", fontName="Helvetica", fontSize=7.5, leading=10, textColor=_STEEL)
_WHD_STYLE = ParagraphStyle("wc_whd", fontName="Helvetica", fontSize=6.5, leading=8, textColor=_STEEL, alignment=1)
_WNAME_STYLE = ParagraphStyle("wc_wname", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=_INK)
_WTAG_STYLE = ParagraphStyle("wc_wtag", fontName="Helvetica-Oblique", fontSize=6.5, leading=8, textColor=_STEEL)
_WVAL_STYLE = ParagraphStyle("wc_wval", fontName="Helvetica", fontSize=7.5, leading=9, textColor=_INK, alignment=1)
_KW_STYLE = ParagraphStyle("wc_kw", fontName="Helvetica", fontSize=6, leading=8, textColor=_STEEL)
_PROV_STYLE = ParagraphStyle(
    "wc_prov", fontName="Helvetica-Oblique", fontSize=6, leading=8, textColor=_STEEL, alignment=2
)
