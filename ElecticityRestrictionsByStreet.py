import requests
from bs4 import BeautifulSoup
import cyrtranslit
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

URLS = {
    "danas": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_0_Iskljucenja.htm",
    "sutra": "https://elektrodistribucija.rs/planirana-iskljucenja-beograd/Dan_1_Iskljucenja.htm"
}

def load_data(url):
    """Učitaj i parsiraj HTML tabelu."""
    try:
        response = requests.get(url, headers=HEADERS)
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
        print(f"⚠️ Greška pri čitanju: {e}")
        return []


def search(query):
    """Pretraži i javi da li ima isključenja danas ili sutra."""
    # Ako query latinica → prebaci u ćirilicu
    if all("a" <= ch.lower() <= "z" or ch.isspace() for ch in query):
        target = cyrtranslit.to_cyrillic(query, "sr")
    else:
        target = query

    results = []

    for day, url in URLS.items():
        data = load_data(url)
        for opstina, vreme, ulice in data:
            if target.upper() in ulice.upper():
                if day == "danas":
                    datum = datetime.now().strftime("%Y-%m-%d")
                    results.append(f"📅 DANAS ({datum}): {opstina} | {vreme} | {ulice}")
                else:
                    datum = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                    results.append(f"📅 SUTRA ({datum}): {opstina} | {vreme} | {ulice}")

    if results:
        return "\n\n".join(results)
    else:
        return "✅ Nema planiranih isključenja danas ni sutra."


if __name__ == "__main__":
    while True:
        q = input("\nUnesi ulicu (latinica ili ćirilica, Enter za kraj): ").strip()
        if not q:
            break
        print(search(q))
