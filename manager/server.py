"""Start/stop Apache, PHP-CGI, and MariaDB processes."""
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from manager.config import (
    APACHE_DIR, PHP_DIR, MARIADB_DIR, MARIADB_DATA, PHPMYADMIN_DIR,
    CERTS_DIR, VHOSTS_DIR, DATA_DIR,
    PHP_PORTS, PHP_VERSIONS, AppConfig, VHost,
)

# ─── Process handles ──────────────────────────────────────────────────────────
_apache_proc: Optional[subprocess.Popen] = None
_php_procs: Dict[str, subprocess.Popen] = {}
_fcgi_proxy_threads: Dict[str, "threading.Thread"] = {}
_fcgi_proxy_stop: Dict[str, "threading.Event"] = {}
_mariadb_proc: Optional[subprocess.Popen] = None

# PHP-CGI listens on PHP_PORTS[v] + PROXY_OFFSET; the FCGI proxy
# listens on PHP_PORTS[v] (where Apache connects).
_PROXY_OFFSET = 10000

_CREATE_NO_WINDOW = 0x08000000

def _si():
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def _run(cmd, cwd=None) -> subprocess.Popen:
    return subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        startupinfo=_si(),
        creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def _run_wait(cmd, cwd=None, timeout=15) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, startupinfo=_si(),
            creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


# ─── MariaDB ──────────────────────────────────────────────────────────────────

def _write_mariadb_ini():
    """Write my.ini with absolute paths so mysqld always finds its files."""
    MARIADB_DATA.mkdir(parents=True, exist_ok=True)
    ini = MARIADB_DIR / "my.ini"
    ini.write_text(
        "[mysqld]\n"
        f"basedir={MARIADB_DIR.as_posix()}\n"
        f"datadir={MARIADB_DATA.as_posix()}\n"
        "port=3306\n"
        "character-set-server=utf8mb4\n"
        "collation-server=utf8mb4_unicode_ci\n"
        "sql_mode=NO_ENGINE_SUBSTITUTION\n"
        "[client]\n"
        "port=3306\n",
        encoding="utf-8",
    )


def initialize_mariadb() -> tuple[bool, str]:
    """Clean-slate initialization of MARIADB_DATA.
    Called only when config.mariadb_initialized is False.
    Safe to call even when MARIADB_DATA has leftover files from zip extraction.
    """
    mysqld       = MARIADB_DIR / "bin" / "mysqld.exe"
    mysql_install = MARIADB_DIR / "bin" / "mysql_install_db.exe"

    if not mysqld.exists():
        return False, "MariaDB not downloaded"

    # Wipe leftover data from zip (the zip ships an incomplete mysql/ dir)
    if MARIADB_DATA.exists():
        shutil.rmtree(MARIADB_DATA)
    MARIADB_DATA.mkdir(parents=True)

    _write_mariadb_ini()

    # mysql_install_db.exe is the recommended Windows initializer
    if mysql_install.exists():
        cmd = [
            str(mysql_install),
            f"--datadir={MARIADB_DATA}",
            "--password=",          # empty root password
        ]
    else:
        cmd = [
            str(mysqld),
            "--initialize-insecure",
            f"--basedir={MARIADB_DIR.as_posix()}",
            f"--datadir={MARIADB_DATA.as_posix()}",
            "--console",
        ]

    code, msg = _run_wait(cmd, cwd=str(MARIADB_DIR / "bin"), timeout=120)
    success = (MARIADB_DATA / "mysql").exists()
    if not success:
        return False, (msg[-600:] if msg else "Initialization produced no mysql/ dir")
    return True, "ok"


