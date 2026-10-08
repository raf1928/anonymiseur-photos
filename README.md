# Anonymiseur de photos

Floute automatiquement les **visages** et les **plaques d'immatriculation** des photos JPG d'un dossier.

## Lancer

```
python anonymiseur.py
```

Onglet **Dépendances** : contrôle des bibliothèques Python et des modèles de détection (version, état).
S'il manque quelque chose au démarrage, le programme ouvre cet onglet et propose de l'installer
(`pip install` dans le Python qui exécute le programme, connexion internet nécessaire). Boutons
« Installer les éléments manquants » et « Tout mettre à jour ». Installation manuelle possible :
`pip install -r requirements.txt`.

Au premier usage, le modèle de détection des plaques (≈ 27 Mo) est téléchargé dans
`%USERPROFILE%\.cache\open-image-models`. Le modèle des visages est fourni dans `modeles/`.

## Utilisation

1. **Choisir…** le dossier des photos. La sortie est proposée dans `<dossier>\anonymisé`.
2. Options : visages / plaques, méthode (`flou`, `pixels`, `noir`), force, sensibilité,
   sous-dossiers, suppression des métadonnées.
3. **Anonymiser**. Les originaux ne sont **jamais modifiés**.
4. **Vérifier / corriger…** : contrôle photo par photo.
   - clic : flouter un carré (taille à la molette) ; glisser : ajouter un rectangle (vert) ;
   - clic droit sur une zone : l'écarter (fausse détection) ou la réactiver ; une zone ajoutée est supprimée ;
   - flèches ← → : photo précédente / suivante ;
   - les photos sans aucune zone floutée apparaissent en orange dans la liste.

   Chaque correction réécrit aussitôt la photo anonymisée. Les corrections sont mémorisées dans
   `anonymisé\zones_anonymisation.json` et conservées si l'on relance l'anonymisation.

### Mode manuel

Bouton **Mode manuel…** : toutes les photos du dossier défilent, sans détection automatique préalable.

- flèches **← →** : photo précédente / suivante ;
- **clic** sur l'image : floute un carré centré sur le clic (cadre jaune en pointillés = taille) ;
- **molette** sur l'image : agrandit / réduit ce carré ;
- glisser : floute le rectangle tracé ; clic droit sur une zone : la retirer ; **Ctrl+Z** : annuler le dernier ajout ;
- la photo est **enregistrée dès qu'on passe à une autre** (ou qu'on ferme la fenêtre), même sans zone :
  on obtient alors une copie sans métadonnées. Les photos enregistrées portent ✓ dans la liste,
  les autres sont en orange.

Les deux modes partagent les mêmes zones : on peut lancer l'automatique puis compléter en manuel.

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
