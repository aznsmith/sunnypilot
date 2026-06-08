from types import SimpleNamespace

from opendbc.can import CANPacker
from opendbc.car import Bus, structs
from opendbc.car.lateral import apply_driver_steer_torque_limits
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.mazda import mazdacan
from opendbc.car.mazda.values import CarControllerParams, Buttons, MazdaSafetyFlags
try:
  from openpilot.common.realtime import ControlsTimer as Timer, DT_CTRL
  from openpilot.common.filter_simple import FirstOrderFilter
  from openpilot.common.params import Params
except ImportError:
  # Stub for standalone opendbc testing (no openpilot runtime available)
  DT_CTRL = 0.01

  class Timer:  # type: ignore[no-redef]
    def __init__(self, duration=0.0): pass
    def active(self) -> bool: return False
    def reset(self) -> None: pass
    @classmethod
    def interval(cls, n: int) -> bool: return False
    @classmethod
    def tick(cls) -> None: pass

  class FirstOrderFilter:  # type: ignore[no-redef]
    def __init__(self, x0=0.0, rc=1.0, dt=DT_CTRL): self.x = x0
    def update(self, x: float) -> float: self.x = x; return x

  class Params:  # type: ignore[no-redef]
    def get(self, key, encoding=None): return None
    def get_bool(self, key): return False

from opendbc.sunnypilot.car.mazda.icbm import IntelligentCruiseButtonManagementInterface

VisualAlert = structs.CarControl.HUDControl.VisualAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState


