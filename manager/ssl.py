"""SSL certificate management via mkcert."""
import subprocess
import sys
from pathlib import Path
from manager.config import MKCERT_DIR, CERTS_DIR

_MKCERT = MKCERT_DIR / "mkcert.exe"

_SI = None
if sys.platform == "win32":
    _SI = subprocess.STARTUPINFO()
    _SI.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _SI.wShowWindow = subprocess.SW_HIDE

_CNW = 0x08000000


def _caroot() -> Path | None:
    """Return mkcert's CAROOT directory."""
    if not _MKCERT.exists():
        return None
    try:
        r = subprocess.run(
            [str(_MKCERT), "-CAROOT"],
            capture_output=True, text=True, timeout=5,
            startupinfo=_SI, creationflags=_CNW,
        )
        path = r.stdout.strip()
        return Path(path) if path else None
    except Exception:
        return None


def is_root_ca_installed() -> bool:
    """Check if mkcert's root CA is actually in the Windows trust store
    (not just whether rootCA.pem exists on disk)."""
    caroot = _caroot()
    if not caroot:
        return False
    root_pem = caroot / "rootCA.pem"
    if not root_pem.exists():
        return False
    if sys.platform != "win32":
        return root_pem.exists()  # best-effort on non-Windows
    # Check Windows CurrentUser\Root store for the cert's thumbprint
    ps = (
        f"$c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 "
        f"'{root_pem}'; "
        f"if (Get-ChildItem Cert:\\CurrentUser\\Root -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.Thumbprint -eq $c.Thumbprint }}) {{ exit 0 }} else {{ exit 1 }}"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=10,
            startupinfo=_SI, creationflags=_CNW,
        )
        return r.returncode == 0
    except Exception:
        return False


def install_root_ca() -> tuple[bool, str]:
    if not _MKCERT.exists():
        return False, "mkcert not installed"

    if is_root_ca_installed():
        return True, "Root CA already installed"

    # Use Start-Process with -Verb RunAs to trigger UAC. Do NOT hide the parent
    # PowerShell with STARTUPINFO — that has been observed to suppress UAC on
    # some Windows builds. We capture output to detect cancellation.
    cmd = (
        f'$ErrorActionPreference="Stop"; '
        f'try {{ '
        f'  Start-Process -FilePath "{_MKCERT}" -ArgumentList "-install" '
        f'    -Verb RunAs -Wait -WindowStyle Hidden; '
        f'  exit 0 '
        f'}} catch {{ Write-Error $_.Exception.Message; exit 1 }}'
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=120,
            creationflags=_CNW,  # hide our own console, not the UAC prompt
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for UAC response"
    except Exception as e:
        return False, str(e)

    # Verify by checking the trust store — don't trust exit codes alone
    if is_root_ca_installed():
        return True, "Root CA installed successfully"

    # Surface the actual PowerShell error if any
    err = (r.stderr or r.stdout or "").strip()
    if "cancelled" in err.lower() or "denied" in err.lower():
        return False, "UAC cancelled by user"
    return False, err or "Install failed — did you click Yes on the UAC prompt?"


def generate_cert(domain: str) -> tuple[bool, str]:
    if not _MKCERT.exists():
        return False, "mkcert not installed"
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    cert = CERTS_DIR / f"{domain}.pem"
    key = CERTS_DIR / f"{domain}-key.pem"
    try:
        r = subprocess.run(
            [str(_MKCERT), "-cert-file", str(cert), "-key-file", str(key), domain],
            capture_output=True, text=True, timeout=15,
            startupinfo=_SI, creationflags=_CNW,
        )
        if r.returncode == 0:
            return True, f"Cert created for {domain}"
        return False, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def cert_exists(domain: str) -> bool:
    return (CERTS_DIR / f"{domain}.pem").exists() and \
           (CERTS_DIR / f"{domain}-key.pem").exists()


def remove_cert(domain: str):
    (CERTS_DIR / f"{domain}.pem").unlink(missing_ok=True)
    (CERTS_DIR / f"{domain}-key.pem").unlink(missing_ok=True)
