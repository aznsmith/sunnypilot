import pickle
import numpy as np
import pytest

import openpilot.sunnypilot.models.helpers as helpers
import openpilot.sunnypilot.modeld_v2.modeld as modeld_module
from openpilot.sunnypilot.modeld_v2.modeld import _find_combined_pkl
from openpilot.sunnypilot.modeld_v2.tests.conftest import DummyArtifact, DummyModelType, DummyModel, DummyBundle

ModelState = modeld_module.ModelState


def _noop_jit(**kwargs):
  pass


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
  def test_asserts_when_no_combined_pkl(self, monkeypatch):
    bundle = DummyBundle(models=[], is_20hz=True)
    monkeypatch.setattr(helpers, 'get_active_bundle', lambda params=None: bundle, raising=False)
    monkeypatch.setattr(modeld_module, 'get_active_bundle', lambda params=None: bundle, raising=False)

    with pytest.raises(AssertionError, match="No combined pkl found"):
      ModelState(cam_w=1928, cam_h=1208)

  def test_use_combined_flag_true_when_pkl_exists(self, tmp_path, monkeypatch):
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

    state = ModelState(cam_w=1928, cam_h=1208)
    assert state._combined_model_type == 'split'
    assert state.vision_input_names == ['img', 'big_img']


class TestVisionInputNames:
  def test_returns_stored_names(self):
    state = ModelState.__new__(ModelState)
    state._vision_input_names = ['input_imgs', 'big_input_imgs']
    assert state.vision_input_names == ['input_imgs', 'big_input_imgs']


class TestDesireKey:
  def test_finds_desire_in_npy(self):
    state = ModelState.__new__(ModelState)
    state.npy = {'desire': np.zeros(8), 'traffic_convention': np.zeros(2)}
    assert state.desire_key == 'desire'

  def test_finds_desire_pulse_in_npy(self):
    state = ModelState.__new__(ModelState)
    state.npy = {'desire_pulse': np.zeros(8), 'traffic_convention': np.zeros(2)}
    assert state.desire_key == 'desire_pulse'
