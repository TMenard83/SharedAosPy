"""Texte des aptitudes : nettoyage, flavor, gras « Placer », coupure des noms longs, libellés anglais (`tr`), capacités d'arme en français."""

from __future__ import annotations

import re

from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph

from .options import render_options
from .theme import _NAME_STYLE

#: Libellé français des mots-clés d'aptitude génériques (règles de base),
#: même vocabulaire que `generic_core_abilities.json`/`faction_rules_fr.json`
#: (« Base,Mouvement », « Sort, Convocation », « Saccage »...). Les mots-clés
#: propres à une faction (Delusion, Blood Tithe...) n'y sont pas : leur nom
#: français officiel se curate au cas par cas, jamais deviné.
_KEYWORD_LABELS_FR = {
    "core": "BASE",
    "attack": "ATTAQUE",
    "fight": "CORPS À CORPS",
    "shoot": "TIR",
    "move": "MOUVEMENT",
    "run": "COURSE",
    "retreat": "REPLI",
    "charge": "CHARGE",
    "rampage": "SACCAGE",
    "spell": "SORT",
    "prayer": "PRIÈRE",
    "summon": "CONVOCATION",
    "unbind": "DISSIPATION",
    "banish": "BANNISSEMENT",
    "deploy": "DÉPLOIEMENT",
    "deploy terrain": "DÉPLOIEMENT DE TERRAIN",
}

#: « Placer » (« Set up ») est un terme de règle (règles de base, Placer des
#: unités) : toujours en gras dans les modes français et `*-split-simple` (demande de
#: l'utilisateur, `RenderOptions.bold_set_up`).
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


def english_labels() -> bool:
    return render_options().english_labels


