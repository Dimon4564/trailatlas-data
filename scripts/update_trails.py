import hashlib

DIFFICULTIES = ["green", "blue", "red", "black"]

def stable_random_difficulty(trail_id: str) -> str:
    # "рандом", но стабильный: один и тот же id -> одна и та же сложность
    h = hashlib.md5(trail_id.encode("utf-8")).hexdigest()
    n = int(h[:8], 16)
    return DIFFICULTIES[n % len(DIFFICULTIES)]

def build_trail_object(prev: dict, tid: str, gpx_url: str, start_lat: float | None, start_lon: float | None):
    # 1) cityId всегда Chisinau (как ты попросил)
    city_id = "chisinau"

    # 2) difficulty: если ты уже выставил руками — сохраняем,
    # иначе ставим "рандом", но стабильный
    prev_diff = prev.get("difficulty", "")
    if isinstance(prev_diff, str) and prev_diff.strip() in DIFFICULTIES:
        difficulty = prev_diff.strip()
    else:
        difficulty = stable_random_difficulty(tid)

    # styles оставляем как было (или пусто)
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

    # сохранить любые доп.поля, которые у тебя могли быть в prev
    owned = set(obj.keys())
    for k, v in prev.items():
        if k not in owned:
            obj[k] = v

    return obj
