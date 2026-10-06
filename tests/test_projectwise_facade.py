#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""``civilpy.projectwise`` is a re-export façade: every public name must
be the very object from the layer module it fronts, so callers using the
short path and callers using the full path share one implementation."""

import importlib

import pytest

from civilpy import projectwise

QUERY_NAMES = (
    "ACTIVE_PROJECT_PATH", "ACTIVE_SHEET_GRAMMAR", "ACTIVE_STRUCTURES_PATH",
    "BRIDGE_NAME_GRAMMAR", "DATASOURCE_ACTIVE", "DATASOURCE_ARCHIVE",
    "PLAN_SET_GRAMMAR", "PLANVAULT_DISTRICT_FOLDERS", "PLANVAULT_FOLDER_ID",
    "PLANVAULT_GUID", "SHORT_DESC_GRAMMAR", "PROJECT_DB_SECRETS_KEY",
    "get_datasource", "find_plans_by_bridge_key", "find_plans_by_pid",
    "find_plans_by_sfn", "get_structures_sheets", "load_planvault_inventory",
    "load_project_db_definitions", "parse_slm", "pull_plan",
    "query_projects_by_sfn", "sfn_to_pids",
)
PROJECT_NAMES = ("DELIVERABLES", "ProjectWiseProject", "ProjectWiseSFN", "PWFolder")
REVIEW_NAMES = ("FILE_KIND_PATTERNS", "ROLE_PATTERNS", "TYPE_PATTERNS",
                "classify_review_file", "classify_review_path")
SHEET_NAMES = ("CODE_INDEX", "CODE_TABLES", "FILENAME_FORMATS",
               "SHEET_ACCESSORS", "classify_filename")


@pytest.mark.parametrize("module, names", [
    ("civilpy.state.ohio.DOT.projectwise", QUERY_NAMES),
    ("civilpy.state.ohio.DOT.pw_project", PROJECT_NAMES),
    ("civilpy.state.ohio.DOT.review_taxonomy", REVIEW_NAMES),
    ("civilpy.state.ohio.DOT.sheet_taxonomy", SHEET_NAMES),
])
def test_facade_re_exports_the_same_objects(module, names):
    source = importlib.import_module(module)
    for name in names:
        assert getattr(projectwise, name) is getattr(source, name), name


def test_facade_is_importable_from_the_package_root():
    import civilpy

    assert civilpy.projectwise is projectwise
    assert projectwise.__doc__ and "ProjectWise" in projectwise.__doc__


def test_get_datasource_rejects_unknown_server_names():
    with pytest.raises(ValueError):
        projectwise.get_datasource("neither")


def test_sheet_classifier_runs_through_the_facade():
    assert projectwise.classify_filename("not a design file.txt") is None
