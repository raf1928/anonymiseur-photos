"""Anonymiseur de photos — interface.

Lancement : python anonymiseur.py

Floute les visages et les plaques d'immatriculation des JPG d'un dossier.
Une seule fenêtre : photo d'origine à gauche, résultat à droite, en mode
automatique comme en mode manuel. Les originaux ne sont jamais modifiés ; à la
fin d'une exécution, le dossier de sortie (par défaut « <dossier>/anonymisé »)
est vidé puis reçoit toutes les photos et le fichier des zones.
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
import onedrive

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
    "Floute les visages et les plaques d'immatriculation des photos JPG d'un dossier. Les originaux ne sont "
    "jamais modifiés. À la fin d'une exécution, le dossier de sortie est vidé de l'exécution précédente puis "
    "reçoit TOUTES les photos en JPG (floutées, ou simplement recopiées et compressées) et le fichier "
    "zones_anonymisation.json. Si vous arrêtez ou abandonnez, rien n'est copié sauf si vous le demandez.\n"
    "« Anonymiser » : détection automatique, chaque photo s'affiche à gauche telle quelle et à droite floutée.  "
    "« Mode manuel » : vous floutez vous-même au clic (les zones d'une exécution précédente sont reprises).  "
    "Le point à côté du dossier : rouge = photos pas encore téléchargées de OneDrive, vert = toutes disponibles. "
    "Survolez un bouton ou un réglage pour son aide.")

AIDE_DEPENDANCES = (
    "Le programme a besoin de bibliothèques Python et de deux modèles de détection. Le tableau indique ce "
    "qui est installé (OK) ou manquant (MANQUE). Au démarrage, s'il manque quelque chose, le programme "
    "propose de l'installer. L'installation utilise pip, nécessite une connexion internet et se fait dans "
    "le Python indiqué ci-dessous. Le modèle des plaques (≈ 27 Mo) n'est téléchargé qu'une fois.")

AIDE_AUTO = ("Traitement automatique : à gauche la photo d'origine avec les zones détectées (rouge = visage, "
             "bleu = plaque, vert = ajoutée à la main), à droite le résultat qui sera enregistré.")

AIDE_MANUEL = ("Mode manuel — clic : flouter un carré (cadre jaune) · glisser : flouter un rectangle · "
               "↑ / ↓ ou molette : agrandir / réduire le carré · clic droit sur une zone : la retirer · "
               "Ctrl+Z : annuler · ← / → : photo précédente / suivante. Rien n'est écrit avant "
               "« Terminer et enregistrer ».")

BANDEAU_MANUEL = "Cliquez sur la zone à flouter"
COTE_APERCU = 1600          # côté maximal des images affichées (calculs d'aperçu rapides)


class VuePhoto(tk.Canvas):
    """Affiche une image réduite (PIL) ajustée au cadre, avec les zones éventuelles.

    `facteur` = taille de l'image affichée / taille de la photo d'origine : il sert à
    convertir les clics en coordonnées de la photo d'origine.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, background="#202020", highlightthickness=0, **kw)
        self.image = None
        self.zones = []
        self.facteur = 1.0
        self.echelle = 1.0     # image réduite → écran
        self.dx = self.dy = 0
        self._tk = None
        self.bind("<Configure>", lambda e: self.redessiner())

    def montrer(self, image, facteur: float, zones=None):
        self.image, self.facteur, self.zones = image, facteur, zones or []
        self.redessiner()

    def vider(self, texte: str = ""):
        self.image = None
        self.delete("all")
        if texte:
            self.create_text(self.winfo_width() // 2, self.winfo_height() // 2, text=texte, fill="#a0a0a0",
                             justify="center")

    def redessiner(self):
        if self.image is None:
            return
        cw, ch = max(20, self.winfo_width()), max(20, self.winfo_height())
        w, h = self.image.size
        self.echelle = min(cw / w, ch / h)
        aff = self.image.resize((max(1, int(w * self.echelle)), max(1, int(h * self.echelle))))
        self.dx, self.dy = (cw - aff.width) // 2, (ch - aff.height) // 2
        self._tk = ImageTk.PhotoImage(aff)
        self.delete("all")
        self.create_image(self.dx, self.dy, anchor="nw", image=self._tk)
        e = self.echelle * self.facteur
        for z in self.zones:
            self.create_rectangle(self.dx + z.x1 * e, self.dy + z.y1 * e, self.dx + z.x2 * e, self.dy + z.y2 * e,
                                  outline=COULEURS.get(z.type, "#ffffff"), width=2,
                                  dash=() if z.actif else (4, 4), tags="zone")

    def vers_photo(self, x, y) -> tuple[float, float]:
        """Coordonnées écran → coordonnées dans la photo d'origine."""
        e = self.echelle * self.facteur
        return (x - self.dx) / e, (y - self.dy) / e

    def vers_ecran(self, x, y) -> tuple[float, float]:
        e = self.echelle * self.facteur
        return self.dx + x * e, self.dy + y * e


