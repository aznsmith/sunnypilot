#pragma once

#include "opendbc/safety/declarations.h"

// CAN msgs we care about
#define MAZDA_LKAS          0x243U
#define MAZDA_LKAS_HUD      0x440U
#define MAZDA_CRZ_CTRL      0x21cU
#define MAZDA_CRZ_BTNS      0x09dU
#define MAZDA_STEER_TORQUE  0x240U
#define MAZDA_ENGINE_DATA   0x202U
#define MAZDA_PEDALS        0x165U
// Torque Interceptor (MICI hardware): steering command consumed by the interceptor
// device itself, sent in addition to the stock MAZDA_LKAS message
#define MAZDA_TI_LKAS       0x249U
// Torque Interceptor: torque-sensor feedback / device state message, injected by the
// interceptor on the aux bus
#define TI_STEER_TORQUE     0x24AU

// CAN bus numbers
#define MAZDA_MAIN 0
#define MAZDA_AUX  1
#define MAZDA_CAM  2

// param flag masks
const int FLAG_MAZDA_TORQUE_INTERCEPTOR = 1;

bool torque_interceptor = false;

// track msgs coming from OP so that we know what CAM msgs to drop and what to forward
static void mazda_rx_hook(const CANPacket_t *msg) {
  if ((int)msg->bus == MAZDA_MAIN) {
    if (msg->addr == MAZDA_ENGINE_DATA) {
      // sample speed: scale by 0.01 to get kph
      int speed = (msg->data[2] << 8) | msg->data[3];
      vehicle_moving = speed > 10; // moving when speed > 0.1 kph
    }

    // Once the Torque Interceptor is installed, the driver-torque sample comes from
    // TI_STEER_TORQUE on the aux bus (below) instead -- the interceptor sits on the
    // torque-sensor line itself, so the stock MAZDA_STEER_TORQUE reading is no longer
    // the interceptor-adjusted value.
    if (msg->addr == MAZDA_STEER_TORQUE && !torque_interceptor) {
      int torque_driver_new = msg->data[0] - 127U;
      // update array of samples
      update_sample(&torque_driver, torque_driver_new);
    }

    // enter controls on rising edge of ACC, exit controls on ACC off
    if (msg->addr == MAZDA_CRZ_CTRL) {
      bool cruise_engaged = msg->data[0] & 0x8U;
      pcm_cruise_check(cruise_engaged);
      acc_main_on = GET_BIT(msg, 17U);
    }

    if (msg->addr == MAZDA_ENGINE_DATA) {
      gas_pressed = (msg->data[4] || (msg->data[5] & 0xF0U));
    }

    if (msg->addr == MAZDA_PEDALS) {
      brake_pressed = (msg->data[0] & 0x10U);
    }
  }

  if (torque_interceptor && (msg->bus == MAZDA_AUX) && (msg->addr == TI_STEER_TORQUE)) {
    int torque_driver_new = msg->data[0] - 127;
    update_sample(&torque_driver, torque_driver_new);
  }
}

