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
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import dependances as dep

# Chargés par charger_modules() : absents tant que les dépendances ne sont pas
# installées, et l'onglet « Dépendances » doit pouvoir s'afficher quand même.
an = cv2 = Image = ImageTk = None


def charger_modules() -> bool:
    global an, cv2, Image, ImageTk
    try:
        import cv2 as _cv2
        from PIL import Image as _Image, ImageTk as _ImageTk
        import anonymisation as _an
    except Exception:
        return False
    an, cv2, Image, ImageTk = _an, _cv2, _Image, _ImageTk
    return True


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


class Infobulle:
    """Petite bulle d'aide affichée après un court survol du widget."""

    def __init__(self, widget, texte: str, delai_ms: int = 500):
        self.widget, self.texte, self.delai = widget, texte, delai_ms
        self.fenetre = None
        self.attente = None
        widget.bind("<Enter>", self._programmer, add="+")
        widget.bind("<Leave>", self._cacher, add="+")
        widget.bind("<ButtonPress>", self._cacher, add="+")

    def _programmer(self, _ev=None):
        self._annuler_attente()
        self.attente = self.widget.after(self.delai, self.montrer)

    def _annuler_attente(self):
        if self.attente:
            self.widget.after_cancel(self.attente)
            self.attente = None

    def montrer(self):
        self.attente = None
        if self.fenetre or not self.widget.winfo_viewable():
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.fenetre = tk.Toplevel(self.widget)
        self.fenetre.wm_overrideredirect(True)
        self.fenetre.attributes("-topmost", True)
        tk.Label(self.fenetre, text=self.texte, justify="left", background="#ffffe0", foreground="#000000",
                 relief="solid", borderwidth=1, wraplength=360, padx=6, pady=4).pack()
        self.fenetre.update_idletasks()
        # rester dans l'écran
        larg, haut = self.fenetre.winfo_width(), self.fenetre.winfo_height()
        x = min(x, self.widget.winfo_screenwidth() - larg - 4)
        if y + haut > self.widget.winfo_screenheight() - 40:
            y = self.widget.winfo_rooty() - haut - 4
        self.fenetre.geometry(f"+{x}+{y}")

    def _cacher(self, _ev=None):
        self._annuler_attente()
        if self.fenetre:
            self.fenetre.destroy()
            self.fenetre = None


def bulle(widget, texte: str):
    """Attache une infobulle et renvoie le widget (pour enchaîner .grid / .pack)."""
    widget.infobulle = Infobulle(widget, texte)
    return widget


def texte_aide(parent, texte: str):
    """Paragraphe explicatif dont la largeur suit celle de son parent."""
    etiquette = ttk.Label(parent, text=texte, justify="left", wraplength=700, foreground="#404040")
    parent.bind("<Configure>", lambda e: etiquette.configure(wraplength=max(300, e.width - 24)), add="+")
    return etiquette


AIDE_PRINCIPALE = (
    "Ce programme floute automatiquement les visages et les plaques d'immatriculation des photos JPG d'un "
    "dossier. Les originaux ne sont jamais modifiés. Le dossier de sortie reçoit TOUTES les photos en JPG "
    "(floutées quand il y a un visage ou une plaque, sinon simplement recopiées et compressées selon la "
    "qualité choisie) ainsi que le fichier zones_anonymisation.json qui mémorise les zones floutées.\n"
    "1) Choisissez le dossier des photos.  2) Réglez les options.  3) Cliquez sur « Anonymiser » : l'aperçu "
    "à droite montre le résultat de chaque photo pendant le traitement ; les photos ne sont copiées dans la "
    "sortie qu'à la fin (si vous arrêtez, rien n'est copié sauf si vous le demandez). Contrôlez ensuite avec "
    "« Vérifier / corriger… ». Ou bien utilisez « Mode manuel… » pour flouter vous-même au clic.\n"
    "Tout est traité sur cet ordinateur : aucune photo n'est envoyée sur internet. "
    "Survolez un bouton ou un réglage pour afficher son aide.")

AIDE_DEPENDANCES = (
    "Le programme a besoin de bibliothèques Python et de deux modèles de détection. Le tableau indique ce "
    "qui est installé (OK) ou manquant (MANQUE). Au démarrage, s'il manque quelque chose, le programme "
    "propose de l'installer. L'installation utilise pip, nécessite une connexion internet et se fait dans "
    "le Python indiqué ci-dessous. Le modèle des plaques (≈ 27 Mo) n'est téléchargé qu'une fois.")

AIDE_VERIFICATION = (
    "Contrôle des photos anonymisées. Cadres rouges = visages détectés, bleus = plaques, verts = zones "
    "ajoutées à la main, pointillés = zones écartées (non floutées).\n"
    "Clic sur l'image : flouter un carré (cadre jaune, taille réglable à la molette).  Glisser : flouter un "
    "rectangle.  Clic droit sur une zone : l'écarter ou la réactiver (une zone ajoutée est supprimée).  "
    "Ctrl+Z : annuler le dernier ajout.  ← → : photo précédente / suivante.\n"
    "Chaque modification est enregistrée aussitôt. En orange dans la liste : photos où rien n'est flouté, "
    "à regarder en priorité.")

