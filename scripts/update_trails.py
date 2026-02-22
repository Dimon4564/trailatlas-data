#!/usr/bin/env python3
import argparse
import json
import math
import random
import re
import hashlib
import time
from copy import deepcopy
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
def is_filename_based_name(name_dict, trail_id):
    """Check if the name was auto-generated from the file ID rather than being a real trail name."""
    if not isinstance(name_dict, dict):
        return True
    en_name = name_dict.get("en", "")
    if not en_name:
        return True
    en_lower = en_name.lower().strip()
    tid_clean = trail_id.replace("_", " ").lower().strip()
    if en_lower == tid_clean or en_lower == trail_id.lower():
        return True
    if en_lower == f"{tid_clean} trail" or en_lower == f"{trail_id.lower()} trail":
        return True
    import re as _re
    if _re.match(r'^[a-z]{2}[ _]\d{3}( trail)?$', en_lower):
        return True
    tid_variants = [
        tid_clean,
        tid_clean + " trail",
        tid_clean.replace(" ", "_"),
        tid_clean.replace(" ", "_") + " trail",
        trail_id.lower(),
        trail_id.lower() + " trail",
    ]
    if en_lower in tid_variants:
        return True
    return False
DIFFICULTIES = ["green", "blue", "red", "black"]

# Country folder name to countryId mapping (extensible)
COUNTRY_FOLDERS = {
    "gpx_romania": "ro",
    "gpx_germany": "de",
    "gpx_poland": "pl",
    "gpx_ukraine": "ua",
}

# Reverse mapping for efficiency
COUNTRY_CODE_TO_FOLDER = {v: k for k, v in COUNTRY_FOLDERS.items()}

# Trail type names in all languages
TRAIL_TYPE_NAMES = {
    "xc": {"ru": "XC трейл", "ro": "Traseu XC", "uk": "XC трейл", "en": "XC Trail"},
    "trail": {"ru": "Трейл", "ro": "Traseu", "uk": "Трейл", "en": "Trail"},
    "enduro": {"ru": "Эндуро", "ro": "Enduro", "uk": "Ендуро", "en": "Enduro"},
    "dh": {"ru": "Даунхилл", "ro": "Downhill", "uk": "Даунхіл", "en": "Downhill"},
    "flow": {"ru": "Флоу", "ro": "Flow", "uk": "Флоу", "en": "Flow"}
}

# Random trail names used as fallback when no name can be determined
RANDOM_TRAIL_NAMES = [
    "Hidden Valley Trail",
    "Sunset Ridge Path",
    "Eagle's Nest Loop",
    "Wildflower Meadow Trail",
    "Silver Creek Route",
    "Thunder Peak Trail",
    "Misty Mountain Path",
    "Golden Oak Loop",
    "Falcon Ridge Trail",
    "Pinecone Valley Route",
    "Stony Brook Path",
    "Crimson Ridge Trail",
    "Whispering Pines Loop",
    "Bear Creek Trail",
    "Moonlit Ridge Path",
    "Cedar Canyon Route",
    "Maple Hollow Trail",
    "Rocky Summit Path",
    "Deer Crossing Loop",
    "Sapphire Lake Trail",
    "Timber Wolf Path",
    "Copper Creek Route",
    "Birchwood Trail",
    "Aspen Grove Loop",
    "Coyote Ridge Trail",
    "Crystal Springs Path",
    "Shadow Canyon Route",
    "Ironwood Trail",
    "Fox Meadow Loop",
    "Granite Peak Path",
    "Lone Pine Trail",
    "Rushing Waters Route",
    "Amber Hillside Path",
    "Ravine Ridge Loop",
]

