# Anonymiseur de photos

Floute les **visages** et les **plaques d'immatriculation** des photos JPG d'un dossier.

## Lancer

```
python anonymiseur.py
```

Onglet **Dépendances** : contrôle des bibliothèques Python et des modèles de détection. S'il manque quelque
chose au démarrage, le programme ouvre cet onglet et propose de l'installer (`pip install` dans le Python qui
exécute le programme, connexion internet nécessaire). Installation manuelle possible :
`pip install -r requirements.txt`. Le modèle des plaques (≈ 27 Mo) est téléchargé une fois dans
`%USERPROFILE%\.cache\open-image-models` ; celui des visages est fourni dans `modeles/`.

## Utilisation

Tout se passe dans une seule fenêtre : **photo d'origine à gauche, résultat à droite**. Un texte explicatif
est affiché ; survoler un bouton ou un réglage affiche une infobulle.

1. **Choisir…** le dossier des photos. La sortie est proposée dans `<dossier>\anonymisé`.
   Le **point à côté du dossier** est rouge tant que des photos sont encore dans le nuage OneDrive / SharePoint ;
   leur téléchargement démarre dès que le dossier est choisi, et le point passe au vert quand toutes les photos
   sont sur l'ordinateur.
2. Options : visages / plaques, méthode (`flou`, `pixels`, `noir`), force, **sensibilité** (1 = détections sûres
   seulement, 5 = trouve davantage avec plus de fausses détections ; 3 conseillé), qualité JPG (50-100, 92 par
   défaut), suppression des métadonnées (le GPS est toujours retiré), sous-dossiers.
3. **Anonymiser** (automatique) : chaque photo s'affiche à gauche telle quelle avec les zones détectées
   (rouge = visage, bleu = plaque, vert = zone manuelle) et à droite floutée, puis le programme passe à la
   suivante. Compter environ 1,5 s par photo de 12 Mpx.
4. **Mode manuel** : même présentation, bandeau rouge « Cliquez sur la zone à flouter » au-dessus du résultat.
   - **← →** : photo précédente / suivante ; **↑ ↓** ou molette : agrandir / réduire le carré de floutage ;
   - **clic** (sur l'une ou l'autre image) : flouter un carré centré sur le clic (cadre jaune = taille) ;
   - glisser : flouter un rectangle ; clic droit sur une zone : la retirer (une détection automatique est
     écartée) ; **Ctrl+Z** : annuler le dernier ajout ;
   - les zones de l'exécution précédente (automatique ou manuelle) sont reprises : le mode manuel sert aussi à
     corriger le résultat automatique.

### Enregistrement

- **Rien n'est copié dans la sortie avant la fin d'une exécution.** Les photos sont préparées dans un dossier
  temporaire.
- À la fin (fin du traitement automatique, ou **Terminer et enregistrer** en mode manuel), le dossier de sortie
  est **vidé de l'exécution précédente** (JPG et fichier des zones ; les autres fichiers sont laissés) puis
  reçoit **toutes** les photos du dossier source en JPG — floutées, ou simplement recopiées et recompressées — et
  `zones_anonymisation.json`, qui mémorise les zones de chaque photo.
- **Arrêter** (automatique) : le programme demande s'il faut enregistrer les photos déjà traitées ; sinon rien
  n'est copié et la sortie reste inchangée. **Abandonner** (manuel) ou fermer le programme : rien n'est copié
  sans accord.
- Par sécurité, le dossier de sortie ne peut pas être le dossier des photos ni l'un de ses dossiers parents.

## Fonctionnement

- Visages : détecteur YuNet (OpenCV). Plaques : YOLOv9 (paquet `open-image-models`). Tout tourne en local,
  aucune photo n'est envoyée sur internet.
- Les grandes photos sont analysées en entier puis par tuiles qui se recouvrent (petits visages, plaques lointaines).
- Le programme s'exclut du mode « efficacité » de Windows 11 (EcoQoS) : sans cela, le calcul est bridé d'un
  facteur 5 à 10 dès que la fenêtre n'est plus au premier plan.
- Le masquage est une mosaïque grossière (puis un flou pour la méthode « flou ») : un simple flou gaussien
  peut parfois être partiellement inversé, une mosaïque non.
- La photo est redressée selon son orientation EXIF.

## Limites

La détection automatique peut manquer un visage de profil, masqué ou très petit, ou une plaque coupée par le
bord de la photo. **Toujours contrôler en mode manuel avant de diffuser des photos.**