AIDE_MANUEL = (
    "Mode manuel : toutes les photos du dossier défilent avec les flèches ← →. L'image montre le résultat tel "
    "qu'il sera enregistré.\n"
    "Clic sur l'image : flouter un carré centré sur le clic (cadre jaune, taille réglable à la molette).  "
    "Glisser : flouter un rectangle.  Clic droit sur une zone : la retirer.  Ctrl+Z : annuler le dernier "
    "ajout.\n"
    "Rien n'est écrit pendant le défilement : tout est enregistré à la fin, avec « Terminer et enregistrer » "
    "(toutes les photos du dossier sont alors copiées dans la sortie, floutées ou non). « Abandonner » ou la "
    "fermeture de la fenêtre ne copient rien sans votre accord. ✓ = photo vue, orange = pas encore vue, "
    "* = modifiée.")


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Anonymiseur de photos — visages et plaques")
        self.geometry("1400x820")
        self.minsize(1100, 600)
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
        self.v_qualite = tk.IntVar(value=r.get("qualite_jpeg", 92))

        self.file_messages: queue.Queue = queue.Queue()
        self.fil: threading.Thread | None = None
        self.fil_dep: threading.Thread | None = None
        self.arreter = threading.Event()
        self.abandon = False             # fermeture pendant un traitement : rien n'est copié
        self._apercu_pil = None
        self._apercu_tk = None
        self.modules_ok = charger_modules()
        self.onglets = ttk.Notebook(self)
        self.onglets.pack(fill="both", expand=True)
        self.page_anon = ttk.Frame(self.onglets)
        self.page_dep = ttk.Frame(self.onglets)
        self.onglets.add(self.page_anon, text="Anonymisation")
        self.onglets.add(self.page_dep, text="Dépendances")
        self._construire(self.page_anon)
        self._construire_dependances(self.page_dep)
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        self.after(100, self._lire_messages)
        self.after(300, self._controle_demarrage)
        self.after(2000, _nettoyer_preparations)

    # ------------------------------------------------------------------ UI
    def _construire(self, page):
        pad = {"padx": 8, "pady": 4}
        gauche = ttk.Frame(page)
        gauche.pack(side="left", fill="both")
        droite = ttk.LabelFrame(page, text="Aperçu du résultat")
        droite.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=8)
        self.apercu = bulle(tk.Label(droite, background="#202020", foreground="#c0c0c0",
                                     text="Le résultat de chaque photo\ns'affiche ici pendant le traitement."),
                            "Résultat de la photo en cours de traitement, tel qu'il sera enregistré dans la sortie.")
        self.apercu.pack(fill="both", expand=True, padx=4, pady=4)
        self.apercu.bind("<Configure>", lambda e: self._dessiner_apercu())
        self.apercu_titre = ttk.Label(droite, text="")
        self.apercu_titre.pack(fill="x", padx=4, pady=(0, 4))
        page = gauche
        texte_aide(page, AIDE_PRINCIPALE).pack(fill="x", padx=10, pady=(8, 2))
        cadre = ttk.LabelFrame(page, text="Dossiers")
        cadre.pack(fill="x", **pad)
        ttk.Label(cadre, text="Photos (JPG) :").grid(row=0, column=0, sticky="w", **pad)
        bulle(ttk.Entry(cadre, textvariable=self.v_source),
              "Dossier contenant les photos JPG à anonymiser. Rien n'y est modifié.").grid(
            row=0, column=1, sticky="ew", **pad)
        bulle(ttk.Button(cadre, text="Choisir…", command=self._choisir_source),
              "Choisir le dossier des photos. La sortie est alors proposée dans son sous-dossier "
              "« anonymisé ».").grid(row=0, column=2, **pad)
        ttk.Label(cadre, text="Sortie :").grid(row=1, column=0, sticky="w", **pad)
        bulle(ttk.Entry(cadre, textvariable=self.v_sortie),
              "Dossier où sont écrites les photos anonymisées. Il doit être différent du dossier des "
              "photos.").grid(row=1, column=1, sticky="ew", **pad)
        bulle(ttk.Button(cadre, text="Choisir…", command=self._choisir_sortie),
              "Choisir un autre dossier de sortie.").grid(row=1, column=2, **pad)
        bulle(ttk.Checkbutton(cadre, text="Inclure les sous-dossiers", variable=self.v_sous_dossiers),
              "Traiter aussi les photos des sous-dossiers ; leur arborescence est reproduite dans la "
              "sortie.").grid(row=2, column=1, sticky="w", **pad)
        cadre.columnconfigure(1, weight=1)

        opt = ttk.LabelFrame(page, text="Options")
        opt.pack(fill="x", **pad)
        bulle(ttk.Checkbutton(opt, text="Visages", variable=self.v_visages),
              "Détecter et flouter automatiquement les visages.").grid(row=0, column=0, sticky="w", **pad)
        bulle(ttk.Checkbutton(opt, text="Plaques d'immatriculation", variable=self.v_plaques),
              "Détecter et flouter automatiquement les plaques d'immatriculation.").grid(
            row=0, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Méthode :").grid(row=1, column=0, sticky="w", **pad)
        bulle(ttk.Combobox(opt, textvariable=self.v_methode, state="readonly", width=12,
                           values=["flou", "pixels", "noir"]),
              "flou : mosaïque adoucie (le plus discret).\npixels : mosaïque visible.\n"
              "noir : zone masquée en noir (le plus sûr).").grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Force du floutage :").grid(row=2, column=0, sticky="w", **pad)
        bulle(tk.Scale(opt, from_=1, to=5, orient="horizontal", variable=self.v_force, length=180),
              "1 = léger, 5 = très fort : plus c'est fort, plus les blocs de la mosaïque sont gros.").grid(
            row=2, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Sensibilité de détection :").grid(row=3, column=0, sticky="w", **pad)
        bulle(tk.Scale(opt, from_=1, to=5, orient="horizontal", variable=self.v_sensibilite, length=180),
              "Plus haut : moins d'oublis mais davantage de fausses détections, à écarter ensuite dans "
              "« Vérifier / corriger… ».").grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(opt, text="(5 = trouve plus de choses, mais plus de fausses alertes)",
                  foreground="gray").grid(row=3, column=2, sticky="w", **pad)
        bulle(ttk.Checkbutton(opt, text="Supprimer les métadonnées (GPS, appareil, date…)",
                              variable=self.v_metadonnees),
              "Coché : les photos de sortie ne contiennent plus aucune information EXIF.\nDécoché : ces "
              "informations sont gardées, sauf la position GPS qui est toujours retirée.").grid(
            row=4, column=0, columnspan=3, sticky="w", **pad)
        bulle(ttk.Checkbutton(opt, text="Ignorer les photos déjà anonymisées dans la sortie",
                              variable=self.v_deja),
              "Pour reprendre un traitement interrompu : les photos déjà présentes dans la sortie ne sont "
              "pas retraitées.").grid(row=5, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(opt, text="Qualité JPG enregistrée :").grid(row=6, column=0, sticky="w", **pad)
        bulle(tk.Scale(opt, from_=50, to=100, orient="horizontal", variable=self.v_qualite, length=180),
              "Compression des JPG écrits dans la sortie (photos floutées et recopiées). 92 par défaut ; "
              "plus bas = fichiers plus légers mais qualité moindre.").grid(row=6, column=1, sticky="w", **pad)
        ttk.Label(opt, text="(100 = meilleure qualité, fichiers plus lourds ; 85-95 conseillé)",
                  foreground="gray").grid(row=6, column=2, sticky="w", **pad)

        bas = ttk.Frame(page)
        bas.pack(fill="x", **pad)
        self.b_lancer = bulle(ttk.Button(bas, text="Anonymiser", command=self._lancer),
                              "Détecter les visages et plaques sur toutes les photos du dossier et écrire les "
                              "photos floutées dans la sortie.")
        self.b_lancer.pack(side="left", padx=4)
        self.b_arreter = bulle(ttk.Button(bas, text="Arrêter", command=self.arreter.set, state="disabled"),
                               "Interrompre le traitement après la photo en cours. Le programme demande alors "
                               "s'il faut copier dans la sortie les photos déjà traitées ; sinon rien n'est copié.")
        self.b_arreter.pack(side="left", padx=4)
        self.b_verifier = bulle(ttk.Button(bas, text="Vérifier / corriger…", command=self._verifier),
                                "Revoir une à une les photos traitées : ajouter une zone oubliée, écarter une "
                                "fausse détection.")
        self.b_verifier.pack(side="left", padx=4)
        self.b_manuel = bulle(ttk.Button(bas, text="Mode manuel…", command=self._mode_manuel),
                              "Faire défiler toutes les photos avec les flèches ← → et flouter au clic ; "
                              "tout est enregistré à la fin, quand vous cliquez « Terminer et enregistrer ».")
        self.b_manuel.pack(side="left", padx=4)
        bulle(ttk.Button(bas, text="Ouvrir la sortie", command=self._ouvrir_sortie),
              "Ouvrir le dossier de sortie dans l'Explorateur Windows.").pack(side="left", padx=4)

        ligne = ttk.Frame(page)
        ligne.pack(fill="x", **pad)
        self.compteur = ttk.Label(ligne, text="", width=14, anchor="e")
        self.compteur.pack(side="right", padx=(8, 0))
        self.progres = bulle(ttk.Progressbar(ligne, mode="determinate"),
                             "Avancement : photos traitées / total, puis copie dans la sortie à la fin.")
        self.progres.pack(side="left", fill="x", expand=True)
        self.journal = tk.Text(page, height=7, wrap="word", state="disabled")
        self.journal.pack(fill="both", expand=True, **pad)

    # ----------------------------------------------------------- dépendances
    def _construire_dependances(self, page):
        pad = {"padx": 8, "pady": 4}
        texte_aide(page, AIDE_DEPENDANCES).pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(page, text=f"Python utilisé : {sys.executable}  (version {sys.version.split()[0]})",
                  foreground="gray").pack(anchor="w", **pad)
        colonnes = ("role", "etat", "version", "detail")
        self.arbre_dep = ttk.Treeview(page, columns=colonnes, height=8)
        self.arbre_dep.heading("#0", text="Élément")
        self.arbre_dep.column("#0", width=170)
        for c, titre, larg in zip(colonnes, ("Rôle", "État", "Version", "Détail"), (230, 70, 80, 200)):
            self.arbre_dep.heading(c, text=titre)
            self.arbre_dep.column(c, width=larg)
        self.arbre_dep.tag_configure("ok", foreground="#118811")
        self.arbre_dep.tag_configure("manque", foreground="#cc2222")
        self.arbre_dep.pack(fill="x", **pad)

        boutons = ttk.Frame(page)
        boutons.pack(fill="x", **pad)
        self.b_controler = bulle(ttk.Button(boutons, text="Contrôler", command=self._controler_dependances),
                                 "Refaire le contrôle des bibliothèques et des modèles.")
        self.b_controler.pack(side="left", padx=4)
        self.b_installer = bulle(ttk.Button(boutons, text="Installer les éléments manquants",
                                            command=lambda: self._installer(False)),
                                 "Installer avec pip uniquement ce qui manque, puis télécharger le modèle des "
                                 "plaques si besoin (connexion internet nécessaire).")
        self.b_installer.pack(side="left", padx=4)
        self.b_maj = bulle(ttk.Button(boutons, text="Tout mettre à jour", command=lambda: self._installer(True)),
                           "Réinstaller toutes les bibliothèques dans leur dernière version. Fermer et "
                           "relancer le programme ensuite.")
        self.b_maj.pack(side="left", padx=4)

        self.journal_dep = tk.Text(page, height=10, wrap="word", state="disabled")
        self.journal_dep.pack(fill="both", expand=True, **pad)
        self._controler_dependances()

    def _ecrire_dep(self, texte: str):
        self.journal_dep.configure(state="normal")
        self.journal_dep.insert("end", texte + "\n")
        self.journal_dep.see("end")
        self.journal_dep.configure(state="disabled")

    def _controler_dependances(self) -> list:
        etats = dep.tout_controler()
        self.arbre_dep.delete(*self.arbre_dep.get_children())
        for e in etats:
            self.arbre_dep.insert("", "end", text=e.nom, tags=("ok" if e.present else "manque",),
                                  values=(e.role, "OK" if e.present else "MANQUE", e.version, e.detail))
        manquants = [e for e in etats if not e.present]
        self.b_installer.configure(state="normal" if manquants else "disabled")
        self.onglets.tab(self.page_dep, text="Dépendances" + (f" ({len(manquants)} ⚠)" if manquants else ""))
        return manquants

    def _controle_demarrage(self):
        manquants = self._controler_dependances()
        if not manquants:
            return
        self.onglets.select(self.page_dep)
        noms = "\n".join(f"  • {e.nom} — {e.detail}" for e in manquants)
        if messagebox.askyesno("Anonymiseur", "Éléments manquants :\n\n" + noms +
                               "\n\nLes installer maintenant ? (connexion internet nécessaire)"):
            self._installer(False)

    def _installer(self, tout: bool):
        if self.fil_dep and self.fil_dep.is_alive():
            return
        if self.fil and self.fil.is_alive():
            messagebox.showwarning("Anonymiseur", "Attendez la fin de l'anonymisation en cours.")
            return
        paquets = list(dep.PAQUETS) if tout else dep.paquets_manquants()
        for b in (self.b_controler, self.b_installer, self.b_maj):
            b.configure(state="disabled")
        self.fil_dep = threading.Thread(target=self._installer_fil, args=(paquets,), daemon=True)
        self.fil_dep.start()

    def _installer_fil(self, paquets):
        msg = self.file_messages.put
        ecrire = lambda t: msg(("dep_log", t))
        ok = dep.installer(paquets, ecrire)
        if ok and paquets:
            ecrire("Installation terminée.")
        elif not ok:
            ecrire("ÉCHEC de l'installation : voir les messages de pip ci-dessus.")
        if ok and not dep.controler_modeles()[1].present:
            dep.telecharger_modele_plaques(ecrire)
        msg(("dep_fin", ok))

    def _modules_prets(self) -> bool:
        if not self.modules_ok:
            self.modules_ok = charger_modules()
        if not self.modules_ok:
            self.onglets.select(self.page_dep)
            messagebox.showwarning("Anonymiseur", "Des dépendances manquent : installez-les depuis "
                                   "l'onglet « Dépendances ».")
        return self.modules_ok

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

    def _montrer_apercu(self, image, titre: str):
        self._apercu_pil = image
        self.apercu_titre.configure(text=titre)
        self._dessiner_apercu()

    def _dessiner_apercu(self):
        if self._apercu_pil is None:
            return
        w, h = max(50, self.apercu.winfo_width() - 4), max(50, self.apercu.winfo_height() - 4)
        img = self._apercu_pil.copy()
        img.thumbnail((w, h))
        self._apercu_tk = ImageTk.PhotoImage(img)
        self.apercu.configure(image=self._apercu_tk, text="")

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
            supprimer_metadonnees=self.v_metadonnees.get(),
            qualite_jpeg=self.v_qualite.get())

    def _memoriser(self):
        ecrire_reglages({
            "source": self.v_source.get(), "sortie": self.v_sortie.get(),
            "sous_dossiers": self.v_sous_dossiers.get(), "visages": self.v_visages.get(),
            "plaques": self.v_plaques.get(), "methode": self.v_methode.get(),
            "force": self.v_force.get(), "sensibilite": self.v_sensibilite.get(),
            "supprimer_metadonnees": self.v_metadonnees.get(), "ignorer_deja_faites": self.v_deja.get(),
            "qualite_jpeg": self.v_qualite.get()})

    def _dossiers(self) -> tuple[Path, Path] | None:
        texte = self.v_source.get().strip()
        src = Path(texte).resolve() if texte else None   # Path("") = dossier courant : à refuser
        if src is None or not src.is_dir():
            messagebox.showerror("Anonymiseur", "Choisissez un dossier de photos existant.")
            return None
        sortie = Path(self.v_sortie.get().strip() or NOM_SORTIE)
        if not sortie.is_absolute():   # « anonymisé » seul = sous-dossier de la source
            sortie = src / sortie
        sortie = sortie.resolve()
        self.v_sortie.set(str(sortie))
        if sortie.resolve() == src.resolve():
            messagebox.showerror("Anonymiseur", "Le dossier de sortie doit être différent du dossier "
                                 "des photos : les originaux ne doivent pas être écrasés.")
            return None
        return src, sortie

    # ------------------------------------------------------------ traitement
    def _lancer(self):
        if not self._modules_prets():
            return
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
        self.b_manuel.configure(state="disabled")
        self.b_arreter.configure(state="normal")
        self.progres.configure(maximum=len(photos), value=0)
        self.compteur.configure(text=f"0 / {len(photos)}")
        self.abandon = False
        prepa = Path(tempfile.mkdtemp(prefix=PREFIXE_PREPA))
        self._ecrire(f"{len(photos)} photo(s) à traiter → {sortie} (copie dans la sortie à la fin)")
        self.fil = threading.Thread(target=self._traiter,
                                    args=(photos, src, sortie, prepa, reg, self.v_deja.get()), daemon=True)
        self.fil.start()

    def _traiter(self, photos, src, sortie, prepa, reg, ignorer_deja):
        """Fil de traitement. Les photos sont écrites dans `prepa` (dossier temporaire) :
        rien n'arrive dans la sortie avant la fin, ou avant l'accord de l'utilisateur s'il arrête."""
        msg = self.file_messages.put
        t0 = time.time()
        zones_toutes = an.charger_zones(sortie)
        faites: list[str] = []
        nb_v = nb_p = nb_err = 0
        interrompu = False
        try:
            det = an.Detecteur(reg)
            for i, p in enumerate(photos, 1):
                if self.arreter.is_set():
                    interrompu = True
                    msg(("log", "Arrêté par l'utilisateur."))
                    break
                cle = p.relative_to(src).as_posix()
                if ignorer_deja and an.chemin_sortie(p, src, sortie).exists() and cle in zones_toutes:
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
                    zones_toutes[cle] = zones
                    v = sum(z.type == "visage" and z.actif for z in zones)
                    pl = sum(z.type == "plaque" and z.actif for z in zones)
                    # toutes les photos iront dans la sortie : floutées ou simplement recompressées
                    resultat = an.flouter(bgr, zones, reg)
                    an.ecrire_image(resultat, pil, an.chemin_sortie(p, src, prepa), reg)
                    faites.append(cle)
                    nb_v += v
                    nb_p += pl
                    texte = f"{cle} : {v} visage(s), {pl} plaque(s)" if v or pl else f"{cle} : rien à flouter"
                    vignette = Image.fromarray(cv2.cvtColor(resultat, cv2.COLOR_BGR2RGB))
                    vignette.thumbnail((1000, 1000))
                    msg(("apercu", (vignette, f"{i}/{len(photos)} — {texte}")))
                    msg(("log", texte))
                except Exception as e:  # une photo illisible ne bloque pas les autres
                    nb_err += 1
                    msg(("log", f"ERREUR {cle} : {e}"))
                msg(("progres", i))
        except Exception as e:
            interrompu = True
            msg(("log", f"ERREUR : {e}"))
        finally:
            msg(("log", f"Traitement terminé en {time.time() - t0:.0f} s : {nb_v} visage(s), {nb_p} plaque(s)"
                        + (f", {nb_err} erreur(s)" if nb_err else "") + "."))
            if self.abandon:
                shutil.rmtree(prepa, ignore_errors=True)
            msg(("fin", {"src": src, "sortie": sortie, "prepa": prepa, "faites": faites,
                         "zones": zones_toutes, "interrompu": interrompu}))

    def _terminer_traitement(self, info):
        """Fin du traitement (fil principal) : copie dans la sortie, ou rien si l'utilisateur refuse."""
        faites, prepa = info["faites"], info["prepa"]
        copier = bool(faites)
        if faites and info["interrompu"]:
            copier = messagebox.askyesno(
                "Anonymiseur", f"Traitement interrompu : {len(faites)} photo(s) déjà traitée(s).\n\n"
                               "Les copier dans le dossier de sortie ?\n(Non : rien n'est copié.)")
        if copier:
            sortie = info["sortie"]
            self.progres.configure(maximum=len(faites), value=0)
            for n, cle in enumerate(faites, 1):
                dest = sortie / cle
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(prepa / cle), str(dest))
                self.progres.configure(value=n)
                self.compteur.configure(text=f"copie {n} / {len(faites)}")
                if n % 10 == 0:
                    self.update()
            zones = an.charger_zones(sortie)                     # zones déjà présentes dans la sortie
            zones.update({k: info["zones"][k] for k in faites})  # + celles des photos copiées
            an.enregistrer_zones(sortie, info["src"], zones)
            self._ecrire(f"{len(faites)} photo(s) copiée(s) dans {sortie}.")
            self._ecrire("Contrôlez le résultat avec « Vérifier / corriger… » : la détection automatique "
                         "peut manquer un visage de profil ou une plaque lointaine.")
        elif faites:
            self._ecrire("Rien n'a été copié dans la sortie.")
        shutil.rmtree(prepa, ignore_errors=True)

    def _lire_messages(self):
        try:
            while True:
                genre, val = self.file_messages.get_nowait()
                if genre == "log":
                    self._ecrire(val)
                elif genre == "apercu":
                    self._montrer_apercu(*val)
                elif genre == "progres":
                    self.progres.configure(value=val)
                    self.compteur.configure(text=f"{val} / {int(self.progres.cget('maximum'))}")
                elif genre == "dep_log":
                    self._ecrire_dep(val)
                elif genre == "dep_fin":
                    self.b_controler.configure(state="normal")
                    self.b_maj.configure(state="normal")
                    manquants = self._controler_dependances()
                    self.modules_ok = charger_modules()
                    if not manquants:
                        messagebox.showinfo("Anonymiseur", "Toutes les dépendances sont installées.")
                    elif val:
                        messagebox.showwarning("Anonymiseur", "Installation faite, mais des éléments restent "
                                               "en défaut. Si un paquet était déjà chargé, fermez et "
                                               "relancez le programme.")
                elif genre == "fin":
                    self.b_arreter.configure(state="disabled")
                    self._terminer_traitement(val)
                    self.b_lancer.configure(state="normal")
                    self.b_verifier.configure(state="normal")
                    self.b_manuel.configure(state="normal")
                    self.b_arreter.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._lire_messages)

    def _verifier(self):
        if not self._modules_prets():
            return
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

    def _mode_manuel(self):
        if not self._modules_prets():
            return
        if self.fil and self.fil.is_alive():
            messagebox.showwarning("Anonymiseur", "Attendez la fin de l'anonymisation en cours.")
            return
        d = self._dossiers()
        if d is None:
            return
        src, sortie = d
        photos = an.lister_photos(src, self.v_sous_dossiers.get(), exclure=sortie)
        if not photos:
            messagebox.showinfo("Anonymiseur", "Aucune photo JPG dans ce dossier.")
            return
        self._memoriser()
        FenetreVerification(self, src, sortie, an.charger_zones(sortie), self.reglages(),
                            manuel=True, photos=photos)

    def _fermer(self):
        self._memoriser()
        if self.fil and self.fil.is_alive():
            if not messagebox.askyesno("Anonymiseur", "Un traitement est en cours. Le quitter ? "
                                       "Rien ne sera copié dans la sortie."):
                return
            self.abandon = True
        self.arreter.set()
        self.destroy()


