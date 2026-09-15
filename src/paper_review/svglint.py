"""Geometry lint for the hand-written SVG diagrams in report.html.

The checks follow archify's authoring contract (tt-a1i/archify, MIT): text
stays inside its box, labels don't overlap, no arrow ends in empty space, no
connector runs through an unrelated box. There is no browser here, so text
width is estimated per character — coefficients fitted against Chrome's
getComputedTextLength on 332 labels from real reports (sans ±12%, mono ±1%).
Every threshold leans toward missing a borderline case rather than flagging a
correct diagram.
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.w3.org/2000/svg}"
TOL = 4  # px a text may poke past its box before it counts
REACH = 14  # px an arrow tip may stop short of what it points at
SLACK = 0.9  # sans widths are ±12%; shrink so an estimate doesn't overstate
MIN_NODE = 20  # thinner rects are bars/ticks on a line, not nodes

_NARROW = set("iljtfr.,:;'!|()[] ·")


def _em(ch: str, mono: bool) -> float:
    if ord(ch) > 0x2E80:  # CJK / Hangul
        return 0.86 if mono else 0.9
    if mono:
        return 0.6
    if ch in _NARROW:
        return 0.29
    if ch.isupper() or ch.isdigit() or ch in "mw@%":
        return 0.64
    return 0.56 if ch.islower() else 0.43


def _num(v, default=0.0) -> float:
    m = re.match(r"\s*(-?[\d.]+)", str(v)) if v is not None else None
    return float(m.group(1)) if m else default


def _class_rules(svg) -> dict:
    """`.name { … }` rules from <style> blocks inside the SVG."""
    rules: dict = {}
    for st in svg.iter(f"{NS}style"):
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", st.text or ""):
            decl = dict(
                (k.strip(), v.strip())
                for k, _, v in (d.partition(":") for d in body.split(";"))
                if v.strip()
            )
            for name in re.findall(r"\.([\w-]+)\s*(?:,|$)", sel.strip()):
                rules.setdefault(name, {}).update(decl)
    return rules


def _style(el, key, rules):
    m = re.search(rf"(?:^|;)\s*{key}\s*:\s*([^;]+)", el.get("style", ""))
    if m:
        return m.group(1).strip()
    for c in reversed((el.get("class") or "").split()):
        if key in rules.get(c, {}):
            return rules[c][key]
    return el.get(key)


def _translate(el):
    t = el.get("transform")
    if not t:
        return 0.0, 0.0
    m = re.fullmatch(r"\s*translate\(\s*(-?[\d.]+)[\s,]*(-?[\d.]+)?\s*\)\s*", t)
    return (float(m.group(1)), float(m.group(2) or 0)) if m else None


def _path_points(d: str):
    """Vertices of a path plus whether each segment between them is straight."""
    toks = re.findall(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?", d)
    arity = dict(M=2, L=2, H=1, V=1, C=6, S=4, Q=4, T=2, A=7, Z=0)
    pts, straight = [], []
    x = y = sx = sy = 0.0
    cmd, i = None, 0
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                x, y = sx, sy
                if pts:
                    straight.append(True)
                    pts.append((x, y))
                continue
        if cmd is None or cmd.upper() not in arity:
            break
        n = arity[cmd.upper()]
        try:
            args = [float(a) for a in toks[i : i + n]]
        except ValueError:
            break
        if len(args) < n:
            break
        i += n
        rel, up = cmd.islower(), cmd.upper()
        if up == "H":
            x = x + args[0] if rel else args[0]
        elif up == "V":
            y = y + args[0] if rel else args[0]
        else:
            x, y = (x + args[-2], y + args[-1]) if rel else (args[-2], args[-1])
        if up == "M":
            if pts:
                return pts, straight  # a second subpath: keep the first only
            sx, sy = x, y
            cmd = "l" if rel else "L"  # implicit lineto after moveto
        else:
            straight.append(up in "LHV")
        pts.append((x, y))
    return pts, straight


def _points(attr):
    nums = [float(v) for v in re.findall(r"-?[\d.]+", attr or "")]
    return list(zip(nums[0::2], nums[1::2]))


def _collect(svg):
    rules = _class_rules(svg)
    boxes, nodes, texts, strokes = [], [], [], []

    def walk(el, dx, dy, inh):
        tr = _translate(el)
        if tr is None:
            return  # rotate/scale: geometry unknown, stay quiet
        dx, dy = dx + tr[0], dy + tr[1]
        inh = dict(
            fs=_num(_style(el, "font-size", rules), inh["fs"]),
            anchor=_style(el, "text-anchor", rules) or inh["anchor"],
            mono="mono" in (_style(el, "font-family", rules) or "") or inh["mono"],
            marker=inh["marker"]
            or bool(
                _style(el, "marker-end", rules) or _style(el, "marker-start", rules)
            ),
        )
        tag = el.tag.replace(NS, "")
        if tag in ("defs", "marker", "clipPath", "mask", "pattern", "symbol", "style"):
            return
        if tag == "rect":
            w, h = _num(el.get("width")), _num(el.get("height"))
            if w > 0 and h > 0:
                x, y = _num(el.get("x")) + dx, _num(el.get("y")) + dy
                boxes.append((x, y, x + w, y + h))
                if min(w, h) >= MIN_NODE:
                    nodes.append(boxes[-1])
        elif tag in ("circle", "ellipse"):
            cx, cy = _num(el.get("cx")) + dx, _num(el.get("cy")) + dy
            rx = _num(el.get("r") or el.get("rx"))
            ry = _num(el.get("r") or el.get("ry"))
            boxes.append((cx - rx, cy - ry, cx + rx, cy + ry))
        elif tag == "polygon":
            ps = _points(el.get("points"))
            if ps:
                xs, ys = [p[0] for p in ps], [p[1] for p in ps]
                boxes.append((min(xs) + dx, min(ys) + dy, max(xs) + dx, max(ys) + dy))
        elif tag == "text":
            _text(el, dx, dy, inh, rules, texts)
            return
        elif tag in ("line", "path", "polyline"):
            if tag == "line":
                pts = [(_num(el.get(f"x{k}")), _num(el.get(f"y{k}"))) for k in (1, 2)]
                straight = [True]
            elif tag == "polyline":
                pts = _points(el.get("points"))
                straight = [True] * max(len(pts) - 1, 0)
            else:
                pts, straight = _path_points(el.get("d", ""))
            fill = _style(el, "fill", rules) or ("black" if tag == "path" else "none")
            if len(pts) >= 2 and fill in ("none", "transparent"):
                strokes.append(
                    dict(
                        pts=[(px + dx, py + dy) for px, py in pts],
                        straight=straight,
                        end=bool(_style(el, "marker-end", rules))
                        or inh["marker"]
                        and not _style(el, "marker-start", rules),
                        start=bool(_style(el, "marker-start", rules)),
                    )
                )
        for child in el:
            walk(child, dx, dy, inh)

    walk(svg, 0.0, 0.0, dict(fs=16.0, anchor="start", mono=False, marker=False))
    return boxes, nodes, texts, strokes


def _text(el, dx, dy, inh, rules, out):
    def own(e, parent):
        return dict(
            fs=_num(_style(e, "font-size", rules), parent["fs"]),
            anchor=_style(e, "text-anchor", rules) or parent["anchor"],
            mono="mono" in (_style(e, "font-family", rules) or "") or parent["mono"],
        )

    st = own(el, inh)
    x, y = _num(el.get("x")) + dx, _num(el.get("y")) + dy
    spans = [c for c in el if c.tag.replace(NS, "") == "tspan"]
    lines = []
    if any(s.get("x") or s.get("y") or s.get("dy") for s in spans):
        if (el.text or "").strip():
            lines.append((x, y, st, el.text))
        for s in spans:
            ss = own(s, st)
            if s.get("x"):
                x = _num(s.get("x")) + dx
            if s.get("y"):
                y = _num(s.get("y")) + dy
            dyv = s.get("dy") or ""
            y += _num(dyv) * (ss["fs"] if "em" in dyv else 1)
            lines.append((x, y, ss, "".join(s.itertext())))
    else:
        lines.append((x, y, st, "".join(el.itertext())))
    for lx, ly, ls, s in lines:
        s = " ".join(s.split())
        if not s:
            continue
        wide = sum(_em(c, ls["mono"]) for c in s) * ls["fs"]
        w = wide if ls["mono"] else wide * SLACK
        a = ls["anchor"]
        top, bot = ly - 0.75 * ls["fs"], ly + 0.25 * ls["fs"]

        def left(width):
            return lx - width / 2 if a == "middle" else lx - width if a == "end" else lx

        out.append(
            dict(
                s=s,
                anchor=(lx, ly),
                box=(left(w), top, left(w) + w, bot),
                # unshrunk: a label bumping into a neighbouring box shows at a
                # couple of px, so that check can't afford the safety margin
                wide=(left(wide), top, left(wide) + wide, bot),
            )
        )


def _inside(p, b, pad=0.0):
    return b[0] - pad <= p[0] <= b[2] + pad and b[1] - pad <= p[1] <= b[3] + pad


def _area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def _seg_dist(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L))
    return ((p[0] - a[0] - t * vx) ** 2 + (p[1] - a[1] - t * vy) ** 2) ** 0.5


def _seg_hits_box(a, b, box):
    """Does the segment a→b cross the interior of box (Liang–Barsky clip)?"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, a[0] - box[0]),
        (dx, box[2] - a[0]),
        (-dy, a[1] - box[1]),
        (dy, box[3] - a[1]),
    ):
        if p == 0:
            if q < 0:
                return False
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)
    return t0 < t1


