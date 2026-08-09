"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.sunnypilot.sunnylink.athena import sunnylinkd


class _FakeParams:
  """Stand-in for the module-level `params` (a compiled common.params_pyx.Params
  instance, whose bound methods are read-only and can't be monkeypatched directly
  -- see git history for the AttributeError this replaced). Also stubs get()/put()
  since saveParams()'s ParamsVersion counter tail uses the same `params` object."""
  def __init__(self, is_offroad: bool):
    self._is_offroad = is_offroad
    self._store: dict[str, str] = {}

  def get_bool(self, key: str) -> bool:
    return self._is_offroad if key == "IsOffroad" else False

  def get(self, key: str):
    return self._store.get(key)

  def put(self, key: str, value: str, block: bool = False):
    self._store[key] = value


class TestSunnylinkdMethods:
  def setup_method(self):
    self.saved_params = []

    self.original_save = sunnylinkd.save_param_from_base64_encoded_string
    self.original_params = sunnylinkd.params

    def mock_save_param(key, value, compression=False):
      self.saved_params.append((key, value, compression))

    sunnylinkd.save_param_from_base64_encoded_string = mock_save_param

  def teardown_method(self):
    sunnylinkd.save_param_from_base64_encoded_string = self.original_save
    sunnylinkd.params = self.original_params

  def _set_offroad(self, is_offroad: bool):
    """Swap the module-level `params` for a fake -- ui_state isn't accessible from
    sunnylinkd's process, so IsOffroad is what actually gates offroad_only params."""
    sunnylinkd.params = _FakeParams(is_offroad)

  def test_saveParams_blocked(self):
    blocked_params = {
      "GithubUsername": "attacker",
      "GithubSshKeys": "ssh-rsa attacker_key",
    }

    sunnylinkd.saveParams(blocked_params)

    assert len(self.saved_params) == 0

  def test_saveParams_allowed(self):
    allowed_params = {
      "SpeedLimitOffset": "5",
      "MyCustomParam": "123"
    }

    sunnylinkd.saveParams(allowed_params)

    # verify content
    assert len(self.saved_params) == 2
    keys_saved = [p[0] for p in self.saved_params]
    assert "SpeedLimitOffset" in keys_saved
    assert "MyCustomParam" in keys_saved

  def test_saveParams_mixed(self):
    mixed_params = {
      "GithubUsername": "attacker",
      "SpeedLimitOffset": "10"
    }

    sunnylinkd.saveParams(mixed_params)

    # should save allowed one
    assert len(self.saved_params) == 1
    assert self.saved_params[0][0] == "SpeedLimitOffset"
    assert self.saved_params[0][1] == "10"

  def test_saveParams_offroad_only_param_blocked_while_onroad(self):
    # MazdaTorqueInterceptorEnabled and SubaruStopAndGo both declare offroad_only
    # enablement in settings_ui.json -- confirm the remote path can't silently
    # apply either while onroad, same as the on-device UI's own offroad gate.
    self._set_offroad(False)

    sunnylinkd.saveParams({"MazdaTorqueInterceptorEnabled": "1", "SubaruStopAndGo": "1"})

    # write never reached save_param_from_base64_encoded_string, so nothing changed
    assert len(self.saved_params) == 0

  def test_saveParams_offroad_only_param_allowed_while_offroad(self):
    self._set_offroad(True)

    sunnylinkd.saveParams({"MazdaTorqueInterceptorEnabled": "1", "SubaruStopAndGo": "1"})

    assert len(self.saved_params) == 2
    keys_saved = [p[0] for p in self.saved_params]
    assert "MazdaTorqueInterceptorEnabled" in keys_saved
    assert "SubaruStopAndGo" in keys_saved

  def test_saveParams_non_offroad_only_param_allowed_while_onroad(self):
    # SpeedLimitOffset has no offroad_only enablement -- confirm the new gate is
    # scoped to offroad_only params specifically, not blocking writes generally
    # while onroad.
    self._set_offroad(False)

    sunnylinkd.saveParams({"SpeedLimitOffset": "5"})

    assert len(self.saved_params) == 1
    assert self.saved_params[0][0] == "SpeedLimitOffset"
    assert self.saved_params[0][1] == "5"
