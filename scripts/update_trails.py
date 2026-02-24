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

def is_technical_name(name_str: str, trail_id: str) -> bool:
    """
    Возвращает True, если имя техническое и его нужно заменить 
    (например, ua_003, ukraine1_trail, Track 1 и т.д.).
    """
    if not name_str:
        return True
    
    text = str(name_str).lower().strip()
    
    base_id = re.sub(r'_\d+$', '', trail_id.lower())
    
    if text in [
        trail_id.lower(),
        base_id,
        f"{trail_id.lower()}_trail",
        f"{trail_id.lower()} trail",
        f"{base_id}_trail",
        f"{base_id} trail",
        "unnamed",
        "ukraine1_trail",
        "ukraine1 trail"
    ]:
        return True
        
    if re.match(r"^[a-z]{2}_\d+.*", text):
        return True
        
    if re.match(r"^(track|route|path|trail)\s*\d*$", text):
        return True
        
    if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", text):
        return True
        
    return False

DIFFICULTIES = ["green", "blue", "red", "black"]

COUNTRY_FOLDERS = {
    "gpx_romania": "ro",
    "gpx_germany": "de",
    "gpx_poland": "pl",
    "gpx_ukraine": "ua",
}

COUNTRY_CODE_TO_FOLDER = {v: k for k, v in COUNTRY_FOLDERS.items()}

RANDOM_TRAIL_NAMES = [
    "Hidden Valley Trail", "Sunset Ridge Path", "Eagle's Nest Loop", "Wildflower Meadow Trail",
    "Silver Creek Route", "Thunder Peak Trail", "Misty Mountain Path", "Golden Oak Loop",
    "Falcon Ridge Trail", "Pinecone Valley Route", "Stony Brook Path", "Crimson Ridge Trail",
    "Whispering Pines Loop", "Bear Creek Trail", "Moonlit Ridge Path", "Cedar Canyon Route",
    "Maple Hollow Trail", "Rocky Summit Path", "Deer Crossing Loop", "Sapphire Lake Trail",
    "Timber Wolf Path", "Copper Creek Route", "Birchwood Trail", "Aspen Grove Loop",
    "Coyote Ridge Trail", "Crystal Springs Path", "Shadow Canyon Route", "Ironwood Trail",
    "Fox Meadow Loop", "Granite Peak Path", "Lone Pine Trail", "Rushing Waters Route",
    "Amber Hillside Path", "Ravine Ridge Loop",
]

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

SURFACE_DESCRIPTIONS = {
    "dirt": "грунтовое покрытие",
    "gravel": "гравийное покрытие",
    "paved": "асфальтированная поверхность",
    "ground": "естественное покрытие"
}

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
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name)
    name = name.lower().strip('_')
    return name if name else "unnamed"

def convert_route_to_track(rte_elem, ns: str):
    def q(tag): return f"{{{ns}}}{tag}" if ns else tag
    trk = ET.Element(q("trk"))
    
    name_elem = rte_elem.find(q("name"))
    if name_elem is not None:
        new_name = ET.SubElement(trk, q("name"))
        new_name.text = name_elem.text
    
    for child in rte_elem:
        if child.tag in [q("name"), q("rtept")]:
            continue 
        trk.append(deepcopy(child))
    
    trkseg = ET.SubElement(trk, q("trkseg"))
    for rtept in rte_elem.findall(q("rtept")):
        trkpt = ET.SubElement(trkseg, q("trkpt"), rtept.attrib)
        for child in rtept:
            trkpt.append(deepcopy(child))
    return trk

