
#include <Arduino.h>
#include <Servo.h>
#include <stdlib.h>
#include <string.h>

// ============================================================
// RP2040 RC CAR CONTROLLER
// Raspberry Pi UART + manual RC + timed autonomous commands
//
// Board: Generic RP2040 (Arduino-Pico / Earle Philhower)
//
// UART commands:
//   PING
//   STATUS?
//   CAP,FORWARD,20
//   CAP,REVERSE,15
//   MODE,MANUAL
//   MODE,AUTO
//   DRIVE,1,-30,1500
//   STOP                 // Option A: latched emergency stop (existing command)
//   ESTOP                // Option A: explicit Pi emergency-stop command
//   RESET
//   OVERRIDE,ON
//   OVERRIDE,STEER,-30
//   OVERRIDE,ARM
//   OVERRIDE,DRIVE,1,-30,800
//   OVERRIDE,OFF
//   PULLOVER,LEFT
//   PULLOVER,RIGHT
//   PULLOVER,ABORT
//
// All commands end with '\n'.
// ============================================================

// ---------------- PIN CONFIGURATION --------------------------

// Receiver inputs (confirmed swapped in your working setup)
const uint8_t STEER_IN    = 3;
const uint8_t THROTTLE_IN = 2;

// Outputs
const uint8_t STEER_OUT    = 4;
const uint8_t THROTTLE_OUT = 5;

// UART connection to Raspberry Pi
const uint8_t PI_TX = 12;
const uint8_t PI_RX = 13;

// HC-SR04 (ECHO via dual 10k divider into 3.3 V GPIO)
// Front/right moved off GP6/7 and GP10/11 (suspect harness / flaky reads).
const uint8_t SONAR_FRONT_TRIG = 14;
const uint8_t SONAR_FRONT_ECHO = 15;
const uint8_t SONAR_LEFT_TRIG  = 8;
const uint8_t SONAR_LEFT_ECHO  = 9;
const uint8_t SONAR_RIGHT_TRIG = 16;
const uint8_t SONAR_RIGHT_ECHO = 17;

const uint32_t PI_BAUD = 115200;

// ---------------- RC CALIBRATION -----------------------------

const int RC_MIN     = 1020;
const int RC_NEUTRAL = 1523;
const int RC_MAX     = 2020;

// Change these if physical steering direction is reversed
const bool REVERSE_STEERING = false;

// Assumes pulses above neutral mean forward.
// Set true if your ESC is calibrated in the opposite direction.
const bool REVERSE_THROTTLE = false;

// ---------------- SPEED CAPS --------------------------------

// Percentage of available RC throttle pulse range.
// These are NOT measured vehicle-speed percentages.

const int DEFAULT_FORWARD_CAP = 20;
const int DEFAULT_REVERSE_CAP = 25;

int forwardCap = DEFAULT_FORWARD_CAP;
int reverseCap = DEFAULT_REVERSE_CAP;

// ---------------- SAFETY SETTINGS ---------------------------

// Receiver pulse considered lost after 100 ms
const uint32_t RC_TIMEOUT_US = 100000;

// Throttle must remain neutral for 1.5 s to arm
const uint32_t ARM_TIME_MS = 1500;
const int NEUTRAL_WINDOW_US = 50;

// In AUTO mode the Pi must send PING every <=250 ms.
// Recommend sending every 100 ms.
const uint32_t PI_HEARTBEAT_TIMEOUT_MS = 250;

// Maximum length of one DRIVE command
const uint32_t MAX_DRIVE_DURATION_MS = 5000;

// Emergency takeover: independent hard-coded throttle limits.
// Percentages refer to the available PWM throttle range, not road speed.
const int OVERRIDE_FORWARD_CAP = 15;
const int OVERRIDE_REVERSE_CAP = 10;
const int OVERRIDE_MAX_STEER = 50;  // percentage of steering travel
const uint32_t OVERRIDE_MAX_DRIVE_MS = 1500;
const uint32_t OVERRIDE_NEUTRAL_HOLD_MS = 500;

// Pull-over (HC-SR04 closed loop on RP2040)
const int PULLOVER_SIDE_TARGET_CM = 10;
const int PULLOVER_SIDE_BAND_CM = 2;       // accept 8..12 cm
const int PULLOVER_FRONT_STOP_CM = 25;
const int PULLOVER_CREEP_CAP = 12;        // % of forward PWM span
const int PULLOVER_STEER_MAX = 28;        // % steer toward wall
const uint32_t PULLOVER_TIMEOUT_MS = 15000;
const uint32_t PULLOVER_STABLE_MS = 400;
const uint32_t PULLOVER_RANGE_TX_MS = 200;
const uint32_t SONAR_TIMEOUT_US = 25000;  // ~4 m
const uint32_t SONAR_GAP_MS = 60;         // stagger sensors
// Must be > (enabled_count * SONAR_GAP_MS) or a channel goes stale → -1.
const uint32_t SONAR_STALE_MS = 450;

// Serial receive buffer
const size_t COMMAND_BUFFER_SIZE = 64;

// ---------------- RECEIVER CAPTURE ---------------------------

struct RCChannel {
  volatile uint32_t riseTime = 0;
  volatile uint32_t lastValidTime = 0;
  volatile uint16_t pulseWidth = RC_NEUTRAL;
  volatile uint32_t invalidCount = 0;
  volatile bool isHigh = false;
};

RCChannel steeringChannel;
RCChannel throttleChannel;

void capturePulse(RCChannel &ch, uint8_t pin) {
  uint32_t now = micros();

  if (digitalRead(pin) == HIGH) {
    ch.riseTime = now;
    ch.isHigh = true;
  }
  else if (ch.isHigh) {
    ch.isHigh = false;

    uint32_t width = now - ch.riseTime;

    if (width >= 900 && width <= 2100) {
      ch.pulseWidth = (uint16_t)width;
      ch.lastValidTime = now;
    }
    else {
      ch.invalidCount++;
    }
  }
}

void steeringISR() {
  capturePulse(steeringChannel, STEER_IN);
}

void throttleISR() {
  capturePulse(throttleChannel, THROTTLE_IN);
}

// ---------------- CONTROL STATE -----------------------------

enum ControlMode {
  MODE_MANUAL,
  MODE_AUTO,
  MODE_OVERRIDE,
  MODE_PULLOVER
};

ControlMode mode = MODE_MANUAL;

Servo steeringServo;
Servo throttleESC;

