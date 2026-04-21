#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import configparser
import requests
import sqlite3
import socket
import time
from datetime import datetime
from math import radians, cos, sin, asin, sqrt
from PIL import Image, ImageFont, ImageDraw
from inky.auto import auto
from curl_cffi import requests as curl_requests
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# -----------------------------
# LOAD CONFIG
# -----------------------------
_config = configparser.ConfigParser()
_config_path = os.path.join(os.path.dirname(__file__), "fuel.conf")
if not _config.read(_config_path):
    raise FileNotFoundError(
        f"\nConfig file not found: {_config_path}\n"
        f"Copy config.ini to the same directory as this script and try again.\n"
        f"Expected location: {os.path.dirname(os.path.abspath(__file__))}"
    )

POSTCODE = _config.get("location", "postcode")
SEARCH_RADIUS_KM = _config.getfloat("location", "search_radius_km")

ALERT_THRESHOLD_DROP = _config.getfloat("alerts", "threshold_drop")
ALERT_THRESHOLD_RISE = _config.getfloat("alerts", "threshold_rise")

IRC_ENABLED = _config.getboolean("irc", "enabled", fallback=True)
IRC_SERVER = _config.get("irc", "server")
IRC_PORT = _config.getint("irc", "port")
IRC_NICK = _config.get("irc", "nick")
IRC_CHANNEL = _config.get("irc", "channel")

FAST_UPDATE = _config.getboolean("display", "fast_update")
PARTIAL_UPDATE = _config.getboolean("display", "partial_update")

DISCORD_ENABLED = _config.getboolean("discord", "enabled", fallback=False)
DISCORD_WEBHOOK_URL = _config.get("discord", "webhook_url", fallback="")

TELEGRAM_ENABLED = _config.getboolean("telegram", "enabled", fallback=False)
TELEGRAM_BOT_TOKEN = _config.get("telegram", "bot_token", fallback="")
TELEGRAM_CHAT_ID = _config.get("telegram", "chat_id", fallback="")

# -----------------------------
# STATIC CONFIG
# -----------------------------
FONT_SMALL = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

DB_FILE = "fuel_history.db"

