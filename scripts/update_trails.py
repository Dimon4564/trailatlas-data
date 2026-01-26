#!/usr/bin/env python3
import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def parse_gpx_points(gpx_path: Path):
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    m = re.match(r"\{(.+)\}", root.tag)
    ns = m.group(1) if m else ""
    def q(tag): return f"{{{ns}}}{tag}" if ns else tag

    pts = []
    for trk in root.findall(q("trk")):
        for seg in trk.findall(f".//{q('trkseg')}"):
            for pt in seg.findall(q("trkpt")):
                lat = safe_float(pt.attrib.get("lat"))
                lon = safe_float(pt.attrib.get("lon"))
                if lat is None or lon is None:
                    continue
                ele_el = pt.find(q("ele"))
                ele = safe_float(ele_el.text) if ele_el is not None else None
                pts.append((lat, lon, ele))

    if not pts:
        for rte in root.findall(q("rte")):
            for pt in rte.findall(q("rtept")):
                lat = safe_float(pt.attrib.get("lat"))
                lon = safe_float(pt.attrib.get("lon"))
                if lat is None or lon is None:
                    continue
                ele_el = pt.find(q("ele"))
                ele = safe_float(ele_el.text) if ele_el is not None else None
                pts.append((lat, lon, ele))

    return pts

def compute_stats(points):
    if len(points) < 2:
        return None

    length = 0.0
    ascent = 0.0
    descent = 0.0

    lats = [points[0][0]]
    lons = [points[0][1]]
    eles = [points[0][2]] if points[0][2] is not None else []

    prev = points[0]
    for cur in points[1:]:
        length += haversine_m(prev[0], prev[1], cur[0], cur[1])
        lats.append(cur[0])
        lons.append(cur[1])

        if prev[2] is not None and cur[2] is not None:
            d = cur[2] - prev[2]
            if d > 0: ascent += d
            else: descent += -d
            eles.append(cur[2])

        prev = cur

    bbox = {
        "min_lat": min(lats),
        "min_lon": min(lons),
        "max_lat": max(lats),
        "max_lon": max(lons),
    }

    min_ele = min(eles) if eles else None
    max_ele = max(eles) if eles else None

    return {
        "length_m": int(round(length)),
        "ascent_m": int(round(ascent)),
        "descent_m": int(round(descent)),
        "min_ele_m": None if min_ele is None else int(round(min_ele)),
        "max_ele_m": None if max_ele is None else int(round(max_ele)),
        "start": {"lat": points[0][0], "lon": points[0][1]},
        "end": {"lat": points[-1][0], "lon": points[-1][1]},
        "bbox": bbox,
    }

def scan_gpx_files(gpx_dir: Path):
    if not gpx_dir.exists():
        return []
    return sorted([p for p in gpx_dir.rglob("*.gpx") if p.is_file()])

def trail_id_from_relpath(rel_gpx_path: str):
    p = rel_gpx_path.replace("\\", "/")
    return p[:-4] if p.lower().endswith(".gpx") else p

def load_json_any(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json_any(path: Path, obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")

def get_trails_container(root_obj):
    if isinstance(root_obj, list):
        return root_obj, None
    if isinstance(root_obj, dict) and isinstance(root_obj.get("trails"), list):
        return root_obj["trails"], root_obj
    return [], root_obj

def find_existing_index(trails_list):
    idx = {}
    for item in trails_list:
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        if tid:
            idx[tid] = item
    return idx

def upsert(gpx_dir: Path, json_path: Path, verified_flag: bool):
    root = load_json_any(json_path) if json_path.exists() else []
    trails_list, container = get_trails_container(root)
    existing_by_id = find_existing_index(trails_list)

    now = utc_now_iso()
    new_trails = []

    for gpx_file in scan_gpx_files(gpx_dir):
        rel_path = gpx_file.as_posix()
        tid = trail_id_from_relpath(rel_path)

        prev = existing_by_id.get(tid, {})
        item = dict(prev) if isinstance(prev, dict) else {}

        item["id"] = tid
        item["gpx_path"] = rel_path
        item["verified"] = verified_flag
        item["updated_at"] = now

        points = parse_gpx_points(gpx_file)
        item["stats"] = compute_stats(points)

        new_trails.append(item)

    if container is None and isinstance(root, list):
        save_json_any(json_path, new_trails)
        return

    if isinstance(container, dict):
        container["trails"] = new_trails
        save_json_any(json_path, container)
        return

    save_json_any(json_path, new_trails)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verified-gpx-dir", required=True)
    ap.add_argument("--verified-json", required=True)
    ap.add_argument("--unverified-gpx-dir", required=True)
    ap.add_argument("--unverified-json", required=True)
    args = ap.parse_args()

    upsert(Path(args.verified_gpx_dir), Path(args.verified_json), True)
    upsert(Path(args.unverified_gpx_dir), Path(args.unverified_json), False)

if __name__ == "__main__":
    main()
