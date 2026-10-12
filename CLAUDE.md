# Consignes pour Claude — anonymiseur-photos

- Répondre en français ; l'utilisateur débute avec Git : expliquer sans jargon.
- Début de session : `git fetch` + `git log` (autres postes) puis `git pull` avant toute modification.
- **Aucune photo sur GitHub** (ni originaux ni anonymisées) : `.gitignore` les bloque.
- Toujours pousser le code sur GitHub (`raf1928/anonymiseur-photos`, privé) après modification.
- Tester sur une **copie** dans un dossier temporaire, jamais sur les photos de l'utilisateur.
  Tests de l'interface : rediriger `anonymiseur.FICHIER_REGLAGES` vers un fichier temporaire,
  rediriger aussi `anonymisation.DOSSIER_ZONES` (ancien emplacement des zones, %LOCALAPPDATA%),
  remplacer `messagebox.show*`, fenêtres invisibles (`attributes('-alpha', 0)`), pas de capture d'écran.
- Code : `anonymisation.py` (détection, floutage, fichiers), `anonymiseur.py` (interface Tkinter),
  `onedrive.py` (disponibilité / téléchargement des photos OneDrive),
  `dependances.py` (contrôle/installation, bibliothèque standard uniquement : ne pas y importer cv2/PIL).
  Dans `anonymiseur.py`, cv2/PIL/anonymisation sont chargés par `charger_modules()`, jamais en tête de fichier.
- Demandes de l'utilisateur (2026-10-12) : une seule fenêtre, original à gauche / résultat à droite, en automatique (défilement visible) comme en manuel (bandeau rouge « Cliquez sur la zone à flouter », ← → photos, ↑ ↓ taille du carré). Sortie = TOUTES les photos source en JPG + `zones_anonymisation.json` ; une nouvelle exécution efface d'abord la précédente ; rien n'est copié avant la fin, ni sans accord en cas d'arrêt / abandon. Point rouge / vert à côté du dossier = photos OneDrive pas encore / toutes téléchargées (`onedrive.py`).
- Lenteur : Windows 11 bride le processus (EcoQoS) → `anonymisation.desactiver_bridage_windows()` ; ne pas l'enlever (8,5 s → 1,6 s par photo sur i9-13900).