class ModeManuel:
    """État du mode manuel (photos, zones, position)."""

    def __init__(self, src: Path, sortie: Path, photos: list[Path], zones: dict):
        self.src, self.sortie = src, sortie
        self.cles = [p.relative_to(src).as_posix() for p in photos]
        self.zones = {k: list(zones.get(k, [])) for k in self.cles}
        self.indice = -1
        self.vues: set[str] = set()
        self.modifiees: set[str] = set()
        self.bgr = None          # photo courante pleine résolution
        self.petite = None       # photo courante réduite (affichage)
        self.facteur = 1.0
        self.taille = 0.10       # côté du carré flouté au clic, fraction du petit côté de la photo

    @property
    def cle(self):
        return self.cles[self.indice]


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Anonymiseur de photos — visages et plaques")
        self.geometry("1500x940")
        self.minsize(1150, 700)
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
        self.v_qualite = tk.IntVar(value=r.get("qualite_jpeg", 92))

        self.file_messages: queue.Queue = queue.Queue()
        self.fil: threading.Thread | None = None
        self.fil_dep: threading.Thread | None = None
        self.arreter = threading.Event()
        self.abandon = False             # fermeture pendant un traitement : rien n'est copié
        self.manuel: ModeManuel | None = None
        self.debut = None                # début d'un glisser (vue, x, y)
        self.souris = None               # (vue, x, y) survolée
        self.chargeur = None             # téléchargement OneDrive en cours
        self.photos_source: list = []
        self.modules_ok = charger_modules()
        if self.modules_ok:
            an.desactiver_bridage_windows()

        self.onglets = ttk.Notebook(self)
        self.onglets.pack(fill="both", expand=True)
        self.page_anon = ttk.Frame(self.onglets)
        self.page_dep = ttk.Frame(self.onglets)
        self.onglets.add(self.page_anon, text="Anonymisation")
        self.onglets.add(self.page_dep, text="Dépendances")
        self._construire(self.page_anon)
        self._construire_dependances(self.page_dep)
        self._raccourcis()
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        self.after(100, self._lire_messages)
        self.after(300, self._controle_demarrage)
        self.after(500, self._source_changee)
        self.after(2000, _nettoyer_preparations)

    # ------------------------------------------------------------------ UI
    def _construire(self, page):
        pad = {"padx": 6, "pady": 3}
        texte_aide(page, AIDE_PRINCIPALE).pack(fill="x", padx=10, pady=(6, 2))

        haut = ttk.Frame(page)
        haut.pack(fill="x", padx=4)
        cadre = ttk.LabelFrame(haut, text="Dossiers")
        cadre.pack(side="left", fill="both", expand=True, padx=4, pady=2)
        ttk.Label(cadre, text="Photos (JPG) :").grid(row=0, column=0, sticky="w", **pad)
        self.e_source = bulle(ttk.Entry(cadre, textvariable=self.v_source),
                              "Dossier contenant les photos JPG à anonymiser. Rien n'y est modifié.")
        self.e_source.grid(row=0, column=1, sticky="ew", **pad)
        self.e_source.bind("<Return>", lambda e: self._source_changee())
        self.e_source.bind("<FocusOut>", lambda e: self._source_changee())
        self.voyant = bulle(tk.Canvas(cadre, width=16, height=16, highlightthickness=0),
                            "Rouge : des photos du dossier sont encore dans le nuage OneDrive ; leur téléchargement "
                            "démarre dès que le dossier est choisi.\nVert : toutes les photos sont sur cet "
                            "ordinateur.")
        self.voyant.grid(row=0, column=2, **pad)
        self.l_voyant = ttk.Label(cadre, text="", width=26)
        self.l_voyant.grid(row=0, column=3, sticky="w")
        bulle(ttk.Button(cadre, text="Choisir…", command=self._choisir_source),
              "Choisir le dossier des photos. La sortie est alors proposée dans son sous-dossier "
              "« anonymisé », et le téléchargement OneDrive des photos démarre.").grid(row=0, column=4, **pad)
        ttk.Label(cadre, text="Sortie :").grid(row=1, column=0, sticky="w", **pad)
        bulle(ttk.Entry(cadre, textvariable=self.v_sortie),
              "Dossier où sont écrites les photos anonymisées. Son contenu (JPG et fichier des zones) est "
              "effacé à chaque nouvelle exécution enregistrée.").grid(row=1, column=1, columnspan=3,
                                                                     sticky="ew", **pad)
        bulle(ttk.Button(cadre, text="Choisir…", command=self._choisir_sortie),
              "Choisir un autre dossier de sortie.").grid(row=1, column=4, **pad)
        bulle(ttk.Checkbutton(cadre, text="Inclure les sous-dossiers", variable=self.v_sous_dossiers,
                              command=self._source_changee),
              "Traiter aussi les photos des sous-dossiers ; leur arborescence est reproduite dans la "
              "sortie.").grid(row=2, column=1, sticky="w", **pad)
        cadre.columnconfigure(1, weight=1)

        opt = ttk.LabelFrame(haut, text="Options")
        opt.pack(side="left", fill="both", padx=4, pady=2)
        bulle(ttk.Checkbutton(opt, text="Visages", variable=self.v_visages),
              "Détecter et flouter automatiquement les visages.").grid(row=0, column=0, sticky="w", **pad)
        bulle(ttk.Checkbutton(opt, text="Plaques", variable=self.v_plaques),
              "Détecter et flouter automatiquement les plaques d'immatriculation.").grid(
            row=0, column=1, sticky="w", **pad)
        bulle(ttk.Checkbutton(opt, text="Supprimer les métadonnées", variable=self.v_metadonnees),
              "Coché : les photos de sortie ne contiennent plus aucune information EXIF.\nDécoché : ces "
              "informations sont gardées, sauf la position GPS qui est toujours retirée.").grid(
            row=0, column=2, columnspan=2, sticky="w", **pad)
        ttk.Label(opt, text="Méthode :").grid(row=1, column=0, sticky="w", **pad)
        bulle(ttk.Combobox(opt, textvariable=self.v_methode, state="readonly", width=8,
                           values=["flou", "pixels", "noir"]),
              "flou : mosaïque adoucie (le plus discret).\npixels : mosaïque visible.\n"
              "noir : zone masquée en noir (le plus sûr).").grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Force :").grid(row=1, column=2, sticky="e", **pad)
        bulle(tk.Scale(opt, from_=1, to=5, orient="horizontal", variable=self.v_force, length=120,
                       command=lambda v: self._reglage_change()),
              "1 = léger, 5 = très fort : plus c'est fort, plus les blocs de la mosaïque sont gros.").grid(
            row=1, column=3, sticky="w", **pad)
        ttk.Label(opt, text="Sensibilité :").grid(row=2, column=0, sticky="w", **pad)
        bulle(tk.Scale(opt, from_=1, to=5, orient="horizontal", variable=self.v_sensibilite, length=120),
              "Seuil de la détection automatique. 1 = seulement les détections sûres ; 5 = trouve davantage "
              "(visages de profil, plaques lointaines) mais avec plus de fausses détections. 3 conseillé ; "
              "sur des photos de constat, 3 retrouve la quasi-totalité des plaques.").grid(
            row=2, column=1, sticky="w", **pad)
        ttk.Label(opt, text="Qualité JPG :").grid(row=2, column=2, sticky="e", **pad)
        bulle(tk.Scale(opt, from_=50, to=100, orient="horizontal", variable=self.v_qualite, length=120),
              "Compression des JPG écrits dans la sortie (photos floutées et recopiées). 92 par défaut ; "
              "plus bas = fichiers plus légers mais qualité moindre ; 85-95 conseillé.").grid(
            row=2, column=3, sticky="w", **pad)

        boutons = ttk.Frame(page)
        boutons.pack(fill="x", padx=8, pady=4)
        self.b_lancer = bulle(ttk.Button(boutons, text="Anonymiser", command=self._lancer),
                              "Détection automatique sur toutes les photos du dossier : chaque photo s'affiche "
                              "à gauche telle quelle et à droite floutée. À la fin, la sortie est vidée puis "
                              "reçoit toutes les photos.")
        self.b_lancer.pack(side="left", padx=4)
        self.b_manuel = bulle(ttk.Button(boutons, text="Mode manuel", command=self._entrer_manuel),
                              "Faire défiler les photos (← →) et flouter au clic dans cette même fenêtre. Les "
                              "zones de l'exécution précédente sont reprises. Rien n'est écrit avant « Terminer "
                              "et enregistrer ».")
        self.b_manuel.pack(side="left", padx=4)
        self.b_arreter = bulle(ttk.Button(boutons, text="Arrêter", command=self.arreter.set, state="disabled"),
                               "Interrompre le traitement automatique. Le programme demande alors s'il faut "
                               "copier les photos déjà traitées ; sinon rien n'est copié et la sortie reste "
                               "inchangée.")
        self.b_arreter.pack(side="left", padx=4)
        bulle(ttk.Button(boutons, text="Ouvrir la sortie", command=self._ouvrir_sortie),
              "Ouvrir le dossier de sortie dans l'Explorateur Windows.").pack(side="left", padx=4)

        # barre du mode manuel (affichée seulement en mode manuel)
        self.barre_manuel = ttk.Frame(boutons)
        bulle(ttk.Button(self.barre_manuel, text="◀ Précédente", command=lambda: self._aller(-1)),
              "Photo précédente (flèche ←).").pack(side="left", padx=2)
        bulle(ttk.Button(self.barre_manuel, text="Suivante ▶", command=lambda: self._aller(1)),
              "Photo suivante (flèche →).").pack(side="left", padx=2)
        bulle(ttk.Button(self.barre_manuel, text="Annuler (Ctrl+Z)", command=self._annuler_zone),
              "Retirer la dernière zone ajoutée à la main sur cette photo.").pack(side="left", padx=2)
        self.b_terminer = bulle(ttk.Button(self.barre_manuel, text="Terminer et enregistrer",
                                           command=self._terminer_manuel),
                                "Vider la sortie puis y écrire TOUTES les photos du dossier (floutées ou "
                                "simplement recopiées) et le fichier des zones.")
        self.b_terminer.pack(side="left", padx=(12, 2))
        bulle(ttk.Button(self.barre_manuel, text="Abandonner", command=self._abandonner_manuel),
              "Quitter le mode manuel sans rien copier (confirmation demandée s'il y a des "
              "modifications).").pack(side="left", padx=2)

        # deux vues : original à gauche, résultat à droite
        vues = ttk.Frame(page)
        vues.pack(fill="both", expand=True, padx=8)
        vues.columnconfigure(0, weight=1, uniform="v")
        vues.columnconfigure(1, weight=1, uniform="v")
        vues.rowconfigure(1, weight=1)
        ttk.Label(vues, text="Photo d'origine", anchor="center").grid(row=0, column=0, sticky="ew")
        self.bandeau = tk.Label(vues, text="Résultat (photo de sortie)", anchor="center")
        self.bandeau.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._bandeau_defaut = (self.bandeau.cget("background"), self.bandeau.cget("foreground"))
        self.vue_orig = bulle(VuePhoto(vues), "Photo d'origine (jamais modifiée) avec les zones à flouter.")
        self.vue_orig.grid(row=1, column=0, sticky="nsew", padx=(0, 2))
        self.vue_res = bulle(VuePhoto(vues), "Résultat tel qu'il sera enregistré dans la sortie.")
        self.vue_res.grid(row=1, column=1, sticky="nsew", padx=(2, 0))
        self.l_photo = ttk.Label(vues, text="", anchor="center")
        self.l_photo.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.aide_mode = texte_aide(vues, AIDE_AUTO)
        self.aide_mode.grid(row=3, column=0, columnspan=2, sticky="ew")
        for v in (self.vue_orig, self.vue_res):
            v.configure(cursor="crosshair")
            v.bind("<ButtonPress-1>", lambda e, v=v: self._presser(v, e))
            v.bind("<B1-Motion>", lambda e, v=v: self._glisser(v, e))
            v.bind("<ButtonRelease-1>", lambda e, v=v: self._relacher(v, e))
            v.bind("<Button-3>", lambda e, v=v: self._clic_droit(v, e))
            v.bind("<Motion>", lambda e, v=v: self._bouger(v, e))
            v.bind("<Leave>", lambda e: self._sortir())
            v.bind("<MouseWheel>", lambda e: self._taille_pinceau(1 if e.delta > 0 else -1))

        bas = ttk.Frame(page)
        bas.pack(fill="x", padx=8, pady=(2, 0))
        self.compteur = ttk.Label(bas, text="", width=22, anchor="e")
        self.compteur.pack(side="right", padx=(8, 0))
        self.progres = bulle(ttk.Progressbar(bas, mode="determinate"),
                             "Avancement : photos traitées (ou vues en mode manuel) / total, puis copie dans la "
                             "sortie.")
        self.progres.pack(side="left", fill="x", expand=True)
        self.journal = tk.Text(page, height=4, wrap="word", state="disabled")
        self.journal.pack(fill="x", padx=8, pady=(2, 6))
        self._dessiner_voyant(None)

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

    # ------------------------------------------------------------ dossiers
    def _choisir_source(self):
        d = filedialog.askdirectory(title="Dossier des photos", initialdir=self.v_source.get() or None)
        if d:
            self.v_source.set(os.path.normpath(d))
            self.v_sortie.set(os.path.join(os.path.normpath(d), NOM_SORTIE))
            self._source_changee()

    def _choisir_sortie(self):
        d = filedialog.askdirectory(title="Dossier de sortie", initialdir=self.v_sortie.get() or None)
        if d:
            self.v_sortie.set(os.path.normpath(d))

    def _ouvrir_sortie(self):
        s = self.v_sortie.get()
        if s and Path(s).is_dir():
            os.startfile(s)

    def _dossiers(self, avertir: bool = True) -> tuple[Path, Path] | None:
        def erreur(t):
            if avertir:
                messagebox.showerror("Anonymiseur", t)
            return None
        texte = self.v_source.get().strip()
        src = Path(texte).resolve() if texte else None   # Path("") = dossier courant : à refuser
        if src is None or not src.is_dir():
            return erreur("Choisissez un dossier de photos existant.")
        sortie = Path(self.v_sortie.get().strip() or NOM_SORTIE)
        if not sortie.is_absolute():   # « anonymisé » seul = sous-dossier de la source
            sortie = src / sortie
        sortie = sortie.resolve()
        if avertir:
            self.v_sortie.set(str(sortie))
        if sortie == src:
            return erreur("Le dossier de sortie doit être différent du dossier des photos : les originaux ne "
                          "doivent pas être écrasés.")
        if sortie in src.parents or sortie.parent == sortie:
            # la sortie est vidée à chaque exécution : elle ne doit pas contenir les originaux
            return erreur("Le dossier de sortie ne peut pas contenir le dossier des photos (il est vidé à "
                          "chaque exécution). Choisissez un sous-dossier, par exemple « anonymisé ».")
        return src, sortie

    def _photos(self, src: Path, sortie: Path) -> list:
        return an.lister_photos(src, self.v_sous_dossiers.get(), exclure=sortie)

    # ------------------------------------------------------------ OneDrive
    def _source_changee(self):
        if self.chargeur:
            self.chargeur.arreter()
            self.chargeur = None
        d = self._dossiers(avertir=False) if self.modules_ok else None
        if d is None:
            self.photos_source = []
            self._dessiner_voyant(None)
            return
        self.photos_source = self._photos(*d)
        self.chargeur = onedrive.Chargeur(self.photos_source).demarrer()
        self._surveiller_voyant()

    def _surveiller_voyant(self):
        if not self.photos_source:
            self._dessiner_voyant(None)
            return
        locales = onedrive.compter_locales(self.photos_source)
        total = len(self.photos_source)
        self._dessiner_voyant(locales == total, f"{locales} / {total} photos disponibles"
                              + ("" if locales == total else " (téléchargement…)"))
        if locales < total and self.chargeur and self.chargeur.actif():
            self.after(1500, self._surveiller_voyant)
        elif locales < total:
            self.l_voyant.configure(text=f"{locales} / {total} disponibles (non téléchargées)")

    def _dessiner_voyant(self, ok, texte: str = ""):
        self.voyant.delete("all")
        if ok is not None:
            self.voyant.create_oval(2, 2, 14, 14, fill="#20b040" if ok else "#e02020", outline="")
        self.l_voyant.configure(text=texte)

    # ------------------------------------------------------------ réglages
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
            supprimer_metadonnees=self.v_metadonnees.get(), qualite_jpeg=self.v_qualite.get())

    def _memoriser(self):
        ecrire_reglages({
            "source": self.v_source.get(), "sortie": self.v_sortie.get(),
            "sous_dossiers": self.v_sous_dossiers.get(), "visages": self.v_visages.get(),
            "plaques": self.v_plaques.get(), "methode": self.v_methode.get(),
            "force": self.v_force.get(), "sensibilite": self.v_sensibilite.get(),
            "supprimer_metadonnees": self.v_metadonnees.get(), "qualite_jpeg": self.v_qualite.get()})

    def _reglage_change(self):
        if self.manuel and self.manuel.petite is not None:
            self._afficher_manuel()

    def _occupe(self, actif: bool):
        """Boutons pendant un traitement automatique ou le mode manuel."""
        etat = "disabled" if actif else "normal"
        self.b_lancer.configure(state=etat)
        self.b_manuel.configure(state=etat)

    # ------------------------------------------------------------ publication
    def _publier(self, src: Path, sortie: Path, prepa: Path, cles: list, zones: dict):
        """Vide la sortie de l'exécution précédente puis y place les photos préparées et les zones."""
        effaces = an.effacer_sortie(sortie)
        sortie.mkdir(parents=True, exist_ok=True)
        self.progres.configure(maximum=max(1, len(cles)), value=0)
        for n, cle in enumerate(cles, 1):
            dest = sortie / cle
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(prepa / cle), str(dest))
            self.progres.configure(value=n)
            self.compteur.configure(text=f"copie {n} / {len(cles)}")
            if n % 10 == 0:
                self.update()
        an.enregistrer_zones(sortie, src, {k: zones[k] for k in cles})
        if effaces:
            self._ecrire(f"{effaces} photo(s) de l'exécution précédente effacée(s).")
        self._ecrire(f"{len(cles)} photo(s) enregistrée(s) dans {sortie}.")

    # ------------------------------------------------------------ automatique
    def _lancer(self):
        if not self._modules_prets() or self.manuel:
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
        photos = self._photos(src, sortie)
        if not photos:
            messagebox.showinfo("Anonymiseur", "Aucune photo JPG dans ce dossier.")
            return
        self.arreter.clear()
        self.abandon = False
        self._occupe(True)
        self.b_arreter.configure(state="normal")
        self.progres.configure(maximum=len(photos), value=0)
        self.compteur.configure(text=f"0 / {len(photos)}")
        self._mode_affichage(manuel=False)
        prepa = Path(tempfile.mkdtemp(prefix=PREFIXE_PREPA))
        self._ecrire(f"{len(photos)} photo(s) à traiter → {sortie}")
        self.fil = threading.Thread(target=self._traiter, args=(photos, src, sortie, prepa, reg), daemon=True)
        self.fil.start()

    def _traiter(self, photos, src, sortie, prepa, reg):
        """Fil de traitement. Les photos sont écrites dans `prepa` (dossier temporaire) :
        rien n'arrive dans la sortie avant la fin, ou avant l'accord de l'utilisateur s'il arrête."""
        msg = self.file_messages.put
        t0 = time.time()
        anciennes = an.charger_zones(sortie)     # zones ajoutées / écartées à la main : reprises
        zones_toutes: dict = {}
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
                try:
                    bgr, pil = an.lire_image(p)
                    manuelles = [z for z in anciennes.get(cle, []) if z.type == "manuel"]
                    ecartees = [z for z in anciennes.get(cle, []) if not z.actif and z.type != "manuel"]
                    zones = det.detecter(bgr)
                    for z in zones:
                        if any(_meme_zone(z, e) for e in ecartees):
                            z.actif = False
                    zones += manuelles
                    zones_toutes[cle] = zones
                    resultat = an.flouter(bgr, zones, reg)
                    an.ecrire_image(resultat, pil, an.chemin_sortie(p, src, prepa), reg)
                    faites.append(cle)
                    v = sum(z.type == "visage" and z.actif for z in zones)
                    pl = sum(z.type == "plaque" and z.actif for z in zones)
                    nb_v += v
                    nb_p += pl
                    texte = f"{cle} : {v} visage(s), {pl} plaque(s)" if v or pl else f"{cle} : rien à flouter"
                    petite_o, f = an.reduire(bgr, COTE_APERCU)
                    petite_r, _ = an.reduire(resultat, COTE_APERCU)
                    msg(("photo", (_vers_pil(petite_o), _vers_pil(petite_r), f, zones, f"{i}/{len(photos)} — {texte}")))
                    msg(("log", texte))
                except Exception as e:  # une photo illisible ne bloque pas les autres
                    nb_err += 1
                    msg(("log", f"ERREUR {cle} : {e}"))
                msg(("progres", i))
        except Exception as e:
            interrompu = True
            msg(("log", f"ERREUR : {e}"))
        finally:
            duree = time.time() - t0
            msg(("log", f"Traitement terminé en {duree:.0f} s ({duree / max(1, len(faites)):.1f} s par photo) : "
                        f"{nb_v} visage(s), {nb_p} plaque(s)" + (f", {nb_err} erreur(s)" if nb_err else "") + "."))
            if self.abandon:
                shutil.rmtree(prepa, ignore_errors=True)
            msg(("fin", {"src": src, "sortie": sortie, "prepa": prepa, "faites": faites,
                         "zones": zones_toutes, "interrompu": interrompu}))

    def _terminer_traitement(self, info):
        """Fin du traitement (fil principal) : publication, ou rien si l'utilisateur refuse."""
        faites, prepa = info["faites"], info["prepa"]
        copier = bool(faites)
        if faites and info["interrompu"]:
            copier = messagebox.askyesno(
                "Anonymiseur", f"Traitement interrompu : {len(faites)} photo(s) déjà traitée(s).\n\n"
                               "Les enregistrer dans le dossier de sortie ? Son contenu précédent sera effacé.\n"
                               "(Non : rien n'est copié, la sortie reste inchangée.)")
        if copier:
            self._publier(info["src"], info["sortie"], prepa, faites, info["zones"])
        elif faites:
            self._ecrire("Rien n'a été copié dans la sortie.")
        shutil.rmtree(prepa, ignore_errors=True)

    def _lire_messages(self):
        try:
            while True:
                genre, val = self.file_messages.get_nowait()
                if genre == "log":
                    self._ecrire(val)
                elif genre == "photo":
                    orig, res, f, zones, titre = val
                    self.vue_orig.montrer(orig, f, zones)
                    self.vue_res.montrer(res, f)
                    self.l_photo.configure(text=titre)
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
                        self._source_changee()
                    elif val:
                        messagebox.showwarning("Anonymiseur", "Installation faite, mais des éléments restent "
                                               "en défaut. Si un paquet était déjà chargé, fermez et "
                                               "relancez le programme.")
                elif genre == "fin":
                    self.b_arreter.configure(state="disabled")
                    self._terminer_traitement(val)
                    self._occupe(False)
        except queue.Empty:
            pass
        self.after(50, self._lire_messages)

    # ------------------------------------------------------------ mode manuel
    def _mode_affichage(self, manuel: bool):
        if manuel:
            self.bandeau.configure(text=BANDEAU_MANUEL, background="#d01818", foreground="#ffffff",
                                   font=("Segoe UI", 11, "bold"))
            self.aide_mode.configure(text=AIDE_MANUEL)
            self.barre_manuel.pack(side="left", padx=(16, 0))
        else:
            self.bandeau.configure(text="Résultat (photo de sortie)", background=self._bandeau_defaut[0],
                                   foreground=self._bandeau_defaut[1], font="TkDefaultFont")
            self.aide_mode.configure(text=AIDE_AUTO)
            self.barre_manuel.pack_forget()

    def _entrer_manuel(self):
        if not self._modules_prets() or (self.fil and self.fil.is_alive()):
            return
        d = self._dossiers()
        if d is None:
            return
        src, sortie = d
        photos = self._photos(src, sortie)
        if not photos:
            messagebox.showinfo("Anonymiseur", "Aucune photo JPG dans ce dossier.")
            return
        self._memoriser()
        self.manuel = ModeManuel(src, sortie, photos, an.charger_zones(sortie))
        self._occupe(True)
        self._mode_affichage(manuel=True)
        self._ecrire(f"Mode manuel : {len(photos)} photo(s). Rien n'est écrit avant « Terminer et enregistrer ».")
        self._aller_a(0)
        self.vue_res.focus_set()

    def _quitter_manuel(self):
        self.manuel = None
        self._mode_affichage(manuel=False)
        self._occupe(False)
        self.vue_orig.vider()
        self.vue_res.vider()
        self.l_photo.configure(text="")

    def _aller(self, pas: int):
        if self.manuel:
            self._aller_a(max(0, min(len(self.manuel.cles) - 1, self.manuel.indice + pas)))

    def _aller_a(self, i: int):
        m = self.manuel
        if m is None or i == m.indice:
            return
        m.indice = i
        try:
            m.bgr, _ = an.lire_image(m.src / m.cle)
        except Exception as e:
            m.bgr = None
            self.vue_orig.vider(f"Photo illisible :\n{e}")
            self.vue_res.vider()
            self.l_photo.configure(text=f"{i + 1}/{len(m.cles)} — {m.cle} : illisible")
            return
        m.petite, m.facteur = an.reduire(m.bgr, COTE_APERCU)
        m.vues.add(m.cle)
        self.progres.configure(maximum=len(m.cles), value=len(m.vues))
        self.compteur.configure(text=f"{len(m.vues)} / {len(m.cles)} vues")
        self._afficher_manuel()

    def _afficher_manuel(self):
        m = self.manuel
        if m is None or m.petite is None:
            return
        zones = m.zones[m.cle]
        reduites = an.zones_reduites(zones, m.facteur)
        resultat = an.flouter(m.petite, reduites, self.reglages())
        self.vue_orig.montrer(_vers_pil(m.petite), m.facteur, zones)
        self.vue_res.montrer(_vers_pil(resultat), m.facteur, [])
        nv = sum(z.type == "visage" and z.actif for z in zones)
        npl = sum(z.type == "plaque" and z.actif for z in zones)
        nm = sum(z.type == "manuel" for z in zones)
        self.l_photo.configure(text=f"{m.indice + 1}/{len(m.cles)} — {m.cle} : {nv} visage(s), {npl} plaque(s), "
                                    f"{nm} zone(s) manuelle(s)" + ("  — modifiée" if m.cle in m.modifiees else "")
                                    + f"  · carré {m.taille:.0%}")
        self._dessiner_pinceau()

    def _modifiee(self):
        self.manuel.modifiees.add(self.manuel.cle)
        self._afficher_manuel()

    def _cote_pinceau(self) -> int:
        m = self.manuel
        return max(8, int(min(m.bgr.shape[:2]) * m.taille))

    def _dessiner_pinceau(self):
        for v in (self.vue_orig, self.vue_res):
            v.delete("pinceau")
        if not self.manuel or self.manuel.bgr is None or self.souris is None or self.debut is not None:
            return
        vue, x, y = self.souris
        px, py = vue.vers_photo(x, y)
        r = self._cote_pinceau() / 2
        for v in (self.vue_orig, self.vue_res):   # même cadre sur les deux images
            x1, y1 = v.vers_ecran(px - r, py - r)
            x2, y2 = v.vers_ecran(px + r, py + r)
            v.create_rectangle(x1, y1, x2, y2, outline="#ffff40", dash=(3, 3), width=2, tags="pinceau")

    def _bouger(self, vue, ev):
        self.souris = (vue, ev.x, ev.y)
        self._dessiner_pinceau()

    def _sortir(self):
        self.souris = None
        self._dessiner_pinceau()

    def _taille_pinceau(self, sens: int):
        if not self.manuel:
            return
        m = self.manuel
        m.taille = min(0.6, max(0.02, m.taille * (1.15 if sens > 0 else 1 / 1.15)))
        self._afficher_manuel()

    def _presser(self, vue, ev):
        if not self.manuel or self.manuel.bgr is None:
            return
        vue.focus_set()
        self.debut = (vue, ev.x, ev.y)
        self._dessiner_pinceau()

    def _glisser(self, vue, ev):
        if self.debut and self.debut[0] is vue:
            vue.delete("trace")
            vue.create_rectangle(self.debut[1], self.debut[2], ev.x, ev.y, outline=COULEURS["manuel"], width=2,
                                 tags="trace")

    def _relacher(self, vue, ev):
        if not self.debut or self.debut[0] is not vue or not self.manuel:
            self.debut = None
            return
        _, x0, y0 = self.debut
        self.debut = None
        vue.delete("trace")
        m = self.manuel
        h, w = m.bgr.shape[:2]
        if abs(ev.x - x0) < 4 and abs(ev.y - y0) < 4:
            cx, cy = vue.vers_photo(ev.x, ev.y)       # simple clic : carré centré sur le point
            if not (0 <= cx < w and 0 <= cy < h):
                return
            r = self._cote_pinceau() // 2
            x1, y1, x2, y2 = cx - r, cy - r, cx + r, cy + r
        elif abs(ev.x - x0) < 4 or abs(ev.y - y0) < 4:
            return   # rectangle trop plat : geste involontaire
        else:
            (ax, ay), (bx, by) = vue.vers_photo(x0, y0), vue.vers_photo(ev.x, ev.y)
            x1, x2 = sorted((ax, bx))
            y1, y2 = sorted((ay, by))
        m.zones[m.cle].append(an.Zone(int(max(0, x1)), int(max(0, y1)), int(min(w, x2)), int(min(h, y2)),
                                      "manuel"))
        self._modifiee()

    def _clic_droit(self, vue, ev):
        if not self.manuel or self.manuel.bgr is None:
            return
        x, y = vue.vers_photo(ev.x, ev.y)
        zones = self.manuel.zones[self.manuel.cle]
        dedans = [z for z in zones if z.x1 <= x <= z.x2 and z.y1 <= y <= z.y2]
        if not dedans:
            return
        z = min(dedans, key=lambda q: q.surface())   # la plus petite sous le curseur
        if z.type == "manuel":
            zones.remove(z)
        else:
            z.actif = not z.actif                    # détection écartée / réactivée
        self._modifiee()

    def _annuler_zone(self):
        if not self.manuel:
            return
        zones = self.manuel.zones[self.manuel.cle]
        for z in reversed(zones):
            if z.type == "manuel":
                zones.remove(z)
                self._modifiee()
                return

    def _terminer_manuel(self):
        """Écrit toutes les photos (floutées ou recopiées) dans un dossier temporaire puis publie."""
        m = self.manuel
        if m is None:
            return
        reg = self.reglages()
        prepa = Path(tempfile.mkdtemp(prefix=PREFIXE_PREPA))
        self.b_terminer.configure(state="disabled")
        self.progres.configure(maximum=len(m.cles), value=0)
        faites, erreurs = [], 0
        try:
            for n, cle in enumerate(m.cles, 1):
                try:
                    bgr, pil = an.lire_image(m.src / cle)
                    an.ecrire_image(an.flouter(bgr, m.zones[cle], reg), pil, prepa / cle, reg)
                    faites.append(cle)
                except Exception as e:
                    erreurs += 1
                    self._ecrire(f"ERREUR {cle} : {e}")
                self.progres.configure(value=n)
                self.compteur.configure(text=f"préparation {n} / {len(m.cles)}")
                self.update()
            self._publier(m.src, m.sortie, prepa, faites, m.zones)
        finally:
            shutil.rmtree(prepa, ignore_errors=True)
            self.b_terminer.configure(state="normal")
        if erreurs:
            messagebox.showwarning("Anonymiseur", f"{erreurs} photo(s) illisible(s) n'ont pas pu être "
                                   "enregistrée(s).")
        self._quitter_manuel()

    def _abandonner_manuel(self) -> bool:
        m = self.manuel
        if m is None:
            return True
        if m.modifiees and not messagebox.askyesno(
                "Anonymiseur", f"{len(m.modifiees)} photo(s) modifiée(s).\n\nQuitter le mode manuel sans rien "
                               "copier dans la sortie ?"):
            return False
        self._ecrire("Mode manuel abandonné : rien n'a été copié.")
        self._quitter_manuel()
        return True

    # ------------------------------------------------------------ clavier
    def _raccourcis(self):
        def si_manuel(action):
            def f(ev):
                # pas pendant la saisie dans un champ ou le réglage d'un curseur
                if not self.manuel or isinstance(ev.widget, (tk.Entry, ttk.Entry, tk.Scale, ttk.Combobox)):
                    return None
                action()
                return "break"
            return f
        self.bind_all("<Left>", si_manuel(lambda: self._aller(-1)))
        self.bind_all("<Right>", si_manuel(lambda: self._aller(1)))
        self.bind_all("<Up>", si_manuel(lambda: self._taille_pinceau(1)))
        self.bind_all("<Down>", si_manuel(lambda: self._taille_pinceau(-1)))
        self.bind_all("<Control-z>", si_manuel(self._annuler_zone))

    def _fermer(self):
        self._memoriser()
        if self.manuel and self.manuel.modifiees:
            rep = messagebox.askyesnocancel(
                "Anonymiseur", "Mode manuel en cours avec des modifications.\n\nOui : enregistrer toutes les "
                               "photos dans la sortie puis quitter.\nNon : quitter sans rien copier.\n"
                               "Annuler : revenir.")
            if rep is None:
                return
            if rep:
                self._terminer_manuel()
        if self.fil and self.fil.is_alive():
            if not messagebox.askyesno("Anonymiseur", "Un traitement est en cours. Le quitter ? "
                                       "Rien ne sera copié dans la sortie."):
                return
            self.abandon = True
        if self.chargeur:
            self.chargeur.arreter()
        self.arreter.set()
        self.destroy()


def _vers_pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def _meme_zone(a, b) -> bool:
    ix = max(0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.surface() + b.surface() - inter
    return union > 0 and inter / union > 0.5


PREFIXE_PREPA = "anonymiseur_encours_"


def _nettoyer_preparations():
    """Supprime les dossiers temporaires laissés par un traitement abandonné (> 1 h)."""
    for d in Path(tempfile.gettempdir()).glob(PREFIXE_PREPA + "*"):
        try:
            if time.time() - d.stat().st_mtime > 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


if __name__ == "__main__":
    Application().mainloop()
