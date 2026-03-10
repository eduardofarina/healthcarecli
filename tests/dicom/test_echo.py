"""Tests for C-ECHO SCU (ping)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset

from healthcarecli.dicom.connections import AEProfile
from healthcarecli.dicom.echo import DicomEchoError, cecho


def _make_profile(**kwargs):
    defaults = dict(name="test", host="127.0.0.1", port=4242, ae_title="TEST")
    defaults.update(kwargs)
    return AEProfile(**defaults)


def _status(code: int):
    s = Dataset()
    s.Status = code
    return s


def _mock_assoc(status_code: int = 0x0000, established: bool = True):
    assoc = MagicMock()
    assoc.is_established = established
    assoc.send_c_echo.return_value = _status(status_code)
    return assoc


@patch("healthcarecli.dicom.echo.AE")
def test_cecho_success_returns_elapsed(mock_ae_cls):
    assoc = _mock_assoc(0x0000)
    mock_ae_cls.return_value.associate.return_value = assoc

    elapsed = cecho(_make_profile())

    assert isinstance(elapsed, float)
    assert elapsed >= 0


@patch("healthcarecli.dicom.echo.AE")
def test_cecho_raises_on_no_association(mock_ae_cls):
    assoc = _mock_assoc(established=False)
    mock_ae_cls.return_value.associate.return_value = assoc

    with pytest.raises(DicomEchoError, match="Could not associate"):
        cecho(_make_profile())


@patch("healthcarecli.dicom.echo.AE")
def test_cecho_raises_on_none_response(mock_ae_cls):
    assoc = MagicMock()
    assoc.is_established = True
    assoc.send_c_echo.return_value = None
    mock_ae_cls.return_value.associate.return_value = assoc

    with pytest.raises(DicomEchoError, match="timeout"):
        cecho(_make_profile())


@patch("healthcarecli.dicom.echo.AE")
def test_cecho_raises_on_failure_status(mock_ae_cls):
    assoc = _mock_assoc(0xA700)
    mock_ae_cls.return_value.associate.return_value = assoc

    with pytest.raises(DicomEchoError, match="C-ECHO failed"):
        cecho(_make_profile())


@patch("healthcarecli.dicom.echo.AE")
def test_cecho_releases_association(mock_ae_cls):
    assoc = _mock_assoc(0x0000)
    mock_ae_cls.return_value.associate.return_value = assoc

    cecho(_make_profile())
    assoc.release.assert_called_once()