def should_process_track(trk_elem, gpx_root, ns: str) -> Tuple[bool, str]:
    def q(tag): return f"{{{ns}}}{tag}" if ns else tag
    
    name_elem = trk_elem.find(q("name"))
    has_name = name_elem is not None and name_elem.text and name_elem.text.strip()
    
    temp_root = ET.Element(gpx_root.tag, gpx_root.attrib)
    temp_root.append(deepcopy(trk_elem))
    temp_tree = ET.ElementTree(temp_root)
    
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gpx', delete=False) as f:
            temp_file_name = f.name
        temp_path = Path(temp_file_name)
        temp_tree.write(temp_path, encoding='utf-8', xml_declaration=True)
        
        pts = parse_gpx_points(temp_path, include_elevation=True)
        if not has_name and len(pts) < 10:
            return (False, f"too few points ({len(pts)})")
        
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
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        
        m = re.match(r"\{(.+)\}", root.tag)
        ns = m.group(1) if m else ""
        def q(tag): return f"{{{ns}}}{tag}" if ns else tag
        
        tracks = root.findall(q("trk"))
        routes = root.findall(q("rte"))
        
        total_elements = len(tracks) + len(routes)
        if total_elements <= 1:
            return []
        
        created_files = []
        parent_dir = gpx_path.parent
        
        for idx, trk in enumerate(tracks, 1):
            should_process, skip_reason = should_process_track(trk, root, ns)
            if not should_process:
                continue
            
            name_elem = trk.find(q("name"))
            if name_elem is not None and name_elem.text:
                track_name = sanitize_filename(name_elem.text)
                new_filename = f"{track_name}.gpx"
            else:
                new_filename = f"{country_code}_{idx:03d}.gpx"
            
            new_path = parent_dir / new_filename
            counter = 1
            while new_path.exists():
                stem = new_filename.rsplit('.', 1)[0]
                new_path = parent_dir / f"{stem}_{counter}.gpx"
                counter += 1
            
            new_root = ET.Element(root.tag, root.attrib)
            metadata = root.find(q("metadata"))
            if metadata is not None:
                new_root.append(deepcopy(metadata))
            new_root.append(trk)
            
            new_tree = ET.ElementTree(new_root)
            ET.indent(new_tree, space="  ")
            new_tree.write(new_path, encoding="utf-8", xml_declaration=True)
            created_files.append(new_path)
        
        for idx, rte in enumerate(routes, len(tracks) + 1):
            trk = convert_route_to_track(rte, ns)
            should_process, skip_reason = should_process_track(trk, root, ns)
            if not should_process:
                continue
            
            name_elem = rte.find(q("name"))
            if name_elem is not None and name_elem.text:
                route_name = sanitize_filename(name_elem.text)
                new_filename = f"{route_name}.gpx"
            else:
                new_filename = f"{country_code}_{idx:03d}.gpx"
            
            new_path = parent_dir / new_filename
            counter = 1
            while new_path.exists():
                stem = new_filename.rsplit('.', 1)[0]
                new_path = parent_dir / f"{stem}_{counter}.gpx"
                counter += 1
            
            new_root = ET.Element(root.tag, root.attrib)
            metadata = root.find(q("metadata"))
            if metadata is not None:
                new_root.append(deepcopy(metadata))
            new_root.append(trk)
            
            new_tree = ET.ElementTree(new_root)
            ET.indent(new_tree, space="  ")
            new_tree.write(new_path, encoding="utf-8", xml_declaration=True)
            created_files.append(new_path)
        
        gpx_path.unlink()
        return created_files
    except Exception as e:
        print(f"Error splitting {gpx_path}: {e}")
        return []

