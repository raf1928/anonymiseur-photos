"""Moteur d'anonymisation : détection des visages et des plaques, floutage, écriture.

Visages : YuNet (OpenCV, modèle ONNX dans modeles/).
Plaques : YOLOv9 « license-plate » (paquet open-image-models, ONNX téléchargé
au premier usage dans ~/.cache/open-image-models).

Les grandes photos sont analysées en entier PUIS par tuiles qui se recouvrent,
sinon les petits visages / plaques lointaines disparaissent à la réduction.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

DOSSIER_MODELES = Path(__file__).resolve().parent / "modeles"
MODELE_VISAGE = DOSSIER_MODELES / "face_detection_yunet_2023mar.onnx"
MODELE_PLAQUE = "yolo-v9-s-608-license-plate-end2end"
EXTENSIONS = {".jpg", ".jpeg"}
FICHIER_ZONES = "zones_anonymisation.json"


@dataclass
class Zone:
    x1: int
    y1: int
    x2: int
    y2: int
    type: str            # "visage", "plaque" ou "manuel"
    score: float = 1.0
    actif: bool = True   # False = écartée à la vérification (faux positif)

    def surface(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)


@dataclass
class Reglages:
    visages: bool = True
    plaques: bool = True
    seuil_visage: float = 0.55
    seuil_plaque: float = 0.30
    methode: str = "flou"        # "flou", "pixels" ou "noir"
    force: int = 3               # 1 (léger) … 5 (très fort)
    marge: float = 0.20          # agrandissement des zones (fraction de la taille)
    supprimer_metadonnees: bool = True
    qualite_jpeg: int = 92


# --------------------------------------------------------------------------- #
# Lecture / écriture
# --------------------------------------------------------------------------- #
def lire_image(chemin: Path) -> tuple[np.ndarray, Image.Image]:
    """Renvoie (image BGR redressée selon l'EXIF, image Pillow d'origine).

    Pillow plutôt que cv2.imread : ce dernier échoue sur les chemins accentués
    sous Windows (« ATDS Direction - Documents », « anonymisé »…).
    """
    pil = Image.open(chemin)
    pil.load()
    redressee = ImageOps.exif_transpose(pil).convert("RGB")
    return cv2.cvtColor(np.asarray(redressee), cv2.COLOR_RGB2BGR), pil


def ecrire_image(bgr: np.ndarray, origine: Image.Image, dest: Path, reglages: Reglages) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    sortie = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    options = {"quality": reglages.qualite_jpeg, "optimize": True}
    if not reglages.supprimer_metadonnees:
        exif = origine.getexif()
        exif[0x0112] = 1          # l'image est déjà redressée
        exif.pop(0x8825, None)    # GPS : toujours retiré, même si on garde le reste
        options["exif"] = exif.tobytes()
        if origine.info.get("icc_profile"):
            options["icc_profile"] = origine.info["icc_profile"]
    # Écriture dans un fichier temporaire puis remplacement : pas de JPEG tronqué
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    sortie.save(tmp, "JPEG", **options)
    os.replace(tmp, dest)


# --------------------------------------------------------------------------- #
# Détection
# --------------------------------------------------------------------------- #
def _tuiles(h: int, w: int, cote: int, recouvrement: float = 0.25):
    """Fenêtres (x, y, l, h) couvrant l'image, côté `cote`, avec recouvrement."""
    if max(h, w) <= cote * 1.3:
        return []
    pas = int(cote * (1 - recouvrement))
    xs = list(range(0, max(1, w - cote), pas)) + [max(0, w - cote)]
    ys = list(range(0, max(1, h - cote), pas)) + [max(0, h - cote)]
    return [(x, y, min(cote, w - x), min(cote, h - y)) for y in sorted(set(ys)) for x in sorted(set(xs))]


def _nms(zones: list[Zone], seuil_iou: float = 0.4) -> list[Zone]:
    if not zones:
        return []
    boites = [[z.x1, z.y1, z.x2 - z.x1, z.y2 - z.y1] for z in zones]
    scores = [z.score for z in zones]
    garder = cv2.dnn.NMSBoxes(boites, scores, 0.0, seuil_iou)
    return [zones[int(i)] for i in np.array(garder).flatten()]


