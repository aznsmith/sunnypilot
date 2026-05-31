"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os

from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp

_PARAMS_DIR = '/data/params/d'


def _get_ti_enabled() -> bool:
  try:
    return ui_state.params.get_bool("MazdaTorqueInterceptorEnabled")
  except Exception:
    try:
      p = os.path.join(_PARAMS_DIR, 'MazdaTorqueInterceptorEnabled')
      return os.path.exists(p) and open(p).read().strip() == '1'
    except Exception:
      return False


def _set_ti_enabled(value: bool):
  try:
    ui_state.params.put_bool("MazdaTorqueInterceptorEnabled", value)
  except Exception:
    try:
      with open(os.path.join(_PARAMS_DIR, 'MazdaTorqueInterceptorEnabled'), 'w') as f:
        f.write('1' if value else '0')
    except Exception:
      pass

DESCRIPTIONS = {
  'torque_interceptor': tr_noop(
    'Enable if you have installed the MICI Torque Interceptor on your Mazda. '
    'This allows sunnypilot to control steering at all speeds by bypassing the '
    'factory LKAS speed limitation. Requires the MICI device connected to the OBD-II port.'
  ),
}


class MazdaSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    self.torque_interceptor = toggle_item_sp(
      lambda: tr("Torque Interceptor (MICI)"),
      description=lambda: tr(DESCRIPTIONS["torque_interceptor"]),
      initial_state=_get_ti_enabled(),
      callback=self._on_torque_interceptor,
      enabled=lambda: not ui_state.engaged,
    )

    self.items = [
      self.torque_interceptor,
    ]

  def _on_torque_interceptor(self, state: bool):
    _set_ti_enabled(state)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def update_settings(self):
    pass
