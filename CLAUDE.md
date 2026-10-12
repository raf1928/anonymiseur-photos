# Consignes pour Claude — anonymiseur-photos

- Répondre en français ; l'utilisateur débute avec Git : expliquer sans jargon.
- Début de session : `git fetch` + `git log` (autres postes) puis `git pull` avant toute modification.
- **Aucune photo sur GitHub** (ni originaux ni anonymisées) : `.gitignore` les bloque.
- Toujours pousser le code sur GitHub (`raf1928/anonymiseur-photos`, privé) après modification.
- Tester sur une **copie** dans un dossier temporaire, jamais sur les photos de l'utilisateur.
  Tests de l'interface : rediriger `anonymiseur.FICHIER_REGLAGES` vers un fichier temporaire,
  rediriger aussi `anonymisation.DOSSIER_ZONES` (zones mémorisées dans %LOCALAPPDATA%),
  remplacer `messagebox.show*`, fenêtres invisibles (`attributes('-alpha', 0)`), pas de capture d'écran.
- Code : `anonymisation.py` (détection, floutage, fichiers), `anonymiseur.py` (interface Tkinter),
  `dependances.py` (contrôle/installation, bibliothèque standard uniquement : ne pas y importer cv2/PIL).
  Dans `anonymiseur.py`, cv2/PIL/anonymisation sont chargés par `charger_modules()`, jamais en tête de fichier.
- Le dossier de sortie ne contient QUE des JPG (demande de l'utilisateur) : toutes les photos source, floutées ou recopiées. Aucun fichier de travail (json…) dans la sortie.
