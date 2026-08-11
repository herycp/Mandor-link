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
# HEADER UNTUK MENGHINDARI 403
# ============================================================
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

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
# EKSTRAK DOMAIN DARI URL (dengan retry dan header)
# ============================================================
def extract_domain(page_url, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(page_url, timeout=15, headers=HEADERS)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            player = soup.find("div", id="player-embed")
            if not player:
                print(f"⚠️ Tidak ditemukan div#player-embed di {page_url}")
                return None
            iframe = player.find("iframe")
            if not iframe or not iframe.get("src"):
                print(f"⚠️ Tidak ditemukan iframe di dalam div#player-embed di {page_url}")
                return None
            src = iframe["src"]
            parsed = urlparse(src)
            domain = parsed.netloc
            if not domain:
                print(f"⚠️ Domain kosong dari src: {src}")
                return None
            return domain
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Percobaan {attempt+1}/{retries} gagal untuk {page_url}: {e}")
            time.sleep(2)  # jeda sebelum retry
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
        total_updated = 0
        for (table_name,) in tables:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            for col in columns:
                col_name = col[1]
                col_type = col[2].upper()
                if any(t in col_type for t in ('TEXT', 'VARCHAR', 'CHAR', 'CLOB')):
                    sql = f"UPDATE {table_name} SET {col_name} = REPLACE({col_name}, ?, ?) WHERE {col_name} LIKE ?"
                    cursor.execute(sql, (old_str, new_str, f'%{old_str}%'))
                    total_updated += cursor.rowcount
        conn.commit()
        conn.close()
        if total_updated > 0:
            print(f"  ✅ DB {db_path} {label}: {total_updated} baris diperbarui.")
    except Exception as e:
        print(f"  ⚠️ Gagal update DB {db_path}: {e}")

# ============================================================
# FUNGSI UPDATE FILE TEKS
# ============================================================
def update_text_file(filepath, old_domain_str, new_domain_str, old_base_str, new_base_str):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except (UnicodeDecodeError, PermissionError):
        return False

    # DOMAIN dulu (case-insensitive)
    new_content = re.sub(re.escape(old_domain_str), new_domain_str, content, flags=re.IGNORECASE)
    # BASE kedua (case-insensitive)
    new_content = re.sub(re.escape(old_base_str), new_base_str, new_content, flags=re.IGNORECASE)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

# ============================================================
# PROSES SETIAP REPO TARGET
# ============================================================
print("\n" + "=" * 60)
print("🚀 MEMULAI PROSES UPDATE SEMUA REPOSITORI")
print("=" * 60)

for repo_url in TARGET_REPOS:
    print(f"\n📦 --- Memproses {repo_url} ---")
    repo_name = repo_url.split('/')[-1]

    # Clone repo
    clone_url = repo_url.replace("https://", f"https://{PAT}@")
    target_dir = tempfile.mkdtemp()
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, target_dir],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError as e:
        print(f"❌ Gagal clone {repo_name}: {e.stderr.decode()}")
        continue

    os.chdir(target_dir)
    files_updated = 0
    db_updated = 0

    # Loop semua file
    for root, dirs, files in os.walk('.'):
        if '.git' in root:
            continue
        for file in files:
            filepath = os.path.join(root, file)

            # SQLite
            if file.endswith(('.db', '.sqlite', '.sqlite3')):
                update_sqlite_db(filepath, old_domain, new_domain, "domain")
                update_sqlite_db(filepath, old_base, new_base, "base")
                db_updated += 1
                continue

            # File teks
            if update_text_file(filepath, old_domain, new_domain, old_base, new_base):
                files_updated += 1
                print(f"  📝 Diperbarui: {filepath}")

    # Commit & push
    if files_updated > 0 or db_updated > 0:
        subprocess.run(["git", "add", "."], check=True)
        commit_msg = f"Update domain: {old_domain} -> {new_domain} | Files: {files_updated} | DBs: {db_updated}"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"✅ {repo_name} berhasil diperbarui.")
    else:
        print(f"ℹ️ Tidak ada perubahan di {repo_name}.")

    os.chdir(os.environ["GITHUB_WORKSPACE"])

# ============================================================
# UPDATE JSON DI REPO ASAL
# ============================================================
print("\n" + "=" * 60)
print("📝 MEMPERBARUI LINK-SEKARANG.JSON")
print("=" * 60)

with open(JSON_FILE, "w") as f:
    json.dump({"Base": new_base, "domain": new_domain}, f, indent=4)

subprocess.run(["git", "add", JSON_FILE], check=True)
status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)

if status.stdout.strip():
    remote_url = f"https://{GITHUB_TOKEN}@github.com/{os.environ['GITHUB_REPOSITORY']}.git"
    subprocess.run(["git", "commit", "-m", f"Update domain ke {new_domain}"], check=True)
    subprocess.run(["git", "push", remote_url, "HEAD:main"], check=True)
    print("✅ JSON di repo asal berhasil diperbarui.")
else:
    print("ℹ️ JSON tidak berubah.")

print("\n" + "=" * 60)
print("🎉 SELESAI! SEMUA REPOSITORI TELAH DIPERBARUI.")
print("=" * 60)
