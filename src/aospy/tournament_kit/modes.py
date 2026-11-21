"""Variantes du roster (`build_roster_pdf(..., mode=...)` / `aospy roster pdf --mode`).

Chaque `RosterMode` (le nom passé par la CLI) se lit en un `ModeSpec`, dont
les propriétés remplacent les tests `mode in (...)` épars :

- `hybrid` (défaut, comportement historique) : Wahapedia (EN, déjà à jour
  des errata) prioritaire, repli sur une page de battletome copiée (FR) par
  catégorie non couverte (`page_copy`) ;
- `en` : Wahapedia uniquement, la copie de page FR est sautée (un trou reste
  un trou, listé dans `RosterPdfResult.rules_unmatched`) ;
- `fr` / `fr-extended` : correctifs/additions verbatim français de
  `data/json/faction_rules_fr.json` (`french`) appliqués partout où ils
  existent ; `fr-extended` ajoute la carte « Aptitudes Génériques »
  (`generic_core_abilities.json`), les sous-sections de choix et l'ordre du
  déploiement (`extended`) ;
- `fr-split` : même contenu que `fr-extended`, mise en page « split »
  (cartes Déploiement / Mon tour / Tour adverse, warscrolls réduits aux
  profils) ;
- `fr-split-simple` : `fr-split` + simplifications par liste
  (`data/json/roster_simplifications.json`, `simple`) ;
- `en-split-simple` : la même mise en page en anglais (`english`) :
  Wahapedia corrigé par les textes officiels anglais de l'app
  (`curated_patch` sans `french`), aptitudes génériques en verbatim Core
  Rules GW, libellés maison anglais, simplifications de la section `en`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RosterMode = Literal["hybrid", "en", "fr", "fr-extended", "fr-split", "fr-split-simple", "en-split-simple"]


@dataclass(frozen=True)
class ModeSpec:
    name: str
    #: correctifs verbatim français (`faction_rules_fr.json`), pastilles de
    #: mots-clés en français, « Placer » en gras.
    french: bool = False
    #: pool Wahapedia corrigé par un fichier de textes curés (même schéma,
    #: `faction_rules_fr.py`) : modes français et `en-split-simple`
    #: (`app_rules_en.json`).
    curated_patch: bool = False
    #: politique de noms FR/EN des cartes de warscroll (nom anglais +
    #: sous-titre français, armes et capacités d'arme en français,
    #: `_apply_display_fr`) : modes français et `hybrid`.
    french_names: bool = False
    #: repli sur une page de battletome copiée (FR) pour une catégorie non
    #: couverte par Wahapedia (`hybrid` seulement).
    page_copy: bool = False
    #: carte « Aptitudes Génériques », sous-sections de choix
    #: (`_CHOICE_CLUSTERS`), ordre du déploiement : `fr-extended` + modes split.
    extended: bool = False
    #: mise en page « split » (cartes Déploiement / Mon tour / Tour adverse).
    split: bool = False
    #: simplifications par liste (`roster_simplifications.py`).
    simple: bool = False
    #: libellés maison, aptitudes génériques et tactiques en anglais.
    english: bool = False
    #: suffixe du PDF par défaut (`pdf_builder.default_output_path`) —
    #: « defaut » pour `hybrid`, le nom du mode étant un détail d'implémentation.
    file_label: str = ""


MODES: dict[str, ModeSpec] = {
    "hybrid": ModeSpec("hybrid", french_names=True, page_copy=True, file_label="defaut"),
    "en": ModeSpec("en", file_label="en"),
    "fr": ModeSpec("fr", french=True, curated_patch=True, french_names=True, file_label="fr"),
    "fr-extended": ModeSpec(
        "fr-extended",
        french=True,
        curated_patch=True,
        french_names=True,
        extended=True,
        file_label="fr-extended",
    ),
    "fr-split": ModeSpec(
        "fr-split",
        french=True,
        curated_patch=True,
        french_names=True,
        extended=True,
        split=True,
        file_label="fr-split",
    ),
    "fr-split-simple": ModeSpec(
        "fr-split-simple",
        french=True,
        curated_patch=True,
        french_names=True,
        extended=True,
        split=True,
        simple=True,
        file_label="fr-split-simple",
    ),
    "en-split-simple": ModeSpec(
        "en-split-simple",
        curated_patch=True,
        extended=True,
        split=True,
        simple=True,
        english=True,
        file_label="en-split-simple",
    ),
}


def mode_spec(mode: str) -> ModeSpec:
    return MODES[mode]
