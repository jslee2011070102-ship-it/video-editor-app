"""
11~12단계: FFmpeg으로
  - 원본 오디오 제거 + TTS 음성 삽입
  - 한국어 자막 하드코딩(burn-in)
  - 최종 mp4 저장
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import OUTPUT_DIR

# 사용 가능한 한국어 폰트 목록 (시스템에 따라 다를 수 있음)
AVAILABLE_FONTS = {
    'NanumGothic':      'NanumGothic',
    'NanumBarunGothic': 'NanumBarunGothic',
    'NanumMyeongjo':    'NanumMyeongjo',
    'UnDotum':          'UnDotum',
    'NotoSansCJK':      'Noto Sans CJK KR',
    'DejaVu':           'DejaVu Sans',
}
DEFAULT_FONT = 'NanumGothic'


# ─── FFprobe 유틸 ──────────────────────────────────────────────────────────

def get_media_duration(path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams', path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0.0
    for stream in data.get('streams', []):
        d = stream.get('duration')
        if d:
            return float(d)
    return 0.0


# ─── 자막 타이밍 생성 (폴백용 - edge-tts SRT 없을 때만 사용) ──────────────

CHARS_PER_LINE = 18  # 한 줄 최대 글자 수

def _wrap_to_two_lines(text: str) -> str:
    """긴 텍스트를 최대 2줄로 분리"""
    if len(text) <= CHARS_PER_LINE:
        return text
    mid = len(text) // 2
    # 공백에서 분리 시도
    for j in range(mid, 0, -1):
        if text[j] == ' ':
            return text[:j] + '\n' + text[j + 1:]
    for j in range(mid, len(text)):
        if text[j] == ' ':
            return text[:j] + '\n' + text[j + 1:]
    return text[:mid] + '\n' + text[mid:]


def split_into_subtitles(script: str, total_duration: float) -> list[dict]:
    """
    스크립트를 문장 단위로 쪼개고 글자수 비례로 타임스탬프 부여.
    반환: [{'start': float, 'end': float, 'text': str}, ...]
    """
    sentences = re.split(r'(?<=[.!?。！？])\s+|\n+', script.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return [{'start': 0.0, 'end': total_duration, 'text': _wrap_to_two_lines(script.strip())}]

    total_chars = sum(len(s) for s in sentences)
    subtitles = []
    current = 0.0
    for sentence in sentences:
        ratio   = len(sentence) / total_chars if total_chars else 1 / len(sentences)
        duration = total_duration * ratio
        duration = max(0.8, min(5.0, duration))
        subtitles.append({
            'start': current,
            'end':   current + duration,
            'text':  _wrap_to_two_lines(sentence),
        })
        current += duration

    return subtitles


def _srt_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(subtitles: list[dict], path: str):
    with open(path, 'w', encoding='utf-8') as f:
        for i, sub in enumerate(subtitles, 1):
            f.write(f"{i}\n")
            f.write(f"{_srt_time(sub['start'])} --> {_srt_time(sub['end'])}\n")
            f.write(f"{sub['text']}\n\n")


# ─── FFmpeg 파이프라인 ─────────────────────────────────────────────────────

def _build_subtitle_filter(srt_path: str, font: str = DEFAULT_FONT) -> str:
    escaped = srt_path.replace('\\', '/').replace(':', r'\:')
    style = (
        f"FontName={font},FontSize=18,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "Outline=2,Shadow=1,Alignment=2,MarginV=40"
    )
    return f"subtitles='{escaped}':force_style='{style}'"


def _ffmpeg(cmd: list[str]) -> bool:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FFmpeg 오류:\n{result.stderr[-400:]}")
    return result.returncode == 0


def run_step7(
    video_path: str,
    audio_path: str,
    script: str,
    video_id: str,
    srt_path: str | None = None,   # edge-tts가 생성한 싱크 SRT (있으면 우선 사용)
    font: str = DEFAULT_FONT,
) -> str:
    print(f"\n=== 11~12단계: 영상 + 음성 합치기 + 자막 burn-in ===\n")
    print(f"폰트: {font}")

    audio_duration = get_media_duration(audio_path)
    if audio_duration == 0:
        print("오디오 길이를 읽을 수 없습니다.")
        return ''

    print(f"TTS 오디오 길이: {audio_duration:.1f}초")

    # ── 1단계: 영상을 TTS 길이에 맞게 트림 + 원본 오디오 제거 ──
    trimmed = str(OUTPUT_DIR / f"{video_id}_trimmed.mp4")
    print("영상 길이 조정 + 원본 오디오 제거 중...")
    ok = _ffmpeg([
        'ffmpeg', '-y',
        '-i', video_path,
        '-t', f"{audio_duration:.3f}",
        '-an',
        '-c:v', 'libx264',
        trimmed,
    ])
    if not ok:
        return ''

    # ── 2단계: 자막 SRT 결정 ──
    generated_srt = False
    if srt_path and Path(srt_path).exists() and Path(srt_path).stat().st_size > 0:
        print(f"edge-tts 싱크 자막 사용: {Path(srt_path).name}")
    else:
        # 폴백: 글자수 비례 타이밍
        srt_path = str(OUTPUT_DIR / f"{video_id}.srt")
        subtitles = split_into_subtitles(script, audio_duration)
        write_srt(subtitles, srt_path)
        print(f"자막 파일 생성 (폴백): {Path(srt_path).name}  ({len(subtitles)}개 구간)")
        generated_srt = True

    # ── 3단계: 영상 + TTS 오디오 + 자막 burn-in ──
    final_path = str(OUTPUT_DIR / f"{video_id}_final.mp4")
    print("최종 합성 중 (영상 + TTS + 자막 burn-in)...")

    sub_filter = _build_subtitle_filter(srt_path, font=font)
    ok = _ffmpeg([
        'ffmpeg', '-y',
        '-i', trimmed,
        '-i', audio_path,
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-vf', sub_filter,
        '-shortest',
        final_path,
    ])

    if not ok:
        # 폴백: DejaVu 폰트로 재시도
        print("  폰트 오류 가능성, DejaVu Sans로 재시도...")
        sub_filter_fallback = _build_subtitle_filter(srt_path, font='DejaVu Sans')
        ok = _ffmpeg([
            'ffmpeg', '-y',
            '-i', trimmed,
            '-i', audio_path,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-vf', sub_filter_fallback,
            '-shortest',
            final_path,
        ])

    # 임시 파일 정리
    Path(trimmed).unlink(missing_ok=True)

    if not ok:
        return ''

    print(f"\n최종 영상 완성: {Path(final_path).name}")
    return final_path


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("사용법: python step7_merge.py <video_path> <audio_path> <video_id>")
        sys.exit(1)
    result = run_step7(
        sys.argv[1], sys.argv[2],
        "테스트 자막 문장입니다. 두 번째 문장입니다.",
        sys.argv[3],
    )
    print(f"결과: {result}")
