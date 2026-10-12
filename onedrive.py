"""Disponibilité locale des photos d'un dossier synchronisé OneDrive / SharePoint.

Un fichier « dans le nuage » existe sur le disque sous forme d'espace réservé :
il n'est téléchargé qu'à la première lecture. Ce module repère ces fichiers
(attributs Windows) et les fait télécharger en arrière-plan en les lisant,
pour que le traitement ne les attende pas une à une.

Bibliothèque standard uniquement.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Attributs d'un espace réservé non téléchargé (Fichiers à la demande)
_DANS_LE_NUAGE = 0x00400000 | 0x00040000 | 0x00001000   # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE


def est_local(chemin: Path) -> bool:
    try:
        attributs = getattr(os.stat(chemin), "st_file_attributes", 0)
    except OSError:
        return False
    return not attributs & _DANS_LE_NUAGE


def compter_locales(photos: list[Path]) -> int:
    return sum(est_local(p) for p in photos)


class Chargeur:
    """Télécharge en arrière-plan les photos encore dans le nuage (lecture complète)."""

    def __init__(self, photos: list[Path], paralleles: int = 4):
        self.photos = [p for p in photos if not est_local(p)]
        self.arret = threading.Event()
        self.erreurs = 0
        self._fil = threading.Thread(target=self._executer, args=(paralleles,), daemon=True)

    def demarrer(self) -> "Chargeur":
        if self.photos:
            self._fil.start()
        return self

    def actif(self) -> bool:
        return self._fil.is_alive()

    def arreter(self):
        self.arret.set()

    def _lire(self, p: Path):
        if self.arret.is_set():
            return
        try:
            with open(p, "rb") as f:
                while not self.arret.is_set() and f.read(1 << 20):
                    pass
        except OSError:
            self.erreurs += 1

    def _executer(self, paralleles: int):
        with ThreadPoolExecutor(max_workers=paralleles) as pool:
            list(pool.map(self._lire, self.photos))
