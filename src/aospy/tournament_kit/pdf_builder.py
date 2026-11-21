"""Assemble le PDF « kit de tournoi » : page de couverture (liste mise en
forme), puis les règles de faction pertinentes en carte maison (traits de
bataille, formation, traits héroïques/artefacts, domaines de sorts/
manifestations choisis — Wahapedia-first, repli page French par catégorie,
cf. `warscroll_card.py`) et les cartes de tactique de bataille citées, elles
aussi en carte maison verbatim français (`tactic_cards.py`, transcription
manuelle de `MdG26-27 Tactiques.pdf` — plus de copie de page pour aucune de
ces sections), puis les profils d'unité, en carte maison anglaise dessinée
par `warscroll_card.py` à partir de `data/wahapedia/*.csv` (jamais une page
de battletome copiée, cf. le module de ce fichier pour le détail). Un
domaine de manifestations générique (partagé entre
factions, absent du battletome) est résolu en français via
`data/Manuel du général/sorts persistants - manifestations.pdf`
(`warscroll_index.generic_manifestation_lores`) — règles de convocation
*et* charte de chaque manifestation invocable, pas seulement l'annonce du
sort. Enfin, si besoin, une annexe en anglais (repli Wahapedia,
`wahapedia_lookup.py`) pour tout ce qui n'existe dans *aucun* des PDF
fournis : règles d'armée de renom, Régiments de Renom, et tout domaine de
sorts/manifestations qui échapperait aussi au French. Aucun accès DB
requis.

Une Armée de Renom (ex. « Slaves to Darkness | Legion of the First Prince »)
*remplace* tout ou partie des traits de bataille / traits héroïques et
artefacts / domaine de sorts de la faction de base par ses propres règles
(cf. `_AOR_REPLACES`) — la page du battletome de base correspondante est
omise plutôt que dupliquée à côté de la version de remplacement (rendue à
part, en anglais via Wahapedia). Aucune armée de renom n'a en revanche ses
propres formations de bataille (constaté sur toutes les entrées du CSV) :
cette section-là reste toujours celle de la faction de base. Un Regiment of
Renown donne accès à des warscrolls normalement hors faction (résolus via
`WahapediaLookup.find_warscroll`, qui cherche dans toutes les factions) *et*
peut porter sa propre aptitude générique (`RegimentOfRenownData.abilities`) —
rendue dans l'annexe comme n'importe quel autre bloc d'aptitudes s'il compte
plusieurs unités membres, mais directement rattachée à la carte de l'unité
(`_render_warscroll(..., extra_abilities=...)`) quand le régiment n'en a
qu'une seule, pour ne pas dupliquer inutilement la structure.

Le paragraphe ci-dessus décrit le mode `hybrid` (défaut). `build_roster_pdf(...,
mode=...)` porte 3 autres variantes (`RosterMode`) : `en` (Wahapedia
uniquement, la copie de page French est sautée) et `fr`/`fr-extended`
(correctifs/additions vérbatim français de `data/json/faction_rules_fr.json`
appliqués sur le pool Wahapedia partout où ils existent, copie de page
également sautée — `fr-extended` ajoute les Aptitudes Génériques,
`data/json/generic_core_abilities.json`). Cf. le commentaire au-dessus de
`RosterMode` et le skill `faction-rules-fr` pour le détail.

Les Règles de Saison 2026-27 (`season_rules.py`, incluses dans tout PDF), les
Aptitudes Génériques (`fr-extended` seulement) et les règles de faction/
Armée de Renom résolues ci-dessus (`rule_ability_pool`) rejoignent toutes le
même bassin d'aptitudes puis une seule carte triée par bandeau de phase
(`build_roster_pdf`, badges d'origine « Saison »/« MdG »/faction pour rester
identifiables) — jamais 3 cartes séparées : un joueur qui consulte la carte
raisonne par phase du tour ("je suis en phase des héros, qu'ai-je le droit
de faire ?"), pas par type de règle."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace as _dc_replace
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..pdf_theme import GOLD, GOLD_DIM, NIGHT_BLUE, PARCHMENT, STEEL, today_str
from .list_parser import ParsedList, parse_list_file
from .translation.faction_rules_fr import (
    DEFAULT_APP_RULES_EN_FILE, ability_join_key, apply_fr_overrides, get_faction_category_overrides, get_regiment_of_renown_overrides,
    get_unit_ability_overrides, get_unit_display_overrides, load_faction_rules_fr,
)
from .translation.generic_core_abilities import (
    CORE_RULES_SOURCE, DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE, load_generic_core_abilities,
)
from .translation.absent_references import find_absent_keywords, find_absent_references
from .translation.roster_simplifications import load_roster_simplifications
from .translation.rules_resolution import (
    _BANNER_PLEDGED_GOD, _PLEDGE_OPTION_RE, FR_MODES, PATCH_MODES, SIMPLE_MODES, SPLIT_MODES, RosterMode, _find_pledge_battle_trait,
    _resolve_rules,
)
from .translation.season_rules import DEFAULT_SEASON_RULES_EN_FILE, load_season_rules
from .translation.tactic_cards import DEFAULT_TACTIC_CARDS_EN_FILE, find_tactic_card, load_tactic_cards
from .translation.wahapedia_lookup import (
    AbilityEntry, RegimentOfRenownData, WahapediaLookup, WarscrollData, load_wahapedia,
)
from .translation.warscroll_index import battletome_path, generic_manifestation_lores_path, load_index
from .warscroll_card import (
    set_bold_set_up,
    ability_section,
    _FULL_PAGE_HEIGHT, CARD_TITLE_FONT, CHOICE_CATEGORIES, PAGE_BG, SECTION_ARMY, SECTION_BASE, SPLIT_PHASE_ORDER, TURN_ENEMY, TURN_MINE, _classify_phase, ability_turn_sides, build_warscroll_cards_flow,
    is_self_profile_modifier, render_rule_card, render_tactic_card, english_labels, set_english_labels, set_faction_specific_keywords,
    set_french_keywords, set_french_weapon_tags, tr,
    cast_badge_legend, drawn_badge_shapes, reset_drawn_badge_shapes, pill_legend, reset_drawn_pills,
    tag_ability_origin, _strip_flavor,
)


#: Modes qui appliquent la politique de noms FR/EN des cartes de warscroll
#: (nom anglais + sous-titre français, armes et capacités d'arme en
#: français, cf. `_apply_display_fr`) : les modes `fr*` et `hybrid` (mode
#: par défaut, dont les règles copiées du battletome sont déjà françaises).
FR_NAME_MODES: tuple[str, ...] = (*FR_MODES, "hybrid")

#: Racine des PDF de roster générés sans `--out` explicite, rangés
#: `<équipe>/<liste>/<liste> (<mode>).pdf` (`default_output_path`) : toutes
#: les variantes d'une même liste côte à côte, sous le dossier de son équipe
#: — demande explicite de l'utilisateur. Distincte de
#: `scratch/output/best_unit/` (rapports pantheon/duels/coût de `reports/`),
#: l'autre moitié du même rangement.
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "scratch" / "output" / "roster"

#: Dossier des listes ; chaque sous-dossier direct est une équipe
#: (`Vae Victis Vernou/`, `Melusior/`, ...) dont le nom est repris en sortie.
DEFAULT_LISTS_DIR = Path(__file__).resolve().parents[3] / "data" / "Proposition de listes"

#: `hybrid` est le mode historique/par défaut de la CLI (`--mode`, cf.
#: `RosterMode` ci-dessus) mais le fichier est suffixé « defaut » plutôt que
#: « hybrid » : le nom du mode est un détail d'implémentation (repli page
#: battletome + Wahapedia), « defaut » est ce que l'utilisateur reconnaît
#: comme « je n'ai pas précisé de mode ».
_MODE_FILE_LABEL: dict[RosterMode, str] = {
    "hybrid": "defaut",
    "en": "en",
    "fr": "fr",
    "fr-extended": "fr-extended",
    "fr-split": "fr-split",
    "fr-split-simple": "fr-split-simple",
    "en-split-simple": "en-split-simple",
}

#: Marge des pages « cartes » (règles/tactiques/warscrolls) — volontairement
#: plus fine que les 18mm de la couverture/annexe (texte suivi, a besoin de
#: respirer) : plus de surface utile pour les cartes elles-mêmes, l'objectif
#: qui a fait réduire cette marge de moitié (elle était à 11mm).
_CARD_PAGE_MARGIN = 5.5 * mm

#: Largeur utile d'une page A4 portrait avec `_CARD_PAGE_MARGIN` de chaque
#: côté — la marge n'a été réduite que pour dégager cette largeur-là aux
#: cartes elles-mêmes, donc toute carte qui reste seule sur sa ligne
#: (règles, tactique) doit s'y caler entièrement plutôt que de laisser un
#: vide à droite.
_CARD_PAGE_WIDTH = A4[0] - 2 * _CARD_PAGE_MARGIN

#: Largeur de la carte de règles fusionnée — occupe toute la largeur utile
#: (elle reste seule sur sa ligne, cf. `_build_rule_cards_pdf`) : sur 2
#: colonnes par bandeau de phase (`warscroll_card.render_rule_card`), une
#: carte à 130mm serrait ces colonnes bien plus qu'il n'était nécessaire —
#: la conserver à 130mm en avait fait un choix arbitraire) plutôt qu'un vrai
#: usage de la place disponible.
_RULE_CARD_WIDTH = _CARD_PAGE_WIDTH

#: Largeur des cartes de tactique de bataille — jamais mises en paire
#: (contrairement aux cartes de warscroll), juste empilées, assez compactes
#: pour que les 2 tactiques citées par une liste tiennent normalement sur
#: une seule page.
_TACTIC_CARD_WIDTH = _CARD_PAGE_WIDTH

#: Largeur d'une carte de profil d'unité — 2 par ligne (`pack_cards_two_columns`),
#: donc calée sur la moitié de la largeur utile moins l'écart entre les 2
#: (même `gap` que `warscroll_card.build_warscroll_cards_flow`) plutôt qu'une
#: valeur fixe (88mm) choisie sans lien avec cette largeur — céder toute la
#: place disponible aux cartes plutôt que de laisser un vide à droite.
_UNIT_CARD_GAP = 5 * mm
_UNIT_CARD_WIDTH = (_CARD_PAGE_WIDTH - _UNIT_CARD_GAP) / 2

#: police du titre de la liste — Cinzel Bold, la même police "tome" que les
#: titres de carte (`warscroll_card.CARD_TITLE_FONT`) plutôt que
#: `OLD_ENGLISH_FONT` (Times-Bold) utilisé avant : demande explicite de
#: l'utilisateur, pour une cohérence visuelle titre de liste / titre de carte.
_TITLE = ParagraphStyle("kit_title", fontName=CARD_TITLE_FONT, fontSize=20, leading=24, textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceAfter=2)
_META = ParagraphStyle("kit_meta", fontName="Times-Italic", fontSize=9.5, leading=13, textColor=STEEL, alignment=TA_LEFT, spaceAfter=10)
_REGIMENT = ParagraphStyle("kit_regiment", fontName="Times-Bold", fontSize=12, leading=15, textColor=GOLD_DIM, alignment=TA_LEFT, spaceBefore=10, spaceAfter=3)
_WARNING = ParagraphStyle("kit_warning", fontName="Times-Bold", fontSize=9.5, leading=13, textColor=STEEL, alignment=TA_LEFT, spaceBefore=14)
_EN_BANNER = ParagraphStyle("kit_en_banner", fontName="Times-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#8c1f1f"), alignment=TA_LEFT, spaceAfter=2)
_EN_SUBBANNER = ParagraphStyle("kit_en_subbanner", fontName="Times-Italic", fontSize=9.5, leading=13, textColor=STEEL, alignment=TA_LEFT, spaceAfter=12)
_EN_SECTION = ParagraphStyle("kit_en_section", fontName="Times-Bold", fontSize=13, leading=17, textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceBefore=12, spaceAfter=4)
_EN_SUBSECTION = ParagraphStyle("kit_en_subsection", fontName="Times-Bold", fontSize=10.5, leading=14, textColor=GOLD_DIM, alignment=TA_LEFT, spaceBefore=8, spaceAfter=3)
_EN_BODY = ParagraphStyle("kit_en_body", fontName="Times-Roman", fontSize=9, leading=12.5, textColor=NIGHT_BLUE, alignment=TA_LEFT, spaceAfter=6)
_EN_LEGEND = ParagraphStyle("kit_en_legend", fontName="Times-Italic", fontSize=8.5, leading=12, textColor=STEEL, alignment=TA_LEFT, spaceAfter=4)



#: Ordre d'apparition des cartes de profil dans le PDF (après les Héros,
#: toute base confondue, toujours en tête) — demande explicite de
#: l'utilisateur. Wahapedia combine base + rôle dans un seul champ `role`
#: (ex. `"Cavalry Hero"`, `"War Machine"`), d'où le test par sous-chaîne
#: plutôt qu'une correspondance exacte dans `_role_rank`.
_ROLE_ORDER = ("infantry", "cavalry", "beast", "monster", "war machine")


def _role_rank(role: str) -> int:
    """Rang de tri d'une carte de profil : Héros (0, toute base confondue)
    d'abord, puis `_ROLE_ORDER` dans l'ordre. Un rôle qui ne matche ni "hero"
    ni aucune entrée de `_ROLE_ORDER` (Faction Terrain, manifestation
    invocable...) reste en dernier plutôt que de forcer un classement
    arbitraire — `list.sort` étant stable, l'ordre relatif au sein d'un même
    rang reste celui de la liste (régiment du général, puis régiment 1, 2...)."""
    role_l = (role or "").lower()
    if "hero" in role_l:
        return 0
    for i, key in enumerate(_ROLE_ORDER, start=1):
        if key in role_l:
            return i
    return len(_ROLE_ORDER) + 1


@dataclass(frozen=True)
class RosterPdfResult:
    output_path: Path
    units_matched: list[str]
    units_unmatched: list[str]
    rules_included: list[str] = field(default_factory=list)
    rules_unmatched: list[str] = field(default_factory=list)
    wahapedia_used: list[str] = field(default_factory=list)
    #: `*-split-simple` : la version avec les cartes de scénario à la fin
    scenario_output_path: Path | None = None
    #: `*-split-simple` : aptitudes qui citent une unité absente de la liste
    #: (`translation.absent_references`) — à proposer au joueur (principe 7)
    absent_references: list = field(default_factory=list)
    #: `*-split-simple` : aptitudes visant des unités amies d'un type
    #: (Infanterie, Cavalerie…) qu'aucune unité de la liste ne porte
    absent_keywords: list = field(default_factory=list)
    #: modes split : aptitudes de chaque carte de tour (« deploy », « any »,
    #: « mine », « enemy ») et celles restées sur les cartes d'unité
    #: (« warscrolls ») — mêmes entrées que le PDF, pour l'analyse des listes
    #: (`scripts/l3_export_lists.py`), pas lu par le rendu.
    ability_cards: dict = field(default_factory=dict)


def _unit_row(name: str, points: int, options: list[str]) -> str:
    text = f"<b>{name}</b> — {points} pts"
    if options:
        text += "<br/><font size=8 color='#4a4536'>" + ", ".join(options) + "</font>"
    return text


#: fautes de frappe présentes dans le texte Wahapedia scrapé, corrigées au
#: rendu (texte d'origine -> texte corrigé). FEC « A Kingdom Deluded ».
_WAHAPEDIA_TYPOS = {
    "the eect of that D  applies": "the effect of that DELUSION applies",
    "same Delusion  as": "same DELUSION as",
}


def _clean_html(text: str) -> str:
    """Convertit le balisage HTML-ish de Wahapedia en balisage compris par
    `reportlab.platypus.Paragraph` (sous-ensemble XML). `<a>` est déballé
    (garde le texte, retire le lien), `<span class="kwb...">` devient `<b>`
    (c'est déjà la mise en forme visuelle voulue — mots-clés en gras),
    `<ul>/<li>` devient une liste à puces séparée par des retours à la ligne."""
    if not text:
        return ""
    # 2+ id de tooltip scrapés collés bout à bout, sans aucun texte entre eux
    # (ex. LRL, Traits de Bataille, "DEPICT RUNE" :
    # "...<br><br>$000002337$000002338$000002339$000002340$000002341<br>...") :
    # contrairement au cas juste en dessous (un seul id, wrapper autour d'un
    # texte réel déjà présent, ex. "%000010870<ky>FIGHT</ky>%" ou
    # "$000001419|As it twitches..." — l'id sert alors de simple séparateur/
    # marqueur), une *suite* d'ids sans rien entre eux référence du contenu
    # (ici, l'effet de chacune des 5 runes) que Wahapedia résout côté client
    # depuis une table de tooltips absente des 13 CSV téléchargés (aucun
    # fichier tooltip dans `scripts/refresh_wahapedia_data.py`) — un vrai
    # trou de données, pas du bruit. Le signaler plutôt que le faire
    # disparaître silencieusement (ce que faisait le strip générique
    # ci-dessous jusqu'à ce que ça masque l'essentiel du texte de cette
    # aptitude, signalé par l'utilisateur).
    text = re.sub(
        r"(?:[%$]\d+){2,}",
        " <i>[texte manquant dans l’export Wahapedia — voir le Manuel du général/l’App]</i> ",
        text,
    )
    # id de tooltip isolé : simple marqueur autour/avant du texte réel déjà
    # présent (ex. "%000010870<ky>FIGHT</ky>%", "$000001419|As it twitches...")
    # — jamais du texte de règle en lui-même, mais peut laisser une "|"
    # orpheline (séparateur du style "$id|texte") qu'il faut retirer avec lui.
    text = re.sub(r"[%$]\d+\|?", "", text).replace("%", "").replace("$", "")
    # au moins un champ connu est tronqué en plein milieu d'une balise
    # ouvrante (ex. Faction_abilities.csv, "SCHOLAR OF THE SIGILS" : `...<a
    # href="/aos4/fact` sans `>` de fermeture, coupé à la fin du champ ; FEC,
    # "A Splendid Pageant" : `...<span class="tooltip00335"
    # data-tooltip-content="#tooltip_conte` de même) — une balise ouvrante
    # sans son `>` de fermeture jusqu'à la fin de la chaîne ne peut être
    # qu'un artefact de troncature, jamais du texte de règle légitime, quel
    # que soit son nom (`<a`, `<span`...).
    text = re.sub(r"<[a-zA-Z][^>]*$", "", text)
    # balise de mot-clé échappée puis re-balisée par le scrape (FEC, « The One
    # True King »/« A Majestic Menagerie » : `&lt;<span>S</span>PAN</span>
    # <span>CLASS="KWB</span> <span>KWBU"&gt;DELUSION&lt;/SPAN&gt;`) : seul le
    # mot-clé est du texte de règle. Les balises retirées s'équilibrent, le
    # `<span>` englobant reste et met le mot-clé en gras.
    text = re.sub(
        r"&lt;(?:<[^>]+>)*S(?:<[^>]+>)*PAN\b.*?&gt;(.*?)&lt;/SPAN&gt;",
        r"\1", text, flags=re.IGNORECASE | re.DOTALL,
    )
    # fautes du scrape lui-même (ligature « ff » et mot-clé perdus)
    for bad, good in _WAHAPEDIA_TYPOS.items():
        text = text.replace(bad, good)
    text = re.sub(r"<a[^>]*>", "", text)
    text = text.replace("</a>", "")
    text = re.sub(r"<span[^>]*>", "<b>", text)
    text = text.replace("</span>", "</b>")
    # une liste collée à du texte (« Sur 2+ :<ul><li>… ») commence sur une
    # nouvelle ligne, sinon la 1re puce reste accrochée au texte
    text = re.sub(r"(?<=[^>\s])\s*<ul>", "<br/><ul>", text)
    text = re.sub(r"(?<=</b>)\s*<ul>", "<br/><ul>", text)
    text = text.replace("<ul>", "").replace("</ul>", "")
    text = re.sub(r"<li>", "• ", text)
    text = text.replace("</li>", "<br/>")
    text = re.sub(r"<br\s*>", "<br/>", text)
    text = re.sub(r"&(?!amp;|lt;|gt;|quot;|#\d+;)", "&amp;", text)
    return text.strip()


def _strip_all_tags(text: str) -> str:
    """Retire tout balisage — y compris une balise tronquée en plein milieu
    (donnée source corrompue, sans `>` de fermeture jusqu'à la fin du champ),
    en supprimant aussi tout `<`/`>` résiduel isolé pour rester un texte brut
    valide (sans quoi reportlab tenterait encore de le parser comme du XML)."""
    text = re.sub(r"<[^>]*>", " ", text)
    text = text.replace("<", " ").replace(">", " ")
    return re.sub(r"\s+", " ", text).strip()


def _safe_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Comme `Paragraph(text, style)`, mais tolérant : `data/wahapedia/*.csv`
    est une donnée externe scrapée, parfois corrompue (ex. une balise HTML
    tronquée en plein milieu d'un champ) — plutôt que de faire planter toute
    la génération du PDF pour une seule entrée abîmée, on retombe sur le
    texte brut (tags retirés) pour cette entrée-là."""
    try:
        return Paragraph(text, style)
    except Exception:
        return Paragraph(_strip_all_tags(text), style)




#: texture pierre du fond de page — générée par
#: `scripts/generate_stone_texture.py` (procédurale plutôt que téléchargée :
#: même raisonnement que `Cinzel-Bold.ttf`/`warscroll_card.py`, pas de
#: licence à auditer). `ImageReader` construit une seule fois au niveau
#: module ; repli silencieux sur un aplat `PAGE_BG` (même teinte) si le
#: fichier venait à manquer (ex. install sans les données du paquet) — même
#: schéma que le repli police de `warscroll_card.py`.
_STONE_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "stone_texture.jpg"
try:
    _STONE_TEXTURE = ImageReader(str(_STONE_TEXTURE_PATH))
except Exception:
    _STONE_TEXTURE = None


def _draw_page_bg(c, doc) -> None:
    """Peint le fond de chaque page du kit (couverture, cartes, annexe) :
    texture pierre pâle sur toute la page (`_STONE_TEXTURE`). Rien d'autre
    ici — le fond blanc qui porte le texte est désormais une case ajustée au
    contenu (`_wrap_in_sheet` pour la couverture/l'annexe, la carte
    elle-même pour les pages de cartes), jamais un grand rectangle peint sur
    toute la hauteur de la page indépendamment de ce que le contenu occupe
    réellement : cette dernière approche laissait un vide énorme sous un
    contenu court (ex. une petite liste sur la couverture) — signalé par
    l'utilisateur."""
    c.saveState()
    page_w, page_h = doc.pagesize
    if _STONE_TEXTURE is not None:
        c.drawImage(_STONE_TEXTURE, 0, 0, width=page_w, height=page_h, preserveAspectRatio=False)
    else:
        c.setFillColor(PAGE_BG)
        c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    c.restoreState()


#: marge intérieure (haut/bas/gauche/droite) de la case blanche que
#: `_wrap_in_sheet` bâtit autour du texte de couverture/d'annexe.
_SHEET_PADDING = 14


def _wrap_in_sheet(story: list, width: float) -> Table:
    """Enveloppe un `story` (liste de flowables déjà construits) dans une
    seule case à fond blanc/bordure dorée, ajustée exactement à la hauteur
    du contenu plutôt qu'un rectangle peint sur toute la page (cf.
    `_draw_page_bg`) : chaque élément de `story` devient sa propre ligne
    d'un `Table` à une colonne — un `Table` se scinde nativement entre pages
    quand son contenu dépasse une page (contrairement à un flowable unique
    imbriqué dans une seule cellule), donc reste valable même pour une
    longue annexe, pas seulement une couverture tenant sur une page."""
    rows = [[item] for item in story]
    n = len(rows)
    box = Table(rows, colWidths=[width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, GOLD_DIM),
        ("LEFTPADDING", (0, 0), (-1, -1), _SHEET_PADDING),
        ("RIGHTPADDING", (0, 0), (-1, -1), _SHEET_PADDING),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), _SHEET_PADDING),
        ("BOTTOMPADDING", (0, n - 1), (0, n - 1), _SHEET_PADDING),
    ]))
    return box