def start_mariadb() -> tuple[bool, str]:
    global _mariadb_proc
    if is_mariadb_running():
        return True, "already running"

    mysqld = MARIADB_DIR / "bin" / "mysqld.exe"
    if not mysqld.exists():
        return False, "MariaDB not downloaded"

    if not (MARIADB_DATA / "mysql").exists():
        return False, "MariaDB not initialized — open Setup and click Initialize"

    _write_mariadb_ini()
    ini = MARIADB_DIR / "my.ini"

    try:
        _mariadb_proc = _run([
            str(mysqld),
            f"--defaults-file={ini}",
            "--console",
        ], cwd=str(MARIADB_DIR / "bin"))
        time.sleep(2.5)
        if _mariadb_proc.poll() is not None:
            err = _mariadb_proc.stderr.read().decode(errors="replace")[-600:]
            return False, err or "MariaDB exited immediately"
        return True, "ok"
    except Exception as e:
        return False, str(e)


def stop_mariadb() -> bool:
    global _mariadb_proc
    # Graceful shutdown via mysqladmin
    mysqladmin = MARIADB_DIR / "bin" / "mysqladmin.exe"
    if mysqladmin.exists():
        _run_wait([str(mysqladmin), "-u", "root", "--protocol=TCP",
                   "--connect-timeout=3", "shutdown"], timeout=8)
    if _mariadb_proc:
        try:
            _mariadb_proc.terminate()
            _mariadb_proc.wait(timeout=5)
        except Exception:
            pass
        _mariadb_proc = None
    return True


def is_mariadb_running() -> bool:
    return _mariadb_proc is not None and _mariadb_proc.poll() is None


# ─── PHP-CGI ──────────────────────────────────────────────────────────────────

def start_php(version: str) -> tuple[bool, str]:
    import threading
    from manager import fcgi_proxy

    if version in _php_procs and _php_procs[version].poll() is None:
        return True, "already running"

    php_cgi = PHP_DIR / version / "php-cgi.exe"
    if not php_cgi.exists():
        return False, f"PHP {version} not installed"

    port = PHP_PORTS.get(version)
    if not port:
        return False, "Unknown version"

    backend_port = port + _PROXY_OFFSET  # real PHP-CGI listens here

    try:
        # 1) Start real PHP-CGI on internal port
        proc = _run(
            [str(php_cgi), "-b", f"127.0.0.1:{backend_port}"],
            cwd=str(PHP_DIR / version),
        )
        time.sleep(0.5)
        if proc.poll() is not None:
            err = proc.stderr.read().decode(errors="replace")[-300:]
            return False, err or "exited immediately"
        _php_procs[version] = proc

        # 2) Start FCGI proxy on external port (Apache connects here).
        #    Workaround for Apache mod_proxy_fcgi bug on Windows where
        #    SCRIPT_FILENAME gets a "proxy:fcgi://host:port/" prefix that
        #    PHP-CGI can't open ("No input file specified.").
        stop_event = threading.Event()
        t = threading.Thread(
            target=fcgi_proxy.serve_threaded,
            args=(port, backend_port, stop_event),
            daemon=True,
        )
        t.start()
        _fcgi_proxy_threads[version] = t
        _fcgi_proxy_stop[version] = stop_event
        time.sleep(0.2)
        return True, f"port {port} (proxy -> {backend_port})"
    except Exception as e:
        return False, str(e)


def stop_php(version: str) -> bool:
    # Stop FCGI proxy
    stop_event = _fcgi_proxy_stop.pop(version, None)
    if stop_event:
        stop_event.set()
    _fcgi_proxy_threads.pop(version, None)
    # Stop real PHP-CGI
    proc = _php_procs.pop(version, None)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass
    return True


def stop_all_php():
    for v in list(_php_procs):
        stop_php(v)


def is_php_running(version: str) -> bool:
    p = _php_procs.get(version)
    return p is not None and p.poll() is None


# ─── Apache ───────────────────────────────────────────────────────────────────

def start_apache(config: AppConfig = None) -> tuple[bool, str]:
    global _apache_proc
    if is_apache_running():
        return True, "already running"

    httpd = APACHE_DIR / "bin" / "httpd.exe"
    if not httpd.exists():
        return False, "Apache not downloaded"

    write_apache_conf(config)

    try:
        _apache_proc = _run(
            [str(httpd), "-d", APACHE_DIR.as_posix()],
            cwd=str(APACHE_DIR / "bin"),
        )
        time.sleep(1.2)
        if _apache_proc.poll() is not None:
            err = _apache_proc.stderr.read().decode(errors="replace")[-600:]
            return False, err or "Apache exited immediately"
        return True, "ok"
    except Exception as e:
        return False, str(e)


