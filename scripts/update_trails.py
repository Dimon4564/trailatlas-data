#!/usr/bin/env python3
import argparse
import json
import math
import re
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    print("Warning: deep-translator not available. Translations will be skipped.")

LANGS = ("ru", "ro", "uk", "en")
DIFFICULTIES = ["green", "blue", "red", "black"]

# Country folder name to countryId mapping (extensible)
COUNTRY_FOLDERS = {
    "gpx_romania": "ro",
    "gpx_germany": "de",
    "gpx_poland": "pl",
}

# ------------------ helpers ------------------
def today_yyyy_mm_dd():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def sanitize_filename(name: str) -> str:
    """Sanitize a string to be a valid filename."""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name)
    name = name.lower().strip('_')
    return name if name else "unnamed"

def split_multi_track_gpx(gpx_path: Path, country_code: str) -> List[Path]:
    """
    Split a GPX file with multiple <trk> elements into individual GPX files.
    Returns list of created file paths.
    """
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        
        # Extract namespace
        m = re.match(r"\{(.+)\}", root.tag)
        ns = m.group(1) if m else ""
        def q(tag): return f"{{{ns}}}{tag}" if ns else tag
        
        tracks = root.findall(q("trk"))
        
        if len(tracks) <= 1:
            # Single track or no tracks, no need to split
            return []
        
        print(f"Splitting {gpx_path.name}: found {len(tracks)} tracks")
        
        created_files = []
        parent_dir = gpx_path.parent
        
        for idx, trk in enumerate(tracks, 1):
            # Try to get track name
            name_elem = trk.find(q("name"))
            if name_elem is not None and name_elem.text:
                track_name = sanitize_filename(name_elem.text)
                new_filename = f"{track_name}.gpx"
            else:
                new_filename = f"{country_code}_{idx:03d}.gpx"
            
            # Ensure unique filename
            new_path = parent_dir / new_filename
            counter = 1
            while new_path.exists():
                stem = new_filename.rsplit('.', 1)[0]
                new_path = parent_dir / f"{stem}_{counter}.gpx"
                counter += 1
            
            # Create new GPX with single track
            new_root = ET.Element(root.tag, root.attrib)
            
            # Copy metadata if exists
            metadata = root.find(q("metadata"))
            if metadata is not None:
                new_root.append(metadata)
            
            # Add the single track
            new_root.append(trk)
            
            # Write to file
            new_tree = ET.ElementTree(new_root)
            ET.indent(new_tree, space="  ")
            new_tree.write(new_path, encoding="utf-8", xml_declaration=True)
            
            created_files.append(new_path)
            print(f"  Created: {new_path.name}")
        
        # Delete original multi-track file
        gpx_path.unlink()
        print(f"  Deleted original: {gpx_path.name}")
        
        return created_files
        
    except Exception as e:
        print(f"Error splitting {gpx_path}: {e}")
        return []

