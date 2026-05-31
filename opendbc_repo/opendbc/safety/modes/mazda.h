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

// Torque Interceptor (MICI) messages
#define MAZDA_TI_LKAS       0x249U  // CAM_LKAS2 — openpilot -> TI device (bus 1)
#define TI_STEER_TORQUE     0x24AU  // TI_FEEDBACK — TI device -> openpilot (bus 1)

// CAN bus numbers
#define MAZDA_MAIN  0
#define MAZDA_TI    1
#define MAZDA_CAM   2

// Safety param flags (must match MazdaFlags in values.py)
#define FLAG_TORQUE_INTERCEPTOR 8U

static bool mazda_ti_enabled = false;

static void mazda_rx_hook(const CANPacket_t *msg) {
  if ((int)msg->bus == MAZDA_MAIN) {
    if (msg->addr == MAZDA_ENGINE_DATA) {
      int speed = (msg->data[2] << 8) | msg->data[3];
      vehicle_moving = speed > 10;
    }

    if (msg->addr == MAZDA_STEER_TORQUE && !mazda_ti_enabled) {
      int torque_driver_new = msg->data[0] - 127U;
      update_sample(&torque_driver, torque_driver_new);
    }

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

  // Read driver torque from TI device when interceptor is active
  if (mazda_ti_enabled && (int)msg->bus == MAZDA_TI) {
    if (msg->addr == TI_STEER_TORQUE) {
      int torque_driver_new = (int)msg->data[0] - 127;
      update_sample(&torque_driver, torque_driver_new);
    }
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

  if (msg->bus == (unsigned char)MAZDA_MAIN) {
    if (msg->addr == MAZDA_LKAS) {
      int desired_torque = (((msg->data[0] & 0x0FU) << 8) | msg->data[1]) - 2048U;
      if (steer_torque_cmd_checks(desired_torque, -1, MAZDA_STEERING_LIMITS)) {
        tx = false;
      }
    }

    if (msg->addr == MAZDA_CRZ_BTNS) {
      bool cancel_cmd = (msg->data[0] == 0x1U);
      if (!controls_allowed && !cancel_cmd) {
        tx = false;
      }
    }
  }

  // Allow and check TI LKAS command on bus 1
  if (mazda_ti_enabled && msg->bus == (unsigned char)MAZDA_TI) {
    if (msg->addr == MAZDA_TI_LKAS) {
      int desired_torque = (((msg->data[0] & 0x0FU) << 8) | msg->data[1]) - 2048U;
      if (steer_torque_cmd_checks(desired_torque, -1, MAZDA_STEERING_LIMITS)) {
        tx = false;
      }
    }
  }

  return tx;
}

static safety_config mazda_init(uint16_t param) {
  mazda_ti_enabled = GET_FLAG(param, FLAG_TORQUE_INTERCEPTOR);

  static const CanMsg MAZDA_TX_MSGS[] = {
    {MAZDA_LKAS,     0, 8, .check_relay = true},
    {MAZDA_CRZ_BTNS, 0, 8, .check_relay = false},
    {MAZDA_LKAS_HUD, 0, 8, .check_relay = true},
  };

  static const CanMsg MAZDA_TI_TX_MSGS[] = {
    {MAZDA_LKAS,     0, 8, .check_relay = true},
    {MAZDA_CRZ_BTNS, 0, 8, .check_relay = false},
    {MAZDA_LKAS_HUD, 0, 8, .check_relay = true},
    {MAZDA_TI_LKAS,  1, 8, .check_relay = false},
  };

  static RxCheck mazda_rx_checks[] = {
    {.msg = {{MAZDA_CRZ_CTRL,     0, 8, 50U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_CRZ_BTNS,     0, 8, 10U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_STEER_TORQUE, 0, 8, 83U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_ENGINE_DATA,  0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_PEDALS,       0, 8, 50U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  static RxCheck mazda_ti_rx_checks[] = {
    {.msg = {{MAZDA_CRZ_CTRL,     0, 8, 50U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_CRZ_BTNS,     0, 8, 10U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_ENGINE_DATA,  0, 8, 100U, .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MAZDA_PEDALS,       0, 8, 50U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{TI_STEER_TORQUE,    1, 8, 50U,  .ignore_checksum = true, .ignore_counter = true, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  if (mazda_ti_enabled) {
    return BUILD_SAFETY_CFG(mazda_ti_rx_checks, MAZDA_TI_TX_MSGS);
  }
  return BUILD_SAFETY_CFG(mazda_rx_checks, MAZDA_TX_MSGS);
}

const safety_hooks mazda_hooks = {
  .init = mazda_init,
  .rx = mazda_rx_hook,
  .tx = mazda_tx_hook,
};
