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
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlannerSP
from opendbc.car.interfaces import ACCEL_MIN


class _Lead:
  def __init__(self, status=True, v_rel=0.0, d_rel=50.0):
    self.status = status
    self.vRel = v_rel
    self.dRel = d_rel


class TestBrakeFloorRelax:
  GENTLE = -1.5

  def test_no_lead_keeps_floor(self):
    assert LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, None) == self.GENTLE
    assert LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, _Lead(status=False, v_rel=-10)) == self.GENTLE

  def test_not_closing_keeps_floor(self):
    assert LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, _Lead(v_rel=0.0)) == self.GENTLE
    assert LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, _Lead(v_rel=-1.0)) == self.GENTLE

  def test_fast_closing_full_authority(self):
    # the da event: lead 87 m closing -17.5 m/s -> floor must relax to full ACCEL_MIN
    f = LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, _Lead(v_rel=-17.5, d_rel=87.0))
    assert abs(f - ACCEL_MIN) < 1e-6

  def test_low_ttc_full_authority(self):
    f = LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, _Lead(v_rel=-5.0, d_rel=15.0))  # ttc 3s
    assert abs(f - ACCEL_MIN) < 1e-6

  def test_partial_relax(self):
    f = LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, _Lead(v_rel=-3.0, d_rel=60.0))
    assert ACCEL_MIN < f < self.GENTLE

  def test_never_softer_than_floor(self):
    for v in (-2.5, -4.0, -10.0):
      assert LongitudinalPlannerSP._relax_brake_floor(self.GENTLE, _Lead(v_rel=v, d_rel=30.0)) <= self.GENTLE + 1e-9

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
