import numpy as np
import pytest
from openpilot.sunnypilot.modeld_v2.constants import ModelConstants

import openpilot.sunnypilot.models.helpers as helpers
import openpilot.sunnypilot.models.runners.helpers as runner_helpers
import openpilot.sunnypilot.modeld_v2.modeld as modeld_module


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
  def __init__(self, is_20hz=False, models=None, generation=10):
    self.overrides = [DummyOverride('lat', '.1'), DummyOverride('long', '.3')]
    self.generation = generation
    self.is20hz = is_20hz
    self.models = models or []


class DummyModelRunner:
  def __init__(self, input_shapes, is_20hz=False, constants_class=None):
    self.input_shapes = input_shapes
    self.is_20hz = is_20hz
    self.is_20hz_3d = False
    self.vision_input_names = []
    self.constants = (constants_class or ModelConstants)()

  def prepare_inputs(self, numpy_inputs):
    return None

  def run_model(self):
    return {
      'hidden_state': np.zeros((1, self.constants.FEATURE_LEN), dtype=np.float32),
      'desired_curvature': np.zeros((1, 1), dtype=np.float32),
    }


@pytest.fixture
def patch_modeld(monkeypatch):
  def _patch(bundle, runner):
    monkeypatch.setattr(helpers, 'get_active_bundle', lambda params=None: bundle, raising=False)
    monkeypatch.setattr(runner_helpers, 'get_model_runner', lambda: runner, raising=False)
    monkeypatch.setattr(modeld_module, 'get_model_runner', lambda: runner, raising=False)
    monkeypatch.setattr(modeld_module, 'get_active_bundle', lambda params=None: bundle, raising=False)
  return _patch
