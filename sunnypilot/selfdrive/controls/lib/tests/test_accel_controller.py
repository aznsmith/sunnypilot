"""
Copyright (c) 2021-, rav4kumar, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.sunnypilot.selfdrive.controls.lib.accel_personality.accel_controller import (
  AccelPersonalityController,
  AccelPersonality,
  A_MAX_V,
)

PERSONALITIES = (AccelPersonality.eco, AccelPersonality.normal, AccelPersonality.sport)


def _make(personality, v_cruise=0.0):
  c = AccelPersonalityController()
  c.set_accel_personality(personality)
  c._v_cruise = v_cruise
  return c


class TestGasCeiling:
  def test_positive(self):
    c = _make(AccelPersonality.normal)
    assert c.get_max_accel(8.0) > 0.5

  def test_sport_at_least_eco(self):
    eco = _make(AccelPersonality.eco)
    sport = _make(AccelPersonality.sport)
    for v in (0.0, 4.0, 8.0, 16.0, 40.0):
      assert sport.get_max_accel(v) >= eco.get_max_accel(v) - 1e-9

  def test_unset_cruise_no_rampoff(self):
    c = _make(AccelPersonality.normal, v_cruise=0.0)
    assert abs(c.get_max_accel(8.0) - A_MAX_V[AccelPersonality.normal][2]) < 1e-6

  def test_rampoff_at_and_above_setpoint(self):
    c = _make(AccelPersonality.normal, v_cruise=20.0)
    assert c.get_max_accel(20.0) == 0.0
    assert c.get_max_accel(25.0) == 0.0
    assert c.get_max_accel(10.0) > 0.0

  def test_rampoff_partial(self):
    c = _make(AccelPersonality.normal, v_cruise=20.0)
    full = _make(AccelPersonality.normal, v_cruise=0.0)
    assert 0.0 < c.get_max_accel(17.5) < full.get_max_accel(17.5)


class TestPersonalityApi:
  def test_cycle(self):
    c = _make(AccelPersonality.eco)
    seen = {c.cycle_accel_personality() for _ in range(3)}
    assert seen == {int(p) for p in PERSONALITIES}

  def test_toggle_enabled(self):
    c = _make(AccelPersonality.normal)
    c.set_enabled(False)
    assert c.toggle_enabled() is True
    assert c.toggle_enabled() is False