class CarController(CarControllerBase, IntelligentCruiseButtonManagementInterface):
  def __init__(self, dbc_names, CP, CP_SP):
    CarControllerBase.__init__(self, dbc_names, CP, CP_SP)
    IntelligentCruiseButtonManagementInterface.__init__(self, CP, CP_SP)
    self.apply_torque_last = 0
    self.ti_apply_torque_last = 0
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.brake_counter = 0
    self.ccp = CarControllerParams(CP)
    self._ti_limits = SimpleNamespace(
      STEER_MAX=self.ccp.TI_STEER_MAX,
      STEER_DELTA_UP=self.ccp.TI_STEER_DELTA_UP,
      STEER_DELTA_DOWN=self.ccp.TI_STEER_DELTA_DOWN,
      STEER_DRIVER_ALLOWANCE=self.ccp.TI_STEER_DRIVER_ALLOWANCE,
      STEER_DRIVER_MULTIPLIER=self.ccp.TI_STEER_DRIVER_MULTIPLIER,
      STEER_DRIVER_FACTOR=self.ccp.TI_STEER_DRIVER_FACTOR,
    ) if CP.flags & MazdaSafetyFlags.GEN1 else None
    self.hold_timer = Timer(6.0)
    self.hold_delay = Timer(.5)
    self.resume_timer = Timer(0.5)
    self.cancel_delay = Timer(0.07)

  def update(self, CC, CC_SP, CS, now_nanos):
    can_sends = []

    apply_torque = 0
    ti_apply_torque = 0

    if CC.latActive:
      # calculate steer and also set limits due to driver torque
      new_torque = int(round(CC.actuators.torque * self.ccp.STEER_MAX))
      apply_torque = apply_driver_steer_torque_limits(new_torque, self.apply_torque_last,
                                                      CS.out.steeringTorque, self.ccp)
      if self.CP.flags & MazdaSafetyFlags.TORQUE_INTERCEPTOR:
        if CS.ti_lkas_allowed and self._ti_limits is not None:
          ti_new_torque = int(round(CC.actuators.torque * self.ccp.TI_STEER_MAX))
          ti_apply_torque = apply_driver_steer_torque_limits(ti_new_torque, self.ti_apply_torque_last,
                                                    CS.out.steeringTorque, self._ti_limits)

    self.apply_torque_last = apply_torque
    self.ti_apply_torque_last = ti_apply_torque

    if self.CP.flags & MazdaSafetyFlags.GEN1:
      if CC.cruiseControl.cancel:
        # If brake is pressed, let us wait >70ms before trying to disable crz to avoid
        # a race condition with the stock system, where the second cancel from openpilot
        # will disable the crz 'main on'. crz ctrl msg runs at 50hz. 70ms allows us to
        # read 3 messages and most likely sync state before we attempt cancel.
        self.brake_counter = self.brake_counter + 1
        if self.frame % 10 == 0 and not (CS.out.brakePressed and self.brake_counter < 7):
          # Cancel Stock ACC if it's enabled while OP is disengaged
          # Send at a rate of 10hz until we sync with stock ACC state
          can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, CS.crz_btns_counter, Buttons.CANCEL))
      else:
        self.brake_counter = 0
        if CC.cruiseControl.resume and self.frame % 5 == 0:
          # Mazda Stop and Go requires a RES button (or gas) press if the car stops more than 3 seconds
          # Send Resume button when planner wants car to move
          can_sends.append(mazdacan.create_button_cmd(self.packer, self.CP, CS.crz_btns_counter, Buttons.RESUME))

      # send HUD alerts
      if self.frame % 50 == 0:
        ldw = CC.hudControl.visualAlert == VisualAlert.ldw
        steer_required = CC.hudControl.visualAlert == VisualAlert.steerRequired
        # TODO: find a way to silence audible warnings so we can add more hud alerts
        steer_required = steer_required and CS.lkas_allowed_speed
        can_sends.append(mazdacan.create_alert_command(self.packer, CS.cam_laneinfo, ldw, steer_required))

      if self.CP.openpilotLongitudinalControl:
        hold = False
        if CS.out.standstill:
          hold = self.hold_timer.active()
        else:
          self.hold_timer.reset()

          raw_acc_output = CC.actuators.accel * 1150
          raw_acc_output = max(-1000, min(raw_acc_output, 1000))
          CS.crz_info["ACCEL_CMD"] = raw_acc_output

        if self.frame % 2 == 0:
          can_sends.extend(mazdacan.create_radar_command(self.packer, self.frame, CC.longActive, CS, hold))

    elif self.CP.flags & MazdaSafetyFlags.GEN2:
      if CC.longActive and self.CP.openpilotLongitudinalControl:
        CS.acc["ACCEL_CMD"] = (CC.actuators.accel * 200) + 2000

      resume = False
      hold = False
      if Timer.interval(2):  # send ACC command at 50hz
        if CS.out.standstill:
          if not self.hold_delay.active():
            if ((CC.cruiseControl.resume and CC.actuators.longControlState != LongCtrlState.stopping) or
                CC.cruiseControl.override or CS.out.gasPressed or
                (CC.actuators.longControlState == LongCtrlState.starting) or CS.acc["RESUME"]):
              self.resume_timer.reset()
            else:
              hold = self.hold_timer.active()
        else:
          self.hold_timer.reset()
          self.hold_delay.reset()

        resume = self.resume_timer.active()
        can_sends.append(mazdacan.create_acc_cmd(self.packer, CS.acc, hold, resume))

    # send steering command
    can_sends.extend(mazdacan.create_steering_control(
      self.packer, self.CP, self.frame, apply_torque, CS.cam_lkas,
      ti_apply_torque if self.CP.flags & MazdaSafetyFlags.TORQUE_INTERCEPTOR else None))

    # Intelligent Cruise Button Management (SET+/SET- speed adjustment)
    can_sends.extend(IntelligentCruiseButtonManagementInterface.update(self, CC_SP, CS, self.packer, self.frame, self.last_button_frame))

    new_actuators = CC.actuators.as_builder()
    new_actuators.torque = apply_torque / self.ccp.STEER_MAX
    new_actuators.torqueOutputCan = apply_torque

    self.frame += 1
    Timer.tick()
    return new_actuators, can_sends
