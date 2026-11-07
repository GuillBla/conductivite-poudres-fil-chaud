"""hotwire — conductivité thermique des poudres par la méthode du fil chaud.

Modules :
    sensors      capteur PT100 et chaînes de mesure (pont diviseur, MAX31865)
    model        modèle thermique : solution analytique (source linéique) et
                 simulation numérique radiale du montage complet
    analysis     extraction de la conductivité à partir d'une courbe T(t)
    virtual      « Arduino virtuel » qui émet les mêmes trames que le firmware
    acquisition  enregistrement des trames série (réelles ou simulées) en CSV
    config       chargement de la description du montage (fichier TOML)
"""

__version__ = "2.0.0"
