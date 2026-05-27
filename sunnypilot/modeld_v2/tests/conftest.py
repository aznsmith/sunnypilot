import pytest

import openpilot.sunnypilot.models.helpers as helpers
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


@pytest.fixture
def patch_modeld(monkeypatch):
  def _patch(bundle):
    monkeypatch.setattr(helpers, 'get_active_bundle', lambda params=None: bundle, raising=False)
    monkeypatch.setattr(modeld_module, 'get_active_bundle', lambda params=None: bundle, raising=False)
  return _patch