bool armed = false;
bool stopLatched = false;

uint32_t neutralStartMs = 0;
uint32_t lastPiHeartbeatMs = 0;

// Active timed manoeuvre
bool driveActive = false;
uint32_t driveStartMs = 0;
uint32_t driveDurationMs = 0;

int autoSteer = RC_NEUTRAL;
int autoThrottle = RC_NEUTRAL;

// Override state: receiver pulses are monitored but never applied to outputs.
bool overrideMotionArmed = false;
uint32_t overrideEnteredMs = 0;
int overrideSteer = RC_NEUTRAL;
int overrideThrottle = RC_NEUTRAL;
bool overrideDriveActive = false;
uint32_t overrideDriveStartMs = 0;
uint32_t overrideDriveDurationMs = 0;

// Current outputs
int steerOutput = RC_NEUTRAL;
int throttleOutput = RC_NEUTRAL;

// Receiver snapshot
int rcSteer = RC_NEUTRAL;
int rcThrottle = RC_NEUTRAL;

bool rcSteerOK = false;
bool rcThrottleOK = false;
bool rcOK = false;

uint32_t steerErrors = 0;
uint32_t throttleErrors = 0;

// Serial receive state
char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;
bool discardingLine = false;

// ---------------- HC-SR04 / PULLOVER -------------------------

enum PulloverSide {
  PULL_NONE = 0,
  PULL_LEFT = 1,
  PULL_RIGHT = 2
};

enum SonarId {
  SONAR_FRONT = 0,
  SONAR_LEFT = 1,
  SONAR_RIGHT = 2,
  SONAR_COUNT = 3
};

struct SonarSensor {
  uint8_t trigPin;
  uint8_t echoPin;
  volatile uint32_t riseUs;
  volatile uint32_t echoUs;
  volatile uint32_t lastEchoMs;
  volatile bool waitingFall;
  int distanceCm;   // -1 = invalid / timeout
  bool enabled;
};

SonarSensor sonars[SONAR_COUNT] = {
  {SONAR_FRONT_TRIG, SONAR_FRONT_ECHO, 0, 0, 0, false, -1, false},
  {SONAR_LEFT_TRIG,  SONAR_LEFT_ECHO,  0, 0, 0, false, -1, false},
  {SONAR_RIGHT_TRIG, SONAR_RIGHT_ECHO, 0, 0, 0, false, -1, false}
};

PulloverSide pulloverSide = PULL_NONE;
uint32_t pulloverStartMs = 0;
uint32_t pulloverStableStartMs = 0;
uint32_t lastRangeTxMs = 0;
uint8_t sonarScanIndex = 0;
uint32_t sonarLastTriggerMs = 0;
bool sonarTriggerArmed = false;
uint32_t sonarDiagUntilMs = 0;  // non-zero: timed SONAR? bench mode
bool sonarDiagContinuous = false;  // SONAR,ON until SONAR,OFF
uint8_t sonarPingPhase = 0;     // prefer FRONT every other ping

void sonarFrontISR() {
  uint32_t now = micros();
  if (digitalRead(SONAR_FRONT_ECHO) == HIGH) {
    sonars[SONAR_FRONT].riseUs = now;
    sonars[SONAR_FRONT].waitingFall = true;
  } else if (sonars[SONAR_FRONT].waitingFall) {
    sonars[SONAR_FRONT].waitingFall = false;
    sonars[SONAR_FRONT].echoUs = now - sonars[SONAR_FRONT].riseUs;
    sonars[SONAR_FRONT].lastEchoMs = millis();
  }
}

void sonarLeftISR() {
  uint32_t now = micros();
  if (digitalRead(SONAR_LEFT_ECHO) == HIGH) {
    sonars[SONAR_LEFT].riseUs = now;
    sonars[SONAR_LEFT].waitingFall = true;
  } else if (sonars[SONAR_LEFT].waitingFall) {
    sonars[SONAR_LEFT].waitingFall = false;
    sonars[SONAR_LEFT].echoUs = now - sonars[SONAR_LEFT].riseUs;
    sonars[SONAR_LEFT].lastEchoMs = millis();
  }
}

void sonarRightISR() {
  uint32_t now = micros();
  if (digitalRead(SONAR_RIGHT_ECHO) == HIGH) {
    sonars[SONAR_RIGHT].riseUs = now;
    sonars[SONAR_RIGHT].waitingFall = true;
  } else if (sonars[SONAR_RIGHT].waitingFall) {
    sonars[SONAR_RIGHT].waitingFall = false;
    sonars[SONAR_RIGHT].echoUs = now - sonars[SONAR_RIGHT].riseUs;
    sonars[SONAR_RIGHT].lastEchoMs = millis();
  }
}

void sonarDisableAll() {
  for (int i = 0; i < SONAR_COUNT; i++) {
    sonars[i].enabled = false;
    sonars[i].distanceCm = -1;
    sonars[i].waitingFall = false;
    digitalWrite(sonars[i].trigPin, LOW);
  }
  sonarTriggerArmed = false;
  sonarDiagContinuous = false;
  sonarDiagUntilMs = 0;
}

void sonarEnableForPullover(int side) {
  sonarDisableAll();
  sonars[SONAR_FRONT].enabled = true;
  if (side == (int)PULL_LEFT) {
    sonars[SONAR_LEFT].enabled = true;
  } else if (side == (int)PULL_RIGHT) {
    sonars[SONAR_RIGHT].enabled = true;
  }
  // Next serviceSonar() picks FRONT first (index starts at COUNT-1 so +1 → 0).
  sonarScanIndex = SONAR_COUNT - 1;
  sonarLastTriggerMs = 0;
}

// Bench enable: all three sensors, no motion (for SONAR? diagnostic).
void sonarEnableAll() {
  sonarDisableAll();
  for (int i = 0; i < SONAR_COUNT; i++) {
    sonars[i].enabled = true;
  }
  sonarScanIndex = SONAR_COUNT - 1;
  sonarLastTriggerMs = 0;
}

void updateSonarDistances() {
  uint32_t nowMs = millis();
  for (int i = 0; i < SONAR_COUNT; i++) {
    if (!sonars[i].enabled) {
      sonars[i].distanceCm = -1;
      continue;
    }
    uint32_t echo;
    uint32_t lastMs;
    noInterrupts();
    echo = sonars[i].echoUs;
    lastMs = sonars[i].lastEchoMs;
    interrupts();
    if (lastMs == 0 || (uint32_t)(nowMs - lastMs) > SONAR_STALE_MS) {
      sonars[i].distanceCm = -1;
      continue;
    }
    // distance cm ≈ echo_us / 58
    if (echo < 100 || echo > SONAR_TIMEOUT_US) {
      sonars[i].distanceCm = -1;
    } else {
      sonars[i].distanceCm = (int)(echo / 58UL);
    }
  }
}