# -----------------------------
# RETAILER FEEDS
# -----------------------------
RETAILER_FEEDS = {
    "Asda": "https://storelocator.asda.com/fuel_prices_data.json",
    "Morrisons": "https://www.morrisons.com/fuel-prices/fuel.json",
    "Sainsbury's": "https://api.sainsburys.co.uk/v1/exports/latest/fuel_prices_data.json",
    "BP": "https://www.bp.com/en_gb/united-kingdom/home/fuelprices/fuel_prices_data.json",
    "MFG": "https://fuel.motorfuelgroup.com/fuel_prices_data.json",
    "JET": "https://jetlocal.co.uk/fuel_prices_data.json",
    "Moto": "https://moto-way.com/fuel-price/fuel_prices.json",
    "Rontec": "https://www.rontec-servicestations.co.uk/fuel-prices/data/fuel_prices_data.json",
    "SGN": "https://www.sgnretail.uk/files/data/SGN_daily_fuel_prices.json",
    "Ascona": "https://fuelprices.asconagroup.co.uk/newfuel.json",
    "Tesco": "https://www.tesco.com/fuel_prices/fuel_prices_data.json",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, */*",
}

# -----------------------------
# GLOBAL HTTP SESSIONS
# -----------------------------
SESSION = requests.Session()
CURL_SESSION = curl_requests.Session()

# -----------------------------
# GLOBAL CACHED RESOURCES
# -----------------------------
inky = auto()
FONT_PRICE = ImageFont.truetype(FONT_BOLD, 17)
FONT_SMALL_BOLD = ImageFont.truetype(FONT_BOLD, 13)


# -----------------------------
# POSTCODE â†’ LAT/LON
# -----------------------------
def postcode_to_latlon(pc):
    r = requests.get(f"https://api.postcodes.io/postcodes/{pc}", timeout=10)
    r.raise_for_status()
    j = r.json()
    return j["result"]["latitude"], j["result"]["longitude"]


# -----------------------------
# HAVERSINE
# -----------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * asin(sqrt(a))


# -----------------------------
# FUEL PUMP ICON
# -----------------------------
def draw_fuel_pump(draw, x, y, black, white, scale=1.2):
    S = lambda v: int(v * scale)
    draw.rectangle([x, y + S(8), x + S(20), y + S(38)], fill=black)
    draw.rectangle([x + S(2), y + S(4), x + S(18), y + S(10)], fill=black)
    draw.rectangle([x + S(20), y + S(8), x + S(28), y + S(12)], fill=black)
    draw.rectangle([x + S(25), y + S(12), x + S(28), y + S(20)], fill=black)
    draw.rectangle([x + S(3), y + S(12), x + S(17), y + S(22)], fill=white)
    draw.rectangle([x + S(-2), y + S(36), x + S(22), y + S(42)], fill=black)


# -----------------------------
# UPTIME
# -----------------------------
def get_uptime():
    try:
        with open("/proc/uptime", "r") as f:
            seconds = float(f.read().split()[0])
    except:
        return "uptime: n/a"

    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    if days > 0:
        return f"Uptime: {days}d {hours}h {minutes}m"
    return f"Uptime: {hours}h {minutes}m"


# -----------------------------
# PARSE JSON
# -----------------------------
def parse_stations(retailer, data):
    out = []
    for s in data.get("stations", []):
        prices = s.get("prices", {})
        diesel = prices.get("B7")
        unleaded = prices.get("E10")
        if diesel is None and unleaded is None:
            continue

        try:
            lat = float(s.get("location", {}).get("latitude"))
            lon = float(s.get("location", {}).get("longitude"))
        except:
            continue

        name = s.get("brand", retailer)
        address = s.get("address", "")

        if retailer == "Asda":
            n = (name or "").strip().lower()
            name = "Asda Exp" if "express" in n else "Asda"

        if name.startswith("MFG "):
            name = name.replace("MFG ", "", 1)
        if address.startswith("MFG "):
            address = address.replace("MFG ", "", 1)

        if retailer != "Asda" and name.startswith(f"{retailer} "):
            name = name.replace(f"{retailer} ", "", 1)

        out.append(
            {
                "retailer": retailer,
                "name": name,
                "address": address,
                "postcode": s.get("postcode", ""),
                "lat": lat,
                "lon": lon,
                "diesel": float(diesel) if diesel is not None else None,
                "unleaded": float(unleaded) if unleaded is not None else None,
            }
        )
    return out


# -----------------------------
# PARALLEL FEED FETCHING
# -----------------------------
def fetch_all_stations():
    def fetch_one(retailer, url):
        try:
            # tiny stagger to avoid TLS pile-up on Zero W
            time.sleep(0.15)

            if retailer in ("Tesco", "BP", "JET"):
                try:
                    r = CURL_SESSION.get(url, impersonate="chrome", timeout=10)
                except Exception:
                    r = SESSION.get(url, headers=HEADERS, timeout=10)
            else:
                r = SESSION.get(url, headers=HEADERS, timeout=10)

            r.raise_for_status()
            return parse_stations(retailer, r.json())
        except Exception as e:
            print(f"Warning: could not fetch {retailer}: {e}")
            return []

    results = []
    # Pi Zero W sweet spot
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(fetch_one, r, u): r for r, u in RETAILER_FEEDS.items()}
        for fut in as_completed(futures):
            stations = fut.result()
            if stations:
                results.extend(stations)

    return results


# -----------------------------
# DEDUPE
# -----------------------------
def dedupe_stations(stations):
    seen = set()
    unique = []
    for s in stations:
        key = (round(s["lat"], 4), round(s["lon"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


# -----------------------------
# FIND CHEAPEST
# -----------------------------
def find_cheapest_nearby(home_lat, home_lon, radius_km=SEARCH_RADIUS_KM):
    stations = dedupe_stations(fetch_all_stations())
    nearby = []

    for s in stations:
        dist = haversine_km(home_lat, home_lon, s["lat"], s["lon"])
        if dist <= radius_km:
            s["distance_km"] = round(dist, 1)
            nearby.append(s)

    if not nearby:
        raise ValueError("No stations found nearby")

    diesel_stations = [s for s in nearby if s["diesel"] is not None]
    unleaded_stations = [s for s in nearby if s["unleaded"] is not None]

    best_diesel = min(diesel_stations, key=lambda s: s["diesel"])
    best_unleaded = min(unleaded_stations, key=lambda s: s["unleaded"])

    now = datetime.now().strftime("%H:%M %d/%m/%Y")

    return {
        "diesel_station": best_diesel["name"],
        "diesel_address": best_diesel["address"],
        "diesel_postcode": best_diesel["postcode"],
        "diesel_price": best_diesel["diesel"],
        "unleaded_station": best_unleaded["name"],
        "unleaded_address": best_unleaded["address"],
        "unleaded_postcode": best_unleaded["postcode"],
        "unleaded_price": best_unleaded["unleaded"],
        "updated": now,
    }


# -----------------------------
# DATABASE
# -----------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fuel_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fuel_type TEXT,
            station TEXT,
            price REAL,
            timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fuel_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fuel_type TEXT,
            price REAL,
            changed TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_price(fuel_type, station, price):
    ft = fuel_type.lower()
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO fuel_prices (fuel_type, station, price, timestamp) VALUES (?, ?, ?, ?)",
        (ft, station, price, datetime.now().isoformat()),
    )
    conn.commit()

    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM fuel_changes WHERE fuel_type = ?", (ft,))
    count = c.fetchone()[0]

    if count == 0:
        conn.execute(
            "INSERT INTO fuel_changes (fuel_type, price, changed) VALUES (?, ?, ?)",
            (ft, price, datetime.now().isoformat()),
        )
        conn.commit()

    conn.close()


def record_price_change(fuel_type, price):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO fuel_changes (fuel_type, price, changed) VALUES (?, ?, ?)",
        (fuel_type.lower(), price, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_last_price(fuel_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        SELECT station, price, timestamp
        FROM fuel_prices
        WHERE fuel_type = ?
        ORDER BY id DESC LIMIT 1
    """,
        (fuel_type.lower(),),
    )
    row = c.fetchone()
    conn.close()
    return row


def get_last_change_time(fuel_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        SELECT changed
        FROM fuel_changes
        WHERE fuel_type = ?
        ORDER BY id DESC LIMIT 1
    """,
        (fuel_type.lower(),),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


# -----------------------------
# IRC ALERTS
# -----------------------------
def send_irc_messages(server, port, nick, channel, messages):
    if not IRC_ENABLED or not messages:
        return
    try:
        try:
            irc = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            irc.connect((server, port, 0, 0))
        except Exception:
            irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            irc.connect((server, port))

        def send(cmd):
            irc.send((cmd + "\r\n").encode("utf-8"))

        send(f"NICK {nick}")
        send(f"USER {nick} 0 * :FuelBot")
        time.sleep(2)
        send(f"JOIN {channel}")
        time.sleep(3)

        for msg in messages:
            send(f"PRIVMSG {channel} :{msg}")
            time.sleep(3)

        send("QUIT :bye")
        irc.close()

    except Exception as e:
        print(f"IRC alert failed: {e}")


# -----------------------------
# ALERT LOGIC
# -----------------------------
def maybe_send_alert(fuel_type, current_price, last_row, station_info):
    if not last_row:
        return None, None

    ft = fuel_type.lower()
    _, last_price, _ = last_row
    diff = current_price - last_price

    fuel_col = "\x0302" if ft == "diesel" else "\x0307"
    reset = "\x0f"
    bold = "\x02"

    station = station_info["name"]
    address = station_info["address"]
    postcode = station_info["postcode"]

    # Expand Asda Exp â†’ Asda Express for notifications only
    if station == "Asda Exp":
        station = "Asda Express"

    location = f"{station}, {address}, {postcode}".replace(",,", ",").strip().strip(",")

    emoji_drop = "ðŸ™‚"
    emoji_rise = "â˜¹ï¸"

    price_pounds = current_price / 100

    if diff <= -ALERT_THRESHOLD_DROP:
        record_price_change(ft, current_price)
        irc_msg = (
            f"{bold}{emoji_drop} {fuel_col}{fuel_type}{reset} "
            f"price decreased {abs(diff):.1f}p â€” now Â£{price_pounds:.2f} at {location}{reset}{bold}"
        )
        plain_msg = (
            f"{emoji_drop} {fuel_type} price decreased {abs(diff):.1f}p "
            f"â€” now Â£{price_pounds:.2f} at {location}"
        )
        return irc_msg, plain_msg

    if diff >= ALERT_THRESHOLD_RISE:
        record_price_change(ft, current_price)
        irc_msg = (
            f"{bold}{emoji_rise} {fuel_col}{fuel_type}{reset} "
            f"price increased {diff:.1f}p â€” now Â£{price_pounds:.2f} at {location}{reset}{bold}"
        )
        plain_msg = (
            f"{emoji_rise} {fuel_type} price increased {diff:.1f}p "
            f"â€” now Â£{price_pounds:.2f} at {location}"
        )
        return irc_msg, plain_msg

    return None, None


# -----------------------------
# DISCORD ALERTS
# -----------------------------
def send_discord_messages(messages):
    if not DISCORD_ENABLED or not DISCORD_WEBHOOK_URL:
        return

    if not messages:
        return

    try:
        content = "\n".join(messages)
        r = SESSION.post(
            DISCORD_WEBHOOK_URL,
            json={"content": content},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Discord alert failed: {e}")


# -----------------------------
# TELEGRAM ALERTS
# -----------------------------
def send_telegram_messages(messages):
    if (
        not TELEGRAM_ENABLED
        or not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
        or not messages
    ):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for msg in messages:
        try:
            r = SESSION.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                timeout=10,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"Telegram alert failed: {e}")


def render_inky(data, fast=False, partial=False):
    try:
        if fast and hasattr(inky, "set_fast_update"):
            inky.set_fast_update(True)
    except:
        pass

    try:
        if partial and hasattr(inky, "set_partial_mode"):
            inky.set_partial_mode(True)
    except:
        pass

    inky.set_border(inky.WHITE)
    WIDTH, HEIGHT = inky.resolution

    img = Image.new("P", (WIDTH, HEIGHT), color=inky.BLACK)
    draw = ImageDraw.Draw(img)

    font_price = FONT_PRICE
    font_small = FONT_SMALL_BOLD

    draw_fuel_pump(draw, WIDTH - 30, 0, inky.RED, inky.BLACK, scale=0.8)

    y = 3

    draw.text((5, y), "DIESEL", inky.WHITE, font=font_small)
    y += 12
    draw.text(
        (5, y),
        f"{data['diesel_price']:.1f}p  {data['diesel_station']}",
        inky.WHITE,
        font=font_price,
    )
    y += 22

    draw.text((5, y), "UNLEADED", inky.WHITE, font=font_small)
    y += 12
    draw.text(
        (5, y),
        f"{data['unleaded_price']:.1f}p  {data['unleaded_station']}",
        inky.WHITE,
        font=font_price,
    )
    y += 22

    draw.line((5, y, WIDTH - 5, y), fill=inky.WHITE, width=1)
    y += 4

    last_change = data.get("last_change")
    if last_change:
        ts = datetime.fromisoformat(last_change).strftime("%H:%M %d/%m/%Y")
        draw.text((5, y), f"Update: {ts}", inky.WHITE, font=font_small)
    else:
        draw.text((5, y), "Update: n/a", inky.WHITE, font=font_small)
    y += 12

    draw.text((5, y), get_uptime(), inky.WHITE, font=font_small)

    img = img.rotate(180)
    inky.set_image(img)
    inky.show()


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    init_db()

    home_lat, home_lon = postcode_to_latlon(POSTCODE)
    print(f"Using postcode {POSTCODE}")

    best = find_cheapest_nearby(home_lat, home_lon)

    alerts = []
    alerts_plain = []  # stripped of IRC colour codes for Discord/Telegram

    last_diesel = get_last_price("diesel")
    irc_msg, plain_msg = maybe_send_alert(
        "Diesel",
        best["diesel_price"],
        last_diesel,
        {
            "name": best["diesel_station"],
            "address": best["diesel_address"],
            "postcode": best["diesel_postcode"],
        },
    )
    if irc_msg:
        alerts.append(irc_msg)
    if plain_msg:
        alerts_plain.append(plain_msg)
    log_price("diesel", best["diesel_station"], best["diesel_price"])

    last_unleaded = get_last_price("unleaded")
    irc_msg, plain_msg = maybe_send_alert(
        "Unleaded",
        best["unleaded_price"],
        last_unleaded,
        {
            "name": best["unleaded_station"],
            "address": best["unleaded_address"],
            "postcode": best["unleaded_postcode"],
        },
    )
    if irc_msg:
        alerts.append(irc_msg)
    if plain_msg:
        alerts_plain.append(plain_msg)
    log_price("unleaded", best["unleaded_station"], best["unleaded_price"])

    diesel_change = get_last_change_time("diesel")
    unleaded_change = get_last_change_time("unleaded")

    latest_change = max(filter(None, [diesel_change, unleaded_change]), default=None)
    best["last_change"] = latest_change

    send_irc_messages(IRC_SERVER, IRC_PORT, IRC_NICK, IRC_CHANNEL, alerts)
    send_discord_messages(alerts_plain)
    send_telegram_messages(alerts_plain)

    render_inky(best, fast=FAST_UPDATE, partial=PARTIAL_UPDATE)
