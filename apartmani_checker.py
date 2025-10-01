import os
import re
import smtplib
import unicodedata
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict

import requests
from bs4 import BeautifulSoup
import cyrtranslit

# ===== KONFIGURACIJA =====
EPS_URLS = {
    "danas": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_0_Iskljucenja.htm",
    "sutra": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_1_Iskljucenja.htm",
}
BVK_URL = "https://www.bvk.rs/kvarovi-na-mrezi/#toggle-id-1"

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 20

# ===== ADRESE + OKOLINA =====
ADRESNI_KLASTERI = {
    "Majke Jevrosime 42": [
        "Majke Jevrosime",
        "Svetogorska",
        "Kosovska",
        "Palmoticeva",
        "Takovska",
        "Hilandarska",
        "Kondina",
        "Makedonska",
        "Nusiceva",
        "Vlajkoviceva",
        "Decanska",
        "ДРАГОСЛАВА"
    ],
    "Kapetan-Misina 4": [
        "Kapetan-Misina",
        "Dositejeva",
        "Gospodar Jovanova",
        "Strahinjica Bana",
        "Brace Jugovica",
        "Studentski trg",
        "Simina",
        "Knez Mihailova",
        "Kralja Petra",
        "Жоржа"
    ],
    "Bulevar Despota Stefana 10": [
        "Bulevar Despota Stefana",
        "Skadarska",
        "Francuska",
        "Cetinjska",
        "Strahinjica Bana",
        "Zetska",
        "Dobracina",
        "Gundulicev venac",
    ],
}

# ===== POMOĆNE =====
def strip_diacritics(s: str) -> str:
    norm = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")

def tolatin(s: str) -> str:
    return cyrtranslit.to_latin(s, "sr")

def norm_text(s: str) -> str:
    s = tolatin(s)
    s = strip_diacritics(s)
    return re.sub(r"\s+", " ", s).lower().strip()

# ===== EPS =====
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
                data.append((
                    cols[0].get_text(strip=True),
                    cols[1].get_text(strip=True),
                    cols[2].get_text(" ", strip=True),
                ))
        return data
    except Exception as e:
        print(f"⚠️ EPS greška: {e}")
        return []

