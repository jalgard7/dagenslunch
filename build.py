#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

STO_TZ = ZoneInfo("Europe/Stockholm")
USER_AGENT = "Mozilla/5.0 (compatible; PMO-IT-Lunch/1.1)"

SOURCE_URLS = {
    "FEI": "https://www.fei.se/meny-fei-restaurant-lounge",
    "Cirkeln": "https://cirkelnstockholm.se/restauranger/restaurang-cirkeln/",
}
DISPLAY_NAMES = {
    "FEI": "FEI Restaurang & Lounge",
    "Cirkeln": "Restaurang Cirkeln",
}
LOGOS = {
    "FEI": "https://res.cloudinary.com/emg-prod/image/upload/c_limit,h_100,w_200/v1/institutes/institute10621/logos/logo",
    "Cirkeln": "https://cirkelnstockholm.se/wp-content/uploads/2021/09/c_restaurang-S-150x150.png",
}

WEEKDAYS_FULL = ["MÅNDAG", "TISDAG", "ONSDAG", "TORSDAG", "FREDAG", "LÖRDAG", "SÖNDAG"]

@dataclass
class DayMenu:
    restaurant_key: str
    items: list[str]

def today_weekday_sv_upper(dt: datetime) -> str:
    return WEEKDAYS_FULL[dt.weekday()]

def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def clean_lines(text: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", ln).strip(" •*-–—. ") for ln in text.splitlines()]
    return [ln for ln in lines if ln]

def parse_fei(soup: BeautifulSoup, weekday_upper: str) -> list[str]:
    candidates = []
    for tag in soup.find_all(["h2", "h3", "h4", "strong", "p"]):
        txt = (tag.get_text(separator=" ", strip=True) or "").strip()
        if txt.upper() == weekday_upper:
            candidates.append(tag)

    items: list[str] = []
    for tag in candidates:
        next_el = tag.find_next_sibling()
        hops = 0
        while next_el and hops < 6 and (next_el.name in [None, "br"] or (hasattr(next_el, "get_text") and not next_el.get_text(strip=True))):
            next_el = next_el.find_next_sibling()
            hops += 1

        if next_el:
            if next_el.name == "ul":
                for li in next_el.find_all("li"):
                    t = li.get_text(" ", strip=True)
                    if t:
                        items.append(t)
            else:
                block_text = []
                walker = next_el
                stop_words = set(WEEKDAYS_FULL + ["PRIS OCH ÖPPETTIDER", "VECKANS VEGETARISKA"])
                steps = 0
                while walker and steps < 12:
                    t = walker.get_text(" ", strip=True) if hasattr(walker, "get_text") else ""
                    if t and t.upper() in stop_words:
                        break
                    if t:
                        block_text.append(t)
                    walker = walker.find_next_sibling()
                    steps += 1
                for ln in clean_lines("\n".join(block_text)):
                    if len(ln) > 3:
                        items.append(ln)
        if items:
            break
    return items

def parse_cirkeln(soup: BeautifulSoup, weekday_upper: str) -> list[str]:
    container = None
    patterns = [re.compile(r"Lunchmeny", re.I), re.compile(r"Vecka\s+\d+", re.I)]
    for tag in soup.find_all(text=True):
        t = tag.strip()
        if all(p.search(t) for p in patterns):
            container = tag.parent
            break
    if not container:
        for el in soup.find_all(["h1", "h2", "h3", "p", "div"]):
            if re.search(r"Lunchmeny", el.get_text(" ", strip=True), re.I):
                container = el
                break

    text = []
    if container:
        cur = container
        steps = 0
        while cur and steps < 80:
            text.append(cur.get_text(" ", strip=True))
            cur = cur.find_next_sibling()
            steps += 1
    full = "\n".join([t for t in text if t])

    wd_order = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag"]
    day_name_cap = weekday_upper.capitalize()

    m = re.search(
        rf"{day_name_cap}\s*(.+?)(?=(?:{'|'.join(wd_order)})\s*|Kontakt|Öppettider|Veckans vegetariska|$)",
        full,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []
    block = m.group(1)
    lines = clean_lines(block)
    filtered = [ln for ln in lines if len(ln) > 3 and not re.match(r"^Pris|^11:|^Dagens|^Veckans", ln, re.I)]
    return filtered

def get_menu_for(key: str, url: str, weekday_upper: str) -> DayMenu:
    soup = fetch(url)
    if key.lower() == "fei":
        items = parse_fei(soup, weekday_upper)
    elif key.lower() == "cirkeln":
        items = parse_cirkeln(soup, weekday_upper)
    else:
        items = []
    return DayMenu(restaurant_key=key, items=items)

def force_linebreaks(text: str) -> str:
    t = re.sub(r"\s*/\s*", "<br>", text)
    t = re.sub(r"\s*\|\s*", "<br>", t)
    return t

def render_html(weekday_upper: str, day_menus: list[DayMenu]) -> str:
    updated_at = datetime.now(tz=STO_TZ).strftime("%Y-%m-%d %H:%M")
    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>Dagens lunch</title>
<style>
  :root {{ --fg:#111; --muted:#555; --card:#fff; --bg:#f6f7f9; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#eaeaea; --muted:#a0a0a0; --card:#171717; --bg:#0e0f11; }}
  }}
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);margin:0}}
  .wrap{{max-width:760px;margin:32px auto;padding:0 16px}}
  .card{{background:var(--card);border-radius:16px;box-shadow:0 6px 24px rgba(0,0,0,.08);padding:24px}}
  h1{{margin:0 0 6px 0;font-size:28px}}
  h2{{margin:0 0 16px 0;font-size:18px;letter-spacing:1px;color:var(--muted)}}
  .rest{{padding:14px 0;border-top:1px solid rgba(128,128,128,.25)}}
  .rest:first-of-type{{border-top:none}}
  .head{{display:flex;align-items:center;gap:12px;margin-bottom:6px}}
  .logo{{width:28px;height:28px;object-fit:contain;border-radius:6px;flex:0 0 28px;filter:contrast(1.1)}}
  .name{{font-weight:700}}
  .dish{{margin:4px 0;line-height:1.5}}
  .footer{{margin-top:10px;color:var(--muted);font-size:12px}}
