#!/usr/bin/env python3
import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

LANGS = ("ru", "ro", "uk")

def today_yyyy_mm_dd():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def parse_gpx_points(gpx_path: Path):
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    m = re.match(r"\{(.+)\}", root.tag)
    ns = m.group(1) if m else ""
    def q(tag): return f"{{{ns}}}{tag}" if ns else tag

    pts = []
    # trkpt
    for trk in root.findall(q("trk")):
        for seg in trk.findall(f".//{q('trkseg')}"):
            for pt in seg.findall(q("trkpt")):
                lat = safe_float(pt.attrib.get("lat"))
                lon = safe_float(pt.attrib.get("lon"))
                if lat is None or lon is None:
                    continue
                pts.append((lat, lon))

    # fallback rtept
    if not pts:
        for rte in root.findall(q("rte")):
            for pt in rte.findall(q("rtept")):
                lat = safe_float(pt.attrib.get("lat"))
                lon = safe_float(pt.attrib.get("lon"))
                if lat is None or lon is None:
                    continue
                pts.append((lat, lon))

    return pts

def scan_gpx_files(gpx_dir: Path):
    if not gpx_dir.exists():
        return []
    return sorted([p for p in gpx_dir.rglob("*.gpx") if p.is_file()])

def load_root(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_root(path: Path, root_obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(root_obj, f, ensure_ascii=False, indent=2)
        f.write("\n")

def default_i18n(text: str):
    return {k: text for k in LANGS}

def normalize_i18n(d, fallback: str):
    if isinstance(d, dict):
        out = {}
        for k in LANGS:
            out[k] = d.get(k, fallback)
        return out
    return default_i18n(fallback)

def build_trail_object(prev: dict, tid: str, gpx_url: str, start_lat: float | None, start_lon: float | None):
    city_id = prev.get("cityId", "")
    difficulty = prev.get("difficulty", "")
    styles = prev.get("styles", [])

    name = normalize_i18n(prev.get("name"), tid)
    suitable = normalize_i18n(prev.get("suitable"), "")
    desc = normalize_i18n(prev.get("desc"), "")

    obj = {
        "id": tid,
        "cityId": city_id,
        "difficulty": difficulty,
        "styles": styles,
        "name": name,
        "suitable": suitable,
        "desc": desc,
        "gpxUrl": gpx_url,
        "startLat": start_lat,
        "startLon": start_lon,
    }

    owned = set(obj.keys())
    for k, v in prev.items():
        if k not in owned:
            obj[k] = v

    return obj

def roots_equal(a, b):
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)

def upsert_file(gpx_dir: Path, json_path: Path, gpx_folder_name: str, raw_base: str, default_version: int):
    existing_root = load_root(json_path)

    if isinstance(existing_root, dict) and isinstance(existing_root.get("trails"), list):
        version = existing_root.get("version", default_version)
        updated_at = existing_root.get("updatedAt", today_yyyy_mm_dd())
        existing_trails = existing_root.get("trails", [])
    else:
        version = default_version
        updated_at = today_yyyy_mm_dd()
        existing_trails = []

    existing_by_id = {}
    order = []
    for t in existing_trails:
        if isinstance(t, dict) and t.get("id"):
            tid = t["id"]
            existing_by_id[tid] = t
            order.append(tid)

    gpx_files = scan_gpx_files(gpx_dir)
    file_by_id = {p.stem: p for p in gpx_files}  # id = filename stem

    new_trails = []

    for tid in order:
        p = file_by_id.get(tid)
        if not p:
            continue  
        pts = parse_gpx_points(p)
        start_lat = pts[0][0] if pts else existing_by_id[tid].get("startLat")
        start_lon = pts[0][1] if pts else existing_by_id[tid].get("startLon")
        gpx_url = f"{raw_base}/{gpx_folder_name}/{p.name}"
        new_trails.append(build_trail_object(existing_by_id[tid], tid, gpx_url, start_lat, start_lon))

    for tid in sorted(file_by_id.keys()):
        if tid in existing_by_id:
            continue
        p = file_by_id[tid]
        pts = parse_gpx_points(p)
        start_lat = pts[0][0] if pts else None
        start_lon = pts[0][1] if pts else None
        gpx_url = f"{raw_base}/{gpx_folder_name}/{p.name}"
        new_trails.append(build_trail_object({}, tid, gpx_url, start_lat, start_lon))

    new_root = {
        "version": version,
        "updatedAt": updated_at,
        "trails": new_trails
    }

    if isinstance(existing_root, dict) and isinstance(existing_root.get("trails"), list):
        old_compare = dict(existing_root)
        new_compare = dict(new_root)
        old_compare["updatedAt"] = "X"
        new_compare["updatedAt"] = "X"

        if not roots_equal(old_compare, new_compare):
            new_root["updatedAt"] = today_yyyy_mm_dd()
        else:
            new_root["updatedAt"] = existing_root.get("updatedAt", updated_at)

    save_root(json_path, new_root)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verified-gpx-dir", required=True)
    ap.add_argument("--verified-json", required=True)
    ap.add_argument("--unverified-gpx-dir", required=True)
    ap.add_argument("--unverified-json", required=True)
    ap.add_argument("--raw-base", required=True)
    args = ap.parse_args()

    upsert_file(Path(args.verified_gpx_dir), Path(args.verified_json), "gpx", args.raw_base, default_version=10)
    upsert_file(Path(args.unverified_gpx_dir), Path(args.unverified_json), "gpx_unverified", args.raw_base, default_version=1)

if __name__ == "__main__":
    main()
