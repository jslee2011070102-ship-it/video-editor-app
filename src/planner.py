"""
2단계: 기획
레퍼런스 분석 결과를 바탕으로 쇼츠 콘텐츠 구조 설계
"""
import anthropic
import json
from dataclasses import dataclass, field
from reference_explorer import ReferenceResult


@dataclass
class Scene:
    index: int
    title: str           # 씬 제목
    duration: int        # 예상 길이 (초)
    narration: str       # 해설 텍스트 (TTS로 변환됨)
    visual_description: str  # 시각적 묘사 (영상 검색에 사용)


@dataclass
class ContentPlan:
    title: str
    hook: str
    total_duration: int
    scenes: list[Scene] = field(default_factory=list)
    call_to_action: str = ""
    hashtags: list[str] = field(default_factory=list)


def create_content_plan(
    reference: ReferenceResult,
    target_duration: int,
    client: anthropic.Anthropic,
) -> ContentPlan:
    """레퍼런스를 바탕으로 쇼츠 콘텐츠 기획"""

    prompt = f"""당신은 숏폼 영상 기획 전문가입니다. 다음 정보를 바탕으로 {target_duration}초짜리 쇼츠 영상을 기획해주세요.

주제: {reference.topic}
톤: {reference.tone}
타겟: {reference.target_audience}
추천 훅: {reference.hook_ideas[0]}
트렌드: {', '.join(reference.trends[:3])}

영상 구조를 씬(scene) 단위로 기획하되, 아래 규칙을 따르세요:
- 첫 씬은 반드시 3초 이내의 강력한 훅으로 시작
- 각 씬은 5~15초 분량
- 총 {target_duration}초를 넘지 않도록
- 마지막 씬에는 반드시 CTA (Call to Action) 포함

반드시 JSON 형식으로만 응답하세요:
{{
  "title": "영상 제목",
  "hook": "첫 훅 문구",
  "total_duration": {target_duration},
  "scenes": [
    {{
      "index": 1,
      "title": "씬 이름",
      "duration": 초수,
      "narration": "이 씬에서 읽힐 나레이션 텍스트",
      "visual_description": "화면에 보여질 장면 설명 (영어로)"
    }}
  ],
  "call_to_action": "구독/좋아요 등 CTA 문구",
  "hashtags": ["#해시태그1", "#해시태그2", "#해시태그3", "#해시태그4", "#해시태그5"]
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())

    scenes = [
        Scene(
            index=s["index"],
            title=s["title"],
            duration=s["duration"],
            narration=s["narration"],
            visual_description=s["visual_description"],
        )
        for s in data["scenes"]
    ]

    return ContentPlan(
        title=data["title"],
        hook=data["hook"],
        total_duration=data["total_duration"],
        scenes=scenes,
        call_to_action=data["call_to_action"],
        hashtags=data["hashtags"],
    )


def print_content_plan(plan: ContentPlan):
    print(f"\n{'='*50}")
    print(f"[콘텐츠 기획] {plan.title}")
    print(f"{'='*50}")
    print(f"🪝 훅: {plan.hook}")
    print(f"⏱️  총 길이: {plan.total_duration}초")
    print(f"\n📋 씬 구성:")
    for scene in plan.scenes:
        print(f"\n  [{scene.index}] {scene.title} ({scene.duration}초)")
        print(f"       나레이션: {scene.narration[:50]}...")
        print(f"       비주얼: {scene.visual_description[:50]}...")
    print(f"\n📣 CTA: {plan.call_to_action}")
    print(f"🏷️  해시태그: {' '.join(plan.hashtags)}")
