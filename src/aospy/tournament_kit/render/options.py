"""Options de rendu des cartes et relevé des pastilles dessinées.

Les options (`RenderOptions`, gelé) sont lues tout en bas d'une dizaine
d'appels imbriqués (pastille, ligne d'aptitude, bandeau de phase...), et
aussi au moment de la mise en page reportlab (`rebuild`), après le retour de
la fonction de rendu : elles voyagent donc dans un `ContextVar` plutôt que
d'être passées en paramètre à chaque appel.

- `render_session()` : portée d'une génération de PDF (`build_roster_pdf`) —
  options par défaut et relevé (`RenderTracker`) neufs, tout est rétabli à la
  sortie, rien ne fuit vers le PDF suivant ni vers les tests.
- `update_render_options(**changes)` : fixe des options jusqu'à la fin de la
  session en cours (une fois par PDF, d'après le mode).
- `render_options_override(**changes)` : options modifiées le temps d'un bloc
  `with` (une carte de règles `sectioned`, un test).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class RenderOptions:
    #: mots-clés d'aptitude propres à une seule faction (minuscules, cf.
    #: `WahapediaLookup.faction_specific_keywords`) — pastille couleur faction.
    faction_keywords: frozenset[str] = frozenset()
    #: pastilles de mots-clés génériques en français (modes `fr*`).
    french_keywords: bool = False
    #: « Placer » / « set up » en gras (modes français et `*-split-simple`).
    bold_set_up: bool = False
    #: capacités d'arme traduites (`weapon_abilities_fr`, modes `fr*` et `hybrid`).
    french_weapon_tags: bool = False
    #: libellés maison en anglais (`tr`, mode `en-split-simple`).
    english_labels: bool = False
    #: masque « Ma phase »/« Phase ennemi » (cartes de tour du mode split).
    hide_turn_qualifier: bool = False
    #: bandeaux de phase découpés en sous-sections titrées.
    sectioned: bool = False
    #: « Règles de base » en dernière sous-section de chaque bandeau.
    base_last: bool = False


@dataclass
class RenderTracker:
    """Ce qui a réellement été dessiné, pour les légendes de la couverture."""

    #: couleurs de fond des pastilles construites (`_pill`, relevé à la construction).
    pill_colors: set[str] = field(default_factory=set)
    #: silhouettes de `_CastBadge` dessinées (relevé au `draw`).
    badge_shapes: set[str] = field(default_factory=set)


_OPTIONS: ContextVar[RenderOptions] = ContextVar("aospy_render_options", default=RenderOptions())
#: relevé hors session (appels directs aux fonctions de rendu, tests).
_DEFAULT_TRACKER = RenderTracker()
_TRACKER: ContextVar[RenderTracker] = ContextVar("aospy_render_tracker", default=_DEFAULT_TRACKER)


def render_options() -> RenderOptions:
    return _OPTIONS.get()


def render_tracker() -> RenderTracker:
    return _TRACKER.get()


def update_render_options(**changes) -> None:
    """Fixe des options jusqu'à la fin de la `render_session` en cours."""
    _OPTIONS.set(replace(_OPTIONS.get(), **changes))


@contextmanager
def render_options_override(**changes) -> Iterator[RenderOptions]:
    token = _OPTIONS.set(replace(_OPTIONS.get(), **changes))
    try:
        yield _OPTIONS.get()
    finally:
        _OPTIONS.reset(token)


@contextmanager
def use_render_options(options: RenderOptions) -> Iterator[None]:
    """Rétablit un jeu d'options capturé plus tôt (recomposition différée)."""
    token = _OPTIONS.set(options)
    try:
        yield
    finally:
        _OPTIONS.reset(token)


@contextmanager
def render_session() -> Iterator[RenderTracker]:
    opt_token = _OPTIONS.set(RenderOptions())
    tracker = RenderTracker()
    tr_token = _TRACKER.set(tracker)
    try:
        yield tracker
    finally:
        _TRACKER.reset(tr_token)
        _OPTIONS.reset(opt_token)
