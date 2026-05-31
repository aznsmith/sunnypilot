"""
Copyright (c) 2021-, rav4kumar, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from cereal import custom
import numpy as np
from opendbc.car.interfaces import ACCEL_MIN
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.common.params import Params
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX

AccelPersonality = custom.LongitudinalPlanSP.AccelerationPersonality
ACCEL_PERSONALITY_OPTIONS = [AccelPersonality.eco, AccelPersonality.normal, AccelPersonality.sport]

# Gas ceiling (MPC accel-max) per personality, by v_ego. Ramps off near set speed.
A_MAX_BP = [0.0, 4.0, 8.0, 16.0, 40.0]
A_MAX_V = {
  AccelPersonality.eco:    [1.40, 1.40, 1.30, 0.43, 0.08],
  AccelPersonality.normal: [1.80, 1.80, 1.45, 0.50, 0.15],
  AccelPersonality.sport:  [2.20, 2.20, 1.60, 0.70, 0.25],
}

# ACC-mode braking authority (hard MPC accel-min). Per-speed brake ceiling per personality.
# Iteration 1: GENTLE START. Soft at city/traffic speed (where gentleness is felt and short
# stops keep it safe), firmer toward highway (retain authority where soft braking is dangerous).
# Clamped to ACCEL_MIN so it never exceeds the stock/physical floor. Used ONLY in ACC mode;
# blended and controller-off fall back to ACCEL_MIN (full authority). Harder-than-floor braking
# defers to FCW + Toyota PCS/AEB. Tighten toward stock if firmer-lead stops feel late.
A_BRAKE_FLOOR_BP = [2.0, 8.0, 16.0, 30.0, 40.0]  # m/s
A_BRAKE_FLOOR_V = {
  AccelPersonality.eco:    [-1.0, -1.3, -1.8, -2.4, -2.8],
  AccelPersonality.normal: [-1.3, -1.7, -2.2, -2.8, -3.2],
  AccelPersonality.sport:  [-1.7, -2.2, -2.8, -3.3, -3.5],
}

RAMP_OFF_RANGE = 5.0
A_MAX_RATE_UP = 1.2
A_MAX_RATE_DOWN = 0.6

PARAM_REFRESH_FRAMES = max(1, int(1.0 / DT_MDL))


class AccelPersonalityController:
  """Two jobs: the gas ceiling (get_max_accel) and the ACC-mode brake floor (get_brake_floor),
  both per-personality (eco/normal/sport). The planner feeds these into the MPC accel box.
  Blended-mode and controller-off braking are handled stock by the planner (ACCEL_MIN)."""

  def __init__(self):
    self.params = Params()
    self.frame = 0
    self._first = True

    val = self.params.get('AccelPersonality')
    self._personality = val if val is not None else AccelPersonality.normal
    self._enabled = self.params.get_bool('AccelPersonalityEnabled')

    self._v_cruise = 0.0
    self._a_max = 1.50

    self._cache_v: float | None = None
    self._cache_v_cruise: float | None = None
    self._cache_a_max = self._a_max

  def update(self, sm=None):
    self.frame += 1
    self._cache_v = None
    self._cache_v_cruise = None

    if sm is not None:
      try:
        # >= V_CRUISE_MAX means cruise unset (255) -> no setpoint
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
    self._first = True
    self._a_max = 1.50
    self._cache_v = None
    self._cache_v_cruise = None

  def get_max_accel(self, v_ego: float) -> float:
    v_ego = max(0.0, v_ego)
    if (self._cache_v is not None
        and abs(self._cache_v - v_ego) < 0.01
        and self._cache_v_cruise == self._v_cruise):
      return self._cache_a_max
    self._cache_a_max = self._step_max(v_ego)
    self._cache_v = v_ego
    self._cache_v_cruise = self._v_cruise
    return self._cache_a_max

  def get_brake_floor(self, v_ego: float) -> float:
    # ACC-mode hard brake ceiling (MPC accel-min). Stateless per-speed lookup, clamped to
    # the stock physical floor. Tracks v_ego smoothly via interp; output smoothness is handled
    # downstream by the MPC + output_a_target jerk-cap.
    floor = float(np.interp(max(0.0, v_ego), A_BRAKE_FLOOR_BP, A_BRAKE_FLOOR_V[self._personality]))
    return max(ACCEL_MIN, floor)

  def _ramp_off(self, v_ego: float) -> float:
    if self._v_cruise <= 0.0:
      return 1.0
    return float(np.clip((self._v_cruise - v_ego) / RAMP_OFF_RANGE, 0.0, 1.0))

  def _target_max(self, v_ego: float) -> float:
    base = float(np.interp(v_ego, A_MAX_BP, A_MAX_V[self._personality]))
    return base * self._ramp_off(v_ego)

  def _step_max(self, v_ego: float) -> float:
    t_max = self._target_max(v_ego)
    if self._first:
      self._a_max = max(0.0, t_max)
      self._first = False
      return self._a_max
    rate = A_MAX_RATE_UP if t_max > self._a_max else A_MAX_RATE_DOWN
    step = rate * DT_MDL
    # floor at 0: accel_max feeds the MPC box (params[:,1]); never let it invert below accel_min
    self._a_max = max(0.0, float(np.clip(t_max, self._a_max - step, self._a_max + step)))
    return self._a_max
