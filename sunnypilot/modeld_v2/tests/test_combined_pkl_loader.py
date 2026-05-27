import pickle
import numpy as np
import pytest
from unittest.mock import MagicMock

import openpilot.sunnypilot.models.helpers as helpers
import openpilot.sunnypilot.models.runners.helpers as runner_helpers
import openpilot.sunnypilot.modeld_v2.modeld as modeld_module
from openpilot.sunnypilot.modeld_v2.modeld import _find_combined_pkl

ModelState = modeld_module.ModelState


def _noop_jit(**kwargs):
  pass


class DummyOverride:
  def __init__(self, key, value):
    self.key = key
    self.value = value


class DummyArtifact:
  def __init__(self, file_name):
    self.file_name = file_name


class DummyModelType:
  def __init__(self, raw):
    self.raw = raw


class DummyModel:
  def __init__(self, type_str, artifact_file):
    self.type = DummyModelType(type_str)
    self.artifact = DummyArtifact(artifact_file)


class DummyBundle:
  def __init__(self, models=None, is_20hz=True):
    self.overrides = [DummyOverride('lat', '.1'), DummyOverride('long', '.3')]
    self.generation = 10
    self.is20hz = is_20hz
    self.models = models or []


class TestFindCombinedPkl:
  def test_returns_none_when_no_bundle(self):
    assert _find_combined_pkl(None) is None

  def test_returns_none_when_no_models(self):
    bundle = DummyBundle(models=[])
    assert _find_combined_pkl(bundle) is None

  def test_returns_none_when_combined_not_on_disk(self):
    bundle = DummyBundle(models=[
      DummyModel('vision', 'driving_vision_fof_tinygrad.pkl'),
      DummyModel('policy', 'driving_policy_fof_tinygrad.pkl'),
    ])
    assert _find_combined_pkl(bundle) is None

  def test_finds_combined_for_split_model(self, tmp_path, monkeypatch):
    combined_file = tmp_path / 'driving_combined_fof_tinygrad.pkl'
    combined_file.write_bytes(b'fake')

    from openpilot.system.hardware import hw
    monkeypatch.setattr(hw.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))

    bundle = DummyBundle(models=[
      DummyModel('vision', 'driving_vision_fof_tinygrad.pkl'),
      DummyModel('policy', 'driving_policy_fof_tinygrad.pkl'),
    ])
    result = _find_combined_pkl(bundle)
    assert result is not None
    assert 'driving_combined_fof' in result

  def test_finds_combined_for_supercombo(self, tmp_path, monkeypatch):
    combined_file = tmp_path / 'driving_combined_lav2_tinygrad.pkl'
    combined_file.write_bytes(b'fake')

    from openpilot.system.hardware import hw
    monkeypatch.setattr(hw.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))

    bundle = DummyBundle(models=[
      DummyModel('supercombo', 'supercombo_lav2_tinygrad.pkl'),
    ])
    result = _find_combined_pkl(bundle)
    assert result is not None
    assert 'driving_combined_lav2' in result

  def test_naming_convention_split(self):
    vision_file = 'driving_vision_cd210_tinygrad.pkl'
    expected_combined = 'driving_combined_cd210_tinygrad.pkl'
    actual = vision_file.replace('driving_vision_', 'driving_combined_')
    assert actual == expected_combined

  def test_naming_convention_supercombo(self):
    sc_file = 'supercombo_wd40_tinygrad.pkl'
    expected_combined = 'driving_combined_wd40_tinygrad.pkl'
    actual = sc_file.replace('supercombo_', 'driving_combined_')
    assert actual == expected_combined


