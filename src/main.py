"""
쇼츠 자동 생성 파이프라인 - 메인 오케스트레이터
============================================================
전체 비용: 0원 (Claude API 제외)

[비용 구조]
  - Claude API     : 유료 (스크립트/기획/레퍼런스 - 입출력 토큰만)
  - edge-tts TTS   : 완전 무료 (Microsoft Neural Voice)
  - Pexels 영상    : 완전 무료 (월 200 크레딧, API 키 필요)
  - moviepy 편집   : 완전 무료 (오픈소스)
  - ffmpeg 렌더링  : 완전 무료 (오픈소스)

[사용법]
  1. .env 파일 설정 (ANTHROPIC_API_KEY, PEXELS_API_KEY)
  2. pip install -r requirements.txt
  3. python src/main.py --topic "주제" --duration 60

[예시]
  python src/main.py --topic "매일 5분 영어 공부법" --duration 60
  python src/main.py --topic "주식 초보 투자 실수" --duration 45 --voice male_standard
"""
import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import anthropic

# 파이프라인 모듈
from reference_explorer import explore_references, print_reference_result
from planner import create_content_plan, print_content_plan
from script_generator import generate_script, print_script
from video_prompt_generator import generate_video_prompts, print_video_prompts
from tts_generator import generate_tts, KOREAN_VOICES, list_available_voices
from video_fetcher import fetch_videos
from video_editor import edit_shorts


def run_pipeline(
    topic: str,
    duration: int,
    voice_key: str,
    output_dir: str,
    skip_video: bool,
) -> None:
    """전체 쇼츠 생성 파이프라인 실행"""
    load_dotenv()

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    pexels_key = os.getenv("PEXELS_API_KEY")

    if not anthropic_key:
        print("❌ ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)
    if not pexels_key and not skip_video:
        print("⚠️  PEXELS_API_KEY가 없습니다. 영상 없이 단색 배경으로 진행합니다.")
        skip_video = True

    client = anthropic.Anthropic(api_key=anthropic_key)
    voice = KOREAN_VOICES.get(voice_key, KOREAN_VOICES["female_standard"])

    start_time = time.time()

    # ─────────────────────────────────────────────
    # STEP 1: 레퍼런스 탐색
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  STEP 1/7  레퍼런스 탐색")
    print(f"{'='*60}")
    reference = explore_references(topic, client)
    print_reference_result(reference)

    # ─────────────────────────────────────────────
    # STEP 2: 콘텐츠 기획
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  STEP 2/7  콘텐츠 기획")
    print(f"{'='*60}")
    plan = create_content_plan(reference, duration, client)
    print_content_plan(plan)

    # ─────────────────────────────────────────────
    # STEP 3: 대본 생성
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  STEP 3/7  대본 생성")
    print(f"{'='*60}")
    script = generate_script(plan, client)
    print_script(script)

    # ─────────────────────────────────────────────
    # STEP 4: 영상 프롬프트 생성
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  STEP 4/7  영상 프롬프트 생성")
    print(f"{'='*60}")
    prompt_set = generate_video_prompts(plan, client)
    print_video_prompts(prompt_set)

    # ─────────────────────────────────────────────
    # STEP 5: 영상 수집 (Pexels API - 무료)
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  STEP 5/7  영상 수집 (Pexels - 무료)")
    print(f"{'='*60}")
    video_dir = os.path.join(output_dir, "video")

    if not skip_video:
        scene_durations = {s.index: s.duration for s in plan.scenes}
        fetched_videos = fetch_videos(
            prompt_set=prompt_set,
            api_key=pexels_key,
            output_dir=video_dir,
            scene_durations=scene_durations,
        )
    else:
        from video_fetcher import FetchedVideoSet
        fetched_videos = FetchedVideoSet()  # 빈 세트 → fallback 클립 사용
        print("  ⏭️  영상 수집 건너뜀 (단색 배경으로 대체)")

    # ─────────────────────────────────────────────
    # STEP 6: TTS 생성 (edge-tts - 완전 무료)
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  STEP 6/7  TTS 생성 (edge-tts - 무료)")
    print(f"{'='*60}")
    audio_dir = os.path.join(output_dir, "audio")
    tts_output = generate_tts(script, audio_dir, voice)

    # ─────────────────────────────────────────────
    # STEP 7: 영상 편집 (moviepy - 완전 무료)
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  STEP 7/7  영상 편집 & 최종 렌더링 (moviepy - 무료)")
    print(f"{'='*60}")
    final_dir = os.path.join(output_dir, "final")
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in plan.title)
    output_filename = f"{safe_title[:40]}.mp4"

    result = edit_shorts(
        plan=plan,
        script=script,
        tts_output=tts_output,
        fetched_videos=fetched_videos,
        output_dir=final_dir,
        output_filename=output_filename,
    )

    elapsed = time.time() - start_time

    # ─────────────────────────────────────────────
    # 완료 요약
    # ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  🎉 쇼츠 자동 생성 완료!")
    print(f"{'='*60}")
    print(f"  📹 영상: {result.output_path}")
    print(f"  ⏱️  길이: {result.duration:.1f}초")
    print(f"  📐 해상도: {result.resolution[0]}x{result.resolution[1]}")
    print(f"  ⏳ 소요 시간: {elapsed:.0f}초")
    print(f"\n  💰 비용 내역:")
    print(f"     Claude API  : 소량의 토큰 비용 (텍스트만)")
    print(f"     TTS (edge-tts): 무료 ✅")
    print(f"     영상 (Pexels) : 무료 ✅")
    print(f"     편집 (moviepy): 무료 ✅")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="쇼츠 자동 생성 파이프라인 (TTS/영상 무료)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python src/main.py --topic "매일 5분 영어 공부법"
  python src/main.py --topic "주식 초보 투자 실수" --duration 45 --voice male_standard
  python src/main.py --topic "AI 트렌드 2025" --skip-video  # 영상 없이 테스트
  python src/main.py --list-voices                           # 음성 목록 보기
        """,
    )
    parser.add_argument("--topic", type=str, help="영상 주제")
    parser.add_argument("--duration", type=int, default=60, help="목표 길이 (초, 기본값: 60)")
    parser.add_argument(
        "--voice",
        type=str,
        default="female_standard",
        choices=list(KOREAN_VOICES.keys()),
        help="TTS 음성 선택 (기본값: female_standard)",
    )
    parser.add_argument("--output-dir", type=str, default="output", help="출력 디렉토리")
    parser.add_argument("--skip-video", action="store_true", help="영상 수집 건너뛰기 (테스트용)")
    parser.add_argument("--list-voices", action="store_true", help="사용 가능한 음성 목록 출력")

    args = parser.parse_args()

    if args.list_voices:
        list_available_voices()
        return

    if not args.topic:
        parser.print_help()
        print("\n❌ --topic 을 입력해주세요.")
        sys.exit(1)

    run_pipeline(
        topic=args.topic,
        duration=args.duration,
        voice_key=args.voice,
        output_dir=args.output_dir,
        skip_video=args.skip_video,
    )


if __name__ == "__main__":
    main()
