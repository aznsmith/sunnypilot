"""
Copyright (c) 2021-, rav4kumar, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from cereal import custom
import numpy as np
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.common.params import Params
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX

AccelPersonality = custom.LongitudinalPlanSP.AccelerationPersonality
ACCEL_PERSONALITY_OPTIONS = [AccelPersonality.eco, AccelPersonality.normal, AccelPersonality.sport]

A_MAX_BP = [0.0, 4.0, 8.0, 16.0, 40.0]
A_MAX_V = {
  AccelPersonality.eco:    [1.40, 1.40, 1.30, 0.43, 0.08],
  AccelPersonality.normal: [1.80, 1.80, 1.45, 0.50, 0.15],
  AccelPersonality.sport:  [2.20, 2.20, 1.60, 0.70, 0.25],
}

RAMP_OFF_RANGE = 5.0

T_FOLLOW = {
  AccelPersonality.eco:    1.55,
  AccelPersonality.normal: 1.45,
  AccelPersonality.sport:  1.30,
}

JERK_SCALE = {
  AccelPersonality.eco:    1.2,
  AccelPersonality.normal: 1.0,
  AccelPersonality.sport:  0.8,
}

PARAM_REFRESH_FRAMES = max(1, int(1.0 / DT_MDL))


class AccelPersonalityController:
  def __init__(self):
    self.params = Params()
    self.frame = 0
    val = self.params.get('AccelPersonality')
    self._personality = val if val is not None else AccelPersonality.normal
    self._enabled = self.params.get_bool('AccelPersonalityEnabled')
    self._v_cruise = 0.0

  def update(self, sm=None):
    self.frame += 1
    if sm is not None:
      try:
        vc_kph = float(sm['carState'].vCruise)
        self._v_cruise = 0.0 if vc_kph >= V_CRUISE_MAX else vc_kph * CV.KPH_TO_MS
      except Exception:
        pass

    if self.frame % PARAM_REFRESH_FRAMES == 0:
      val = self.params.get('AccelPersonality')
      self._personality = val if val is not None else AccelPersonality.normal
      self._enabled = self.params.get_bool('AccelPersonalityEnabled')

  @property
  def accel_personality(self) -> int:
    return self._personality

  def get_accel_personality(self) -> int:
    return int(self._personality)

  def set_accel_personality(self, personality: int):
    if personality in ACCEL_PERSONALITY_OPTIONS:
      self._personality = personality
      self.params.put('AccelPersonality', personality)

  def cycle_accel_personality(self) -> int:
    idx = ACCEL_PERSONALITY_OPTIONS.index(self._personality) if self._personality in ACCEL_PERSONALITY_OPTIONS else 0
    nxt = ACCEL_PERSONALITY_OPTIONS[(idx + 1) % len(ACCEL_PERSONALITY_OPTIONS)]
    self.set_accel_personality(nxt)
    return int(nxt)

  def is_enabled(self) -> bool:
    return self._enabled

  def set_enabled(self, enabled: bool):
    self._enabled = bool(enabled)
    self.params.put_bool('AccelPersonalityEnabled', self._enabled)

  def toggle_enabled(self) -> bool:
    self.set_enabled(not self._enabled)
    return self._enabled

  def reset(self, personality: int | None = None):
    if personality is None or personality not in ACCEL_PERSONALITY_OPTIONS:
      personality = AccelPersonality.normal
    self._personality = personality
    self.params.put('AccelPersonality', self._personality)
    self.frame = 0
    self._v_cruise = 0.0

  def get_max_accel(self, v_ego: float) -> float:
    base = float(np.interp(max(0.0, v_ego), A_MAX_BP, A_MAX_V[self._personality]))
    if self._v_cruise <= 0.0:
      return base
    ramp = float(np.clip((self._v_cruise - v_ego) / RAMP_OFF_RANGE, 0.0, 1.0))
    return base * ramp

  def get_t_follow(self) -> float:
    return T_FOLLOW[self._personality]

  def get_jerk_scale(self) -> float:
    return JERK_SCALE[self._personality]
