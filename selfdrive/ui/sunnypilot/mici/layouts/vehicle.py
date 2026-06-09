"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os
from collections.abc import Callable

from openpilot.selfdrive.ui.mici.widgets.button import BigToggle
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

_SP_PARAMS_DIR = '/data/params_sp'
_PARAMS_DIR = '/data/params/d'


def _read_param_bool(key: str) -> bool:
  for base in (_SP_PARAMS_DIR, _PARAMS_DIR):
    try:
      path = os.path.join(base, key)
      if os.path.exists(path):
        return open(path).read().strip() == '1'
    except Exception:
      pass
  return False


def _write_param_bool(key: str, value: bool):
  try:
    os.makedirs(_SP_PARAMS_DIR, exist_ok=True)
    with open(os.path.join(_SP_PARAMS_DIR, key), 'w') as f:
      f.write('1' if value else '0')
  except Exception:
    pass


class BigDirectParamToggle(BigToggle):
  """BigToggle variant that reads/writes the param file directly.

  Used for params not yet registered in the prebuilt params_pyx.so binary,
  bypassing the key allowlist check in Params.check_key().
  """
  def __init__(self, text: str, param: str, toggle_callback: Callable | None = None):
    super().__init__(text, "", initial_state=_read_param_bool(param), toggle_callback=toggle_callback)
    self._param = param

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    _write_param_bool(self._param, self._checked)

  def refresh(self):
    self.set_checked(_read_param_bool(self._param))


class VehicleLayoutMici(NavScroller):
  def __init__(self, back_callback: Callable):
    super().__init__()
    self.set_back_callback(back_callback)

    self._ti_toggle = BigDirectParamToggle(
      tr("torque interceptor (mici)"),
      "MazdaTorqueInterceptorEnabled",
    )
    self._ti_toggle.set_enabled(lambda: not ui_state.engaged)

    self._scroller.add_widgets([self._ti_toggle])

  def show_event(self):
    super().show_event()
    is_mazda = ui_state.CP is not None and ui_state.CP.brand == 'mazda'
    self._ti_toggle.set_visible(is_mazda)
    self._ti_toggle.refresh()
