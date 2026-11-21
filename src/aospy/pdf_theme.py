"""Palette et constantes PDF partagées entre `reports/` (registres « édition
TM ») et `tournament_kit/` (kit de tournoi) — tout ce que les deux consomment
réellement en commun. Les gabarits de page/tableaux complets (`build_document`,
`ranked_table`, styles de paragraphe...), eux, restent propres à `reports/common.py`
puisque `tournament_kit/pdf_builder.py` construit ses propres pages (portrait,
pas le même gabarit landscape Cover/Data)."""

from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape

OLD_ENGLISH_FONT = "Times-Bold"

PAGE_W, PAGE_H = landscape(A4)

INK_BLACK = colors.HexColor("#0b0d13")
NIGHT_BLUE = colors.HexColor("#161a2b")
GOLD = colors.HexColor("#b8912f")
GOLD_BRIGHT = colors.HexColor("#f0cf6b")
GOLD_DIM = colors.HexColor("#8a6d24")
PARCHMENT = colors.HexColor("#f3ead6")
PARCHMENT_2 = colors.HexColor("#e9dcc0")
STEEL = colors.HexColor("#4a4536")
BLOOD_GREEN = colors.HexColor("#2f6b32")
BLOOD_RED = colors.HexColor("#8c1f1f")


def today_str() -> str:
    return datetime.now().strftime("%d/%m/%Y à %Hh%M")
