"""
Copyright (c) 2021-, rav4kumar, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.sunnypilot.selfdrive.controls.lib.accel_personality.accel_controller import (
  AccelPersonalityController,
  AccelPersonality,
  A_MAX_V,
  A_MIN_V,
)
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlannerSP
from opendbc.car.interfaces import ACCEL_MIN

PERSONALITIES = (AccelPersonality.eco, AccelPersonality.normal, AccelPersonality.sport)


def _make(personality, v_cruise=0.0):
  c = AccelPersonalityController()
  c._personality = personality
  c._enabled = True
  c._v_cruise = v_cruise
  return c


class FakeLead:
  def __init__(self, status=False, d_rel=0.0, v_rel=0.0, v_lead=0.0, a_lead=0.0, fcw=False):
    self.status = status
    self.dRel = d_rel
    self.vRel = v_rel
    self.vLead = v_lead
    self.aLeadK = a_lead
    self.fcw = fcw


class FakeRadarState:
  def __init__(self, lead_one=None, lead_two=None):
    self.leadOne = lead_one or FakeLead()
    self.leadTwo = lead_two or FakeLead()


class FakeCarState:
  def __init__(self, v_ego=0.0):
    self.vEgo = v_ego


class FakeControlsState:
  def __init__(self, force_decel=False):
    self.forceDecel = force_decel


class FakeSM:
  def __init__(self, radarstate, v_ego=0.0, force_decel=False):
    self._data = {
      'radarState': radarstate,
      'carState': FakeCarState(v_ego),
      'controlsState': FakeControlsState(force_decel),
    }

  def __getitem__(self, k):
    return self._data[k]


def _sm(lead_one=None, lead_two=None, v_ego=0.0, force_decel=False):
  return FakeSM(FakeRadarState(lead_one, lead_two), v_ego, force_decel)


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


class TestFollowDistance:
  def test_eco_loosest_sport_tightest(self):
    eco = _make(AccelPersonality.eco)
    normal = _make(AccelPersonality.normal)
    sport = _make(AccelPersonality.sport)
    assert eco.get_t_follow() > normal.get_t_follow() > sport.get_t_follow()

  def test_values_sane(self):
    for p in PERSONALITIES:
      assert 1.0 <= _make(p).get_t_follow() <= 2.0


class TestJerkScale:
  def test_eco_smoother_sport_snappier(self):
    eco = _make(AccelPersonality.eco)
    normal = _make(AccelPersonality.normal)
    sport = _make(AccelPersonality.sport)
    assert eco.get_jerk_scale() > normal.get_jerk_scale() > sport.get_jerk_scale()

  def test_normal_is_stock(self):
    assert _make(AccelPersonality.normal).get_jerk_scale() == 1.0


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


class TestBrakeFloor:
  def test_profile_brake_floor(self):
    c = _make(AccelPersonality.normal)
    assert abs(c.get_profile_min_accel(15.0) - A_MIN_V[AccelPersonality.normal][2]) < 1e-6

  def test_eco_softest_sport_deepest(self):
    eco = _make(AccelPersonality.eco)
    normal = _make(AccelPersonality.normal)
    sport = _make(AccelPersonality.sport)
    for v in (0.0, 5.0, 15.0, 35.0):
      assert eco.get_min_accel(v) > normal.get_min_accel(v) > sport.get_min_accel(v)

  def test_disabled_uses_stock_floor(self):
    c = _make(AccelPersonality.normal)
    c.set_enabled(False)
    assert c.get_min_accel(10.0) == ACCEL_MIN

  def test_closing_lead_opens_more_brake(self):
    c = _make(AccelPersonality.normal)
    lead = FakeLead(status=True, d_rel=14.0, v_lead=7.0)
    profile_min = c.get_profile_min_accel(14.0)
    assert ACCEL_MIN <= c.get_min_accel(14.0, _sm(lead)) < profile_min

  def test_critical_lead_uses_stock_floor(self):
    c = _make(AccelPersonality.normal)
    lead = FakeLead(status=True, d_rel=8.0, v_lead=1.0)
    assert c.get_min_accel(16.0, _sm(lead)) == ACCEL_MIN

  def test_stop_and_force_decel_use_stock_floor(self):
    c = _make(AccelPersonality.normal)
    assert c.get_min_accel(8.0, should_stop=True) == ACCEL_MIN
    assert c.get_min_accel(8.0, force_decel=True) == ACCEL_MIN


class TestBrakeShaping:
  def test_low_risk_lead_caps_unnecessary_brake(self):
    c = _make(AccelPersonality.eco)
    lead = FakeLead(status=True, d_rel=45.0, v_lead=12.0)
    shaped = c.shape_decel(12.0, -2.0, _sm(lead))
    assert shaped == c.get_profile_min_accel(12.0)

  def test_closing_lead_adds_early_brake(self):
    c = _make(AccelPersonality.normal)
    lead = FakeLead(status=True, d_rel=24.0, v_lead=10.0)
    shaped = c.shape_decel(14.0, 0.1, _sm(lead))
    assert shaped < 0.1
    assert shaped >= c.get_min_accel(14.0, _sm(lead))

  def test_disabled_shape_is_noop(self):
    c = _make(AccelPersonality.normal)
    c.set_enabled(False)
    lead = FakeLead(status=True, d_rel=45.0, v_lead=12.0)
    assert c.shape_decel(12.0, -2.0, _sm(lead)) == -2.0


class TestPlannerBrakeHook:
  def test_stop_not_raised_to_comfort_floor(self):
    p = object.__new__(LongitudinalPlannerSP)
    p.accel_controller = _make(AccelPersonality.eco)
    p._last_plan_sm = _sm(FakeLead(status=True, d_rel=45.0, v_lead=12.0), v_ego=12.0)
    p._smoothed_radarstate = None
    p.output_should_stop = True

    assert p._apply_accel_personality_decel(-2.0) == -2.0

  def test_force_decel_not_raised_to_comfort_floor(self):
    p = object.__new__(LongitudinalPlannerSP)
    p.accel_controller = _make(AccelPersonality.eco)
    p._last_plan_sm = _sm(FakeLead(status=True, d_rel=45.0, v_lead=12.0), v_ego=12.0, force_decel=True)
    p._smoothed_radarstate = None
    p.output_should_stop = False

    assert p._apply_accel_personality_decel(-2.0) == -2.0
