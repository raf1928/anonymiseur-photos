# Consignes pour Claude — anonymiseur-photos

- Répondre en français ; l'utilisateur débute avec Git : expliquer sans jargon.
- Début de session : `git fetch` + `git log` (autres postes) puis `git pull` avant toute modification.
- **Aucune photo sur GitHub** (ni originaux ni anonymisées) : `.gitignore` les bloque.
- Toujours pousser le code sur GitHub (`raf1928/anonymiseur-photos`, privé) après modification.
- Tester sur une **copie** dans un dossier temporaire, jamais sur les photos de l'utilisateur.
  Tests de l'interface : rediriger `anonymiseur.FICHIER_REGLAGES` vers un fichier temporaire,
  remplacer `messagebox.show*`, fenêtres invisibles (`attributes('-alpha', 0)`), pas de capture d'écran.
- Code : `anonymisation.py` (détection, floutage, fichiers), `anonymiseur.py` (interface Tkinter).