def lint_svg(svg_text: str) -> list[str]:
    try:
        svg = ET.fromstring(svg_text)
    except ET.ParseError:
        return []
    vb = [float(v) for v in re.findall(r"-?[\d.]+", svg.get("viewBox", ""))]
    boxes, nodes, texts, strokes = _collect(svg)
    frame = vb[2] * vb[3] if len(vb) == 4 else 0
    # a box holding other boxes (or most of the canvas) is a group backdrop
    nodes = [
        b
        for b in nodes
        if not (frame and _area(b) > 0.5 * frame)
        and not any(o != b and _inside(o[:2], b) and _inside(o[2:], b) for o in boxes)
    ]
    out = []

    for t in texts:
        tb = t["box"]
        home = [b for b in nodes if _inside(t["anchor"], b)]
        if home:
            b = min(home, key=_area)
            over = max(b[0] - tb[0], tb[2] - b[2])
            if over > TOL:
                out.append(f"TEXT_OVERFLOW: {t['s']!r} runs ~{over:.0f}px past its box")
        if len(vb) == 4:
            over = max(vb[0] - tb[0], tb[2] - vb[0] - vb[2])
            if over > TOL:
                out.append(
                    f"TEXT_CLIPPED: {t['s']!r} runs ~{over:.0f}px outside the viewBox"
                )
        wb = t["wide"]
        for n in nodes:
            if n in home:
                continue
            w = min(wb[2], n[2]) - max(wb[0], n[0])
            h = min(wb[3], n[3]) - max(wb[1], n[1])
            if w > 3 and h > 0.4 * (wb[3] - wb[1]):
                out.append(
                    f"TEXT_OVER_BOX: {t['s']!r} runs into the box at "
                    f"({n[0]:.0f},{n[1]:.0f})"
                )

    for i, a in enumerate(texts):
        for b in texts[i + 1 :]:
            ab, bb = a["box"], b["box"]
            w = min(ab[2], bb[2]) - max(ab[0], bb[0])
            h = min(ab[3], bb[3]) - max(ab[1], bb[1])
            if w > TOL and h > 1:
                out.append(f"TEXT_OVERLAP: {a['s']!r} overlaps {b['s']!r}")

    targets = boxes + [t["box"] for t in texts]
    for s in strokes:
        pts = s["pts"]
        attached = any(_inside(p, b, REACH) for p in (pts[0], pts[-1]) for b in boxes)
        # an axis starts in empty space too; only a connector leaving a shape
        # can be said to point at nothing
        tips = ([pts[-1]] if s["end"] else []) + ([pts[0]] if s["start"] else [])
        for tip in tips if attached else []:
            near = any(_inside(tip, b, REACH) for b in targets) or any(
                _seg_dist(tip, o["pts"][k], o["pts"][k + 1]) <= REACH
                for o in strokes
                if o is not s
                for k in range(len(o["pts"]) - 1)
            )
            if not near:
                out.append(
                    f"DANGLING_ARROW: arrow tip at ({tip[0]:.0f},{tip[1]:.0f}) points at nothing"
                )
        if not (s["end"] or s["start"]):
            continue  # guide lines and axes may pass behind shapes
        for k, straight in enumerate(s["straight"]):
            if not straight:
                continue
            a, b = pts[k], pts[k + 1]
            for n in nodes:
                if _inside(pts[0], n, REACH) or _inside(pts[-1], n, REACH):
                    continue
                inner = (n[0] + 6, n[1] + 6, n[2] - 6, n[3] - 6)
                if _seg_hits_box(a, b, inner):
                    out.append(
                        f"EDGE_THROUGH_BOX: line ({a[0]:.0f},{a[1]:.0f})→({b[0]:.0f},{b[1]:.0f}) "
                        f"crosses the box at ({n[0]:.0f},{n[1]:.0f})"
                    )
    return list(dict.fromkeys(out))


def lint_report(html: str) -> list[str]:
    """Diagnostics for every inline diagram, prefixed with its number."""
    out = []
    for i, svg in enumerate(re.findall(r"<svg\b.*?</svg>", html, re.S), 1):
        if "xmlns=" not in svg.split(">", 1)[0]:
            svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        out += [f"diagram {i} · {d}" for d in lint_svg(svg)]
    return out


if __name__ == "__main__":
    for f in sys.argv[1:]:
        found = lint_report(Path(f).read_text(encoding="utf-8"))
        print(f"{f}: {len(found)}")
        for d in found:
            print("  " + d)
