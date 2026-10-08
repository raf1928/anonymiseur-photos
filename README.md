# Anonymiseur de photos

Floute automatiquement les **visages** et les **plaques d'immatriculation** des photos JPG d'un dossier.

## Lancer

```
pip install -r requirements.txt
python anonymiseur.py
```

Au premier usage, le modèle de détection des plaques (≈ 27 Mo) est téléchargé dans
`%USERPROFILE%\.cache\open-image-models`. Le modèle des visages est fourni dans `modeles/`.

## Utilisation

1. **Choisir…** le dossier des photos. La sortie est proposée dans `<dossier>\anonymisé`.
2. Options : visages / plaques, méthode (`flou`, `pixels`, `noir`), force, sensibilité,
   sous-dossiers, suppression des métadonnées.
3. **Anonymiser**. Les originaux ne sont **jamais modifiés**.
4. **Vérifier / corriger…** : contrôle photo par photo.
   - glisser avec le clic gauche : ajouter une zone à flouter (vert) ;
   - clic droit sur une zone : l'écarter (fausse détection) ou la réactiver ; une zone ajoutée est supprimée ;
   - flèches ← → : photo précédente / suivante ;
   - les photos sans aucune zone floutée apparaissent en orange dans la liste.

   Chaque correction réécrit aussitôt la photo anonymisée. Les corrections sont mémorisées dans
   `anonymisé\zones_anonymisation.json` et conservées si l'on relance l'anonymisation.

## Fonctionnement

- Visages : détecteur YuNet (OpenCV). Plaques : YOLOv9 (paquet `open-image-models`). Tout tourne en local,
  aucune photo n'est envoyée sur internet.
- Les grandes photos sont analysées en entier puis par tuiles qui se recouvrent (petits visages, plaques lointaines).
- Le masquage est une mosaïque grossière (puis un flou pour la méthode « flou ») : un simple flou gaussien
  peut parfois être partiellement inversé, une mosaïque non.
- La photo est redressée selon son orientation EXIF. Métadonnées : toutes supprimées par défaut ; si on les
  garde, la position **GPS est retirée quand même**.

## Limites

La détection automatique peut manquer un visage de profil, masqué, très flou ou très petit, ou une plaque
très inclinée. **Toujours passer par « Vérifier / corriger… » avant de diffuser des photos.**
