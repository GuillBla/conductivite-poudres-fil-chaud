# Théorie de la méthode du fil chaud

## 1. Principe

Un fil fin est noyé dans la poudre. À partir de $t = 0$, il dissipe une
puissance constante $P$ sur une longueur $L$, soit une puissance linéique

$$q = \frac{P}{L} = \frac{U\,I}{L} \quad [\mathrm{W/m}].$$

La chaleur diffuse radialement dans la poudre. Plus la poudre conduit bien,
plus la chaleur s'évacue vite, et moins le fil s'échauffe.

## 2. Solution de la source linéique

On modélise le fil comme une ligne infiniment fine et infiniment longue,
dans un milieu infini et homogène, de conductivité $k$ et de diffusivité
$\alpha = k / (\rho c)$. L'élévation de température à la distance $r$ du fil
vaut alors (Carslaw & Jaeger) :

$$\Delta T(r,t) = \frac{q}{4\pi k}\; E_1\!\left(\frac{r^2}{4\alpha t}\right),
\qquad E_1(x) = \int_x^\infty \frac{e^{-u}}{u}\,du .$$

Quand $t \gg r^2/(4\alpha)$, on peut utiliser $E_1(x) \approx -\gamma - \ln x$
($\gamma = 0{,}5772$, constante d'Euler), ce qui donne

$$\Delta T \approx \frac{q}{4\pi k}\left[\ln t + \ln\frac{4\alpha}{r^2} - \gamma\right].$$

**$\Delta T$ devient une fonction linéaire de $\ln t$, de pente $q/(4\pi k)$.**
La conductivité s'obtient donc sans connaître $\rho c$ ni la distance exacte $r$ :

$$\boxed{k = \frac{q}{4\pi}\;\frac{1}{\mathrm{d}T/\mathrm{d}\ln t}}$$

> ⚠️ Il s'agit du logarithme **népérien**. Si la pente est mesurée en
> fonction de $\log_{10} t$, il faut multiplier le résultat par
> $\ln 10 = 2{,}303$. Le tableur de la v1 a oublié ce facteur.

L'erreur relative sur la pente vaut environ $r^2/(4\alpha t)$. Pour qu'elle
reste sous 1 %, il faut $t > 25\,r^2/\alpha$. Avec $\alpha \approx 1{,}7\cdot10^{-7}$ m²/s :

| distance capteur–fil $r$ | 1 % d'erreur atteint après |
|---|---|
| 0,05 mm (sur un fil Ø 0,1 mm) | 0,4 s |
| 0,5 mm | 37 s |
| 3 mm | 22 min |
| 16 mm (paroi du tube v1) | 10 h |

Voilà pourquoi la méthode exige un capteur **sur le fil ou tout près**.

## 3. Ce qui limite la méthode en pratique

La fenêtre de temps exploitable est bornée des deux côtés :

* **Aux temps courts**, le fil n'est pas infiniment fin : son rayon $r_w$ et
  sa capacité thermique décalent la courbe tant que $t$ n'est pas grand
  devant $r_w^2/\alpha$, multiplié par le rapport des capacités thermiques.
  Avec un fil de Ø 0,5 mm, l'erreur est encore de 5 % à 10–100 s. Avec
  Ø 0,1 mm, elle tombe sous 1 % dès 5 s.
* **Aux temps longs**, la chaleur atteint la paroi du tube (temps
  caractéristique $R^2/4\alpha$, soit 5 min pour un tube de Ø 29 mm). À partir
  de là, le milieu n'est plus infini et la pente augmente : la méthode
  sous-estime $k$ de 20 % ou plus.
* **Pertes par les extrémités** : le modèle suppose un fil infiniment long.
  Il faut une longueur chauffée grande devant le diamètre du tube (au moins
  4 fois). La v1 avait 41 mm de poudre pour 29 mm de diamètre.
* **Convection et rayonnement dans la poudre** : on les rend négligeables
  avec un faible échauffement (quelques kelvins à quelques dizaines de kelvins).
* **Contact fil–poudre** : une résistance de contact décale la courbe sans
  changer la pente. La méthode de la pente y est insensible.

`python -m hotwire design` calcule cette fenêtre pour un montage donné (en
simulant l'expérience sans bruit et en comparant le $k$ retrouvé au $k$
imposé).

## 4. Pourquoi un capteur sur la paroi ne marche pas

Dans le montage v1, la PT100 était collée sur la paroi extérieure du tube.
Deux choses empêchent alors de remonter à $k$ :

1. La loi logarithmique ne s'applique qu'après plusieurs heures (tableau
   ci-dessus). Or, bien avant ce délai, la chaleur a atteint la paroi et
   s'échappe dans l'air.
2. En régime permanent, la température de paroi vaut
   $T_\text{paroi} - T_\text{air} = q / (2\pi R h)$. Elle ne dépend que du
   coefficient d'échange $h$ avec l'air, **pas du tout de $k$**. Pendant le
   régime transitoire, $k$ n'influence que le retard avec lequel la paroi
   commence à chauffer.

Les coefficients de sensibilité réduits $X_p = p\,\partial T/\partial p$,
calculés par `hotwire design`, le montrent directement. Pour le montage v1 en
fin d'essai, $X_k \approx +3$ K sur la paroi, contre $X_h \approx -71$ K et
$X_{\rho c} \approx -14$ K. La mesure en paroi renseigne donc sur $h$ et
$\rho c$, presque pas sur $k$.

## 5. Le modèle numérique du montage complet

Pour aller au-delà de la solution idéale, `hotwire/model.py` résout
l'équation de la chaleur en coordonnées cylindriques,

$$\rho c\,\frac{\partial T}{\partial t} = \frac{1}{r}\frac{\partial}{\partial r}\left(k\,r\,\frac{\partial T}{\partial r}\right),$$

sur plusieurs couches :

* le fil : une maille à température uniforme, avec sa capacité thermique, qui reçoit $q$ ;
* la poudre : maillage logarithmique, plus fin près du fil ;
* la paroi du tube : avec sa propre conductivité et sa propre capacité thermique ;
* la condition à la limite extérieure : convection $-k\,\partial T/\partial r = h\,(T - T_\text{air})$.

Le schéma est en volumes finis, implicite (Euler arrière), avec un pas de
temps adaptatif. Il est inconditionnellement stable et coûte moins de
0,1 s pour une heure simulée. Il est validé de deux façons :

* face à la solution $E_1$, avec un tube très grand : écart < 1 % (test `test_numerical_model_matches_line_source`) ;
* face au bilan d'énergie en régime permanent : résistances en série, écart < 1 % (test `test_energy_balance_steady_state`).

## 6. Les trois méthodes d'analyse

| méthode | hypothèse | paramètres estimés | quand l'utiliser |
|---|---|---|---|
| **pente** (`slope`) | régime logarithmique, milieu infini | $k$ | capteur sur le fil, fenêtre de temps bien choisie |
| **E1** (`line`) | milieu infini, capteur à distance $r$ connue | $k$, $\alpha$, $T_0$ | capteur à quelques mm du fil, essai assez court pour que la chaleur n'atteigne pas la paroi |
| **modèle complet** (`model`) | modèle 1D radial du montage | $k$, $\rho c$, $h$, $T_\text{air}$ (au choix) | tous les cas ; donne aussi les corrélations entre paramètres |

La méthode `model` ajuste les paramètres par moindres carrés
(`scipy.optimize.least_squares`). Les incertitudes viennent de la jacobienne.
Si deux paramètres ont une corrélation proche de ±1, la mesure ne permet pas
de les distinguer.

## Références

* H. S. Carslaw, J. C. Jaeger, *Conduction of Heat in Solids*, 2ᵉ éd., Oxford, 1959. Chap. 10 : source linéique.
* ASTM D5334, *Standard Test Method for Determination of Thermal Conductivity of Soil and Rock by Thermal Needle Probe Procedure*. Variante « aiguille » de la méthode, adaptée aux milieux granulaires.
* ISO 8894-1, *Matériaux réfractaires — Détermination de la conductivité thermique — Méthode du fil chaud (croisillon)*.
* IEC 60751, *Thermomètres à résistance de platine industriels*. Coefficients de Callendar–Van Dusen de la PT100.
