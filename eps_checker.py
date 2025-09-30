import os
import re
import smtplib
import unicodedata
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Tuple, Dict

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

def norm_text(s: str) -> str:
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

def search_eps_hits(query: str) -> List[Dict[str, str]]:
    # ako je latinica -> prebaci na ćirilicu
    if all("a" <= ch.lower() <= "z" or ch.isspace() for ch in query):
        target = cyrtranslit.to_cyrillic(query, "sr")
    else:
        target = query

    hits = []
    for day, url in EPS_URLS.items():
        data = load_eps_data(url)
        for opstina, vreme, ulice in data:
            if target.upper() in ulice.upper():
                if day == "danas":
                    datum = datetime.now().strftime("%Y-%m-%d")
                else:
                    datum = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                hits.append({
                    "day": day,
                    "date": datum,
                    "opstina": opstina,
                    "vreme": vreme,
                    "ulice": ulice,
                    "url": url,
                    "query": query
                })
    return hits

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
    norm_targets = [norm_text(t) for t in targets]
    hits = []
    for raw in items:
        nline = norm_text(raw)
        for tgt_raw, tgt in zip(targets, norm_targets):
            if tgt and tgt in nline:
                hits.append((tgt_raw, raw))
    # uniq
    unique = []
    seen = set()
    for k in hits:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique

def search_bvk_hits(query: str) -> List[str]:
    items = fetch_bvk_items(BVK_URL)
    hits = match_streets(items, [query])
    return [raw for (_street, raw) in hits]

# ===== EMAIL (HTML + TXT) =====
def build_subject(eps_hits: List[Dict[str, str]], bvk_hits: List[str]) -> str:
    has_eps = len(eps_hits) > 0
    has_bvk = len(bvk_hits) > 0
    today = datetime.now().strftime("%Y-%m-%d")

    if not has_eps and not has_bvk:
        return f"🎉 Danas {today}: nema ni struje ni vode — sve radi!"
    if has_eps and has_bvk:
        return f"⚡🚰 Danas {today}: isključenja struje + problemi sa vodom"
    if has_eps and not has_bvk:
        return f"⚡ Danas {today}: planirana isključenja struje"
    # only water
    return f"🚰 Danas {today}: kvarovi / obaveštenja o vodi"

def build_html_body(eps_hits: List[Dict[str, str]], bvk_hits: List[str], streets: List[str]) -> str:
    style = """
      body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,Arial; background:#0b0f14; color:#e6edf3; padding:24px;}
      .card{background:#111826; border:1px solid #1f2a37; border-radius:14px; padding:20px; margin-bottom:16px;}
      .badge{display:inline-block; padding:6px 10px; border-radius:999px; font-size:12px; margin-right:8px; border:1px solid #263241; background:#0f1620;}
      .ok{color:#34d399; border-color:#1f513f; background:#0e1c16;}
      .warn{color:#f59e0b; border-color:#5a441a; background:#1a150a;}
      .danger{color:#f97373; border-color:#5b2121; background:#1a0e0e;}
      .small{opacity:.8; font-size:12px;}
      .list{margin:0; padding-left:18px;}
      .pill{display:inline-block; font-size:12px; padding:5px 10px; border-radius:999px; background:#1a2432; border:1px solid #243244; margin:2px 6px 2px 0;}
      a{color:#93c5fd; text-decoration:none} a:hover{text-decoration:underline;}
      .grid{display:grid; grid-template-columns:1fr; gap:12px;}
      @media(min-width:700px){.grid{grid-template-columns:1fr 1fr;}}
    """

    header_joke = "☕ Ako danas nestane kofeina — bar neće struje. Šalimo se. 🙂"
    if not eps_hits and not bvk_hits:
        header_joke = "🎊 Sve radi! Idealno vreme da uključimo mašinu za veš *i* espreso."

    html = [f"""\
<!doctype html>
<html>
  <head><meta charset="utf-8"><meta name="color-scheme" content="dark light"><style>{style}</style></head>
  <body>
    <div class="card">
      <div style="font-size:18px; font-weight:600; margin-bottom:6px;">📬 EPS/BVK dnevni izveštaj</div>
      <div class="small">{datetime.now().strftime("%A, %d.%m.%Y.")} — Ulice posmatranja: {" • ".join(streets)}</div>
      <div style="margin-top:10px;" class="small">{header_joke}</div>
    </div>
"""]

    # Rezime bedževi
    if eps_hits:
        html.append('<span class="badge danger">⚡ Struja: pronađeni pogoci</span>')
    else:
        html.append('<span class="badge ok">⚡ Struja: bez planiranih isključenja</span>')
    if bvk_hits:
        html.append('<span class="badge warn">🚰 Voda: prijavljeni radovi/kvarovi</span>')
    else:
        html.append('<span class="badge ok">🚰 Voda: nema prijavljenih problema</span>')
    html.append("<br><br>")

    # EPS
    html.append('<div class="card"><div style="font-weight:600;margin-bottom:6px;">⚡ EPS (struja)</div>')
    if eps_hits:
        html.append('<div class="grid">')
        for h in eps_hits:
            html.append(f"""
              <div class="card" style="padding:14px;">
                <div style="margin-bottom:6px;">
                  <span class="pill">{'DANAS' if h['day']=='danas' else 'SUTRA'} • {h['date']}</span>
                  <span class="pill">Opština: {h['opstina']}</span>
                </div>
                <div><strong>Vreme:</strong> {h['vreme']}</div>
                <div style="margin-top:6px;"><strong>Ulice:</strong> {h['ulice']}</div>
                <div class="small" style="margin-top:8px;">Izvor: <a href="{h['url']}">{h['url']}</a></div>
              </div>
            """)
        html.append('</div>')
        html.append('<div class="small" style="margin-top:8px;">Tip: napunite baterije i skuvajte kafu unapred. ☕🔋</div>')
    else:
        html.append('<div>✅ Nema planiranih isključenja za tražene ulice.</div>')
    html.append("</div>")

    # BVK
    html.append('<div class="card"><div style="font-weight:600;margin-bottom:6px;">🚰 BVK (voda)</div>')
    if bvk_hits:
        html.append('<ul class="list">')
        for raw in bvk_hits:
            html.append(f'<li>{raw}</li>')
        html.append('</ul>')
        html.append(f'<div class="small" style="margin-top:8px;">Izvor: <a href="{BVK_URL}">{BVK_URL}</a></div>')
        html.append('<div class="small" style="margin-top:8px;">Tip: napunite bokale — za svaki slučaj. 💧</div>')
    else:
        html.append('<div>✅ Nema prijavljenih isključenja/kvarova vode za tražene ulice.</div>')
    html.append("</div>")

    # Bez footera
    html.append("""
  </body>
</html>
""")
    return "".join(html)

