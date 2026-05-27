import numpy as np
import pytest
from typing import Any

import openpilot.sunnypilot.modeld_v2.modeld as modeld_module
from openpilot.sunnypilot.modeld_v2.constants import ModelConstants
from openpilot.sunnypilot.models.split_model_constants import SplitModelConstants
from openpilot.sunnypilot.modeld_v2.tests.conftest import DummyBundle, DummyModelRunner

ModelState = modeld_module.ModelState


class Archetype:
  def __init__(self, name, shapes, is_20hz, model_types, expected_buffer_length,
               expected_constants_class, expected_temporal_modes):
    self.name = name
    self.shapes = shapes
    self.is_20hz = is_20hz
    self.model_types = model_types
    self.expected_buffer_length = expected_buffer_length
    self.expected_constants_class = expected_constants_class
    self.expected_temporal_modes = expected_temporal_modes


ARCHETYPES = {
  'supercombo_non20hz': Archetype(
    name='supercombo_non20hz',
    shapes={
      'desire': (1, 100, 8),
      'features_buffer': (1, 99, 512),
      'lateral_control_params': (1, 2),
      'prev_desired_curv': (1, 100, 1),
    },
    is_20hz=False,
    model_types={'supercombo'},
    expected_buffer_length=2,
    expected_constants_class=ModelConstants,
    expected_temporal_modes={
      'desire': 'non20hz',
      'features_buffer': 'non20hz',
      'prev_desired_curv': 'non20hz',
    },
  ),
  'supercombo_20hz': Archetype(
    name='supercombo_20hz',
    shapes={
      'desire': (1, 25, 8),
      'features_buffer': (1, 24, 512),
    },
    is_20hz=True,
    model_types={'supercombo'},
    expected_buffer_length=5,
    expected_constants_class=ModelConstants,
    expected_temporal_modes={
      'desire': '20hz',
      'features_buffer': '20hz',
    },
  ),
  'vision_policy_split': Archetype(
    name='vision_policy_split',
    shapes={
      'desire_pulse': (1, 25, 8),
      'features_buffer': (1, 25, 512),
    },
    is_20hz=True,
    model_types={'vision', 'policy'},
    expected_buffer_length=5,
    expected_constants_class=SplitModelConstants,
    expected_temporal_modes={
      'desire_pulse': 'split',
      'features_buffer': 'split',
    },
  ),
  'vision_on_off_policy_split': Archetype(
    name='vision_on_off_policy_split',
    shapes={
      'desire_pulse': (1, 25, 8),
      'features_buffer': (1, 25, 512),
    },
    is_20hz=True,
    model_types={'vision', 'onPolicy', 'offPolicy'},
    expected_buffer_length=5,
    expected_constants_class=SplitModelConstants,
    expected_temporal_modes={
      'desire_pulse': 'split',
      'features_buffer': 'split',
    },
  ),
}


def make_fixtures(archetype: Archetype):
  is_split = archetype.model_types & {'vision', 'policy', 'offPolicy', 'onPolicy'}
  constants_class = SplitModelConstants if is_split else ModelConstants
  bundle = DummyBundle(is_20hz=archetype.is_20hz)
  runner = DummyModelRunner(archetype.shapes, is_20hz=archetype.is_20hz,
                            constants_class=constants_class)
  return bundle, runner


def detect_temporal_mode(shape, features_buffer_shape):
  if shape[1] in (24, 25) and features_buffer_shape is not None and features_buffer_shape[1] == 24:
    return '20hz'
  elif shape[1] == 25:
    return 'split'
  elif shape[1] >= 99:
    return 'non20hz'
  return 'unknown'


def expected_temporal_idxs(mode, shape, constants):
  if mode == '20hz':
    features_buffer_shape_1 = 24
    buffer_history_len = (features_buffer_shape_1 + 1) * 4
    step = int(-buffer_history_len / shape[1])
    return np.arange(step, step * (shape[1] + 1), step)[::-1]
  elif mode == 'split':
    buffer_history_len = shape[1] * 4
    skip = buffer_history_len // shape[1]
    return np.arange(buffer_history_len)[-1 - (skip * (shape[1] - 1))::skip]
  elif mode == 'non20hz':
    return np.arange(shape[1])
  return None