#: libellé maison français -> anglais (vocabulaire des Core Rules GW). Clés
#: exactes, telles qu'affichées (pastilles en majuscules, bandeaux et titres
#: en casse normale).
_EN_LABELS: dict[str, str] = {
    # bandeaux de phase
    "Déploiement": "Deployment",
    "Début de round": "Start of battle round",
    "Astérisme": "Asterism",
    "Début de tour": "Start of turn",
    "Phase des héros": "Hero phase",
    "Phase de mouvement": "Movement phase",
    "Phase de tir": "Shooting phase",
    "Phase de charge": "Charge phase",
    "Phase de mêlée": "Combat phase",
    "Fin de tour": "End of turn",
    "N'importe quelle phase": "Any phase",
    # catégories / sous-sections
    "Aptitudes": "Abilities",
    "Sorts": "Spells",
    "Prières": "Prayers",
    "Manifestations": "Manifestations",
    "Délires": "Delusions",
    "Dîme de Sang": "Blood Tithe",
    "Bénédictions de Khaine": "Blessings of Khaine",
    "Vocation au Chaos": "Pledge to Chaos",
    "Règles de base": "Core rules",
    "Règles d'armée": "Army rules",
    # pastilles de timing
    "Ma phase": "Your phase",
    "Les 2 phases": "Both turns",
    "Phase ennemi": "Enemy phase",
    "×1 / TOUR": "×1 / TURN",
    "×1 / BATAILLE": "×1 / BATTLE",
    "×1 / TOUR (ARMÉE)": "×1 / TURN (ARMY)",
    "×1 / BATAILLE (ARMÉE)": "×1 / BATTLE (ARMY)",
    "×1 / ROUND (ARMÉE)": "×1 / ROUND (ARMY)",
    "×1 / ROUND": "×1 / ROUND",
    "×1 / PHASE": "×1 / PHASE",
    "×1 / PHASE (ARMÉE)": "×1 / PHASE (ARMY)",
    "DÉBUT DU 1ER ROUND": "START OF FIRST BATTLE ROUND",
    "FIN DU 1ER ROUND": "END OF FIRST BATTLE ROUND",
    "PASSIF": "PASSIVE",
    "RÉACTION": "REACTION",
    "Réaction :": "Reaction:",
    "PHASE DE DÉPLOIEMENT": "DEPLOYMENT PHASE",
    "DÉBUT DU ROUND DE BATAILLE": "START OF BATTLE ROUND",
    "ILLIMITÉ": "UNLIMITED",
    "SORT": "SPELL",
    "PRIÈRE": "PRAYER",
    "ORDRE": "COMMAND",
    "DIME DE SANG": "BLOOD TITHE",
    # badges d'origine (`tag_ability_origin`, internes en français)
    "SAISON": "SEASON",
    "MDG": "GHB",
    "TACTIQUE": "TACTIC",
    "TRAITS DE BATAILLE": "BATTLE TRAITS",
    "TRAIT DE BATAILLE": "BATTLE TRAIT",
    "TRAIT HÉROÏQUE": "HEROIC TRAIT",
    "ARTEFACT DE POUVOIR": "ARTEFACT OF POWER",
    "TRAIT MONSTRUEUX": "MONSTROUS TRAIT",
    "MUTATION D'AIRAIN": "BRAZEN MUTATION",
    "MARQUE DES DIEUX SOMBRES": "BRAND OF THE DARK GODS",
    "BANNIÈRE ENSORCELÉE": "ENSORCELLED BANNER",
    "MÉDAILLE DE BRAVOURE": "DECORATION FOR VALOUR",
    "FABLE TERRIFIANTE": "TERRIFYING FOLK TALE",
    # carte d'unité
    "Portée": "Rng",
    "Invoquée": "Summoned",
    # cartes de tactique
    "ÉCHAUFFOURÉE": "AFFRAY",
    "FRAPPE": "STRIKE",
    "DOMINATION": "DOMINATION",
    "RÈGLE SPÉCIALE": "SPECIAL RULE",
    "PTS DE<br/>VICTOIRE": "VICTORY<br/>POINTS",
    # légende de la page de garde
    "Source du texte : MDG (Manuel du Général), BT (battletome), FP (faction pack), AQSHY, WAHAPEDIA "
    "(anglais). Traits de Bataille, Formation : catégorie de règles d'armée.": "Text source: GW APP (official Warhammer Age of Sigmar app), CORE RULES (GW Core Rules), GHB (General's Handbook), BT (battletome), "
    "FP (faction pack), AQSHY, WAHAPEDIA. Battle Traits, Formation: army rule category.",
    "Texte adapté, pas le verbatim : en cas de litige, revenir à la règle d'origine.": "Adapted text, not verbatim: in case of dispute, refer to the original rule.",
    "Aptitude de base du jeu (Core) ; règle de la saison en cours (MdG 2026-27).": "Core ability; current season rule (General's Handbook 2026-27).",
    "Fréquence — (ARMÉE) : une seule fois pour toute l'armée ; passif : toujours actif, rien à déclarer.": "Frequency — (ARMY): once for the whole army; passive: always active, nothing to declare.",
    "Réaction : utilisée en réponse à l'aptitude indiquée.": "Reaction: used in response to the stated ability.",
    "Mot-clé d'aptitude, à la couleur de sa phase (Mouvement, Tir, Charge, Corps à Corps).": "Ability keyword, in the colour of its phase (Move, Shoot, Charge, Fight).",
    "Mot-clé d'aptitude valable dans plusieurs phases.": "Ability keyword used in several phases.",
    "Magie (sort, manifestation, bannissement…) ; prière. Illimité : utilisable plusieurs fois par tour.": "Magic (spell, manifestation, banishment…); prayer. Unlimited: can be used several times per turn.",
    "Unité qui porte l'aptitude (pour un sort signature : son lanceur).": "Unit that has the ability (for a signature spell: its caster).",
    "Autre mot-clé d'aptitude (Tactique : règle spéciale d'une carte de tactique) ; bordeaux : propre à la faction.": "Other ability keyword (Tactic: special rule of a battle tactic card); burgundy: faction-specific.",
    "Aptitude : valeur de lancement. Warscroll : niveau de Sorcier ; manifestation : valeur de lancement de sa convocation.": "Ability: casting value. Warscroll: Wizard level; manifestation: casting value of its summoning.",
    "Aptitude : valeur de récitation. Warscroll : niveau de Prêtre.": "Ability: chanting value. Warscroll: Priest level.",
    "Ordre : coût en points d’ordre": "Command: command point cost",
    "Dîme de sang : coût en points de dîme de sang": "Blood tithe: blood tithe point cost",
    "Dés de rage : « +N » gagnés, sinon nombre dépensé": "Rage dice: “+N” gained, otherwise number spent",
    "Niveau de fureur : « +N » augmenté, sinon diminué": "Fury level: “+N” increased, otherwise decreased",
    "NOM D'UNITÉ": "UNIT NAME",
    "MOT-CLÉ": "KEYWORD",
    "ATTAQUE": "ATTACK",
    "SACCAGE": "RAMPAGE",
    "TIR": "SHOOT",
    "BASE": "CORE",
    "MOUVEMENT": "MOVE",
    "COURSE": "RUN",
    "REPLI": "RETREAT",
    "CORPS À CORPS": "FIGHT",
    "BANNISSEMENT": "BANISH",
    "DISSIPATION": "UNBIND",
    "CONVOCATION": "SUMMON",
    "DÉPLOIEMENT": "DEPLOY",
    "DÉPLOIEMENT DE TERRAIN": "DEPLOY TERRAIN",
    # cartes de règle / pages du roster (`pdf_builder`)
    "Mon tour": "My turn",
    "Tour adverse": "Opponent's turn",
    "Tour de l'adversaire": "Opponent's turn",
    "Traits de Bataille": "Battle Traits",
    "Battle Tactic Cards :": "Battle Tactic Cards:",
    "⚠ Profil non trouvé (ni battletome, ni Wahapedia) pour : ": "⚠ Profile not found (neither battletome nor Wahapedia) for: ",
    "⚠ Règle non trouvée (ni battletome, ni Wahapedia) pour : ": "⚠ Rule not found (neither battletome nor Wahapedia) for: ",
    "ℹ Complété en anglais via Wahapedia (voir annexe en fin de document) : ": "ℹ Completed from Wahapedia (see appendix at the end of the document): ",
    "Généré le ": "Generated on ",
    "Légende des pictos": "Icon legend",
    "ANNEXE — CONTENU WAHAPEDIA (ANGLAIS)": "APPENDIX — WAHAPEDIA CONTENT",
    "Ce qui suit n'existe dans aucun des PDF fournis (battletomes, Manuel du général) : "
    "domaines de sorts/manifestations génériques, règles d'armée de renom, Régiments de Renom. "
    "Repris tel quel depuis data/wahapedia/ (Wahapedia, en anglais) — non traduit pour éviter tout contresens sur des règles de jeu.": "Generic spell/manifestation lores, Army of Renown rules and Regiments of Renown not covered elsewhere, "
    "taken as-is from data/wahapedia/ (Wahapedia).",
}

