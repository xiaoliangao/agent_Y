"""天气：手动城市 → Open-Meteo 地理编码 → 今天/明天预报 + 规则化穿衣/出行建议。

用免费、无需 API key 的 Open-Meteo（geocoding + forecast）。隐私优先：只查用户在设置里
手动填的城市，不做 IP 定位。解析与建议是纯函数（可离线测试），联网仅 geocode/forecast 两步。
"""
from __future__ import annotations

from typing import Any

import httpx

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 12

# WMO weather code → 中文（Open-Meteo daily.weather_code）
_WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}
_RAIN = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_SNOW = {71, 73, 75, 77, 85, 86}


def code_text(code: int | None) -> str:
    return _WMO.get(int(code), "未知") if code is not None else "未知"


def _day(data: dict, i: int) -> dict | None:
    """从 forecast 的 daily 数组取第 i 天（0=今天,1=明天）。"""
    daily = (data or {}).get("daily") or {}
    times = daily.get("time") or []
    if i >= len(times):
        return None
    code = (daily.get("weather_code") or [None] * len(times))[i]
    return {
        "date": times[i],
        "code": code,
        "text": code_text(code),
        "tmax": (daily.get("temperature_2m_max") or [None] * len(times))[i],
        "tmin": (daily.get("temperature_2m_min") or [None] * len(times))[i],
        "precip_prob": (daily.get("precipitation_probability_max") or [None] * len(times))[i],
    }


def parse_forecast(data: dict) -> dict:
    """forecast JSON → {today, tomorrow}（任一天缺失则为 None）。"""
    return {"today": _day(data, 0), "tomorrow": _day(data, 1)}


def parse_current(data: dict) -> dict | None:
    """当前实况（温度/体感/湿度/风/天气）。"""
    c = (data or {}).get("current") or {}
    if not c:
        return None
    return {
        "temp": c.get("temperature_2m"), "feels": c.get("apparent_temperature"),
        "humidity": c.get("relative_humidity_2m"), "wind": c.get("wind_speed_10m"),
        "code": c.get("weather_code"), "text": code_text(c.get("weather_code")),
    }


def parse_hourly(data: dict, n: int = 6) -> list[dict]:
    """从当前时刻起的 n 个逐时点 [{time(HH:MM), temp, code, text}]。"""
    h = (data or {}).get("hourly") or {}
    times = h.get("time") or []
    temps = h.get("temperature_2m") or []
    codes = h.get("weather_code") or []
    cur = ((data or {}).get("current") or {}).get("time")
    start = 0
    if cur:
        for i, t in enumerate(times):
            if t >= cur:
                start = i
                break
    out: list[dict] = []
    for i in range(start, min(start + n, len(times))):
        code = codes[i] if i < len(codes) else None
        out.append({
            "time": times[i][11:16], "temp": temps[i] if i < len(temps) else None,
            "code": code, "text": code_text(code),
        })
    return out


def advise(today: dict | None, tomorrow: dict | None) -> str:
    """据明天预报给一句简短建议（带伞/添衣/防晒…）。无明天数据则退回今天。"""
    ref = tomorrow or today
    if not ref:
        return "暂无足够数据给出建议。"
    cues: list[str] = []
    code = ref.get("code")
    prob = ref.get("precip_prob") or 0
    if code in _SNOW:
        cues.append("有雪，注意保暖防滑")
    elif code in _RAIN or prob >= 50:
        cues.append("可能有雨，记得带伞")
    # 与今天比较的温差（仅当两天都有 tmax）
    if today and tomorrow and today.get("tmax") is not None and tomorrow.get("tmax") is not None:
        d = tomorrow["tmax"] - today["tmax"]
        if d <= -5:
            cues.append(f"较今天降温约 {round(-d)}°，记得添衣")
        elif d >= 5:
            cues.append(f"较今天升温约 {round(d)}°")
    tmax, tmin = ref.get("tmax"), ref.get("tmin")
    if tmax is not None and tmax >= 32:
        cues.append("天气炎热，注意防晒补水")
    elif tmin is not None and tmin <= 3:
        cues.append("天气较冷，注意保暖")
    when = "明天" if tomorrow else "今天"
    return f"{when}{('，'.join(cues))}。" if cues else f"{when}天气平稳，安排照常。"


async def geocode_city(name: str) -> dict | None:
    """城市名 → {lat, lon, label}（取首个匹配）。失败返回 None。"""
    if not name.strip():
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(_GEOCODE, params={"name": name, "count": 1, "language": "zh", "format": "json"})
        results = (r.json() or {}).get("results") or []
    if not results:
        return None
    top = results[0]
    parts = [top.get("name"), top.get("admin1"), top.get("country")]
    label = " · ".join(p for p in parts if p)
    return {"lat": top["latitude"], "lon": top["longitude"], "label": label}


async def fetch_forecast(lat: float, lon: float) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(_FORECAST, params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,weather_code",
        })
        return r.json() or {}


async def get_weather(*, city: str = "", lat: Any = None, lon: Any = None, label: str = "") -> dict:
    """汇总：必要时先 geocode（返回值含 resolved 经纬度供调用方缓存），再取预报 + 建议。

    返回 {ok, label, lat, lon, today, tomorrow, advice}；未配城市/查不到/网络失败时 ok=False + reason。
    """
    if lat is None or lon is None:
        if not city.strip():
            return {"ok": False, "reason": "no_city"}
        geo = await geocode_city(city)
        if not geo:
            return {"ok": False, "reason": "geocode_failed"}
        lat, lon, label = geo["lat"], geo["lon"], geo["label"]
    data = await fetch_forecast(float(lat), float(lon))
    days = parse_forecast(data)
    return {
        "ok": True, "label": label or city, "lat": lat, "lon": lon,
        "today": days["today"], "tomorrow": days["tomorrow"],
        "current": parse_current(data), "hourly": parse_hourly(data),
        "advice": advise(days["today"], days["tomorrow"]),
    }
