# Utilisation des outils

Toutes les commandes se lancent avec `python -m hotwire <commande>`, ou
`hotwire <commande>` après `pip install -e .`. L'option `-h` affiche l'aide
de chaque commande.

## Description du montage : fichiers TOML

Les commandes lisent `config/montage.toml` par défaut (le montage v1), ou le
fichier donné avec `--config`. On peut surcharger les paramètres principaux
en ligne de commande :

| option | paramètre |
|---|---|
| `--power` | puissance de chauffe (W) |
| `--length` | longueur chauffée (m) |
| `--k`, `--rhocp` | conductivité et ρc de la poudre (utilisés par la simulation, ou comme point de départ de l'ajustement) |
| `--h` | coefficient d'échange extérieur (W/m²/K) |
| `--sensor` | `outer` (paroi), `wire` (fil) ou un rayon en mètres |

## `design` — dimensionner une expérience

```bash
python -m hotwire design --config config/montage_recommande.toml --duration 300 --plot design.png
```

La commande affiche :
* les temps caractéristiques et les températures en régime permanent ;
* la résolution des trois chaînes de mesure PT100 ;
* l'erreur de la méthode de la pente pour différentes fenêtres de temps ;
* les sensibilités au fil et à la paroi (et la figure correspondante avec `--plot`).

## `simulate` — expérience virtuelle

```bash
python -m hotwire simulate --config config/montage_recommande.toml \
    --k 0.25 --duration 300 --baseline 30 --cooling 120 --period 1 \
    --frontend max31865 --noise 0.7 --out data/sim.csv --plot sim.png
```

Le CSV produit a le même format que celui du vrai firmware. Le modèle
physique fournit la température vraie ; elle est ensuite convertie en
résistance PT100, puis en valeur ADC (avec quantification et bruit), puis
reconvertie comme le ferait l'Arduino. `--frontend divider-legacy` simule
l'électronique de la v1 : on y voit des paliers de plusieurs dizaines de
degrés.

## `analyze` — calculer la conductivité

```bash
python -m hotwire analyze data/sim.csv --config config/montage_recommande.toml \
    --method all --t-min 10 --t-max 300 --plot analyse.png
```

* `--method slope | line | model | all` (voir [théorie](theorie.md#6-les-trois-méthodes-danalyse)).
* `--free k_powder,rhocp_powder,h_ext` : paramètres ajustés par `model`. Par
  défaut, le choix dépend de la position du capteur. $T_\text{air}$ est prise
  sur la ligne de base quand le fichier en contient une.
* `--legacy-conversion` : convertit la résistance en température avec le
  coefficient linéaire 0,00391 du tableur v1.
* Formats reconnus : colonnes `time_s` ou `time_ms`, `temperature_c` et/ou
  `resistance_ohm`, et `heater` (optionnelle). Les lignes commençant par `#`
  sont des commentaires ; on peut y écrire `power=…` et `length=…`.

## `acquire` — enregistrer un Arduino

```bash
python -m hotwire acquire --list-ports
python -m hotwire acquire --port COM3 --out data/essai.csv --baseline 30 --duration 300
python -m hotwire acquire --simulate --speed 100 --config config/montage_recommande.toml --period 1 --duration 300
```

Chaque trame est écrite immédiatement sur le disque. Ctrl+C arrête
proprement l'enregistrement et coupe la chauffe. Les durées `--baseline` et
`--duration` doivent correspondre à `BASELINE_MS` et `MAX_HEAT_MS` dans le
firmware.

## Utiliser la bibliothèque depuis Python

```python
import numpy as np
from hotwire.model import Setup, simulate
from hotwire.analysis import slope_method

s = Setup(wire_radius=0.05e-3, powder_radius=0.025, length=0.2, power=0.8,
          k_powder=0.2, sensor="wire")
t = np.arange(1, 301)
sim = simulate(s, times=t)
print(slope_method(t, sim.t_sensor, s.q_lin, t_min=10, t_max=300))
```

## Format des trames du firmware

```
# hotwire_logger v2.0 frontend=max31865 period_ms=1000
time_ms,heater,raw,resistance_ohm,temperature_c
123456,0,8034.00,105.425,13.908
...
# event=heater_on
```

| colonne | contenu |
|---|---|
| `time_ms` | `millis()` de l'Arduino |
| `heater` | 1 si la chauffe est active |
| `raw` | code ADC brut (moyenne en mode pont) |
| `resistance_ohm` | résistance de la PT100 |
| `temperature_c` | température selon IEC 60751 (Callendar–Van Dusen) |

Commandes acceptées : `S` (séquence ligne de base puis chauffe), `H`
(chauffe immédiate), `X` (arrêt), `?` (état).
