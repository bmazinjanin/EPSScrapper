import os
import re
import smtplib
import unicodedata
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup
import cyrtranslit

# ===== KONFIGURACIJA =====
EPS_URLS = {
    "danas": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_0_Iskljucenja.htm",
    "sutra": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_1_Iskljucenja.htm",
}
BVK_URL = "https://www.bvk.rs/kvarovi-na-mrezi/#toggle-id-1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

TIMEOUT = 20

# ===== POMOĆNE FUNKCIJE =====
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

# ===== EPS STRUJA =====
def load_eps_data(url: str):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

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

def search_eps(query: str):
    # latinica -> ćirilica ako treba
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
                else:
                    datum = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                results.append(f"⚡ {day.upper()} ({datum}): {opstina} | {vreme} | {ulice}\nIzvor: {url}")

    return "\n\n".join(results) if results else None

# ===== BVK VODA =====
def fetch_bvk_items(url: str) -> List[str]:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
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

def match_streets(items: List[str], targets: List[str]) -> List[Tuple[str, str]]:
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

def search_bvk(query: str):
    items = fetch_bvk_items(BVK_URL)
    hits = match_streets(items, [query])
    if not hits:
        return None
    lines = []
    for street, raw in hits:
        lines.append(f"🚰 {street} → {raw}\nIzvor: {BVK_URL}")
    return "\n".join(lines)

# ===== EMAIL =====
def send_email(subject: str, body: str):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_to = os.getenv("EMAIL_TO")

    if not all([smtp_user, smtp_pass, email_to]):
        print("⚠️ Nedostaju SMTP kredencijali.")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg["Subject"] = subject

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"📧 Email poslat na {email_to}")
    except Exception as e:
        print(f"⚠️ Greška pri slanju email-a: {e}")

# ===== MAIN =====
if __name__ == "__main__":
    streets = ["Sestara", "Nikodima", "Salvadora", "Vlajkovićeva", "Marijane", "Радмиловића"]
    all_results = []

    for street in streets:
        eps_res = search_eps(street)
        bvk_res = search_bvk(street)
        if eps_res:
            all_results.append(f"=== EPS: {street} ===\n{eps_res}")
        if bvk_res:
            all_results.append(f"=== BVK: {street} ===\n{bvk_res}")

    if all_results:
        final_report = "\n\n".join(all_results)
        print("✅ Pronađeni rezultati:\n", final_report)
        send_email("⚡ EPS/BVK izveštaj", final_report)
    else:
        print("✅ Nema planiranih isključenja struje/vode za tražene ulice.")

