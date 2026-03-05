"""
쇼츠 자동화 파이프라인 - 웹 서버
실행: python shorts_automation/web_app.py
브라우저: http://localhost:5000
"""
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, jsonify, render_template, request, send_file

from config import OUTPUT_DIR
from step1_search import search_videos
from step2_original import search_original_candidates
from step3_download import run_step3
from step4_analyze import run_step4
from step5_clip_edit import run_step5
from step6_tts import run_step6
from step7_merge import run_step7

app = Flask(__name__)

# { job_id: {'status', 'progress', 'message', 'result'} }
jobs: dict = {}


# ─── 파이프라인 백그라운드 실행 ────────────────────────────────────────────

def _run_pipeline(job_id: str, video: dict):
    def upd(message: str, progress: int):
        jobs[job_id].update(status='running', message=message, progress=progress)
        print(f"[{job_id}] {progress}% - {message}")

    jobs[job_id] = {'status': 'running', 'progress': 0, 'message': '시작 중...'}
    video_id = video['video_id']

    try:
        upd('영상 다운로드 + 자막 추출 중...', 10)
        dl = run_step3(video['url'], video_id)
        if not dl.get('video_path'):
            raise RuntimeError('영상 다운로드에 실패했습니다.')

        upd('AI 분석 + 한국어 대본 재작성 중... (30~60초 소요)', 30)
        analysis = run_step4(dl.get('subtitle_path'), video_id, video_info=video)
        script = analysis.get('new_script', '').strip()
        if not script:
            raise RuntimeError('AI 대본 생성에 실패했습니다.')

        upd('영상 클립 기승전결 재편집 중...', 55)
        rearranged = run_step5(dl['video_path'], analysis, video_id)

        upd('gTTS 한국어 음성 생성 중...', 70)
        audio = run_step6(script, video_id)
        if not audio:
            raise RuntimeError('TTS 음성 생성에 실패했습니다.')

        upd('영상 + 음성 + 자막 최종 합성 중...', 83)
        final = run_step7(rearranged, audio, script, video_id)
        if not final:
            raise RuntimeError('최종 영상 합성에 실패했습니다.')

        jobs[job_id] = {
            'status': 'done',
            'progress': 100,
            'message': '완성!',
            'result': Path(final).name,
        }

    except Exception as e:
        jobs[job_id] = {'status': 'error', 'progress': 0, 'message': str(e)}
        print(f"[{job_id}] 오류: {e}")


# ─── 라우트 ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json or {}
    try:
        start = datetime.strptime(data['start_date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end = datetime.strptime(data['end_date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=180)
        end = now - timedelta(days=90)

    try:
        results = search_videos(
            keyword=data.get('keyword', ''),
            start_date=start,
            end_date=end,
            min_views=int(data.get('min_views', 100_000)),
            min_duration=int(data.get('min_duration', 30)),
            max_duration=int(data.get('max_duration', 180)),
        )
        return jsonify({'results': results[:20]})
    except Exception as e:
        return jsonify({'error': str(e), 'results': []}), 500


@app.route('/api/find-original', methods=['POST'])
def api_find_original():
    video = (request.json or {}).get('video', {})
    try:
        candidates = search_original_candidates(video)
        return jsonify({'candidates': candidates[:10]})
    except Exception as e:
        return jsonify({'error': str(e), 'candidates': []}), 500


@app.route('/api/process', methods=['POST'])
def api_process():
    video = (request.json or {}).get('video', {})
    job_id = uuid.uuid4().hex[:8]
    t = threading.Thread(target=_run_pipeline, args=(job_id, video), daemon=True)
    t.start()
    return jsonify({'job_id': job_id})


@app.route('/api/status/<job_id>')
def api_status(job_id):
    return jsonify(jobs.get(job_id, {'status': 'not_found', 'progress': 0, 'message': ''}))


@app.route('/output/<path:filename>')
def serve_output(filename):
    path = OUTPUT_DIR / filename
    if not path.exists():
        return 'Not found', 404
    return send_file(str(path), mimetype='video/mp4')


# ─── 실행 ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("  쇼츠 자동화 파이프라인 웹 서버 시작")
    print("  브라우저에서 http://localhost:5000 열어주세요")
    print("=" * 50 + "\n")
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
