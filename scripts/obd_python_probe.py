#  CivilPy
#  Copyright (C) 2019-2026 Dane Parks
#
#  SPDX-License-Identifier: MIT
#  See the LICENSE file in the project root for full license text.

"""Probe the Python embedded in OpenBridge Designer / MicroStation.

Run INSIDE OBD with a model containing OBM objects (a girder, pier, deck)
open as the active model:

    key-in:  python load C:\\path\\to\\civilpy\\scripts\\obd_python_probe.py

or load it from Utilities > Python Manager.  It also runs under a plain
``python`` (it then reports only the interpreter and that the MSPy modules
are missing).

Writes one JSON file to ``%USERPROFILE%\\obm_probe\\`` and prints its path:

* the interpreter: version, executable, prefix, sys.path, pip, civilpy;
* which MSPy modules import, and any exported names that look bridge-specific;
* for each graphic element in the active model (capped): id, handler
  description, and every EC instance attached with its class, schema and
  property values.

The element section answers the open question: do OBM girders / piers expose
their engineering data as EC properties Python can read, or only geometry?
Every API call is wrapped - an unverified call records its error in the JSON
instead of aborting the run.
"""

import datetime
import importlib
import importlib.util
import json
import os
import pkgutil
import sys
import traceback

MAX_ELEMENTS = 2000
MAX_INSTANCES_PER_ELEMENT = 25
MAX_PROPERTIES_PER_INSTANCE = 300

MSPY_MODULES = [
    "MSPyBentley",
    "MSPyBentleyGeom",
    "MSPyECObjects",
    "MSPyDgnPlatform",
    "MSPyDgnView",
    "MSPyMstnPlatform",
]
BRIDGE_HINTS = ("bridge", "obm", "girder", "pier", "abutment", "bearing", "deck")
# Output must never land on ProjectWise or a network share.
FORBIDDEN_PREFIXES = ("c:\\projectwise", "\\\\")


def _err(exc):
    return f"{type(exc).__name__}: {exc}"


def _call(obj, name, *args):
    """``obj.name(*args)`` or an ``{"error": ...}`` dict."""
    try:
        return getattr(obj, name)(*args)
    except Exception as exc:
        return {"error": _err(exc)}


def _public_names(obj):
    return [n for n in dir(obj) if not n.startswith("_")]


def probe_interpreter():
    info = {
        "version": sys.version,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": getattr(sys, "base_prefix", None),
        "path": list(sys.path),
        "pip_available": importlib.util.find_spec("pip") is not None,
    }
    try:
        import civilpy

        info["civilpy"] = {
            "version": getattr(civilpy, "__version__", None),
            "file": civilpy.__file__,
        }
    except Exception as exc:
        info["civilpy"] = {"error": _err(exc)}
    bentleyish = sorted(
        m.name
        for m in pkgutil.iter_modules()
        if m.name.lower().startswith(("mspy", "bentley"))
        or any(h in m.name.lower() for h in BRIDGE_HINTS)
    )
    info["bentley_like_top_level_modules"] = bentleyish
    return info


def probe_modules():
    loaded, report = {}, {}
    for name in MSPY_MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception as exc:
            report[name] = {"imported": False, "error": _err(exc)}
            continue
        loaded[name] = mod
        names = _public_names(mod)
        report[name] = {
            "imported": True,
            "file": getattr(mod, "__file__", None),
            "export_count": len(names),
            "bridge_like_exports": [
                n for n in names if any(h in n.lower() for h in BRIDGE_HINTS)
            ],
        }
    return loaded, report


def _find(loaded, attr):
    """First MSPy module exporting ``attr`` (they re-export liberally)."""
    for mod in loaded.values():
        if hasattr(mod, attr):
            return getattr(mod, attr)
    raise AttributeError(f"{attr} not exported by any loaded MSPy module")


def _handler_description(loaded, eh):
    try:
        WString = _find(loaded, "WString")
        handler = eh.GetHandler()
        desc = WString()
        handler.GetDescription(eh, desc, 100)
        return str(desc)
    except Exception as exc:
        return {"error": _err(exc)}


def _ec_value_text(loaded, inst, prop_name):
    try:
        ECValue = _find(loaded, "ECValue")
        value = ECValue()
        inst.GetValue(value, prop_name)
        if value.IsNull():
            return None
        return str(value.ToString()) if hasattr(value, "ToString") else str(value)
    except Exception as exc:
        return {"error": _err(exc)}


