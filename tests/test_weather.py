"""天气：WMO 文案 / 预报解析 / 规则建议（纯函数）+ /weather 端点（geocode/forecast 打桩，离线）。"""
from __future__ import annotations

import httpx
from httpx import ASGITransport

from core import weather
from server.app import create_app

_DAILY = {
    "daily": {
        "time": ["2026-06-17", "2026-06-18"],
        "weather_code": [0, 61],
        "temperature_2m_max": [26, 19],
        "temperature_2m_min": [18, 14],
        "precipitation_probability_max": [10, 80],
    }
}


def test_code_text():
    assert weather.code_text(0) == "晴"
    assert weather.code_text(61) == "小雨"
    assert weather.code_text(None) == "未知"
    assert weather.code_text(12345) == "未知"


def test_parse_forecast():
    days = weather.parse_forecast(_DAILY)
    assert days["today"]["text"] == "晴" and days["today"]["tmax"] == 26
    assert days["tomorrow"]["text"] == "小雨" and days["tomorrow"]["precip_prob"] == 80
    # 数据不足时明天为 None
    one = weather.parse_forecast({"daily": {"time": ["2026-06-17"], "weather_code": [0]}})
    assert one["tomorrow"] is None


def test_advise_rain_and_cooldown():
    days = weather.parse_forecast(_DAILY)
    msg = weather.advise(days["today"], days["tomorrow"])
    assert "带伞" in msg and "降温" in msg  # 明天小雨 + 较今天降温 7°


def test_advise_variants():
    snow = {"code": 73, "tmax": 0, "tmin": -5, "precip_prob": 90}
    assert "防滑" in weather.advise(None, snow)
    hot = {"code": 0, "tmax": 35, "tmin": 27, "precip_prob": 0}
    assert "防晒" in weather.advise(None, hot)
    calm = {"code": 1, "tmax": 22, "tmin": 16, "precip_prob": 5}
    assert "平稳" in weather.advise(None, calm)
    assert "数据" in weather.advise(None, None)


async def test_get_weather_geocodes_then_forecasts(monkeypatch):
    async def fake_geocode(name):
        return {"lat": 39.9, "lon": 116.4, "label": f"{name} · 北京 · 中国"}

    async def fake_forecast(lat, lon):
        return _DAILY

    monkeypatch.setattr(weather, "geocode_city", fake_geocode)
    monkeypatch.setattr(weather, "fetch_forecast", fake_forecast)
    w = await weather.get_weather(city="北京")
    assert w["ok"] and w["lat"] == 39.9 and "北京" in w["label"]
    assert w["today"]["text"] == "晴" and w["tomorrow"]["text"] == "小雨"


async def test_get_weather_no_city():
    w = await weather.get_weather(city="")
    assert not w["ok"] and w["reason"] == "no_city"


async def test_weather_endpoint_caches_coords(tmp_path, monkeypatch):
    async def fake_geocode(name):
        return {"lat": 31.2, "lon": 121.5, "label": "上海 · 中国"}

    async def fake_forecast(lat, lon):
        return _DAILY

    monkeypatch.setattr(weather, "geocode_city", fake_geocode)
    monkeypatch.setattr(weather, "fetch_forecast", fake_forecast)
    app = create_app(provider=object(), db_path=str(tmp_path / "db"), data_dir=str(tmp_path / "d"))
    app.state.settings.update(weather_city="上海")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        w = (await c.get("/weather")).json()
        assert w["ok"] and w["tomorrow"]["precip_prob"] == 80
    # 经纬度已缓存进 settings（下次不再 geocode）
    s = app.state.settings.get()
    assert s["weather_lat"] == 31.2 and s["weather_label"] == "上海 · 中国"