def stop_apache() -> bool:
    global _apache_proc
    httpd = APACHE_DIR / "bin" / "httpd.exe"
    try:
        _run_wait([str(httpd), "-d", APACHE_DIR.as_posix(), "-k", "stop"], timeout=5)
    except Exception:
        pass
    if _apache_proc:
        try:
            _apache_proc.terminate()
            _apache_proc.wait(timeout=5)
        except Exception:
            pass
        _apache_proc = None
    return True


def reload_apache(config: AppConfig = None) -> tuple[bool, str]:
    if not is_apache_running():
        return start_apache(config)
    write_apache_conf(config)
    httpd = APACHE_DIR / "bin" / "httpd.exe"
    code, msg = _run_wait(
        [str(httpd), "-d", APACHE_DIR.as_posix(), "-k", "graceful"], timeout=5
    )
    return code == 0, msg


def is_apache_running() -> bool:
    return _apache_proc is not None and _apache_proc.poll() is None


# ─── Start / Stop all ─────────────────────────────────────────────────────────

def start_all(config: AppConfig) -> list[str]:
    """Start MariaDB → PHP versions → Apache. Returns list of error messages."""
    errors = []

    ok, msg = start_mariadb()
    if not ok:
        errors.append(f"MariaDB: {msg}")

    needed = {v.php_version for v in config.vhosts if v.enabled}
    # Always start at least one PHP (for phpMyAdmin)
    from manager.downloader import is_php_ready
    installed = [ver for ver in PHP_VERSIONS if is_php_ready(ver)]
    needed |= {installed[0]} if installed and not needed else set()

    for ver in needed:
        ok, msg = start_php(ver)
        if not ok:
            errors.append(f"PHP {ver}: {msg}")

    ok, msg = start_apache(config)
    if not ok:
        errors.append(f"Apache: {msg}")

    return errors


def stop_all():
    stop_apache()
    stop_all_php()
    stop_mariadb()


# ─── Apache config generation ─────────────────────────────────────────────────

