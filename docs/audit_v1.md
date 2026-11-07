# Audit de la version 1

Les fichiers d'origine sont conservés sans modification dans `legacy/`. Ce
document recense ce qui empêchait la v1 de fonctionner ou faussait le
résultat, et indique comment la v2 le corrige.

## Firmware `ReadAndSendResitanceToCSV.ino`

| # | problème | conséquence | v2 |
|---|---|---|---|
| 1 | Pont diviseur 10 kΩ + PT100 lu par l'ADC 10 bits sous 5 V | 1 pas d'ADC ≈ 10 Ω ≈ **26 °C**. La mesure ne pouvait rien voir. | MAX31865, ou pont 1 kΩ / réf. 1,1 V / 64 lectures |
| 2 | `char buffer[7]` reçoit `ltoa(millis())` | Débordement de tampon dès que `millis()` dépasse 999 999, soit après **16,7 min** : comportement imprévisible | `Serial.print` direct, sans tampon |
| 3 | `strcat(dataStr, 0)` | Passe un pointeur nul à `strcat` : comportement indéfini, plantage possible | supprimé |
| 4 | Deux `println` par mesure : `R2`, puis `"millis, R2"` | Une ligne sur deux, Processing lit le **temps** comme si c'était la résistance | une seule trame CSV par mesure, avec en-tête |
| 5 | `delay(1000)` puis `delay(60000)` | Période réelle de 61 s et plus, qui dérive | échantillonnage sur `millis()` sans dérive |
| 6 | `if (raw)` | Si `raw == 0`, la valeur précédente est renvoyée sans le signaler | détection de défaut capteur |
| 7 | 1 mesure par minute | Trop lent pour la fenêtre utile de la méthode (10–300 s) | 1 Hz par défaut |
| 8 | Chauffe non pilotée | L'instant $t = 0$ n'est pas connu précisément, et aucune sécurité | MOSFET piloté, commandes `S/H/X`, coupure sur durée max, surchauffe ou défaut |
| 9 | Diviseur par 1024 au lieu du centre du pas | biais d'un demi-LSB (mineur) | corrigé |

## Sketch Processing `RetrieveRandCreateCsv.pde`

| # | problème | conséquence | v2 (`hotwire acquire`) |
|---|---|---|---|
| 1 | `table` n'est jamais créée (`new Table()` manquant) | `NullPointerException` dès `table.addColumn` : le sketch ne démarre pas | — |
| 2 | `setInt("time", second())` | Enregistre les secondes de l'horloge du PC (0–59), pas le temps écoulé | temps de l'Arduino (`millis`) |
| 3 | Sauvegarde toutes les 1000 lectures seulement | À 1 mesure/min, plus de 16 h avant la première écriture : tout est perdu si on ferme avant | écriture et `flush` à chaque trame |
| 4 | Nom de fichier sans extension | `saveTable` ne sait pas quel format utiliser | `.csv` explicite |
| 5 | Port `COM3` codé en dur | | `--port`, `--list-ports` |

## Tableur `Protech.ods`

| # | problème | effet sur $k$ |
|---|---|---|
| 1 | Pente mesurée en fonction de `LOG10(t)` alors que la formule $k = P/(4\pi\,\text{pente}\,L)$ suppose $\ln t$ | **sous-estimé d'un facteur 2,303** |
| 2 | Conversion linéaire de la PT100 avec α = 0,00391 au lieu de 0,00385 (IEC 60751) | environ 1,5 % |
| 3 | Fenêtre d'ajustement choisie à la main (lignes 9 à 51) | résultat très dépendant de ce choix : sur l'essai 1, de 0,51 à 1,30 W/m/K selon la fenêtre |
| 4 | Capteur sur la paroi extérieure du tube | voir ci-dessous : la méthode ne s'applique pas |

## Réanalyse des deux essais

Les données ont été extraites du tableur vers `data/essai_1.csv` et
`data/essai_2.csv`. Les commandes et résultats :

```bash
python -m hotwire analyze data/essai_1.csv --method all --plot docs/img/analyse_essai_1.png
python -m hotwire analyze data/essai_2.csv --method all --plot docs/img/analyse_essai_2.png
```

| méthode | essai 1 (3,93 W) | essai 2 (3,77 W) |
|---|---|---|
| tableur d'origine (log10) | — | 0,86 |
| pente en ln t, fin de courbe | 1,18 ± 0,03 | 1,59 ± 0,04 |
| E1 à r = 16 mm | 0,62 ± 0,01 | 1,33 ± 0,05 |
| modèle complet | 1,9 ± 0,3 | 0,60 ± 0,07 |

*(k en W/m/K ; incertitudes statistiques seulement.)*

**Conclusion : ces essais ne permettent pas de donner une valeur de $k$.**

* Selon la méthode, on obtient de 0,6 à 1,9 W/m/K. Les incertitudes
  statistiques, petites, cachent une erreur de modèle bien plus grande.
* Le modèle complet ne reproduit les courbes qu'avec $\rho c$ = 5 à
  18·10⁶ J/m³/K, alors qu'une poudre est vers 1 à 2·10⁶. Les corrélations
  entre $k$, $\rho c$ et $h$ dépassent 0,95. La mesure en paroi ne sépare
  donc pas ces paramètres, ce que l'étude de sensibilité prévoit
  ([théorie §4](theorie.md#4-pourquoi-un-capteur-sur-la-paroi-ne-marche-pas)).
* Le bilan d'énergie ne boucle pas. En 40 min, l'essai 1 injecte environ
  9 500 J. Or 27 cm³ de poudre (Ø 29 mm × 41 mm) n'ont qu'une capacité
  d'environ 33 J/K (avec ρc ≈ 1,2·10⁶ J/m³/K), ce qui donnerait un
  échauffement d'environ 290 K sans pertes. La paroi n'a pris que 11 K. L'essentiel de la chaleur est donc parti
  ailleurs : pertes axiales par les extrémités et le support, ou puissance
  mesurée aux bornes de l'alimentation plutôt qu'aux bornes du fil.
* La résolution de l'électronique (point 1 du firmware) laisse penser que les
  résistances ont été relevées à l'ohmmètre.

Le montage et le protocole v2 ([materiel.md](materiel.md),
[protocole.md](protocole.md)) corrigent ces points. La simulation
correspondante retrouve $k$ à 0,3 % près avec le bruit d'un MAX31865.