class _FitToFrame(Flowable):
    """Empile `flowables` et les réduit uniformément (jamais agrandis) pour
    tenir dans la hauteur disponible du cadre — la page de garde (liste +
    légende des pictos) tient ainsi toujours sur une seule page, centrée
    horizontalement."""

    def __init__(self, flowables: list):
        super().__init__()
        self._flowables = flowables
        self._sizes: list[tuple[float, float]] = []
        self._scale = 1.0

    def wrap(self, avail_width, avail_height):
        self._sizes = [f.wrap(avail_width, 1e6) for f in self._flowables]
        natural = sum(h for _w, h in self._sizes)
        self._scale = min(1.0, avail_height / natural) if natural else 1.0
        self._avail_width = avail_width
        self.width, self.height = avail_width, natural * self._scale
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        content_width = max((w for w, _h in self._sizes), default=0)
        canvas.translate((self._avail_width - content_width * self._scale) / 2, 0)
        canvas.scale(self._scale, self._scale)
        y = self.height / self._scale
        for flowable, (_w, h) in zip(self._flowables, self._sizes):
            y -= h
            flowable.drawOn(canvas, 0, y)
        canvas.restoreState()


def _build_cover_pdf(
    parsed: ParsedList, units_unmatched: list[str], rules_unmatched: list[str], wahapedia_used: list[str],
    badge_shapes: frozenset[str] = frozenset(),
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=15 * mm,
        title=parsed.title,
    )
    #: largeur dispo pour le contenu une fois la case blanche (`_wrap_in_sheet`)
    #: posée autour, sa propre marge intérieure (`_SHEET_PADDING`) déduite des
    #: deux côtés — les tables imbriquées (lignes d'unité) doivent s'y caler,
    #: pas à `doc.width` (largeur du cadre de page, plus large que la case).
    content_width = doc.width - 2 * _SHEET_PADDING
    story = [Paragraph(parsed.title, _TITLE)]

    meta_lines = [parsed.faction]
    if parsed.allegiance:
        meta_lines.append(parsed.allegiance)
    if parsed.drops is not None:
        meta_lines.append(tr(f"Drops : {parsed.drops}"))
    if parsed.spell_lore:
        meta_lines.append(tr(f"Domaine de sorts : {parsed.spell_lore}"))
    if parsed.prayer_lore:
        meta_lines.append(tr(f"Domaine de prières : {parsed.prayer_lore}"))
    if parsed.manifestation_lore:
        meta_lines.append(tr(f"Domaine de manifestations : {parsed.manifestation_lore}"))
    story.append(Paragraph(" · ".join(meta_lines), _META))

    if parsed.battle_tactic_cards:
        story.append(Paragraph(f"<b>{tr('Battle Tactic Cards :')}</b> " + ", ".join(parsed.battle_tactic_cards), _META))

    style = ParagraphStyle("kit_cell", fontName="Times-Roman", fontSize=9.5, leading=13, textColor=NIGHT_BLUE)
    for regiment in parsed.regiments:
        story.append(Paragraph(regiment.title, _REGIMENT))
        rows = [[Paragraph(_unit_row(u.name, u.points, u.options), style)] for u in regiment.units]
        if rows:
            table = Table(rows, colWidths=[content_width])
            table.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.6, GOLD),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, GOLD),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(table)

    if parsed.regiments_of_renown:
        story.append(Paragraph("Regiments of Renown", _REGIMENT))
        rows = [
            [Paragraph(_unit_row(ror.name, ror.points, ror.units), style)]
            for ror in parsed.regiments_of_renown
        ]
        table = Table(rows, colWidths=[content_width])
        table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, GOLD),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, GOLD),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)

    if parsed.faction_terrain:
        story.append(Paragraph("Faction Terrain", _REGIMENT))
        story.append(Paragraph(", ".join(parsed.faction_terrain), style))

    if units_unmatched:
        story.append(Paragraph(
            tr("⚠ Profil non trouvé (ni battletome, ni Wahapedia) pour : ") + ", ".join(units_unmatched),
            _WARNING,
        ))
    if rules_unmatched:
        story.append(Paragraph(
            tr("⚠ Règle non trouvée (ni battletome, ni Wahapedia) pour : ") + ", ".join(tr(r) for r in rules_unmatched),
            _WARNING,
        ))
    if wahapedia_used:
        story.append(Paragraph(
            tr("ℹ Complété en anglais via Wahapedia (voir annexe en fin de document) : ") + ", ".join(tr(w) for w in wahapedia_used),
            ParagraphStyle("kit_info", fontName="Times-Italic", fontSize=8.5, leading=12, textColor=STEEL, spaceBefore=8),
        ))

    story.append(Spacer(1, 14))
    story.append(Paragraph(tr("Généré le ") + f"{today_str()} — aospy roster pdf", ParagraphStyle("kit_footer", fontName="Times-Italic", fontSize=8, textColor=STEEL)))

    # légende des pictos (cercle sort, losange prière...) dessinés dans le
    # reste du PDF — demande de l'utilisateur, dans sa propre case sous celle
    # de la liste plutôt que mêlée à celle-ci
    sheets = [_wrap_in_sheet(story, doc.width)]
    legend = cast_badge_legend(badge_shapes)
    pills = pill_legend()
    if legend or pills:
        legend_style = ParagraphStyle("kit_legend", fontName="Times-Roman", fontSize=9, leading=12, textColor=NIGHT_BLUE)
        legend_title = ParagraphStyle("kit_legend_title", parent=_REGIMENT, spaceBefore=0)
        legend_story: list = [Paragraph(tr("Légende des pictos"), legend_title)]
        if legend:
            table = Table(
                [[badge, Paragraph(text, legend_style)] for badge, text in legend], colWidths=[22, content_width - 22],
            )
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]))
            legend_story.append(table)
        if pills:
            # pastilles d'exemple à gauche (largeur de la plus large rangée),
            # explication à droite — mêmes familles/couleurs que les cartes
            pill_col = max(width for _row, width, _text in pills) + 6
            pill_text_style = ParagraphStyle("kit_legend_pill", parent=legend_style, fontSize=8.5, leading=10)
            legend_story.append(Spacer(1, 4))
            # une `Table` par ligne : chacune devient une ligne de la case
            # (`_wrap_in_sheet`), qui peut alors se couper entre deux pages
            for row, _width, text in pills:
                line = Table([[row, Paragraph(text, pill_text_style)]], colWidths=[pill_col, content_width - pill_col])
                line.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                ]))
                legend_story.append(line)
        sheets += [Spacer(1, 10), _wrap_in_sheet(legend_story, doc.width)]

    # liste + légende toujours ensemble en page 1 (demande de l'utilisateur) :
    # réduites uniformément juste assez pour tenir quand la liste est longue
    doc.build([_FitToFrame(sheets)], onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()


#: Les pages copiées depuis les battletomes/Manuel du général sont des scans
#: aplatis (une seule image ~1865x2472 par page, cf. le traitement anti-copie
#: documenté dans CLAUDE.md) : `writer.add_page` les recopie telles quelles,
#: soit ~1 Mo/page rien qu'en JPEG déjà compressé — largement plus que
#: nécessaire pour une page de règles lue à l'écran ou imprimée en A4. On les
#: redimensionne/recompresse après coup (~150-250 Ko/page), ce qui a divisé
#: par 30-40 la taille des PDF de tournoi générés (plusieurs Mo -> quelques
#: centaines de Ko) sans perte de lisibilité perceptible.
_COPIED_PAGE_MAX_DIM = 1600
_COPIED_PAGE_JPEG_QUALITY = 65


def _compress_page_images(page) -> None:
    for img_file in page.images:
        pil_image = img_file.image
        scale = min(1.0, _COPIED_PAGE_MAX_DIM / max(pil_image.size))
        if scale >= 1.0:
            continue
        new_size = (round(pil_image.width * scale), round(pil_image.height * scale))
        resized = pil_image.convert("RGB").resize(new_size, Image.LANCZOS)
        img_file.replace(resized, quality=_COPIED_PAGE_JPEG_QUALITY)


#: Cartes de scénario du Manuel du Général 2026-27 (12 scans, format carte,
#: sans couche texte), ajoutées à la fin d'une seconde version des PDF
#: `*-split-simple`, `(…-split-simple-scenar)` (demande de l'utilisateur),
#: 4 par page A4 (`_append_scenario_pages`).
DEFAULT_SCENARIOS_FILE = Path("data/Manuel du général/MdG26-27 Scenarii.pdf")
_SCENARIO_GAP = 4 * mm


def scenario_variant_path(out_path: Path) -> Path:
    """`<liste> (fr-split-simple).pdf` -> `<liste> (fr-split-simple-scenar).pdf`."""
    stem = out_path.stem
    stem = stem[:-1] + "-scenar)" if stem.endswith(")") else stem + " (scenar)"
    return out_path.with_name(stem + out_path.suffix)


def _append_scenario_pages(writer: PdfWriter, path: Path) -> None:
    """Ajoute les cartes de `path`, 4 par page A4 (2 × 2), réduites juste
    assez pour tenir (≈ 88 %, lisibles) et centrées ; images recompressées
    comme toute page copiée (`_compress_page_images`). Fichier absent : rien."""
    if not path.exists():
        return
    cards = PdfWriter()
    for page in PdfReader(str(path)).pages:
        cards.add_page(page)
        _compress_page_images(cards.pages[-1])
    page_w, page_h = A4
    margin = _CARD_PAGE_MARGIN
    for start in range(0, len(cards.pages), 4):
        sheet = writer.add_blank_page(width=page_w, height=page_h)
        for k, card in enumerate(cards.pages[start:start + 4]):
            # La carte occupe la TrimBox (pages A4 avec carte centrée) ; sans
            # TrimBox, pypdf renvoie la CropBox/MediaBox, soit la page entière.
            box = card.trimbox
            cw, ch = float(box.width), float(box.height)
            scale = min(
                (page_w - 2 * margin - _SCENARIO_GAP) / 2 / cw, (page_h - 2 * margin - _SCENARIO_GAP) / 2 / ch,
            )
            block_w, block_h = 2 * cw * scale + _SCENARIO_GAP, 2 * ch * scale + _SCENARIO_GAP
            x0, y0 = (page_w - block_w) / 2, (page_h - block_h) / 2
            col, row = k % 2, k // 2
            x = x0 + col * (cw * scale + _SCENARIO_GAP)
            y = y0 + (1 - row) * (ch * scale + _SCENARIO_GAP)
            sheet.merge_transformed_page(
                card,
                Transformation().translate(-float(box.left), -float(box.bottom)).scale(scale).translate(x, y),
            )


def _append_pages(writer: PdfWriter, reader: PdfReader, seen_pages: set[int], sections: list[tuple[str, list[int]]]) -> None:
    for _label, pages in sections:
        for page_num in pages:
            if page_num in seen_pages:
                continue
            seen_pages.add(page_num)
            writer.add_page(reader.pages[page_num])
            _compress_page_images(writer.pages[-1])


def _render_ability_entries(story: list, entries: list[AbilityEntry]) -> None:
    for entry in entries:
        story.append(_safe_paragraph(entry.name, _EN_SUBSECTION))
        if entry.legend:
            story.append(_safe_paragraph(_clean_html(entry.legend), _EN_LEGEND))
        story.append(_safe_paragraph(_clean_html(entry.description), _EN_BODY))


def _build_wahapedia_appendix_pdf(
    wahapedia_lore_blocks: list[tuple[str, list[AbilityEntry]]],
    renown_army: tuple[str, dict[str, list[AbilityEntry]]] | None,
    regiments_of_renown: list[tuple[str, RegimentOfRenownData | None]],
) -> bytes | None:
    """Repli anglais pour ce qui n'a pas de carte/page dédiée : domaines de
    sorts/manifestations génériques, règles d'armée de renom, Regiments of
    Renown à plusieurs membres (un seul membre : son aptitude rejoint plutôt
    la carte de cette unité, cf. `build_roster_pdf`). Les profils d'unité
    eux-mêmes ne passent plus par ici — ils sont rendus en carte maison
    (`warscroll_card.py`), plus de page de battletome copiée ni de bloc de
    texte anglais pour un profil d'unité."""
    if not (wahapedia_lore_blocks or renown_army or regiments_of_renown):
        return None

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=15 * mm,
        title="Annexe Wahapedia (EN)",
    )
    story: list = [
        Paragraph(tr("ANNEXE — CONTENU WAHAPEDIA (ANGLAIS)"), _EN_BANNER),
        Paragraph(tr(
            "Ce qui suit n'existe dans aucun des PDF fournis (battletomes, Manuel du général) : "
            "domaines de sorts/manifestations génériques, règles d'armée de renom, Régiments de Renom. "
            "Repris tel quel depuis data/wahapedia/ (Wahapedia, en anglais) — non traduit pour éviter tout contresens sur des règles de jeu."
        ), _EN_SUBBANNER),
    ]

    for label, entries in wahapedia_lore_blocks:
        story.append(Paragraph(label, _EN_SECTION))
        _render_ability_entries(story, entries)

    if renown_army is not None:
        renown_name, grouped = renown_army
        story.append(Paragraph(f"{renown_name} — Army of Renown Rules", _EN_SECTION))
        for category, entries in grouped.items():
            story.append(Paragraph(category, _EN_SUBSECTION))
            _render_ability_entries(story, entries)

    for ror_name, ror_data in regiments_of_renown:
        story.append(Paragraph(f"Regiment of Renown — {ror_name}", _EN_SECTION))
        if ror_data is None:
            story.append(Paragraph("⚠ Non trouvé dans Wahapedia non plus.", _WARNING))
            continue
        if ror_data.legend:
            story.append(_safe_paragraph(_clean_html(ror_data.legend), _EN_LEGEND))
        if ror_data.composition:
            story.append(_safe_paragraph("Composition : " + ", ".join(_clean_html(c) for c in ror_data.composition), _EN_BODY))
        _render_ability_entries(story, ror_data.abilities)

    doc.build([_wrap_in_sheet(story, doc.width)], onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()


#: hauteur réservée en haut de page à l'en-tête discret des pages de tour du
#: mode `fr-split` (`_build_rule_cards_pdf(..., page_label=...)`). Était à
#: 9mm (libellé à ~6mm du bord) : l'imprimante de l'utilisateur coupait le
#: libellé à mi-hauteur, d'où le décalage de tout le contenu de 5mm vers le bas.
_PAGE_LABEL_MARGIN = 14 * mm


def _draw_page_label(c, doc, label: str) -> None:
    """En-tête discret (petites capitales bleu nuit, centrées, filet doré de
    part et d'autre) dans la marge haute d'une page de carte de tour du mode
    `fr-split` — « Mon tour »/« Tour de l'adversaire » : les 2 cartes ont les
    mêmes bandeaux de phase, ce repère dit d'un coup d'œil sur quelle page on
    est sans remonter jusqu'au titre de la carte (demande de l'utilisateur)."""
    c.saveState()
    page_w, page_h = doc.pagesize
    text = label.upper()
    font, size = "Helvetica-Bold", 7
    y = page_h - _PAGE_LABEL_MARGIN + 3 * mm
    text_w = c.stringWidth(text, font, size)
    c.setFont(font, size)
    c.setFillColor(NIGHT_BLUE)
    c.drawCentredString(page_w / 2, y, text)
    c.setStrokeColor(GOLD_DIM)
    c.setLineWidth(0.5)
    gap, rule = 3 * mm, 25 * mm
    mid_y = y + size * 0.35
    c.line(page_w / 2 - text_w / 2 - gap - rule, mid_y, page_w / 2 - text_w / 2 - gap, mid_y)
    c.line(page_w / 2 + text_w / 2 + gap, mid_y, page_w / 2 + text_w / 2 + gap + rule, mid_y)
    c.restoreState()


def _pad_to_odd_page(writer: PdfWriter) -> None:
    """Ajoute une page blanche si la prochaine page serait paire, pour qu'une
    section démarre sur une page impaire (recto) à l'impression recto-verso —
    mode `fr-split` : « Tour de l'adversaire » et les warscrolls (demande
    explicite de l'utilisateur)."""
    if len(writer.pages) % 2 == 1:
        first = writer.pages[0].mediabox
        writer.add_blank_page(width=first.width, height=first.height)


#: hauteur de la ligne de base du numéro de page, depuis le bas de la page :
#: sous le contenu des pages de cartes (`_CARD_PAGE_MARGIN`, 5.5mm).
_PAGE_NUMBER_Y = 2.2 * mm


def _stamp_page_numbers(writer: PdfWriter) -> None:
    """Numéro « n / total » centré en bas de chaque page (demande de
    l'utilisateur), posé après l'assemblage : chaque section est un mini-PDF
    séparé, seule la numérotation finale est la bonne. Une page blanche de
    recto-verso (`_pad_to_odd_page`, sans contenu) compte mais reste vierge."""
    total = len(writer.pages)
    buf = BytesIO()
    first = writer.pages[0].mediabox
    c = rl_canvas.Canvas(buf, pagesize=(float(first.width), float(first.height)))
    for i in range(total):
        c.setFont("Helvetica", 6.5)
        c.setFillColor(STEEL)
        c.drawCentredString(float(first.width) / 2, _PAGE_NUMBER_Y, f"{i + 1} / {total}")
        c.showPage()
    c.save()
    overlay = PdfReader(BytesIO(buf.getvalue()))
    for i, page in enumerate(writer.pages):
        if "/Contents" not in page:
            continue
        page.merge_page(overlay.pages[i])


def _build_rule_cards_pdf(cards: list, page_label: str | None = None, label_margin: bool = False) -> bytes | None:
    """Empile les cartes de règle (Traits de Bataille/Formation/Traits
    Héroïques/Artefacts) en pile simple, sans les grouper 2 par ligne comme
    les cartes de warscroll : leur longueur varie trop (1 aptitude pour une
    formation, 9 pour des traits héroïques) pour qu'un `KeepTogether` sur une
    paire reste pertinent — une carte trop longue pour une page tiendrait la
    carte voisine, plus courte, en otage sur la page précédente.
    `label_margin` : même marge haute que les pages de tour du mode
    `fr-split` (`_PAGE_LABEL_MARGIN`), sans le libellé — carte « Aptitudes »
    des modes non-split (demande de l'utilisateur)."""
    if not cards:
        return None
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_CARD_PAGE_MARGIN, rightMargin=_CARD_PAGE_MARGIN,
        topMargin=_PAGE_LABEL_MARGIN if page_label or label_margin else _CARD_PAGE_MARGIN, bottomMargin=_CARD_PAGE_MARGIN,
        title="Règles de faction (cartes)",
    )
    story: list = []
    for card in cards:
        if story:
            # avant chaque carte sauf la première : un `Spacer` de fin qui ne
            # rentre plus dans l'espace restant part seul sur une page neuve
            # — page blanche en fin de PDF (cf. `pack_cards_two_columns`).
            story.append(Spacer(1, 5 * mm))
        # une carte sectionnée (`render_rule_card(..., sectioned=True)`) est
        # une liste de flowables, chaque bandeau de phase pouvant se couper
        story.extend(card if isinstance(card, list) else [card])

    def on_page(c, d) -> None:
        _draw_page_bg(c, d)
        if page_label:
            _draw_page_label(c, d, page_label)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _tactic_cards_block(cards: list, min_scale: float | None = None) -> Flowable | None:
    """Toutes les cartes de tactique citées dans un seul `KeepTogether` :
    toujours sur la même page (demande explicite de l'utilisateur), quitte
    à partir en page suivante si la place restante ne suffit pas. Sans texte
    d'ambiance (`render_tactic_card`), 2 cartes tiennent largement sur une
    page. Avec `min_scale`, le bloc se réduit jusqu'à cette échelle pour
    tenir dans la place restante plutôt que de changer de page
    (`_ShrinkToFitTogether`)."""
    if not cards:
        return None
    flow: list = []
    for card in cards:
        if flow:
            flow.append(Spacer(1, 6 * mm))
        flow.append(card)
    return _ShrinkToFitTogether(flow, min_scale) if min_scale is not None else KeepTogether(flow)