def calculate_elevation_stats(points: List[Tuple[float, float, Optional[float]]]) -> Dict[str, float]:
    if not points:
        return {"elevation_gain": 0, "elevation_loss": 0, "avg_gradient": 0, "total_distance": 0, "has_elevation": False}
    
    points_with_ele = [(lat, lon, ele) for lat, lon, ele in points if ele is not None]
    
    total_distance = 0
    for i in range(1, len(points)):
        prev_lat, prev_lon = points[i-1][0], points[i-1][1]
        curr_lat, curr_lon = points[i][0], points[i][1]
        
        lat1, lon1 = math.radians(prev_lat), math.radians(prev_lon)
        lat2, lon2 = math.radians(curr_lat), math.radians(curr_lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        distance = 6371000 * c
        total_distance += distance
    
    if len(points_with_ele) < 2:
        return {"elevation_gain": 0, "elevation_loss": 0, "avg_gradient": 0, "total_distance": total_distance, "has_elevation": False}
    
    elevation_gain = 0
    elevation_loss = 0
    
    for i in range(1, len(points_with_ele)):
        prev_ele = points_with_ele[i-1][2]
        curr_ele = points_with_ele[i][2]
        
        ele_change = curr_ele - prev_ele
        if ele_change > 0:
            elevation_gain += ele_change
        else:
            elevation_loss += abs(ele_change)
    
    avg_gradient = 0
    if total_distance > 0:
        net_elevation = elevation_gain - elevation_loss
        avg_gradient = (net_elevation / total_distance) * 100
    
    return {
        "elevation_gain": elevation_gain,
        "elevation_loss": elevation_loss,
        "avg_gradient": abs(avg_gradient),
        "total_distance": total_distance,
        "has_elevation": True
    }

def determine_difficulty_from_elevation(stats: Dict[str, float], trail_id: str) -> str:
    if not stats.get("has_elevation", False):
        return stable_random_difficulty(trail_id)
    
    avg_gradient = stats.get("avg_gradient", 0)
    if avg_gradient < 5: return "green"
    elif avg_gradient < 10: return "blue"
    elif avg_gradient < 15: return "red"
    else: return "black"

def detect_trail_styles(stats: Dict[str, float], points: List) -> List[str]:
    if not stats.get("has_elevation", False): return ["MTB"]
    elevation_loss = stats.get("elevation_loss", 0)
    elevation_gain = stats.get("elevation_gain", 0)
    if elevation_loss > elevation_gain * 2 and elevation_loss > 50:
        return ["MTB", "DH"]
    return ["MTB"]

def generate_suitable_text(difficulty: str, styles: List[str]) -> str:
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
    if (difficulty, styles_tuple) in style_map:
        return style_map[(difficulty, styles_tuple)]
    
    if difficulty == "green": return "Cross Country / All Mountain"
    elif difficulty == "blue": return "All Mountain / Cross Country"
    elif difficulty == "red": return "All Mountain / Enduro"
    else: return "Downhill / Freeride"

def generate_description(gpx_path: Path, stats: Dict[str, float], difficulty: str, 
                        country_code: str, trail_type: str) -> str:
    distance_km = stats.get("total_distance", 0) / 1000
    elevation_gain = stats.get("elevation_gain", 0)
    elevation_loss = stats.get("elevation_loss", 0)
    surface = extract_surface_type(gpx_path) if gpx_path else None
    parts = []
    
    if stats.get("has_elevation", False):
        if elevation_loss > elevation_gain * 1.2:
            parts.append(f"Трейл протяженностью {distance_km:.1f} км с перепадом высоты {elevation_loss:.0f} м")
        else:
            parts.append(f"Трейл протяженностью {distance_km:.1f} км с набором высоты {elevation_gain:.0f} м")
    else:
        parts.append(f"Трейл протяженностью {distance_km:.1f} км")
    
    if trail_type in TRAIL_TYPE_DESCRIPTIONS and difficulty in TRAIL_TYPE_DESCRIPTIONS[trail_type]:
        parts.append(TRAIL_TYPE_DESCRIPTIONS[trail_type][difficulty])
    else:
        parts.append("Горный велосипедный трейл")
    
    if surface and surface in SURFACE_DESCRIPTIONS:
        parts.append(f"Покрытие: {SURFACE_DESCRIPTIONS[surface]}")
    
    if difficulty in DIFFICULTY_DESCRIPTIONS:
        parts.append(DIFFICULTY_DESCRIPTIONS[difficulty])
    
    return ". ".join(parts) + "."

def stable_random_difficulty(trail_id: str) -> str:
    h = hashlib.md5(trail_id.encode("utf-8")).hexdigest()
    return DIFFICULTIES[int(h[:8], 16) % len(DIFFICULTIES)]

def parse_gpx_points(gpx_path: Path, include_elevation: bool = True):
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
                if lat is None or lon is None: continue
                
                if include_elevation:
                    ele_elem = pt.find(q("ele"))
                    ele = safe_float(ele_elem.text) if ele_elem is not None else None
                    pts.append((lat, lon, ele))
                else:
                    pts.append((lat, lon))

    if not pts:
        for rte in root.findall(q("rte")):
            for pt in rte.findall(q("rtept")):
                lat = safe_float(pt.attrib.get("lat"))
                lon = safe_float(pt.attrib.get("lon"))
                if lat is None or lon is None: continue
                
                if include_elevation:
                    ele_elem = pt.find(q("ele"))
                    ele = safe_float(ele_elem.text) if ele_elem is not None else None
                    pts.append((lat, lon, ele))
                else:
                    pts.append((lat, lon))
    return pts

def get_gpx_track_name(gpx_path: Path) -> Optional[str]:
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        m = re.match(r"\{(.+)\}", root.tag)
        ns = m.group(1) if m else ""
        def q(tag): return f"{{{ns}}}{tag}" if ns else tag
        
        for trk in root.findall(q("trk")):
            name_elem = trk.find(q("name"))
            if name_elem is not None and name_elem.text: return name_elem.text
        for rte in root.findall(q("rte")):
            name_elem = rte.find(q("name"))
            if name_elem is not None and name_elem.text: return name_elem.text
        metadata = root.find(q("metadata"))
        if metadata is not None:
            name_elem = metadata.find(q("name"))
            if name_elem is not None and name_elem.text: return name_elem.text
        return None
    except Exception:
        return None

def extract_osm_name(gpx_path: Path) -> Optional[str]:
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
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

def determine_trail_type(gpx_path: Path, stats: Dict[str, float], difficulty: str = "green") -> str:
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        osm_tags = {}
        for ext in root.findall('.//{*}extensions'):
            for child in ext:
                tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if child.text: osm_tags[tag_name] = child.text
        
        if 'mtb:scale' in osm_tags:
            try:
                scale = int(osm_tags['mtb:scale'])
                if scale >= 4: return "dh"
                elif scale >= 2: return "enduro"
                elif scale >= 1: return "trail"
                else: return "xc"
            except ValueError:
                pass
        
        if 'highway' in osm_tags:
            highway = osm_tags['highway']
            if highway == 'path':
                if difficulty in ["black", "red"]: return "enduro"
                elif difficulty == "blue": return "trail"
        
        if not stats.get("has_elevation", False):
            if difficulty == "black": return "dh"
            elif difficulty == "red": return "enduro"
            else: return "trail"
        
        avg_gradient = stats.get("avg_gradient", 0)
        elevation_loss = stats.get("elevation_loss", 0)
        elevation_gain = stats.get("elevation_gain", 0)
        
        if elevation_loss > elevation_gain * 1.5 and elevation_loss > 100: return "dh"
        if difficulty == "black": return "dh" if avg_gradient > 15 or elevation_loss > 200 else "enduro"
        if difficulty == "red": return "enduro" if avg_gradient > 12 else "trail"
        if avg_gradient > 5: return "trail"
        return "xc"
    except Exception:
        return "xc"

def extract_surface_type(gpx_path: Path) -> Optional[str]:
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
        for ext in root.findall('.//{*}extensions'):
            surface_elem = ext.find('.//{*}surface')
            if surface_elem is not None and surface_elem.text: return surface_elem.text
        return None
    except Exception:
        return None

def preprocess_split_multi_track_gpx(gpx_dir: Path):
    if not gpx_dir.exists(): return
    for folder_name, country_code in COUNTRY_FOLDERS.items():
        folder_path = gpx_dir / folder_name
        if not folder_path.exists(): continue
        gpx_files = sorted([p for p in folder_path.glob("*.gpx") if p.is_file()])
        for gpx_file in gpx_files:
            split_multi_track_gpx(gpx_file, country_code)

def load_root(path: Path):
    if not path.exists(): return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_root(path: Path, root_obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(root_obj, f, ensure_ascii=False, indent=2)
        f.write("\n")

def translate_text(text: str, target_lang: str) -> str:
    if not TRANSLATOR_AVAILABLE or not text or not text.strip(): return text
    try:
        lang_map = {"ru": "ru", "ro": "ro", "uk": "uk", "en": "en"}
        target = lang_map.get(target_lang, target_lang)
        translator = GoogleTranslator(source='auto', target=target)
        result = translator.translate(text)
        time.sleep(0.05)
        return result if result else text
    except Exception:
        return text

def auto_translate_i18n(source_text: str, source_lang: str = "ru") -> Dict[str, str]:
    result = {}
    for lang in LANGS:
        if lang == source_lang:
            result[lang] = source_text
        else:
            translated = translate_text(source_text, lang)
            result[lang] = translated if TRANSLATOR_AVAILABLE and translated else source_text
    return result

def default_i18n(text: str):
    """Возвращает словарь со всеми языками, заполненными одним текстом"""
    return {k: text for k in LANGS}

def roots_equal(a, b):
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


# ------------------ main trail builder ------------------
def build_trail_object(prev: dict, tid: str, gpx_url: str, start_lat, start_lon, 
                       gpx_path: Path = None, country_id: str = None, 
                       is_unverified: bool = False):
    """
    Генерирует объект трейла с нуля (вызывается ТОЛЬКО для новых файлов).
    """

    stats = {"has_elevation": False}
    pts_with_ele = []
    if gpx_path and gpx_path.exists():
        pts_with_ele = parse_gpx_points(gpx_path, include_elevation=True)
        if pts_with_ele:
            stats = calculate_elevation_stats(pts_with_ele)
    
    if is_unverified and stats.get("has_elevation", False):
        difficulty = determine_difficulty_from_elevation(stats, tid)
    else:
        difficulty = stable_random_difficulty(tid)

    if is_unverified and stats.get("has_elevation", False):
        styles = detect_trail_styles(stats, pts_with_ele)
    else:
        styles = []

    # Генерация имени (ищем в GPX или OSM, иначе случайное. Никаких упоминаний стран!)
    final_name = None
    if gpx_path and gpx_path.exists():
        raw_gpx_name = get_gpx_track_name(gpx_path)
        if raw_gpx_name and not is_technical_name(raw_gpx_name, tid):
            final_name = raw_gpx_name
            
    if not final_name:
        if gpx_path and gpx_path.exists():
            raw_osm = extract_osm_name(gpx_path)
            if raw_osm and not is_technical_name(raw_osm, tid):
                final_name = raw_osm
                
    if not final_name:
        final_name = random.choice(RANDOM_TRAIL_NAMES)

    # Заполняем ВСЕ языки (ru, ro, uk, en) ОДНИМ английским текстом (именем трейла)
    name = default_i18n(final_name)
            
    # Подходящие стили катания (заполняем ВСЕ языки (ru, ro, uk, en) ОДНИМ английским текстом)
    if is_unverified:
        suitable_text = generate_suitable_text(difficulty, styles)
        suitable = default_i18n(suitable_text)
    else:
        suitable = default_i18n("")
    
    # Описание (оставили с нормальным переводом)
    if is_unverified and country_id:
        trail_type = determine_trail_type(gpx_path, stats, difficulty) if gpx_path else "xc"
        desc_text = generate_description(gpx_path, stats, difficulty, country_id, trail_type)
        desc = auto_translate_i18n(desc_text, "ru")
    else:
        desc = default_i18n("")

    # Собираем объект (без cityId)
    obj = {
        "id": tid,
        "styles": styles,
        "name": name,
        "suitable": suitable,
        "difficulty": difficulty,
        "desc": desc,
        "gpxUrl": gpx_url,
        "startLat": start_lat,
        "startLon": start_lon,
    }
    
    if country_id:
        obj["countryId"] = country_id

    return obj

def upsert_file(gpx_dir: Path, json_path: Path, gpx_folder_name: str, raw_base: str, 
                default_version: int, is_unverified: bool = False):
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

    all_gpx_files = []
    
    if gpx_dir.exists():
        root_gpx = sorted([p for p in gpx_dir.glob("*.gpx") if p.is_file()])
        all_gpx_files.extend([(p, None) for p in root_gpx])
    
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

    # 1. СНАЧАЛА ОБРАБАТЫВАЕМ СУЩЕСТВУЮЩИЕ ТРЕЙЛЫ (ЧТОБЫ НЕ ТРОГАТЬ ИХ)
    for tid in order:
        if tid not in file_by_id:
            continue
        
        p, country_code = file_by_id[tid]
        
        existing_trail = deepcopy(existing_by_id[tid])
        
        if country_code:
            folder_name = COUNTRY_CODE_TO_FOLDER.get(country_code, f"gpx_{country_code}")
            existing_trail["gpxUrl"] = f"{raw_base}/{gpx_folder_name}/{folder_name}/{p.name}"
        else:
            existing_trail["gpxUrl"] = f"{raw_base}/{gpx_folder_name}/{p.name}"
            
        new_trails.append(existing_trail)

    # 2. ЗАТЕМ ДОБАВЛЯЕМ ТОЛЬКО НОВЫЕ ТРЕЙЛЫ, КОТОРЫХ ЕЩЕ НЕТ В БАЗЕ
    for tid in sorted(file_by_id.keys()):
        if tid in existing_by_id:
            continue
        
        p, country_code = file_by_id[tid]
        pts = parse_gpx_points(p, include_elevation=False)
        start_lat = pts[0][0] if pts else None
        start_lon = pts[0][1] if pts else None
        
        if country_code:
            folder_name = COUNTRY_CODE_TO_FOLDER.get(country_code, f"gpx_{country_code}")
            gpx_url = f"{raw_base}/{gpx_folder_name}/{folder_name}/{p.name}"
        else:
            gpx_url = f"{raw_base}/{gpx_folder_name}/{p.name}"
        
        new_trails.append(build_trail_object(
            {}, tid, gpx_url, start_lat, start_lon,
            gpx_path=p, country_id=country_code, is_unverified=is_unverified
        ))

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

    print("Pre-processing: Checking for multi-track GPX files...")
    preprocess_split_multi_track_gpx(Path(args.unverified_gpx_dir))
    
    print("\nProcessing verified trails...")
    upsert_file(Path(args.verified_gpx_dir), Path(args.verified_json), "gpx", args.raw_base, 
                default_version=10, is_unverified=False)
    
    print("\nProcessing unverified trails...")
    upsert_file(Path(args.unverified_gpx_dir), Path(args.unverified_json), "gpx_unverified", 
                args.raw_base, default_version=1, is_unverified=True)
    
    print("\nDone!")

if __name__ == "__main__":
    main()
