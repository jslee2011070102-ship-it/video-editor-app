"""
1단계: 레퍼런스 탐색
Claude API를 활용해 주제에 대한 리서치 및 트렌드 분석
"""
import anthropic
from dataclasses import dataclass


@dataclass
class ReferenceResult:
    topic: str
    trends: list[str]
    hook_ideas: list[str]
    target_audience: str
    tone: str
    keywords: list[str]


def explore_references(topic: str, client: anthropic.Anthropic) -> ReferenceResult:
    """주제에 대한 레퍼런스 탐색 및 트렌드 분석"""

    prompt = f"""당신은 숏폼 콘텐츠 전문가입니다. 다음 주제로 바이럴 쇼츠 영상을 제작하려 합니다.

주제: {topic}

아래 항목을 분석해주세요:

1. **트렌드 분석** (5가지): 현재 이 주제와 관련된 인기 트렌드
2. **훅(Hook) 아이디어** (5가지): 처음 3초 안에 시청자를 사로잡을 강렬한 시작 문구
3. **타겟 오디언스**: 가장 효과적인 핵심 타겟층
4. **콘텐츠 톤**: (예: 유머/진지/감성/교육적/충격적)
5. **핵심 키워드** (10가지): SEO 및 영상 검색에 유리한 키워드

반드시 JSON 형식으로만 응답하세요:
{{
  "trends": ["트렌드1", "트렌드2", "트렌드3", "트렌드4", "트렌드5"],
  "hook_ideas": ["훅1", "훅2", "훅3", "훅4", "훅5"],
  "target_audience": "타겟 설명",
  "tone": "톤",
  "keywords": ["키워드1", ..., "키워드10"]
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    raw = message.content[0].text.strip()
    # JSON 블록이 마크다운 코드펜스 안에 있을 경우 처리
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())

    return ReferenceResult(
        topic=topic,
        trends=data["trends"],
        hook_ideas=data["hook_ideas"],
        target_audience=data["target_audience"],
        tone=data["tone"],
        keywords=data["keywords"],
    )


def print_reference_result(result: ReferenceResult):
    print(f"\n{'='*50}")
    print(f"[레퍼런스 탐색 결과] 주제: {result.topic}")
    print(f"{'='*50}")
    print(f"\n📊 트렌드:")
    for i, t in enumerate(result.trends, 1):
        print(f"  {i}. {t}")
    print(f"\n🪝 훅 아이디어:")
    for i, h in enumerate(result.hook_ideas, 1):
        print(f"  {i}. {h}")
    print(f"\n🎯 타겟 오디언스: {result.target_audience}")
    print(f"🎭 톤: {result.tone}")
    print(f"\n🔑 키워드: {', '.join(result.keywords)}")