class Detecteur:
    def __init__(self, reglages: Reglages):
        self.reglages = reglages
        self._visage = None
        self._plaque = None

    # chargement paresseux : le modèle de plaques est téléchargé au premier usage
    def _det_visage(self):
        if self._visage is None:
            self._visage = cv2.FaceDetectorYN.create(
                str(MODELE_VISAGE), "", (320, 320), self.reglages.seuil_visage, 0.3, 5000)
        self._visage.setScoreThreshold(self.reglages.seuil_visage)
        return self._visage

    def _det_plaque(self):
        if self._plaque is None:
            import logging
            logging.getLogger("open_image_models").setLevel(logging.WARNING)
            from open_image_models import LicensePlateDetector
            self._plaque = LicensePlateDetector(detection_model=MODELE_PLAQUE, conf_thresh=0.05)
        return self._plaque

    def _visages_dans(self, img: np.ndarray, ox: int, oy: int, echelle: float) -> list[Zone]:
        det = self._det_visage()
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, res = det.detect(img)
        zones = []
        if res is not None:
            for r in res:
                x, y, bw, bh, score = r[0], r[1], r[2], r[3], float(r[-1])
                zones.append(Zone(int(ox + x / echelle), int(oy + y / echelle),
                                  int(ox + (x + bw) / echelle), int(oy + (y + bh) / echelle),
                                  "visage", score))
        return zones

    def _plaques_dans(self, img: np.ndarray, ox: int, oy: int) -> list[Zone]:
        zones = []
        for r in self._det_plaque().predict(img):
            if r.confidence < self.reglages.seuil_plaque:
                continue
            b = r.bounding_box
            zones.append(Zone(int(ox + b.x1), int(oy + b.y1), int(ox + b.x2), int(oy + b.y2),
                              "plaque", float(r.confidence)))
        return zones

    def detecter(self, bgr: np.ndarray) -> list[Zone]:
        h, w = bgr.shape[:2]
        zones: list[Zone] = []
        if self.reglages.visages:
            trouves = []
            # 1) image entière réduite (grands visages)
            e = min(1.0, 1280 / max(h, w))
            petite = cv2.resize(bgr, (int(w * e), int(h * e)), interpolation=cv2.INTER_AREA) if e < 1 else bgr
            trouves += self._visages_dans(petite, 0, 0, e)
            # 2) tuiles pleine résolution (petits visages)
            for x, y, tw, th in _tuiles(h, w, 1280):
                trouves += self._visages_dans(bgr[y:y + th, x:x + tw], x, y, 1.0)
            zones += _nms(trouves)
        if self.reglages.plaques:
            trouves = self._plaques_dans(bgr, 0, 0)
            for x, y, tw, th in _tuiles(h, w, 1024):
                trouves += self._plaques_dans(bgr[y:y + th, x:x + tw], x, y)
            zones += _nms(trouves)
        return zones


# --------------------------------------------------------------------------- #
# Floutage
# --------------------------------------------------------------------------- #
def flouter(bgr: np.ndarray, zones: list[Zone], reglages: Reglages) -> np.ndarray:
    sortie = bgr.copy()
    h, w = bgr.shape[:2]
    for z in zones:
        if not z.actif:
            continue
        mx = int((z.x2 - z.x1) * reglages.marge / 2)
        my = int((z.y2 - z.y1) * reglages.marge / 2)
        x1, y1 = max(0, z.x1 - mx), max(0, z.y1 - my)
        x2, y2 = min(w, z.x2 + mx), min(h, z.y2 + my)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        bloc = sortie[y1:y2, x1:x2]
        bh, bw = bloc.shape[:2]
        if reglages.methode == "noir":
            traite = np.zeros_like(bloc)
        else:
            # Pixellisation d'abord dans les deux cas : un simple flou gaussien
            # peut être partiellement inversé, une mosaïque grossière non.
            cases = max(3, int(12 / reglages.force))       # cases sur le petit côté
            pas = max(1, min(bw, bh) // cases)
            mosa = cv2.resize(bloc, (max(1, bw // pas), max(1, bh // pas)), interpolation=cv2.INTER_AREA)
            traite = cv2.resize(mosa, (bw, bh), interpolation=cv2.INTER_NEAREST)
            if reglages.methode == "flou":
                k = max(3, (min(bw, bh) // 3) | 1)
                traite = cv2.GaussianBlur(traite, (k, k), 0)
        # visages : masque elliptique adouci ; plaques / manuel : rectangle
        if z.type == "visage":
            masque = np.zeros((bh, bw), np.float32)
            cv2.ellipse(masque, (bw // 2, bh // 2), (bw // 2, bh // 2), 0, 0, 360, 1.0, -1)
            if reglages.methode != "noir":
                k = max(3, (min(bw, bh) // 10) | 1)
                masque = np.maximum(masque, cv2.GaussianBlur(masque, (k, k), 0))
        else:
            masque = np.ones((bh, bw), np.float32)
        m = masque[..., None]
        sortie[y1:y2, x1:x2] = (traite * m + bloc * (1 - m)).astype(np.uint8)
    return sortie


# --------------------------------------------------------------------------- #
# Fichiers et zones mémorisées (pour la vérification manuelle)
# --------------------------------------------------------------------------- #
def lister_photos(dossier: Path, sous_dossiers: bool, exclure: Path | None = None) -> list[Path]:
    motif = dossier.rglob("*") if sous_dossiers else dossier.glob("*")
    photos = []
    for p in motif:
        if p.is_file() and p.suffix.lower() in EXTENSIONS:
            if exclure is not None and exclure in p.parents:
                continue
            photos.append(p)
    return sorted(photos)


def charger_zones(dossier_sortie: Path) -> dict[str, list[Zone]]:
    f = dossier_sortie / FICHIER_ZONES
    if not f.exists():
        return {}
    data = json.loads(f.read_text(encoding="utf-8"))
    return {k: [Zone(**z) for z in v] for k, v in data.get("photos", {}).items()}


def enregistrer_zones(dossier_sortie: Path, source: Path, zones: dict[str, list[Zone]]) -> None:
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    data = {"source": str(source), "photos": {k: [asdict(z) for z in v] for k, v in zones.items()}}
    (dossier_sortie / FICHIER_ZONES).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def chemin_sortie(photo: Path, source: Path, dossier_sortie: Path) -> Path:
    return dossier_sortie / photo.relative_to(source)
