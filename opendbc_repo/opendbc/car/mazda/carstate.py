from opendbc.can import CANDefine, CANParser
from opendbc.car import Bus, create_button_events, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.interfaces import CarStateBase
from opendbc.car.mazda.values import DBC, LKAS_LIMITS, MazdaFlags, TI_STATE

ButtonType = structs.CarState.ButtonEvent.Type


class CarState(CarStateBase):
  def __init__(self, CP, CP_SP):
    super().__init__(CP, CP_SP)

    can_define = CANDefine(DBC[CP.carFingerprint][Bus.pt])
    self.shifter_values = can_define.dv["GEAR"]["GEAR"]

    self.crz_btns_counter = 0
    self.acc_active_last = False
    self.lkas_allowed_speed = False

    self.distance_button = 0
    self.accel_button = 0
    self.decel_button = 0

    # Torque Interceptor device state (only populated when MazdaFlags.TORQUE_INTERCEPTOR
    # is set -- see update() below for the gate)
    self.ti_ramp_down = False
    self.ti_version = 1
    self.ti_state = TI_STATE.RUN
    self.ti_violation = 0
    self.ti_error = 0
    self.ti_lkas_allowed = False

  def update(self, can_parsers) -> tuple[structs.CarState, structs.CarStateSP]:
    cp = can_parsers[Bus.pt]
    cp_cam = can_parsers[Bus.cam]

    ret = structs.CarState()
    ret_sp = structs.CarStateSP()

    self.parse_wheel_speeds(ret,
      cp.vl["WHEEL_SPEEDS"]["FL"],
      cp.vl["WHEEL_SPEEDS"]["FR"],
      cp.vl["WHEEL_SPEEDS"]["RL"],
      cp.vl["WHEEL_SPEEDS"]["RR"],
    )

    # Match panda speed reading
    speed_kph = cp.vl["ENGINE_DATA"]["SPEED"]
    ret.standstill = speed_kph <= .1

    can_gear = int(cp.vl["GEAR"]["GEAR"])
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(can_gear, None))

    ret.genericToggle = bool(cp.vl["BLINK_INFO"]["HIGH_BEAMS"])
    ret.leftBlindspot = cp.vl["BSM"]["LEFT_BS_STATUS"] != 0
    ret.rightBlindspot = cp.vl["BSM"]["RIGHT_BS_STATUS"] != 0
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(40, cp.vl["BLINK_INFO"]["LEFT_BLINK"] == 1,
                                                                      cp.vl["BLINK_INFO"]["RIGHT_BLINK"] == 1)

    ret.steeringAngleDeg = cp.vl["STEER"]["STEER_ANGLE"]

    # GATE: Torque Interceptor feedback replaces the stock torque-sensor reading only
    # when the flag is set. Off (the default): identical to today, cp.vl["STEER_TORQUE"].
    if self.CP.flags & MazdaFlags.TORQUE_INTERCEPTOR:
      cp_body = can_parsers[Bus.body]
      ret.steeringTorque = cp_body.vl["TI_FEEDBACK"]["TI_TORQUE_SENSOR"]

      self.ti_version = cp_body.vl["TI_FEEDBACK"]["VERSION_NUMBER"]
      self.ti_state = cp_body.vl["TI_FEEDBACK"]["STATE"]      # DISCOVER=0, OFF=1, DRIVER_OVER=2, RUN=3
      self.ti_violation = cp_body.vl["TI_FEEDBACK"]["VIOL"]   # 0 = no violation
      self.ti_error = cp_body.vl["TI_FEEDBACK"]["ERROR"]      # 0 = no error
      if self.ti_version > 1:
        self.ti_ramp_down = (cp_body.vl["TI_FEEDBACK"]["RAMP_DOWN"] == 1)

      ret.steeringPressed = abs(ret.steeringTorque) > LKAS_LIMITS.TI_STEER_THRESHOLD
      self.ti_lkas_allowed = not self.ti_ramp_down and self.ti_state == TI_STATE.RUN
    else:
      ret.steeringTorque = cp.vl["STEER_TORQUE"]["STEER_TORQUE_SENSOR"]
      ret.steeringPressed = abs(ret.steeringTorque) > LKAS_LIMITS.STEER_THRESHOLD

    ret.steeringTorqueEps = cp.vl["STEER_TORQUE"]["STEER_TORQUE_MOTOR"]
    ret.steeringRateDeg = cp.vl["STEER_RATE"]["STEER_ANGLE_RATE"]

    ret.brakePressed = cp.vl["PEDALS"]["BRAKE_ON"] == 1

    ret.seatbeltUnlatched = cp.vl["SEATBELT"]["DRIVER_SEATBELT"] == 0
    ret.doorOpen = any([cp.vl["DOORS"]["FL"], cp.vl["DOORS"]["FR"],
                        cp.vl["DOORS"]["BL"], cp.vl["DOORS"]["BR"]])

    # TODO: this should be from 0 - 1.
    ret.gasPressed = cp.vl["ENGINE_DATA"]["PEDAL_GAS"] > 0

    # Either due to low speed or hands off
    lkas_blocked = cp.vl["STEER_RATE"]["LKAS_BLOCK"] == 1

    if self.CP.minSteerSpeed > 0:
      # LKAS is enabled at 52kph going up and disabled at 45kph going down
      # wait for LKAS_BLOCK signal to clear when going up since it lags behind the speed sometimes
      if speed_kph > LKAS_LIMITS.ENABLE_SPEED and not lkas_blocked:
        self.lkas_allowed_speed = True
      elif speed_kph < LKAS_LIMITS.DISABLE_SPEED:
        self.lkas_allowed_speed = False
    else:
      self.lkas_allowed_speed = True

    # TODO: the signal used for available seems to be the adaptive cruise signal, instead of the main on
    #       it should be used for carState.cruiseState.nonAdaptive instead
    ret.cruiseState.available = cp.vl["CRZ_CTRL"]["CRZ_AVAILABLE"] == 1
    ret.cruiseState.enabled = cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"] == 1
    ret.cruiseState.standstill = cp.vl["PEDALS"]["STANDSTILL"] == 1
    ret.cruiseState.speed = cp.vl["CRZ_EVENTS"]["CRZ_SPEED"] * CV.KPH_TO_MS

    # stock lkas should be on
    # TODO: is this needed?
    ret.invalidLkasSetting = cp_cam.vl["CAM_LANEINFO"]["LANE_LINES"] == 0

    # NOTE: the source fork wraps this whole block in `if not TORQUE_INTERCEPTOR:` to
    # suppress the low-speed alert once the interceptor is active. Not replicated as a
    # separate gate here -- _initialize_mazda() (opendbc/sunnypilot/car/interfaces.py)
    # already sets CP.minSteerSpeed = 0.0 when the flag is on, which makes
    # `self.CP.minSteerSpeed > 0` above false, so self.lkas_allowed_speed is unconditionally
    # True and this block already evaluates to low_speed_alert=False on its own. Verified
    # below, not just asserted.
    if ret.cruiseState.enabled:
      if not self.lkas_allowed_speed and self.acc_active_last:
        self.low_speed_alert = True
      else:
        self.low_speed_alert = False
    ret.lowSpeedAlert = self.low_speed_alert

    # Check if LKAS is disabled due to lack of driver torque when all other states indicate
    # it should be enabled (steer lockout). Don't warn until we actually get lkas active
    # and lose it again, i.e, after initial lkas activation
    # GATE: self.ti_lkas_allowed is only ever True when MazdaFlags.TORQUE_INTERCEPTOR is set
    # (see update()'s driver-torque block above) and the interceptor itself reports RUN state
    # -- suppresses the stock lockout fault once the interceptor has taken over steering.
    ret.steerFaultTemporary = self.lkas_allowed_speed and lkas_blocked and not self.ti_lkas_allowed

    self.acc_active_last = ret.cruiseState.enabled

    self.crz_btns_counter = cp.vl["CRZ_BTNS"]["CTR"]

    # camera signals
    self.cam_lkas = cp_cam.vl["CAM_LKAS"]
    self.cam_laneinfo = cp_cam.vl["CAM_LANEINFO"]
    # GATE: the stock camera's fault bit is meaningless once the interceptor has taken
    # over steering (the camera can't see the interceptor's own fault state) -- suppressed
    # rather than reporting a false fault. self.ti_state/self.ti_violation/self.ti_error
    # above are the interceptor's own equivalent, currently tracked but not yet surfaced as
    # a CarState fault -- flagging that as a gap for later review, not resolved here.
    ret.steerFaultPermanent = cp_cam.vl["CAM_LKAS"]["ERR_BIT_1"] == 1 if not self.CP.flags & MazdaFlags.TORQUE_INTERCEPTOR else False

    # cruise control button events: distance, inc, and dec
    prev_distance_button = self.distance_button
    prev_accel_button = self.accel_button
    prev_decel_button = self.decel_button
    self.distance_button = cp.vl["CRZ_BTNS"]["DISTANCE_LESS"]
    self.accel_button = cp.vl["CRZ_BTNS"]["RES"]
    self.decel_button = cp.vl["CRZ_BTNS"]["SET_M"]

    ret.buttonEvents = [
      *create_button_events(self.distance_button, prev_distance_button, {1: ButtonType.gapAdjustCruise}),
      *create_button_events(self.accel_button, prev_accel_button, {1: ButtonType.accelCruise}),
      *create_button_events(self.decel_button, prev_decel_button, {1: ButtonType.decelCruise}),
    ]

    return ret, ret_sp

  @staticmethod
  def get_can_parsers(CP, CP_SP):
    parsers = {
      Bus.pt: CANParser(DBC[CP.carFingerprint][Bus.pt], [], 0),
      Bus.cam: CANParser(DBC[CP.carFingerprint][Bus.pt], [], 2),
    }
    # GATE: aux-bus (bus 1) parser only created when the Torque Interceptor is enabled --
    # that's the bus TI_FEEDBACK is injected on; nothing listens there otherwise.
    if CP.flags & MazdaFlags.TORQUE_INTERCEPTOR:
      parsers[Bus.body] = CANParser(DBC[CP.carFingerprint][Bus.pt], [], 1)
    return parsers
