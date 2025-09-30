import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup
import cyrtranslit
from datetime import datetime, timedelta
import unicodedata
import re

# ========================
# EPS KONFIG
# ========================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

EPS_URLS = {
    "danas": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_0_Iskljucenja.htm",
    "sutra": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_1_Iskljucenja.htm"
}

# ========================
# BVK KONFIG
# ========================
BVK_URL = "https://www.bvk.rs/kvarovi-na-mrezi/#toggle-id-1"
TARGET_STREETS = [
    "Sestara",
    "Nikodima",
    "Salvadora",
    "Vlajkovićeva",
    "Радмиловића",
    "Marijane"
]

TIMEOUT = 25

# ========================
# EMAIL KONFIG
# ========================
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

# ========================
# EPS FUNKCIJE
# ========================

def load_eps_data(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

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
        print(f"⚠️ EPS greška: {e}")
        return []

def search_eps(query):
    if all("a" <= ch.lower() <= "z" or ch.isspace() for ch in query):
        target = cyrtranslit.to_cyrillic(query, "sr")
    else:
        target = query

    results = []
    for day, url in EPS_URLS.items():
        data = load_eps_data(url)
        for opstina, vreme, ulice in data:
            if target.upper() in ulice.upper():
                if day == "danas":
                    datum = datetime.now().strftime("%Y-%m-%d")
                    results.append(f"📅 DANAS ({datum}): {opstina} | {vreme} | {ulice}\n🔗 Izvor: {url}")
                else:
                    datum = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                    results.append(f"📅 SUTRA ({datum}): {opstina} | {vreme} | {ulice}\n🔗 Izvor: {url}")
    return results

# ========================
# BVK FUNKCIJE
# ========================

def strip_diacritics(s: str) -> str:
    norm = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")

def tolatin(s: str) -> str:
    table = str.maketrans({
        "А":"A","Б":"B","В":"V","Г":"G","Д":"D","Ђ":"Dj","Е":"E","Ж":"Z","З":"Z","И":"I","Ј":"J","К":"K",
        "Л":"L","Љ":"Lj","М":"M","Н":"N","Њ":"Nj","О":"O","П":"P","Р":"R","С":"S","Т":"T","Ћ":"C","У":"U",
        "Ф":"F","Х":"H","Ц":"C","Ч":"C","Џ":"Dz","Ш":"S",
        "а":"a","б":"b","в":"v","г":"g","д":"d","ђ":"dj","е":"e","ж":"z","з":"z","и":"i","ј":"j","к":"k",
        "л":"l","љ":"lj","м":"m","н":"n","њ":"nj","о":"o","п":"p","р":"r","с":"s","т":"t","ћ":"c","у":"u",
        "ф":"f","х":"h","ц":"c","ч":"c","џ":"dz","ш":"s",
    })
    return s.translate(table)

def norm(s: str) -> str:
    s = tolatin(s)
    s = strip_diacritics(s)
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fetch_bvk_items(url: str):
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    all_lis = [li.get_text(" ", strip=True) for li in soup.find_all("li")]

    items = []
    for li_text in all_lis:
        if "Распоред аутоцистерни" in li_text or "Raspored autocisterni" in li_text:
            break
        if any(bad in li_text.lower() for bad in ["share", "facebook", "twitter"]):
            continue
        items.append(li_text)

    if not items:
        text = soup.get_text("\n", strip=True)
        m = re.search(r"(Без воде су.*?)(Распоред аутоцистерни|$)", text, flags=re.S | re.I)
        if m:
            block = m.group(1)
            for line in block.splitlines():
                line = line.strip("•*- \t")
                if len(line) > 3:
                    items.append(line)

    return items

def match_bvk(items, targets):
    norm_targets = [norm(t) for t in targets]
    hits = []
    for raw in items:
        nline = norm(raw)
        for tgt_raw, tgt in zip(targets, norm_targets):
            if tgt and tgt in nline:
                hits.append((tgt_raw, raw))
    unique = []
    seen = set()
    for k in hits:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique

def search_bvk():
    try:
        items = fetch_bvk_items(BVK_URL)
    except Exception as e:
        print(f"❌ BVK greška: {e}")
        return []

    hits = match_bvk(items, TARGET_STREETS)
    results = []
    for street, raw in hits:
        results.append(f"- {street} → {raw}\n🔗 Izvor: {BVK_URL}")
    return results

# ========================
# EMAIL
# ========================

def send_email(subject, body):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO]):
        print("⚠️ Nedostaju SMTP parametri.")
        return
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print(f"📧 Email poslat na {EMAIL_TO}")

# ========================
# MAIN
# ========================

if __name__ == "__main__":
    final_parts = []

    # EPS
    eps_results = []
    for street in TARGET_STREETS:
        res = search_eps(street)
        if res:
            eps_results.append(f"🔌 Struja – {street}:\n" + "\n".join(res))
    if eps_results:
        final_parts.append("=== EPS Isključenja ===\n" + "\n\n".join(eps_results))

    # BVK
    bvk_results = search_bvk()
    if bvk_results:
        final_parts.append("=== BVK Bez vode ===\n" + "\n".join(bvk_results))

    if final_parts:
        body = "\n\n".join(final_parts)
        print("⚡ Rezultati:\n", body)
        send_email("⚠️ Isključenja (struja/voda)", body)
    else:
        print("✅ Nema isključenja ni kvarova za tvoje ulice.")