class TestRunnerSelection:
  @pytest.mark.parametrize("model_types,expected_split", [
    ({'supercombo'}, False),
    ({'vision', 'policy'}, True),
    ({'vision', 'onPolicy', 'offPolicy'}, True),
    ({'vision', 'policy', 'offPolicy'}, True),
  ])
  def test_runner_type_selection_logic(self, model_types, expected_split):
    from openpilot.sunnypilot.models.runners.constants import ModelType
    split_types = {ModelType.vision, ModelType.policy, ModelType.offPolicy, ModelType.onPolicy}
    model_type_raws = set()
    type_map = {
      'supercombo': ModelType.supercombo,
      'vision': ModelType.vision,
      'policy': ModelType.policy,
      'offPolicy': ModelType.offPolicy,
      'onPolicy': ModelType.onPolicy,
    }
    for mt in model_types:
      model_type_raws.add(type_map[mt])

    should_split = bool(model_type_raws & split_types)
    assert should_split == expected_split, \
      f"model_types={model_types}: expected split={expected_split}, got {should_split}"


class TestWarpBufferLength:
  @pytest.mark.parametrize("archetype_name", list(ARCHETYPES.keys()))
  def test_warp_buffer_length(self, archetype_name, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)

    patch_modeld(bundle, runner)

    state = ModelState()
    assert state.warp.buffer_length == arch.expected_buffer_length, \
      f"{arch.name}: warp buffer_length={state.warp.buffer_length}, expected {arch.expected_buffer_length}"

  def test_wrong_is_20hz_gives_wrong_buffer_length(self, patch_modeld):
    arch = ARCHETYPES['supercombo_non20hz']
    bundle = DummyBundle(is_20hz=True)
    runner = DummyModelRunner(arch.shapes, is_20hz=True)

    patch_modeld(bundle, runner)

    state = ModelState()
    assert state.warp.buffer_length != arch.expected_buffer_length, \
      "Wrong is_20hz should produce wrong buffer_length"


class TestConstantsSelection:
  @pytest.mark.parametrize("archetype_name", list(ARCHETYPES.keys()))
  def test_constants_class(self, archetype_name, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)

    patch_modeld(bundle, runner)

    state = ModelState()
    assert type(state.constants) == type(runner.constants), \
      f"{arch.name}: constants type mismatch"

  @pytest.mark.parametrize("archetype_name,wrong_constants", [
    ('supercombo_non20hz', SplitModelConstants),
    ('vision_policy_split', ModelConstants),
  ])
  def test_wrong_constants_detected(self, archetype_name, wrong_constants, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)
    runner.constants = wrong_constants()

    patch_modeld(bundle, runner)

    state = ModelState()
    assert type(state.constants) != type(arch.expected_constants_class()), \
      f"{arch.name}: wrong constants should be detected"


class TestTemporalModeDetection:
  @pytest.mark.parametrize("archetype_name", list(ARCHETYPES.keys()))
  def test_temporal_modes_correct(self, archetype_name, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)

    patch_modeld(bundle, runner)

    state = ModelState()

    for key, expected_mode in arch.expected_temporal_modes.items():
      shape = arch.shapes[key]
      if len(shape) < 3 or shape[1] <= 1:
        continue

      features_buffer_shape = arch.shapes.get('features_buffer')
      detected_mode = detect_temporal_mode(shape, features_buffer_shape)
      assert detected_mode == expected_mode, \
        f"{arch.name}.{key}: temporal mode={detected_mode}, expected {expected_mode}"

  @pytest.mark.parametrize("archetype_name", list(ARCHETYPES.keys()))
  def test_temporal_idxs_map_values(self, archetype_name, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)

    patch_modeld(bundle, runner)

    state = ModelState()

    for key, expected_mode in arch.expected_temporal_modes.items():
      shape = arch.shapes[key]
      if len(shape) < 3 or shape[1] <= 1:
        continue

      actual_idxs = state.temporal_idxs_map.get(key)
      expected_idxs = expected_temporal_idxs(expected_mode, shape, runner.constants)

      assert actual_idxs is not None, f"{arch.name}.{key}: temporal_idxs_map missing"
      assert expected_idxs is not None, f"{arch.name}.{key}: could not compute expected indices"
      np.testing.assert_array_equal(actual_idxs, expected_idxs,
                                    err_msg=f"{arch.name}.{key}: temporal indices mismatch")

  @pytest.mark.parametrize("archetype_name", list(ARCHETYPES.keys()))
  def test_temporal_buffer_shapes(self, archetype_name, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)

    patch_modeld(bundle, runner)

    state = ModelState()

    for key, expected_mode in arch.expected_temporal_modes.items():
      shape = arch.shapes[key]
      if len(shape) < 3 or shape[1] <= 1:
        continue

      buf = state.temporal_buffers.get(key)
      assert buf is not None, f"{arch.name}.{key}: temporal buffer missing"

      if expected_mode == 'non20hz':
        expected_shape = (1, shape[1], shape[2])
      else:
        buffer_history_len = shape[1] * 4
        if expected_mode == '20hz':
          features_buffer_shape = arch.shapes.get('features_buffer')
          buffer_history_len = (features_buffer_shape[1] + 1) * 4
        expected_shape = (1, buffer_history_len, shape[2])

      assert buf.shape == expected_shape, \
        f"{arch.name}.{key}: buffer shape {buf.shape} != expected {expected_shape}"

  def test_temporal_idxs_within_buffer_bounds(self, patch_modeld):
    for archetype_name, arch in ARCHETYPES.items():
      bundle, runner = make_fixtures(arch)

      patch_modeld(bundle, runner)

      state = ModelState()

      for key in arch.expected_temporal_modes:
        if key not in state.temporal_idxs_map or key not in state.temporal_buffers:
          continue
        idxs = state.temporal_idxs_map[key]
        buf = state.temporal_buffers[key]
        buf_len = buf.shape[1]
        assert np.all(idxs >= -buf_len) and np.all(idxs < buf_len), \
          f"{arch.name}.{key}: indices {idxs} out of bounds for buffer len {buf_len}"