static bool mazda_tx_hook(const CANPacket_t *msg) {
  const TorqueSteeringLimits MAZDA_STEERING_LIMITS = {
    .max_torque = 800,
    .max_rate_up = 10,
    .max_rate_down = 25,
    .max_rt_delta = 300,
    .driver_torque_multiplier = 1,
    .driver_torque_allowance = 15,
    .type = TorqueDriverLimited,
  };

  bool tx = true;
  // Check if msg is sent on the main BUS
  if (msg->bus == (unsigned char)MAZDA_MAIN) {
    // steer cmd checks
    // With the Torque Interceptor installed, MAZDA_LKAS is skipped here and
    // MAZDA_TI_LKAS is checked instead (below) -- see that block's comment for why.
    if (msg->addr == MAZDA_LKAS && !torque_interceptor) {
      int desired_torque = (((msg->data[0] & 0x0FU) << 8) | msg->data[1]) - 2048U;

      if (steer_torque_cmd_checks(desired_torque, -1, MAZDA_STEERING_LIMITS)) {
        tx = false;
      }
    }

    // cruise buttons check
    if (msg->addr == MAZDA_CRZ_BTNS) {
      // allow resume spamming while controls allowed, but
      // only allow cancel while controls not allowed
      bool cancel_cmd = (msg->data[0] == 0x1U);
      if (!controls_allowed && !cancel_cmd) {
        tx = false;
      }
    }
  }

  // Torque Interceptor: rate/magnitude-limit the interceptor's own steering command.
  //
  // steer_torque_cmd_checks() tracks its rate-limit state (desired_torque_last,
  // rt_torque_last, torque_driver) in module-level globals shared by the whole safety
  // framework, not per-message-ID -- it cannot safely be called twice per cycle for two
  // different messages without the two calls corrupting each other's state (confirmed:
  // no other brand in this codebase calls it more than once per tx_hook, and the
  // underlying state is not parameterizable without a cross-brand refactor of
  // lateral.h/declarations.h/safety.h). So MAZDA_LKAS and MAZDA_TI_LKAS cannot both be
  // independently enforced here -- exactly one of them is checked.
  //
  // MAZDA_TI_LKAS is the one checked. Per the MoreTorque installation guide
  // (moretorques-organization.gitbook.io), the comma device's CAN harness plugs into the
  // TI board first, which then connects onward to the car -- i.e. the interceptor sits
  // inline on the CAN bus itself (not just on the analog torque-sensor wire), so every
  // message panda sends toward the car, including MAZDA_LKAS, physically routes through
  // it. Combined with the device defining its own independent CAM_LKAS2/TI_FEEDBACK
  // protocol, this makes it highly likely MAZDA_LKAS is superseded/ignored once the
  // interceptor is installed. This is device-topology evidence, not a protocol-level
  // guarantee: no CAN trace with the device installed has confirmed MAZDA_LKAS is
  // actually dropped on the far side. VERIFY WITH A CAN LOG (interceptor installed,
  // comparing MAZDA_LKAS vs MAZDA_TI_LKAS effect on steering) BEFORE THIS SHIPS TO A
  // REAL CAR. Reuses MAZDA_STEERING_LIMITS (not a separate constant) because the source
  // fork's carcontroller.py computes this channel's torque using the same
  // CarControllerParams.STEER_MAX/DELTA_UP/DELTA_DOWN as the stock channel -- see
  // report.md / torque_interceptor_faithful_port.patch for the verified comparison.
  if (torque_interceptor && (msg->bus == MAZDA_AUX) && (msg->addr == MAZDA_TI_LKAS)) {
    // CAM_LKAS2 LKAS_REQUEST : 3|12@0+ (1,-2048) -- same 12-bit encoding as MAZDA_LKAS's
    // LKAS_REQUEST signal (both packed identically by mazdacan.py).
    int desired_torque = (((msg->data[0] & 0x0FU) << 8) | msg->data[1]) - 2048U;

    if (steer_torque_cmd_checks(desired_torque, -1, MAZDA_STEERING_LIMITS)) {
      tx = false;
    }
  }

  return tx;
}

static safety_config mazda_init(uint16_t param) {
  static const CanMsg MAZDA_TX_MSGS[] = {{MAZDA_LKAS, 0, 8, .check_relay = true}, {MAZDA_CRZ_BTNS, 0, 8, .check_relay = false}, {MAZDA_LKAS_HUD, 0, 8, .check_relay = true}};
  // MAZDA_LKAS is kept allow-listed even with the Torque Interceptor active (the source
  // fork still transmits it every cycle); MAZDA_TI_LKAS is added on the aux bus with
  // check_relay=false since it never reaches the camera-relay path. See mazda_tx_hook()
  // for why only MAZDA_TI_LKAS gets steer_torque_cmd_checks() when this flag is set.
  static const CanMsg MAZDA_TI_TX_MSGS[] = {{MAZDA_LKAS, 0, 8, .check_relay = true}, {MAZDA_TI_LKAS, MAZDA_AUX, 8, .check_relay = false},
                                             {MAZDA_CRZ_BTNS, 0, 8, .check_relay = false}, {MAZDA_LKAS_HUD, 0, 8, .check_relay = true}};

  static RxCheck mazda_rx_checks[] = {
    {.msg = {{MAZDA_CRZ_CTRL,     0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_CRZ_BTNS,     0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_STEER_TORQUE, 0, 8, 83U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_ENGINE_DATA,  0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_PEDALS,       0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };
  static RxCheck mazda_ti_rx_checks[] = {
    {.msg = {{MAZDA_CRZ_CTRL,     0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_CRZ_BTNS,     0, 8, 10U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_STEER_TORQUE, 0, 8, 83U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_ENGINE_DATA,  0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_PEDALS,       0, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{TI_STEER_TORQUE,    MAZDA_AUX, 8, 50U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  torque_interceptor = GET_FLAG(param, FLAG_MAZDA_TORQUE_INTERCEPTOR);

  safety_config ret = BUILD_SAFETY_CFG(mazda_rx_checks, MAZDA_TX_MSGS);
  if (torque_interceptor) {
    ret = BUILD_SAFETY_CFG(mazda_ti_rx_checks, MAZDA_TI_TX_MSGS);
  }
  return ret;
}

const safety_hooks mazda_hooks = {
  .init = mazda_init,
  .rx = mazda_rx_hook,
  .tx = mazda_tx_hook,
};
