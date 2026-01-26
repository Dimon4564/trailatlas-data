#!/usr/bin/env python3
import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

# ------------------ helpers ------------------
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

    # Track points
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

    # Fallback: route points
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
            if d > 0:
                ascent += d
            else:
                descent += -d
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
        "startLat": points[0][0],
        "startLon": points[0][1],
        "endLat": points[-1][0],
        "endLon": points[-1][1],
        "bbox": bbox,
    }

def scan_gpx_files(gpx_dir: Path):
    if not gpx_dir.exists():
        return []
    return sorted([p for p in gpx_dir.rglob("*.gpx") if p.is_file()])

def load_json(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

def default_i18n(name: str):
    return {"ru": name, "ro": name, "uk": name}

def upsert_trails(gpx_dir: Path, json_path: Path, gpx_folder_name: str, raw_base: str):
    """
    Writes list of trail objects in YOUR format.
    Preserves manual fields if they already exist.
    """
    existing = load_json(json_path)
    existing_by_id = {t.get("id"): t for t in existing if isinstance(t, dict) and t.get("id")}

    now = utc_now_iso()
    new_list = []

    for gpx_file in scan_gpx_files(gpx_dir):
        stem = gpx_file.stem  # scate_park
        tid = stem

        prev = existing_by_id.get(tid, {})

        # Build gpxUrl
        # Example: https://raw.githubusercontent.com/Dimon4564/trailatlas-data/main/gpx/scate_park.gpx
        gpx_url = f"{raw_base}/{gpx_folder_name}/{gpx_file.name}"

        points = parse_gpx_points(gpx_file)
        stats = compute_stats(points)

        # Start coords
        start_lat = stats["startLat"] if stats else prev.get("startLat")
        start_lon = stats["startLon"] if stats else prev.get("startLon")

        # --- preserve manual fields if exist, otherwise defaults ---
        city_id = prev.get("cityId", "")                 
        difficulty = prev.get("difficulty", "")          
        styles = prev.get("styles", [])                  

        name = prev.get("name") if isinstance(prev.get("name"), dict) else default_i18n(stem)
        suitable = prev.get("suitable") if isinstance(prev.get("suitable"), dict) else default_i18n("")
        desc = prev.get("desc") if isinstance(prev.get("desc"), dict) else default_i18n("")

        item = {
            "id": tid,
            "cityId": city_id,
            "difficulty": difficulty,
            "styles": styles,
            "gpxUrl": gpx_url,
            "startLat": start_lat,
            "startLon": start_lon,

            "name": name,
            "suitable": suitable,
            "desc": desc,

            "stats": stats,
            "updatedAt": now
        }

        owned = set(item.keys())
        for k, v in prev.items():
            if k not in owned:
                item[k] = v

        new_list.append(item)

    save_json(json_path, new_list)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verified-gpx-dir", required=True)
    ap.add_argument("--verified-json", required=True)
    ap.add_argument("--unverified-gpx-dir", required=True)
    ap.add_argument("--unverified-json", required=True)
    ap.add_argument("--raw-base", default="https://raw.githubusercontent.com/Dimon4564/trailatlas-data/main")
    args = ap.parse_args()

    upsert_trails(Path(args.verified_gpx_dir), Path(args.verified_json), "gpx", args.raw_base)
    upsert_trails(Path(args.unverified_gpx_dir), Path(args.unverified_json), "gpx_unverified", args.raw_base)

if __name__ == "__main__":
    main()
