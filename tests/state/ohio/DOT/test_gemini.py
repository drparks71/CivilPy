#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Checks for :mod:`civilpy.state.ohio.DOT.gemini`.

``google.generativeai`` is not a test dependency, so a stub package is placed
in ``sys.modules`` before the module is imported; every test then patches the
stub's ``configure`` / ``GenerativeModel`` / ``GenerationConfig`` and asserts
the exact calls. ``load_dotenv`` is patched so a developer's ``.env`` can never
leak a real key into a test, and no request is ever made.
"""

import json
import sys
import types
from unittest.mock import MagicMock

import pytest
from PIL import Image

try:  # pragma: no cover - the real SDK may be present on a developer box
    import google.generativeai  # noqa: F401
except ImportError:
    _google = types.ModuleType("google")
    _genai = types.ModuleType("google.generativeai")
    _genai.configure = MagicMock(name="configure")
    _genai.GenerativeModel = MagicMock(name="GenerativeModel")
    _genai.GenerationConfig = MagicMock(name="GenerationConfig")
    _google.generativeai = _genai
    sys.modules.setdefault("google", _google)
    sys.modules.setdefault("google.generativeai", _genai)

from civilpy.state.ohio.DOT import gemini  # noqa: E402


@pytest.fixture
def genai(monkeypatch):
    stub = MagicMock(name="genai")
    monkeypatch.setattr(gemini, "genai", stub)
    monkeypatch.setattr(gemini, "load_dotenv", MagicMock(name="load_dotenv"))
    return stub


@pytest.fixture
def table_png(tmp_path):
    p = tmp_path / "std_drawings.png"
    Image.new("RGB", (4, 4), (255, 255, 255)).save(p)
    return p


# --------------------------------------------------------------------------- #
# Schema types
# --------------------------------------------------------------------------- #

def test_response_schema_shapes():
    assert gemini.DrawingEntry.__annotations__ == {"drawing_code": str, "date": str}
    assert gemini.ExtractionResult.__annotations__ == {"drawings": list[gemini.DrawingEntry]}
    assert gemini.DrawingEntry(drawing_code="BP-2.1", date="07/19/2019") == \
        {"drawing_code": "BP-2.1", "date": "07/19/2019"}


# --------------------------------------------------------------------------- #
# configure_gemini
# --------------------------------------------------------------------------- #

def test_configure_requires_api_key(genai, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API Key not found"):
        gemini.configure_gemini()
    gemini.load_dotenv.assert_called_once_with()
    genai.configure.assert_not_called()


def test_configure_passes_key_from_env(genai, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-123")
    gemini.configure_gemini()
    genai.configure.assert_called_once_with(api_key="test-key-123")


def test_configure_treats_blank_key_as_missing(genai, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    with pytest.raises(ValueError):
        gemini.configure_gemini()


# --------------------------------------------------------------------------- #
# extract_std_drawings
# --------------------------------------------------------------------------- #

def test_extract_std_drawings_builds_request_and_maps_codes(genai, monkeypatch, table_png):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    model = genai.GenerativeModel.return_value
    model.generate_content.return_value.text = json.dumps({
        "drawings": [
            {"drawing_code": "BP-2.1", "date": "07/19/2019"},
            {"drawing_code": "F-1", "date": "01/17/2020"},
        ]
    })

    result = gemini.extract_std_drawings(table_png)

    assert result == {"StdConstructionDrawings": {"BP-2.1": "07/19/2019", "F-1": "01/17/2020"}}
    genai.configure.assert_called_once_with(api_key="k")
    genai.GenerativeModel.assert_called_once_with("gemini-1.5-flash")
    genai.GenerationConfig.assert_called_once_with(
        response_mime_type="application/json", response_schema=gemini.ExtractionResult)
    (parts,), kwargs = model.generate_content.call_args
    assert kwargs == {"generation_config": genai.GenerationConfig.return_value}
    prompt, img = parts
    assert "Supplemental Prints of Standard Construction Drawings" in prompt
    assert "Ignore empty rows." in prompt
    assert isinstance(img, Image.Image) and img.size == (4, 4)


def test_extract_std_drawings_custom_model_and_empty_table(genai, monkeypatch, table_png):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    genai.GenerativeModel.return_value.generate_content.return_value.text = '{"drawings": []}'
    assert gemini.extract_std_drawings(str(table_png), model_name="gemini-2.0-pro") == \
        {"StdConstructionDrawings": {}}
    genai.GenerativeModel.assert_called_once_with("gemini-2.0-pro")


def test_extract_std_drawings_later_duplicate_code_wins(genai, monkeypatch, table_png):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    genai.GenerativeModel.return_value.generate_content.return_value.text = json.dumps({
        "drawings": [{"drawing_code": "F-1", "date": "old"}, {"drawing_code": "F-1", "date": "new"}]})
    assert gemini.extract_std_drawings(table_png)["StdConstructionDrawings"] == {"F-1": "new"}


def test_extract_std_drawings_missing_image_fails_before_any_request(genai, monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    with pytest.raises(FileNotFoundError):
        gemini.extract_std_drawings(tmp_path / "missing.png")
    genai.GenerativeModel.assert_not_called()


def test_extract_std_drawings_without_key_never_opens_model(genai, monkeypatch, table_png):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        gemini.extract_std_drawings(table_png)
    genai.GenerativeModel.assert_not_called()


def test_malformed_model_reply_raises_json_error(genai, monkeypatch, table_png):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    genai.GenerativeModel.return_value.generate_content.return_value.text = "not json"
    with pytest.raises(json.JSONDecodeError):
        gemini.extract_std_drawings(table_png)
