"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp


class MazdaSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    self.torque_interceptor_toggle = toggle_item_sp(
      tr("Torque Interceptor"), "",
      param="MazdaTorqueInterceptorEnabled", callback=self._on_toggle_changed,
    )

    self.items = [self.torque_interceptor_toggle]

  def _on_toggle_changed(self, _):
    self.update_settings()

  def update_settings(self):
    # Hardware-config toggle, not a driving-mode toggle -- changing it changes which CAN
    # messages/panda safety config get used for steering (see CP.flags/safetyParam wiring
    # in opendbc/sunnypilot/car/interfaces.py's _initialize_mazda()). Restricted to offroad
    # only, same pattern as Subaru's stop-and-go toggles in this same directory.
    description = tr(
      "Enable if the MoreTorque Torque Interceptor hardware is installed on this vehicle. "
      "This changes how steering torque commands and driver-torque feedback are read and "
      "sent -- only enable this if the interceptor hardware is actually installed."
    )
    disabled_msg = "" if ui_state.is_offroad() else tr("Turn vehicle off to toggle.")

    self.torque_interceptor_toggle.action_item.set_enabled(ui_state.is_offroad())
    self.torque_interceptor_toggle.set_description(f"<b>{disabled_msg}</b><br><br>{description}" if disabled_msg else description)
