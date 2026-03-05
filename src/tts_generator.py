"""
6단계: TTS 생성 (완전 무료)
edge-tts 사용 - Microsoft Neural 음성 (비용 0원, GPU 불필요)

사용 가능한 한국어 음성:
- ko-KR-SunHiNeural  : 여성, 표준 (기본값)
- ko-KR-InJoonNeural : 남성, 표준
- ko-KR-HyunsuNeural : 남성, 다중감정

설치: pip install edge-tts
"""
import asyncio
import os
from pathlib import Path
from dataclasses import dataclass, field

import edge_tts

from script_generator import FullScript, ScriptLine


@dataclass
class TTSResult:
    scene_index: int
    audio_path: str
    duration_seconds: float


@dataclass
class TTSOutput:
    full_audio_path: str
    scene_audios: list[TTSResult] = field(default_factory=list)


# 사용 가능한 한국어 음성 목록
KOREAN_VOICES = {
    "female_standard": "ko-KR-SunHiNeural",
    "male_standard": "ko-KR-InJoonNeural",
    "male_expressive": "ko-KR-HyunsuNeural",
}


async def _generate_audio(text: str, voice: str, output_path: str) -> float:
    """단일 텍스트를 오디오 파일로 변환 (비동기)"""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

    # 오디오 길이 계산 (moviepy 없이도 동작)
    try:
        from moviepy.editor import AudioFileClip
        clip = AudioFileClip(output_path)
        duration = clip.duration
        clip.close()
        return duration
    except Exception:
        # moviepy 없을 경우 텍스트 길이로 추정 (약 3.5자/초)
        return len(text) / 3.5


async def _generate_scene_audio(
    scene_index: int,
    text: str,
    voice: str,
    output_dir: str,
) -> TTSResult:
    """씬별 오디오 생성"""
    output_path = os.path.join(output_dir, f"scene_{scene_index:02d}.mp3")
    duration = await _generate_audio(text, voice, output_path)
    print(f"  ✅ 씬 {scene_index} TTS 완료: {output_path} ({duration:.1f}초)")
    return TTSResult(
        scene_index=scene_index,
        audio_path=output_path,
        duration_seconds=duration,
    )


async def _generate_full_audio(
    full_text: str,
    voice: str,
    output_dir: str,
) -> str:
    """전체 스크립트 통합 오디오 생성"""
    output_path = os.path.join(output_dir, "full_narration.mp3")
    await _generate_audio(full_text, voice, output_path)
    print(f"  ✅ 전체 나레이션 TTS 완료: {output_path}")
    return output_path


def generate_tts(
    script: FullScript,
    output_dir: str,
    voice: str = KOREAN_VOICES["female_standard"],
) -> TTSOutput:
    """
    스크립트 전체를 TTS로 변환 (edge-tts, 완전 무료)

    Args:
        script: 생성된 대본
        output_dir: 오디오 파일 저장 경로
        voice: 음성 선택 (기본값: 한국어 여성 표준)
    """
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n🎙️  TTS 생성 시작 (음성: {voice})")
    print("  [무료] Microsoft Neural Voice via edge-tts")

    # 씬별 텍스트 모으기
    scenes: dict[int, list[str]] = {}
    for line in script.lines:
        scenes.setdefault(line.scene_index, []).append(line.text)

    async def _run_all():
        # 씬별 오디오 병렬 생성
        tasks = [
            _generate_scene_audio(
                scene_idx,
                " ".join(texts),
                voice,
                output_dir,
            )
            for scene_idx, texts in sorted(scenes.items())
        ]
        scene_results = await asyncio.gather(*tasks)

        # 전체 통합 오디오 생성
        full_text = script.full_text()
        full_path = await _generate_full_audio(full_text, voice, output_dir)

        return full_path, list(scene_results)

    full_path, scene_results = asyncio.run(_run_all())

    return TTSOutput(
        full_audio_path=full_path,
        scene_audios=sorted(scene_results, key=lambda r: r.scene_index),
    )


def list_available_voices():
    """사용 가능한 한국어 음성 목록 출력"""
    async def _list():
        voices = await edge_tts.list_voices()
        korean = [v for v in voices if v["Locale"].startswith("ko-")]
        return korean

    korean_voices = asyncio.run(_list())
    print("\n🎙️  사용 가능한 한국어 음성:")
    for v in korean_voices:
        print(f"  - {v['ShortName']} ({v['Gender']})")
