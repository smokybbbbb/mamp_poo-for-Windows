"""Windows hosts file manager — requires elevation to write."""
import subprocess
import sys
import tempfile
from pathlib import Path

HOSTS_FILE = Path(r"C:\Windows\System32\drivers\etc\hosts")
MARKER = "# LocalDevManager"

STARTUPINFO = None
if sys.platform == "win32":
    STARTUPINFO = subprocess.STARTUPINFO()
    STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    STARTUPINFO.wShowWindow = subprocess.SW_HIDE


def _read_hosts() -> str:
    try:
        return HOSTS_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _managed_domains() -> list[str]:
    """Return domains currently managed by us."""
    domains = []
    in_block = False
    for line in _read_hosts().splitlines():
        if line.strip() == f"{MARKER} BEGIN":
            in_block = True
            continue
        if line.strip() == f"{MARKER} END":
            in_block = False
            continue
        if in_block and line.strip() and not line.startswith("#"):
            parts = line.split()
            if len(parts) >= 2:
                domains.append(parts[1])
    return domains


def _build_hosts_content(domains: list[str]) -> str:
    """Build the full hosts file content with our block updated."""
    original = _read_hosts()
    lines = original.splitlines()

    # Strip old managed block
    cleaned = []
    in_block = False
    for line in lines:
        if line.strip() == f"{MARKER} BEGIN":
            in_block = True
            continue
        if line.strip() == f"{MARKER} END":
            in_block = False
            continue
        if not in_block:
            cleaned.append(line)

    # Build new block
    if domains:
        block = [f"{MARKER} BEGIN"]
        for d in domains:
            block.append(f"127.0.0.1  {d}")
        block.append(f"{MARKER} END")
        new_content = "\n".join(cleaned).rstrip() + "\n\n" + "\n".join(block) + "\n"
    else:
        new_content = "\n".join(cleaned).rstrip() + "\n"

    return new_content


def _write_hosts_elevated(content: str) -> tuple[bool, str]:
    """Write hosts file content using elevated PowerShell."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                     delete=False, encoding="utf-8") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    ps_cmd = (
        f"Copy-Item -Path '{tmp_path}' "
        f"-Destination 'C:\\Windows\\System32\\drivers\\etc\\hosts' -Force"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Start-Process powershell -ArgumentList '-NoProfile','-Command',\"{ps_cmd}\" "
             f"-Verb RunAs -Wait"],
            capture_output=True, text=True, timeout=20,
            startupinfo=STARTUPINFO,
        )
        Path(tmp_path).unlink(missing_ok=True)
        return True, "hosts updated"
    except subprocess.TimeoutExpired:
        return False, "Timed out (user may have cancelled UAC)"
    except Exception as e:
        return False, str(e)


def add_domain(domain: str) -> tuple[bool, str]:
    current = _managed_domains()
    if domain not in current:
        current.append(domain)
    content = _build_hosts_content(current)
    return _write_hosts_elevated(content)


def remove_domain(domain: str) -> tuple[bool, str]:
    current = _managed_domains()
    if domain in current:
        current.remove(domain)
    content = _build_hosts_content(current)
    return _write_hosts_elevated(content)


def sync_domains(domains: list[str]) -> tuple[bool, str]:
    """Sync managed block to exactly the given list."""
    content = _build_hosts_content(list(set(domains)))
    return _write_hosts_elevated(content)


def domain_in_hosts(domain: str) -> bool:
    return domain in _managed_domains()
