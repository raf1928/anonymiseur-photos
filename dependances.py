"""Contrôle et installation des dépendances.

N'utilise que la bibliothèque standard : ce module doit fonctionner même
quand rien n'est installé, puisque c'est lui qui propose l'installation.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
MODELE_VISAGE = DOSSIER / "modeles" / "face_detection_yunet_2023mar.onnx"
CACHE_PLAQUES = Path.home() / ".cache" / "open-image-models" / "yolo-v9-s-608-license-plate-end2end"


@dataclass
class Paquet:
    module: str        # nom à importer
    pip: str           # nom pour pip install (avec version minimale)
    distribution: str  # nom pour lire la version installée
    role: str


PAQUETS = [
    Paquet("cv2", "opencv-python>=4.8", "opencv-python", "détection des visages, floutage"),
    Paquet("onnxruntime", "onnxruntime>=1.16", "onnxruntime", "exécution du modèle des plaques"),
    Paquet("open_image_models", "open-image-models>=0.6", "open-image-models", "détection des plaques"),
    Paquet("numpy", "numpy", "numpy", "calcul sur les images"),
    Paquet("PIL", "pillow", "pillow", "lecture / écriture des JPG, affichage"),
]


@dataclass
class Etat:
    nom: str
    role: str
    present: bool
    version: str = ""
    detail: str = ""


def _version(distribution: str) -> str:
    try:
        return md.version(distribution)
    except md.PackageNotFoundError:
        return ""


def controler_paquet(p: Paquet) -> Etat:
    importlib.invalidate_caches()
    if importlib.util.find_spec(p.module) is None:
        return Etat(p.distribution, p.role, False, detail="non installé")
    try:
        importlib.import_module(p.module)
    except Exception as e:  # installé mais cassé (DLL manquante, version incompatible…)
        return Etat(p.distribution, p.role, False, _version(p.distribution), f"erreur à l'import : {e}")
    v = _version(p.distribution)
    if p.module == "cv2":
        import cv2
        if not hasattr(cv2, "FaceDetectorYN"):
            return Etat(p.distribution, p.role, False, v, "version trop ancienne (FaceDetectorYN absent)")
    return Etat(p.distribution, p.role, True, v)


def controler_modeles() -> list[Etat]:
    etats = []
    ok = MODELE_VISAGE.is_file() and MODELE_VISAGE.stat().st_size > 100_000
    etats.append(Etat("Modèle visages (YuNet)", "fourni avec le programme", ok,
                      detail="" if ok else f"fichier absent : {MODELE_VISAGE}"))
    fichiers = list(CACHE_PLAQUES.glob("*.onnx")) if CACHE_PLAQUES.is_dir() else []
    ok = any(f.stat().st_size > 1_000_000 for f in fichiers)
    etats.append(Etat("Modèle plaques (YOLOv9)", "téléchargé au premier usage (≈ 27 Mo)", ok,
                      detail="" if ok else "pas encore téléchargé"))
    return etats


def tout_controler() -> list[Etat]:
    return [controler_paquet(p) for p in PAQUETS] + controler_modeles()


def paquets_manquants() -> list[Paquet]:
    return [p for p in PAQUETS if not controler_paquet(p).present]


def installer(paquets: list[Paquet], ecrire=print) -> bool:
    """pip install dans l'interpréteur Python qui exécute le programme.

    `ecrire` reçoit chaque ligne de sortie de pip. Renvoie True si pip a réussi.
    """
    if not paquets:
        return True
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *[p.pip for p in paquets]]
    ecrire("> " + " ".join(cmd))
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW   # pas de console noire
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", **options)
    except OSError as e:
        ecrire(f"Impossible de lancer pip : {e}")
        return False
    for ligne in proc.stdout:
        ecrire(ligne.rstrip())
    proc.wait()
    importlib.invalidate_caches()
    return proc.returncode == 0


def telecharger_modele_plaques(ecrire=print) -> bool:
    try:
        from open_image_models import LicensePlateDetector
        ecrire("Téléchargement du modèle des plaques…")
        LicensePlateDetector(detection_model="yolo-v9-s-608-license-plate-end2end")
        ecrire("Modèle des plaques prêt.")
        return True
    except Exception as e:
        ecrire(f"Échec du téléchargement du modèle des plaques : {e}")
        return False
