/*Declare your sensor pins as variables. I'm using Analog In pins 0 and 1. Change the names and numbers as needed
  Pro tip: If you're pressed for memory, use #define to declare your sensor pins without using any memory. Just be careful that your pin name shows up NOWHERE ELSE in your sketch!
  for more info, see: http://arduino.cc/en/Reference/Define
*/

#define analogPin A0 /* The pin linking the two resistances (see drawing) */
int raw = 0;
float Vin = 5; /*Potential of 5V (USB connected) */
float Vout = 0; /* Potential of the ground */
float R1 = 10000; /*The value of the resitance we use*/
float R2 = 0; /*The value of the unknown resistance we need to calculate and send */
float buffer1 = 0;

/* The pin of the unknown resistance*/
char dataStr[100] = "";
char buffer[7];

void setup() {
  Serial.begin(9600); //This line tells the Serial port to begin communicating at 9600 bauds
}


void loop() {

  raw = analogRead(analogPin);
  if (raw) {
    buffer1 = raw * Vin;
    Vout = (buffer1) / 1024.0;
    buffer1 = (Vin / Vout) - 1;
    R2 = R1 * buffer1;
    delay(1000);
  }

  dataStr[0] = 0; //clean out string
  //convert floats to string and assemble c-type char string for writing:
  ltoa( millis(),buffer,10); //convert long to charStr
    strcat(dataStr, buffer); //add it to the end
    strcat(dataStr, ", "); //append the delimiter*/

  //Resistance :
    dtostrf(R2, 5, 1, buffer);  //5 is minimum width, 1 is precision; float value is copied onto buff
    strcat( dataStr, buffer); //append the converted float
  

  strcat( dataStr, 0); //terminate correctly
  Serial.println(R2);
  Serial.println(dataStr);

  delay(60000); // We wait a minute before the next measure...
}
