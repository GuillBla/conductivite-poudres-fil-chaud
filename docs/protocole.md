# Protocole de mesure

## Avant l'essai

1. **Décrire le montage** dans un fichier TOML : partir de
   `config/montage_recommande.toml` et indiquer les dimensions réelles.
2. **Dimensionner l'essai** :
   ```bash
   python -m hotwire design --config config/mon_montage.toml --duration 300 --plot design.png
   ```
   Points à vérifier dans la sortie :
   * la fenêtre de temps où la méthode de la pente est juste (lignes `<- OK`) ;
   * l'échauffement du fil : quelques kelvins à quelques dizaines de kelvins, jamais plus de 150 °C ;
   * la résolution de la chaîne de mesure, qui doit être petite devant l'échauffement.
3. **Valider à blanc** avec une simulation au même format qu'un vrai essai :
   ```bash
   python -m hotwire simulate --config config/mon_montage.toml --duration 300 --baseline 30 --period 1 --out data/sim.csv
   python -m hotwire analyze data/sim.csv --config config/mon_montage.toml --t-min 10 --t-max 300
   ```
4. **Étalonner, si possible, sur un matériau connu** avant de mesurer une
   poudre inconnue. Par exemple :
   * eau gélifiée avec 0,5 % d'agar, pour éviter la convection : $k \approx 0{,}60$ W/m/K à 20 °C ;
   * glycérine : $k \approx 0{,}29$ W/m/K ;
   * sable de quartz sec : 0,25 à 0,35 W/m/K selon la granulométrie (moins reproductible).

## Préparation de l'échantillon

* Remplir le tube par couches et tasser de la même façon à chaque essai. La
  conductivité d'une poudre dépend beaucoup de sa compacité : **noter la
  masse de poudre et la hauteur remplie** pour en déduire la masse volumique
  apparente.
* Le fil doit rester tendu et centré (guides en haut et en bas).
* Le capteur est collé à mi-hauteur du fil, avec une colle thermique fine ou
  un point de vernis.
* Laisser l'ensemble revenir à l'équilibre thermique : au moins 30 min après
  la manipulation, à l'abri des courants d'air.

## Essai

```bash
python -m hotwire acquire --port COM3 --out data/2026-11-07_sable_1.csv --duration 300 --baseline 30
```

Le programme envoie `S` à l'Arduino : 30 s de ligne de base, puis mise en
chauffe. L'origine des temps sera placée automatiquement à la mise en
chauffe, grâce à la colonne `heater`. L'enregistrement s'arrête à la fin de
la durée prévue, ou avec Ctrl+C (la chauffe est alors coupée).

**Mesurer pendant la chauffe** la tension aux bornes du fil seul et le
courant, puis noter $P = UI$ et la longueur chauffée $L$. On peut les ajouter
en commentaire en tête du CSV ; `analyze` les lira automatiquement :

```
# power=0.812 length=0.200
```

Entre deux essais sur le même échantillon, attendre que la température soit
revenue à sa valeur initiale, soit environ 10 fois la durée de chauffe.
**Répéter 3 fois** et retenir la moyenne et l'écart-type.

## Analyse

```bash
python -m hotwire analyze data/2026-11-07_sable_1.csv --config config/mon_montage.toml \
       --t-min 10 --t-max 300 --method all --plot resultats.png
```

* Le graphique en échelle log doit montrer **une droite** sur la fenêtre
  choisie. Une courbure vers le haut aux temps longs signifie que la chaleur
  atteint la paroi : réduire `--t-max`. Une courbure aux temps courts vient
  du fil : augmenter `--t-min`.
* Le $R^2$ de la régression doit être supérieur à 0,999.
* La méthode `model` doit donner un $k$ cohérent avec la méthode de la pente.

## Bilan d'incertitude (ordre de grandeur)

$$\frac{\delta k}{k} \approx \sqrt{\left(\frac{\delta U}{U}\right)^2 + \left(\frac{\delta I}{I}\right)^2 + \left(\frac{\delta L}{L}\right)^2 + \left(\frac{\delta\,\text{pente}}{\text{pente}}\right)^2} + \text{biais de méthode}$$

| source | typique |
|---|---|
| U, I (multimètre) | 0,5 % chacun |
| longueur chauffée L (± 1 mm sur 200 mm) | 0,5 % |
| pente (statistique, donnée par `analyze`) | 0,1 à 1 % |
| biais de méthode (rayon du fil, paroi, extrémités), estimé avec `design` | 0,5 à 3 % |
| reproductibilité du tassement de la poudre | souvent la plus grande, 5 à 10 % |
