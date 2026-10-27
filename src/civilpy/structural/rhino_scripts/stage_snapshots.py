"""Rhino 8 script: one Snapshot per construction stage from the 4-D User Text.

Runs INSIDE Rhino (script editor or rhino-mcp ``run_python``) on a model baked
with the tags of :mod:`civilpy.structural.rhino_stages` (``stage_order``,
``stage``, ``removed_stage``).  For every stage k it hides the objects whose
``stage_order`` > k (not built yet) and those removed at or before k, shows the
rest, colours the current stage's objects by object colour (``HIGHLIGHT``) and
saves a Snapshot named ``"Stage k - <name>"`` with object visibility and
colours; then restores the document.

Set ``SNBI_STAGE_PLAY = "1"`` to also step through the snapshots and capture a
PNG per stage into ``<model folder>/stages/`` (3200 x 1800, the current view).
"""
import os

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc
import System

HIGHLIGHT = System.Drawing.Color.FromArgb(255, 230, 120, 20)
PLAY = os.environ.get("SNBI_STAGE_PLAY", "") == "1"


def tagged_objects():
    out = []
    for o in sc.doc.Objects:
        k = o.Attributes.GetUserString("stage_order")
        if k:
            out.append((o, int(k), o.Attributes.GetUserString("stage") or "",
                        o.Attributes.GetUserString("removed_stage") or ""))
    return out


def main():
    objs = tagged_objects()
    if not objs:
        print("no objects carry stage_order User Text")
        return
    stages = {}
    for o, k, name, _ in objs:
        stages.setdefault(k, name)
    order_of_name = {name: k for k, name in stages.items()}
    saved = {o.Id: (o.Attributes.ColorSource, o.Attributes.ObjectColor, o.IsHidden) for o, *_ in objs}
    out_dir = os.path.join(os.path.dirname(sc.doc.Path or os.getcwd()), "stages")
    for k in sorted(stages):
        rs.EnableRedraw(False)
        for o, ko, _, removed in objs:
            removed_k = order_of_name.get(removed, None)
            hide = ko > k or (removed_k is not None and removed_k <= k)
            if hide:
                sc.doc.Objects.Hide(o.Id, True)
            else:
                sc.doc.Objects.Show(o.Id, True)
            a = o.Attributes.Duplicate()
            if ko == k and not hide:
                a.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
                a.ObjectColor = HIGHLIGHT
            else:
                a.ColorSource = saved[o.Id][0]
                a.ObjectColor = saved[o.Id][1]
            sc.doc.Objects.ModifyAttributes(o.Id, a, True)
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()
        name = "Stage %d - %s" % (k, stages[k])
        rs.Command('_-Snapshots _Save "%s" _Enter' % name.replace('"', ""), False)
        print("snapshot", name)
        if PLAY:
            os.makedirs(out_dir, exist_ok=True)
            vc = Rhino.Display.ViewCapture()
            vc.Width, vc.Height = 3200, 1800
            vc.ScaleScreenItems = False
            vc.DrawAxes = vc.DrawGrid = vc.DrawGridAxes = False
            bmp = vc.CaptureToBitmap(sc.doc.Views.ActiveView)
            if bmp is not None:
                bmp.Save(os.path.join(out_dir, "stage_%02d.png" % k), System.Drawing.Imaging.ImageFormat.Png)
    # restore
    rs.EnableRedraw(False)
    for o, *_ in objs:
        src, col, hidden = saved[o.Id]
        a = o.Attributes.Duplicate()
        a.ColorSource, a.ObjectColor = src, col
        sc.doc.Objects.ModifyAttributes(o.Id, a, True)
        (sc.doc.Objects.Hide if hidden else sc.doc.Objects.Show)(o.Id, True)
    rs.EnableRedraw(True)
    sc.doc.Views.Redraw()


main()