# Trail type descriptions in Russian
TRAIL_TYPE_DESCRIPTIONS = {
    "xc": {
        "green": "Кросс-кантри трейл с плавными подъемами",
        "blue": "Кросс-кантри трейл с умеренными подъемами",
        "red": "Технический кросс-кантри трейл",
        "black": "Экстремальный технический трейл"
    },
    "trail": {
        "green": "Лесная тропа с несложными участками",
        "blue": "Трейловая трасса с техническими секциями",
        "red": "Технически сложная трейловая трасса",
        "black": "Экстремальная трейловая трасса с высокой технической сложностью"
    },
    "enduro": {
        "green": "Эндуро трасса начального уровня",
        "blue": "Эндуро трасса с чередованием подъемов и спусков",
        "red": "Эндуро трасса с крутыми спусками и техническими участками",
        "black": "Экстремальная эндуро трасса с очень крутыми и техническими секциями"
    },
    "dh": {
        "green": "Даунхилл трасса для начинающих",
        "blue": "Даунхилл трасса среднего уровня",
        "red": "Технический даунхилл с крутыми спусками",
        "black": "Экстремальный даунхилл с очень крутыми и опасными участками"
    },
    "flow": {
        "green": "Флоу-трейл с плавными виражами",
        "blue": "Флоу-трейл с прыжками и виражами",
        "red": "Технический флоу-трейл с большими прыжками",
        "black": "Экстремальный флоу-трейл для профессионалов"
    }
}

# Surface type descriptions in Russian
SURFACE_DESCRIPTIONS = {
    "dirt": "грунтовое покрытие",
    "gravel": "гравийное покрытие",
    "paved": "асфальтированная поверхность",
    "ground": "естественное покрытие"
}

