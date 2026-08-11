#!/usr/bin/env python3
import os
import json
import re
import sys
import subprocess
import tempfile
import sqlite3
import time
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

# ============================================================
# KONFIGURASI
# ============================================================
URLS = [
    "https://9tsu.in/douga/125726.html",
    "https://9tsu.one/douga/34833.html",
    "https://9tsu.vip/125726.html",
    "https://9tsu.in/douga/126009.html",
]

TARGET_REPOS = [
    "https://github.com/herycp/9tsu-Plugins",
    "https://github.com/herycp/Drmx-extraxt",
    "https://github.com/herycp/Daur-ulangLink",
    "https://github.com/herycp/Pengepul-link",
]

JSON_FILE = "link-sekarang.json"
PAT = os.environ.get("PAT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# ============================================================
# VALIDASI
# ============================================================
if not PAT:
    print("❌ ERROR: PAT_TOKEN tidak diset.")
    sys.exit(1)

if not GITHUB_TOKEN:
    print("❌ ERROR: GITHUB_TOKEN tidak tersedia.")
    sys.exit(1)

# ============================================================
# BACA JSON SAAT INI
# ============================================================
try:
    with open(JSON_FILE, "r") as f:
        current = json.load(f)
    old_domain = current["domain"]
    old_base = current["Base"]
    print(f"📌 Domain saat ini: {old_domain}")
    print(f"📌 Base saat ini: {old_base}")
except Exception as e:
    print(f"❌ Gagal baca {JSON_FILE}: {e}")
    sys.exit(1)

# ============================================================
# BUAT SESSION DENGAN HEADER LENGKAP + COOKIE
# ============================================================
def create_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    })
    return session

# ============================================================
# EKSTRAK DOMAIN DARI URL (dengan session & cookie)
# ============================================================
def extract_domain(page_url, retries=3):
    # Parse domain utama untuk referer
    parsed = urlparse(page_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    session = create_session()

    # Langkah 1: Kunjungi halaman utama untuk mendapatkan cookie
    try:
        print(f"  🍪 Mengambil cookie dari {base_url}...")
        session.get(base_url, timeout=10)
    except Exception as e:
        print(f"  ⚠️ Gagal ambil cookie: {e}")

    # Langkah 2: Akses URL target dengan referer
    session.headers.update({'Referer': base_url})

    for attempt in range(retries):
        try:
            print(f"  📡 Mencoba {page_url} (percobaan {attempt+1}/{retries})...")
            resp = session.get(page_url, timeout=20, allow_redirects=True)
            print(f"     Status: {resp.status_code}")

            if resp.status_code == 403:
                print("     ⚠️ 403 - coba refresh cookie...")
                # Refresh cookie dengan kunjungi ulang halaman utama
                session.get(base_url, timeout=10)
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                else:
                    break

            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            player = soup.find("div", id="player-embed")
            if not player:
                print("⚠️ Tidak ditemukan div#player-embed")
                return None
            iframe = player.find("iframe")
            if not iframe or not iframe.get("src"):
                print("⚠️ Tidak ditemukan iframe")
                return None
            src = iframe["src"]
            parsed_src = urlparse(src)
            domain = parsed_src.netloc
            if not domain:
                print("⚠️ Domain kosong")
                return None
            return domain
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Percobaan {attempt+1}/{retries} gagal: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    return None

# ============================================================
# CARI DOMAIN BARU
# ============================================================
print("\n🔍 Mencari domain baru...")
new_domain = None
for url in URLS:
    dom = extract_domain(url)
    if dom:
        new_domain = dom
        print(f"✅ Domain ditemukan dari {url}: {new_domain}")
        break

if not new_domain:
    print("❌ Tidak ada domain yang bisa diekstrak. Keluar.")
    sys.exit(1)

if new_domain == old_domain:
    print("✅ Domain masih sama. Tidak ada perubahan.")
    sys.exit(0)

new_base = new_domain.split('.')[0]
print(f"✅ Domain baru: {new_domain}")
print(f"✅ Base baru: {new_base}")

# ============================================================
# FUNGSI UPDATE SQLITE
# ============================================================
def update_sqlite_db(db_path, old_str, new_str, label=""):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        total = 0
        for (table_name,) in tables:
            cursor.execute(f"PRAGMA table_info({table_name})")
            cols = cursor.fetchall()
            for col in cols:
                col_name = col[1]
                col_type = col[2].upper()
                if any(t in col_type for t in ('TEXT','VARCHAR','CHAR','CLOB')):
                    sql = f"UPDATE {table_name} SET {col_name} = REPLACE({col_name}, ?, ?) WHERE {col_name} LIKE ?"
                    cursor.execute(sql, (old_str, new_str, f'%{old_str}%'))
                    total += cursor.rowcount
        conn.commit()
        conn.close()
        if total > 0:
            print(f"  ✅ DB {db_path} {label}: {total} baris diupdate")
    except Exception as e:
        print(f"  ⚠️ Gagal update DB {db_path}: {e}")

# ============================================================
# FUNGSI UPDATE FILE TEKS
# ============================================================
def update_text_file(filepath, old_d, new_d, old_b, new_b):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        return False
    new_content = re.sub(re.escape(old_d), new_d, content, flags=re.IGNORECASE)
    new_content = re.sub(re.escape(old_b), new_b, new_content, flags=re.IGNORECASE)
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

# ============================================================
# PROSES SEMUA REPO
# ============================================================
print("\n" + "="*60)
print("🚀 MEMULAI UPDATE SEMUA REPOSITORI")
print("="*60)

for repo_url in TARGET_REPOS:
    print(f"\n📦 --- {repo_url} ---")
    repo_name = repo_url.split('/')[-1]
    clone_url = repo_url.replace("https://", f"https://{PAT}@")
    target_dir = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "clone", "--depth", "1", clone_url, target_dir], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Gagal clone: {e.stderr.decode()}")
        continue

    os.chdir(target_dir)
    files_upd = 0
    dbs_upd = 0

    for root, dirs, files in os.walk('.'):
        if '.git' in root:
            continue
        for file in files:
            filepath = os.path.join(root, file)
            if file.endswith(('.db','.sqlite','.sqlite3')):
                update_sqlite_db(filepath, old_domain, new_domain, "domain")
                update_sqlite_db(filepath, old_base, new_base, "base")
                dbs_upd += 1
                continue
            if update_text_file(filepath, old_domain, new_domain, old_base, new_base):
                files_upd += 1
                print(f"  📝 {filepath}")

    if files_upd > 0 or dbs_upd > 0:
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"Update domain: {old_domain} -> {new_domain}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"✅ {repo_name} selesai")
    else:
        print(f"ℹ️ Tidak ada perubahan di {repo_name}")

    os.chdir(os.environ["GITHUB_WORKSPACE"])

# ============================================================
# UPDATE JSON
# ============================================================
print("\n📝 Update link-sekarang.json")
with open(JSON_FILE, "w") as f:
    json.dump({"Base": new_base, "domain": new_domain}, f, indent=4)

subprocess.run(["git", "add", JSON_FILE], check=True)
status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
if status.stdout.strip():
    remote = f"https://{GITHUB_TOKEN}@github.com/{os.environ['GITHUB_REPOSITORY']}.git"
    subprocess.run(["git", "commit", "-m", f"Update domain ke {new_domain}"], check=True)
    subprocess.run(["git", "push", remote, "HEAD:main"], check=True)
    print("✅ JSON diperbarui")
else:
    print("ℹ️ JSON tidak berubah")

print("\n🎉 SELESAI!")
