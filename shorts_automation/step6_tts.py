"""
10단계: gTTS로 한국어 스크립트 → mp3 음성 파일 생성
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import AUDIO_DIR


def run_step6(script: str, video_id: str) -> str:
    print(f"\n=== 10단계: TTS 음성 생성 ===\n")

    if not script.strip():
        print("대본이 비어 있습니다.")
        return ''

    try:
        from gtts import gTTS
    except ImportError:
        print("gTTS 패키지가 필요합니다: pip install gTTS")
        sys.exit(1)

    output_path = str(AUDIO_DIR / f"{video_id}_tts.mp3")

    print(f"대본 길이: {len(script)}자")
    print("gTTS 한국어 음성 생성 중...")

    tts = gTTS(text=script, lang='ko', slow=False)
    tts.save(output_path)

    print(f"TTS 완료: {Path(output_path).name}")
    return output_path


if __name__ == '__main__':
    sample = (
        "믿기지 않는 일이 일어났습니다. "
        "길거리에서 만난 강아지가 어린이를 위험에서 구해냈는데요. "
        "어떻게 된 일인지, 지금 바로 알려드릴게요. "
        "이 강아지는 사실 주인도 없이 홀로 돌아다니고 있었습니다. "
        "그런데 아이가 위험에 처한 순간, 누구보다 먼저 달려갔습니다."
    )
    result = run_step6(sample, 'test_id')
    print(f"저장 경로: {result}")
