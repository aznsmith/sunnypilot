"""
Copyright (c) 2021-, rav4kumar, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.sunnypilot.selfdrive.controls.lib.accel_personality.accel_controller import (
  AccelPersonalityController,
  AccelPersonality,
  A_BRAKE_FLOOR_BP,
  A_BRAKE_FLOOR_V,
)
from opendbc.car.interfaces import ACCEL_MIN

PERSONALITIES = (AccelPersonality.eco, AccelPersonality.normal, AccelPersonality.sport)
SPEEDS = (0.0, 2.0, 8.0, 16.0, 30.0, 40.0, 55.0)


def _make(personality):
  c = AccelPersonalityController()
  c.set_accel_personality(personality)
  return c


class TestBrakeFloor:
  def test_never_below_accel_min(self):
    # ACC-mode hard brake ceiling must never exceed the stock/physical floor
    for p in PERSONALITIES:
      c = _make(p)
      for v in SPEEDS:
        assert c.get_brake_floor(v) >= ACCEL_MIN - 1e-9

  def test_is_braking_authority(self):
    # a meaningful negative floor at speed (not the near-zero coast value)
    c = _make(AccelPersonality.normal)
    assert c.get_brake_floor(16.0) <= -1.5

  def test_sport_firmer_than_eco(self):
    eco = _make(AccelPersonality.eco)
    sport = _make(AccelPersonality.sport)
    for v in (2.0, 8.0, 16.0, 30.0, 40.0):
      # sport allows at least as much braking (more negative) as eco
      assert sport.get_brake_floor(v) <= eco.get_brake_floor(v) + 1e-9

  def test_low_speed_gentler_than_high(self):
    for p in PERSONALITIES:
      c = _make(p)
      assert c.get_brake_floor(2.0) > c.get_brake_floor(30.0)

  def test_matches_table_at_breakpoint(self):
    c = _make(AccelPersonality.normal)
    expected = max(ACCEL_MIN, A_BRAKE_FLOOR_V[AccelPersonality.normal][2])  # 16 m/s breakpoint
    assert abs(c.get_brake_floor(A_BRAKE_FLOOR_BP[2]) - expected) < 1e-6

  def test_clamped_below_table(self):
    # any table entry softer than ACCEL_MIN would be clamped; all entries are >= ACCEL_MIN
    for p in PERSONALITIES:
      assert min(A_BRAKE_FLOOR_V[p]) >= ACCEL_MIN - 1e-9
