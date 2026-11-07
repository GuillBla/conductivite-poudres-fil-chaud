# Matériel et câblage

## Liste du matériel (montage v2 recommandé)

| élément | choix conseillé | rôle |
|---|---|---|
| Carte | Arduino Uno / Nano | acquisition, pilotage de la chauffe |
| Capteur | PT100 3 fils, petit format (film mince 2×5 mm) ou thermocouple type K Ø 0,08–0,13 mm | température au contact du fil |
| Convertisseur | module **MAX31865** (PT100, R_ref = 430 Ω), ou MAX31856 pour un thermocouple | conversion précise de la mesure (15–19 bits) |
| Fil chauffant | **Kanthal A1** (déjà utilisé en v1) ou nichrome, **Ø 0,1 mm**, 200 mm tendu au centre du tube | source de chaleur |
| Alimentation de chauffe | alimentation de laboratoire réglable, stabilisée | puissance constante |
| Commutation | MOSFET canal N « logic level » (ex. IRLZ44N) + résistance de grille 220 Ω + résistance de rappel 10 kΩ | mise en chauffe pilotée par l'Arduino, avec un instant $t = 0$ connu |
| Mesure de puissance | multimètre en ampèremètre + voltmètre aux bornes du **fil seul** (montage 4 fils) | connaître $q = UI/L$ |
| Tube | PVC ou verre, Ø intérieur ≥ 50 mm, longueur ≥ 4 × diamètre | contenir la poudre |

### Dimensionner la chauffe

Le Kanthal A1 Ø 0,1 mm fait environ 185 Ω/m, soit 37 Ω pour 200 mm. Pour
0,8 W, il faut $I = \sqrt{P/R} \approx 0{,}15$ A sous environ 5,4 V. Une
alimentation de laboratoire convient ; une sortie de l'Arduino, non.
`python -m hotwire design` fait ce calcul pour votre montage (clé
`wire_material` du fichier TOML).

| alliage | résistivité (µΩ·m) | Ø 0,1 mm (Ω/m) | ρc (MJ/m³/K) | T max (°C) |
|---|---|---|---|---|
| **Kanthal A1** (FeCrAl) | 1,45 | 185 | 3,3 | 1400 |
| Nichrome 80/20 (NiCr) | 1,09 | 139 | 3,8 | 1200 |
| Constantan (CuNi) | 0,49 | 62 | 3,5 | 600 |

Le Kanthal convient très bien. Sa résistance varie peu avec la température
(quelques ‰ sur 100 K), donc la puissance reste constante pendant l'essai.
Pour la même raison, il ne peut pas servir de thermomètre : la température
doit être lue par une sonde séparée, collée sur le fil. Le Kanthal se soude
mal à l'étain ; utilisez des bornes à vis ou des cosses serties pour les
connexions.

> Pour la v1, U = 2,6 V et I = 1,45 A sur 41 mm de Kanthal correspondent à
> un fil d'environ Ø 0,2 mm, si la tension était mesurée aux bornes du fil
> seul (`hotwire.model.wire_diameter_from_measurement`). Le diamètre retenu
> dans `config/montage.toml` (Ø 0,5 mm) reste à vérifier.

Ordre de grandeur de la puissance : la pente au fil vaut $q/(4\pi k)$. On vise
1 à 2 K par unité de $\ln t$, ce qui donne quelques kelvins d'échauffement
sur l'essai. Pour $k \approx 0{,}2$ W/m/K, cela fait $q \approx 3$ à 5 W/m.
`python -m hotwire design` donne la valeur pour votre montage.

> ⚠️ La v1 injectait 3,8 W sur 41 mm, soit 92 W/m. Selon le modèle, le fil
> aurait atteint plusieurs centaines de °C pour une poudre isolante. C'est un risque
> d'oxydation et de brûlure, et la convection dans la poudre fausse alors la
> mesure.

## Câblage — option A : MAX31865 (recommandé)

```
 Arduino Uno           MAX31865 (Adafruit ou clone)
 ───────────           ────────────────────────────
 5V  ───────────────── Vin
 GND ───────────────── GND
 D13 (SCK) ─────────── CLK
 D12 (MISO) ────────── SDO
 D11 (MOSI) ────────── SDI
 D10 ───────────────── CS
                       F+ / RTD+ / RTD- / F-  ──► PT100 (2, 3 ou 4 fils,
                                                  configurer les ponts de
                                                  soudure du module)
```

Dans le firmware : `#define USE_MAX31865 1`, et `RTD_WIRES` réglé selon votre
sonde. Installer la bibliothèque « Adafruit MAX31865 » depuis le gestionnaire
de bibliothèques de l'IDE Arduino.

## Câblage — option B : pont diviseur amélioré (sans module)

```
 D8 (EXCITE_PIN) ── R_ref 1 kΩ 0,1 % ──┬── A0
                                        │
                                      PT100
                                        │
 GND ───────────────────────────────────┘
```

* **La PT100 se branche côté masse** : la tension sur A0 (≈ 0,5 V) reste
  sous la référence interne de 1,1 V.
* Le pont n'est alimenté que pendant la mesure (`EXCITE_PIN`), ce qui
  supprime presque tout l'auto-échauffement de la sonde.
* Avec 64 lectures moyennées, on obtient environ 0,1 °C de résolution.
* La justesse dépend de `V_EXCITE` et de `V_ADC_REF`, à mesurer au
  multimètre (la référence interne vaut entre 1,0 et 1,2 V selon les cartes).

## Commande de la chauffe

```
 Alim + ──────────── fil chauffant ──────────┐
                                             │ Drain
 D7 ── 220 Ω ──┬─────────────────── Grille  MOSFET (IRLZ44N)
              10 kΩ                          │ Source
               │                             │
 GND Arduino ──┴──────────── Alim − ─────────┘   (masses communes)
```

## Comparatif des chaînes de mesure

Valeurs calculées par `python -m hotwire design` :

| chaîne | résolution (°C) | auto-échauffement PT100 |
|---|---|---|
| pont 10 kΩ, réf. 5 V (**v1**) | ≈ 26 | 0,03 mW |
| pont 1 kΩ, réf. 1,1 V, 64 lectures | ≈ 0,09 | 2,2 mW si alimenté en continu, ≈ 0 en impulsions |
| MAX31865 | ≈ 0,03 | 1,5 mW |

## Simuler sans matériel

* **Toute la chaîne** : `python -m hotwire acquire --simulate` utilise
  l'Arduino virtuel (`hotwire/virtual.py`). Il reproduit le format des
  trames, la quantification de l'ADC, le bruit et la séquence ligne de base
  → chauffe.
* **Le firmware lui-même** : il peut être chargé dans un simulateur
  d'Arduino en ligne comme [Wokwi](https://wokwi.com). Le MAX31865 n'y existe
  pas : passer `USE_MAX31865` à 0 et remplacer la PT100 par un potentiomètre
  sur A0 pour vérifier les commandes série et les sécurités.
