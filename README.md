# Mamp Poo

Local development environment manager for Windows — a lightweight alternative to MAMP Pro.  
Manages Apache, PHP-CGI (multiple versions), and MariaDB through a single dark-themed GUI.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- **One-click start/stop** — Apache, PHP-CGI, and MariaDB start automatically on launch
- **Multiple PHP versions** — 7.4, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5 (switch per site)
- **Virtual host management** — add local domains with custom document roots
- **HTTPS support** — auto-generates trusted local SSL certificates via [mkcert](https://github.com/FiloSottile/mkcert)
- **phpMyAdmin built-in** — accessible at `localhost/phpmyadmin`
- **System tray** — close the window and services keep running in the background
- **Auto-download** — downloads and installs Apache, MariaDB, PHP, phpMyAdmin on first run
- **Portable data** — all binaries stored in `%APPDATA%\LocalDevManager` (no PATH pollution)

---

## Requirements

- Windows 10 / 11 (64-bit)
- Python 3.10+
- Internet connection (first run only — to download Apache, PHP, MariaDB)

---

## Quick Start

### Run from source

```bat
git clone <repo-url>
cd mamp_poo
pip install -r requirements.txt
python main.py
```

On first launch a Setup dialog will appear to download and install all required components.

### Build as standalone `.exe`

```bat
build_exe.bat
```

Output: `dist\Mamp Poo.exe` — a single portable executable, no Python required.

---

## Project Structure

```
mamp_poo/
├── main.py               # Entry point — auto-installs missing packages
├── manager/
│   ├── config.py         # Config dataclasses, paths, constants
│   ├── server.py         # Start/stop Apache, PHP-CGI, MariaDB
│   ├── downloader.py     # Download & extract Apache, PHP, MariaDB, phpMyAdmin
│   ├── ssl.py            # mkcert wrapper — generate local SSL certs
│   ├── hosts.py          # Edit Windows hosts file
│   └── fcgi_proxy.py     # FastCGI proxy (workaround for Apache mod_proxy_fcgi on Windows)
├── ui/
│   ├── app.py            # Main window
│   ├── sites_page.py     # Virtual host management page
│   ├── php_page.py       # PHP version management page
│   ├── dialogs.py        # Setup dialog
│   └── tray.py           # System tray icon
├── requirements.txt
└── build_exe.bat         # PyInstaller build script
```

---

## Data Directory

All binaries and config are stored in `%APPDATA%\LocalDevManager\` — never inside the project folder.

| Path | Contents |
|---|---|
| `apache/` | Apache httpd binaries + generated config |
| `php/<version>/` | PHP-CGI binaries per version |
| `mariadb/` | MariaDB binaries |
| `mariadb_data/` | Database files (survives reinstall) |
| `phpmyadmin/` | phpMyAdmin files |
| `certs/` | mkcert SSL certificates |
| `config.json` | App settings and virtual host list |

---

## Ports

| Service | Default Port |
|---|---|
| Apache HTTP | 80 |
| Apache HTTPS | 443 |
| PHP 7.4 (FastCGI) | 9074 |
| PHP 8.0 | 9080 |
| PHP 8.1 | 9081 |
| PHP 8.2 | 9082 |
| PHP 8.3 | 9083 |
| PHP 8.4 | 9084 |
| PHP 8.5 | 9085 |
| MariaDB | 3306 |

> Port 80/443 requires Administrator privileges. Change to 8080/8443 in Settings to run without elevation.

---

## Notes

- **First run** requires internet access to download ~150 MB of components
- **MariaDB root password** is empty by default (local dev only)
- **HTTPS** requires running the mkcert install step once (installs a local CA into the system trust store)
- The `.exe` build uses `--onefile` mode; first launch extracts to a temp directory and may take a few seconds