void serviceSonar() {
  // Only run TRIG when at least one sensor is enabled.
  bool any = false;
  for (int i = 0; i < SONAR_COUNT; i++) {
    if (sonars[i].enabled) {
      any = true;
      break;
    }
  }
  if (!any) {
    return;
  }

  updateSonarDistances();

  uint32_t nowMs = millis();
  if ((uint32_t)(nowMs - sonarLastTriggerMs) < SONAR_GAP_MS) {
    return;
  }

  // Diag: fair round-robin so RIGHT is not starved.
  // Pullover: still prefer FRONT every other ping for collision stop.
  uint8_t pick = 255;
  const bool preferFront =
      (!sonarDiagContinuous && sonarDiagUntilMs == 0) &&
      sonars[SONAR_FRONT].enabled &&
      (sonars[SONAR_LEFT].enabled || sonars[SONAR_RIGHT].enabled);

  if (preferFront && ((sonarPingPhase++ & 1) == 0)) {
    pick = SONAR_FRONT;
  } else {
    for (int n = 0; n < SONAR_COUNT; n++) {
      uint8_t idx = (uint8_t)((sonarScanIndex + 1 + n) % SONAR_COUNT);
      if (!sonars[idx].enabled) {
        continue;
      }
      if (preferFront && idx == SONAR_FRONT) {
        continue;
      }
      pick = idx;
      break;
    }
    if (pick == 255) {
      for (int n = 0; n < SONAR_COUNT; n++) {
        if (sonars[n].enabled) {
          pick = (uint8_t)n;
          break;
        }
      }
    }
  }
  if (pick == 255) {
    return;
  }
  sonarScanIndex = pick;

  SonarSensor &s = sonars[sonarScanIndex];
  noInterrupts();
  s.waitingFall = false;
  s.echoUs = 0;
  interrupts();
  digitalWrite(s.trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(s.trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(s.trigPin, LOW);
  sonarLastTriggerMs = nowMs;
}

int sonarFrontCm() {
  return sonars[SONAR_FRONT].distanceCm;
}

int sonarSideCm() {
  if (pulloverSide == PULL_LEFT) {
    return sonars[SONAR_LEFT].distanceCm;
  }
  if (pulloverSide == PULL_RIGHT) {
    return sonars[SONAR_RIGHT].distanceCm;
  }
  return -1;
}

void sendRangeTelemetry() {
  uint32_t nowMs = millis();
  if ((uint32_t)(nowMs - lastRangeTxMs) < PULLOVER_RANGE_TX_MS) {
    return;
  }
  lastRangeTxMs = nowMs;
  Serial1.print("RANGE,");
  Serial1.print(sonarFrontCm());
  Serial1.print(',');
  Serial1.println(sonarSideCm());
}

int pulloverCreepThrottlePulse() {
  int forwardOutput =
      RC_NEUTRAL + (RC_MAX - RC_NEUTRAL) * PULLOVER_CREEP_CAP / 100;
  if (REVERSE_THROTTLE) {
    return RC_NEUTRAL - (RC_NEUTRAL - RC_MIN) * PULLOVER_CREEP_CAP / 100;
  }
  return forwardOutput;
}

int pulloverSteerTowardWall() {
  int angle = (pulloverSide == PULL_LEFT) ? -PULLOVER_STEER_MAX : PULLOVER_STEER_MAX;
  int side = sonarSideCm();
  if (side > 0) {
    int err = side - PULLOVER_SIDE_TARGET_CM;
    // Scale steer by error; still capped.
    int mag = constrain(abs(err) * 3, 8, PULLOVER_STEER_MAX);
    angle = (pulloverSide == PULL_LEFT) ? -mag : mag;
    // If too close to wall, steer away slightly
    if (err < -PULLOVER_SIDE_BAND_CM) {
      angle = (pulloverSide == PULL_LEFT) ? mag / 2 : -mag / 2;
    }
  }
  return mapSteeringAngle(angle);
}

void cancelPullover() {
  pulloverSide = PULL_NONE;
  pulloverStartMs = 0;
  pulloverStableStartMs = 0;
  sonarDisableAll();
}

void finishPulloverOk() {
  cancelPullover();
  setNeutral();
  mode = MODE_MANUAL;
  armed = false;
  neutralStartMs = 0;
  Serial1.println("DONE,PULLOVER");
}

void pulloverFrontFault() {
  cancelPullover();
  emergencyStop();
  Serial1.println("ERR,PULLOVER,FRONT");
}

void pulloverAbortByPi() {
  cancelPullover();
  mode = MODE_MANUAL;
  armed = false;
  neutralStartMs = 0;
  setNeutral();
  Serial1.println("ERR,PULLOVER,ABORT");
}

// Pi takeover for pull-over: seizes outputs even if TX sticks are not centered
// (same idea as OVERRIDE,ON). Needs a live receiver; ignores stick position.
bool startPullover(int side) {
  if (stopLatched) {
    return false;
  }
  if (mode == MODE_OVERRIDE) {
    return false;
  }
  if (!rcOK) {
    return false;
  }

  cancelDrive();
  clearOverrideState();
  pulloverSide = (PulloverSide)side;
  pulloverStartMs = millis();
  pulloverStableStartMs = 0;
  lastRangeTxMs = 0;
  lastPiHeartbeatMs = millis();
  mode = MODE_PULLOVER;
  armed = true;  // Pi owns motion; STATUS shows active drive during manoeuvre
  neutralStartMs = 0;
  sonarEnableForPullover(side);
  setNeutral();  // cut TX throttle immediately, then creep under Pi control
  return true;
}

void updatePullover() {
  uint32_t nowMs = millis();

  if ((uint32_t)(nowMs - lastPiHeartbeatMs) > PI_HEARTBEAT_TIMEOUT_MS) {
    cancelPullover();
    emergencyStop();
    Serial1.println("ERR,PI_TIMEOUT");
    return;
  }

  if (!rcOK) {
    cancelPullover();
    emergencyStop();
    Serial1.println("ERR,RC_LOST");
    return;
  }

  if ((uint32_t)(nowMs - pulloverStartMs) > PULLOVER_TIMEOUT_MS) {
    cancelPullover();
    setNeutral();
    mode = MODE_MANUAL;
    armed = false;
    Serial1.println("ERR,PULLOVER,TIMEOUT");
    return;
  }

  sendRangeTelemetry();

  int front = sonarFrontCm();
  int side = sonarSideCm();

  if (front > 0 && front < PULLOVER_FRONT_STOP_CM) {
    pulloverFrontFault();
    return;
  }

  // Wait until we have at least one side reading before creeping hard
  int steerPulse = pulloverSteerTowardWall();
  int thrPulse = pulloverCreepThrottlePulse();

  bool inBand = (side > 0) &&
      (abs(side - PULLOVER_SIDE_TARGET_CM) <= PULLOVER_SIDE_BAND_CM);

  if (inBand) {
    if (pulloverStableStartMs == 0) {
      pulloverStableStartMs = nowMs;
    }
    // Ease throttle while holding position
    thrPulse = RC_NEUTRAL + (thrPulse - RC_NEUTRAL) / 3;
    steerPulse = RC_NEUTRAL;
    if ((uint32_t)(nowMs - pulloverStableStartMs) >= PULLOVER_STABLE_MS) {
      finishPulloverOk();
      return;
    }
  } else {
    pulloverStableStartMs = 0;
  }

  // Apply creep with pullover-specific throttle (bypass normal CAP)
  steerOutput = constrain(steerPulse, RC_MIN, RC_MAX);
  throttleOutput = constrain(thrPulse, RC_MIN, RC_MAX);
  steeringServo.writeMicroseconds(steerOutput);
  throttleESC.writeMicroseconds(throttleOutput);
}

// ---------------- THROTTLE MAPPING ---------------------------

// Maps a raw throttle pulse to a capped output pulse.
// Forward and reverse caps are independent.

int mapThrottle(int input) {
  input = constrain(input, RC_MIN, RC_MAX);

  int forwardSpan = RC_MAX - RC_NEUTRAL;
  int reverseSpan = RC_NEUTRAL - RC_MIN;

  int forwardOutput =
      RC_NEUTRAL + forwardSpan * forwardCap / 100;

  int reverseOutput =
      RC_NEUTRAL - reverseSpan * reverseCap / 100;

  // For ESCs with inverted forward/reverse direction
  if (REVERSE_THROTTLE) {
    if (input >= RC_NEUTRAL) {
      return map(
        input,
        RC_NEUTRAL, RC_MAX,
        RC_NEUTRAL, reverseOutput
      );
    }

    return map(
      input,
      RC_MIN, RC_NEUTRAL,
      forwardOutput, RC_NEUTRAL
    );
  }

  if (input >= RC_NEUTRAL) {
    return map(
      input,
      RC_NEUTRAL, RC_MAX,
      RC_NEUTRAL, forwardOutput
    );
  }

  return map(
    input,
    RC_MIN, RC_NEUTRAL,
    reverseOutput, RC_NEUTRAL
  );
}

// Apply separate emergency movement caps. Never use normal CAP settings here.
int mapOverrideThrottle(int input) {
  input = constrain(input, RC_MIN, RC_MAX);
  const int f = RC_NEUTRAL + (RC_MAX - RC_NEUTRAL) * OVERRIDE_FORWARD_CAP / 100;
  const int r = RC_NEUTRAL - (RC_NEUTRAL - RC_MIN) * OVERRIDE_REVERSE_CAP / 100;
  if (REVERSE_THROTTLE) {
    return input >= RC_NEUTRAL
        ? map(input, RC_NEUTRAL, RC_MAX, RC_NEUTRAL, r)
        : map(input, RC_MIN, RC_NEUTRAL, f, RC_NEUTRAL);
  }
  return input >= RC_NEUTRAL
      ? map(input, RC_NEUTRAL, RC_MAX, RC_NEUTRAL, f)
      : map(input, RC_MIN, RC_NEUTRAL, r, RC_NEUTRAL);
}

// Convert angle percentage (-100..100) into servo pulse.
// Negative = left, positive = right.

int mapSteeringAngle(int angle) {
  angle = constrain(angle, -100, 100);

  if (REVERSE_STEERING) {
    angle = -angle;
  }

  if (angle < 0) {
    return map(
      angle,
      -100, 0,
      RC_MIN, RC_NEUTRAL
    );
  }

  return map(
    angle,
    0, 100,
    RC_NEUTRAL, RC_MAX
  );
}

// ---------------- OUTPUT CONTROL -----------------------------

void setNeutral() {
  steerOutput = RC_NEUTRAL;
  throttleOutput = RC_NEUTRAL;

  steeringServo.writeMicroseconds(steerOutput);
  throttleESC.writeMicroseconds(throttleOutput);
}

void setOutputs(int steeringPulse, int throttlePulse) {
  steerOutput = constrain(
    steeringPulse, RC_MIN, RC_MAX
  );

  throttleOutput = mapThrottle(throttlePulse);

  steeringServo.writeMicroseconds(steerOutput);
  throttleESC.writeMicroseconds(throttleOutput);
}

void cancelDrive() {
  driveActive = false;
  driveStartMs = 0;
  driveDurationMs = 0;

  autoSteer = RC_NEUTRAL;
  autoThrottle = RC_NEUTRAL;
}

void cancelOverrideDrive() {
  overrideDriveActive = false;
  overrideDriveStartMs = 0;
  overrideDriveDurationMs = 0;
  overrideThrottle = RC_NEUTRAL;
}

void clearOverrideState() {
  overrideMotionArmed = false;
  overrideEnteredMs = 0;
  overrideSteer = RC_NEUTRAL;
  cancelOverrideDrive();
}

// Pi takeover: immediate neutral throttle, no automatic motor re-arming.
// This works from MANUAL or AUTO even if the RC throttle is non-neutral.
void enterPiOverride() {
  cancelDrive();
  clearOverrideState();
  cancelPullover();
  mode = MODE_OVERRIDE;
  armed = false;
  neutralStartMs = 0;
  overrideEnteredMs = millis();
  lastPiHeartbeatMs = millis();
  setNeutral();
}

// Override steering is allowed while motor throttle is held at neutral.
void setPiOverrideSteering(int angle) {
  angle = constrain(angle, -OVERRIDE_MAX_STEER, OVERRIDE_MAX_STEER);
  overrideSteer = mapSteeringAngle(angle);
  // Apply immediately; never apply receiver throttle in this mode.
  steerOutput = overrideSteer;
  throttleOutput = RC_NEUTRAL;
  steeringServo.writeMicroseconds(steerOutput);
  throttleESC.writeMicroseconds(throttleOutput);
}

void enterManualDisarmed() {
  mode = MODE_MANUAL;
  armed = false;
  neutralStartMs = 0;

  cancelDrive();
  clearOverrideState();
  cancelPullover();
  setNeutral();
}

void emergencyStop() {
  stopLatched = true;
  armed = false;
  neutralStartMs = 0;

  cancelDrive();
  clearOverrideState();
  cancelPullover();
  setNeutral();
}

// ---------------- OPTION A: PI EMERGENCY STOP -----------------
// Independent of Option D override. Works in MANUAL, AUTO or
// OVERRIDE, even while the receiver continues sending commands.
// This latches neutral outputs; only a safe RESET can release it.
// ESC neutral is not guaranteed to brake the moving vehicle.
void piEmergencyStop() {
  emergencyStop();
}

// ---------------- RECEIVER MONITORING ------------------------

void updateReceiver() {
  uint16_t sPulse, tPulse;
  uint32_t sTime, tTime;

  noInterrupts();

  sPulse = steeringChannel.pulseWidth;
  tPulse = throttleChannel.pulseWidth;

  sTime = steeringChannel.lastValidTime;
  tTime = throttleChannel.lastValidTime;

  steerErrors = steeringChannel.invalidCount;
  throttleErrors = throttleChannel.invalidCount;

  interrupts();

  uint32_t now = micros();

  rcSteerOK =
      sTime != 0 &&
      (uint32_t)(now - sTime) <= RC_TIMEOUT_US;

  rcThrottleOK =
      tTime != 0 &&
      (uint32_t)(now - tTime) <= RC_TIMEOUT_US;

  rcOK = rcSteerOK && rcThrottleOK;

  rcSteer = sPulse;
  rcThrottle = tPulse;
}

bool throttleIsNeutral() {
  return abs(rcThrottle - RC_NEUTRAL)
         <= NEUTRAL_WINDOW_US;
}

// ---------------- STATUS REPORTING ---------------------------

const char* modeName() {
  if (stopLatched) {
    return "STOPPED";
  }

  if (mode == MODE_OVERRIDE) return "OVERRIDE";
  if (mode == MODE_PULLOVER) return "PULLOVER";
  return mode == MODE_AUTO ? "AUTO" : "MANUAL";
}

// STATUS fields:
// STATUS,mode,armed,rcOK,rcSteer,rcThrottle,
//        steerOut,throttleOut,forwardCap,reverseCap,
//        driveActive,uptimeMs

void sendStatus() {
  Serial1.print("STATUS,");
  Serial1.print(modeName());
  Serial1.print(',');
  Serial1.print(mode == MODE_OVERRIDE ? (overrideMotionArmed ? 1 : 0) : (armed ? 1 : 0));
  Serial1.print(',');
  Serial1.print(rcOK ? 1 : 0);
  Serial1.print(',');
  Serial1.print(rcSteer);
  Serial1.print(',');
  Serial1.print(rcThrottle);
  Serial1.print(',');
  Serial1.print(steerOutput);
  Serial1.print(',');
  Serial1.print(throttleOutput);
  Serial1.print(',');
  Serial1.print(forwardCap);
  Serial1.print(',');
  Serial1.print(reverseCap);
  Serial1.print(',');
  Serial1.print((driveActive || overrideDriveActive || mode == MODE_PULLOVER) ? 1 : 0);
  Serial1.print(',');
  Serial1.println(millis());
}

// ---------------- NUMBER PARSING -----------------------------

// Avoids Arduino String and dynamic memory allocation.

bool parseLongStrict(const char* text, long &value) {
  if (text == nullptr || *text == '\0') {
    return false;
  }

  char* end = nullptr;

  value = strtol(text, &end, 10);

  // Reject missing digits and trailing characters.
  if (end == text || *end != '\0') {
    return false;
  }

  return true;
}

// ---------------- UART COMMAND HANDLER -----------------------

void handleCommand(char* line) {
  updateReceiver();

  // PING also refreshes the AUTO heartbeat.
  // Response contains RP2040 uptime in milliseconds.
  if (strcmp(line, "PING") == 0) {
    lastPiHeartbeatMs = millis();

    Serial1.print("PONG,");
    Serial1.println(millis());
    return;
  }

  if (strcmp(line, "STATUS?") == 0) {
    sendStatus();
    return;
  }

  // OPTION A: emergency stop always works, regardless of mode,
  // receiver throttle, or whether Option D is currently active.
  // Keep STOP backwards-compatible with Rp2040Client.stop().
  if (strcmp(line, "STOP") == 0) {
    if (mode == MODE_PULLOVER) {
      cancelPullover();
    }
    piEmergencyStop();
    Serial1.println("OK,STOP");
    return;
  }
  if (strcmp(line, "ESTOP") == 0) {
    if (mode == MODE_PULLOVER) {
      cancelPullover();
    }
    piEmergencyStop();
    Serial1.println("OK,ESTOP");
    return;
  }
  if (strcmp(line, "PULLOVER,ABORT") == 0) {
    if (mode == MODE_PULLOVER) {
      pulloverAbortByPi();
    } else {
      Serial1.println("OK,PULLOVER,ABORT");
      sonarDisableAll();
    }
    return;
  }

  // RESET clears the STOP latch but does not arm the car.
  if (strcmp(line, "RESET") == 0) {
    if (!rcOK || !throttleIsNeutral()) {
      Serial1.println("ERR,NOT_SAFE");
      return;
    }

    stopLatched = false;
    enterManualDisarmed();

    Serial1.println("OK,RESET");
    return;
  }

  // A latched STOP cannot be overridden by any Pi command.
  // No motion or configuration commands while stopped.
  if (stopLatched) {
    Serial1.println("ERR,STOP_LATCHED");
    return;
  }

  // ---------------- EMERGENCY PI OVERRIDE -------------------
  // ON has priority over MANUAL and AUTO, even with non-neutral RC input.
  if (strcmp(line, "OVERRIDE,ON") == 0) {
    enterPiOverride();
    Serial1.println("OK,OVERRIDE,ON");
    return;
  }

  if (strncmp(line, "OVERRIDE,", 9) == 0) {
    if (mode != MODE_OVERRIDE) {
      Serial1.println("ERR,NOT_OVERRIDE");
      return;
    }

    if (strcmp(line, "OVERRIDE,OFF") == 0) {
      // Prevent sudden transfer of a live throttle signal to the ESC.
      if (!rcOK || !throttleIsNeutral() || overrideDriveActive) {
        Serial1.println("ERR,OVERRIDE_RELEASE_UNSAFE");
        return;
      }
      enterManualDisarmed();  // re-arm only after 1.5 s of neutral
      Serial1.println("OK,OVERRIDE,OFF");
      return;
    }

    if (strcmp(line, "OVERRIDE,ARM") == 0) {
      if (!rcOK ||
          (uint32_t)(millis() - overrideEnteredMs) < OVERRIDE_NEUTRAL_HOLD_MS ||
          (uint32_t)(millis() - lastPiHeartbeatMs) > PI_HEARTBEAT_TIMEOUT_MS) {
        Serial1.println("ERR,OVERRIDE_NOT_READY");
        return;
      }
      overrideMotionArmed = true;
      Serial1.println("OK,OVERRIDE,ARM");
      return;
    }

    if (strncmp(line, "OVERRIDE,STEER,", 15) == 0) {
      long angle;
      if (!parseLongStrict(line + 15, angle) ||
          angle < -OVERRIDE_MAX_STEER || angle > OVERRIDE_MAX_STEER) {
        Serial1.println("ERR,OVERRIDE_STEER_RANGE");
        return;
      }
      cancelOverrideDrive();  // steering command also stops any ongoing override movement
      setPiOverrideSteering((int)angle);
      Serial1.println("OK,OVERRIDE,STEER");
      return;
    }

    if (strncmp(line, "OVERRIDE,DRIVE,", 15) == 0) {
      if (!overrideMotionArmed || !rcOK) {
        Serial1.println("ERR,OVERRIDE_NOT_ARMED");
        return;
      }
      char* directionText = line + 15;
      char* angleText = strchr(directionText, ',');
      if (!angleText) { Serial1.println("ERR,OVERRIDE_DRIVE_FORMAT"); return; }
      *angleText++ = '\0';
      char* durationText = strchr(angleText, ',');
      if (!durationText) { Serial1.println("ERR,OVERRIDE_DRIVE_FORMAT"); return; }
      *durationText++ = '\0';
      long direction, angle, duration;
      if (!parseLongStrict(directionText, direction) ||
          !parseLongStrict(angleText, angle) ||
          !parseLongStrict(durationText, duration)) {
        Serial1.println("ERR,OVERRIDE_DRIVE_FORMAT");
        return;
      }
      if ((direction != 1 && direction != 2) ||
          angle < -OVERRIDE_MAX_STEER || angle > OVERRIDE_MAX_STEER ||
          duration < 1 || duration > OVERRIDE_MAX_DRIVE_MS) {
        Serial1.println("ERR,OVERRIDE_DRIVE_RANGE");
        return;
      }
      overrideSteer = mapSteeringAngle((int)angle);
      // mapOverrideThrottle handles REVERSE_THROTTLE exactly once.
      overrideThrottle = (direction == 1) ? RC_MAX : RC_MIN;
      overrideDriveStartMs = millis();
      overrideDriveDurationMs = (uint32_t)duration;
      overrideDriveActive = true;
      Serial1.println("OK,OVERRIDE,DRIVE");
      return;
    }

    Serial1.println("ERR,OVERRIDE_COMMAND");
    return;
  }

  // ---------------- SONAR DIAGNOSTIC ------------------------
  // SONAR,ON  — continuous RANGE3,front,left,right (no motion)
  // SONAR,OFF — stop streaming / power sensors down
  // SONAR?    — same stream for ~3 s then auto-off
  if (strcmp(line, "SONAR,ON") == 0 || strcmp(line, "SONAR?") == 0) {
    if (mode == MODE_PULLOVER) {
      Serial1.println("ERR,PULLOVER,ACTIVE");
      return;
    }
    sonarEnableAll();
    lastRangeTxMs = 0;
    if (strcmp(line, "SONAR,ON") == 0) {
      sonarDiagContinuous = true;
      sonarDiagUntilMs = 0;
      Serial1.println("OK,SONAR,ON");
    } else {
      sonarDiagContinuous = false;
      sonarDiagUntilMs = millis() + 3000;
      Serial1.println("OK,SONAR");
    }
    return;
  }

  if (strcmp(line, "SONAR,OFF") == 0) {
    sonarDisableAll();
    sonarDiagContinuous = false;
    sonarDiagUntilMs = 0;
    Serial1.println("OK,SONAR,OFF");
    return;
  }

  // ---------------- PULLOVER --------------------------------

  if (strcmp(line, "PULLOVER,LEFT") == 0 ||
      strcmp(line, "PULLOVER,RIGHT") == 0) {
    if (mode == MODE_OVERRIDE) {
      Serial1.println("ERR,OVERRIDE_ACTIVE");
      return;
    }
    if (mode == MODE_PULLOVER) {
      Serial1.println("ERR,PULLOVER,ACTIVE");
      return;
    }
    int side =
        (strcmp(line, "PULLOVER,LEFT") == 0) ? (int)PULL_LEFT : (int)PULL_RIGHT;
    if (!startPullover(side)) {
      Serial1.println("ERR,PULLOVER,NOT_READY");
      return;
    }
    Serial1.println(side == (int)PULL_LEFT ? "OK,PULLOVER,LEFT" : "OK,PULLOVER,RIGHT");
    return;
  }

  // ---------------- MODE: MANUAL ----------------------------

  if (strcmp(line, "MODE,MANUAL") == 0) {
    if (mode == MODE_OVERRIDE) {
      Serial1.println("ERR,OVERRIDE_ACTIVE");
      return;
    }
    if (mode == MODE_PULLOVER) {
      cancelPullover();
    }
    enterManualDisarmed();

    Serial1.println("OK,MANUAL");
    return;
  }

  // ---------------- MODE: AUTO ------------------------------

  if (strcmp(line, "MODE,AUTO") == 0) {
    if (mode == MODE_OVERRIDE) {
      Serial1.println("ERR,OVERRIDE_ACTIVE");
      return;
    }
    if (mode == MODE_PULLOVER) {
      Serial1.println("ERR,PULLOVER,ACTIVE");
      return;
    }
    if (!armed || !rcOK || !throttleIsNeutral()) {
      Serial1.println("ERR,NOT_ARMED_OR_NEUTRAL");
      return;
    }

    mode = MODE_AUTO;
    cancelDrive();
    setNeutral();

    // Start heartbeat timer on entering AUTO.
    lastPiHeartbeatMs = millis();

    Serial1.println("OK,AUTO");
    return;
  }

  // ---------------- CAP SETTINGS ----------------------------

  if (strncmp(line, "CAP,", 4) == 0) {
    if (mode == MODE_OVERRIDE) {
      Serial1.println("ERR,OVERRIDE_ACTIVE");
      return;
    }
    char* directionText = line + 4;
    char* percentText = strchr(directionText, ',');

    if (!percentText) {
      Serial1.println("ERR,CAP_FORMAT");
      return;
    }

    *percentText++ = '\0';

    long percent;

    if (!parseLongStrict(percentText, percent) ||
        percent < 0 || percent > 100) {
      Serial1.println("ERR,CAP_RANGE");
      return;
    }

    if (strcmp(directionText, "FORWARD") == 0) {
      forwardCap = (int)percent;
      Serial1.println("OK,CAP,FORWARD");
    }
    else if (strcmp(directionText, "REVERSE") == 0) {
      reverseCap = (int)percent;
      Serial1.println("OK,CAP,REVERSE");
    }
    else {
      Serial1.println("ERR,CAP_DIRECTION");
    }

    return;
  }

  // ---------------- TIMED DRIVE -----------------------------
  //
  // DRIVE,<direction>,<angle>,<duration>
  //
  // direction: 1 forward, 2 backward
  // angle:    -100 left, 0 straight, +100 right
  // duration: 1..5000 milliseconds
  //
  // New DRIVE replaces any active DRIVE.
  // Duration begins when the RP2040 accepts the command.
  // ----------------------------------------------------------

  if (strncmp(line, "DRIVE,", 6) == 0) {
    if (mode == MODE_PULLOVER) {
      Serial1.println("ERR,PULLOVER,ACTIVE");
      return;
    }
    if (mode != MODE_AUTO || !armed || !rcOK) {
      Serial1.println("ERR,NOT_AUTO");
      return;
    }

    char* directionText = line + 6;

    char* angleText = strchr(directionText, ',');
    if (!angleText) {
      Serial1.println("ERR,DRIVE_FORMAT");
      return;
    }

    *angleText++ = '\0';

    char* durationText = strchr(angleText, ',');
    if (!durationText) {
      Serial1.println("ERR,DRIVE_FORMAT");
      return;
    }

    *durationText++ = '\0';

    long direction;
    long angle;
    long duration;

    if (!parseLongStrict(directionText, direction) ||
        !parseLongStrict(angleText, angle) ||
        !parseLongStrict(durationText, duration)) {
      Serial1.println("ERR,DRIVE_FORMAT");
      return;
    }

    if ((direction != 1 && direction != 2) ||
        angle < -100 || angle > 100 ||
        duration < 1 ||
        duration > MAX_DRIVE_DURATION_MS) {
      Serial1.println("ERR,DRIVE_RANGE");
      return;
    }

    autoSteer = mapSteeringAngle((int)angle);

    // Direction determines which side of neutral is used.
    // The mapThrottle() function applies the speed cap.
    if (direction == 1) {
      autoThrottle = RC_MAX;
    }
    else {
      autoThrottle = RC_MIN;
    }

    driveStartMs = millis();
    driveDurationMs = (uint32_t)duration;
    driveActive = true;

    Serial1.println("OK,DRIVE");
    return;
  }

  Serial1.println("ERR,UNKNOWN_COMMAND");
}

// ---------------- NON-BLOCKING UART READER -------------------

void readPiSerial() {
  // Limit work per loop to prevent serial traffic from
  // monopolizing the controller.

  for (int i = 0; i < 64 && Serial1.available(); i++) {
    char c = (char)Serial1.read();

    if (c == '\n') {
      if (!discardingLine && commandLength > 0) {
        commandBuffer[commandLength] = '\0';
        handleCommand(commandBuffer);
      }

      commandLength = 0;
      discardingLine = false;
    }
    else if (c != '\r') {
      if (discardingLine) {
        continue;
      }

      if (commandLength < COMMAND_BUFFER_SIZE - 1) {
        commandBuffer[commandLength++] = c;
      }
      else {
        // Ignore the remainder of this oversized line.
        commandLength = 0;
        discardingLine = true;

        Serial1.println("ERR,LINE_TOO_LONG");
      }
    }
  }
}

// ---------------- SAFETY + CONTROL LOOP ----------------------

void updateControl() {
  uint32_t nowMs = millis();

  // STOP latch is highest priority and must never be cleared implicitly.
  if (stopLatched) {
    setNeutral();
    return;
  }

  // Pi loss during Pi-controlled modes causes a LATCHED stop.
  if (mode == MODE_AUTO || mode == MODE_OVERRIDE || mode == MODE_PULLOVER) {
    if ((uint32_t)(nowMs - lastPiHeartbeatMs) > PI_HEARTBEAT_TIMEOUT_MS) {
      emergencyStop();
      Serial1.println("ERR,PI_TIMEOUT");
      return;
    }
  }

  if (mode == MODE_PULLOVER) {
    updatePullover();
    return;
  }

  // Override must be processed before the normal RC receiver path.
  // The RC receiver is still monitored for safety, but cannot drive outputs.
  if (mode == MODE_OVERRIDE) {
    if (!rcOK) {
      emergencyStop();
      Serial1.println("ERR,RC_LOST");
      return;
    }

    if (overrideDriveActive) {
      if ((uint32_t)(nowMs - overrideDriveStartMs) >= overrideDriveDurationMs) {
        cancelOverrideDrive();
        Serial1.println("DONE,OVERRIDE,DRIVE");
      }
    }

    steerOutput = overrideSteer;
    throttleOutput = overrideDriveActive
        ? mapOverrideThrottle(overrideThrottle) : RC_NEUTRAL;
    steeringServo.writeMicroseconds(steerOutput);
    throttleESC.writeMicroseconds(throttleOutput);
    return;
  }

  // Normal modes require a valid receiver.
  if (!rcOK) {
    enterManualDisarmed();
    return;
  }

  // Arming requires continuous neutral RC throttle for 1.5 seconds.
  if (!armed) {
    if (throttleIsNeutral()) {
      if (neutralStartMs == 0) neutralStartMs = nowMs;
      if ((uint32_t)(nowMs - neutralStartMs) >= ARM_TIME_MS) {
        armed = true;
        Serial.println("ARMED");
      }
    } else {
      neutralStartMs = 0;
    }
    setNeutral();
    return;
  }

  if (mode == MODE_AUTO) {
    if (driveActive) {
      if ((uint32_t)(nowMs - driveStartMs) < driveDurationMs) {
        setOutputs(autoSteer, autoThrottle);
      } else {
        cancelDrive();
        setNeutral();
        Serial1.println("DONE,DRIVE");
      }
    } else {
      setNeutral();
    }
    return;
  }

  // Manual RC controls apply only when not in Pi override.
  setOutputs(rcSteer, rcThrottle);
}

// ---------------- USB DEBUG OUTPUT --------------------------

void printDiagnostics() {
  static uint32_t lastPrintMs = 0;

  if ((uint32_t)(millis() - lastPrintMs) < 250) {
    return;
  }

  lastPrintMs = millis();

  Serial.print("Mode: ");
  Serial.print(modeName());

  Serial.print(" | Armed: ");
  Serial.print(armed ? "YES" : "NO");

  Serial.print(" | RC: ");
  Serial.print(rcOK ? "OK" : "LOST");

  Serial.print(" | Steer IN/OUT: ");
  Serial.print(rcSteer);
  Serial.print("/");
  Serial.print(steerOutput);

  Serial.print(" | Throttle IN/OUT: ");
  Serial.print(rcThrottle);
  Serial.print("/");
  Serial.print(throttleOutput);

  Serial.print(" | Caps F/R: ");
  Serial.print(forwardCap);
  Serial.print("%/");
  Serial.print(reverseCap);
  Serial.print("%");

  Serial.print(" | Drive: ");
  Serial.print(driveActive ? "ACTIVE" : "IDLE");

  Serial.print(" | Pull: ");
  if (mode == MODE_PULLOVER) {
    Serial.print(pulloverSide == PULL_LEFT ? "L" : "R");
    Serial.print(" F=");
    Serial.print(sonarFrontCm());
    Serial.print(" S=");
    Serial.print(sonarSideCm());
  } else if (sonarDiagContinuous || sonarDiagUntilMs != 0) {
    Serial.print("DIAG F=");
    Serial.print(sonars[SONAR_FRONT].distanceCm);
    Serial.print(" L=");
    Serial.print(sonars[SONAR_LEFT].distanceCm);
    Serial.print(" R=");
    Serial.print(sonars[SONAR_RIGHT].distanceCm);
  } else {
    Serial.print("OFF");
  }

  Serial.print(" | Invalid S/T: ");
  Serial.print(steerErrors);
  Serial.print("/");
  Serial.print(throttleErrors);

  Serial.print(" | Uptime: ");
  Serial.println(millis());
}

// ---------------- SETUP -------------------------------------

void setup() {
  // USB debug
  Serial.begin(115200);

  // Raspberry Pi UART
  Serial1.setTX(PI_TX);
  Serial1.setRX(PI_RX);
  Serial1.begin(PI_BAUD);

  // Receiver inputs
  pinMode(STEER_IN, INPUT);
  pinMode(THROTTLE_IN, INPUT);

  // Servo/ESC outputs
  steeringServo.attach(STEER_OUT, 900, 2100);
  throttleESC.attach(THROTTLE_OUT, 900, 2100);

  setNeutral();

  // HC-SR04 pins (disabled until PULLOVER)
  for (int i = 0; i < SONAR_COUNT; i++) {
    pinMode(sonars[i].trigPin, OUTPUT);
    digitalWrite(sonars[i].trigPin, LOW);
    pinMode(sonars[i].echoPin, INPUT);
  }
  sonarDisableAll();

  attachInterrupt(digitalPinToInterrupt(SONAR_FRONT_ECHO), sonarFrontISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(SONAR_LEFT_ECHO), sonarLeftISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(SONAR_RIGHT_ECHO), sonarRightISR, CHANGE);

  // Receiver interrupts
  attachInterrupt(
    digitalPinToInterrupt(STEER_IN),
    steeringISR,
    CHANGE
  );

  attachInterrupt(
    digitalPinToInterrupt(THROTTLE_IN),
    throttleISR,
    CHANGE
  );

  Serial.println();
  Serial.println("=================================");
  Serial.println("RP2040 RC + RASPBERRY PI (v5)");
  Serial.println("=================================");
  Serial.println("UART: 115200 baud");
  Serial.println("TX: GP12 | RX: GP13");
  Serial.println("Sonar F:14/15 L:8/9 R:16/17 (off until PULLOVER)");
  Serial.println("Initial mode: MANUAL");
  Serial.println("Initial caps: F20% / R20%");
  Serial.println("AUTO/OVERRIDE/PULLOVER heartbeat timeout: 250 ms");
  Serial.println("Override: F15% R10%, steer +/-50, max 1500ms");
  Serial.println("Pullover: side 10cm, front stop 25cm, creep 12%");
  Serial.println("Waiting for receiver and neutral...");
}

// ---------------- MAIN LOOP ---------------------------------

void loop() {
  updateReceiver();

  // Read serial before applying control, so STOP and
  // updated caps take effect in the same loop iteration.
  readPiSerial();

  serviceSonar();

  // SONAR debug: stream RANGE3,front,left,right (timed or continuous)
  if (sonarDiagContinuous || sonarDiagUntilMs != 0) {
    uint32_t nowMs = millis();
    if ((uint32_t)(nowMs - lastRangeTxMs) >= PULLOVER_RANGE_TX_MS) {
      lastRangeTxMs = nowMs;
      Serial1.print("RANGE3,");
      Serial1.print(sonars[SONAR_FRONT].distanceCm);
      Serial1.print(',');
      Serial1.print(sonars[SONAR_LEFT].distanceCm);
      Serial1.print(',');
      Serial1.println(sonars[SONAR_RIGHT].distanceCm);
    }
    if (!sonarDiagContinuous && sonarDiagUntilMs != 0 &&
        (int32_t)(nowMs - sonarDiagUntilMs) >= 0) {
      sonarDisableAll();
      sonarDiagUntilMs = 0;
      Serial1.println("DONE,SONAR");
    }
  }

  updateControl();

  printDiagnostics();
}
