"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp

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
      initial_state=ui_state.params.get_bool("MazdaTorqueInterceptorEnabled"),
      callback=self._on_torque_interceptor,
      enabled=lambda: not ui_state.engaged,
    )

    self.items = [
      self.torque_interceptor,
    ]

  def _on_torque_interceptor(self, state: bool):
    ui_state.params.put_bool("MazdaTorqueInterceptorEnabled", state)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def update_settings(self):
    pass
