"""FastCGI proxy that fixes SCRIPT_FILENAME before forwarding to PHP-CGI.

Apache mod_proxy_fcgi on Windows sends SCRIPT_FILENAME with a "proxy:fcgi://host:port/"
prefix that PHP-CGI can't handle (results in "No input file specified."). This proxy:
  - Listens on `external_port` (Apache connects here)
  - Forwards to PHP-CGI on `internal_port`
  - Rewrites SCRIPT_FILENAME and DOCUMENT_URI in FCGI_PARAMS to strip the proxy prefix
"""
import re
import socket
import struct
import sys
import threading
from typing import Dict


# FCGI record types
FCGI_BEGIN_REQUEST = 1
FCGI_PARAMS = 4
FCGI_STDIN = 5

_PROXY_PREFIX_RE = re.compile(rb'^proxy:fcgi://[^/]+/')


def _encode_kv(name: bytes, value: bytes) -> bytes:
    """Encode a single FCGI name-value pair."""
    out = bytearray()
    for length in (len(name), len(value)):
        if length < 128:
            out.append(length)
        else:
            out += struct.pack('!I', length | 0x80000000)
    out += name + value
    return bytes(out)


def _rewrite_params(content: bytes) -> bytes:
    """Parse, rewrite SCRIPT_FILENAME/PATH_TRANSLATED, re-encode."""
    pairs: Dict[bytes, bytes] = {}
    i = 0
    while i < len(content):
        if content[i] & 0x80:
            name_len = struct.unpack('!I', content[i:i+4])[0] & 0x7FFFFFFF
            i += 4
        else:
            name_len = content[i]; i += 1
        if content[i] & 0x80:
            value_len = struct.unpack('!I', content[i:i+4])[0] & 0x7FFFFFFF
            i += 4
        else:
            value_len = content[i]; i += 1
        name = content[i:i+name_len]; i += name_len
        value = content[i:i+value_len]; i += value_len

        # Strip "proxy:fcgi://host:port/" prefix from any value that has it
        if value.startswith(b'proxy:fcgi://'):
            value = _PROXY_PREFIX_RE.sub(b'', value)
        pairs[name] = value

    # Rebuild
    out = bytearray()
    for name, value in pairs.items():
        out += _encode_kv(name, value)
    return bytes(out)


def _forward_loop(src: socket.socket, dst: socket.socket, rewrite: bool):
    """Forward bytes from src to dst, optionally rewriting FCGI params records."""
    buf = b''
    try:
        while True:
            chunk = src.recv(8192)
            if not chunk:
                break
            buf += chunk
            # Process complete FCGI records
            while len(buf) >= 8:
                version, type_, request_id, content_length, padding_length, _ = \
                    struct.unpack('!BBHHBB', buf[:8])
                total = 8 + content_length + padding_length
                if len(buf) < total:
                    break
                header = buf[:8]
                content = buf[8:8+content_length]
                padding = buf[8+content_length:total]
                buf = buf[total:]

                if rewrite and type_ == FCGI_PARAMS and content:
                    new_content = _rewrite_params(content)
                    new_header = struct.pack(
                        '!BBHHBB', version, type_, request_id,
                        len(new_content), 0, 0,
                    )
                    dst.sendall(new_header + new_content)
                else:
                    dst.sendall(header + content + padding)
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        try: dst.shutdown(socket.SHUT_WR)
        except OSError: pass


def _handle(client: socket.socket, backend_host: str, backend_port: int):
    """Handle one Apache → PHP-CGI session."""
    try:
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.connect((backend_host, backend_port))
    except OSError as e:
        sys.stderr.write(f"backend connect failed: {e}\n")
        client.close()
        return

    # Apache → PHP-CGI: rewrite FCGI_PARAMS
    t1 = threading.Thread(target=_forward_loop, args=(client, backend, True), daemon=True)
    # PHP-CGI → Apache: pass through unchanged
    t2 = threading.Thread(target=_forward_loop, args=(backend, client, False), daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()
    client.close(); backend.close()


def serve(listen_port: int, backend_port: int, backend_host: str = '127.0.0.1'):
    """Run the proxy forever."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', listen_port))
    s.listen(128)
    sys.stderr.write(f"fcgi_proxy: listening on 127.0.0.1:{listen_port} -> {backend_host}:{backend_port}\n")
    sys.stderr.flush()
    while True:
        client, _ = s.accept()
        threading.Thread(target=_handle, args=(client, backend_host, backend_port),
                         daemon=True).start()


def serve_threaded(listen_port: int, backend_port: int, stop_event,
                   backend_host: str = '127.0.0.1'):
    """Run the proxy until stop_event is set. For embedded use."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(0.5)
    try:
        s.bind(('127.0.0.1', listen_port))
    except OSError:
        return
    s.listen(128)
    while not stop_event.is_set():
        try:
            client, _ = s.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=_handle, args=(client, backend_host, backend_port),
                         daemon=True).start()
    try:
        s.close()
    except OSError:
        pass


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("usage: fcgi_proxy.py <listen_port> <backend_port>")
        sys.exit(1)
    serve(int(sys.argv[1]), int(sys.argv[2]))
