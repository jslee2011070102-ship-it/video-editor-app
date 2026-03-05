"""
7단계 (추가): Gemini AI가 출력한 기승전결 재배치 기반으로 영상 클립 재편집 (FFmpeg)
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CLIPS_DIR


def get_video_duration(video_path: str) -> float:
    """FFprobe로 영상 길이(초) 조회"""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams',
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0.0

    for stream in data.get('streams', []):
        if stream.get('codec_type') == 'video':
            return float(stream.get('duration', 0))
    return 0.0


def cut_clip(video_path: str, start: float, end: float, output_path: str) -> bool:
    """FFmpeg으로 영상 구간 잘라내기"""
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-ss', f"{start:.3f}",
        '-to', f"{end:.3f}",
        '-c:v', 'libx264', '-c:a', 'aac',
        '-avoid_negative_ts', 'make_zero',
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  클립 생성 오류: {result.stderr[:200]}")
    return result.returncode == 0


def concatenate_clips(clip_paths: list[str], output_path: str) -> bool:
    """FFmpeg concat demuxer로 클립 이어붙이기"""
    concat_file = Path(output_path).parent / '_concat_list.txt'
    with open(concat_file, 'w', encoding='utf-8') as f:
        for path in clip_paths:
            f.write(f"file '{path}'\n")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', str(concat_file),
        '-c:v', 'libx264', '-c:a', 'aac',
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_file.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"  클립 연결 오류: {result.stderr[:200]}")
    return result.returncode == 0


def run_step5(video_path: str, analysis: dict, video_id: str) -> str:
    """
    narrative_structure의 ratio 값을 실제 타임스탬프로 변환,
    rearranged_order 순서로 클립을 잘라서 재조합.
    실패 시 원본 video_path 반환.
    """
    print(f"\n=== 7단계(추가): 영상 클립 재편집 ===\n")

    structure = analysis.get('narrative_structure', {})
    order = analysis.get('rearranged_order', [])

    if not structure or not order:
        print("재배치 정보가 없습니다. 원본 영상을 그대로 사용합니다.")
        return video_path

    duration = get_video_duration(video_path)
    if duration == 0:
        print("영상 길이를 읽을 수 없습니다. 원본 영상을 사용합니다.")
        return video_path

    print(f"원본 영상 길이: {duration:.1f}초")

    # ratio → 실제 초 단위 타임스탬프 변환
    segments: dict[str, dict] = {}
    for name, data in structure.items():
        start = data['start_ratio'] * duration
        end = data['end_ratio'] * duration
        segments[name] = {'start': start, 'end': end}

    print(f"재배치 순서: {' → '.join(order)}\n")

    clip_paths = []
    for i, section in enumerate(order):
        if section not in segments:
            print(f"  '{section}' 구간 정보 없음, 건너뜀")
            continue

        seg = segments[section]
        clip_path = str(CLIPS_DIR / f"{video_id}_clip{i:02d}_{section}.mp4")
        duration_sec = seg['end'] - seg['start']

        print(
            f"  클립 {i + 1} [{section}] "
            f"{seg['start']:.1f}s ~ {seg['end']:.1f}s "
            f"({duration_sec:.1f}초)"
        )
        if cut_clip(video_path, seg['start'], seg['end'], clip_path):
            clip_paths.append(clip_path)
        else:
            print(f"  클립 {i + 1} 생성 실패")

    if not clip_paths:
        print("모든 클립 생성에 실패했습니다. 원본 영상을 사용합니다.")
        return video_path

    if len(clip_paths) == 1:
        print(f"재편집 완료 (클립 1개): {Path(clip_paths[0]).name}")
        return clip_paths[0]

    output_path = str(CLIPS_DIR / f"{video_id}_rearranged.mp4")
    print(f"\n클립 {len(clip_paths)}개 연결 중...")
    if concatenate_clips(clip_paths, output_path):
        print(f"재편집 완료: {Path(output_path).name}")
        return output_path

    print("클립 연결 실패. 원본 영상을 사용합니다.")
    return video_path


if __name__ == '__main__':
    test_analysis = {
        'narrative_structure': {
            'intro':       {'summary': '도입', 'start_ratio': 0.0,  'end_ratio': 0.25},
            'development': {'summary': '전개', 'start_ratio': 0.25, 'end_ratio': 0.70},
            'climax':      {'summary': '결말', 'start_ratio': 0.70, 'end_ratio': 1.0},
        },
        'rearranged_order': ['climax', 'intro', 'development'],
    }
    if len(sys.argv) < 2:
        print("사용법: python step5_clip_edit.py <video_path>")
        sys.exit(1)
    result = run_step5(sys.argv[1], test_analysis, 'test_id')
    print(f"결과: {result}")
