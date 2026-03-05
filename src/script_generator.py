"""
3단계: 대본 생성
기획된 씬별 나레이션을 완성도 높은 대본으로 발전
"""
import anthropic
import json
from dataclasses import dataclass, field
from planner import ContentPlan, Scene


@dataclass
class ScriptLine:
    scene_index: int
    text: str            # 실제 읽힐 텍스트
    emphasis: list[str]  # 강조할 단어/문구
    pause_after: float   # 다음 줄 전 쉬는 시간 (초)


@dataclass
class FullScript:
    title: str
    lines: list[ScriptLine] = field(default_factory=list)

    def full_text(self) -> str:
        return " ".join(line.text for line in self.lines)

    def scene_text(self, scene_index: int) -> str:
        return " ".join(
            line.text for line in self.lines if line.scene_index == scene_index
        )


def generate_script(plan: ContentPlan, client: anthropic.Anthropic) -> FullScript:
    """기획안을 바탕으로 완성된 대본 생성"""

    scenes_info = "\n".join(
        f"씬{s.index} ({s.duration}초): {s.narration}"
        for s in plan.scenes
    )

    prompt = f"""당신은 숏폼 영상 대본 작가입니다. 다음 기획안을 바탕으로 자연스럽고 몰입감 있는 대본을 완성해주세요.

영상 제목: {plan.title}
훅: {plan.hook}

씬별 나레이션 초안:
{scenes_info}

작성 규칙:
- 각 씬의 나레이션을 자연스러운 구어체로 다듬기
- TTS로 읽힐 것을 고려해 문장 길이 조절 (한 문장 15자 이내 권장)
- 강조할 핵심 단어 선정
- 씬 전환 시 0.5초 쉼 추가

반드시 JSON 형식으로만 응답하세요:
{{
  "title": "{plan.title}",
  "lines": [
    {{
      "scene_index": 씬번호,
      "text": "읽힐 텍스트",
      "emphasis": ["강조단어1", "강조단어2"],
      "pause_after": 쉼시간(초, 0.0~1.0)
    }}
  ]
}}

각 씬마다 최소 1개 이상의 line을 생성하세요."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())

    lines = [
        ScriptLine(
            scene_index=l["scene_index"],
            text=l["text"],
            emphasis=l.get("emphasis", []),
            pause_after=l.get("pause_after", 0.3),
        )
        for l in data["lines"]
    ]

    return FullScript(title=data["title"], lines=lines)


def print_script(script: FullScript):
    print(f"\n{'='*50}")
    print(f"[완성 대본] {script.title}")
    print(f"{'='*50}")
    current_scene = None
    for line in script.lines:
        if line.scene_index != current_scene:
            current_scene = line.scene_index
            print(f"\n--- 씬 {current_scene} ---")
        emphasis_str = f" [강조: {', '.join(line.emphasis)}]" if line.emphasis else ""
        print(f"  {line.text}{emphasis_str}")
        if line.pause_after > 0:
            print(f"  (쉬기: {line.pause_after}초)")