</style>
<div class="wrap">
  <div class="card">
    <h1>Dagens lunch by PMO IT</h1>
    <h2>{weekday_upper}</h2>
"""
    for dm in day_menus:
        key = dm.restaurant_key
        name = DISPLAY_NAMES.get(key, key)
        logo = LOGOS.get(key, "")
        html += "    <div class='rest'>\n      <div class='head'>\n"
        if logo:
            html += f"        <img class='logo' src='{logo}' alt='{name} logotyp'>\n"
        html += f"        <div class='name'>{name}</div>\n      </div>\n"
        if dm.items:
            for dish in dm.items:
                html += f"      <div class='dish'>{force_linebreaks(dish)}</div>\n"
        else:
            html += f"      <div class='dish'><em>ingen meny hittad för {weekday_upper.capitalize()}</em></div>\n"
        html += "    </div>\n"
    html += f"""    <div class="footer">Uppdaterad: {updated_at} · Tidszon: Europe/Stockholm</div>
  </div>
</div>
"""
    return html

def main() -> int:
    today = datetime.now(tz=STO_TZ)
    weekday_upper = today_weekday_sv_upper(today)

    day_menus: list[DayMenu] = []
    for key, url in SOURCE_URLS.items():
        try:
            day_menus.append(get_menu_for(key, url, weekday_upper))
        except Exception as e:
            day_menus.append(DayMenu(restaurant_key=key, items=[f"(fel vid hämtning: {e})"]))

    html = render_html(weekday_upper, day_menus)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Skrev index.html")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