def write_apache_conf(config: AppConfig = None):
    """Write httpd.conf and regenerate all vhost configs."""
    if not APACHE_DIR.exists():
        return

    VHOSTS_DIR.mkdir(parents=True, exist_ok=True)
    logs_dir = APACHE_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)

    apache_root = APACHE_DIR.as_posix()
    pma_root = PHPMYADMIN_DIR.as_posix()

    # Use highest installed PHP for phpMyAdmin
    from manager.downloader import is_php_ready
    pma_php_port = next(
        (PHP_PORTS[v] for v in PHP_VERSIONS if is_php_ready(v)),
        9085,
    )

    http_port = config.http_port if config else 80
    https_port = config.https_port if config else 443

    has_ssl = config and any(v.https_enabled for v in config.vhosts if v.enabled)
    ssl_listen = f"Listen {https_port}" if has_ssl else ""
    ssl_modules = """\
LoadModule ssl_module modules/mod_ssl.so
LoadModule socache_shmcb_module modules/mod_socache_shmcb.so""" if has_ssl else ""
    ssl_global = """\
SSLSessionCache "shmcb:logs/ssl_scache(512000)"
SSLSessionCacheTimeout 300""" if has_ssl else ""

    httpd_conf = f"""ServerRoot "{apache_root}"
Listen {http_port}
{ssl_listen}

LoadModule actions_module modules/mod_actions.so
LoadModule alias_module modules/mod_alias.so
LoadModule auth_basic_module modules/mod_auth_basic.so
LoadModule authn_core_module modules/mod_authn_core.so
LoadModule authn_file_module modules/mod_authn_file.so
LoadModule authz_core_module modules/mod_authz_core.so
LoadModule authz_host_module modules/mod_authz_host.so
LoadModule authz_user_module modules/mod_authz_user.so
LoadModule autoindex_module modules/mod_autoindex.so
LoadModule dir_module modules/mod_dir.so
LoadModule env_module modules/mod_env.so
LoadModule filter_module modules/mod_filter.so
LoadModule headers_module modules/mod_headers.so
LoadModule log_config_module modules/mod_log_config.so
LoadModule mime_module modules/mod_mime.so
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_fcgi_module modules/mod_proxy_fcgi.so
LoadModule rewrite_module modules/mod_rewrite.so
LoadModule setenvif_module modules/mod_setenvif.so
{ssl_modules}

ServerAdmin admin@localhost
ServerName localhost:80

<Directory />
    AllowOverride none
    Require all denied
</Directory>

DocumentRoot "{apache_root}/htdocs"
<Directory "{apache_root}/htdocs">
    Options Indexes FollowSymLinks
    AllowOverride All
    Require all granted
</Directory>

DirectoryIndex index.php index.html index.htm

TypesConfig conf/mime.types
ErrorLog "logs/error.log"
LogLevel warn
CustomLog "logs/access.log" common

{ssl_global}

# phpMyAdmin (built-in)
<VirtualHost *:{http_port}>
    ServerName localhost
    DocumentRoot "{apache_root}/htdocs"

    Alias /phpmyadmin "{pma_root}"
    <Directory "{pma_root}">
        Options FollowSymLinks
        AllowOverride All
        Require all granted
        DirectoryIndex index.php
    </Directory>

    ProxyPassMatch "^/phpmyadmin/(.*\\.php(/.*)?$)" "fcgi://127.0.0.1:{pma_php_port}/{pma_root}/$1"
</VirtualHost>

IncludeOptional conf/vhosts/*.conf
"""
    (APACHE_DIR / "conf" / "httpd.conf").write_text(httpd_conf, encoding="utf-8")

    # Regenerate all vhosts
    if config:
        for f in VHOSTS_DIR.glob("*.conf"):
            f.unlink()
        for vhost in config.vhosts:
            if vhost.enabled:
                write_vhost_conf(vhost, http_port, https_port)


def write_vhost_conf(vhost: VHost, http_port: int = 80, https_port: int = 443):
    VHOSTS_DIR.mkdir(parents=True, exist_ok=True)
    root = Path(vhost.root_path).as_posix()
    php_port = PHP_PORTS.get(vhost.php_version, 9084)

    http_block = f"""\
<VirtualHost *:{http_port}>
    ServerName {vhost.domain}
    DocumentRoot "{root}"

    <Directory "{root}">
        Options Indexes FollowSymLinks ExecCGI
        AllowOverride All
        Require all granted
    </Directory>

    DirectoryIndex index.php index.html index.htm

    ProxyPassMatch "^/(.*\\.php(/.*)?$)" "fcgi://127.0.0.1:{php_port}/{root}/$1"

    ErrorLog "logs/{vhost.domain}-error.log"
    CustomLog "logs/{vhost.domain}-access.log" common
</VirtualHost>
"""

    https_block = ""
    if vhost.https_enabled:
        cert = (CERTS_DIR / f"{vhost.domain}.pem").as_posix()
        key = (CERTS_DIR / f"{vhost.domain}-key.pem").as_posix()
        https_block = f"""
<VirtualHost *:{https_port}>
    ServerName {vhost.domain}
    DocumentRoot "{root}"

    SSLEngine on
    SSLCertificateFile    "{cert}"
    SSLCertificateKeyFile "{key}"

    <Directory "{root}">
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    DirectoryIndex index.php index.html index.htm

    ProxyPassMatch "^/(.*\\.php(/.*)?$)" "fcgi://127.0.0.1:{php_port}/{root}/$1"
</VirtualHost>
"""

    (VHOSTS_DIR / f"{vhost.domain}.conf").write_text(http_block + https_block, encoding="utf-8")


def remove_vhost_conf(domain: str):
    (VHOSTS_DIR / f"{domain}.conf").unlink(missing_ok=True)
