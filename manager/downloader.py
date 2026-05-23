"""Download Apache, PHP, MariaDB, phpMyAdmin, mkcert and set them up."""
import re
import secrets
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Optional

import requests

from manager.config import (
    DATA_DIR, APACHE_DIR, PHP_DIR, MARIADB_DIR, PHPMYADMIN_DIR, MKCERT_DIR,
    MKCERT_URL, PHPMYADMIN_URL,
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_APACHE_HEADERS = {
    **_HEADERS,
    "Referer": "https://www.apachelounge.com/download/",
    "Accept": "application/zip,application/octet-stream,*/*",
}

# ─── URL detection ────────────────────────────────────────────────────────────

# VS18 = VS2022 toolset (VC++2022 runtime), Win64 capitalisation matters
_APACHE_CANDIDATES = [
    "https://www.apachelounge.com/download/VS18/binaries/httpd-2.4.67-260504-Win64-VS18.zip",
    "https://www.apachelounge.com/download/VS18/binaries/httpd-2.4.63-250207-Win64-VS18.zip",
    "https://www.apachelounge.com/download/VS17/binaries/httpd-2.4.63-250207-win64-VS17.zip",
    "https://www.apachelounge.com/download/VS17/binaries/httpd-2.4.62-241211-win64-VS17.zip",
    "https://www.apachelounge.com/download/VS17/binaries/httpd-2.4.62-240909-win64-VS17.zip",
]

_MARIADB_VERSIONS = ["11.4.5", "11.4.4", "11.4.3", "11.4.2", "10.11.10", "10.11.9"]


def _find_apache_url() -> str:
    # 1) Parse Apache Lounge download page (most reliable)
    try:
        r = requests.get("https://www.apachelounge.com/download/",
                         timeout=12, headers=_APACHE_HEADERS)
        # Match both VS17 and VS18, win64 and Win64
        m = re.search(
            r'href=["\']([^"\']*httpd-[\d.]+-\d+-[Ww]in64-VS\d+\.zip)["\']',
            r.text, re.IGNORECASE,
        )
        if m:
            path = m.group(1)
            if path.startswith("http"):
                return path
            if path.startswith("/"):
                return "https://www.apachelounge.com" + path
            return "https://www.apachelounge.com/download/" + path.lstrip("/")
    except Exception:
        pass

    # 2) Verify each candidate serves actual zip bytes (Range request)
    for url in _APACHE_CANDIDATES:
        try:
            r = requests.get(url, headers={**_APACHE_HEADERS, "Range": "bytes=0-3"},
                             timeout=8, allow_redirects=True)
            if r.status_code in (200, 206) and r.content[:2] == b"PK":
                return url
        except Exception:
            continue

    return _APACHE_CANDIDATES[0]


def _find_mariadb_url() -> str:
    # archive.mariadb.org — direct download, no redirect, verified working
    for ver in _MARIADB_VERSIONS:
        url = (f"https://archive.mariadb.org/mariadb-{ver}"
               f"/winx64-packages/mariadb-{ver}-winx64.zip")
        try:
            r = requests.get(url, headers={**_HEADERS, "Range": "bytes=0-3"},
                             timeout=8, allow_redirects=True)
            if r.status_code in (200, 206) and r.content[:2] == b"PK":
                return url
        except Exception:
            continue
    return (f"https://archive.mariadb.org/mariadb-11.4.3"
            f"/winx64-packages/mariadb-11.4.3-winx64.zip")


# ─── Download helper ──────────────────────────────────────────────────────────

def _download(url: str, dest: Path,
              progress_cb: Optional[Callable[[float], None]] = None,
              extra_headers: dict = None) -> None:
    headers = {**_HEADERS, **(extra_headers or {})}
    resp = requests.get(url, stream=True, timeout=120, headers=headers,
                        allow_redirects=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    done = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(65536):
            f.write(chunk)
            done += len(chunk)
            if progress_cb and total:
                progress_cb(done / total)


def _is_valid_zip(path: Path) -> bool:
    """Check magic bytes (PK) then try to open as zip."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"PK":
                return False
        with zipfile.ZipFile(path) as zf:
            return len(zf.namelist()) > 0
    except Exception:
        return False


def _zip_error_detail(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            preview = f.read(80)
        if b"<html" in preview.lower() or b"<!doctype" in preview.lower():
            return "Server returned an HTML page instead of a zip file"
        return f"File starts with: {preview[:20]!r}"
    except Exception:
        return "Cannot read downloaded file"


# ─── Apache ───────────────────────────────────────────────────────────────────

def download_apache(progress_cb=None) -> tuple[bool, str]:
    url = ""
    zip_path = DATA_DIR / "_apache.zip"
    try:
        url = _find_apache_url()
        _download(url, zip_path, progress_cb, extra_headers=_APACHE_HEADERS)

        if not _is_valid_zip(zip_path):
            detail = _zip_error_detail(zip_path)
            zip_path.unlink(missing_ok=True)
            return False, f"{detail}\nURL: {url}"

        tmp = DATA_DIR / "_apache_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        extracted = next(p for p in tmp.iterdir() if p.is_dir())
        if APACHE_DIR.exists():
            shutil.rmtree(APACHE_DIR)
        shutil.move(str(extracted), str(APACHE_DIR))
        shutil.rmtree(tmp, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        return True, "ok"

    except requests.exceptions.ConnectionError:
        return False, "ไม่สามารถเชื่อมต่ออินเทอร์เน็ตได้"
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP Error {e.response.status_code} — URL: {url}"
    except zipfile.BadZipFile:
        zip_path.unlink(missing_ok=True)
        return False, f"ไฟล์ zip เสียหาย — URL: {url}"
    except Exception as e:
        zip_path.unlink(missing_ok=True)
        return False, str(e)


def is_apache_ready() -> bool:
    return (APACHE_DIR / "bin" / "httpd.exe").exists()


# ─── PHP ──────────────────────────────────────────────────────────────────────

_PHP_RELEASES_URL = "https://windows.php.net/downloads/releases/releases.json"
_PHP_RELEASES_BASE = "https://windows.php.net/downloads/releases/"
_PHP_ARCHIVE_BASE  = "https://windows.php.net/downloads/releases/archives/"

# Cache so we only fetch once per session
_php_releases_cache: dict | None = None


def _fetch_php_releases() -> dict:
    global _php_releases_cache
    if _php_releases_cache is not None:
        return _php_releases_cache
    try:
        r = requests.get(_PHP_RELEASES_URL, timeout=10, headers=_HEADERS)
        r.raise_for_status()
        _php_releases_cache = r.json()
    except Exception:
        _php_releases_cache = {}
    return _php_releases_cache


def _find_php_url(major_minor: str) -> str:
    """Return NTS x64 zip URL for a PHP major.minor, using live releases.json."""
    data = _fetch_php_releases()
    entry = data.get(major_minor, {})

    # Key format: "nts-vsXX-x64"
    nts_key = next((k for k in entry if k.startswith("nts-") and k.endswith("-x64")), None)
    if nts_key:
        filename = entry[nts_key].get("zip", {}).get("path", "")
        if filename:
            # Archived versions (7.4, 8.0) live in /archives/
            base = (_PHP_ARCHIVE_BASE
                    if major_minor in ("7.4", "8.0") else _PHP_RELEASES_BASE)
            return base + filename

    # Fallback: hardcoded last-known-good filenames
    _fallback = {
        "7.4": "php-7.4.33-nts-Win32-vc15-x64.zip",
        "8.0": "php-8.0.30-nts-Win32-vs16-x64.zip",
        "8.1": "php-8.1.34-nts-Win32-vs16-x64.zip",
        "8.2": "php-8.2.31-nts-Win32-vs16-x64.zip",
        "8.3": "php-8.3.31-nts-Win32-vs16-x64.zip",
        "8.4": "php-8.4.21-nts-Win32-vs17-x64.zip",
        "8.5": "php-8.5.0-nts-Win32-vs17-x64.zip",
    }
    if major_minor in _fallback:
        base = (_PHP_ARCHIVE_BASE
                if major_minor in ("7.4", "8.0") else _PHP_RELEASES_BASE)
        return base + _fallback[major_minor]

    return ""


def download_php(version: str, progress_cb=None) -> tuple[bool, str]:
    zip_path = DATA_DIR / f"_php{version}.zip"
    url = ""
    try:
        url = _find_php_url(version)
        if not url:
            return False, f"ไม่พบ URL สำหรับ PHP {version}"

        _download(url, zip_path, progress_cb)

        if not _is_valid_zip(zip_path):
            detail = _zip_error_detail(zip_path)
            zip_path.unlink(missing_ok=True)
            return False, f"{detail}\nURL: {url}"

        php_dir = PHP_DIR / version
        if php_dir.exists():
            shutil.rmtree(php_dir)
        php_dir.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(php_dir)
        zip_path.unlink(missing_ok=True)
        _setup_php_ini(version)
        return True, f"PHP {version} installed OK"

    except requests.exceptions.HTTPError as e:
        zip_path.unlink(missing_ok=True)
        return False, f"HTTP {e.response.status_code} — {url}"
    except requests.exceptions.ConnectionError:
        zip_path.unlink(missing_ok=True)
        return False, "ไม่สามารถเชื่อมต่ออินเทอร์เน็ตได้"
    except Exception as e:
        zip_path.unlink(missing_ok=True)
        return False, str(e)


def _setup_php_ini(version: str):
    php_dir = PHP_DIR / version
    ini = php_dir / "php.ini"
    src = php_dir / "php.ini-development"
    if not ini.exists() and src.exists():
        shutil.copy(src, ini)
    if not ini.exists():
        return
    ext_dir = (php_dir / "ext").as_posix()
    text = ini.read_text(encoding="utf-8", errors="replace")
    # Uncomment and set extension_dir to absolute path (handles both "; ext" and ";ext")
    text = re.sub(
        r'^;?\s*extension_dir\s*=\s*["\']?(?:ext|\./)["\'.]?',
        f'extension_dir = "{ext_dir}"',
        text, flags=re.MULTILINE | re.IGNORECASE,
    )
    for ext in ["pdo_mysql", "mysqli", "mbstring", "json",
                "curl", "zip", "gd", "intl", "openssl", "fileinfo", "exif"]:
        text = re.sub(rf"^;(extension\s*=\s*{ext})", r"\1",
                      text, flags=re.MULTILINE | re.IGNORECASE)

    # Suppress PHP warnings/deprecations in HTTP responses — otherwise they
    # pollute JSON/AJAX bodies (phpMyAdmin reports "OK (rejected)" for them).
    # Errors still go to the log file.
    text = re.sub(r'^\s*display_errors\s*=.*$', 'display_errors = Off',
                  text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^\s*display_startup_errors\s*=.*$', 'display_startup_errors = Off',
                  text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^\s*error_reporting\s*=.*$',
                  'error_reporting = E_ALL & ~E_DEPRECATED & ~E_STRICT & ~E_NOTICE',
                  text, flags=re.MULTILINE | re.IGNORECASE)
    ini.write_text(text, encoding="utf-8")


def is_php_ready(version: str) -> bool:
    return (PHP_DIR / version / "php-cgi.exe").exists()


# ─── MariaDB ──────────────────────────────────────────────────────────────────

def download_mariadb(progress_cb=None) -> tuple[bool, str]:
    url = ""
    zip_path = DATA_DIR / "_mariadb.zip"
    try:
        url = _find_mariadb_url()
        _download(url, zip_path, progress_cb)

        if not _is_valid_zip(zip_path):
            zip_path.unlink(missing_ok=True)
            return False, f"ไฟล์ที่ดาวน์โหลดมาไม่ใช่ zip (URL อาจผิด)\n{url}"

        tmp = DATA_DIR / "_mariadb_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        extracted = next(p for p in tmp.iterdir() if p.is_dir())
        if MARIADB_DIR.exists():
            shutil.rmtree(MARIADB_DIR)
        shutil.move(str(extracted), str(MARIADB_DIR))
        shutil.rmtree(tmp, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        return True, "ok"

    except requests.exceptions.ConnectionError:
        return False, "ไม่สามารถเชื่อมต่ออินเทอร์เน็ตได้"
    except requests.exceptions.HTTPError as e:
        zip_path.unlink(missing_ok=True)
        return False, f"HTTP Error {e.response.status_code} — URL: {url}"
    except zipfile.BadZipFile:
        zip_path.unlink(missing_ok=True)
        return False, f"ไฟล์ zip เสียหาย — URL: {url}"
    except Exception as e:
        zip_path.unlink(missing_ok=True)
        return False, str(e)


def is_mariadb_ready() -> bool:
    return (MARIADB_DIR / "bin" / "mysqld.exe").exists()


# ─── phpMyAdmin ───────────────────────────────────────────────────────────────

def download_phpmyadmin(progress_cb=None) -> tuple[bool, str]:
    zip_path = DATA_DIR / "_phpmyadmin.zip"
    try:
        _download(PHPMYADMIN_URL, zip_path, progress_cb)
        if not _is_valid_zip(zip_path):
            zip_path.unlink(missing_ok=True)
            return False, "ไฟล์ phpMyAdmin ไม่ใช่ zip จริง"

        tmp = DATA_DIR / "_pma_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        extracted = next(p for p in tmp.iterdir() if p.is_dir())
        if PHPMYADMIN_DIR.exists():
            shutil.rmtree(PHPMYADMIN_DIR)
        shutil.move(str(extracted), str(PHPMYADMIN_DIR))
        shutil.rmtree(tmp, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        _write_phpmyadmin_config()
        return True, "ok"
    except Exception as e:
        zip_path.unlink(missing_ok=True)
        return False, str(e)


def _write_phpmyadmin_config():
    secret = secrets.token_hex(16)
    cfg = f"""<?php
declare(strict_types=1);
$cfg['blowfish_secret'] = '{secret}';
$i = 0;
$i++;
$cfg['Servers'][$i]['auth_type']       = 'cookie';
$cfg['Servers'][$i]['host']            = '127.0.0.1';
$cfg['Servers'][$i]['port']            = '3306';
$cfg['Servers'][$i]['compress']        = false;
$cfg['Servers'][$i]['AllowNoPassword'] = true;
$cfg['UploadDir'] = '';
$cfg['SaveDir']   = '';
$cfg['TempDir']   = sys_get_temp_dir();
"""
    (PHPMYADMIN_DIR / "config.inc.php").write_text(cfg, encoding="utf-8")


def is_phpmyadmin_ready() -> bool:
    return (PHPMYADMIN_DIR / "index.php").exists()


# ─── mkcert ───────────────────────────────────────────────────────────────────

def download_mkcert(progress_cb=None) -> tuple[bool, str]:
    try:
        MKCERT_DIR.mkdir(parents=True, exist_ok=True)
        _download(MKCERT_URL, MKCERT_DIR / "mkcert.exe", progress_cb)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def is_mkcert_ready() -> bool:
    return (MKCERT_DIR / "mkcert.exe").exists()
