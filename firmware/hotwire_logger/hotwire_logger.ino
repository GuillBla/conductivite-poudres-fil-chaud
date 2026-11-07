/*
  hotwire_logger — v2.0
  ---------------------------------------------------------------------------
  Acquisition pour la mesure de conductivité thermique des poudres par fil
  chaud.  Lit une sonde PT100, pilote la chauffe du fil (MOSFET) et envoie
  une trame CSV par période d'échantillonnage sur le port série :

      time_ms,heater,raw,resistance_ohm,temperature_c

  Commandes série (une lettre, suivie ou non d'un retour à la ligne) :
      S  démarre une séquence : ligne de base (BASELINE_MS) puis chauffe
      H  chauffe immédiatement
      X  coupe la chauffe
      ?  réaffiche l'en-tête et l'état

  Sécurités : la chauffe est coupée après MAX_HEAT_MS ou si la température
  dépasse T_MAX_C, ou en cas de défaut capteur.

  Chaîne de mesure (choisir avec USE_MAX31865) :
    1 = module MAX31865 (recommandé, ~0,03 °C de résolution),
        bibliothèque « Adafruit MAX31865 » (gestionnaire de bibliothèques).
    0 = pont diviseur sur A0 : 5 V(pin EXCITE_PIN) — R_REF — A0 — PT100 — GND,
        référence interne 1,1 V et moyenne de OVERSAMPLING lectures
        (~0,1 °C de résolution, sans composant spécial).

  Voir docs/materiel.md pour le câblage, et `python -m hotwire acquire`
  pour enregistrer les trames.  Le firmware est émulé par hotwire/virtual.py.
*/

// ======================= Configuration =====================================
#define USE_MAX31865 1

const unsigned long BAUD_RATE        = 115200;
const unsigned long SAMPLE_PERIOD_MS = 1000;     // 1 s : la méthode exploite 10–300 s
const unsigned long BASELINE_MS      = 30000;    // ligne de base avant chauffe
const unsigned long MAX_HEAT_MS      = 600000;   // durée max de chauffe (10 min)
const float         T_MAX_C          = 120.0;    // coupure de sécurité
const uint8_t       HEATER_PIN       = 7;        // grille du MOSFET (logic level)

// Sonde PT100 (IEC 60751)
const float R0    = 100.0;
const float CVD_A = 3.9083e-3;
const float CVD_B = -5.775e-7;

#if USE_MAX31865
  #include <Adafruit_MAX31865.h>
  const uint8_t MAX_CS_PIN = 10;
  const float   RREF       = 430.0;              // résistance de référence du module
  Adafruit_MAX31865 rtd(MAX_CS_PIN);             // SPI matériel (D11, D12, D13)
  // Nombre de fils de la sonde : MAX31865_2WIRE, MAX31865_3WIRE ou MAX31865_4WIRE
  #define RTD_WIRES MAX31865_3WIRE
#else
  const uint8_t SENSE_PIN    = A0;
  const uint8_t EXCITE_PIN   = 8;                // alimente le pont seulement pendant la mesure
  const float   R_REF        = 1000.0;           // résistance de précision 0,1 %
  const float   V_EXCITE     = 5.0;              // à mesurer au multimètre pour plus de justesse
  const float   V_ADC_REF    = 1.1;              // référence interne : à étalonner (1,0–1,2 V)
  const uint8_t OVERSAMPLING = 64;
#endif
// ===========================================================================

enum State { IDLE, BASELINE, HEATING };
State state = IDLE;
unsigned long stateStart = 0;
unsigned long nextSample = 0;
bool heaterOn = false;

void setHeater(bool on) {
  heaterOn = on;
  digitalWrite(HEATER_PIN, on ? HIGH : LOW);
}

void printHeader() {
  Serial.print(F("# hotwire_logger v2.0 frontend="));
#if USE_MAX31865
  Serial.print(F("max31865"));
#else
  Serial.print(F("divider"));
#endif
  Serial.print(F(" period_ms="));
  Serial.println(SAMPLE_PERIOD_MS);
  Serial.println(F("time_ms,heater,raw,resistance_ohm,temperature_c"));
}

// Inversion de Callendar–Van Dusen (T >= 0 °C)
float pt100Temperature(float r) {
  return (-CVD_A + sqrt(CVD_A * CVD_A - 4.0 * CVD_B * (1.0 - r / R0))) / (2.0 * CVD_B);
}

