"""
1~2단계: YouTube Data API로 조건에 맞는 영상 검색 후 사용자 선택
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import YOUTUBE_API_KEY


def _require_google_api():
    try:
        from googleapiclient.discovery import build
        return build
    except ImportError:
        print("google-api-python-client 패키지가 필요합니다.")
        print("pip install google-api-python-client")
        sys.exit(1)


def parse_iso_duration(duration_str: str) -> int:
    """ISO 8601 duration (PT#H#M#S) → 초"""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def format_views(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def search_videos(
    keyword: str,
    start_date: datetime,
    end_date: datetime,
    min_views: int,
    min_duration: int,
    max_duration: int,
) -> list[dict]:
    build = _require_google_api()
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

    search_resp = youtube.search().list(
        part='id',
        q=keyword,
        type='video',
        publishedAfter=start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        publishedBefore=end_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        maxResults=50,
        order='viewCount',
    ).execute()

    video_ids = [item['id']['videoId'] for item in search_resp.get('items', [])]
    if not video_ids:
        return []

    details_resp = youtube.videos().list(
        part='snippet,statistics,contentDetails',
        id=','.join(video_ids),
    ).execute()

    results = []
    for item in details_resp.get('items', []):
        view_count = int(item['statistics'].get('viewCount', 0))
        duration_sec = parse_iso_duration(item['contentDetails']['duration'])

        if view_count < min_views:
            continue
        if not (min_duration <= duration_sec <= max_duration):
            continue

        results.append({
            'video_id': item['id'],
            'title': item['snippet']['title'],
            'url': f"https://www.youtube.com/watch?v={item['id']}",
            'views': view_count,
            'upload_date': item['snippet']['publishedAt'][:10],
            'duration': duration_sec,
            'channel': item['snippet']['channelTitle'],
            'description': item['snippet'].get('description', ''),
        })

    return sorted(results, key=lambda x: x['views'], reverse=True)


def get_user_inputs() -> dict:
    print("\n=== 쇼츠 자동화 파이프라인 - 1단계: 영상 검색 ===\n")

    keyword = input("검색 키워드: ").strip()
    if not keyword:
        print("키워드를 입력해주세요.")
        sys.exit(0)

    now = datetime.now(timezone.utc)
    default_end = now - timedelta(days=90)    # 3개월 전
    default_start = now - timedelta(days=180)  # 6개월 전

    print(f"\n업로드 기간 (기본값: {default_start.strftime('%Y-%m-%d')} ~ {default_end.strftime('%Y-%m-%d')})")
    start_input = input("시작일 (YYYY-MM-DD, 엔터=기본값): ").strip()
    end_input = input("종료일   (YYYY-MM-DD, 엔터=기본값): ").strip()

    try:
        start_date = (
            datetime.strptime(start_input, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if start_input else default_start
        )
        end_date = (
            datetime.strptime(end_input, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if end_input else default_end
        )
    except ValueError:
        print("날짜 형식이 잘못되었습니다. 기본값을 사용합니다.")
        start_date, end_date = default_start, default_end

    min_views_input = input("\n최소 조회수 (예: 500000, 기본값: 100000): ").strip()
    min_views = int(min_views_input) if min_views_input.isdigit() else 100_000

    min_dur_input = input("최소 영상 길이(초) (기본값: 30): ").strip()
    max_dur_input = input("최대 영상 길이(초) (기본값: 180): ").strip()
    min_duration = int(min_dur_input) if min_dur_input.isdigit() else 30
    max_duration = int(max_dur_input) if max_dur_input.isdigit() else 180

    return {
        'keyword': keyword,
        'start_date': start_date,
        'end_date': end_date,
        'min_views': min_views,
        'min_duration': min_duration,
        'max_duration': max_duration,
    }


def run_step1() -> dict | None:
    params = get_user_inputs()

    print(f"\n검색 중... (키워드: {params['keyword']})\n")
    results = search_videos(**params)

    if not results:
        print("조건에 맞는 영상이 없습니다. 조건을 완화해서 다시 시도해보세요.")
        return None

    display_count = min(20, len(results))
    print(f"검색 결과 {len(results)}개 (상위 {display_count}개 표시):\n")
    print(f"{'No':>3}  {'조회수':>8}  {'길이':>5}  {'업로드':>10}  제목")
    print("-" * 72)
    for i, v in enumerate(results[:display_count], 1):
        print(
            f"{i:>3}. {format_views(v['views']):>8}  "
            f"{format_duration(v['duration']):>5}  "
            f"{v['upload_date']}  "
            f"{v['title'][:42]}"
        )

    choice = input("\n선택 (번호 입력, q=종료): ").strip()
    if choice.lower() == 'q':
        return None

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(results[:display_count]):
            selected = results[idx]
            print(f"\n선택된 영상: {selected['title']}")
            print(f"URL: {selected['url']}")
            return selected

    print("잘못된 입력입니다.")
    return None


if __name__ == '__main__':
    result = run_step1()
    if result:
        print(f"\n선택 완료: {result['video_id']}")
