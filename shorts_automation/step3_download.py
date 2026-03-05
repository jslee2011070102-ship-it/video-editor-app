"""
4단계: yt-dlp로 영상 다운로드 + 자막 추출 (언어 자동 감지)
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DOWNLOADS_DIR, SUBTITLES_DIR


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def download_video_file(url: str, video_id: str) -> str | None:
    output_template = str(DOWNLOADS_DIR / f"{video_id}.%(ext)s")
    cmd = [
        'yt-dlp',
        '-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
        '--merge-output-format', 'mp4',
        '-o', output_template,
        '--no-playlist',
        '--no-warnings',
        url,
    ]
    print("영상 다운로드 중...")
    result = _run(cmd)

    if result.returncode != 0:
        print(f"다운로드 오류:\n{result.stderr[:400]}")
        return None

    for f in DOWNLOADS_DIR.glob(f"{video_id}.*"):
        if f.suffix in ('.mp4', '.mkv', '.webm'):
            print(f"다운로드 완료: {f.name}")
            return str(f)

    print("다운로드된 영상 파일을 찾을 수 없습니다.")
    return None


def extract_subtitles(url: str, video_id: str) -> str | None:
    output_template = str(SUBTITLES_DIR / video_id)

    # 자동 생성 자막 우선 시도
    print("자동 생성 자막 추출 시도 중...")
    cmd_auto = [
        'yt-dlp',
        '--write-auto-subs',
        '--skip-download',
        '--sub-format', 'vtt',
        '--convert-subs', 'srt',
        '-o', output_template,
        '--no-playlist',
        url,
    ]
    _run(cmd_auto)

    sub = _find_subtitle(video_id)
    if sub:
        print(f"자동 생성 자막 추출 완료: {Path(sub).name}")
        return sub

    # 수동 자막 시도
    print("수동 자막 추출 시도 중...")
    cmd_manual = [
        'yt-dlp',
        '--write-subs',
        '--skip-download',
        '--sub-format', 'vtt',
        '--convert-subs', 'srt',
        '-o', output_template,
        '--no-playlist',
        url,
    ]
    _run(cmd_manual)

    sub = _find_subtitle(video_id)
    if sub:
        print(f"수동 자막 추출 완료: {Path(sub).name}")
        return sub

    print("자막을 찾을 수 없습니다. AI가 영상 내용을 추정해서 대본을 작성합니다.")
    return None


def _find_subtitle(video_id: str) -> str | None:
    for f in SUBTITLES_DIR.glob(f"{video_id}*"):
        if f.suffix in ('.srt', '.vtt'):
            return str(f)
    return None


def parse_srt(srt_path: str) -> str:
    """SRT/VTT 파일에서 순수 텍스트만 추출"""
    with open(srt_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.isdigit() or '-->' in line:
            continue
        # HTML 태그, VTT 메타 제거
        line = re.sub(r'<[^>]+>', '', line)
        line = re.sub(r'WEBVTT.*', '', line)
        line = line.strip()
        if line:
            lines.append(line)

    return ' '.join(lines)


def run_step3(url: str, video_id: str) -> dict:
    print(f"\n=== 4단계: 영상 다운로드 + 자막 추출 ===\n")
    print(f"URL: {url}")

    video_path = download_video_file(url, video_id)
    if not video_path:
        return {}

    subtitle_path = extract_subtitles(url, video_id)

    return {
        'video_path': video_path,
        'subtitle_path': subtitle_path,
    }


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("사용법: python step3_download.py <url> <video_id>")
        sys.exit(1)
    result = run_step3(sys.argv[1], sys.argv[2])
    print(result)
