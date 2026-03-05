"""
쇼츠 자동화 파이프라인 - 전체 실행 파일
사용법: python shorts_automation/main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import YOUTUBE_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, AI_PROVIDER
from step1_search import run_step1
from step2_original import run_step2
from step3_download import run_step3
from step4_analyze import run_step4
from step5_clip_edit import run_step5
from step6_tts import run_step6
from step7_merge import run_step7


def check_api_keys() -> bool:
    missing = []
    if not YOUTUBE_API_KEY:
        missing.append("YOUTUBE_API_KEY")
    if AI_PROVIDER == 'claude':
        if not ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY (AI_PROVIDER=claude 설정됨)")
    else:
        if not GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")

    if missing:
        print("\n⚠️  다음 API 키가 .env에 설정되지 않았습니다:")
        for k in missing:
            print(f"   - {k}")
        print("\n.env.shorts.example 파일을 참고해서 .env에 키를 추가해주세요.\n")
        return False
    return True


def main():
    print("=" * 60)
    print("    쇼츠 자동화 파이프라인")
    print(f"    AI 제공자: {AI_PROVIDER.upper()}")
    print("=" * 60)

    if not check_api_keys():
        sys.exit(1)

    # ── 1~2단계: 영상 검색 ──────────────────────────────────────
    video_info = run_step1()
    if not video_info:
        print("영상이 선택되지 않았습니다. 종료합니다.")
        sys.exit(0)

    video_id = video_info['video_id']

    # ── 3단계: 원본 영상 탐색 ────────────────────────────────────
    final_video_info = run_step2(video_info)
    video_id = final_video_info.get('video_id', video_id)

    # ── 4단계: 다운로드 + 자막 추출 ──────────────────────────────
    download_result = run_step3(final_video_info['url'], video_id)
    if not download_result.get('video_path'):
        print("\n영상 다운로드에 실패했습니다. 종료합니다.")
        sys.exit(1)

    video_path = download_result['video_path']
    subtitle_path = download_result.get('subtitle_path')

    # ── 5~9단계: AI 분석 + 대본 재작성 ────────────────────────────
    analysis = run_step4(subtitle_path, video_id)
    new_script = analysis.get('new_script', '').strip()

    if not new_script:
        print("\nAI 대본 생성에 실패했습니다. 종료합니다.")
        sys.exit(1)

    # ── 7단계(추가): 영상 클립 재편집 ────────────────────────────
    rearranged_video = run_step5(video_path, analysis, video_id)

    # ── 10단계: TTS 음성 생성 ─────────────────────────────────────
    audio_path = run_step6(new_script, video_id)
    if not audio_path:
        print("\nTTS 생성에 실패했습니다. 종료합니다.")
        sys.exit(1)

    # ── 11~12단계: 영상 + 음성 + 자막 합치기 ──────────────────────
    final_output = run_step7(rearranged_video, audio_path, new_script, video_id)

    if final_output:
        print("\n" + "=" * 60)
        print(f"  완성! 최종 파일: {final_output}")
        print("=" * 60)
    else:
        print("\n최종 영상 생성에 실패했습니다.")
        sys.exit(1)


if __name__ == '__main__':
    main()
