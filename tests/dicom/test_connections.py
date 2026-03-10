"""Tests for AEProfile persistence (config manager + connections)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcarecli.dicom.connections import AEProfile, ProfileNotFoundError


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect config writes to a temp directory for every test."""
    import healthcarecli.config.manager as mgr
    monkeypatch.setattr(mgr, "config_dir", lambda: tmp_path)
    # profiles_path() calls config_dir() internally, so this is sufficient


def test_save_and_load():
    p = AEProfile(name="orthanc", host="127.0.0.1", port=4242, ae_title="ORTHANC")
    p.save()

    loaded = AEProfile.load("orthanc")
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 4242
    assert loaded.ae_title == "ORTHANC"
    assert loaded.calling_ae == "HEALTHCARECLI"
    assert loaded.tls is False


def test_load_missing_raises():
    with pytest.raises(ProfileNotFoundError):
        AEProfile.load("nonexistent")


def test_list_profiles():
    AEProfile(name="a", host="h1", port=104, ae_title="A").save()
    AEProfile(name="b", host="h2", port=105, ae_title="B").save()

    profiles = AEProfile.list_all()
    names = {p.name for p in profiles}
    assert names == {"a", "b"}


def test_delete_profile():
    AEProfile(name="temp", host="h", port=100, ae_title="T").save()
    AEProfile.load("temp").delete()

    with pytest.raises(ProfileNotFoundError):
        AEProfile.load("temp")


def test_delete_missing_raises():
    p = AEProfile(name="ghost", host="h", port=100, ae_title="G")
    with pytest.raises(ProfileNotFoundError):
        p.delete()


def test_profiles_file_json_structure(tmp_path):
    import healthcarecli.config.manager as mgr
    AEProfile(name="pacs", host="10.0.0.1", port=11112, ae_title="PACS").save()

    raw = json.loads(mgr.profiles_path().read_text())
    assert "dicom" in raw
    assert "pacs" in raw["dicom"]
    assert raw["dicom"]["pacs"]["host"] == "10.0.0.1"