def calculate_elevation_stats(points: List[Tuple[float, float, Optional[float]]]) -> Dict[str, float]:
    """
    Calculate elevation statistics from points with elevation data.
    Returns dict with elevation_gain, elevation_loss, avg_gradient, etc.
    """
    if not points:
        return {"elevation_gain": 0, "elevation_loss": 0, "avg_gradient": 0, "has_elevation": False}
    
    # Filter points with elevation data
    points_with_ele = [(lat, lon, ele) for lat, lon, ele in points if ele is not None]
    
    if len(points_with_ele) < 2:
        return {"elevation_gain": 0, "elevation_loss": 0, "avg_gradient": 0, "has_elevation": False}
    
    elevation_gain = 0
    elevation_loss = 0
    total_distance = 0
    
    for i in range(1, len(points_with_ele)):
        prev_lat, prev_lon, prev_ele = points_with_ele[i-1]
        curr_lat, curr_lon, curr_ele = points_with_ele[i]
        
        # Calculate distance (Haversine formula)
        lat1, lon1 = math.radians(prev_lat), math.radians(prev_lon)
        lat2, lon2 = math.radians(curr_lat), math.radians(curr_lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        distance = 6371000 * c  # Earth radius in meters
        
        total_distance += distance
        
        # Calculate elevation change
        ele_change = curr_ele - prev_ele
        if ele_change > 0:
            elevation_gain += ele_change
        else:
            elevation_loss += abs(ele_change)
    
    # Calculate average gradient
    avg_gradient = 0
    if total_distance > 0:
        net_elevation = elevation_gain - elevation_loss
        avg_gradient = (net_elevation / total_distance) * 100  # percentage
    
    return {
        "elevation_gain": elevation_gain,
        "elevation_loss": elevation_loss,
        "avg_gradient": abs(avg_gradient),
        "total_distance": total_distance,
        "has_elevation": True
    }

def determine_difficulty_from_elevation(stats: Dict[str, float], trail_id: str) -> str:
    """
    Determine difficulty based on elevation statistics.
    Falls back to stable random if no elevation data.
    """
    if not stats.get("has_elevation", False):
        return stable_random_difficulty(trail_id)
    
    avg_gradient = stats.get("avg_gradient", 0)
    
    if avg_gradient < 5:
        return "green"
    elif avg_gradient < 10:
        return "blue"
    elif avg_gradient < 15:
        return "red"
    else:
        return "black"

def detect_trail_styles(stats: Dict[str, float], points: List) -> List[str]:
    """Auto-detect trail styles based on characteristics."""
    styles = []
    
    if not stats.get("has_elevation", False):
        return ["MTB"]
    
    elevation_loss = stats.get("elevation_loss", 0)
    elevation_gain = stats.get("elevation_gain", 0)
    
    # Check if it's primarily downhill
    if elevation_loss > elevation_gain * 2 and elevation_loss > 50:
        styles = ["MTB", "DH"]
    else:
        styles = ["MTB"]
    
    return styles

def generate_suitable_text(difficulty: str, styles: List[str]) -> str:
    """Generate suitable field based on difficulty and styles."""
    # Convert styles list to tuple for dictionary key
    styles_tuple = tuple(sorted(styles)) if styles else ()
    
    style_map = {
        ("green", ("MTB",)): "Cross Country / All Mountain",
        ("blue", ("MTB",)): "All Mountain / Cross Country",
        ("blue", ("DH", "MTB")): "All Mountain / Enduro / Downhill",
        ("red", ("MTB",)): "All Mountain / Enduro",
        ("red", ("DH", "MTB")): "Enduro / Downhill",
        ("black", ("DH", "MTB")): "Downhill / Freeride",
        ("black", ("DH",)): "Downhill / Freeride"
    }
    
    key = (difficulty, styles_tuple)
    if key in style_map:
        return style_map[key]
    
    # Default based on difficulty
    if difficulty == "green":
        return "Cross Country / All Mountain"
    elif difficulty == "blue":
        return "All Mountain / Cross Country"
    elif difficulty == "red":
        return "All Mountain / Enduro"
    else:
        return "Downhill / Freeride"

def generate_description(stats: Dict[str, float], difficulty: str, country_code: str) -> str:
    """Generate a basic description in Russian based on trail characteristics."""
    distance_km = stats.get("total_distance", 0) / 1000
    elevation_gain = stats.get("elevation_gain", 0)
    
    country_names = {
        "ro": "Румынии",
        "de": "Германии",
        "pl": "Польши",
        "md": "Молдове"
    }
    
    country_name = country_names.get(country_code, "")
    
    if stats.get("has_elevation", False):
        desc = f"Трейл протяженностью {distance_km:.1f} км с набором высоты {elevation_gain:.0f} м"
        if country_name:
            desc += f" в {country_name}"
        desc += "."
    else:
        desc = f"Трейл"
        if country_name:
            desc += f" в {country_name}"
        desc += "."
    
    return desc

def stable_random_difficulty(trail_id: str) -> str:
    # "рандом", но стабильный: один и тот же id -> одна и та же сложность
    h = hashlib.md5(trail_id.encode("utf-8")).hexdigest()
    n = int(h[:8], 16)
    return DIFFICULTIES[n % len(DIFFICULTIES)]

def parse_gpx_points(gpx_path: Path, include_elevation: bool = True):
    """
    Returns list of (lat, lon, ele) tuples.
    Supports GPX 1.0/1.1 namespaces.
    If include_elevation is False, returns (lat, lon) tuples for backward compatibility.
    """
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
                
                if include_elevation:
                    ele_elem = pt.find(q("ele"))
                    ele = safe_float(ele_elem.text) if ele_elem is not None else None
                    pts.append((lat, lon, ele))
                else:
                    pts.append((lat, lon))

    # fallback rtept
    if not pts:
        for rte in root.findall(q("rte")):
            for pt in rte.findall(q("rtept")):
                lat = safe_float(pt.attrib.get("lat"))
                lon = safe_float(pt.attrib.get("lon"))
                if lat is None or lon is None:
                    continue
                
                if include_elevation:
                    ele_elem = pt.find(q("ele"))
                    ele = safe_float(ele_elem.text) if ele_elem is not None else None
                    pts.append((lat, lon, ele))
                else:
                    pts.append((lat, lon))

    return pts

def get_gpx_track_name(gpx_path: Path) -> Optional[str]:
    """Extract track name from GPX file."""
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        m = re.match(r"\{(.+)\}", root.tag)
        ns = m.group(1) if m else ""
        def q(tag): return f"{{{ns}}}{tag}" if ns else tag
        
        # Try track name first
        for trk in root.findall(q("trk")):
            name_elem = trk.find(q("name"))
            if name_elem is not None and name_elem.text:
                return name_elem.text
        
        # Try metadata name
        metadata = root.find(q("metadata"))
        if metadata is not None:
            name_elem = metadata.find(q("name"))
            if name_elem is not None and name_elem.text:
                return name_elem.text
        
        return None
    except Exception:
        return None

def scan_gpx_files(gpx_dir: Path):
    if not gpx_dir.exists():
        return []
    return sorted([p for p in gpx_dir.rglob("*.gpx") if p.is_file()])

def preprocess_split_multi_track_gpx(gpx_dir: Path):
    """
    Scan all country subfolders for multi-track GPX files and split them.
    """
    if not gpx_dir.exists():
        return
    
    # Check country subfolders
    for folder_name, country_code in COUNTRY_FOLDERS.items():
        folder_path = gpx_dir / folder_name
        if not folder_path.exists():
            continue
        
        gpx_files = sorted([p for p in folder_path.glob("*.gpx") if p.is_file()])
        
        for gpx_file in gpx_files:
            split_multi_track_gpx(gpx_file, country_code)

def load_root(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_root(path: Path, root_obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(root_obj, f, ensure_ascii=False, indent=2)
        f.write("\n")

def translate_text(text: str, target_lang: str) -> str:
    """Translate text to target language using deep-translator."""
    if not TRANSLATOR_AVAILABLE or not text or not text.strip():
        return text
    
    try:
        # Map language codes to deep-translator format
        lang_map = {
            "ru": "ru",
            "ro": "ro",
            "uk": "uk",
            "en": "en"
        }
        
        target = lang_map.get(target_lang, target_lang)
        translator = GoogleTranslator(source='auto', target=target)
        result = translator.translate(text)
        time.sleep(0.1)  # Rate limiting
        return result if result else text
    except Exception as e:
        # Silently fail and return original text
        return text

def auto_translate_i18n(source_text: str, source_lang: str = "ru") -> Dict[str, str]:
    """Auto-translate text to all languages."""
    result = {}
    for lang in LANGS:
        if lang == source_lang:
            result[lang] = source_text
        else:
            translated = translate_text(source_text, lang)
            # If translation failed, use source text as fallback
            result[lang] = translated if translated != source_text or not TRANSLATOR_AVAILABLE else source_text
    return result

def default_i18n(text: str):
    return {k: text for k in LANGS}

def normalize_i18n(d, fallback: str):
    if isinstance(d, dict):
        out = {}
        for k in LANGS:
            out[k] = d.get(k, fallback)
        return out
    return default_i18n(fallback)

def roots_equal(a, b):
    # Compare content ignoring formatting/order noise
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)

# ------------------ main trail builder ------------------
def build_trail_object(prev: dict, tid: str, gpx_url: str, start_lat, start_lon, 
                       gpx_path: Path = None, country_id: str = None, 
                       is_unverified: bool = False):
    """
    Build object exactly in your schema:
    id, cityId, styles, name, suitable, difficulty, desc, gpxUrl, startLat, startLon
    (difficulty stable-random if missing/invalid)
    cityId forced to chisinau
    
    For unverified trails from country folders, auto-generate fields.
    """
    # Force cityId for every trail
    city_id = prev.get("cityId", "chisinau")

    # Get elevation stats if GPX path provided
    stats = {"has_elevation": False}
    pts_with_ele = []
    if gpx_path and gpx_path.exists():
        pts_with_ele = parse_gpx_points(gpx_path, include_elevation=True)
        if pts_with_ele:
            stats = calculate_elevation_stats(pts_with_ele)
    
    # Handle difficulty
    prev_diff = prev.get("difficulty", "")
    if isinstance(prev_diff, str) and prev_diff.strip() in DIFFICULTIES:
        difficulty = prev_diff.strip()
    elif is_unverified and stats.get("has_elevation", False):
        # Auto-determine difficulty for unverified trails
        difficulty = determine_difficulty_from_elevation(stats, tid)
    else:
        difficulty = stable_random_difficulty(tid)

    # Handle styles
    prev_styles = prev.get("styles", [])
    if isinstance(prev_styles, list) and len(prev_styles) > 0:
        styles = prev_styles
    elif is_unverified and stats.get("has_elevation", False):
        # Auto-detect styles for unverified trails
        styles = detect_trail_styles(stats, pts_with_ele)
    else:
        styles = []

    # Handle name - try to get from GPX if not set
    prev_name = prev.get("name")
    if isinstance(prev_name, dict):
        # Check if we have any existing values
        has_existing = any(v for v in prev_name.values() if v)
        if has_existing:
            # Normalize to include all languages
            name = {}
            for lang in LANGS:
                if lang in prev_name and prev_name[lang]:
                    name[lang] = prev_name[lang]
                else:
                    # Fill missing language with Russian or first available
                    name[lang] = prev_name.get("ru") or next((v for v in prev_name.values() if v), tid)
        else:
            # No existing values, try GPX name
            gpx_name = None
            if gpx_path and gpx_path.exists():
                gpx_name = get_gpx_track_name(gpx_path)
            
            if gpx_name:
                name = auto_translate_i18n(gpx_name, "ru")
            else:
                name = default_i18n(tid)
    else:
        # Try to extract name from GPX
        gpx_name = None
        if gpx_path and gpx_path.exists():
            gpx_name = get_gpx_track_name(gpx_path)
        
        if gpx_name:
            name = auto_translate_i18n(gpx_name, "ru")
        else:
            name = default_i18n(tid)
    
    # Handle suitable field
    prev_suitable = prev.get("suitable")
    if isinstance(prev_suitable, dict):
        has_existing = any(v for v in prev_suitable.values() if v)
        if has_existing:
            suitable = {}
            for lang in LANGS:
                if lang in prev_suitable and prev_suitable[lang]:
                    suitable[lang] = prev_suitable[lang]
                else:
                    # Fill missing language with Russian or first available
                    suitable[lang] = prev_suitable.get("ru") or next((v for v in prev_suitable.values() if v), "")
        elif is_unverified:
            # Auto-generate suitable for unverified trails
            suitable_text = generate_suitable_text(difficulty, styles)
            suitable = auto_translate_i18n(suitable_text, "en")
        else:
            suitable = default_i18n("")
    elif is_unverified:
        # Auto-generate suitable for unverified trails
        suitable_text = generate_suitable_text(difficulty, styles)
        suitable = auto_translate_i18n(suitable_text, "en")
    else:
        suitable = default_i18n("")
    
    # Handle description
    prev_desc = prev.get("desc")
    if isinstance(prev_desc, dict):
        has_existing = any(v for v in prev_desc.values() if v)
        if has_existing:
            desc = {}
            for lang in LANGS:
                if lang in prev_desc and prev_desc[lang]:
                    desc[lang] = prev_desc[lang]
                else:
                    # Fill missing language with Russian or first available
                    desc[lang] = prev_desc.get("ru") or next((v for v in prev_desc.values() if v), "")
        elif is_unverified and country_id:
            # Auto-generate description for unverified trails
            desc_text = generate_description(stats, difficulty, country_id)
            desc = auto_translate_i18n(desc_text, "ru")
        else:
            desc = default_i18n("")
    elif is_unverified and country_id:
        # Auto-generate description for unverified trails
        desc_text = generate_description(stats, difficulty, country_id)
        desc = auto_translate_i18n(desc_text, "ru")
    else:
        desc = default_i18n("")

    # Build in stable key order
    obj = {
        "id": tid,
        "cityId": city_id,
        "styles": styles,
        "name": name,
        "suitable": suitable,
        "difficulty": difficulty,
        "desc": desc,
        "gpxUrl": gpx_url,
        "startLat": start_lat,
        "startLon": start_lon,
    }
    
    # Add countryId if provided or if it exists in prev
    if country_id:
        obj["countryId"] = country_id
    elif "countryId" in prev:
        obj["countryId"] = prev["countryId"]

    # Preserve any extra custom fields that might exist in prev
    owned = set(obj.keys())
    if isinstance(prev, dict):
        for k, v in prev.items():
            if k not in owned:
                obj[k] = v

    return obj

def upsert_file(gpx_dir: Path, json_path: Path, gpx_folder_name: str, raw_base: str, 
                default_version: int, is_unverified: bool = False):
    """
    Ensures JSON is:
    {
      "version": <int>,
      "updatedAt": "YYYY-MM-DD",
      "trails": [ ... ]
    }
    
    For unverified trails, also scans country subfolders.
    """
    existing_root = load_root(json_path)

    # Read existing schema or create new
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

    # Collect all GPX files (root folder + country subfolders for unverified)
    all_gpx_files = []
    
    # Root folder GPX files
    if gpx_dir.exists():
        root_gpx = sorted([p for p in gpx_dir.glob("*.gpx") if p.is_file()])
        all_gpx_files.extend([(p, None) for p in root_gpx])  # (path, country_id)
    
    # Country subfolder GPX files (only for unverified)
    if is_unverified:
        for folder_name, country_code in COUNTRY_FOLDERS.items():
            folder_path = gpx_dir / folder_name
            if folder_path.exists():
                subfolder_gpx = sorted([p for p in folder_path.glob("*.gpx") if p.is_file()])
                all_gpx_files.extend([(p, country_code) for p in subfolder_gpx])
    
    file_by_id = {}
    for p, country_code in all_gpx_files:
        tid = p.stem
        file_by_id[tid] = (p, country_code)

    new_trails = []

    # Keep old order first
    for tid in order:
        if tid not in file_by_id:
            continue  # GPX removed -> remove from JSON
        
        p, country_code = file_by_id[tid]
        pts = parse_gpx_points(p, include_elevation=False)  # For backward compatibility

        # start coords from GPX if possible, else keep previous
        if pts:
            start_lat, start_lon = pts[0][0], pts[0][1]
        else:
            start_lat = existing_by_id[tid].get("startLat")
            start_lon = existing_by_id[tid].get("startLon")

        # Construct GPX URL based on location
        if country_code:
            folder_name = [k for k, v in COUNTRY_FOLDERS.items() if v == country_code][0]
            gpx_url = f"{raw_base}/{gpx_folder_name}/{folder_name}/{p.name}"
        else:
            gpx_url = f"{raw_base}/{gpx_folder_name}/{p.name}"
        
        new_trails.append(build_trail_object(
            existing_by_id[tid], tid, gpx_url, start_lat, start_lon,
            gpx_path=p, country_id=country_code, is_unverified=is_unverified
        ))

    # Add new GPX not present in JSON, sorted by id
    for tid in sorted(file_by_id.keys()):
        if tid in existing_by_id:
            continue
        
        p, country_code = file_by_id[tid]
        pts = parse_gpx_points(p, include_elevation=False)
        start_lat = pts[0][0] if pts else None
        start_lon = pts[0][1] if pts else None
        
        # Construct GPX URL based on location
        if country_code:
            folder_name = [k for k, v in COUNTRY_FOLDERS.items() if v == country_code][0]
            gpx_url = f"{raw_base}/{gpx_folder_name}/{folder_name}/{p.name}"
        else:
            gpx_url = f"{raw_base}/{gpx_folder_name}/{p.name}"
        
        new_trails.append(build_trail_object(
            {}, tid, gpx_url, start_lat, start_lon,
            gpx_path=p, country_id=country_code, is_unverified=is_unverified
        ))

    # EXTRA SAFETY: ensure cityId exists in every trail (even if something strange happens)
    for t in new_trails:
        if isinstance(t, dict):
            if "cityId" not in t:
                t["cityId"] = "chisinau"

    new_root = {
        "version": version,
        "updatedAt": updated_at,
        "trails": new_trails
    }

    # Update updatedAt only if trails changed (ignore updatedAt in comparison)
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

    # Pre-processing: Split multi-track GPX files in unverified country folders
    print("Pre-processing: Checking for multi-track GPX files...")
    preprocess_split_multi_track_gpx(Path(args.unverified_gpx_dir))
    
    # Main processing
    print("\nProcessing verified trails...")
    upsert_file(Path(args.verified_gpx_dir), Path(args.verified_json), "gpx", args.raw_base, 
                default_version=10, is_unverified=False)
    
    print("\nProcessing unverified trails...")
    upsert_file(Path(args.unverified_gpx_dir), Path(args.unverified_json), "gpx_unverified", 
                args.raw_base, default_version=1, is_unverified=True)
    
    print("\nDone!")

if __name__ == "__main__":
    main()