#: Échelle minimale à laquelle le bloc des cartes de tactique peut être
#: réduit pour tenir sur la page de « Fin de tour » (mode `fr-split`,
#: `_ShrinkToFitTogether`) — en deçà, le texte deviendrait trop petit : le
#: bloc part alors en page suivante, à taille normale.
_TACTIC_MIN_SCALE = 0.85


class _ShrinkToFitTogether(Flowable):
    """`KeepTogether` qui, avant de partir en page suivante, tente de tenir
    dans la place restante en se réduisant (au plus jusqu'à `min_scale`,
    centré horizontalement) — cartes de tactique du mode `fr-split`, posées
    sur la même page que le bandeau « Fin de tour » de « Mon tour » dès que
    c'est possible (demande de l'utilisateur)."""

    def __init__(self, content: list, min_scale: float):
        super().__init__()
        self.content = content
        self.min_scale = min_scale
        self.scale = 1.0

    def _natural(self, avail_width: float) -> tuple[float, float, list[float]]:
        sizes = [f.wrap(avail_width, 0xFFFF) for f in self.content]
        return max(w for w, _h in sizes), sum(h for _w, h in sizes), [h for _w, h in sizes]

    def wrap(self, availWidth, availHeight):
        self._avail_width = availWidth
        width, height, self._heights = self._natural(availWidth)
        self.scale = 1.0
        if height > availHeight and height * self.min_scale <= availHeight:
            self.scale = availHeight / height
        self.width, self.height = availWidth, height * self.scale
        return self.width, self.height

    def split(self, availWidth, availHeight):
        # ne tient même pas réduit : page suivante, à taille normale (comme
        # `KeepTogether`) ; déjà en haut de page, on laisse couper.
        if availHeight < _FULL_PAGE_HEIGHT:
            return []
        return list(self.content)

    def draw(self):
        c = self.canv
        c.saveState()
        content_width = max(f.wrap(self._avail_width, 0xFFFF)[0] for f in self.content)
        c.translate((self._avail_width - content_width * self.scale) / 2, 0)
        c.scale(self.scale, self.scale)
        y = sum(self._heights)
        for f, h in zip(self.content, self._heights):
            y -= h
            f.drawOn(c, 0, y)
        c.restoreState()