class TestModelStateCombinedInit:
  def test_fallback_when_no_combined_pkl(self, monkeypatch):
    shapes = {'desire_pulse': (1, 25, 8), 'features_buffer': (1, 25, 512)}

    class FallbackRunner:
      def __init__(self):
        self.input_shapes = shapes
        self.is_20hz = True
        self.is_20hz_3d = False
        self.vision_input_names = []
        self.constants = type('C', (), {
          'DESIRE_LEN': 8, 'FEATURE_LEN': 512,
          'FULL_HISTORY_BUFFER_LEN': 100, 'INPUT_HISTORY_BUFFER_LEN': 25,
          'TEMPORAL_SKIP': 4, 'PREV_DESIRED_CURV_LEN': 1,
        })()
        self.inputs = {}

      def prepare_inputs(self, x): return None

      def run_model(self): return {'hidden_state': np.zeros((1, 512)), 'desired_curvature': np.zeros((1, 1))}

    bundle = DummyBundle(models=[], is_20hz=True)
    runner = FallbackRunner()

    monkeypatch.setattr(helpers, 'get_active_bundle', lambda params=None: bundle, raising=False)
    monkeypatch.setattr(runner_helpers, 'get_model_runner', lambda: runner, raising=False)
    monkeypatch.setattr(modeld_module, 'get_model_runner', lambda: runner, raising=False)
    monkeypatch.setattr(modeld_module, 'get_active_bundle', lambda params=None: bundle, raising=False)

    state = ModelState()
    assert state.use_combined is False
    assert state.model_runner is runner
    assert state.warp is not None

  def test_use_combined_flag_true_when_pkl_exists(self, tmp_path, monkeypatch):
    import json
    from openpilot.system.hardware import hw

    vision_slices = {'hidden_state': slice(0, 512), 'plan': slice(512, 1024)}
    policy_slices = {'plan': slice(0, 495), 'meta': slice(495, 550)}
    vision_input_shapes = {'img': (1, 12, 128, 256), 'big_img': (1, 12, 128, 256)}
    policy_input_shapes = {'features_buffer': (1, 25, 512), 'desire_pulse': (1, 25, 8), 'traffic_convention': (1, 2)}

    pkl_data = {
      'metadata': {
        'vision': {'input_shapes': vision_input_shapes, 'output_slices': vision_slices},
        'policy': {'input_shapes': policy_input_shapes, 'output_slices': policy_slices},
      },
      (1928, 1208): {'run_policy': _noop_jit, 'warp_enqueue': _noop_jit},
    }

    pkl_path = tmp_path / 'driving_combined_test_tinygrad.pkl'
    with open(pkl_path, 'wb') as f:
      pickle.dump(pkl_data, f)

    bundle = DummyBundle(
      models=[DummyModel('vision', 'driving_vision_test_tinygrad.pkl'),
              DummyModel('policy', 'driving_policy_test_tinygrad.pkl')],
      is_20hz=True,
    )

    monkeypatch.setattr(helpers, 'get_active_bundle', lambda params=None: bundle, raising=False)
    monkeypatch.setattr(modeld_module, 'get_active_bundle', lambda params=None: bundle, raising=False)
    monkeypatch.setattr(hw.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))

    tg_devices_path = tmp_path / 'tg_input_devices.json'
    with open(tg_devices_path, 'w') as f:
      json.dump({modeld_module.PROCESS_NAME: 'CPU'}, f)

    from openpilot.selfdrive.modeld import helpers as modeld_helpers
    monkeypatch.setattr(modeld_helpers, 'TG_INPUT_DEVICES_PATH', tg_devices_path)

    state = ModelState(cam_w=1928, cam_h=1208)
    assert state.use_combined is True
    assert state.model_runner is None
    assert state.warp is None
    assert state._combined_model_type == 'split'
    assert state.vision_input_names == ['img', 'big_img']


class TestVisionInputNames:
  def test_combined_path_returns_img_pair(self, monkeypatch):
    state = ModelState.__new__(ModelState)
    state.use_combined = True
    state.model_runner = None
    assert state.vision_input_names == ['img', 'big_img']

  def test_separate_path_delegates_to_runner(self, monkeypatch):
    state = ModelState.__new__(ModelState)
    state.use_combined = False
    state.model_runner = MagicMock()
    state.model_runner.vision_input_names = ['input_imgs', 'big_input_imgs']
    assert state.vision_input_names == ['input_imgs', 'big_input_imgs']


class TestDesireKey:
  def test_combined_path_finds_desire_in_npy(self):
    state = ModelState.__new__(ModelState)
    state.use_combined = True
    state.npy = {'desire': np.zeros(8), 'traffic_convention': np.zeros(2)}
    assert state.desire_key == 'desire'

  def test_combined_path_finds_desire_pulse_in_npy(self):
    state = ModelState.__new__(ModelState)
    state.use_combined = True
    state.npy = {'desire_pulse': np.zeros(8), 'traffic_convention': np.zeros(2)}
    assert state.desire_key == 'desire_pulse'

  def test_separate_path_finds_desire_in_numpy_inputs(self):
    state = ModelState.__new__(ModelState)
    state.use_combined = False
    state.numpy_inputs = {'desire': np.zeros((1, 100, 8)), 'features_buffer': np.zeros((1, 99, 512))}
    assert state.desire_key == 'desire'


class TestRunDispatch:
  def test_run_dispatches_to_combined(self):
    state = ModelState.__new__(ModelState)
    state.use_combined = True
    state._run_combined = MagicMock(return_value={'plan': np.zeros(1)})
    state._run_separate = MagicMock()

    result = state.run({}, {}, {}, False)
    state._run_combined.assert_called_once()
    state._run_separate.assert_not_called()
    assert 'plan' in result

  def test_run_dispatches_to_separate(self):
    state = ModelState.__new__(ModelState)
    state.use_combined = False
    state._run_combined = MagicMock()
    state._run_separate = MagicMock(return_value={'plan': np.zeros(1)})

    result = state.run({}, {}, {}, False)
    state._run_separate.assert_called_once()
    state._run_combined.assert_not_called()
    assert 'plan' in result