# Difficulty recommendations in Russian
DIFFICULTY_DESCRIPTIONS = {
    "green": "Подходит для начинающих райдеров",
    "blue": "Требует базовых навыков катания и хорошей физической подготовки",
    "red": "Рекомендуется для опытных райдеров с хорошей технической подготовкой",
    "black": "ТОЛЬКО для экспертов! Требует отличной техники, опыта и специального оборудования"
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

def convert_route_to_track(rte_elem, ns: str):
    """
    Convert a <rte> element to a <trk> element.
    Routes contain <rtept> elements directly, tracks contain <trkseg> with <trkpt> elements.
    """
    def q(tag): return f"{{{ns}}}{tag}" if ns else tag
    
    # Create new track element
    trk = ET.Element(q("trk"))
    
    # Copy name if exists
    name_elem = rte_elem.find(q("name"))
    if name_elem is not None:
        new_name = ET.SubElement(trk, q("name"))
        new_name.text = name_elem.text
    
    # Copy other metadata (desc, cmt, etc.)
    for child in rte_elem:
        if child.tag in [q("name"), q("rtept")]:
            continue  # Skip name (already copied) and route points (will be converted)
        trk.append(deepcopy(child))
    
    # Create track segment
    trkseg = ET.SubElement(trk, q("trkseg"))
    
    # Convert route points to track points
    for rtept in rte_elem.findall(q("rtept")):
        trkpt = ET.SubElement(trkseg, q("trkpt"), rtept.attrib)
        # Copy all children (ele, time, etc.)
        for child in rtept:
            trkpt.append(deepcopy(child))
    
    return trk

def should_process_track(trk_elem, gpx_root, ns: str) -> Tuple[bool, str]:
    """
    Check if track should be processed.
    Returns (should_process, skip_reason)
    """
    def q(tag): return f"{{{ns}}}{tag}" if ns else tag
    
    # Check if track has a name - named tracks are always processed regardless of length
    name_elem = trk_elem.find(q("name"))
    has_name = name_elem is not None and name_elem.text and name_elem.text.strip()
    
    # Create temp GPX to analyze
    temp_root = ET.Element(gpx_root.tag, gpx_root.attrib)
    temp_root.append(deepcopy(trk_elem))
    temp_tree = ET.ElementTree(temp_root)
    
    # Save to temp file
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gpx', delete=False) as f:
            temp_file_name = f.name
        # Write after closing the file to avoid issues on some platforms
        temp_path = Path(temp_file_name)
        temp_tree.write(temp_path, encoding='utf-8', xml_declaration=True)
        
        # Check point count - but named tracks are always processed
        pts = parse_gpx_points(temp_path, include_elevation=True)
        if not has_name and len(pts) < 10:
            return (False, f"too few points ({len(pts)})")
        
        # Check length
        stats = calculate_elevation_stats(pts)
        length = stats.get("total_distance", 0)
        
        if not has_name and length < 700:
            return (False, f"too short ({length:.0f}m)")
        
        if length > 50000:
            return (False, f"too long ({length/1000:.1f}km)")
        
        return (True, "")
    
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()

def split_multi_track_gpx(gpx_path: Path, country_code: str) -> List[Path]:
    """
    Split a GPX file with multiple <trk> or <rte> elements into individual GPX files.
    Routes are automatically converted to tracks in output.
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
        routes = root.findall(q("rte"))
        
        # Check if we need to split
        total_elements = len(tracks) + len(routes)
        if total_elements <= 1:
            # Single track/route or no tracks/routes, no need to split
            return []
        
        element_type = "tracks" if tracks else "routes"
        if tracks and routes:
            element_type = f"{len(tracks)} tracks and {len(routes)} routes"
        else:
            element_type = f"{total_elements} {element_type}"
        
        print(f"Splitting {gpx_path.name}: found {element_type}")
        
        created_files = []
        parent_dir = gpx_path.parent
        
        # Process tracks
        for idx, trk in enumerate(tracks, 1):
            # Check if track should be processed
            should_process, skip_reason = should_process_track(trk, root, ns)
            if not should_process:
                print(f"⚠️  Skipping track {idx}: {skip_reason}")
                continue
            
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
                new_root.append(deepcopy(metadata))
            
            # Add the single track
            new_root.append(trk)
            
            # Write to file
            new_tree = ET.ElementTree(new_root)
            ET.indent(new_tree, space="  ")
            new_tree.write(new_path, encoding="utf-8", xml_declaration=True)
            
            created_files.append(new_path)
            print(f"  Created: {new_path.name}")
        
        # Process routes (convert to tracks)
        # Note: idx starts after tracks (len(tracks) + 1) for continuous numbering in fallback filenames
        # Example: if 2 tracks without names create ro_001.gpx and ro_002.gpx, routes will create ro_003.gpx, ro_004.gpx, etc.
        for idx, rte in enumerate(routes, len(tracks) + 1):
            # Convert route to track first for quality checking
            trk = convert_route_to_track(rte, ns)
            
            # Check if track should be processed
            should_process, skip_reason = should_process_track(trk, root, ns)
            if not should_process:
                print(f"⚠️  Skipping route {idx}: {skip_reason}")
                continue
            
            # Try to get route name
            name_elem = rte.find(q("name"))
            if name_elem is not None and name_elem.text:
                route_name = sanitize_filename(name_elem.text)
                new_filename = f"{route_name}.gpx"
            else:
                new_filename = f"{country_code}_{idx:03d}.gpx"
            
            # Ensure unique filename
            new_path = parent_dir / new_filename
            counter = 1
            while new_path.exists():
                stem = new_filename.rsplit('.', 1)[0]
                new_path = parent_dir / f"{stem}_{counter}.gpx"
                counter += 1
            
            # Create new GPX with route converted to track
            new_root = ET.Element(root.tag, root.attrib)
            
            # Copy metadata if exists
            metadata = root.find(q("metadata"))
            if metadata is not None:
                new_root.append(deepcopy(metadata))
            
            # Add the converted track (already done above)
            new_root.append(trk)
            
            # Write to file
            new_tree = ET.ElementTree(new_root)
            ET.indent(new_tree, space="  ")
            new_tree.write(new_path, encoding="utf-8", xml_declaration=True)
            
            created_files.append(new_path)
            print(f"  Created: {new_path.name} (converted from route)")
        
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
    Returns dict with elevation_gain, elevation_loss, avg_gradient, total_distance, etc.
    Always calculates total_distance even without elevation data.
    """
    if not points:
        return {"elevation_gain": 0, "elevation_loss": 0, "avg_gradient": 0, "total_distance": 0, "has_elevation": False}
    
    # Filter points with elevation data
    points_with_ele = [(lat, lon, ele) for lat, lon, ele in points if ele is not None]
    
    # Calculate total distance using all points (even without elevation)
    total_distance = 0
    for i in range(1, len(points)):
        prev_lat, prev_lon = points[i-1][0], points[i-1][1]
        curr_lat, curr_lon = points[i][0], points[i][1]
        
        # Calculate distance (Haversine formula)
        lat1, lon1 = math.radians(prev_lat), math.radians(prev_lon)
        lat2, lon2 = math.radians(curr_lat), math.radians(curr_lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        distance = 6371000 * c  # Earth radius in meters
        
        total_distance += distance
    
    # If we have no elevation data, return early with distance only
    if len(points_with_ele) < 2:
        return {"elevation_gain": 0, "elevation_loss": 0, "avg_gradient": 0, "total_distance": total_distance, "has_elevation": False}
    
    elevation_gain = 0
    elevation_loss = 0
    
    for i in range(1, len(points_with_ele)):
        prev_ele = points_with_ele[i-1][2]
        curr_ele = points_with_ele[i][2]
        
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

def generate_description(gpx_path: Path, stats: Dict[str, float], difficulty: str, 
                        country_code: str, trail_type: str) -> str:
    """Generate detailed, unique description based on trail characteristics"""
    distance_km = stats.get("total_distance", 0) / 1000
    elevation_gain = stats.get("elevation_gain", 0)
    elevation_loss = stats.get("elevation_loss", 0)
    
    # Extract OSM surface info if available
    surface = extract_surface_type(gpx_path) if gpx_path else None
    
    # Build description parts
    parts = []
    
    # 1. Basic length and elevation
    if stats.get("has_elevation", False):
        if elevation_loss > elevation_gain * 1.2:
            parts.append(f"Трейл протяженностью {distance_km:.1f} км с перепадом высоты {elevation_loss:.0f} м")
        else:
            parts.append(f"Трейл протяженностью {distance_km:.1f} км с набором высоты {elevation_gain:.0f} м")
    else:
        parts.append(f"Трейл протяженностью {distance_km:.1f} км")
    
    # 2. Trail type description - MATCH with difficulty properly
    if trail_type in TRAIL_TYPE_DESCRIPTIONS and difficulty in TRAIL_TYPE_DESCRIPTIONS[trail_type]:
        parts.append(TRAIL_TYPE_DESCRIPTIONS[trail_type][difficulty])
    else:
        # Fallback generic descriptions
        parts.append("Горный велосипедный трейл")
    
    # 3. Surface type if available
    if surface and surface in SURFACE_DESCRIPTIONS:
        parts.append(f"Покрытие: {SURFACE_DESCRIPTIONS[surface]}")
    
    # 4. Difficulty recommendation
    if difficulty in DIFFICULTY_DESCRIPTIONS:
        parts.append(DIFFICULTY_DESCRIPTIONS[difficulty])
    
    # Join parts
    desc = ". ".join(parts) + "."
    
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
    """Extract track or route name from GPX file."""
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
        
        # Try route name
        for rte in root.findall(q("rte")):
            name_elem = rte.find(q("name"))
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

def extract_osm_name(gpx_path: Path) -> Optional[str]:
    """Extract name from OSM extensions (ogr:name or ogr:ref)"""
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        m = re.match(r"\{(.+)\}", root.tag)
        ns = m.group(1) if m else ""
        
        # Check for ogr:ref (e.g., "DC49")
        for ext in root.findall('.//{*}extensions'):
            ref_elem = ext.find('.//{*}ref')
            if ref_elem is not None and ref_elem.text:
                return f"Route {ref_elem.text}"
            
            name_elem = ext.find('.//{*}name')
            if name_elem is not None and name_elem.text:
                return name_elem.text
        
        return None
    except Exception:
        return None

def detect_region_from_coords(lat: float, lon: float) -> str:
    """Region detection based on coordinates"""
    # Romania regions
    if 45.4 <= lat <= 45.9 and 21.2 <= lon <= 21.8:
        return "Timiș"
    elif 44.7 <= lat <= 45.2 and 22.5 <= lon <= 23.0:
        return "Caraș-Severin"
    elif 47.0 <= lat <= 47.8 and 23.5 <= lon <= 24.5:
        return "Cluj"
    elif 46.0 <= lat <= 46.5 and 24.5 <= lon <= 25.5:
        return "Brașov"
    elif 45.0 <= lat <= 45.5 and 25.5 <= lon <= 26.5:
        return "Prahova"

    # Ukraine regions (approximate lat/lon ranges)
    elif 48.2 <= lat <= 48.9 and 23.5 <= lon <= 25.0:
        return "Carpathians"
    elif 49.7 <= lat <= 50.0 and 23.5 <= lon <= 24.5:
        return "Lviv"
    elif 50.3 <= lat <= 50.6 and 30.2 <= lon <= 30.8:
        return "Kyiv"
    elif 48.4 <= lat <= 48.7 and 34.9 <= lon <= 35.3:
        return "Dnipro"
    elif 49.8 <= lat <= 50.1 and 36.1 <= lon <= 36.5:
        return "Kharkiv"
    elif 46.4 <= lat <= 46.7 and 30.6 <= lon <= 30.9:
        return "Odesa"
    elif 48.5 <= lat <= 49.0 and 24.0 <= lon <= 24.8:
        return "Ivano-Frankivsk"
    elif 48.0 <= lat <= 48.5 and 22.0 <= lon <= 23.0:
        return "Zakarpattia"
    elif 49.4 <= lat <= 49.9 and 23.8 <= lon <= 24.2:
        return "Lviv Region"
    elif 48.8 <= lat <= 49.3 and 25.0 <= lon <= 25.8:
        return "Ternopil"

    # Germany regions (approximate)
    elif 47.5 <= lat <= 48.5 and 7.5 <= lon <= 9.0:
        return "Black Forest"
    elif 47.0 <= lat <= 47.8 and 10.5 <= lon <= 12.5:
        return "Bavaria"
    elif 49.0 <= lat <= 50.0 and 8.0 <= lon <= 10.0:
        return "Baden-Württemberg"

    # Poland regions (approximate)
    elif 49.0 <= lat <= 49.6 and 19.0 <= lon <= 20.5:
        return "Tatras"
    elif 50.0 <= lat <= 50.5 and 19.5 <= lon <= 20.5:
        return "Kraków"
    elif 52.0 <= lat <= 52.5 and 20.5 <= lon <= 21.5:
        return "Warsaw"

    # Country-level fallback based on rough coordinate ranges
    elif 44.0 <= lat <= 48.5 and 20.0 <= lon <= 30.0:
        return "Romania"
    elif 44.0 <= lat <= 52.5 and 22.0 <= lon <= 40.5:
        return "Ukraine"
    elif 47.0 <= lat <= 55.0 and 5.5 <= lon <= 15.5:
        return "Germany"
    elif 49.0 <= lat <= 55.0 and 14.0 <= lon <= 24.5:
        return "Poland"

    return "Unknown Region"

def generate_smart_name(gpx_path: Path, stats: Dict, trail_type: str) -> Optional[Dict[str, str]]:
    """Generate smart name based on location and trail characteristics"""
    try:
        # Get start coordinates
        pts = parse_gpx_points(gpx_path, include_elevation=False)
        if not pts:
            return None
        
        start_lat, start_lon = pts[0]
        
        # Simple location-based naming (without external API to avoid rate limits)
        region = detect_region_from_coords(start_lat, start_lon)
        
        length_km = stats.get("total_distance", 0) / 1000
        
        # Get trail type names from constants
        type_name = TRAIL_TYPE_NAMES.get(trail_type, TRAIL_TYPE_NAMES["trail"])
        
        return {
            "ru": f"{type_name['ru']} {region} {length_km:.1f} км",
            "ro": f"{type_name['ro']} {region} {length_km:.1f} km",
            "uk": f"{type_name['uk']} {region} {length_km:.1f} км",
            "en": f"{type_name['en']} {region} {length_km:.1f} km"
        }
    except Exception:
        return None

def determine_trail_type(gpx_path: Path, stats: Dict[str, float], difficulty: str = "green") -> str:
    """
    Determine trail type from OSM tags, characteristics, AND difficulty.
    Black/Red trails should never be classified as XC.
    """
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        
        # Extract OSM tags from extensions
        osm_tags = {}
        for ext in root.findall('.//{*}extensions'):
            for child in ext:
                # Extract tag name (remove namespace)
                tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if child.text:
                    osm_tags[tag_name] = child.text
        
        # Check mtb:scale (most reliable)
        if 'mtb:scale' in osm_tags:
            try:
                scale = int(osm_tags['mtb:scale'])
                if scale >= 4:
                    return "dh"
                elif scale >= 2:
                    return "enduro"
                elif scale >= 1:
                    return "trail"
                else:
                    return "xc"
            except ValueError:
                pass
        
        # Check highway type
        if 'highway' in osm_tags:
            highway = osm_tags['highway']
            if highway == 'path':
                # Paths with difficulty should not be XC
                if difficulty in ["black", "red"]:
                    return "enduro"
                elif difficulty == "blue":
                    return "trail"
        
        # Fallback to gradient-based detection
        if not stats.get("has_elevation", False):
            # No elevation data, but check difficulty
            if difficulty == "black":
                return "dh"  # Black without elevation = assume DH
            elif difficulty == "red":
                return "enduro"
            else:
                return "trail"
        
        avg_gradient = stats.get("avg_gradient", 0)
        elevation_loss = stats.get("elevation_loss", 0)
        elevation_gain = stats.get("elevation_gain", 0)
        
        # Priority 1: Check if primarily downhill (DH indicator)
        if elevation_loss > elevation_gain * 1.5 and elevation_loss > 100:
            return "dh"
        
        # Priority 2: Difficulty-based classification
        # Black difficulty should NEVER be XC
        if difficulty == "black":
            if avg_gradient > 15 or elevation_loss > 200:
                return "dh"
            else:
                return "enduro"
        
        # Red difficulty should be at least trail/enduro
        if difficulty == "red":
            if avg_gradient > 12:
                return "enduro"
            else:
                return "trail"
        
        # Blue/Green can be XC or trail
        if avg_gradient > 8:
            return "trail"
        elif avg_gradient > 5:
            return "trail"
        else:
            return "xc"
    except Exception:
        return "xc"

def extract_surface_type(gpx_path: Path) -> Optional[str]:
    """Extract surface type from OSM tags"""
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        
        for ext in root.findall('.//{*}extensions'):
            surface_elem = ext.find('.//{*}surface')
            if surface_elem is not None and surface_elem.text:
                return surface_elem.text
        
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
        time.sleep(0.05)  # Reduced delay for better performance
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
            # If translation is available and successful, use it; otherwise use source
            result[lang] = translated if TRANSLATOR_AVAILABLE and translated else source_text
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

    # Handle name - smart generation with priority order
       prev_name = prev.get("name")
    needs_new_name = True

    if isinstance(prev_name, dict):
        has_existing = any(v for v in prev_name.values() if v)
        if has_existing and not is_filename_based_name(prev_name, tid):
            # Существующее человекоподобное имя — сохраняем!
            needs_new_name = False
            name = {}
            for lang in LANGS:
                if lang in prev_name and prev_name[lang]:
                    name[lang] = prev_name[lang]
                else:
                    name[lang] = prev_name.get("ru") or next((v for v in prev_name.values() if v), tid)

    if needs_new_name:
        # дальше обычная логика — ищем имя в GPX, потом в OSM, потом генерим умное, потом случайное
        gpx_name = None
        if gpx_path and gpx_path.exists():
            gpx_name = get_gpx_track_name(gpx_path)

        if gpx_name:
            name = auto_translate_i18n(gpx_name, "ru")
        else:
            osm_name = extract_osm_name(gpx_path) if gpx_path else None

            if osm_name:
                name = auto_translate_i18n(osm_name, "en")
            elif is_unverified and stats.get("total_distance", 0) > 0:
                trail_type = determine_trail_type(gpx_path, stats, difficulty) if gpx_path else "xc"
                smart_name = generate_smart_name(gpx_path, stats, trail_type)

                if smart_name:
                    name = smart_name
                else:
                    random_name = random.choice(RANDOM_TRAIL_NAMES)
                    name = auto_translate_i18n(random_name, "en")
            else:
                random_name = random.choice(RANDOM_TRAIL_NAMES)
                name = auto_translate_i18n(random_name, "en")

    needs_new_name = True

    if isinstance(prev_name, dict):
        has_existing = any(v for v in prev_name.values() if v)
        if has_existing and not is_filename_based_name(prev_name, tid):
            # Real existing name - keep it
            needs_new_name = False
            name = {}
            for lang in LANGS:
                if lang in prev_name and prev_name[lang]:
                    name[lang] = prev_name[lang]
                else:
                    name[lang] = prev_name.get("ru") or next((v for v in prev_name.values() if v), tid)

    if needs_new_name:
        # Priority 1: Try GPX <name> tag
        gpx_name = None
        if gpx_path and gpx_path.exists():
            gpx_name = get_gpx_track_name(gpx_path)

        if gpx_name:
            name = auto_translate_i18n(gpx_name, "ru")
        else:
            # Priority 2: Try OSM ref
            osm_name = extract_osm_name(gpx_path) if gpx_path else None

            if osm_name:
                name = auto_translate_i18n(osm_name, "en")
            elif is_unverified and stats.get("total_distance", 0) > 0:
                # Priority 3: Generate smart name from geolocation + characteristics
                trail_type = determine_trail_type(gpx_path, stats, difficulty) if gpx_path else "xc"
                smart_name = generate_smart_name(gpx_path, stats, trail_type)

                if smart_name:
                    name = smart_name
                else:
                    # Priority 4: Fallback to random name
                    random_name = random.choice(RANDOM_TRAIL_NAMES)
                    name = auto_translate_i18n(random_name, "en")
            else:
                # Fallback to random name
                random_name = random.choice(RANDOM_TRAIL_NAMES)
                name = auto_translate_i18n(random_name, "en")
    
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
    
    # Handle description - enhanced generation
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
            # Auto-generate enhanced description for unverified trails
            trail_type = determine_trail_type(gpx_path, stats, difficulty) if gpx_path else "xc"
            desc_text = generate_description(gpx_path, stats, difficulty, country_id, trail_type)
            desc = auto_translate_i18n(desc_text, "ru")
        else:
            desc = default_i18n("")
    elif is_unverified and country_id:
        # Auto-generate enhanced description for unverified trails
        trail_type = determine_trail_type(gpx_path, stats, difficulty) if gpx_path else "xc"
        desc_text = generate_description(gpx_path, stats, difficulty, country_id, trail_type)
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
            folder_name = COUNTRY_CODE_TO_FOLDER.get(country_code, f"gpx_{country_code}")
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
            folder_name = COUNTRY_CODE_TO_FOLDER.get(country_code, f"gpx_{country_code}")
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
