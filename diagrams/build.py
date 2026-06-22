#!/usr/bin/env python3
"""Convert compact diagram scenes (the format authored for the Excalidraw MCP
create_view tool) into valid .excalidraw files that open in excalidraw.com,
the desktop app, or the VS Code Excalidraw extension.

Reads every _src/*.json (a plain array of compact elements) and writes a
sibling <name>.excalidraw next to this script.

Transforms applied:
  - drop pseudo-elements (cameraUpdate / delete / restoreCheckpoint)
  - expand each shape/arrow `label` into a bound text element (+ boundElements)
  - null out start/end bindings (arrows keep explicit points, so they render
    in place without needing the bound shapes to cross-reference them)
  - fill the required Excalidraw element fields with sane defaults
"""
import json, glob, os, random

random.seed(1234)
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "_src")
FONT = 2  # 2 = Helvetica (clean, proportional) — professional look for label-heavy diagrams
ROUGHNESS = 0  # 0 = crisp/modern (per excalidraw-diagram skill), 1 = hand-drawn


def nonce():
    return random.randint(1, 2**31 - 1)


def est(text, fs):
    lines = str(text).split("\n")
    w = max((len(l) for l in lines), default=1) * fs * 0.55
    h = len(lines) * fs * 1.25
    return max(w, 10.0), max(h, float(fs))


def base(el):
    el.setdefault("angle", 0)
    el.setdefault("strokeColor", "#1e1e1e")
    el.setdefault("backgroundColor", "transparent")
    el.setdefault("fillStyle", "solid")
    el.setdefault("strokeWidth", 2)
    el.setdefault("strokeStyle", "solid")
    el.setdefault("roughness", ROUGHNESS)
    el.setdefault("opacity", 100)
    el["groupIds"] = []
    el["frameId"] = None
    el.setdefault("roundness", None)
    el["seed"] = nonce()
    el["version"] = 1
    el["versionNonce"] = nonce()
    el["isDeleted"] = False
    el.setdefault("boundElements", None)
    el["updated"] = 1
    el["link"] = None
    el["locked"] = False
    return el


def convert(simple):
    out = []
    for raw in simple:
        t = raw.get("type")
        if t in ("cameraUpdate", "delete", "restoreCheckpoint"):
            continue
        el = dict(raw)
        label = el.pop("label", None)
        if t == "arrow":
            el.setdefault("points", [[0, 0], [el.get("width", 0), el.get("height", 0)]])
            el["startArrowhead"] = el.get("startArrowhead", None)
            el["endArrowhead"] = el.get("endArrowhead", "arrow")
            el["lastCommittedPoint"] = None
            el["startBinding"] = None
            el["endBinding"] = None
            el["elbowed"] = False
        if t == "text":
            el.setdefault("fontSize", 16)
            el.setdefault("fontFamily", FONT)  # allow per-element override (e.g. monospace code)
            el.setdefault("textAlign", "left")
            el.setdefault("verticalAlign", "top")
            el["originalText"] = el.get("text", "")
            el["lineHeight"] = 1.25
            el["autoResize"] = True
            el.setdefault("containerId", None)
            if "width" not in el or "height" not in el:
                w, h = est(el.get("text", ""), el["fontSize"])
                el.setdefault("width", w)
                el.setdefault("height", h)
        base(el)
        out.append(el)
        if label:
            txt = label.get("text", "")
            fs = label.get("fontSize", 16)
            tw, th = est(txt, fs)
            cx = el["x"] + el.get("width", 0) / 2.0
            cy = el["y"] + el.get("height", 0) / 2.0
            tel = {
                "type": "text", "id": "t%011x" % nonce(),
                "x": cx - tw / 2.0, "y": cy - th / 2.0, "width": tw, "height": th,
                "text": txt, "originalText": txt,
                "fontSize": fs, "fontFamily": FONT,
                "textAlign": "center", "verticalAlign": "middle",
                "containerId": el["id"], "lineHeight": 1.25, "autoResize": True,
                "strokeColor": "#1e1e1e",
            }
            base(tel)
            el["boundElements"] = [{"type": "text", "id": tel["id"]}]
            out.append(tel)
    return out


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.json")))
    if not files:
        print("no source files in", SRC)
        return
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        try:
            simple = json.load(open(f))
        except Exception as e:
            print("PARSE FAIL", name, "::", e)
            continue
        els = convert(simple)
        scene = {
            "type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
            "elements": els,
            "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
            "files": {},
        }
        op = os.path.join(HERE, name + ".excalidraw")
        json.dump(scene, open(op, "w"), indent=2)
        print("OK  %-34s %3d elements" % (name, len(els)))


if __name__ == "__main__":
    main()