def build_text_body(eps_hits: List[Dict[str, str]], bvk_hits: List[str], streets: List[str]) -> str:
    lines = []
    lines.append(f"EPS/BVK dnevni izveštaj — {datetime.now().strftime('%A, %d.%m.%Y.')}")
    lines.append(f"Ulice posmatranja: {', '.join(streets)}")
    lines.append("")

    # EPS
    lines.append("⚡ EPS (struja)")
    if eps_hits:
        for h in eps_hits:
            when = "DANAS" if h["day"] == "danas" else "SUTRA"
            lines.append(f"• {when} ({h['date']}): {h['opstina']} | {h['vreme']} | {h['ulice']} (izvor: {h['url']})")
    else:
        lines.append("• Nema planiranih isključenja za tražene ulice.")
    lines.append("")

    # BVK
    lines.append("🚰 BVK (voda)")
    if bvk_hits:
        for raw in bvk_hits:
            lines.append(f"• {raw} (izvor: {BVK_URL})")
    else:
        lines.append("• Nema prijavljenih isključenja/kvarova vode za tražene ulice.")
    lines.append("")
    return "\n".join(lines)

def send_email(subject: str, html_body: str, text_body: str):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_to = os.getenv("EMAIL_TO")

    if not all([smtp_user, smtp_pass, email_to]):
        print("⚠️ Nedostaju SMTP kredencijali.")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg["Subject"] = subject

    part_text = MIMEText(text_body, "plain", "utf-8")
    part_html = MIMEText(html_body, "html", "utf-8")
    msg.attach(part_text)
    msg.attach(part_html)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"📧 Email poslat na {email_to} • Subject: {subject}")
    except Exception as e:
        print(f"⚠️ Greška pri slanju email-a: {e}")

# ===== MAIN =====
if __name__ == "__main__":
    streets = ["Sestara", "Nikodima", "Salvadora", "Vlajkovićeva", "Marijane", "Радмиловића"]

    eps_hits_all: List[Dict[str, str]] = []
    bvk_hits_all: List[str] = []

    for street in streets:
        eps_hits_all.extend(search_eps_hits(street))
        bvk_hits_all.extend(search_bvk_hits(street))

    # uniq BVK linije
    bvk_hits_all = list(dict.fromkeys(bvk_hits_all))

    subject = build_subject(eps_hits_all, bvk_hits_all)
    html_body = build_html_body(eps_hits_all, bvk_hits_all, streets)
    text_body = build_text_body(eps_hits_all, bvk_hits_all, streets)

    if not eps_hits_all and not bvk_hits_all:
        print("✅ Nema planiranih isključenja struje/vode za tražene ulice.")
    else:
        print("✅ Pronađeni rezultati (slanje email-a)…")

    send_email(subject, html_body, text_body)
