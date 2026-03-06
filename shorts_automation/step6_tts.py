"""
TTS 음성 생성 - edge-tts 사용
  - 다중 한국어 목소리 (여성/남성)
  - 재생 속도 조절
  - 단어 타이밍 기반 자막 싱크 SRT 자동 생성
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import AUDIO_DIR, OUTPUT_DIR

# 사용 가능한 한국어 목소리
VOICES = {
    'female': 'ko-KR-SunHiNeural',      # 여성 (기본)
    'male':   'ko-KR-InJoonNeural',      # 남성
    'male2':  'ko-KR-HyunsuNeural',      # 남성 (감성)
}
VOICE_LABELS = {
    'female': '여성 (SunHi)',
    'male':   '남성 (InJoon)',
    'male2':  '남성 감성 (Hyunsu)',
}

# 자막 한 줄 최대 글자 수 (한국어 쇼츠 기준)
CHARS_PER_LINE = 18


def _srt_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_to_srt(words: list[dict], srt_path: str):
    """
    단어 타이밍 목록 → 2줄 이내 SRT 파일 생성.
    words: [{'offset': float(초), 'duration': float(초), 'text': str}, ...]
    """
    if not words:
        return

    max_chars = CHARS_PER_LINE * 2  # 2줄 최대

    # 단어를 그룹으로 묶기
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0

    for word in words:
        wlen = len(word['text'])
        if current_len + wlen > max_chars and current:
            groups.append(current)
            current = [word]
            current_len = wlen
        else:
            current.append(word)
            current_len += wlen

    if current:
        groups.append(current)

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, grp in enumerate(groups, 1):
            start = grp[0]['offset']
            end   = grp[-1]['offset'] + grp[-1]['duration']
            # 단어 사이에 공백 추가 (edge-tts는 구두점 포함 단어 반환)
            text = ' '.join(w['text'] for w in grp).strip()
            # 공백 중복 제거
            import re
            text = re.sub(r' +', ' ', text)

            # 2줄 분리
            if len(text) > CHARS_PER_LINE:
                mid = len(text) // 2
                # 공백에서 분리 시도
                split_idx = None
                for j in range(mid, 0, -1):
                    if text[j] == ' ':
                        split_idx = j
                        break
                if split_idx is None:
                    for j in range(mid, len(text)):
                        if text[j] == ' ':
                            split_idx = j
                            break
                if split_idx is not None:
                    text = text[:split_idx] + '\n' + text[split_idx + 1:]
                else:
                    text = text[:mid] + '\n' + text[mid:]

            f.write(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n\n")


async def _generate_tts(text: str, voice: str, rate: str,
                        audio_path: str, srt_path: str):
    """edge-tts 스트리밍 → 음성 파일 + 자막 타이밍 SRT 생성"""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    words: list[dict] = []
    audio_bytes = b''

    async for chunk in communicate.stream():
        if chunk['type'] == 'audio':
            audio_bytes += chunk['data']
        elif chunk['type'] == 'WordBoundary':
            # offset / duration 단위: 100 나노초 → 초 변환
            words.append({
                'offset':   chunk['offset']   / 10_000_000,
                'duration': chunk['duration'] / 10_000_000,
                'text':     chunk['text'],
            })

    with open(audio_path, 'wb') as f:
        f.write(audio_bytes)

    _words_to_srt(words, srt_path)
    return len(words)


def run_step6(
    script: str,
    video_id: str,
    voice: str = 'female',
    speed: int = 0,          # -25 ~ +25 (%)
) -> tuple[str, str]:
    """
    한국어 TTS 음성 생성 (edge-tts).

    Returns:
        (audio_path, srt_path)  — 실패 시 ('', '')
    """
    print(f"\n=== TTS 음성 생성 ===\n")

    if not script.strip():
        print("대본이 비어 있습니다.")
        return '', ''

    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("edge-tts 패키지가 필요합니다: pip install edge-tts")
        sys.exit(1)

    voice_name = VOICES.get(voice, VOICES['female'])
    rate_str   = f"+{speed}%" if speed >= 0 else f"{speed}%"
    audio_path = str(AUDIO_DIR / f"{video_id}_tts.mp3")
    srt_path   = str(OUTPUT_DIR / f"{video_id}.srt")

    print(f"대본 길이  : {len(script)}자")
    print(f"목소리     : {VOICE_LABELS.get(voice, voice_name)}")
    print(f"재생 속도  : {rate_str}")

    try:
        word_count = asyncio.run(
            _generate_tts(script, voice_name, rate_str, audio_path, srt_path)
        )
        print(f"TTS 완료   : {Path(audio_path).name}")
        print(f"자막 파일  : {Path(srt_path).name}  (단어 {word_count}개 타이밍 기반)")
        return audio_path, srt_path
    except Exception as e:
        print(f"edge-tts 오류: {e}")
        # gTTS 폴백
        print("gTTS 폴백 시도 중...")
        return _gtts_fallback(script, video_id)


def _gtts_fallback(script: str, video_id: str) -> tuple[str, str]:
    try:
        from gtts import gTTS
    except ImportError:
        print("gTTS도 없습니다. pip install gTTS")
        return '', ''

    audio_path = str(AUDIO_DIR / f"{video_id}_tts.mp3")
    tts = gTTS(text=script, lang='ko', slow=False)
    tts.save(audio_path)
    print(f"gTTS 완료: {Path(audio_path).name}")
    return audio_path, ''  # SRT 없음


if __name__ == '__main__':
    sample = (
        "믿기지 않는 일이 일어났습니다. "
        "길거리에서 만난 강아지가 어린이를 위험에서 구해냈는데요. "
        "어떻게 된 일인지, 지금 바로 알려드릴게요. "
        "이 강아지는 사실 주인도 없이 홀로 돌아다니고 있었습니다. "
        "그런데 아이가 위험에 처한 순간, 누구보다 먼저 달려갔습니다."
    )
    a, s = run_step6(sample, 'test_id', voice='female', speed=0)
    print(f"오디오: {a}")
    print(f"자막  : {s}")
