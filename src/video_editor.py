"""
7단계: 영상 편집 (완전 무료)
moviepy + ffmpeg를 사용해 영상 + 대본 자막 + TTS 합성

설치: pip install moviepy imageio[ffmpeg]
"""
import os
from dataclasses import dataclass

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip,
)
from moviepy.video.fx.resize import resize

from planner import ContentPlan, Scene
from script_generator import FullScript
from tts_generator import TTSOutput
from video_fetcher import FetchedVideoSet


# 쇼츠 해상도 (9:16 세로형)
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920


@dataclass
class EditResult:
    output_path: str
    duration: float
    resolution: tuple[int, int]


def _crop_to_portrait(clip: VideoFileClip) -> VideoFileClip:
    """영상을 9:16 세로형으로 크롭"""
    target_ratio = SHORTS_WIDTH / SHORTS_HEIGHT
    current_ratio = clip.w / clip.h

    if current_ratio > target_ratio:
        # 가로가 더 넓음 → 좌우 크롭
        new_width = int(clip.h * target_ratio)
        x_center = clip.w / 2
        clip = clip.crop(
            x1=x_center - new_width / 2,
            x2=x_center + new_width / 2,
        )
    elif current_ratio < target_ratio:
        # 세로가 더 김 → 상하 크롭 (중앙 기준)
        new_height = int(clip.w / target_ratio)
        y_center = clip.h / 2
        clip = clip.crop(
            y1=y_center - new_height / 2,
            y2=y_center + new_height / 2,
        )

    return resize(clip, (SHORTS_WIDTH, SHORTS_HEIGHT))


def _add_subtitle(
    text: str,
    duration: float,
    fontsize: int = 60,
    color: str = "white",
    stroke_color: str = "black",
    stroke_width: int = 3,
    position: tuple = ("center", 0.75),
) -> TextClip:
    """자막 텍스트 클립 생성"""
    txt_clip = TextClip(
        text,
        fontsize=fontsize,
        color=color,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
        size=(SHORTS_WIDTH - 80, None),
        method="caption",
        align="center",
    ).set_duration(duration)

    # 화면 하단 75% 위치에 자막 배치
    txt_clip = txt_clip.set_position(
        (position[0], SHORTS_HEIGHT * position[1] - txt_clip.h / 2)
    )
    return txt_clip


def _build_scene_clip(
    scene: Scene,
    raw_video_path: str,
    audio_path: str,
    narration_text: str,
    target_duration: float,
) -> CompositeVideoClip:
    """씬 단위 클립 합성: 영상 + 자막 + 오디오"""
    # 1. 영상 불러오기 및 세로형 크롭
    video = VideoFileClip(raw_video_path)
    video = _crop_to_portrait(video)

    # 오디오 길이에 맞게 영상 길이 조정
    audio = AudioFileClip(audio_path)
    actual_duration = audio.duration

    if video.duration < actual_duration:
        # 영상이 짧으면 루프
        loops = int(actual_duration / video.duration) + 1
        from moviepy.editor import concatenate_videoclips
        video = concatenate_videoclips([video] * loops)

    video = video.subclip(0, actual_duration)

    # 2. 자막 생성
    subtitle = _add_subtitle(narration_text, actual_duration)

    # 3. 합성
    composite = CompositeVideoClip([video, subtitle])
    composite = composite.set_audio(audio)
    return composite


def _build_fallback_clip(
    scene: Scene,
    audio_path: str,
    narration_text: str,
    bg_color: tuple = (20, 20, 40),
) -> CompositeVideoClip:
    """영상 파일 없을 때 단색 배경 + 자막 클립 생성"""
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    bg = ColorClip(
        size=(SHORTS_WIDTH, SHORTS_HEIGHT),
        color=bg_color,
        duration=duration,
    )

    # 씬 제목 (상단)
    title_clip = TextClip(
        scene.title,
        fontsize=50,
        color="white",
        size=(SHORTS_WIDTH - 100, None),
        method="caption",
        align="center",
    ).set_duration(duration).set_position(("center", 200))

    # 나레이션 자막 (하단)
    subtitle = _add_subtitle(narration_text, duration)

    composite = CompositeVideoClip([bg, title_clip, subtitle])
    composite = composite.set_audio(audio)
    return composite


def edit_shorts(
    plan: ContentPlan,
    script: FullScript,
    tts_output: TTSOutput,
    fetched_videos: FetchedVideoSet,
    output_dir: str,
    output_filename: str = "final_shorts.mp4",
) -> EditResult:
    """
    모든 씬을 합쳐 최종 쇼츠 영상 편집 (moviepy, 완전 무료)

    Args:
        plan: 콘텐츠 기획
        script: 완성 대본
        tts_output: TTS 오디오 파일
        fetched_videos: 다운로드된 영상 파일
        output_dir: 최종 출력 경로
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    print(f"\n✂️  영상 편집 시작 (moviepy - 무료)")

    # 씬별 오디오 매핑
    audio_map = {r.scene_index: r.audio_path for r in tts_output.scene_audios}

    # 씬별 영상 매핑
    video_map = {v.scene_index: v.local_path for v in fetched_videos.videos}

    scene_clips = []

    for scene in plan.scenes:
        narration_text = script.scene_text(scene.index)
        audio_path = audio_map.get(scene.index)

        if not audio_path or not os.path.exists(audio_path):
            print(f"  ⚠️  씬 {scene.index}: TTS 오디오 없음, 건너뜀")
            continue

        raw_video_path = video_map.get(scene.index)

        if raw_video_path and os.path.exists(raw_video_path):
            print(f"  🎬 씬 {scene.index}: 영상 + 자막 + TTS 합성 중...")
            clip = _build_scene_clip(
                scene=scene,
                raw_video_path=raw_video_path,
                audio_path=audio_path,
                narration_text=narration_text,
                target_duration=scene.duration,
            )
        else:
            print(f"  🎨 씬 {scene.index}: 영상 없음, 단색 배경으로 대체 중...")
            clip = _build_fallback_clip(
                scene=scene,
                audio_path=audio_path,
                narration_text=narration_text,
            )

        scene_clips.append(clip)
        print(f"  ✅ 씬 {scene.index} 완료 ({clip.duration:.1f}초)")

    if not scene_clips:
        raise RuntimeError("합성할 씬 클립이 없습니다.")

    # 전체 영상 연결
    print(f"\n  🔗 {len(scene_clips)}개 씬 연결 중...")
    final_video = concatenate_videoclips(scene_clips, method="compose")

    # 최종 렌더링
    print(f"  💾 최종 렌더링 → {output_path}")
    print(f"  (해상도: {SHORTS_WIDTH}x{SHORTS_HEIGHT}, 길이: {final_video.duration:.1f}초)")

    final_video.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp_audio.m4a",
        remove_temp=True,
        preset="fast",        # 빠른 인코딩 (용량 약간 큼)
        threads=4,
        logger="bar",
    )

    # 클립 메모리 해제
    for clip in scene_clips:
        clip.close()
    final_video.close()

    result = EditResult(
        output_path=output_path,
        duration=final_video.duration,
        resolution=(SHORTS_WIDTH, SHORTS_HEIGHT),
    )

    print(f"\n🎉 최종 영상 완성!")
    print(f"   경로: {output_path}")
    print(f"   길이: {result.duration:.1f}초")
    print(f"   해상도: {SHORTS_WIDTH}x{SHORTS_HEIGHT}")
    return result
