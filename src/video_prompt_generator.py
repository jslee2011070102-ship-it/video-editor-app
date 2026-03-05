"""
4단계: 영상 프롬프트 생성
각 씬에 맞는 영상 검색 쿼리 및 비주얼 방향 생성
"""
import anthropic
import json
from dataclasses import dataclass, field
from planner import ContentPlan, Scene


@dataclass
class VideoPrompt:
    scene_index: int
    pexels_query: str        # Pexels 검색 키워드 (영어)
    pexels_query_alt: str    # 대체 검색 키워드 (영어)
    orientation: str         # "portrait" (세로) / "landscape" (가로)
    color_mood: str          # 색감 분위기
    description: str         # 씬 비주얼 설명


@dataclass
class VideoPromptSet:
    title: str
    prompts: list[VideoPrompt] = field(default_factory=list)


def generate_video_prompts(
    plan: ContentPlan,
    client: anthropic.Anthropic,
) -> VideoPromptSet:
    """각 씬에 최적화된 영상 검색 프롬프트 생성"""

    scenes_info = "\n".join(
        f"씬{s.index}: {s.visual_description} (나레이션: {s.narration[:30]}...)"
        for s in plan.scenes
    )

    prompt = f"""당신은 영상 감독 겸 Pexels 스톡 영상 검색 전문가입니다.
다음 각 씬에 가장 적합한 Pexels 영상 검색 쿼리를 작성해주세요.

영상 제목: {plan.title}
형식: 세로형 쇼츠 (9:16)

씬 정보:
{scenes_info}

규칙:
- pexels_query는 반드시 영어로 (2~4단어, 구체적으로)
- pexels_query_alt는 검색 실패시 대체 키워드
- orientation은 항상 "portrait" (세로형 쇼츠)
- color_mood: warm/cool/neutral/vibrant/dark 중 하나

반드시 JSON 형식으로만 응답하세요:
{{
  "title": "{plan.title}",
  "prompts": [
    {{
      "scene_index": 씬번호,
      "pexels_query": "english search query",
      "pexels_query_alt": "alternative english query",
      "orientation": "portrait",
      "color_mood": "분위기",
      "description": "씬 비주얼 한국어 설명"
    }}
  ]
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

    prompts = [
        VideoPrompt(
            scene_index=p["scene_index"],
            pexels_query=p["pexels_query"],
            pexels_query_alt=p["pexels_query_alt"],
            orientation=p.get("orientation", "portrait"),
            color_mood=p.get("color_mood", "neutral"),
            description=p.get("description", ""),
        )
        for p in data["prompts"]
    ]

    return VideoPromptSet(title=data["title"], prompts=prompts)


def print_video_prompts(prompt_set: VideoPromptSet):
    print(f"\n{'='*50}")
    print(f"[영상 프롬프트] {prompt_set.title}")
    print(f"{'='*50}")
    for p in prompt_set.prompts:
        print(f"\n  씬 {p.scene_index}: {p.description}")
        print(f"    🔍 Pexels 검색: '{p.pexels_query}' / 대체: '{p.pexels_query_alt}'")
        print(f"    🎨 색감: {p.color_mood} | 방향: {p.orientation}")