PREFIXE_PREPA = "anonymiseur_encours_"


def _nettoyer_preparations():
    """Supprime les dossiers temporaires laissés par un traitement abandonné (> 1 h)."""
    for d in Path(tempfile.gettempdir()).glob(PREFIXE_PREPA + "*"):
        try:
            if time.time() - d.stat().st_mtime > 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _meme_zone(a: an.Zone, b: an.Zone) -> bool:
    ix = max(0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.surface() + b.surface() - inter
    return union > 0 and inter / union > 0.5


class FenetreVerification(tk.Toplevel):
    """Contrôle photo par photo.

    Clic gauche : flouter un carré centré sur le clic (taille : molette).
    Clic gauche + glisser : flouter le rectangle tracé.
    Clic droit sur une zone : l'écarter (faux positif) ou la réactiver ;
    une zone ajoutée à la main est supprimée. Ctrl+Z : annuler le dernier ajout.

    Mode vérification : photos déjà traitées, chaque modification est écrite aussitôt.
    Mode manuel (`manuel=True`) : toutes les photos du dossier, défilement aux
    flèches ; rien n'est écrit avant « Terminer et enregistrer » (toutes les photos
    sont alors copiées dans la sortie). Abandon / fermeture : rien sans accord.
    """

    def __init__(self, maitre: Application, src: Path, sortie: Path, zones: dict, reglages: an.Reglages,
                 manuel: bool = False, photos: list[Path] | None = None):
        super().__init__(maitre)
        self.manuel = manuel
        self.title("Mode manuel — flouter au clic" if manuel else "Vérifier / corriger l'anonymisation")
        self.geometry("1200x800")
        self.src, self.sortie, self.zones, self.reg = src, sortie, zones, reglages
        if manuel:
            self.cles = [p.relative_to(src).as_posix() for p in photos or []]
            for k in self.cles:
                self.zones.setdefault(k, [])
        else:
            self.cles = sorted(k for k in zones if (src / k).exists())
        self.indice = 0
        self.bgr = self.pil = None
        self.echelle = 1.0
        self.debut = None
        self.vues: set[str] = set()
        self.modifiees: set[str] = set()
        self.taille = 0.10          # côté du carré flouté au clic, fraction du petit côté de la photo
        self.souris = None
        self.v_apercu = tk.BooleanVar(value=manuel)

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
        enreg = " Rien n'est écrit avant « Terminer et enregistrer »." if manuel else ""
        bulle(ttk.Button(haut, text="◀ Précédente", command=lambda: self._aller(-1)),
              "Photo précédente (flèche ←)." + enreg).pack(side="left", padx=4, pady=4)
        bulle(ttk.Button(haut, text="Suivante ▶", command=lambda: self._aller(1)),
              "Photo suivante (flèche →)." + enreg).pack(side="left", padx=4)
        bulle(ttk.Button(haut, text="Annuler (Ctrl+Z)", command=self._annuler),
              "Retirer la dernière zone ajoutée à la main sur cette photo.").pack(side="left", padx=4)
        bulle(ttk.Checkbutton(haut, text="Voir le résultat flouté", variable=self.v_apercu,
                              command=self._afficher),
              "Coché : l'image montre le résultat tel qu'il sera enregistré.\nDécoché : la photo d'origine, "
              "avec seulement les cadres des zones.").pack(side="left", padx=12)
        if manuel:
            bulle(ttk.Button(haut, text="Abandonner", command=self._abandonner),
                  "Fermer sans rien copier dans la sortie (confirmation demandée).").pack(side="right", padx=4)
            self.b_terminer = bulle(ttk.Button(haut, text="Terminer et enregistrer", command=self._terminer),
                                    "Écrire maintenant dans la sortie TOUTES les photos du dossier (floutées ou "
                                    "simplement recopiées) et le fichier des zones, puis fermer.")
            self.b_terminer.pack(side="right", padx=4)
        texte_aide(droite, AIDE_MANUEL if manuel else AIDE_VERIFICATION).pack(fill="x", padx=6, pady=(0, 4))
        bulle(self.liste, "Cliquer sur une photo pour l'afficher. Entre parenthèses : nombre de zones floutées. "
                          + ("✓ = vue, orange = pas encore vue, * = modifiée (enregistrée à la fin)." if manuel
                             else "En orange : aucune zone floutée, à vérifier."))
        self.info = ttk.Label(droite, text="")
        self.info.pack(fill="x", padx=4)
        if manuel:
            ligne = ttk.Frame(droite)
            ligne.pack(fill="x", padx=4, pady=2)
            self.compteur = ttk.Label(ligne, text="", anchor="e")
            self.compteur.pack(side="right", padx=(8, 0))
            self.progres = bulle(ttk.Progressbar(ligne, mode="determinate", maximum=max(1, len(self.cles))),
                                 "Photos vues / nombre total de photos du dossier ; à la fin, avancement "
                                 "de l'enregistrement.")
            self.progres.pack(side="left", fill="x", expand=True)
        self.canevas = tk.Canvas(droite, background="#202020", highlightthickness=0, cursor="crosshair")
        self.canevas.pack(fill="both", expand=True)
        self.canevas.bind("<Configure>", lambda e: self._afficher())
        self.canevas.bind("<ButtonPress-1>", self._presser)
        self.canevas.bind("<B1-Motion>", self._glisser)
        self.canevas.bind("<ButtonRelease-1>", self._relacher)
        self.canevas.bind("<Button-3>", self._clic_droit)
        self.canevas.bind("<Motion>", self._bouger)
        self.canevas.bind("<Leave>", self._sortir)
        self.bind("<MouseWheel>", self._molette)
        self.bind("<Left>", lambda e: self._aller(-1))
        self.bind("<Right>", lambda e: self._aller(1))
        self.bind("<Control-z>", lambda e: self._annuler())
        self.protocol("WM_DELETE_WINDOW", self._fermer)

        self._remplir_liste()
        self._maj_avancement()
        if self.cles:
            self.liste.selection_set(0)
            self._charger()
        self.focus_force()

    def _libelle(self, cle):
        zs = [z for z in self.zones[cle] if z.actif]
        marque = ""
        if self.manuel:
            marque = (" *" if cle in self.modifiees else "") + (" ✓" if cle in self.vues else "")
        return f"{cle}  ({len(zs)}){marque}"

    def _remplir_liste(self):
        self.liste.delete(0, "end")
        for i, k in enumerate(self.cles):
            self.liste.insert("end", self._libelle(k))
            self._colorer(i)

    def _colorer(self, i):
        # vérification : rien flouté = à regarder ; manuel : pas encore vue
        if self.manuel:
            self.liste.itemconfigure(i, foreground="" if self.cles[i] in self.vues else "#c07000")
        elif not any(z.actif for z in self.zones[self.cles[i]]):
            self.liste.itemconfigure(i, foreground="#c07000")

    def _maj_avancement(self):
        if not self.manuel:
            return
        self.progres.configure(maximum=max(1, len(self.cles)), value=len(self.vues))
        self.compteur.configure(text=f"{len(self.vues)} / {len(self.cles)} vues")

    def _maj_ligne(self, i):
        self.liste.delete(i)
        self.liste.insert(i, self._libelle(self.cles[i]))
        self._colorer(i)
        if i == self.indice:
            self.liste.selection_set(i)

    def _choisir(self):
        sel = self.liste.curselection()
        if sel and sel[0] != self.indice:
            self._aller_a(sel[0])

    def _aller(self, pas):
        if self.cles:
            self._aller_a(max(0, min(len(self.cles) - 1, self.indice + pas)))

    def _aller_a(self, i):
        if i != self.indice:
            self._quitter_photo()
            self.indice = i
            self._charger()
        self.liste.selection_clear(0, "end")
        self.liste.selection_set(self.indice)
        self.liste.see(self.indice)

    def _quitter_photo(self):
        """Rien n'est écrit en changeant de photo (mode manuel : tout à la fin)."""

    def _fermer(self):
        if not self.manuel:
            self.destroy()
            return
        if not self.modifiees and all(an.chemin_sortie(self.src / k, self.src, self.sortie).exists()
                                      for k in self.cles):
            self.destroy()   # rien de nouveau : la sortie est déjà complète
            return
        rep = messagebox.askyesnocancel(
            "Mode manuel", "Enregistrer maintenant dans la sortie toutes les photos du dossier "
                           f"({len(self.cles)}) ?\n\nOui : enregistrer puis fermer.\nNon : fermer sans rien "
                           "copier.\nAnnuler : revenir aux photos.", parent=self)
        if rep is None:
            return
        if rep:
            self._enregistrer_tout()
        self.destroy()

    def _terminer(self):
        self._enregistrer_tout()
        self.destroy()

    def _abandonner(self):
        if self.modifiees and not messagebox.askyesno(
                "Mode manuel", f"{len(self.modifiees)} photo(s) modifiée(s).\n\nFermer sans rien copier "
                               "dans la sortie ?", parent=self):
            return
        self.destroy()

    def _enregistrer_tout(self):
        """Écrit dans la sortie toutes les photos du dossier (floutées ou recopiées) et les zones.
        Les photos déjà présentes et non modifiées ne sont pas réécrites."""
        a_ecrire = [k for k in self.cles if k in self.modifiees
                    or not an.chemin_sortie(self.src / k, self.src, self.sortie).exists()]
        self.b_terminer.configure(state="disabled")
        self.progres.configure(maximum=max(1, len(a_ecrire)), value=0)
        erreurs = 0
        for n, k in enumerate(a_ecrire, 1):
            try:
                bgr, pil = an.lire_image(self.src / k)
                an.ecrire_image(an.flouter(bgr, self.zones.get(k, []), self.reg), pil,
                                an.chemin_sortie(self.src / k, self.src, self.sortie), self.reg)
            except Exception:
                erreurs += 1   # photo illisible : ignorée, comme en automatique
            self.progres.configure(value=n)
            self.compteur.configure(text=f"enregistrement {n} / {len(a_ecrire)}")
            self.update()
        zones = an.charger_zones(self.sortie)
        zones.update({k: v for k, v in self.zones.items() if k in self.cles})
        an.enregistrer_zones(self.sortie, self.src, zones)
        self.modifiees.clear()
        if erreurs:
            messagebox.showwarning("Mode manuel", f"{erreurs} photo(s) illisible(s) n'ont pas pu être "
                                   "enregistrée(s).", parent=self)

    def _charger(self):
        cle = self.cles[self.indice]
        self.bgr, self.pil = an.lire_image(self.src / cle)
        if self.manuel:
            self.vues.add(cle)
            self._maj_ligne(self.indice)
            self._maj_avancement()
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
        etat = ""
        if self.manuel and cle in self.modifiees:
            etat = " — modifiée (enregistrée à la fin)"
        self.info.configure(text=f"{self.indice + 1}/{len(self.cles)} — {cle} : {nv} visage(s) (rouge), "
                                 f"{npl} plaque(s) (bleu), {nm} ajoutée(s) (vert), {nx} écartée(s) (pointillés)"
                                 f" · pinceau {self.taille:.0%}{etat}")
        self._dessiner_pinceau()

    def _vers_image(self, ev):
        return int(ev.x / self.echelle), int(ev.y / self.echelle)

    def _cote_pinceau(self) -> int:
        """Côté du carré flouté au clic, en pixels de la photo."""
        return max(8, int(min(self.bgr.shape[:2]) * self.taille))

    def _dessiner_pinceau(self):
        self.canevas.delete("pinceau")
        if self.souris is None or self.bgr is None or self.debut is not None:
            return
        x, y = self.souris
        r = self._cote_pinceau() * self.echelle / 2
        self.canevas.create_rectangle(x - r, y - r, x + r, y + r, outline="#ffff40", dash=(3, 3), tags="pinceau")

    def _bouger(self, ev):
        self.souris = (ev.x, ev.y)
        self._dessiner_pinceau()

    def _sortir(self, ev):
        self.souris = None
        self.canevas.delete("pinceau")

    def _molette(self, ev):
        if self.souris is None:
            return   # souris hors de l'image (sur la liste : défilement normal)
        self.taille = min(0.6, max(0.02, self.taille * (1.15 if ev.delta > 0 else 1 / 1.15)))
        self._afficher()

    def _presser(self, ev):
        self.debut = (ev.x, ev.y)
        self.canevas.delete("trace")
        self.canevas.delete("pinceau")

    def _glisser(self, ev):
        if self.debut:
            self.canevas.delete("trace")
            self.canevas.create_rectangle(*self.debut, ev.x, ev.y, outline=COULEURS["manuel"], width=2, tags="trace")

    def _relacher(self, ev):
        if not self.debut or self.bgr is None:
            return
        x0, y0 = self.debut
        self.debut = None
        self.canevas.delete("trace")
        h, w = self.bgr.shape[:2]
        e = self.echelle
        if abs(ev.x - x0) < 4 and abs(ev.y - y0) < 4:
            # simple clic : carré centré sur le point cliqué
            cx, cy = self._vers_image(ev)
            if not (0 <= cx < w and 0 <= cy < h):
                return
            r = self._cote_pinceau() // 2
            x1, y1, x2, y2 = cx - r, cy - r, cx + r, cy + r
        elif abs(ev.x - x0) < 4 or abs(ev.y - y0) < 4:
            return   # rectangle trop plat : geste involontaire
        else:
            x1, x2 = sorted((int(x0 / e), int(ev.x / e)))
            y1, y2 = sorted((int(y0 / e), int(ev.y / e)))
        self.zones[self.cles[self.indice]].append(
            an.Zone(max(0, x1), max(0, y1), min(w, x2), min(h, y2), "manuel"))
        self._sauver()

    def _annuler(self):
        zones = self.zones[self.cles[self.indice]] if self.cles else []
        for z in reversed(zones):
            if z.type == "manuel":
                zones.remove(z)
                self._sauver()
                return

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
        """Après une modification : écriture aussitôt (vérification) ou au changement de photo (manuel)."""
        if self.manuel:
            self.modifiees.add(self.cles[self.indice])
        else:
            self._ecrire_photo()
        self._maj_ligne(self.indice)
        self.liste.selection_set(self.indice)
        self._afficher()

    def _ecrire_photo(self):
        """Mode vérification : la photo corrigée est réécrite aussitôt."""
        cle = self.cles[self.indice]
        an.ecrire_image(an.flouter(self.bgr, self.zones[cle], self.reg), self.pil,
                        an.chemin_sortie(self.src / cle, self.src, self.sortie), self.reg)
        an.enregistrer_zones(self.sortie, self.src, self.zones)
        self._maj_ligne(self.indice)


if __name__ == "__main__":
    Application().mainloop()
