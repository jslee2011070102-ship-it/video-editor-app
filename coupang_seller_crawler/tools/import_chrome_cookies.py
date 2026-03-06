"""실제 Chrome 브라우저에서 coupang.com 쿠키를 가져와 크롤러 프로파일에 주입하는 유틸리티.

사용법:
    python tools/import_chrome_cookies.py                          # 쿠키 읽어서 data/coupang_cookies.json 저장
    python tools/import_chrome_cookies.py --inject                 # 크롤러 프로파일에 바로 주입
    python tools/import_chrome_cookies.py --profile-dir data/chrome_profile

동작 원리:
    1. 시스템에 설치된 Chrome의 쿠키 DB(SQLite)를 읽는다
    2. coupang.com 관련 쿠키를 추출한다
    3. Linux는 평문 / Windows는 DPAPI+AES-GCM 복호화
    4. JSON 파일로 저장하거나 크롤러 프로파일에 직접 주입한다

주의: Chrome이 실행 중이면 쿠키 DB가 잠겨있을 수 있습니다.
      Chrome을 완전히 종료한 후 실행하세요.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# 플랫폼별 Chrome 쿠키 경로
# ──────────────────────────────────────────────────────────────────────────────

def _get_chrome_cookie_paths() -> List[Path]:
    """플랫폼별 Chrome 쿠키 DB 후보 경로 목록을 반환한다."""
    system = platform.system()
    paths: List[Path] = []

    if system == "Linux":
        home = Path.home()
        paths = [
            home / ".config" / "google-chrome" / "Default" / "Cookies",
            home / ".config" / "google-chrome" / "Profile 1" / "Cookies",
            home / ".config" / "chromium" / "Default" / "Cookies",
            # Snap 패키지
            home / "snap" / "chromium" / "current" / ".config" / "chromium" / "Default" / "Cookies",
        ]
    elif system == "Darwin":
        home = Path.home()
        paths = [
            home / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Cookies",
            home / "Library" / "Application Support" / "Chromium" / "Default" / "Cookies",
        ]
    elif system == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        paths = [
            local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "Network" / "Cookies",
            local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "Cookies",
            local_app_data / "Chromium" / "User Data" / "Default" / "Network" / "Cookies",
        ]
    return paths


def _get_chrome_local_state_path() -> Optional[Path]:
    """Windows에서 AES 키 추출을 위한 Local State 파일 경로."""
    system = platform.system()
    if system != "Windows":
        return None
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    p = local_app_data / "Google" / "Chrome" / "User Data" / "Local State"
    return p if p.exists() else None


# ──────────────────────────────────────────────────────────────────────────────
# Windows DPAPI + AES-GCM 복호화
# ──────────────────────────────────────────────────────────────────────────────

def _get_windows_encryption_key() -> Optional[bytes]:
    """Windows Chrome AES-256-GCM 암호화 키를 DPAPI로 복호화하여 반환한다."""
    import base64
    import json as _json

    local_state_path = _get_chrome_local_state_path()
    if not local_state_path:
        return None

    try:
        with open(local_state_path, encoding="utf-8") as f:
            local_state = _json.load(f)
        encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
        encrypted_key = base64.b64decode(encrypted_key_b64)
        # 앞 5바이트 "DPAPI" 헤더 제거
        encrypted_key = encrypted_key[5:]

        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        p = ctypes.create_string_buffer(encrypted_key, len(encrypted_key))
        blobin = DATA_BLOB(ctypes.sizeof(p), p)
        blobout = DATA_BLOB()
        retval = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blobin), None, None, None, None, 0, ctypes.byref(blobout)
        )
        if not retval:
            return None
        result = ctypes.string_at(blobout.pbData, blobout.cbData)
        ctypes.windll.kernel32.LocalFree(blobout.pbData)
        return result
    except Exception as e:
        print(f"[경고] Windows 암호화 키 추출 실패: {e}", file=sys.stderr)
        return None


def _decrypt_windows_cookie(encrypted_value: bytes, key: Optional[bytes]) -> str:
    """Windows Chrome 암호화된 쿠키 값을 복호화한다."""
    if not encrypted_value:
        return ""

    # v10/v11: AES-256-GCM
    if encrypted_value[:3] in (b"v10", b"v11"):
        if key is None:
            return ""
        try:
            from Crypto.Cipher import AES
            iv = encrypted_value[3:15]
            payload = encrypted_value[15:-16]
            tag = encrypted_value[-16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
            return cipher.decrypt_and_verify(payload, tag).decode("utf-8", errors="replace")
        except ImportError:
            print("[경고] pycryptodome이 없습니다. pip install pycryptodome 실행하세요.", file=sys.stderr)
            return ""
        except Exception:
            return ""

    # 구형 DPAPI 암호화
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        p = ctypes.create_string_buffer(encrypted_value, len(encrypted_value))
        blobin = DATA_BLOB(ctypes.sizeof(p), p)
        blobout = DATA_BLOB()
        ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blobin), None, None, None, None, 0, ctypes.byref(blobout)
        )
        result = ctypes.string_at(blobout.pbData, blobout.cbData)
        ctypes.windll.kernel32.LocalFree(blobout.pbData)
        return result.decode("utf-8", errors="replace")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# macOS Keychain 복호화
# ──────────────────────────────────────────────────────────────────────────────

def _get_macos_chrome_key() -> Optional[bytes]:
    """macOS Keychain에서 Chrome 암호화 키를 추출한다."""
    try:
        import subprocess
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-a", "Chrome", "-s", "Chrome Safe Storage"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            password = result.stdout.strip().encode("utf-8")
            # PBKDF2로 키 유도
            import hashlib
            key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, dklen=16)
            return key
    except Exception:
        pass
    return None


def _decrypt_macos_cookie(encrypted_value: bytes, key: Optional[bytes]) -> str:
    """macOS Chrome 암호화된 쿠키 값을 복호화한다."""
    if not encrypted_value or len(encrypted_value) < 3:
        return ""
    if encrypted_value[:3] != b"v10":
        return encrypted_value.decode("utf-8", errors="replace")
    if key is None:
        return ""
    try:
        from Crypto.Cipher import AES
        encrypted_value = encrypted_value[3:]
        iv = b" " * 16
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted_value)
        # PKCS7 패딩 제거
        padding = decrypted[-1]
        return decrypted[:-padding].decode("utf-8", errors="replace")
    except ImportError:
        print("[경고] pycryptodome이 없습니다. pip install pycryptodome 실행하세요.", file=sys.stderr)
        return ""
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# 쿠키 읽기
# ──────────────────────────────────────────────────────────────────────────────

def read_chrome_cookies(host_filter: str = "coupang.com") -> List[dict]:
    """Chrome 쿠키 DB에서 지정 호스트의 쿠키를 읽어 반환한다."""
    system = platform.system()
    cookie_paths = _get_chrome_cookie_paths()

    cookie_db_path: Optional[Path] = None
    for path in cookie_paths:
        if path.exists():
            cookie_db_path = path
            print(f"[정보] Chrome 쿠키 DB 발견: {cookie_db_path}")
            break

    if cookie_db_path is None:
        print("[오류] Chrome 쿠키 DB를 찾을 수 없습니다.", file=sys.stderr)
        print("       Chrome을 설치했는지 확인하고, 종료 후 다시 시도하세요.", file=sys.stderr)
        return []

    # Windows용 암호화 키
    win_key: Optional[bytes] = None
    mac_key: Optional[bytes] = None
    if system == "Windows":
        win_key = _get_windows_encryption_key()
    elif system == "Darwin":
        mac_key = _get_macos_chrome_key()

    # SQLite 연결: Chrome 실행 중에도 읽을 수 있도록 immutable URI 방식 우선 시도
    tmp_path: Optional[str] = None
    conn: Optional[sqlite3.Connection] = None

    # 1순위: immutable=1 URI 직접 읽기 (Chrome 실행 중 잠긴 파일도 접근 가능)
    try:
        uri = f"file:{cookie_db_path}?mode=ro&immutable=1"
        _conn = sqlite3.connect(uri, uri=True)
        _conn.execute("SELECT name FROM cookies LIMIT 1")  # 실제 접근 가능 여부 확인
        conn = _conn
        print("[정보] Chrome 쿠키 DB에 직접 접근 (Chrome 실행 중이어도 OK)")
    except Exception:
        pass

    # 2순위: 파일 복사 후 읽기 (URI 방식이 실패한 경우)
    if conn is None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name
            shutil.copy2(str(cookie_db_path), tmp_path)
            conn = sqlite3.connect(tmp_path)
            print("[정보] Chrome 쿠키 DB 복사 후 접근")
        except PermissionError as e:
            print(f"[오류] 쿠키 DB 접근 실패: {e}", file=sys.stderr)
            print("       Chrome을 완전히 종료(작업 표시줄 아이콘까지 닫기) 후 재시도하세요.", file=sys.stderr)
            return []

    conn.row_factory = sqlite3.Row
    cookies: List[dict] = []
    try:
        cursor = conn.execute(
            """
            SELECT host_key, name, encrypted_value, value, path,
                   expires_utc, is_secure, is_httponly, samesite
            FROM cookies
            WHERE host_key LIKE ?
            """,
            (f"%{host_filter}%",),
        )
        for row in cursor:
            # 쿠키 값 복호화
            enc_val = bytes(row["encrypted_value"]) if row["encrypted_value"] else b""
            plain_val = row["value"] or ""

            if enc_val:
                if system == "Windows":
                    plain_val = _decrypt_windows_cookie(enc_val, win_key)
                elif system == "Darwin":
                    plain_val = _decrypt_macos_cookie(enc_val, mac_key)
                else:
                    # Linux: 평문 저장
                    plain_val = enc_val.decode("utf-8", errors="replace")

            # Playwright 쿠키 형식으로 변환
            expires = row["expires_utc"]
            # Chrome의 epoch는 1601-01-01 기준, Unix epoch는 1970-01-01 기준
            # 차이: 11644473600초
            if expires and expires > 0:
                expires_unix = (expires / 1000000) - 11644473600
            else:
                expires_unix = -1

            cookies.append({
                "name": row["name"],
                "value": plain_val,
                "domain": row["host_key"],
                "path": row["path"] or "/",
                "expires": expires_unix,
                "httpOnly": bool(row["is_httponly"]),
                "secure": bool(row["is_secure"]),
                "sameSite": _samesite_int_to_str(row["samesite"]),
            })
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"[오류] 쿠키 DB 읽기 실패: {e}", file=sys.stderr)
        print("       Chrome이 실행 중이면 완전히 종료 후 다시 시도하세요.", file=sys.stderr)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    print(f"[정보] {host_filter} 쿠키 {len(cookies)}개 추출 완료")
    return cookies


def _samesite_int_to_str(value: int) -> str:
    """Chrome DB의 samesite 정수값을 문자열로 변환한다."""
    # 0: unspecified, 1: no_restriction, 2: lax, 3: strict
    mapping = {0: "Lax", 1: "None", 2: "Lax", 3: "Strict"}
    return mapping.get(value, "Lax")


# ──────────────────────────────────────────────────────────────────────────────
# 크롤러 프로파일에 주입
# ──────────────────────────────────────────────────────────────────────────────

async def inject_cookies_to_profile(cookies: List[dict], profile_dir: str) -> None:
    """Playwright를 통해 크롤러 Chrome 프로파일에 쿠키를 주입한다."""
    from playwright.async_api import async_playwright

    print(f"[정보] 프로파일 {profile_dir} 에 쿠키 {len(cookies)}개 주입 중...")

    async with async_playwright() as p:
        # 프로파일에 간단히 접속해 쿠키만 추가
        try:
            ctx = await p.chromium.launch_persistent_context(
                profile_dir,
                channel="chrome",
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                ignore_default_args=["--enable-automation"],
            )
        except Exception:
            ctx = await p.chromium.launch_persistent_context(
                profile_dir,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                ignore_default_args=["--enable-automation"],
            )

        try:
            await ctx.add_cookies(cookies)
            print(f"[정보] 쿠키 주입 완료. 프로파일: {profile_dir}")
        finally:
            await ctx.close()


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="실제 Chrome에서 coupang.com 쿠키를 추출해 크롤러 프로파일에 주입합니다",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python tools/import_chrome_cookies.py
      → data/coupang_cookies.json 으로 저장

  python tools/import_chrome_cookies.py --inject
      → 크롤러 Chrome 프로파일(data/chrome_profile)에 직접 주입

  python tools/import_chrome_cookies.py --inject --profile-dir /path/to/profile
      → 지정한 프로파일 디렉토리에 주입
""",
    )
    parser.add_argument(
        "--inject",
        action="store_true",
        help="쿠키를 크롤러 Chrome 프로파일에 직접 주입 (기본: JSON 저장만)",
    )
    parser.add_argument(
        "--profile-dir",
        default="data/chrome_profile",
        metavar="DIR",
        help="크롤러 Chrome 프로파일 디렉토리 (기본: data/chrome_profile)",
    )
    parser.add_argument(
        "--output",
        default="data/coupang_cookies.json",
        metavar="FILE",
        help="쿠키 저장 JSON 파일 경로 (기본: data/coupang_cookies.json)",
    )
    parser.add_argument(
        "--host",
        default="coupang.com",
        metavar="HOST",
        help="추출할 호스트 필터 (기본: coupang.com)",
    )
    args = parser.parse_args()

    cookies = read_chrome_cookies(host_filter=args.host)
    if not cookies:
        print("[오류] 쿠키를 추출하지 못했습니다.", file=sys.stderr)
        sys.exit(1)

    # JSON 저장
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print(f"[정보] 쿠키 저장됨: {output_path} ({len(cookies)}개)")

    # 프로파일 주입
    if args.inject:
        profile_dir = str(Path(args.profile_dir).resolve())
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        asyncio.run(inject_cookies_to_profile(cookies, profile_dir))
        print("\n[완료] 이제 크롤러를 실행하면 주입된 쿠키를 사용합니다.")
        print("       python -m src.main --keyword 청소용품 --headless false")
    else:
        print(f"\n[다음 단계] 쿠키를 크롤러 프로파일에 주입하려면:")
        print(f"  python tools/import_chrome_cookies.py --inject")


if __name__ == "__main__":
    main()
