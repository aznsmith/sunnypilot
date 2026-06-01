"""
Copyright (c) 2021-, rav4kumar, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.sunnypilot.selfdrive.controls.lib.longitudinal_planner import apply_stop_hold, STOP_GO_FRAMES


class TestStopHold:
  def test_latches_at_stop_and_suppresses_creep(self):
    a, ss, held, _ = apply_stop_hold(False, 0, 0.2, 0.3, True)
    assert held is True
    assert ss is True
    assert a <= 0.0

  def test_not_latched_while_moving(self):
    a, ss, held, _ = apply_stop_hold(False, 0, 5.0, -1.0, True)
    assert held is False
    assert a == -1.0

  def test_holds_through_should_stop_flicker(self):
    a, ss, held, gc = apply_stop_hold(True, 0, 0.1, 0.2, False)
    assert held is True
    assert ss is True
    assert a <= 0.0
    assert gc == 1

  def test_go_count_resets_on_should_stop(self):
    _, _, held, gc = apply_stop_hold(True, 3, 0.1, 0.0, True)
    assert held is True
    assert gc == 0

  def test_releases_after_sustained_go(self):
    held, gc = True, 0
    for _ in range(STOP_GO_FRAMES):
      _, _, held, gc = apply_stop_hold(held, gc, 0.1, 0.5, False)
    assert held is False
    a, ss, held, _ = apply_stop_hold(held, gc, 0.1, 0.5, False)
    assert a == 0.5
    assert ss is False