#: badges d'origine paramétrés (« Formation : X », « Optimisation (X) »...) :
#: préfixe français -> préfixe anglais, en majuscules comme la pastille.
_EN_LABEL_PREFIXES = (
    ("FORMATION : ", "FORMATION: "),
    ("RÉGIMENT DE RENOM : ", "REGIMENT OF RENOWN: "),
    ("OPTIMISATION (", "ENHANCEMENT ("),
    ("Drops : ", "Drops: "),
    ("Domaine de sorts : ", "Spell lore: "),
    ("Domaine de prières : ", "Prayer lore: "),
    ("Domaine de manifestations : ", "Manifestation lore: "),
    ("Carte de tactique : ", "Battle tactic card: "),
    ("Domaine de Sorts — ", "Spell Lore — "),
    ("Domaine de Prières — ", "Prayer Lore — "),
    ("Domaine de Manifestations — ", "Manifestation Lore — "),
)


def tr(text: str) -> str:
    """`text` (libellé maison français) en anglais en mode `en-split-simple`,
    inchangé sinon ou s'il n'a pas de traduction connue."""
    if not render_options().english_labels:
        return text
    if text in _EN_LABELS:
        return _EN_LABELS[text]
    for fr, en in _EN_LABEL_PREFIXES:
        if text.startswith(fr):
            return en + text[len(fr) :]
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
    "infantry": "Infanterie",
    "monster": "Monstre",
    "hero": "Héros",
    "charge": "charge",
    "cavalry": "Cavalerie",
    "wizard": "Sorcier",
    "priest": "Prêtre",
    "manifestation": "Manifestation",
    "beast": "Bête",
    "war machine": "Machine de Guerre",
    "faction terrain": "Terrain de Faction",
    "daemon": "Démon",
    "unique": "Unique",
}
_ANTI_RE = re.compile(r"\bAnti-([A-Za-z ]+?)\s*(?=\()")


def weapon_abilities_fr(text: str) -> str:
    """Mots-clés d'un profil d'arme (« Shoot in Combat, Anti-INFANTRY (+1
    Rend) ») en français (modes `fr*`) ; un mot-clé inconnu reste tel quel."""
    for pattern, repl in _WEAPON_ABILITIES_FR:
        text = pattern.sub(repl, text)
    return _ANTI_RE.sub(
        lambda m: "Anti-" + _ANTI_TARGET_FR.get(m.group(1).strip().lower(), m.group(1).strip()) + " ",
        text,
    )


def _safe_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Comme `Paragraph(text, style)`, mais tolérant : `data/wahapedia/*.csv`
    est une donnée externe scrapée, parfois corrompue (ex. une balise HTML
    tronquée en plein milieu d'un champ, cf. `assembly._safe_paragraph` —
    même pattern, dupliqué ici pour éviter un import circulaire avec
    `pdf_builder.py`) — on retombe sur le texte brut plutôt que de faire
    planter toute la génération pour une seule entrée abîmée."""
    try:
        return Paragraph(text, style)
    except Exception:
        stripped = re.sub(r"<[^>]*>", " ", text).replace("<", " ").replace(">", " ")
        return Paragraph(re.sub(r"\s+", " ", stripped).strip(), style)


#: fautes de frappe présentes dans le texte Wahapedia scrapé, corrigées au
#: rendu (texte d'origine -> texte corrigé). FEC « A Kingdom Deluded ».
_WAHAPEDIA_TYPOS = {
    "the eect of that D  applies": "the effect of that DELUSION applies",
    "same Delusion  as": "same DELUSION as",
}


def clean_html(text: str) -> str:
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
        r"\1",
        text,
        flags=re.IGNORECASE | re.DOTALL,
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


def _clean_text(html: str) -> str:
    """Alias historique de `clean_html` (même nettoyage partout : pas de
    divergence de rendu texte entre cartes et annexe)."""
    return clean_html(html)


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
