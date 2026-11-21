"""Génère la texture pierre (fond de page du kit de tournoi) utilisée par
`tournament_kit.pdf_builder._draw_page_bg`. Procédural plutôt que téléchargée
depuis une source externe — même raisonnement que `Cinzel-Bold.ttf`
(cf. `render/`) : pas de question de licence à auditer, un fichier
reproductible qui vit dans le dépôt.

Usage : `python scripts/generate_stone_texture.py` régénère
`src/aospy/tournament_kit/assets/stone_texture.jpg` (nécessite Pillow +
numpy — outils de génération ponctuelle, pas des dépendances runtime de
`aospy`). Seed fixe (`_SEED`) : sortie reproductible d'un run à l'autre.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

_SEED = 42

#: teinte de base — même couleur que `render/theme.PAGE_BG` (#f8f2e3),
#: la texture doit rester "de la bonne couleur", juste avec du grain en plus.
_BASE = np.array([248.0, 242.0, 227.0])

#: taille de sortie — A4 portrait à ~150dpi, assez pour rester net une fois
#: étirée sur la page par `_draw_page_bg` (`drawImage` plein cadre), sans
#: gonfler inutilement le poids du fichier embarqué dans le paquet.
_WIDTH, _HEIGHT = 1240, 1754

#: JPEG plutôt que PNG : cette texture n'est que du bruit fin (grain, mouchetures)
#: — le pire cas pour la compression PNG sans perte — alors que l'artefact JPEG
#: sur du bruit aléatoire est imperceptible à l'œil sur un fond de page pâle.
#: qualité 85 : ~180 Ko contre ~1,1 Mo en PNG, et ce fichier est dupliqué sur
#: chaque page du PDF de tournoi généré (cf. `pdf_builder._draw_page_bg`), donc
#: son poids se répercute directement sur la taille du PDF final.
_OUT_PATH = Path(__file__).resolve().parents[1] / "src" / "aospy" / "tournament_kit" / "assets" / "stone_texture.jpg"


def _noise_layer(rng: np.random.Generator, blur_radius: float) -> np.ndarray:
    """Bruit gaussien lissé, recentré à moyenne 0 sur `[-1, 1]` — une octave
    d'irrégularité de surface, `blur_radius` en fixant l'échelle (grand rayon
    = larges plaques de teinte, petit rayon = grain fin)."""
    raw = rng.normal(0, 1, size=(_HEIGHT, _WIDTH)).astype(np.float32)
    img = Image.fromarray(((raw - raw.min()) / (raw.max() - raw.min()) * 255).astype(np.uint8), mode="L")
    img = img.filter(ImageFilter.GaussianBlur(blur_radius))
    arr = np.asarray(img, dtype=np.float64) / 255.0
    arr -= arr.mean()
    return arr / (np.abs(arr).max() or 1.0)


def _veins(rng: np.random.Generator, n: int) -> np.ndarray:
    """Quelques veines/craquelures sombres irrégulières (marche aléatoire
    lissée, tracé en plusieurs passes voisines pour leur donner une
    épaisseur), comme sur une dalle de pierre naturelle — un aplat de bruit
    seul (`_noise_layer`) reste trop uniforme pour lire comme de la pierre
    plutôt que du papier grené."""
    mask = np.zeros((_HEIGHT, _WIDTH), dtype=np.float64)
    for _ in range(n):
        x0 = rng.uniform(0, _WIDTH)
        y0 = rng.uniform(0, _HEIGHT)
        angle = rng.uniform(0, 2 * np.pi)
        length = rng.uniform(_HEIGHT * 0.2, _HEIGHT * 0.6)
        steps = int(length / 3)
        x, y = x0, y0
        for _s in range(steps):
            angle += rng.uniform(-0.3, 0.3)
            x += 3 * np.cos(angle)
            y += 3 * np.sin(angle)
            for ox, oy in ((0, 0), (1, 0), (0, 1), (-1, 0), (0, -1)):
                xi, yi = int(x + ox), int(y + oy)
                if 0 <= xi < _WIDTH and 0 <= yi < _HEIGHT:
                    mask[yi, xi] = 1.0
    img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    img = img.filter(ImageFilter.GaussianBlur(1.6))
    return np.asarray(img, dtype=np.float64) / 255.0


def _flecks(rng: np.random.Generator, n: int) -> np.ndarray:
    """Petites mouchetures minérales ponctuelles (granite/grès) — points
    isolés à pleine opacité, tantôt plus sombres tantôt plus clairs que le
    fond, contrairement aux couches de bruit lissé ci-dessus qui ne
    produisent que des variations douces et continues."""
    mask = np.zeros((_HEIGHT, _WIDTH), dtype=np.float64)
    xs = rng.integers(0, _WIDTH, size=n)
    ys = rng.integers(0, _HEIGHT, size=n)
    signs = rng.choice([-1.0, 1.0], size=n, p=[0.7, 0.3])
    mask[ys, xs] = signs
    img = Image.fromarray(((mask + 1) * 127.5).astype(np.uint8), mode="L")
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return (np.asarray(img, dtype=np.float64) / 127.5) - 1.0


def generate() -> Image.Image:
    rng = np.random.default_rng(_SEED)
    canvas = np.tile(_BASE, (_HEIGHT, _WIDTH, 1))

    # larges plaques de teinte (variation de couleur à grande échelle, comme
    # les taches naturelles d'une dalle de pierre)
    blotches = _noise_layer(rng, 55)
    canvas[..., 0] += blotches * 22
    canvas[..., 1] += blotches * 17
    canvas[..., 2] += blotches * 10

    # grain moyen
    canvas += (_noise_layer(rng, 5) * 13)[..., None]

    # moucheture fine (aspect minéral)
    canvas += (_noise_layer(rng, 1.0) * 9)[..., None]

    # mouchetures ponctuelles (grains de minéral individuels)
    canvas += (_flecks(rng, 26000) * 20)[..., None]

    # veines/craquelures sombres
    canvas -= (_veins(rng, 9) * 30)[..., None]

    # vignettage vers les bords — donne une impression de dalle plutôt qu'un
    # aplat texturé infini
    yy, xx = np.mgrid[0:_HEIGHT, 0:_WIDTH]
    cx, cy = _WIDTH / 2, _HEIGHT / 2
    dist = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    vignette = np.clip(dist - 0.5, 0, None) * 32
    canvas -= vignette[..., None]

    canvas = np.clip(canvas, 0, 255).astype(np.uint8)
    return Image.fromarray(canvas, mode="RGB")


if __name__ == "__main__":
    img = generate()
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(_OUT_PATH, "JPEG", quality=85, optimize=True)
    print(f"écrit : {_OUT_PATH} ({_OUT_PATH.stat().st_size / 1024:.0f} Ko)")