def _build_tactic_cards_pdf(cards: list) -> bytes | None:
    """Les cartes de tactique de bataille citées, toutes sur la même page
    (`_tactic_cards_block`)."""
    if not cards:
        return None
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_CARD_PAGE_MARGIN, rightMargin=_CARD_PAGE_MARGIN, topMargin=_CARD_PAGE_MARGIN, bottomMargin=_CARD_PAGE_MARGIN,
        title="Cartes de tactique de bataille",
    )
    doc.build([_tactic_cards_block(cards)], onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()


def _build_warscroll_cards_pdf(warscrolls: list[WarscrollData], regiment_notes: dict[str, str]) -> bytes | None:
    if not warscrolls:
        return None
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_CARD_PAGE_MARGIN, rightMargin=_CARD_PAGE_MARGIN, topMargin=_CARD_PAGE_MARGIN, bottomMargin=_CARD_PAGE_MARGIN,
        title="Profils d'unité (cartes)",
    )
    doc.build(build_warscroll_cards_flow(warscrolls, width=_UNIT_CARD_WIDTH, gap=_UNIT_CARD_GAP, regiment_notes=regiment_notes), onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    return buf.getvalue()


def _apply_display_fr(ws: WarscrollData, display: dict) -> WarscrollData:
    """Nom, mots-clés et profils d'arme traduits (`faction_rules_fr.json`,
    cf. `get_unit_display_overrides`) — une arme sans traduction garde son
    nom Wahapedia."""
    if not display:
        return ws
    changes: dict = {}
    if display.get("name_fr"):
        changes["name"] = display["name_fr"]
    if display.get("subtitle_fr"):
        changes["subtitle"] = display["subtitle_fr"]
    if display.get("keywords_fr"):
        changes["keywords"] = list(display["keywords_fr"])
    weapons_fr = {ability_join_key(w["wahapedia_name"]): w for w in display.get("weapons", [])}
    if weapons_fr:
        changes["weapons"] = [
            _dc_replace(w, name=fr["name"], abilities=fr.get("abilities", w.abilities))
            if (fr := weapons_fr.get(ability_join_key(w.name))) else w
            for w in ws.weapons
        ]
    return _dc_replace(ws, **changes)


def _mark_self_profile(ws: WarscrollData) -> WarscrollData:
    """Marque (`AbilityEntry.self_profile`) les aptitudes qui ne modifient
    que le profil de l'unité (`is_self_profile_modifier`), sur le texte et
    les noms d'arme Wahapedia d'origine : à appeler *avant* les correctifs
    français, qui traduisent « Cursed Lances » dans le texte de l'aptitude
    sans forcément traduire le nom de l'arme dans le profil."""
    names = [w.name for w in ws.weapons]
    return _dc_replace(ws, abilities=[
        _dc_replace(ab, self_profile=True) if is_self_profile_modifier(ab, names) else ab for ab in ws.abilities
    ])


def _with_section(abilities: list[AbilityEntry], section: str) -> list[AbilityEntry]:
    return [_dc_replace(ab, section=section) for ab in abilities]


def _warscroll_ability_pool(warscrolls: list[WarscrollData]) -> list[AbilityEntry]:
    """Aptitudes de tous les warscrolls (`fr-split`), chacune marquée du nom
    de son warscroll (`AbilityEntry.warscrolls`, badge dédié). Une même
    aptitude (nom, texte et timing identiques — texte d'ambiance en tête
    ignoré, jamais imprimé : ex. « Descendez-les » des Boltboyz et de la
    Killbow) portée par plusieurs unités de la liste —
    n'apparaît qu'une fois, avec un badge par unité, plutôt que répétée à
    l'identique dans la même phase. Ordre de première apparition conservé
    (celui des cartes : héros d'abord, cf. `_role_rank`). Les aptitudes de
    profil de l'unité elle-même (`is_self_profile_modifier`, ex. Stigmates de Guerre, Charge Empaleuse) n'y entrent pas :
    elles restent sur la carte du warscroll. Les aptitudes d'une
    manifestation (mot-clé d'unité `MANIFESTATION`) reçoivent un badge
    « Manifestation » (demande de l'utilisateur) : sorties de leur carte,
    rien d'autre ne les distingue d'une aptitude d'unité."""
    merged: dict[tuple, AbilityEntry] = {}
    for ws in warscrolls:
        abilities = ws.abilities
        if any(kw.strip().upper() == "MANIFESTATION" for kw in ws.keywords):
            abilities = tag_ability_origin(abilities, "Manifestation")
        for ab in abilities:
            if is_self_profile_modifier(ab, [w.name for w in ws.weapons]):
                continue
            key = (ab.name, _strip_flavor(ab.description), ab.condition, ab.ability_phase, ab.keywords, ab.points_type, ab.points)
            prev = merged.get(key)
            if prev is None:
                merged[key] = _dc_replace(ab, warscrolls=(ws.name,))
            elif ws.name not in prev.warscrolls:
                merged[key] = _dc_replace(prev, warscrolls=prev.warscrolls + (ws.name,))
    return list(merged.values())


@dataclass(frozen=True)
class _ChoiceCluster:
    """Sous-section de choix en tête du bandeau `phase` (demande de
    l'utilisateur) : la ou les aptitudes qui font *choisir* (`chooser_names`,
    dans cet ordre) suivies de toutes les options possibles (`keyword`,
    mot-clé d'aptitude Wahapedia ; vide quand les options sont décrites dans
    le texte même du choix, ex. Bénédictions de Khaine), pour voir d'un coup
    d'oeil, au moment du choix, tout ce qu'on peut prendre. Les options qui
    agissent dans une autre phase restent *aussi* à leur place (doublon
    voulu) ; celles déjà dans `phase` n'y sont pas dupliquées, l'appelant
    retire leur original. `moved_names` : aptitudes liées au choix sans en
    être une option, *déplacées* (pas dupliquées) juste après les
    `chooser_names` (ou à leur place s'ils y figurent aussi) — elles n'ont de
    sens qu'au moment du choix. Toute réaction à un `chooser_names`
    (`_is_choice_reaction`, ex. « Offrandes Pourpres » des Blood Hags aux
    Bénédictions de Khaine) est déplacée de la même façon. Noms en
    anglais (Wahapedia) et en français (patch `faction_rules_fr.json`),
    minuscules. `modes` : modes de rendu où la sous-section s'applique.
    `option_names` : options repérées par leur nom quand elles n'ont pas de
    mot-clé commun (ex. les 4 « Voué à … » de Slaves to Darkness), dans cet
    ordre, une seule par nom (la copie d'un warscroll identique est déjà
    fondue dans la règle d'armée, cf. `_fold_warscroll_copies`)."""

    category: str
    chooser_names: tuple[frozenset[str], ...]
    modes: frozenset[str]
    keyword: str = ""
    option_names: tuple[frozenset[str], ...] = ()
    moved_names: frozenset[str] = frozenset()
    phase: str = "Start of Turn"


_CHOICE_CLUSTERS = (
    # Flesh-eater Courts : « Royaume Délirant » fait choisir le Délire du tour
    # (il n'a lui-même pas le mot-clé "Delusion", d'où le repère par nom) ;
    # « Épicentre de l'Illusion » (Ushoran, ±1 au jet de délire) y est déplacé.
    _ChoiceCluster(
        category="delusion", keyword="delusion",
        chooser_names=(frozenset({"a kingdom deluded", "royaume délirant"}),),
        moved_names=frozenset({"epicentre of delusion", "épicentre de l'illusion"}),
        modes=frozenset({"fr-extended", *SPLIT_MODES}),
    ),
    # Blades of Khorne : « Des Crânes pour le Trône de Crânes » déverrouille
    # une aptitude de Dîme de Sang, « Trempés de Sang » réagit à ce
    # déverrouillage — puis toutes les aptitudes de Dîme de Sang, par coût.
    _ChoiceCluster(
        category="blood_tithe", keyword="blood tithe",
        chooser_names=(
            frozenset({"skulls for the skull throne", "des crânes pour le trône de crânes"}),
            frozenset({"blood-drenched", "trempés de sang"}),
        ),
        modes=frozenset({"fr-extended", *SPLIT_MODES}),
    ),
    # Daughters of Khaine : « Rites de Sang » (comment on en accomplit,
    # passif déplacé) puis « Bénédictions de Khaine », qui fait choisir la
    # bénédiction — en fin de tour, moment de ce choix ; les 7 bénédictions
    # sont dans son propre texte, pas d'aptitudes-options séparées.
    _ChoiceCluster(
        category="khaine_blessing",
        chooser_names=(
            frozenset({"blood rites", "rites de sang"}),
            frozenset({"blessings of khaine", "bénédictions de khaine"}),
        ),
        moved_names=frozenset({"blood rites", "rites de sang"}),
        modes=frozenset({"fr-extended", *SPLIT_MODES}),
        phase="End of Turn",
    ),
    # Slaves to Darkness : « Vocation au Chaos » (phase des héros) fait
    # choisir un vœu — les 4 « Voué à … » en options ; chacun reste aussi
    # dans la phase où il sert (demande de l'utilisateur).
    _ChoiceCluster(
        category="chaos_pledge",
        chooser_names=(frozenset({"pledge to chaos", "vocation au chaos"}),),
        option_names=(
            frozenset({"pledged to khorne", "voué à khorne"}),
            frozenset({"pledged to tzeentch", "voué à tzeentch"}),
            frozenset({"pledged to nurgle", "voué à nurgle"}),
            frozenset({"pledged to slaanesh", "voué à slaanesh"}),
        ),
        modes=frozenset({"fr-extended", *SPLIT_MODES}),
        phase="Hero Phase",
    ),
)


def _is_option(ab: AbilityEntry, spec: _ChoiceCluster) -> bool:
    if spec.keyword and _has_keyword(ab, spec.keyword):
        return True
    return any(ab.name.strip().lower() in names for names in spec.option_names)


def _fold_warscroll_copies(pool: list[AbilityEntry]) -> list[AbilityEntry]:
    """Une aptitude de warscroll identique à une règle d'armée du bassin
    (même nom, même texte hors ambiance, même timing — ex. « Voué à Nurgle »
    du Prince Démon, qui a déjà le vœu, et le trait de bataille) n'est pas
    répétée : la règle d'armée prend la pastille de l'unité."""
    def key(ab: AbilityEntry) -> tuple:
        return (ab.name.strip().lower(), _strip_flavor(ab.description), ab.condition, ab.ability_phase)

    army = {key(ab): i for i, ab in enumerate(pool) if not ab.warscrolls}
    out = list(pool)
    dropped: set[int] = set()
    for i, ab in enumerate(pool):
        j = army.get(key(ab)) if ab.warscrolls else None
        if j is None:
            continue
        out[j] = _dc_replace(out[j], warscrolls=out[j].warscrolls + tuple(w for w in ab.warscrolls if w not in out[j].warscrolls))
        dropped.add(i)
    return [ab for i, ab in enumerate(out) if i not in dropped]


def _has_keyword(ab: AbilityEntry, keyword: str) -> bool:
    return any(kw.strip().lower() == keyword for kw in (ab.keywords or "").split(","))


_DECLARED_ABILITY_RE = re.compile(r"you declared the\s*[‘'’\"]?%?\d*([^‘'’\"%]+)", re.IGNORECASE)


def _is_choice_reaction(ab: AbilityEntry, spec: _ChoiceCluster) -> bool:
    """Réaction (condition Wahapedia « Reaction: You declared the ‘<nom>’
    ability », toujours en anglais, le patch français ne la touche pas) à
    l'une des aptitudes de choix de `spec`."""
    m = _DECLARED_ABILITY_RE.search(ab.condition or "")
    return m is not None and any(m.group(1).strip().lower() in names for names in spec.chooser_names)


def _points_sort_key(ab: AbilityEntry) -> int:
    value = (ab.points or "").strip()
    return int(value) if value.isdigit() else 0


def _choice_cluster(pool: list[AbilityEntry], spec: _ChoiceCluster) -> list[AbilityEntry]:
    """Les aptitudes de la sous-section `spec` (cf. `_ChoiceCluster`), basculées
    dans sa phase et marquées de sa catégorie. Liste vide si le bassin ne
    porte aucune option (ni aucun choix, pour une sous-section sans
    `keyword`) — toute autre faction : aucun effet."""
    if spec.option_names:
        options = [
            first for names in spec.option_names
            if (first := next((ab for ab in pool if ab.name.strip().lower() in names), None)) is not None
        ]
    else:
        options = sorted((ab for ab in pool if spec.keyword and _has_keyword(ab, spec.keyword)), key=_points_sort_key)
    choosers = [ab for names in spec.chooser_names for ab in pool if ab.name.strip().lower() in names]
    if not (options if (spec.keyword or spec.option_names) else choosers):
        return []
    # un nom à la fois choisi et déplacé (« Rites de Sang ») garde sa place
    # parmi les `chooser_names`, sans doublon.
    moved = [
        ab for ab in pool
        if (ab.name.strip().lower() in spec.moved_names or _is_choice_reaction(ab, spec)) and ab not in choosers
    ]
    return [
        _dc_replace(ab, ability_phase=spec.phase, ability_category=spec.category)
        for ab in choosers + moved + options
    ]


def _turn_sides(ab: AbilityEntry, pool: list[AbilityEntry]) -> set[str]:
    """Tour(s) d'une aptitude (`ability_turn_sides`) ; une copie de sous-section
    de choix n'apparaît que dans un tour où l'aptitude qui fait choisir (la
    première de sa catégorie, cf. `_choice_cluster`) sert aussi : les
    « Voué à … » passifs ne doivent pas ouvrir une « Vocation au Chaos »
    (votre phase des héros) dans le tour adverse."""
    sides = set(ability_turn_sides(ab))
    if ab.ability_category in CHOICE_CATEGORIES:
        chooser = next(x for x in pool if x.ability_category == ab.ability_category)
        sides &= set(ability_turn_sides(chooser))
    return sides


def _apply_choice_clusters(pool: list[AbilityEntry], mode: str) -> list[AbilityEntry]:
    """Ajoute au bassin chaque sous-section de choix (`_CHOICE_CLUSTERS`)
    active pour `mode`, en retirant les originaux qu'elle remplace : options
    et `chooser_names` déjà dans sa phase (pas de doublon dans la même
    phase), `moved_names` et réactions au choix quelle que soit leur phase."""
    for spec in _CHOICE_CLUSTERS:
        if mode not in spec.modes:
            continue
        cluster = _choice_cluster(pool, spec)
        if not cluster:
            continue
        chooser_names = frozenset().union(*spec.chooser_names)
        phase_key = _classify_phase(cluster[0])
        pool = [
            ab for ab in pool
            if not ((_is_option(ab, spec) or ab.name.strip().lower() in chooser_names)
                    and _classify_phase(ab) == phase_key)
            and ab.name.strip().lower() not in spec.moved_names
            and not _is_choice_reaction(ab, spec)
        ] + cluster
    return pool


#: ordre de déroulé d'une partie (demande de l'utilisateur) : ces aptitudes
#: ouvrent le bandeau Déploiement, dans cet ordre, une par ligne
#: (`AbilityEntry.full_width`) — modes `fr-extended`/`fr-split`/
#: `fr-split-simple`.
_DEPLOY_ORDER = tuple(ability_join_key(n) for n in (
    "Placez le Champ de Bataille", "Déploiement de Terrain de Faction", "Déploiement de Régiment",
    "Déploiement d’Unité", "Souffler sur les Braises",
    # pas un déploiement, mais même modèle « étapes numérotées » : ouvre le
    # bandeau « Début de Round », en pleine largeur
    "Début de Round de Bataille",
    # `en-split-simple` (`generic_core_abilities_en.json`, `season_rules_en.json`)
    "Set Up the Battlefield", "Deploy Faction Terrain", "Deploy Regiment", "Deploy Unit", "Raising the Heat",
    "Start of Battle Round",
))


def _order_deploy(abilities: list[AbilityEntry]) -> list[AbilityEntry]:
    """Aptitudes de `_DEPLOY_ORDER` en tête, dans cet ordre et en pleine
    largeur ; les autres suivent dans leur ordre d'origine (tri stable)."""
    rank = {key: i for i, key in enumerate(_DEPLOY_ORDER)}
    out = sorted(abilities, key=lambda ab: rank.get(ability_join_key(ab.name), len(rank)))
    return [_dc_replace(ab, full_width=True) if ability_join_key(ab.name) in rank else ab for ab in out]


#: relance du jet de charge (ordre de base) — EN Wahapedia + FR MdG.
_CHARGE_REROLL_KEYS = frozenset(ability_join_key(n) for n in ("En Avant, vers la Victoire", "Forward to Victory"))


def _has_charge_keyword(ability: AbilityEntry) -> bool:
    # « Charge Rampage » : virgule manquante dans au moins une ligne Wahapedia
    return any("charge" in kw.lower().split() for kw in (ability.keywords or "").split(","))


#: ordres inapplicables dans le tour adverse (demande de l'utilisateur) :
#: « Au Pas de Course » réagit à une Course, qui ne se fait qu'à votre phase
#: de mouvement — retirés de la carte « Tour adverse » (modes split).
_MINE_ONLY_KEYS = frozenset(ability_join_key(n) for n in ("Au Pas de Course", "At the Double"))


_CASTER_LEVEL_RE = re.compile(r"^(WIZARD|PRIEST)\s*\(\d+\)$", re.IGNORECASE)


def _merge_unit_keywords(keywords: list[str], added) -> list[str]:
    """`keywords` + mots-clés `add_unit_keywords` ; un `WIZARD (N)`/`PRIEST (N)`
    ajouté *remplace* celui du même type déjà porté (ex. Bâton des Marais
    *Appliqué* : Sorcier (1) → « WIZARD (2) »), au lieu d'un second badge."""
    out = list(keywords)
    for kw in added:
        m = _CASTER_LEVEL_RE.match(kw.strip())
        if m:
            out = [k for k in out if not ((c := _CASTER_LEVEL_RE.match(k.strip())) and c.group(1).upper() == m.group(1).upper())]
        if kw not in out:
            out.append(kw)
    return out


def _drop_enemy_charge_reroll(enemy: list[AbilityEntry]) -> list[AbilityEntry]:
    """Retire « En Avant, vers la Victoire » de la carte « Tour adverse »
    (modes split, demande de l'utilisateur) sauf si une autre aptitude de
    cette carte porte le mot-clé Charge : sinon la seule unité qui peut y
    charger est celle qui fait une Contre-Charge, déjà un ordre — elle ne
    peut pas en recevoir un second, la relance prête donc à confusion."""
    if any(_has_charge_keyword(ab) for ab in enemy if ability_join_key(ab.name) not in _CHARGE_REROLL_KEYS):
        return enemy
    return [ab for ab in enemy if ability_join_key(ab.name) not in _CHARGE_REROLL_KEYS]


def _tactic_special_rules(parsed, tactic_cards) -> list[AbilityEntry]:
    """Règle spéciale de chaque carte de tactique citée (ex. le repaire
    d'« Assaut Flamboyant ») en aptitude du bandeau Déploiement : elle se joue
    après le déploiement, avant de déterminer qui a le premier tour, alors que
    la carte elle-même n'est lue qu'en fin de tour (demande de l'utilisateur,
    tous modes). Texte vérbatim de la carte."""
    out = []
    for card_name in parsed.battle_tactic_cards:
        card = find_tactic_card(tactic_cards, card_name)
        if card is None or not card.special_rule:
            continue
        out.append(AbilityEntry(
            name=f"{card.name_en}: Special Rule" if english_labels() else f"{card.title_fr} : Règle Spéciale",
            description=card.special_rule, legend="",
            condition="Deployment Phase", ability_phase="Deployment Phase", full_width=True,
        ))
    return out


#: coût d'une option payante en fin de sous-ligne ` • ... - (N) Points`.
_PAID_OPTION_RE = re.compile(r"\((\d+)\)\s*points?\s*$", re.IGNORECASE)


def _relabel_options(parsed, simplifications):
    """Page de garde `fr-split-simple` : options ` • ...` renommées selon
    `RosterSimplifications.option_labels` (copie, `parsed` reste intact pour
    la résolution des optimisations)."""
    if simplifications is None or not simplifications.option_labels:
        return parsed
    labels = simplifications.option_labels
    regiments = [
        _dc_replace(reg, units=[
            _dc_replace(u, options=[labels.get(o, o) for o in u.options]) for u in reg.units
        ])
        for reg in parsed.regiments
    ]
    return _dc_replace(parsed, regiments=regiments)


def _apply_unit_aliases(parsed, simplifications):
    """`RosterSimplifications.unit_aliases` : l'entrée de la liste dont le nom
    et les options correspondent prend le nom affiché (copie de `parsed`).
    Renvoie aussi `{nom affiché -> nom d'unité}`, pour retrouver son warscroll."""
    if simplifications is None or not simplifications.unit_aliases:
        return parsed, {}
    sources: dict[str, str] = {}
    regiments = []
    for reg in parsed.regiments:
        units = []
        for u in reg.units:
            for alias, (unit, options) in simplifications.unit_aliases.items():
                if u.name == unit and set(options) <= set(u.options):
                    u = _dc_replace(u, name=alias)
                    sources[alias] = unit
                    break
            units.append(u)
        regiments.append(_dc_replace(reg, units=units))
    return _dc_replace(parsed, regiments=regiments), sources


def _apply_section_order(pool: list[AbilityEntry], section_order: dict[str, tuple[str, ...]]) -> list[AbilityEntry]:
    """`section_order` (`roster_simplifications.json`) : les sous-sections
    nommées passent en tête de leur bandeau de phase, dans l'ordre donné
    (rang négatif, avant « Règles de base »)."""
    if not section_order:
        return pool
    out = []
    for ab in pool:
        titles = section_order.get(_classify_phase(ab), ())
        title = ability_section(ab)
        if title in titles:
            ab = _dc_replace(ab, section_rank=titles.index(title) - len(titles))
        out.append(ab)
    return out


def _collapse_alias_pills(pool: list[AbilityEntry], alias_sources: dict[str, str]) -> list[AbilityEntry]:
    """Une aptitude portée à la fois par un alias (`unit_aliases`) et par son
    unité d'origine ne garde que l'unité d'origine (« Verminlord
    Warbringer » couvre les deux Warbringers) — demande de l'utilisateur."""
    out = []
    for ab in pool:
        names = ab.warscrolls or ()
        kept = tuple(n for n in names if not (n in alias_sources and alias_sources[n] in names))
        out.append(ab if kept == tuple(names) else _dc_replace(ab, warscrolls=kept))
    return out


def _drop_identical_alias_cards(warscrolls: list[WarscrollData], alias_sources: dict[str, str]) -> list[WarscrollData]:
    """Modes split (demande de l'utilisateur) : une fois les aptitudes parties
    sur les cartes de tour, la carte d'un alias (`unit_aliases`, ex.
    « Warbringer riche et outillé ») identique à celle de son unité d'origine
    — mêmes caractéristiques, armes, mots-clés et aptitudes restées — n'est
    plus qu'un doublon : retirée, l'alias ne sert plus qu'aux pastilles des
    cartes de tour."""
    by_name = {ws.name: ws for ws in warscrolls}

    def same(alias: WarscrollData, base: WarscrollData) -> bool:
        return _dc_replace(alias, name=base.name, subtitle=base.subtitle) == base

    return [
        ws for ws in warscrolls
        if not (ws.name in alias_sources and alias_sources[ws.name] in by_name and same(ws, by_name[alias_sources[ws.name]]))
    ]


def default_output_path(
    list_path: str | Path,
    mode: RosterMode,
    lists_dir: str | Path = DEFAULT_LISTS_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Chemin de sortie par défaut : `<output_dir>/<équipe>/<liste>/<liste> (<mode>).pdf`.

    L'équipe est le premier sous-dossier de `lists_dir` contenant la liste ;
    une liste hors de `lists_dir` (ou posée à sa racine) n'a pas de dossier
    d'équipe et va directement sous `<output_dir>/<liste>/`.
    """
    list_path = Path(list_path).resolve()
    out_dir = Path(output_dir)
    try:
        rel = list_path.relative_to(Path(lists_dir).resolve())
    except ValueError:
        rel = None
    if rel is not None and len(rel.parts) > 1:
        out_dir = out_dir / rel.parts[0]
    stem = list_path.stem.strip()
    return out_dir / stem / f"{stem} ({_MODE_FILE_LABEL[mode]}).pdf"


def build_roster_pdf(
    list_path: str | Path,
    out_path: str | Path | None = None,
    index_path: str | Path | None = None,
    battletome_dir: str | Path | None = None,
    wahapedia_dir: str | Path | None = None,
    mode: RosterMode = "hybrid",
    faction_rules_fr_path: str | Path | None = None,
    generic_core_abilities_path: str | Path | None = None,
) -> RosterPdfResult:
    list_path = Path(list_path)
    parsed = parse_list_file(list_path)
    # `fr-split-simple` : simplifications propres à cette liste (cf.
    # `roster_simplifications.py`) — aptitudes de synthèse ajoutées à leur
    # unité, aptitudes qu'elles résument retirées partout (warscrolls,
    # optimisations, règles de faction, manifestations).
    simplifications = (
        load_roster_simplifications(list_path.stem.strip(), lang="en" if mode == "en-split-simple" else "fr")
        if mode in SIMPLE_MODES else None
    )
    parsed, alias_sources = _apply_unit_aliases(parsed, simplifications)
    # avant toute carte : la légende des pastilles (couverture, construite
    # en dernier) ne liste que les familles construites pour ce PDF
    reset_drawn_pills()
    index = load_index(index_path) if index_path is not None else load_index()
    # Fichier vide (`{"factions": {}}`) tant qu'aucune faction n'est curée —
    # lecture à froid sans coût notable, inutile de la conditionner à `mode`
    # (`_fr_patch` ignore `frf` lui-même hors `fr`/`fr-extended`). Même
    # convention `*_path` optionnel que `index_path`, pour les tests.
    frf = load_faction_rules_fr(faction_rules_fr_path) if faction_rules_fr_path is not None else load_faction_rules_fr()
    if mode == "en-split-simple":
        # textes officiels anglais de l'app (même schéma que le français),
        # prioritaires sur Wahapedia
        frf = load_faction_rules_fr(DEFAULT_APP_RULES_EN_FILE)
    faction_index = index.factions.get(parsed.base_faction)
    bt_path = (
        battletome_path(index, parsed.base_faction, battletome_dir)
        if battletome_dir is not None
        else battletome_path(index, parsed.base_faction)
    )
    wh = load_wahapedia(wahapedia_dir) if wahapedia_dir is not None else load_wahapedia()
    # une seule fois par PDF : cf. `warscroll_card._FACTION_KEYWORDS` pour
    # pourquoi ce n'est pas plutôt passé en paramètre à chaque appel de rendu.
    set_faction_specific_keywords(wh.faction_specific_keywords() if wh.available else frozenset())
    set_french_keywords(mode in FR_MODES)
    set_bold_set_up(mode in FR_MODES or mode in SIMPLE_MODES)
    set_french_weapon_tags(mode in FR_NAME_MODES)
    set_english_labels(mode == "en-split-simple")  # cf. `english` plus bas
    english = mode == "en-split-simple"
    tactic_cards = load_tactic_cards(en_path=DEFAULT_TACTIC_CARDS_EN_FILE if english else None)
    renown_prefix = parsed.faction.split("|", 1)[1].strip() if "|" in parsed.faction else None

    # Profils d'unité : rendus en carte maison (warscroll_card.py) à partir
    # de data/wahapedia/*.csv plutôt que copiés depuis le battletome — cf.
    # demande explicite de remplacer les pages PDF par les cartes pour les
    # unités. Wahapedia couvre la totalité du contenu AoS4 (bien plus large
    # que les 2 battletomes actuellement indexés en français), donc plus de
    # repli sur `find_pages`/copie de page pour une unité : introuvable ici
    # = réellement non trouvé, signalé comme tel plutôt que masqué par un
    # rendu différent.
    matched: list[str] = []
    unmatched_units: list[str] = []
    warscrolls_by_name: dict[str, WarscrollData] = {}
    wahapedia_used: list[str] = []
    for name in parsed.unique_unit_names():
        # `prefer_faction` : certaines unités d'armée de renom (ex.
        # "Bloodletters" pour "Legion of the First Prince") existent sous 2
        # lignes Wahapedia homonymes — la version de base (autre faction,
        # sans restriction) et une variante `parsed.base_faction`-only
        # ("This unit can only be taken in a <armée de renom> Army of
        # Renown", stats différentes) — sans indice de faction,
        # `find_warscroll` retombait sur la première ligne du CSV (la
        # version de base, erronée ici), signalé par l'utilisateur.
        ws = wh.find_warscroll(alias_sources.get(name, name), prefer_faction=parsed.base_faction) if wh.available else None
        if ws is None and wh.available and renown_prefix and name.startswith(renown_prefix):
            # les unités d'une armée de renom sont listées préfixées par son
            # nom (ex. "Legion of the First Prince Bloodletters") mais leur
            # warscroll Wahapedia est enregistré sous son nom nu ("Bloodletters").
            ws = wh.find_warscroll(name[len(renown_prefix):].strip(), prefer_faction=parsed.base_faction)
        if ws is not None:
            warscrolls_by_name[name] = ws
            matched.append(name)
        else:
            unmatched_units.append(name)

    # Aptitudes propres à chaque unité : correctifs/additions vérbatim
    # français (`data/json/faction_rules_fr.json`, cf. `faction_rules_fr.py`) —
    # uniquement en `fr`/`fr-extended` (`_fr_patch` renvoie `entries` tel
    # quel sinon), une unité non curée gardant ses aptitudes Wahapedia (EN)
    # inchangées.
    if mode in PATCH_MODES:
        for name, ws in list(warscrolls_by_name.items()):
            # Curé sous la faction PROPRE du warscroll résolu (`ws.faction_id`),
            # pas `parsed.base_faction` : une unité amenée par un Régiment de
            # Renom (ex. Skarbrand/Slaughterpriest/Bloodreavers/Skullreapers
            # via un Régiment Blades of Khorne cité par une liste Slaves to
            # Darkness) est curée sous sa faction d'origine, jamais sous celle
            # de la liste qui la cite — même raisonnement que la résolution du
            # Régiment de Renom lui-même ci-dessus. Repli sur `parsed.base_faction`
            # si `faction_id` n'est pas résolu (id manquant/inconnu), identique
            # au comportement précédent pour toute unité native de la liste.
            unit_faction = wh.faction_name(ws.faction_id) or parsed.base_faction
            ws = _mark_self_profile(ws)
            overrides = get_unit_ability_overrides(frf, unit_faction, name, ws.name)
            if overrides:
                ws = _dc_replace(ws, abilities=apply_fr_overrides(ws.abilities, overrides))
            warscrolls_by_name[name] = _apply_display_fr(ws, get_unit_display_overrides(frf, unit_faction, name, ws.name))
    elif mode in FR_NAME_MODES:
        # `hybrid` : noms seulement (sous-titre français, armes françaises),
        # le texte des aptitudes reste celui de Wahapedia.
        for name, ws in list(warscrolls_by_name.items()):
            unit_faction = wh.faction_name(ws.faction_id) or parsed.base_faction
            warscrolls_by_name[name] = _apply_display_fr(ws, get_unit_display_overrides(frf, unit_faction, name, ws.name))

    # Armée de Renom : ses propres règles (Faction_abilities.csv, groupées
    # par catégorie) remplacent tout ou partie de celles de la faction de
    # base — calculé *avant* `_resolve_rules` pour pouvoir lui passer les
    # catégories à omettre côté battletome (cf. `_AOR_REPLACES`).
    renown_army: tuple[str, dict[str, list[AbilityEntry]]] | None = None
    renown_categories: frozenset[str] = frozenset()
    if renown_prefix and wh.available:
        grouped = wh.find_renown_army_rules(renown_prefix)
        if grouped:
            renown_army = (renown_prefix, grouped)
            renown_categories = frozenset(grouped)

    battletome_rules, generic_manifestation_sections, tactic_sections, wahapedia_lore_blocks, rules_unmatched, lore_wahapedia_used, rule_card_labels, rule_ability_pool, manifestation_warscrolls = _resolve_rules(
        parsed, faction_index, index, wh, tactic_cards, renown_categories, mode=mode, frf=frf,
        renown_army=renown_army, tactic_card_width=_TACTIC_CARD_WIDTH,
    )
    wahapedia_used.extend(lore_wahapedia_used)

    if renown_army is not None:
        renown_name = renown_army[0]
        if f"Armée de Renom — {renown_name}" in rule_card_labels:
            # curation vérbatim française complète (`_renown_army_pool`,
            # `fr`/`fr-extended` seulement) : déjà rendu sur la carte de
            # règles fusionnée par `_resolve_rules`, ne doit plus apparaître
            # dans l'annexe anglaise ni y être rattaché par l'appelant.
            renown_army = None
        else:
            wahapedia_used.append(f"{renown_name} — Army of Renown Rules (EN, Wahapedia)")
        if "Spell Lore" in renown_categories and any(u.startswith("Domaine de sorts") for u in rules_unmatched):
            rules_unmatched = [u for u in rules_unmatched if not u.startswith("Domaine de sorts")]

    # Un Régiment de Renom natif d'une faction (PDF officiel propre, cf.
    # `faction_rules_fr.py`) peut avoir ses aptitudes vérbatim françaises
    # (`get_regiment_of_renown_overrides`, `fr`/`fr-extended` seulement) —
    # appliquées ici, *avant* le partage single/grouped ci-dessous, pour que
    # les deux chemins (aptitude repliée sur une unité, ou pool fusionné)
    # héritent du texte déjà patché sans double logique. `regiment_curated`
    # retient quels régiments l'ont reçu, pour ne compter ni dans
    # `wahapedia_used` (pas un repli anglais) ni dans l'annexe Wahapedia.
    regiments_of_renown: list[tuple[str, RegimentOfRenownData | None]] = []
    regiment_curated: set[str] = set()
    for ror in parsed.regiments_of_renown:
        ror_data = wh.find_regiment_of_renown(ror.name) if wh.available else None
        if ror_data is not None:
            if mode in PATCH_MODES:
                # Curé sous la faction d'ORIGINE du Régiment de Renom
                # (`RegimentOfRenownData.faction_id`), pas `parsed.base_faction`
                # (la faction de la liste qui le cite) : plusieurs Régiments
                # (ex. Blades of Khorne "The Exiled One"/"The Red Revelation")
                # sont explicitement exclus de leur propre liste d'inclusion
                # (Wahapedia `Warscrolls_RoRfactions.csv`) — seules d'autres
                # factions Chaos peuvent les citer, donc `parsed.base_faction`
                # ne correspondrait jamais à la clé sous laquelle ce Régiment
                # est curé. Repli sur `parsed.base_faction` si la faction
                # d'origine n'est pas résolue (id manquant/inconnu).
                origin_faction = wh.faction_name(ror_data.faction_id) or parsed.base_faction
                overrides = get_regiment_of_renown_overrides(frf, origin_faction, ror_data.name)
                if overrides:
                    ror_data = _dc_replace(ror_data, abilities=apply_fr_overrides(ror_data.abilities, overrides))
                    regiment_curated.add(ror.name)
            if ror.name not in regiment_curated:
                wahapedia_used.append(f"Regiment of Renown : {ror.name} (EN, Wahapedia)")
        else:
            rules_unmatched.append(f"Regiment of Renown : {ror.name}")
        regiments_of_renown.append((ror.name, ror_data))

    # Un Regiment of Renown à une seule unité membre n'a rien de distinct de
    # cette unité pour le lecteur : son aptitude propre rejoint directement
    # sa carte (petite note de provenance + aptitude en plus) plutôt qu'une
    # section « Regiment of Renown » à part dans l'annexe. Un Régiment à
    # plusieurs membres curé en français (`regiment_curated`) rejoint le pool
    # d'aptitudes fusionné (`regiment_ability_pool`, badge d'origine dédié)
    # au lieu de l'annexe anglaise Wahapedia — seul un Régiment non curé (ou
    # curé mais résolu en mode `hybrid`/`en`) tombe encore dans
    # `grouped_regiments`.
    single_unit_ror_extras: dict[str, tuple[str, list[AbilityEntry]]] = {}
    grouped_regiments: list[tuple[str, RegimentOfRenownData | None]] = []
    regiment_ability_pool: list[AbilityEntry] = []
    for ror_name, ror_data in regiments_of_renown:
        member = _strip_all_tags(ror_data.composition[0]) if ror_data and len(ror_data.composition) == 1 else None
        if member is not None and member in warscrolls_by_name:
            single_unit_ror_extras[member] = (ror_name, ror_data.abilities)
        elif ror_name in regiment_curated:
            regiment_ability_pool.extend(tag_ability_origin(ror_data.abilities, f"Régiment de Renom : {ror_name}"))
        else:
            grouped_regiments.append((ror_name, ror_data))

    # Optimisations (Traits Héroïques/Artefacts de Pouvoir/Traits
    # Monstrueux/catégories saisonnières propres à la faction, ex. StD
    # "Brands of the Dark Gods"/"Ensorcelled Banners") : choisies une seule
    # fois pour toute la liste puis rattachées à une seule unité — jamais
    # montrées en bloc générique (cf. `_resolve_rules`, qui marque désormais
    # `heroic_traits_artefacts` couvert sans jamais l'ajouter au pool), une
    # optimisation non choisie n'apparaissant nulle part, comme une unité non
    # choisie. Résolues par correspondance de nom sur les options ` • ... `
    # de chaque unité (`WahapediaLookup.find_unit_enhancement`) et rattachées
    # à sa carte plus bas — même mécanisme que l'aptitude d'un Regiment of
    # Renown à une seule unité membre (`single_unit_ror_extras` ci-dessus).
    unit_enhancements: dict[str, list[AbilityEntry]] = {}
    enhancements_included: list[str] = []
    if wh.available:
        # Correctifs vérbatim français pour cette catégorie (pas de `scope` —
        # toutes les optimisations de la faction, comme côté Wahapedia) :
        # récupérés une seule fois, appliqués ci-dessous par nom sur chaque
        # optimisation trouvée (même mécanisme que `_fr_patch`, appliqué ici
        # à une entrée unique plutôt qu'un pool entier).
        heroic_overrides = (
            get_faction_category_overrides(frf, parsed.base_faction, "heroic_traits_artefacts")
            if mode in PATCH_MODES else []
        )
        # Cf. `_find_pledge_battle_trait` : unités StD qui commencent la
        # bataille déjà marquées (Prince Démon, porteur de Bannière
        # Ensorcelée) — la Trait de Bataille "Voué à <Dieu>" correspondante
        # leur est rattachée en plus, ci-dessous après la boucle.
        pledged_gods: dict[str, set[str]] = {}
        for regiment in parsed.regiments:
            for unit in regiment.units:
                if unit.name not in warscrolls_by_name:
                    continue
                for option in unit.options:
                    match = wh.find_unit_enhancement(parsed.base_faction, option)
                    if match is not None:
                        label, entry = match
                        entry_name = entry.name.strip().upper()
                        if heroic_overrides:
                            matching = [o for o in heroic_overrides if ability_join_key(o.get("wahapedia_name")) == ability_join_key(entry_name)]
                            if matching:
                                entry = apply_fr_overrides([entry], matching)[0]
                        unit_enhancements.setdefault(unit.name, []).extend(tag_ability_origin([entry], label))
                        enhancements_included.append(f"{label} : {entry.name} → {unit.name}")
                        god = _BANNER_PLEDGED_GOD.get(entry_name)
                        if god:
                            pledged_gods.setdefault(unit.name, set()).add(god)
                        continue
                    pledge_match = _PLEDGE_OPTION_RE.search(option)
                    if pledge_match:
                        pledged_gods.setdefault(unit.name, set()).add(pledge_match.group(1).upper())
        for unit_name, gods in pledged_gods.items():
            for god in sorted(gods):
                pledge_entry = _find_pledge_battle_trait(wh, frf, parsed.base_faction, mode, god)
                if pledge_entry is None:
                    continue
                unit_enhancements.setdefault(unit_name, []).extend(tag_ability_origin([pledge_entry], "Trait de Bataille"))
                enhancements_included.append(f"Trait de Bataille : {pledge_entry.name} → {unit_name}")

    # options payantes (« Brand of Unbreakable Bonds - (10) Points ») :
    # la carte affiche « base+N pts » (demande de l'utilisateur), le prix
    # Wahapedia ne les comptant pas.
    paid_options: dict[str, int] = {}
    for regiment in parsed.regiments:
        for unit in regiment.units:
            cost = sum(int(m.group(1)) for opt in unit.options if (m := _PAID_OPTION_RE.search(opt)))
            if cost:
                paid_options.setdefault(unit.name, cost)

    warscrolls_for_cards: list[WarscrollData] = []
    regiment_notes: dict[str, str] = {}
    for name in matched:
        ws = warscrolls_by_name[name]
        if name in alias_sources:
            # carte et pastilles d'unité sous le nom affiché, le nom du
            # warscroll en sous-titre
            ws = _dc_replace(ws, name=name, subtitle=ws.name)
        if name in paid_options and ws.points:
            ws = _dc_replace(ws, points=f"{ws.points}+{paid_options[name]}")
        extras = list(unit_enhancements.get(name, []))
        if simplifications is not None:
            extras += simplifications.unit_abilities.get(name, [])
        if name in single_unit_ror_extras:
            ror_name, ror_extras = single_unit_ror_extras[name]
            extras += ror_extras
            regiment_notes[ws.name] = f"Regiment of Renown — {ror_name}"
        if extras:
            ws = _dc_replace(ws, abilities=list(ws.abilities) + extras)
        if simplifications is not None:
            ws = _dc_replace(
                ws, abilities=[simplifications.rewrite_unit(name, ab) for ab in ws.abilities],
                keywords=_merge_unit_keywords(ws.keywords, simplifications.unit_keywords.get(name, ())),
                weapons=[
                    _dc_replace(w, **simplifications.unit_weapons.get(name, {}).get(w.name, {})) for w in ws.weapons
                ],
                **simplifications.unit_stats.get(name, {}),
            )
        warscrolls_for_cards.append(ws)
    # Ordre des cartes : Héros (toute base confondue) d'abord, puis
    # Infanterie/Cavalerie/Bêtes/Monstres/Machines de Guerre — demande
    # explicite de l'utilisateur ; tri stable, l'ordre relatif au sein d'un
    # même rang reste celui de la liste (régiment du général, puis régiment
    # 1, 2...). Cf. `_role_rank`.
    warscrolls_for_cards.sort(key=lambda ws: _role_rank(ws.role))
    if simplifications is not None and simplifications.warscroll_order:
        order = [ability_join_key(n) for n in simplifications.warscroll_order]
        warscrolls_for_cards.sort(
            key=lambda ws: order.index(ability_join_key(ws.name)) if ability_join_key(ws.name) in order else len(order),
        )
    # les manifestations invocables par le domaine choisi rejoignent la même
    # feuille de cartes, à la suite des unités de la liste — ce sont des
    # profils complets au même titre qu'une unité, juste optionnels/
    # invoqués en jeu plutôt que déployés d'entrée. Leurs aptitudes reçoivent
    # les mêmes correctifs vérbatim français que les unités de la liste
    # (`units.<manifestation>` de `faction_rules_fr.json`), cherchés sous la
    # faction propre du warscroll puis sous celle de la liste — une
    # manifestation partagée (ex. Foot of Gork, Mâchefers *et* Kruelboyz)
    # n'existe qu'en un exemplaire résolu par `find_warscroll`.
    if mode in PATCH_MODES:
        patched_manifestations = []
        for ws in manifestation_warscrolls:
            ws = _mark_self_profile(ws)
            overrides = (
                get_unit_ability_overrides(frf, wh.faction_name(ws.faction_id) or parsed.base_faction, ws.name)
                or get_unit_ability_overrides(frf, parsed.base_faction, ws.name)
            )
            if overrides:
                ws = _dc_replace(ws, abilities=apply_fr_overrides(ws.abilities, overrides))
            display = (
                get_unit_display_overrides(frf, wh.faction_name(ws.faction_id) or parsed.base_faction, ws.name)
                or get_unit_display_overrides(frf, parsed.base_faction, ws.name)
            )
            patched_manifestations.append(_apply_display_fr(ws, display))
        manifestation_warscrolls = patched_manifestations
    elif mode in FR_NAME_MODES:
        manifestation_warscrolls = [
            _apply_display_fr(ws, (
                get_unit_display_overrides(frf, wh.faction_name(ws.faction_id) or parsed.base_faction, ws.name)
                or get_unit_display_overrides(frf, parsed.base_faction, ws.name)
            ))
            for ws in manifestation_warscrolls
        ]
    warscrolls_for_cards.extend(manifestation_warscrolls)
    if simplifications is not None:
        warscrolls_for_cards = [
            _dc_replace(ws, abilities=[simplifications.rewrite(ab) for ab in ws.abilities if not simplifications.is_removed(ab)])
            for ws in warscrolls_for_cards
        ]
        rule_ability_pool = [simplifications.rewrite(ab) for ab in rule_ability_pool if not simplifications.is_removed(ab)]
        regiment_ability_pool = [
            simplifications.rewrite(ab) for ab in regiment_ability_pool if not simplifications.is_removed(ab)
        ]

    # Règles de Saison 2026-27 / Aptitudes Génériques / règles de faction
    # (`rule_ability_pool`, déjà résolu par `_resolve_rules`) rejoignent
    # toutes le *même* bassin puis une seule carte triée par bandeau de
    # phase — demande explicite de l'utilisateur : un joueur qui consulte
    # cette carte raisonne "je suis en phase des héros, qu'est-ce que j'ai le
    # droit de faire ?", pas par type de règle ; les séparer sur 3 cartes
    # (Saison / Générique / Faction, chacune déjà triée par phase en interne)
    # l'obligeait à vérifier 3 fois la même phase pour la même question.
    # `tag_ability_origin` pose un badge d'origine par source ("Saison"/
    # "MdG"/le nom de faction ou d'Armée de Renom) pour rester
    # identifiable malgré la fusion.
    #
    # Exception demandée par l'utilisateur pour Seraphon : "Le Grand
    # Dessein"/"Faites Avancer le Grand Dessein" choisissent/activent les 4
    # Astérismes (mot-clé Wahapedia "Asterism"), qui ont chacun leur propre
    # `ability_phase` réel et finissent donc éparpillés sur plusieurs pages
    # de la grande carte fusionnée (trop de contenu Saison/MdG partage les
    # mêmes bandeaux "Déploiement"/"Début de round" pour que les 6 tiennent
    # ensemble sur une page, même avec le bandeau virtuel "asterism" de
    # `warscroll_card._PHASE_ORDER`). Plutôt que de retravailler le tri
    # partagé par *toute* carte fusionnée (régression potentielle pour
    # n'importe quelle autre faction), ces 6 aptitudes ("Traits de Bataille")
    # rejoignent leur propre petite carte à part (cf. `rule_cards` plus bas)
    # — assez courte pour tenir sur une seule page sans jamais se disputer
    # l'espace avec le reste. Déclenché uniquement par la présence du
    # mot-clé "Asterism" (propre à Seraphon) : aucun effet pour aucune autre
    # faction/liste.
    battle_traits_entries = [
        ab for ab in rule_ability_pool
        if any(kw.strip().lower() == "traits de bataille" for kw in (ab.keywords or "").split(","))
    ]
    separate_battle_traits_card = None
    if battle_traits_entries and any("asterism" in (ab.keywords or "").lower() for ab in rule_ability_pool):
        rule_ability_pool = [ab for ab in rule_ability_pool if ab not in battle_traits_entries]
        separate_battle_traits_card = render_rule_card(
            tr("Traits de Bataille"), battle_traits_entries, width=_RULE_CARD_WIDTH, subtitle=parsed.base_faction,
        )

    # `section` : sous-section de la carte en mode `fr-split` (règles de base
    # = Saison/MdG, règles d'armée = tout le reste hors warscrolls), cf.
    # `warscroll_card.ability_section` ; ignoré par les autres modes.
    combined_pool = _with_section(list(rule_ability_pool) + regiment_ability_pool, SECTION_ARMY)
    season_entries = load_season_rules(en_path=DEFAULT_SEASON_RULES_EN_FILE if english else None)
    if simplifications is not None:
        season_entries = [ab for ab in season_entries if not simplifications.is_removed(ab)]
    # les Aptitudes Génériques (plus bas) s'insèrent ici, *avant* la Saison :
    # dans un bandeau, les règles de base du jeu (ex. « Placez le Champ de
    # Bataille », en tête du Déploiement) précèdent celles de la saison.
    generic_insert_at = len(combined_pool)
    if season_entries:
        # « Saison » dit que la règle change chaque saison ; sa source (badge
        # source, cf. `warscroll_card._TEXT_SOURCE_KEYWORDS`) est le MdG
        combined_pool.extend(_with_section(
            tag_ability_origin(tag_ability_origin(season_entries, "Saison"), "MdG"), SECTION_BASE,
        ))

    # Aptitudes Génériques (modes `fr-extended`/`fr-split`) : superset complet
    # de `MdG26-27 Aptitudes.pdf`, pas seulement les 4 règles de saison — cf.
    # `generic_core_abilities.py`. Fichier vide tant que non curé (liste
    # vide, pas d'erreur) : le mode se comporte alors comme `fr` sans rien
    # ajouter au bassin. `fr-split` les inclut aussi : son objet est de
    # répondre à « qu'ai-je le droit de faire dans cette phase de ce tour ? »,
    # aptitudes de base du jeu comprises (ex. Redéploiement en phase de
    # mouvement adverse).
    # « Musicien »/« Porte-Étendard »/« Champion » n'y restent que si une unité de la
    # liste en a (`requires_unit_keyword`, cf. `generic_core_abilities.py`).
    generic_entries: list[AbilityEntry] = []
    if mode in ("fr-extended", *SPLIT_MODES):
        unit_keywords = frozenset(kw.strip().upper() for ws in warscrolls_by_name.values() for kw in ws.keywords)
        # `en-split-simple` : verbatim Core Rules anglais par-dessus (cf.
        # `generic_core_abilities.py`), le français reste pour le reste.
        en_path = DEFAULT_GENERIC_CORE_ABILITIES_EN_FILE if english else None
        generic_entries = (
            load_generic_core_abilities(generic_core_abilities_path, unit_keywords=unit_keywords, en_path=en_path)
            if generic_core_abilities_path is not None
            else load_generic_core_abilities(unit_keywords=unit_keywords, en_path=en_path)
        )
        if simplifications is not None:
            generic_entries = [ab for ab in generic_entries if not simplifications.is_removed(ab)]
        if generic_entries:
            # source « MdG » sauf pour celles déjà sourcées « Core Rules »
            generic_tagged = _with_section([
                ab if CORE_RULES_SOURCE.lower() in ab.keywords.lower() else tag_ability_origin([ab], "MdG")[0]
                for ab in generic_entries
            ], SECTION_BASE)
            # les règles de saison du Déploiement (ex. « Souffler sur les
            # Braises ») suivent directement « Placez le Champ de Bataille »,
            # qui désigne attaquant et défenseur dont elles dépendent (demande
            # de l'utilisateur), plutôt que la fin des aptitudes génériques.
            anchor = next(
                (i + 1 for i, ab in enumerate(generic_tagged)
                 if ab.name in ("Placez le Champ de Bataille", "Set Up the Battlefield")), None,
            )
            if anchor is not None:
                season_tail = combined_pool[generic_insert_at:]
                season_deploy = [ab for ab in season_tail if ab.ability_phase == "Deployment Phase"]
                combined_pool[generic_insert_at:] = [ab for ab in season_tail if ab not in season_deploy]
                generic_tagged[anchor:anchor] = season_deploy
            combined_pool[generic_insert_at:generic_insert_at] = generic_tagged

    combined_pool.extend(_with_section(
        tag_ability_origin(tag_ability_origin(_tactic_special_rules(parsed, tactic_cards), "Tactique"), "MdG"), SECTION_BASE,
    ))

    # Mode `fr-split` : les aptitudes des warscrolls quittent leur carte
    # d'unité (qui ne garde que stats + armes + mots-clés) pour rejoindre le
    # bassin de règles, chacune marquée du nom de son/ses warscroll(s)
    # (`_warscroll_ability_pool`), puis tout le bassin est réparti en 3
    # cartes « Déploiement » / « Mon tour » / « Tour adverse »
    # (`ability_turn_sides`) — une aptitude utilisable dans les 2 tours
    # figure sur les 2 cartes de tour. Chaque carte démarre sur sa propre page
    # (`_build_rule_cards_pdf` séparé), bandeaux dans l'ordre
    # `SPLIT_PHASE_ORDER`. « N'importe quelle phase » (vert) a sa propre
    # carte, juste après « Déploiement », plutôt que d'être dupliqué sur les
    # 2 cartes de tour (demande explicite de l'utilisateur). Les cartes de tactique de bataille rejoignent « Mon tour »,
    # juste après son dernier bandeau « Fin de tour » (moment où l'on marque
    # leurs points) — demande explicite de l'utilisateur ; elles ne sont
    # alors plus ajoutées en section séparée plus bas. Sur la même page que
    # « Fin de tour » dès que possible, quitte à être légèrement réduites
    # (`_TACTIC_MIN_SCALE`).
    rule_card_groups: list[tuple[str | None, list]] = []
    ability_cards: dict[str, list[AbilityEntry]] = {}
    tactics_in_turn_card = False
    if mode in SPLIT_MODES:
        # `fr-split-simple` : certaines aptitudes restent sur leur carte de
        # warscroll (`RosterSimplifications.keep_on_warscroll`).
        def kept(ab: AbilityEntry) -> bool:
            return simplifications is not None and simplifications.keeps_on_warscroll(ab)

        full_pool = combined_pool + _warscroll_ability_pool([
            _dc_replace(ws, abilities=[ab for ab in ws.abilities if not kept(ab)]) for ws in warscrolls_for_cards
        ])
        full_pool = _collapse_alias_pills(full_pool, alias_sources)
        if simplifications is not None:
            # règles de base/saison, ajoutées au bassin après le premier
            # passage (cf. plus haut) : badges `all_lists` (« Simple »...)
            full_pool = [simplifications.rewrite(ab) for ab in full_pool]
            full_pool = simplifications.merge(full_pool)
        full_pool = _apply_choice_clusters(_fold_warscroll_copies(full_pool), mode)
        if simplifications is not None:
            full_pool = simplifications.expand_phases(
                full_pool, lambda ab: ab.ability_category in CHOICE_CATEGORIES,
            )
            full_pool = _apply_section_order(full_pool, simplifications.section_order)
        warscrolls_for_cards = [
            _dc_replace(ws, abilities=[
                ab for ab in ws.abilities if kept(ab) or is_self_profile_modifier(ab, [w.name for w in ws.weapons])
            ])
            for ws in warscrolls_for_cards
        ]
        warscrolls_for_cards = _drop_identical_alias_cards(warscrolls_for_cards, alias_sources)
        if separate_battle_traits_card is not None:
            rule_card_groups.append((None, [separate_battle_traits_card]))

        def turn_card(title: str, abilities: list[AbilityEntry]):
            return render_rule_card(
                title, abilities, width=_RULE_CARD_WIDTH, subtitle=parsed.base_faction, phase_order=SPLIT_PHASE_ORDER,
                hide_turn_qualifier=True, sectioned=True,
                base_last=simplifications is not None and simplifications.base_rules_last,
            )

        deploy = [ab for ab in full_pool if _classify_phase(ab) == "deploy"]
        deploy = _order_deploy(deploy)
        any_phase = [ab for ab in full_pool if _classify_phase(ab) == "any"]
        in_turn = _order_deploy([ab for ab in full_pool if _classify_phase(ab) not in ("deploy", "any")])
        mine = [ab for ab in in_turn if TURN_MINE in _turn_sides(ab, in_turn)]
        enemy = _drop_enemy_charge_reroll([
            ab for ab in in_turn
            if TURN_ENEMY in _turn_sides(ab, in_turn) and ability_join_key(ab.name) not in _MINE_ONLY_KEYS
        ])
        ability_cards = {
            "deploy": deploy, "any": any_phase, "mine": mine, "enemy": enemy,
            "warscrolls": [_dc_replace(ab, warscrolls=(ws.name,)) for ws in warscrolls_for_cards for ab in ws.abilities],
            "battle_traits": battle_traits_entries if separate_battle_traits_card is not None else [],
        }

        # « N'importe quelle phase » : sa propre carte (demande de
        # l'utilisateur), à la suite de « Déploiement » sur les mêmes pages.
        rule_card_groups.append((None, [
            turn_card(tr("Déploiement"), deploy), turn_card(tr("N'importe quelle phase"), any_phase),
        ]))
        rule_card_groups.append((
            tr("Mon tour"),
            [
                turn_card(tr("Mon tour"), mine),
                _tactic_cards_block([flowable for _label, flowable in tactic_sections], min_scale=_TACTIC_MIN_SCALE),
            ],
        ))
        rule_card_groups.append((tr("Tour de l'adversaire"), [turn_card(tr("Tour adverse"), enemy)]))
        rule_card_groups = [(label, [c for c in group if c is not None]) for label, group in rule_card_groups]
        tactics_in_turn_card = True
    else:
        rule_cards: list = []
        if separate_battle_traits_card is not None:
            rule_cards.append(separate_battle_traits_card)
        combined_pool = _apply_choice_clusters(combined_pool, mode)
        if mode == "fr-extended":
            combined_pool = _order_deploy(combined_pool)
        if combined_pool:
            # même rendu sectionné que les cartes du mode `fr-split` (en-tête
            # horizontal et espace entre bandeaux de phase, sous-sections
            # Règles de base / Règles d'armée / Sorts..., « (suite) » après une
            # coupe de page), « N'importe quelle phase » (vert) juste après
            # le Déploiement (`SPLIT_PHASE_ORDER`) — demande de l'utilisateur ;
            # la carte reste unique, pastilles de tour comprises.
            rule_cards.append(render_rule_card(
                tr("Aptitudes"), combined_pool, width=_RULE_CARD_WIDTH, subtitle=parsed.base_faction,
                phase_order=SPLIT_PHASE_ORDER, sectioned=True,
            ))
        rule_card_groups.append((None, rule_cards))

    rules_included = (
        (["Règles de Saison 2026-27"] if season_entries else [])
        + (["Aptitudes Génériques — MdG26-27"] if generic_entries else [])
        + rule_card_labels
        + [label for label, _pages in battletome_rules]
        + [label for label, _pages in generic_manifestation_sections]
        + [label for label, _flowable in tactic_sections]
        + [label for label, _entries in wahapedia_lore_blocks]
        + enhancements_included
        + ([f"{renown_army[0]} — Army of Renown Rules"] if renown_army else [])
        + [
            f"Régiment de Renom : {name} (FR)" if name in regiment_curated else f"Regiment of Renown : {name}"
            for name, data in regiments_of_renown if data is not None
        ]
    )

    # Chaque section est rendue avant la couverture, qui légende les pictos
    # réellement dessinés (`drawn_badge_shapes`).
    reset_drawn_badge_shapes()
    rule_cards_bytes_by_group = [
        (page_label, _build_rule_cards_pdf(rule_cards, page_label=page_label, label_margin=mode not in SPLIT_MODES))
        for page_label, rule_cards in rule_card_groups
    ]
    tactic_cards_bytes = (
        None if tactics_in_turn_card else _build_tactic_cards_pdf([flowable for _label, flowable in tactic_sections])
    )
    cards_bytes = _build_warscroll_cards_pdf(warscrolls_for_cards, regiment_notes)
    appendix_bytes = _build_wahapedia_appendix_pdf(
        wahapedia_lore_blocks, renown_army, grouped_regiments,
    )

    writer = PdfWriter()
    cover = _build_cover_pdf(
        _relabel_options(parsed, simplifications), unmatched_units, rules_unmatched, wahapedia_used,
        badge_shapes=drawn_badge_shapes(),
    )
    for page in PdfReader(BytesIO(cover)).pages:
        writer.add_page(page)

    # Les warscrolls, consultés le plus souvent, juste après la liste, dans
    # tous les modes (demande de l'utilisateur) ; en mode split, ils sont en
    # plus recopiés en tête de la section « Tour de l'adversaire » (recto),
    # pour que chaque moitié du livret imprimé ait ses chartes.
    if cards_bytes is not None:
        for page in PdfReader(BytesIO(cards_bytes)).pages:
            writer.add_page(page)

    for page_label, rule_cards_bytes in rule_cards_bytes_by_group:
        if rule_cards_bytes is not None:
            if mode in SPLIT_MODES and page_label == tr("Tour de l'adversaire"):
                _pad_to_odd_page(writer)
                if cards_bytes is not None:
                    for page in PdfReader(BytesIO(cards_bytes)).pages:
                        writer.add_page(page)
            for page in PdfReader(BytesIO(rule_cards_bytes)).pages:
                writer.add_page(page)

    seen_battletome_pages: set[int] = set()
    if bt_path is not None and bt_path.exists():
        source_reader = PdfReader(str(bt_path))
        _append_pages(writer, source_reader, seen_battletome_pages, battletome_rules)

    gm_path = generic_manifestation_lores_path(index)
    if gm_path is not None and gm_path.exists() and generic_manifestation_sections:
        gm_reader = PdfReader(str(gm_path))
        _append_pages(writer, gm_reader, set(), generic_manifestation_sections)

    if tactic_cards_bytes is not None:
        for page in PdfReader(BytesIO(tactic_cards_bytes)).pages:
            writer.add_page(page)

    if appendix_bytes is not None:
        for page in PdfReader(BytesIO(appendix_bytes)).pages:
            writer.add_page(page)

    # Chaque section (couverture, cartes de règle, cartes de tactique, cartes
    # de warscroll, annexe) est construite comme un mini-PDF `reportlab`
    # séparé (son propre `SimpleDocTemplate.build`), donc chacun réembarque
    # sa propre copie du fond `_STONE_TEXTURE` (~1,3 Mo) : `add_page` copie
    # ces pages telles quelles, sans dédoublonner un XObject par ailleurs
    # identique octet pour octet entre les pages. `compress_identical_objects`
    # fusionne ces objets par hash de contenu en un seul, partagé par toutes
    # les pages — le gain dominant, avant même la recompression des pages de
    # battletome copiées (`_compress_page_images`).
    _stamp_page_numbers(writer)
    writer.compress_identical_objects()

    if out_path is None:
        out_path = default_output_path(list_path, mode)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    # `*-split-simple` : une seconde version, même contenu + les 12 cartes de
    # scénario à la fin (demande de l'utilisateur), à côté de la première —
    # pages de scénario non numérotées (numéros déjà apposés).
    scenario_path = None
    if mode in SIMPLE_MODES and DEFAULT_SCENARIOS_FILE.exists():
        _append_scenario_pages(writer, DEFAULT_SCENARIOS_FILE)
        writer.compress_identical_objects()
        scenario_path = scenario_variant_path(out_path)
        with open(scenario_path, "wb") as f:
            writer.write(f)

    return RosterPdfResult(
        scenario_output_path=scenario_path,
        absent_references=find_absent_references(parsed) if mode in SIMPLE_MODES else [],
        absent_keywords=find_absent_keywords(parsed) if mode in SIMPLE_MODES else [],
        output_path=out_path,
        units_matched=matched,
        units_unmatched=unmatched_units,
        rules_included=rules_included,
        rules_unmatched=rules_unmatched,
        wahapedia_used=wahapedia_used,
        ability_cards=ability_cards,
    )