def _ec_instances(loaded, eh, api_notes):
    """EC instances on one element, as plain dicts."""
    try:
        FindInstancesScope = _find(loaded, "FindInstancesScope")
        FindInstancesScopeOption = _find(loaded, "FindInstancesScopeOption")
        DgnECHostType = _find(loaded, "DgnECHostType")
        ECQuery = _find(loaded, "ECQuery")
        DgnECManager = _find(loaded, "DgnECManager")
        search_all = None
        for flag in ("ECQUERY_PROCESS_SearchAllClasses", "ECQueryProcessFlags"):
            try:
                search_all = _find(loaded, flag)
                if flag == "ECQueryProcessFlags":
                    search_all = search_all.eECQUERY_PROCESS_SearchAllClasses
                break
            except Exception:
                continue

        scope = FindInstancesScope.CreateScope(
            eh, FindInstancesScopeOption(DgnECHostType.Element)
        )
        query = ECQuery.CreateQuery(search_all)
        query.SetSelectProperties(True)
        result = DgnECManager.GetManager().FindInstances(scope, query)
        instances = result[0] if isinstance(result, tuple) else result
    except Exception as exc:
        api_notes.setdefault("ec_query_errors", set()).add(_err(exc))
        return {"error": _err(exc)}

    out = []
    for i, inst in enumerate(instances):
        if i >= MAX_INSTANCES_PER_ELEMENT:
            out.append({"truncated": True})
            break
        entry = {}
        try:
            ec_class = inst.GetClass()
            entry["class"] = str(ec_class.GetName())
            entry["schema"] = str(_call(ec_class.GetSchema(), "GetName"))
            props = {}
            for j, prop in enumerate(ec_class.GetProperties(True)):
                if j >= MAX_PROPERTIES_PER_INSTANCE:
                    props["__truncated__"] = True
                    break
                pname = str(prop.GetName())
                props[pname] = _ec_value_text(loaded, inst, pname)
            entry["properties"] = props
        except Exception as exc:
            entry["error"] = _err(exc)
            if "instance_dir" not in api_notes:
                api_notes["instance_dir"] = _public_names(inst)
        out.append(entry)
    return out


def probe_active_model(loaded):
    if "MSPyDgnPlatform" not in loaded or "MSPyMstnPlatform" not in loaded:
        return {"skipped": "MSPyDgnPlatform/MSPyMstnPlatform not importable"}
    api_notes = {}
    model_info = {}
    try:
        ISessionMgr = _find(loaded, "ISessionMgr")
        model_ref = ISessionMgr.ActiveDgnModelRef
        model = model_ref.GetDgnModel()
        model_info["model_name"] = str(_call(model, "GetModelName"))
        dgn_file = _call(model, "GetDgnFileP")
        if not isinstance(dgn_file, dict):
            model_info["file_name"] = str(_call(dgn_file, "GetFileName"))
        elements = model.GetGraphicElements()
    except Exception as exc:
        return {"error": _err(exc), "traceback": traceback.format_exc()}

    EditElementHandle = _find(loaded, "EditElementHandle")
    rows, by_description, total = [], {}, 0
    for elm_ref in elements:
        total += 1
        if len(rows) >= MAX_ELEMENTS:
            continue
        try:
            eh = EditElementHandle(elm_ref, model)
        except Exception as exc:
            rows.append({"error": _err(exc)})
            continue
        desc = _handler_description(loaded, eh)
        key = desc if isinstance(desc, str) else "?"
        by_description[key] = by_description.get(key, 0) + 1
        rows.append(
            {
                "element_id": _call(elm_ref, "GetElementId"),
                "element_type": _call(eh, "GetElementType"),
                "description": desc,
                "ec_instances": _ec_instances(loaded, eh, api_notes),
            }
        )
        if len(rows) == 1:
            api_notes["element_handle_dir"] = _public_names(eh)

    if "ec_query_errors" in api_notes:
        api_notes["ec_query_errors"] = sorted(api_notes["ec_query_errors"])
    ec_classes = {}
    for row in rows:
        for inst in row.get("ec_instances") or []:
            if isinstance(inst, dict) and "class" in inst:
                k = f"{inst.get('schema')}:{inst['class']}"
                ec_classes[k] = ec_classes.get(k, 0) + 1
    model_info.update(
        {
            "graphic_element_count": total,
            "elements_dumped": len(rows),
            "count_by_description": dict(
                sorted(by_description.items(), key=lambda kv: -kv[1])
            ),
            "ec_class_counts": dict(sorted(ec_classes.items(), key=lambda kv: -kv[1])),
            "api_notes": api_notes,
            "elements": rows,
        }
    )
    return model_info


def output_path():
    root = os.path.join(os.path.expanduser("~"), "obm_probe")
    if root.lower().startswith(FORBIDDEN_PREFIXES):
        raise SystemExit(f"refusing to write under {root!r} (ProjectWise/network)")
    os.makedirs(root, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(root, f"obm_probe_{stamp}.json")


def main():
    report = {"generated": datetime.datetime.now().astimezone().isoformat()}
    report["interpreter"] = probe_interpreter()
    loaded, report["mspy_modules"] = probe_modules()
    report["active_model"] = probe_active_model(loaded)

    path = output_path()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)

    am = report["active_model"]
    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    print(f"MSPy modules imported: {sum(v['imported'] for v in report['mspy_modules'].values())}/{len(MSPY_MODULES)}")
    if "graphic_element_count" in am:
        print(f"Model {am.get('model_name')}: {am['graphic_element_count']} graphic elements")
        print(f"EC classes seen: {len(am['ec_class_counts'])}")
    else:
        print(f"Active model not probed: {am.get('skipped') or am.get('error')}")
    print(f"Wrote {path}")


main()
