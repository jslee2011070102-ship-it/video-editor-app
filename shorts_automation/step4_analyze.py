"""
5~9단계: AI(Gemini 또는 Claude)로 자막 분석 + 한국어 대본 재작성

나중에 Claude API로 교체하려면 .env에서 AI_PROVIDER=claude 로 설정
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import AI_PROVIDER, GEMINI_API_KEY, ANTHROPIC_API_KEY, SCRIPTS_DIR
from step3_download import parse_srt

# ─── AI 호출 레이어 (교체 가능) ───────────────────────────────────────────

def _call_gemini(prompt: str) -> str:
    try:
        from google import genai
    except ImportError:
        print("google-genai 패키지가 필요합니다: pip install google-genai")
        sys.exit(1)

    client = genai.Client(api_key=GEMINI_API_KEY)
    # 무료 할당량 넉넉한 순서로 모델 시도
    models = ['gemini-1.5-flash', 'gemini-2.0-flash-lite', 'gemini-1.5-flash-8b', 'gemini-2.0-flash']
    last_err = None
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            print(f"  (사용 모델: {model_name})")
            return response.text
        except Exception as e:
            print(f"  {model_name} 실패: {str(e)[:100]}")
            last_err = e
    raise last_err


def _call_claude(prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        print("anthropic 패키지가 필요합니다: pip install anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model='claude-opus-4-6',
        max_tokens=4096,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return message.content[0].text


def call_ai(prompt: str) -> str:
    if AI_PROVIDER == 'claude':
        print(f"  (Claude API 사용)")
        return _call_claude(prompt)
    print(f"  (Gemini API 사용)")
    return _call_gemini(prompt)


# ─── 분석 + 대본 재작성 ────────────────────────────────────────────────────

ANALYSIS_PROMPT = """아래는 유튜브 영상의 자막입니다.

[자막 내용]
{subtitle_text}

다음 작업을 수행하고, 반드시 아래 JSON 형식으로만 응답해주세요. 마크다운 코드블록 없이 순수 JSON만 출력하세요.

{{
  "narrative_structure": {{
    "intro":       {{"summary": "도입부 요약", "start_ratio": 0.0, "end_ratio": 0.25}},
    "development": {{"summary": "전개부 요약", "start_ratio": 0.25, "end_ratio": 0.70}},
    "climax":      {{"summary": "결말/클라이맥스 요약", "start_ratio": 0.70, "end_ratio": 1.0}}
  }},
  "keywords": ["핵심키워드1", "핵심키워드2", "핵심키워드3"],
  "rearranged_order": ["climax", "intro", "development"],
  "similar_keywords": {{"원본키워드": "유사단어"}},
  "new_script": "완전히 새로 작성된 한국어 쇼츠 대본"
}}

new_script 작성 규칙 (매우 중요):
- 분량: 40~55초 TTS 낭독 기준 (약 200~280자)
- 첫 2~3초: 시청자가 멈추게 만드는 강한 훅 문장 (예: "이걸 보고도 믿을 수 있을까요?")
- 문체: 실제 유튜브 나레이터가 말하듯 자연스러운 한국어 구어체
  * 너무 딱딱하거나 뉴스 앵커 말투 금지
  * 짧고 리듬감 있는 문장 사용 (한 문장 20자 이내 권장)
  * 감탄사·추임새 자연스럽게 포함 (예: "그런데요", "놀랍게도", "사실은")
  * 존댓말 일관성 유지 (습니다/요 체 또는 해요체 중 하나로 통일)
- 원본 문장을 직역하지 말고 한국 시청자 감성에 맞게 완전히 새로 작성
- rearranged_order 순서로 기승전결 재배치 반영
- 자연스러운 낭독을 위해 문장 끝에 마침표(.) 또는 느낌표(!) 반드시 포함
- 문장 사이 줄바꿈 없이 이어서 작성 (한 문단으로)
- 절대 금지: 영어 단어 혼용, 어색한 번역투, 지나치게 긴 복합문"""


def _extract_json(raw: str) -> dict:
    """AI 응답에서 JSON 파싱 (마크다운 코드블록 포함 대응)"""
    # 마크다운 코드블록 제거
    cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r'\s*```$', '', cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()

    # JSON 객체 추출
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        raise ValueError("JSON을 찾을 수 없습니다.")

    return json.loads(match.group())


def analyze_and_rewrite(subtitle_text: str, video_id: str) -> dict:
    print(f"\n=== 5~9단계: AI 분석 + 대본 재작성 ===\n")
    print(f"자막 길이: {len(subtitle_text)}자")

    prompt = ANALYSIS_PROMPT.format(subtitle_text=subtitle_text[:6000])

    print("AI 분석 중...")
    raw = call_ai(prompt)

    try:
        analysis = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"JSON 파싱 실패: {e}")
        print(f"AI 응답 앞부분:\n{raw[:600]}")
        return {}

    # 결과 저장
    script_path = SCRIPTS_DIR / f"{video_id}_script.txt"
    script_path.write_text(analysis.get('new_script', ''), encoding='utf-8')
    print(f"대본 저장: {script_path.name}")

    analysis_path = SCRIPTS_DIR / f"{video_id}_analysis.json"
    analysis_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f"분석 결과 저장: {analysis_path.name}")

    order = analysis.get('rearranged_order', [])
    print(f"\n재배치 순서: {' → '.join(order)}")
    script_preview = analysis.get('new_script', '')[:120]
    print(f"새 대본 미리보기:\n  {script_preview}...")

    return analysis


def run_step4(subtitle_path: str | None, video_id: str, video_info: dict | None = None) -> dict:
    if subtitle_path:
        subtitle_text = parse_srt(subtitle_path)
        if subtitle_text.strip():
            return analyze_and_rewrite(subtitle_text, video_id)
        print("자막 내용이 비어 있습니다. 영상 제목/설명으로 대본을 생성합니다.")
    else:
        print("\n자막 없음. 영상 제목/설명 기반으로 대본을 생성합니다.")

    # 자막 없을 때 fallback: 제목+설명으로 대본 생성
    if not video_info:
        print("영상 정보도 없습니다. 대본 생성을 건너뜁니다.")
        return {}

    title = video_info.get('title', '')
    description = video_info.get('description', '')[:500]
    fallback_text = f"영상 제목: {title}\n영상 설명: {description}"
    print(f"제목 기반 대본 생성: {title[:60]}")
    return analyze_and_rewrite(fallback_text, video_id)


if __name__ == '__main__':
    sample = (
        "This is an incredible story. A stray dog saved a child from danger. "
        "The dog barked loudly to alert the parents. Everyone was amazed by the dog's courage. "
        "The family decided to adopt the dog. Now they live happily together."
    )
    result = analyze_and_rewrite(sample, 'test_id')
    print(json.dumps(result, ensure_ascii=False, indent=2))
