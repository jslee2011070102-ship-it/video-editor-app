"""
3단계: 선택한 영상의 원본 출처를 탐색하고 사용자가 선택
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import YOUTUBE_API_KEY


def _require_google_api():
    try:
        from googleapiclient.discovery import build
        return build
    except ImportError:
        print("google-api-python-client 패키지가 필요합니다.")
        sys.exit(1)


def extract_search_keyword(title: str, description: str) -> str:
    """제목/설명에서 원본 출처 검색 키워드 추출"""

    # 설명에서 명시적 출처 표기 우선 탐색
    source_patterns = [
        r'원본[:\s]+(.+?)(?:\n|$)',
        r'출처[:\s]+(.+?)(?:\n|$)',
        r'source[:\s]+(.+?)(?:\n|$)',
        r'credit[s]?[:\s]+(.+?)(?:\n|$)',
        r'via[:\s]+(.+?)(?:\n|$)',
        r'original[:\s]+(.+?)(?:\n|$)',
    ]
    for pattern in source_patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            kw = re.sub(r'https?://\S+', '', match.group(1)).strip()
            if kw:
                return kw[:80]

    # 제목에서 재업로드/모음집 마커 제거 후 핵심어 추출
    cleaned = title
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    cleaned = re.sub(r'[#@]\S+', '', cleaned)
    cleaned = re.sub(r'\[.*?\]|\(.*?\)', '', cleaned)
    cleaned = re.sub(
        r'(shorts|쇼츠|viral|trending|compilation|모음|짤|repost|reaction|리액션)',
        '', cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:60]


def search_original_candidates(video_info: dict) -> list[dict]:
    build = _require_google_api()
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

    keyword = extract_search_keyword(video_info['title'], video_info['description'])

    # 선택 영상 업로드일보다 이전에 올라온 영상 검색
    published_before = video_info['upload_date'] + 'T00:00:00Z'

    search_resp = youtube.search().list(
        part='id',
        q=keyword,
        type='video',
        publishedBefore=published_before,
        maxResults=20,
        order='relevance',
    ).execute()

    video_ids = [
        item['id']['videoId']
        for item in search_resp.get('items', [])
        if item['id']['videoId'] != video_info['video_id']
    ]

    if not video_ids:
        return []

    details_resp = youtube.videos().list(
        part='snippet,statistics',
        id=','.join(video_ids),
    ).execute()

    results = []
    for item in details_resp.get('items', []):
        results.append({
            'video_id': item['id'],
            'title': item['snippet']['title'],
            'url': f"https://www.youtube.com/watch?v={item['id']}",
            'views': int(item['statistics'].get('viewCount', 0)),
            'upload_date': item['snippet']['publishedAt'][:10],
            'channel': item['snippet']['channelTitle'],
            'description': item['snippet'].get('description', ''),
        })

    return results


def run_step2(video_info: dict) -> dict:
    print(f"\n=== 3단계: 원본 영상 탐색 ===\n")
    print(f"선택 영상: {video_info['title']}")

    keyword = extract_search_keyword(video_info['title'], video_info['description'])
    print(f"추출된 검색 키워드: '{keyword}'\n")

    print("원본 후보 검색 중...")
    candidates = search_original_candidates(video_info)

    if not candidates:
        print("원본 후보를 찾지 못했습니다. 선택한 영상을 그대로 사용합니다.")
        return video_info

    display = candidates[:10]
    print(f"\n원본 후보 {len(display)}개:\n")
    print(f"{'No':>3}  {'조회수':>8}  {'업로드':>10}  제목")
    print("-" * 68)
    print(f"  0.  {'':>8}  {'':>10}  [건너뛰기 - 선택한 영상 그대로 사용]")
    for i, v in enumerate(display, 1):
        views_str = (
            f"{v['views'] / 1_000_000:.1f}M" if v['views'] >= 1_000_000
            else f"{v['views'] // 1000}K"
        )
        print(f"{i:>3}. {views_str:>8}  {v['upload_date']}  {v['title'][:48]}")

    choice = input("\n선택 (번호 입력): ").strip()

    if choice == '0' or not choice:
        print("선택한 영상을 그대로 사용합니다.")
        return video_info

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(display):
            selected = display[idx]
            print(f"\n원본 선택: {selected['title']}")
            return selected

    print("잘못된 입력. 원래 영상을 사용합니다.")
    return video_info


if __name__ == '__main__':
    test = {
        'video_id': 'abc123',
        'title': 'Amazing dog rescue compilation 2024',
        'url': 'https://youtube.com/watch?v=abc123',
        'views': 1_500_000,
        'upload_date': '2024-09-01',
        'description': '출처: @originaldog\n원본 채널에서 허락받음',
    }
    result = run_step2(test)
    print(f"\n최종 선택: {result['title']}")
