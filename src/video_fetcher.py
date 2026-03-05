"""
5단계: 영상 수집 (완전 무료)
Pexels API를 사용한 무료 스톡 영상 다운로드

Pexels 무료 정책:
- API 키 발급: https://www.pexels.com/api/ (무료)
- 월 200 크레딧 무료 (동영상 1개 = 약 1 크레딧)
- 상업적 이용 가능, 저작권 무료

발급 방법:
1. https://www.pexels.com 회원가입
2. https://www.pexels.com/api/ 접속 → API 키 발급
3. .env 파일에 PEXELS_API_KEY 설정
"""
import os
import requests
from pathlib import Path
from dataclasses import dataclass, field
from tqdm import tqdm

from video_prompt_generator import VideoPrompt, VideoPromptSet


PEXELS_API_BASE = "https://api.pexels.com/videos"


@dataclass
class FetchedVideo:
    scene_index: int
    local_path: str
    pexels_id: int
    duration: int      # 원본 영상 길이 (초)
    width: int
    height: int
    query_used: str


@dataclass
class FetchedVideoSet:
    videos: list[FetchedVideo] = field(default_factory=list)


def _search_pexels_video(
    query: str,
    api_key: str,
    orientation: str = "portrait",
    per_page: int = 5,
) -> list[dict]:
    """Pexels에서 영상 검색"""
    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "orientation": orientation,
        "per_page": per_page,
        "size": "medium",
    }
    resp = requests.get(f"{PEXELS_API_BASE}/search", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json().get("videos", [])


def _download_video(url: str, output_path: str) -> bool:
    """영상 파일 다운로드"""
    resp = requests.get(url, stream=True)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    with open(output_path, "wb") as f, tqdm(
        desc=f"  다운로드",
        total=total,
        unit="iB",
        unit_scale=True,
        unit_divisor=1024,
        leave=False,
    ) as bar:
        for chunk in resp.iter_content(chunk_size=8192):
            size = f.write(chunk)
            bar.update(size)
    return True


def _pick_best_video_file(video: dict, prefer_portrait: bool = True) -> dict | None:
    """가장 적합한 화질의 영상 파일 선택 (HD 우선)"""
    files = video.get("video_files", [])
    if not files:
        return None

    # 세로형 선호 시 portrait 필터
    if prefer_portrait:
        portrait_files = [
            f for f in files
            if f.get("height", 0) > f.get("width", 0)
        ]
        if portrait_files:
            files = portrait_files

    # HD(720p~1080p) 우선 선택
    hd_files = [
        f for f in files
        if 720 <= f.get("height", 0) <= 1920
    ]
    target = hd_files or files

    # 해상도 내림차순 정렬 후 최고 품질 선택
    return sorted(target, key=lambda f: f.get("height", 0), reverse=True)[0]


def fetch_videos(
    prompt_set: VideoPromptSet,
    api_key: str,
    output_dir: str,
    scene_durations: dict[int, int] | None = None,
) -> FetchedVideoSet:
    """
    씬별 영상 다운로드 (Pexels API, 완전 무료)

    Args:
        prompt_set: 씬별 검색 프롬프트
        api_key: Pexels API 키 (.env에서 로드)
        output_dir: 다운로드 경로
        scene_durations: 씬별 필요 길이 {scene_index: 초}
    """
    os.makedirs(output_dir, exist_ok=True)
    result = FetchedVideoSet()

    print(f"\n🎬 영상 수집 시작 (Pexels API - 무료)")

    for prompt in prompt_set.prompts:
        print(f"\n  씬 {prompt.scene_index}: '{prompt.pexels_query}' 검색 중...")

        # 1차 검색
        videos = _search_pexels_video(
            prompt.pexels_query, api_key, prompt.orientation
        )

        # 결과 없으면 대체 키워드로 재시도
        if not videos:
            print(f"    ⚠️  결과 없음, 대체 검색: '{prompt.pexels_query_alt}'")
            videos = _search_pexels_video(
                prompt.pexels_query_alt, api_key, prompt.orientation
            )

        # 여전히 없으면 landscape로 재시도
        if not videos:
            print(f"    ⚠️  세로형 없음, landscape로 재시도...")
            videos = _search_pexels_video(
                prompt.pexels_query, api_key, "landscape"
            )

        if not videos:
            print(f"    ❌ 씬 {prompt.scene_index}: 영상을 찾을 수 없습니다.")
            continue

        # 씬 필요 길이 이상의 영상 우선 선택
        need_duration = (scene_durations or {}).get(prompt.scene_index, 5)
        long_enough = [v for v in videos if v.get("duration", 0) >= need_duration]
        target_video = (long_enough or videos)[0]

        video_file = _pick_best_video_file(
            target_video, prefer_portrait=(prompt.orientation == "portrait")
        )
        if not video_file:
            print(f"    ❌ 씬 {prompt.scene_index}: 적합한 파일 없음.")
            continue

        output_path = os.path.join(
            output_dir, f"scene_{prompt.scene_index:02d}_raw.mp4"
        )
        print(f"    ⬇️  다운로드: {video_file.get('width')}x{video_file.get('height')}")
        _download_video(video_file["link"], output_path)

        result.videos.append(
            FetchedVideo(
                scene_index=prompt.scene_index,
                local_path=output_path,
                pexels_id=target_video["id"],
                duration=target_video.get("duration", 0),
                width=video_file.get("width", 0),
                height=video_file.get("height", 0),
                query_used=prompt.pexels_query,
            )
        )
        print(f"    ✅ 씬 {prompt.scene_index} 완료: {output_path}")

    print(f"\n  총 {len(result.videos)}개 영상 다운로드 완료")
    return result
