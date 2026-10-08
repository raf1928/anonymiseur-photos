"""Anonymiseur de photos — interface.

Lancement : python anonymiseur.py

Floute les visages et les plaques d'immatriculation des JPG d'un dossier.
Les originaux ne sont jamais modifiés : les photos anonymisées sont écrites
dans un dossier de sortie (par défaut « <dossier>/anonymisé »).
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

import anonymisation as an

FICHIER_REGLAGES = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "anonymiseur_photos" / "reglages.json"
NOM_SORTIE = "anonymisé"
COULEURS = {"visage": "#ff3030", "plaque": "#2f7dff", "manuel": "#20c040"}


def lire_reglages() -> dict:
    try:
        return json.loads(FICHIER_REGLAGES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ecrire_reglages(d: dict) -> None:
    try:
        FICHIER_REGLAGES.parent.mkdir(parents=True, exist_ok=True)
        FICHIER_REGLAGES.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Anonymiseur de photos — visages et plaques")
        self.geometry("760x600")
        self.minsize(640, 480)
        r = lire_reglages()

        self.v_source = tk.StringVar(value=r.get("source", ""))
        self.v_sortie = tk.StringVar(value=r.get("sortie", ""))
        self.v_sous_dossiers = tk.BooleanVar(value=r.get("sous_dossiers", False))
        self.v_visages = tk.BooleanVar(value=r.get("visages", True))
        self.v_plaques = tk.BooleanVar(value=r.get("plaques", True))
        self.v_methode = tk.StringVar(value=r.get("methode", "flou"))
        self.v_force = tk.IntVar(value=r.get("force", 3))
        self.v_sensibilite = tk.IntVar(value=r.get("sensibilite", 3))
        self.v_metadonnees = tk.BooleanVar(value=r.get("supprimer_metadonnees", True))
        self.v_deja = tk.BooleanVar(value=r.get("ignorer_deja_faites", False))

        self.file_messages: queue.Queue = queue.Queue()
        self.fil: threading.Thread | None = None
        self.arreter = threading.Event()
        self._construire()
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        self.after(100, self._lire_messages)

    # ------------------------------------------------------------------ UI
    def _construire(self):
        pad = {"padx": 8, "pady": 4}
        cadre = ttk.LabelFrame(self, text="Dossiers")
        cadre.pack(fill="x", **pad)
        ttk.Label(cadre, text="Photos (JPG) :").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(cadre, textvariable=self.v_source).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(cadre, text="Choisir…", command=self._choisir_source).grid(row=0, column=2, **pad)
        ttk.Label(cadre, text="Sortie :").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(cadre, textvariable=self.v_sortie).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(cadre, text="Choisir…", command=self._choisir_sortie).grid(row=1, column=2, **pad)
        ttk.Checkbutton(cadre, text="Inclure les sous-dossiers", variable=self.v_sous_dossiers).grid(
            row=2, column=1, sticky="w", **pad)
        cadre.columnconfigure(1, weight=1)

        opt = ttk.LabelFrame(self, text="Options")
        opt.pack(fill="x", **pad)
        ttk.Checkbutton(opt, text="Visages", variable=self.v_visages).grid(row=0, column=0, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Plaques d'immatriculation", variable=self.v_plaques).grid(
            row=0, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Méthode :").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(opt, textvariable=self.v_methode, state="readonly", width=12,
                     values=["flou", "pixels", "noir"]).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Force du floutage :").grid(row=2, column=0, sticky="w", **pad)
        tk.Scale(opt, from_=1, to=5, orient="horizontal", variable=self.v_force, length=180).grid(
            row=2, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Sensibilité de détection :").grid(row=3, column=0, sticky="w", **pad)
        tk.Scale(opt, from_=1, to=5, orient="horizontal", variable=self.v_sensibilite, length=180).grid(
            row=3, column=1, sticky="w", **pad)
        ttk.Label(opt, text="(5 = trouve plus de choses, mais plus de fausses alertes)",
                  foreground="gray").grid(row=3, column=2, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Supprimer les métadonnées (GPS, appareil, date…)",
                        variable=self.v_metadonnees).grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Ignorer les photos déjà anonymisées dans la sortie",
                        variable=self.v_deja).grid(row=5, column=0, columnspan=3, sticky="w", **pad)

        bas = ttk.Frame(self)
        bas.pack(fill="x", **pad)
        self.b_lancer = ttk.Button(bas, text="Anonymiser", command=self._lancer)
        self.b_lancer.pack(side="left", padx=4)
        self.b_arreter = ttk.Button(bas, text="Arrêter", command=self.arreter.set, state="disabled")
        self.b_arreter.pack(side="left", padx=4)
        self.b_verifier = ttk.Button(bas, text="Vérifier / corriger…", command=self._verifier)
        self.b_verifier.pack(side="left", padx=4)
        ttk.Button(bas, text="Ouvrir la sortie", command=self._ouvrir_sortie).pack(side="left", padx=4)

        self.progres = ttk.Progressbar(self, mode="determinate")
        self.progres.pack(fill="x", **pad)
        self.journal = tk.Text(self, height=12, wrap="word", state="disabled")
        self.journal.pack(fill="both", expand=True, **pad)

    def _choisir_source(self):
        d = filedialog.askdirectory(title="Dossier des photos", initialdir=self.v_source.get() or None)
        if d:
            self.v_source.set(os.path.normpath(d))
            self.v_sortie.set(os.path.join(os.path.normpath(d), NOM_SORTIE))

    def _choisir_sortie(self):
        d = filedialog.askdirectory(title="Dossier de sortie", initialdir=self.v_sortie.get() or None)
        if d:
            self.v_sortie.set(os.path.normpath(d))

    def _ouvrir_sortie(self):
        s = self.v_sortie.get()
        if s and Path(s).is_dir():
            os.startfile(s)

    def _ecrire(self, texte: str):
        self.journal.configure(state="normal")
        self.journal.insert("end", texte + "\n")
        self.journal.see("end")
        self.journal.configure(state="disabled")

    def reglages(self) -> an.Reglages:
        s = self.v_sensibilite.get()   # 1..5 → seuils
        return an.Reglages(
            visages=self.v_visages.get(), plaques=self.v_plaques.get(),
            seuil_visage={1: 0.8, 2: 0.7, 3: 0.55, 4: 0.45, 5: 0.35}[s],
            seuil_plaque={1: 0.6, 2: 0.45, 3: 0.30, 4: 0.20, 5: 0.12}[s],
            methode=self.v_methode.get(), force=self.v_force.get(),
            supprimer_metadonnees=self.v_metadonnees.get())

    def _memoriser(self):
        ecrire_reglages({
            "source": self.v_source.get(), "sortie": self.v_sortie.get(),
            "sous_dossiers": self.v_sous_dossiers.get(), "visages": self.v_visages.get(),
            "plaques": self.v_plaques.get(), "methode": self.v_methode.get(),
            "force": self.v_force.get(), "sensibilite": self.v_sensibilite.get(),
            "supprimer_metadonnees": self.v_metadonnees.get(), "ignorer_deja_faites": self.v_deja.get()})

    def _dossiers(self) -> tuple[Path, Path] | None:
        src = Path(self.v_source.get().strip())
        if not src.is_dir():
            messagebox.showerror("Anonymiseur", "Choisissez un dossier de photos existant.")
            return None
        if not self.v_sortie.get().strip():
            self.v_sortie.set(str(src / NOM_SORTIE))
        sortie = Path(self.v_sortie.get().strip())
        if sortie.resolve() == src.resolve():
            messagebox.showerror("Anonymiseur", "Le dossier de sortie doit être différent du dossier "
                                 "des photos : les originaux ne doivent pas être écrasés.")
            return None
        return src, sortie

    # ------------------------------------------------------------ traitement
    def _lancer(self):
        d = self._dossiers()
        if d is None:
            return
        src, sortie = d
        reg = self.reglages()
        if not (reg.visages or reg.plaques):
            messagebox.showwarning("Anonymiseur", "Cochez au moins « Visages » ou « Plaques ».")
            return
        self._memoriser()
        photos = an.lister_photos(src, self.v_sous_dossiers.get(), exclure=sortie)
        if not photos:
            messagebox.showinfo("Anonymiseur", "Aucune photo JPG dans ce dossier.")
            return
        self.arreter.clear()
        self.b_lancer.configure(state="disabled")
        self.b_verifier.configure(state="disabled")
        self.b_arreter.configure(state="normal")
        self.progres.configure(maximum=len(photos), value=0)
        self._ecrire(f"{len(photos)} photo(s) à traiter → {sortie}")
        self.fil = threading.Thread(target=self._traiter, args=(photos, src, sortie, reg, self.v_deja.get()),
                                    daemon=True)
        self.fil.start()

    def _traiter(self, photos, src, sortie, reg, ignorer_deja):
        msg = self.file_messages.put
        t0 = time.time()
        zones_toutes = an.charger_zones(sortie)
        nb_v = nb_p = nb_err = 0
        try:
            det = an.Detecteur(reg)
            for i, p in enumerate(photos, 1):
                if self.arreter.is_set():
                    msg(("log", "Arrêté par l'utilisateur."))
                    break
                cle = p.relative_to(src).as_posix()
                dest = an.chemin_sortie(p, src, sortie)
                if ignorer_deja and dest.exists() and cle in zones_toutes:
                    msg(("progres", i))
                    continue
                try:
                    bgr, pil = an.lire_image(p)
                    # les zones ajoutées / écartées à la main sont conservées
                    manuelles = [z for z in zones_toutes.get(cle, []) if z.type == "manuel"]
                    ecartees = [z for z in zones_toutes.get(cle, []) if not z.actif and z.type != "manuel"]
                    zones = det.detecter(bgr)
                    for z in zones:
                        if any(_meme_zone(z, e) for e in ecartees):
                            z.actif = False
                    zones += manuelles
                    an.ecrire_image(an.flouter(bgr, zones, reg), pil, dest, reg)
                    zones_toutes[cle] = zones
                    v = sum(z.type == "visage" and z.actif for z in zones)
                    pl = sum(z.type == "plaque" and z.actif for z in zones)
                    nb_v += v
                    nb_p += pl
                    msg(("log", f"{cle} : {v} visage(s), {pl} plaque(s)"))
                except Exception as e:  # une photo illisible ne bloque pas les autres
                    nb_err += 1
                    msg(("log", f"ERREUR {cle} : {e}"))
                msg(("progres", i))
                if i % 10 == 0:
                    an.enregistrer_zones(sortie, src, zones_toutes)
        except Exception as e:
            msg(("log", f"ERREUR : {e}"))
        finally:
            an.enregistrer_zones(sortie, src, zones_toutes)
            msg(("log", f"Terminé en {time.time() - t0:.0f} s : {nb_v} visage(s), {nb_p} plaque(s) floutés"
                        + (f", {nb_err} erreur(s)" if nb_err else "") + "."))
            msg(("log", "Contrôlez le résultat avec « Vérifier / corriger… » : la détection "
                        "automatique peut manquer un visage de profil ou une plaque lointaine."))
            msg(("fin", None))

    def _lire_messages(self):
        try:
            while True:
                genre, val = self.file_messages.get_nowait()
                if genre == "log":
                    self._ecrire(val)
                elif genre == "progres":
                    self.progres.configure(value=val)
                elif genre == "fin":
                    self.b_lancer.configure(state="normal")
                    self.b_verifier.configure(state="normal")
                    self.b_arreter.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._lire_messages)

    def _verifier(self):
        d = self._dossiers()
        if d is None:
            return
        src, sortie = d
        zones = an.charger_zones(sortie)
        if not zones:
            messagebox.showinfo("Anonymiseur", "Aucune photo anonymisée dans ce dossier de sortie : "
                                "lancez d'abord « Anonymiser ».")
            return
        self._memoriser()
        FenetreVerification(self, src, sortie, zones, self.reglages())

    def _fermer(self):
        self._memoriser()
        self.arreter.set()
        self.destroy()


def _meme_zone(a: an.Zone, b: an.Zone) -> bool:
    ix = max(0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.surface() + b.surface() - inter
    return union > 0 and inter / union > 0.5


class FenetreVerification(tk.Toplevel):
    """Contrôle photo par photo.

    Clic gauche + glisser : ajouter une zone à flouter.
    Clic droit sur une zone : l'écarter (faux positif) ou la réactiver ;
    une zone ajoutée à la main est supprimée.
    Chaque modification réécrit aussitôt la photo anonymisée.
    """

    def __init__(self, maitre: Application, src: Path, sortie: Path, zones: dict, reglages: an.Reglages):
        super().__init__(maitre)
        self.title("Vérifier / corriger l'anonymisation")
        self.geometry("1200x800")
        self.src, self.sortie, self.zones, self.reg = src, sortie, zones, reglages
        self.cles = sorted(k for k in zones if (src / k).exists())
        self.indice = 0
        self.bgr = self.pil = None
        self.echelle = 1.0
        self.debut = None
        self.v_apercu = tk.BooleanVar(value=False)

        gauche = ttk.Frame(self)
        gauche.pack(side="left", fill="y")
        self.liste = tk.Listbox(gauche, width=38, exportselection=False)
        self.liste.pack(side="left", fill="y")
        barre = ttk.Scrollbar(gauche, command=self.liste.yview)
        barre.pack(side="left", fill="y")
        self.liste.configure(yscrollcommand=barre.set)
        self.liste.bind("<<ListboxSelect>>", lambda e: self._choisir())

        droite = ttk.Frame(self)
        droite.pack(side="left", fill="both", expand=True)
        haut = ttk.Frame(droite)
        haut.pack(fill="x")
        ttk.Button(haut, text="◀ Précédente", command=lambda: self._aller(-1)).pack(side="left", padx=4, pady=4)
        ttk.Button(haut, text="Suivante ▶", command=lambda: self._aller(1)).pack(side="left", padx=4)
        ttk.Checkbutton(haut, text="Voir le résultat flouté", variable=self.v_apercu,
                        command=self._afficher).pack(side="left", padx=12)
        ttk.Label(haut, text="Glisser = ajouter une zone · clic droit = écarter / réactiver",
                  foreground="gray").pack(side="left", padx=8)
        self.info = ttk.Label(droite, text="")
        self.info.pack(fill="x", padx=4)
        self.canevas = tk.Canvas(droite, background="#202020", highlightthickness=0)
        self.canevas.pack(fill="both", expand=True)
        self.canevas.bind("<Configure>", lambda e: self._afficher())
        self.canevas.bind("<ButtonPress-1>", self._presser)
        self.canevas.bind("<B1-Motion>", self._glisser)
        self.canevas.bind("<ButtonRelease-1>", self._relacher)
        self.canevas.bind("<Button-3>", self._clic_droit)
        self.bind("<Left>", lambda e: self._aller(-1))
        self.bind("<Right>", lambda e: self._aller(1))

        self._remplir_liste()
        if self.cles:
            self.liste.selection_set(0)
            self._charger()

    def _libelle(self, cle):
        zs = [z for z in self.zones[cle] if z.actif]
        return f"{cle}  ({len(zs)})"

    def _remplir_liste(self):
        self.liste.delete(0, "end")
        for k in self.cles:
            self.liste.insert("end", self._libelle(k))
            if not any(z.actif for z in self.zones[k]):
                self.liste.itemconfigure("end", foreground="#c07000")   # rien flouté : à regarder

    def _choisir(self):
        sel = self.liste.curselection()
        if sel and sel[0] != self.indice:
            self.indice = sel[0]
            self._charger()

    def _aller(self, pas):
        if not self.cles:
            return
        self.indice = max(0, min(len(self.cles) - 1, self.indice + pas))
        self.liste.selection_clear(0, "end")
        self.liste.selection_set(self.indice)
        self.liste.see(self.indice)
        self._charger()

    def _charger(self):
        cle = self.cles[self.indice]
        self.bgr, self.pil = an.lire_image(self.src / cle)
        self._afficher()

    def _afficher(self):
        if self.bgr is None:
            return
        cle = self.cles[self.indice]
        zones = self.zones[cle]
        cw, ch = max(50, self.canevas.winfo_width()), max(50, self.canevas.winfo_height())
        h, w = self.bgr.shape[:2]
        self.echelle = min(cw / w, ch / h)
        img = an.flouter(self.bgr, zones, self.reg) if self.v_apercu.get() else self.bgr
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        petite = Image.fromarray(rgb).resize((max(1, int(w * self.echelle)), max(1, int(h * self.echelle))))
        self._photo = ImageTk.PhotoImage(petite)
        self.canevas.delete("all")
        self.canevas.create_image(0, 0, anchor="nw", image=self._photo)
        e = self.echelle
        for z in zones:
            coul = COULEURS.get(z.type, "#ffffff")
            self.canevas.create_rectangle(z.x1 * e, z.y1 * e, z.x2 * e, z.y2 * e, outline=coul, width=2,
                                          dash=() if z.actif else (4, 4))
        nv = sum(z.type == "visage" and z.actif for z in zones)
        npl = sum(z.type == "plaque" and z.actif for z in zones)
        nm = sum(z.type == "manuel" for z in zones)
        nx = sum(not z.actif for z in zones)
        self.info.configure(text=f"{self.indice + 1}/{len(self.cles)} — {cle} : {nv} visage(s) (rouge), "
                                 f"{npl} plaque(s) (bleu), {nm} ajoutée(s) (vert), {nx} écartée(s) (pointillés)")

    def _vers_image(self, ev):
        return int(ev.x / self.echelle), int(ev.y / self.echelle)

    def _presser(self, ev):
        self.debut = (ev.x, ev.y)
        self.canevas.delete("trace")

    def _glisser(self, ev):
        if self.debut:
            self.canevas.delete("trace")
            self.canevas.create_rectangle(*self.debut, ev.x, ev.y, outline=COULEURS["manuel"], width=2, tags="trace")

    def _relacher(self, ev):
        if not self.debut:
            return
        x0, y0 = self.debut
        self.debut = None
        self.canevas.delete("trace")
        if abs(ev.x - x0) < 4 or abs(ev.y - y0) < 4:
            return
        h, w = self.bgr.shape[:2]
        e = self.echelle
        x1, x2 = sorted((int(x0 / e), int(ev.x / e)))
        y1, y2 = sorted((int(y0 / e), int(ev.y / e)))
        self.zones[self.cles[self.indice]].append(
            an.Zone(max(0, x1), max(0, y1), min(w, x2), min(h, y2), "manuel"))
        self._sauver()

    def _clic_droit(self, ev):
        x, y = self._vers_image(ev)
        zones = self.zones[self.cles[self.indice]]
        dedans = [z for z in zones if z.x1 <= x <= z.x2 and z.y1 <= y <= z.y2]
        if not dedans:
            return
        z = min(dedans, key=lambda q: q.surface())   # la plus petite sous le curseur
        if z.type == "manuel":
            zones.remove(z)
        else:
            z.actif = not z.actif
        self._sauver()

    def _sauver(self):
        cle = self.cles[self.indice]
        an.ecrire_image(an.flouter(self.bgr, self.zones[cle], self.reg), self.pil,
                        an.chemin_sortie(self.src / cle, self.src, self.sortie), self.reg)
        an.enregistrer_zones(self.sortie, self.src, self.zones)
        self.liste.delete(self.indice)
        self.liste.insert(self.indice, self._libelle(cle))
        self.liste.selection_set(self.indice)
        self._afficher()


if __name__ == "__main__":
    Application().mainloop()
