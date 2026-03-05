# 🎬 쇼츠 자동 생성 파이프라인

Claude API를 활용한 완전 자동화 숏폼 영상 제작 도구.
**TTS와 영상 수집은 완전 무료**로 동작합니다.

## 💰 비용 구조

| 단계 | 도구 | 비용 |
|------|------|------|
| 레퍼런스 탐색 / 기획 / 대본 / 프롬프트 | Claude API | 소량의 토큰 비용 |
| TTS (음성 합성) | **edge-tts** (Microsoft Neural) | **무료** ✅ |
| 영상 수집 | **Pexels API** (스톡 영상) | **무료** ✅ (월 200건) |
| 영상 편집 | **moviepy + ffmpeg** | **무료** ✅ |

---

## 🚀 빠른 시작

### 1. 의존성 설치
```bash
pip install -r requirements.txt

# ffmpeg 설치 (시스템)
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 2. API 키 설정
```bash
cp .env.example .env
# .env 파일 열어서 키 입력
```

**.env 파일:**
```
ANTHROPIC_API_KEY=sk-ant-...        # https://console.anthropic.com
PEXELS_API_KEY=...                   # https://www.pexels.com/api/ (무료)
```

### 3. 실행
```bash
# 기본 실행 (60초 쇼츠)
python src/main.py --topic "매일 5분 영어 공부법"

# 45초, 남성 음성
python src/main.py --topic "주식 초보 투자 실수" --duration 45 --voice male_standard

# 영상 없이 텍스트만 테스트
python src/main.py --topic "AI 트렌드 2025" --skip-video

# 사용 가능한 음성 목록
python src/main.py --list-voices
```

---

## 📁 프로젝트 구조

```
video-editor-app/
├── src/
│   ├── main.py                  # 메인 오케스트레이터
│   ├── reference_explorer.py    # STEP 1: 레퍼런스 탐색
│   ├── planner.py               # STEP 2: 기획
│   ├── script_generator.py      # STEP 3: 대본 생성
│   ├── video_prompt_generator.py # STEP 4: 영상 프롬프트
│   ├── video_fetcher.py         # STEP 5: 영상 수집 (Pexels, 무료)
│   ├── tts_generator.py         # STEP 6: TTS (edge-tts, 무료)
│   └── video_editor.py          # STEP 7: 편집 (moviepy, 무료)
├── output/
│   ├── audio/                   # TTS 생성 오디오
│   ├── video/                   # Pexels 다운로드 영상
│   └── final/                   # 최종 완성 쇼츠
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🔄 파이프라인 상세

```
주제 입력
    │
    ▼
[STEP 1] 레퍼런스 탐색 (Claude)
  → 트렌드, 훅 아이디어, 타겟, 키워드 분석
    │
    ▼
[STEP 2] 콘텐츠 기획 (Claude)
  → 씬 구조 설계, 나레이션 초안, 비주얼 방향
    │
    ▼
[STEP 3] 대본 생성 (Claude)
  → 구어체 대본, 강조 포인트, 씬별 정리
    │
    ▼
[STEP 4] 영상 프롬프트 생성 (Claude)
  → Pexels 검색 키워드 최적화
    │
    ▼
[STEP 5] 영상 수집 (Pexels API - 무료)
  → 씬별 세로형 스톡 영상 자동 다운로드
    │
    ▼
[STEP 6] TTS 생성 (edge-tts - 무료)
  → Microsoft Neural 한국어 음성 합성
  → 씬별 + 전체 오디오 병렬 생성
    │
    ▼
[STEP 7] 영상 편집 (moviepy - 무료)
  → 9:16 세로형 크롭
  → 씬 영상 + TTS 오디오 + 자막 합성
  → 씬 연결 → 최종 mp4 렌더링
    │
    ▼
output/final/[제목].mp4
```

---

## 🎙️ 사용 가능한 한국어 음성 (edge-tts)

| 키 | 음성 ID | 설명 |
|----|---------|------|
| `female_standard` | `ko-KR-SunHiNeural` | 여성, 표준 (기본값) |
| `male_standard` | `ko-KR-InJoonNeural` | 남성, 표준 |
| `male_expressive` | `ko-KR-HyunsuNeural` | 남성, 다중 감정 |

---

## 🔧 개별 모듈 사용

```python
import anthropic
from src.reference_explorer import explore_references
from src.tts_generator import generate_tts, KOREAN_VOICES
from src.video_fetcher import fetch_videos

client = anthropic.Anthropic(api_key="...")

# 레퍼런스만 탐색
ref = explore_references("매일 5분 영어 공부법", client)

# TTS만 생성
from src.script_generator import FullScript, ScriptLine
script = FullScript(title="테스트", lines=[
    ScriptLine(scene_index=1, text="안녕하세요!", emphasis=[], pause_after=0.3)
])
tts = generate_tts(script, "output/audio", KOREAN_VOICES["female_standard"])
```

---

## ⚠️ 주의사항

- **Pexels API**: 월 200 동영상 다운로드 무료. 초과시 유료 플랜 필요.
- **edge-tts**: 인터넷 연결 필요 (오프라인 미지원). 한국어 17개 음성 지원.
- **moviepy**: `libx264` 코덱 필요 → ffmpeg 시스템 설치 필수.
- **GPU**: 불필요. 모든 처리가 CPU로 동작.