def search_eps_hits(streets: List[str]) -> List[Dict[str, str]]:
    hits = []
    for day, url in EPS_URLS.items():
        data = load_eps_data(url)
        for opstina, vreme, ulice in data:
            for query in streets:
                if query.upper() in ulice.upper():
                    datum = datetime.now().strftime("%Y-%m-%d") if day == "danas" else (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                    hits.append({
                        "day": day,
                        "date": datum,
                        "opstina": opstina,
                        "vreme": vreme,
                        "ulice": ulice,
                        "url": url,
                        "match": query,
                    })
    return hits

# ===== BVK =====
def fetch_bvk_items(url: str) -> List[str]:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    all_lis = [li.get_text(" ", strip=True) for li in soup.find_all("li")]
    items = []
    for li_text in all_lis:
        if "Распоред аутоцистерни" in li_text:
            break
        items.append(li_text)
    return items

def search_bvk_hits(streets: List[str]) -> List[str]:
    items = fetch_bvk_items(BVK_URL)
    hits = []
    for line in items:
        for street in streets:
            if street.lower() in line.lower():
                hits.append(line)
    return list(dict.fromkeys(hits))

# ===== EMAIL =====
def build_html_body(results: dict) -> str:
    today = datetime.now().strftime("%A, %d.%m.%Y.")

    html = [f"""
<!doctype html>
<html>
  <head><meta charset="utf-8"></head>
  <body style="font-family:Arial, sans-serif; background-color:#0b0f14 !important; color:#e6edf3 !important; padding:24px;">
    <div style="background-color:#111826 !important; border:1px solid #1f2a37; border-radius:14px; padding:20px; margin-bottom:16px;">
      <div style="font-size:18px; font-weight:600; margin-bottom:6px; color:#93c5fd !important;">📬 Apartmani — dnevni izveštaj ({datetime.now().strftime("%d.%m.%Y")})</div>
      <div style="opacity:.8; font-size:12px; color:#e6edf3 !important;">{today}</div>
    </div>
"""]

    for adresa, data in results.items():
        html.append(f"""
        <div style="background-color:#111826 !important; border:1px solid #1f2a37; border-radius:14px; padding:20px; margin-bottom:16px; color:#e6edf3 !important;">
          <div style="font-weight:600; margin-bottom:6px; font-size:16px; color:#ff6b6b !important;">🏠 Okolina: {adresa}</div>
        """)

        # EPS deo
        if data["eps"]:
            html.append('<div style="font-weight:600; margin-bottom:6px; color:#f97373 !important;">⚡ EPS isključenja:</div>')
            for h in data["eps"]:
                html.append(f"""
                  <div style="margin-bottom:8px; color:#e6edf3 !important;">
                    <div><strong>Ulica pogođena:</strong> {h['match']}</div>
                    <div>{h['date']} ({h['day']}), {h['opstina']} — {h['vreme']}</div>
                    <div><a href="{h['url']}" style="color:#93c5fd !important;">izvor</a></div>
                  </div>
                """)
        else:
            html.append('<div style="color:#34d399 !important; margin-bottom:8px;">✅ Nema isključenja struje u okolini.</div>')

        # BVK deo
        if data["bvk"]:
            html.append('<div style="font-weight:600; margin-top:10px; margin-bottom:6px; color:#f59e0b !important;">🚰 BVK kvarovi/radovi:</div><ul>')
            for raw in data["bvk"]:
                html.append(f'<li style="color:#e6edf3 !important;">{raw} <a href="{BVK_URL}" style="color:#93c5fd !important;">izvor</a></li>')
            html.append('</ul>')
        else:
            html.append('<div style="color:#34d399 !important; margin-top:8px;">✅ Nema prijavljenih kvarova vode u okolini.</div>')

        html.append("</div>")  # zatvaranje card-a za adresu

    html.append("</body></html>")
    return "".join(html)

def send_email(subject: str, html_body: str, text_body: str = ""):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_to = os.getenv("EMAIL_TO")

    if not all([smtp_user, smtp_pass, email_to]):
        print("⚠️ Nedostaju SMTP kredencijali ili EMAIL_TO.")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = smtp_user
        msg["To"] = email_to
        msg["Subject"] = subject

        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        print(f"📧 Email poslat na {email_to} • Subject: {subject}")

    except Exception as e:
        # Ovde hvatamo sve SMTP greške i NE prekidamo program
        print(f"⚠️ Greška pri slanju email-a: {e}")

# ===== MAIN =====
if __name__ == "__main__":
    results = {}
    ukupno_eps = 0
    ukupno_bvk = 0

    for adresa, streets in ADRESNI_KLASTERI.items():
        eps_hits = search_eps_hits(streets)
        bvk_hits = search_bvk_hits(streets)
        results[adresa] = {"eps": eps_hits, "bvk": bvk_hits}
        ukupno_eps += len(eps_hits)
        ukupno_bvk += len(bvk_hits)

    # ---- PRINT NA KONZOLU ----
    print("\n===== REZIME =====")
    for adresa, data in results.items():
        print(f"\n🏠 Okolina: {adresa}")
        if data["eps"]:
            print("  ⚡ EPS isključenja:")
            for hit in data["eps"]:
                print(f"    - {hit['match']} | {hit['date']} ({hit['day']}) | {hit['opstina']} | {hit['vreme']}")
        else:
            print("  ✅ Nema isključenja struje")
        if data["bvk"]:
            print("  🚰 BVK kvarovi/radovi:")
            for hit in data["bvk"]:
                print(f"    - {hit}")
        else:
            print("  ✅ Nema prijavljenih kvarova vode")
    print("\n===== KRAJ REZIMEA =====\n")

    # ---- EMAIL SAMO AKO IMA NEŠTO ----
    if ukupno_eps == 0 and ukupno_bvk == 0:
        print("📭 Nema pogodaka (struja/voda) — email neće biti poslat.")
    else:
        subject = f"📬 Apartmani — izveštaj {datetime.now().strftime('%Y-%m-%d')}"
        html_body = build_html_body(results)
        send_email(subject, html_body)