class TestCrossArchetypeMismatch:
  def test_split_shapes_with_non20hz_flag_wrong_buffer_length(self, patch_modeld):
    arch = ARCHETYPES['vision_policy_split']
    bundle = DummyBundle(is_20hz=False)
    runner = DummyModelRunner(arch.shapes, is_20hz=False)

    patch_modeld(bundle, runner)

    state = ModelState()
    assert state.warp.buffer_length == 2, \
      "Split shapes with is_20hz=False should get buffer_length=2 (wrong for split models)"
    assert state.warp.buffer_length != arch.expected_buffer_length, \
      "Mismatch confirms wrong is_20hz propagates to wrong buffer_length"

  def test_non20hz_shapes_with_20hz_flag_wrong_buffer_length(self, patch_modeld):
    arch = ARCHETYPES['supercombo_non20hz']
    bundle = DummyBundle(is_20hz=True)
    runner = DummyModelRunner(arch.shapes, is_20hz=True)

    patch_modeld(bundle, runner)

    state = ModelState()
    assert state.warp.buffer_length == 5, \
      "Non-20Hz shapes with is_20hz=True should get buffer_length=5 (wrong for non-20Hz models)"
    assert state.warp.buffer_length != arch.expected_buffer_length, \
      "Mismatch confirms wrong is_20hz propagates to wrong buffer_length"

  def test_20hz_temporal_idxs_differ_from_split(self):
    shapes_20hz = {'desire': (1, 25, 8), 'features_buffer': (1, 24, 512)}
    shapes_split = {'desire_pulse': (1, 25, 8), 'features_buffer': (1, 25, 512)}

    fb_20hz = shapes_20hz['features_buffer']
    fb_split = shapes_split['features_buffer']

    mode_20hz = detect_temporal_mode(shapes_20hz['desire'], fb_20hz)
    mode_split = detect_temporal_mode(shapes_split['desire_pulse'], fb_split)

    assert mode_20hz == '20hz'
    assert mode_split == 'split'
    assert mode_20hz != mode_split

    idxs_20hz = expected_temporal_idxs('20hz', shapes_20hz['desire'], None)
    idxs_split = expected_temporal_idxs('split', shapes_split['desire_pulse'], None)
    assert not np.array_equal(idxs_20hz, idxs_split), \
      "20Hz and split should produce different temporal indices for desire"


class TestNumpyInputAllocation:
  @pytest.mark.parametrize("archetype_name", list(ARCHETYPES.keys()))
  def test_all_policy_inputs_allocated(self, archetype_name, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)

    patch_modeld(bundle, runner)

    state = ModelState()

    for key, shape in arch.shapes.items():
      if key in runner.vision_input_names:
        continue
      assert key in state.numpy_inputs, \
        f"{arch.name}: policy input '{key}' not in numpy_inputs"
      assert state.numpy_inputs[key].shape == shape, \
        f"{arch.name}.{key}: shape {state.numpy_inputs[key].shape} != expected {shape}"

  @pytest.mark.parametrize("archetype_name", list(ARCHETYPES.keys()))
  def test_desire_key_detection(self, archetype_name, patch_modeld):
    arch = ARCHETYPES[archetype_name]
    bundle, runner = make_fixtures(arch)

    patch_modeld(bundle, runner)

    state = ModelState()
    desire_key = state.desire_key
    assert desire_key.startswith('desire'), \
      f"{arch.name}: desire_key={desire_key} doesn't start with 'desire'"
    assert desire_key in arch.shapes, \
      f"{arch.name}: desire_key={desire_key} not in shapes"