// Lit la sonde ; renvoie false en cas de défaut.
bool readSensor(float &raw, float &resistance) {
#if USE_MAX31865
  uint16_t code = rtd.readRTD();                 // 15 bits, ratio R/RREF
  uint8_t fault = rtd.readFault();
  if (fault) {
    Serial.print(F("# fault=0x"));
    Serial.println(fault, HEX);
    rtd.clearFault();
    return false;
  }
  raw = code;
  resistance = code * RREF / 32768.0;
  return true;
#else
  digitalWrite(EXCITE_PIN, HIGH);
  delayMicroseconds(500);                        // stabilisation
  analogRead(SENSE_PIN);                         // première lecture jetée
  unsigned long sum = 0;
  for (uint8_t i = 0; i < OVERSAMPLING; i++) sum += analogRead(SENSE_PIN);
  digitalWrite(EXCITE_PIN, LOW);                 // limite l'auto-échauffement
  raw = (float)sum / OVERSAMPLING;
  if (raw < 1 || raw > 1022) return false;       // sonde coupée ou en court-circuit
  float v = (raw + 0.5) * V_ADC_REF / 1024.0;
  resistance = R_REF * v / (V_EXCITE - v);
  return true;
#endif
}

void handleCommand(char c) {
  unsigned long now = millis();
  switch (c) {
    case 'S': case 's':
      setHeater(false);
      state = BASELINE; stateStart = now;
      Serial.println(F("# event=baseline"));
      break;
    case 'H': case 'h':
      setHeater(true);
      state = HEATING; stateStart = now;
      Serial.println(F("# event=heater_on"));
      break;
    case 'X': case 'x':
      setHeater(false);
      state = IDLE;
      Serial.println(F("# event=heater_off reason=command"));
      break;
    case '?':
      printHeader();
      Serial.print(F("# state="));
      Serial.println(state == IDLE ? F("idle") : state == BASELINE ? F("baseline") : F("heating"));
      break;
    default:
      break;                                     // ignore \r, \n, etc.
  }
}

void setup() {
  pinMode(HEATER_PIN, OUTPUT);
  setHeater(false);
  Serial.begin(BAUD_RATE);
#if USE_MAX31865
  rtd.begin(RTD_WIRES);
  rtd.enable50Hz(true);                          // filtre secteur 50 Hz (Europe)
#else
  pinMode(EXCITE_PIN, OUTPUT);
  digitalWrite(EXCITE_PIN, LOW);
  analogReference(INTERNAL);
  delay(20);
  for (uint8_t i = 0; i < 8; i++) analogRead(SENSE_PIN);  // laisse la référence se stabiliser
#endif
  printHeader();
  nextSample = millis();
}

void loop() {
  while (Serial.available()) handleCommand(Serial.read());

  unsigned long now = millis();

  // Machine d'état
  if (state == BASELINE && now - stateStart >= BASELINE_MS) {
    setHeater(true);
    state = HEATING; stateStart = now;
    Serial.println(F("# event=heater_on"));
  }
  if (state == HEATING && now - stateStart >= MAX_HEAT_MS) {
    setHeater(false);
    state = IDLE;
    Serial.println(F("# event=heater_off reason=timeout"));
  }

  // Échantillonnage à période fixe, sans dérive (nextSample += période)
  if ((long)(now - nextSample) >= 0) {
    nextSample += SAMPLE_PERIOD_MS;
    float raw = 0, resistance = 0;
    bool ok = readSensor(raw, resistance);
    if (!ok) {
      if (heaterOn) {
        setHeater(false);
        state = IDLE;
        Serial.println(F("# event=heater_off reason=sensor_fault"));
      }
      return;
    }
    float temperature = pt100Temperature(resistance);
    if (heaterOn && temperature > T_MAX_C) {
      setHeater(false);
      state = IDLE;
      Serial.println(F("# event=heater_off reason=overtemperature"));
    }
    // Serial.print(float, n) évite les tampons de chaînes du firmware d'origine
    Serial.print(now);            Serial.print(',');
    Serial.print(heaterOn ? 1 : 0); Serial.print(',');
    Serial.print(raw, 2);         Serial.print(',');
    Serial.print(resistance, 3);  Serial.print(',');
    Serial.println(temperature, 3);
  }
}
