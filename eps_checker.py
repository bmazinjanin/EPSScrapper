import os
import re
import smtplib
import unicodedata
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup
import cyrtranslit

# ===== KONFIG =====
EPS_URLS = {
    "danas": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_0_Iskljucenja.htm",
    "sutra": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_1_Iskljucenja.htm"
}
BVK_URL = "https://www.bvk.rs/kvarovi-na-mrezi/#toggle-id-1"

TARGET_STREETS = ["Сестара", "Никодима", "Салвадора", "Влајковићева", "Маријане", "Радмиловића"]

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)
EMAIL_TO = os.getenv("EMAIL_TO", "")

TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

# ===== HELPERI =====
def strip_diacritics(s: str) -> str:
    norm = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")

def tolatin(s: str) -> str:
    table = str.maketrans({
        "А": "A","Б": "B","В": "V","Г": "G","Д": "D","Ђ": "Dj","Е": "E","Ж": "Z","З": "Z","И": "I",
        "Ј": "J","К": "K","Л": "L","Љ": "Lj","М": "M","Н": "N","Њ": "Nj","О": "O","П": "P","Р": "R",
        "С": "S","Т": "T","Ћ": "C","У": "U","Ф": "F","Х": "H","Ц": "C","Ч": "C","Џ": "Dz","Ш": "S",
        "а": "a","б": "b","в": "v","г": "g","д": "d","ђ": "dj","е": "e","ж": "z","з": "z","и": "i",
        "ј": "j","к": "k","л": "l","љ": "lj","м": "m","н": "n","њ": "nj","о": "o","п": "p","р": "r",
        "с": "s","т": "t","ћ": "c","у": "u","ф": "f","х": "h","ц": "c","ч": "c","џ": "dz","ш": "s",
    })
    return s.translate(table)

def norm(s: str) -> str:
    s = tolatin(s)
    s = strip_diacritics(s)
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ===== EPS STRUJA =====
def load_eps(url: str):
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")
        if len(tables) < 2:
            return []
        rows = tables[1].find_all("tr")
        data = []
        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) == 3:
                opstina = cols[0].get_text(strip=True)
                vreme = cols[1].get_text(strip=True)
                ulice = cols[2].get_text(" ", strip=True)
                data.append((opstina, vreme, ulice))
        return data
    except Exception as e:
        print("⚠️ EPS error:", e)
        return []

def search_eps(street: str) -> List[str]:
    results = []
    target = cyrtranslit.to_cyrillic(street, "sr") if all("a" <= ch.lower() <= "z" or ch.isspace() for ch in street) else street
    for day, url in EPS_URLS.items():
        for opstina, vreme, ulice in load_eps(url):
            if target.upper() in ulice.upper():
                datum = datetime.now().strftime("%Y-%m-%d") if day == "danas" else (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                results.append(f"{day.upper()} ({datum}): {opstina} | {vreme} | {ulice} (📎 {url})")
    return results

# ===== BVK VODA =====
def fetch_bvk_items(url: str) -> List[str]:
    resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    all_lis = [li.get_text(" ", strip=True) for li in soup.find_all("li")]
    items = []
    for li_text in all_lis:
        if "Распоред аутоцистерни" in li_text or "Raspored autocisterni" in li_text:
            break
        if any(bad in li_text.lower() for bad in ["share", "facebook", "twitter", "whatsapp"]):
            continue
        items.append(li_text)

    if not items:
        text = soup.get_text("\n", strip=True)
        m = re.search(r"(Без воде су.*?)(Распоред аутоцистерни|$)", text, flags=re.S | re.I)
        if m:
            for line in m.group(1).splitlines():
                line = line.strip("•*- \t")
                if len(line) > 3:
                    items.append(line)
    return items

def search_bvk(street: str) -> List[str]:
    hits = []
    items = fetch_bvk_items(BVK_URL)
    target_norm = norm(street)
    for raw in items:
        if target_norm in norm(raw):
            hits.append(f"{street} → {raw} (📎 {BVK_URL})")
    return hits

# ===== EMAIL =====
def send_email(subject: str, body: str):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM, EMAIL_TO]):
        print("⚠️ Nedostaju SMTP parametri.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    body_html = body.replace("\n", "<br>")
    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.5; color: #333;">
        <h2>{subject}</h2>
        <p>{body_html}</p>
        <hr>
        <p style="font-size:12px; color:#777;">
          📡 Automatski izveštaj sa EPS & BVK<br>
          🔌 Ako nema struje: punite power bankove.<br>
          🚿 Ako nema vode: napunite flaše i balone.<br>
          🍻 Ako nema ni struje ni vode: vreme je za kafanu 😅
        </p>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    print(f"📧 Poslat email na {EMAIL_TO}")

# ===== MAIN =====
if __name__ == "__main__":
    eps_hits, bvk_hits = [], []

    for street in TARGET_STREETS:
        print(f"🔎 Tražim za: {street}")
        eps_hits.extend(search_eps(street))
        bvk_hits.extend(search_bvk(street))

    subject, body_parts = "✅ Sve je OK – struja i voda rade", []

    if eps_hits and not bvk_hits:
        subject = "⚡ NEMA STRUJE – pripremite sveće!"
        body_parts.append("⚡ <b>Isključenja struje:</b><br>" + "<br>".join(eps_hits))

    elif bvk_hits and not eps_hits:
        subject = "🚰 NEMA VODE – punite balone i flaše!"
        body_parts.append("🚰 <b>Isključenja vode:</b><br>" + "<br>".join(bvk_hits))

    elif eps_hits and bvk_hits:
        subject = "⚡🚰 NEMA STRUJE I VODE – apokalipsa u komšiluku!"
        body_parts.append("⚡ <b>Isključenja struje:</b><br>" + "<br>".join(eps_hits))
        body_parts.append("🚰 <b>Isključenja vode:</b><br>" + "<br>".join(bvk_hits))

    body = "<br><br>".join(body_parts) if body_parts else "✅ Sve OK! Nema prekida."
    send_email(subject, body)
