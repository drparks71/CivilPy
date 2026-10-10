#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Google Gemini helpers for plan-sheet data extraction.

Sends plan-sheet images to the Gemini API to extract structured data
(labels, tables) that supplements the local ML models in
:mod:`civilpy.state.ohio.DOT.title_sheet`. Requires a ``GOOGLE_API_KEY``
in the environment or a ``.env`` file.

.. todo::
   This started as a one-off extraction script; generalize the prompt and
   schema beyond the "Supplemental Prints of Standard Construction
   Drawings" table.
"""

import json
import os

import google.generativeai as genai
import PIL.Image
import typing_extensions as typing
try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional: without it the key must already be in the environment
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False


class DrawingEntry(typing.TypedDict):
    drawing_code: str
    date: str


class ExtractionResult(typing.TypedDict):
    drawings: list[DrawingEntry]


def configure_gemini():
    """Load ``GOOGLE_API_KEY`` from the environment/.env and configure genai."""
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "API Key not found. Make sure you have a .env file with "
            "GOOGLE_API_KEY defined."
        )
    genai.configure(api_key=api_key)


def extract_std_drawings(image_path, model_name="gemini-1.5-flash"):
    """Extract standard-construction-drawing codes and dates from a title-sheet image.

    :param image_path: Path to an image of the "Supplemental Prints of
        Standard Construction Drawings" table.
    :param model_name: Gemini model to use.
    :return: ``{"StdConstructionDrawings": {code: date, ...}}``
    """
    configure_gemini()
    img = PIL.Image.open(image_path)
    model = genai.GenerativeModel(model_name)

    prompt = """
    Analyze this image of a "Supplemental Prints of Standard Construction Drawings" table.
    Extract all drawing codes (like F-1, BP-2, etc.) and their corresponding dates.
    Ignore empty rows.
    """

    response = model.generate_content(
        [prompt, img],
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=ExtractionResult,
        ),
    )
    raw_data = json.loads(response.text)
    return {
        "StdConstructionDrawings": {
            item["drawing_code"]: item["date"] for item in raw_data["drawings"]
        }
    }


if __name__ == "__main__":  # pragma: no cover
    import sys

    print(json.dumps(extract_std_drawings(sys.argv[1]), indent=4))
