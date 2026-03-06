"""쿠팡 판매자 크롤러 - Streamlit UI.

실행 방법:
    cd coupang_seller_crawler
    streamlit run app.py
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
EXPORTS_DIR = BASE_DIR / "data" / "exports"
LOGS_DIR = BASE_DIR / "data" / "logs"
CONFIG_DIR = BASE_DIR / "config"
KEYWORDS_FILE = CONFIG_DIR / "keywords.txt"

# ─────────────────────────────────────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="쿠팡 판매자 크롤러",
    page_icon="🕷️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Session State 초기화
# ─────────────────────────────────────────────────────────────────────────────
if "log_lines" not in st.session_state:
    st.session_state.log_lines: list[str] = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "proc" not in st.session_state:
    st.session_state.proc = None
if "log_queue" not in st.session_state:
    st.session_state.log_queue: queue.Queue = queue.Queue()
if "finished" not in st.session_state:
    st.session_state.finished = False
if "keywords_text" not in st.session_state:
    # 기본 키워드 파일에서 로드
    if KEYWORDS_FILE.exists():
        raw = KEYWORDS_FILE.read_text(encoding="utf-8")
        lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
        st.session_state.keywords_text = "\n".join(lines)
    else:
        st.session_state.keywords_text = "청소용품\n욕실세정제\n주방세정제\n세탁세제"


# ─────────────────────────────────────────────────────────────────────────────
# 사이드바 (설정)
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 크롤링 설정")
    st.divider()

    max_pages = st.number_input(
        "키워드당 최대 페이지 수",
        min_value=1, max_value=100, value=10, step=1,
    )

    headless = st.toggle("헤드리스 모드 (브라우저 숨김)", value=True)
    resume = st.toggle("Resume 모드 (기존 수집 건너뜀)", value=True)

    st.divider()
    st.subheader("내보내기 형식")
    export_csv   = st.checkbox("CSV", value=True)
    export_excel = st.checkbox("Excel", value=True)
    export_sqlite = st.checkbox("SQLite", value=True)

    st.divider()
    st.subheader("고급 설정")
    limit_products = st.number_input(
        "키워드당 최대 상품 수 (0=무제한)",
        min_value=0, max_value=10000, value=0, step=50,
    )

    st.divider()
    with st.expander("🔄 특수 실행 모드"):
        special_mode = st.radio(
            "모드 선택",
            ["전체 파이프라인", "검색만 (--only-search)", "상품 상세만 (--only-product)", "실패 재시도 (--retry-failed)"],
            index=0,
        )

    st.divider()
    st.caption("💡 처음 실행 시 `playwright install chromium` 필요")


# ─────────────────────────────────────────────────────────────────────────────
# 메인 영역 - 탭 구성
# ─────────────────────────────────────────────────────────────────────────────
st.title("🕷️ 쿠팡 판매자 크롤러")
st.caption("검색결과 기반으로 상품을 수집하고 판매자 DB를 구축합니다.")

tab_crawl, tab_results, tab_download = st.tabs(["🚀 크롤링", "📊 결과 보기", "💾 파일 다운로드"])


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1: 크롤링
# ─────────────────────────────────────────────────────────────────────────────
with tab_crawl:
    col_left, col_right = st.columns([1, 1], gap="medium")

    with col_left:
        st.subheader("📝 키워드 입력")
        keywords_text = st.text_area(
            "한 줄에 하나씩 입력하세요",
            value=st.session_state.keywords_text,
            height=300,
            placeholder="청소용품\n욕실세정제\n주방세정제",
            key="keywords_input",
        )
        st.caption(f"총 {len([k for k in keywords_text.splitlines() if k.strip()])}개 키워드")

    with col_right:
        st.subheader("📋 현재 설정")
        settings_md = f"""
| 설정 | 값 |
|------|-----|
| 최대 페이지 | {max_pages} |
| 헤드리스 | {'✅' if headless else '❌'} |
| Resume | {'✅' if resume else '❌'} |
| 내보내기 | {'CSV ' if export_csv else ''}{'Excel ' if export_excel else ''}{'SQLite' if export_sqlite else ''} |
| 키워드당 제한 | {'무제한' if limit_products == 0 else f'{limit_products}개'} |
| 실행 모드 | {special_mode.split('(')[0].strip()} |
        """
        st.markdown(settings_md)

    st.divider()

    # ── 실행 버튼 ──────────────────────────────────────────────────────────
    col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 3])

    with col_btn1:
        start_btn = st.button(
            "▶ 크롤링 시작",
            type="primary",
            disabled=st.session_state.is_running,
            use_container_width=True,
        )

    with col_btn2:
        stop_btn = st.button(
            "⏹ 중지",
            disabled=not st.session_state.is_running,
            use_container_width=True,
        )

    with col_btn3:
        clear_btn = st.button("🗑 로그 초기화", use_container_width=True)

    # 로그 상태 표시
    if st.session_state.is_running:
        st.info("⏳ 크롤링 진행 중... 완료될 때까지 이 페이지를 유지하세요.")
    elif st.session_state.finished:
        st.success("✅ 크롤링이 완료되었습니다. '결과 보기' 탭을 확인하세요.")

    # ── 버튼 로직 ─────────────────────────────────────────────────────────
    if clear_btn:
        st.session_state.log_lines = []
        st.session_state.finished = False
        st.rerun()

    if stop_btn and st.session_state.proc:
        try:
            st.session_state.proc.terminate()
        except Exception:
            pass
        st.session_state.is_running = False
        st.session_state.proc = None
        st.session_state.log_lines.append("⏹ 사용자에 의해 중지됨.")
        st.rerun()

    if start_btn and not st.session_state.is_running:
        keywords_list = [k.strip() for k in keywords_text.splitlines() if k.strip()]
        if not keywords_list:
            st.error("키워드를 하나 이상 입력하세요.")
        else:
            # 임시 키워드 파일 저장
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp_kw_file = BASE_DIR / "data" / "_tmp_keywords.txt"
            tmp_kw_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_kw_file.write_text("\n".join(keywords_list), encoding="utf-8")

            # CLI 인수 구성
            cmd = [
                sys.executable, "-m", "src.main",
                "--keywords", str(tmp_kw_file),
                "--max-pages", str(max_pages),
                "--headless", "true" if headless else "false",
            ]

            if resume:
                cmd.append("--resume")
            if limit_products > 0:
                cmd.extend(["--limit-products", str(limit_products)])

            # 내보내기 포맷
            export_formats = []
            if export_csv:    export_formats.append("csv")
            if export_excel:  export_formats.append("excel")
            if export_sqlite: export_formats.append("sqlite")
            if export_formats:
                cmd.extend(["--export"] + export_formats)

            # 특수 모드
            if "--only-search" in special_mode:
                cmd.append("--only-search")
            elif "--only-product" in special_mode:
                cmd.append("--only-product")
            elif "--retry-failed" in special_mode:
                cmd = [sys.executable, "-m", "src.main", "--retry-failed"]

            # 서브프로세스 시작
            st.session_state.log_lines = []
            st.session_state.log_lines.append(f"🚀 실행 명령: {' '.join(cmd)}\n")
            st.session_state.finished = False

            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )
            st.session_state.proc = proc
            st.session_state.is_running = True

            # 백그라운드 스레드로 출력 읽기
            q = st.session_state.log_queue
            def _reader(p: subprocess.Popen, q: queue.Queue):
                for line in iter(p.stdout.readline, ""):
                    q.put(line.rstrip())
                p.stdout.close()
                p.wait()
                q.put("__DONE__")

            t = threading.Thread(target=_reader, args=(proc, q), daemon=True)
            t.start()
            st.rerun()

    # ── 로그 수신 (실행 중일 때) ──────────────────────────────────────────
    if st.session_state.is_running:
        q = st.session_state.log_queue
        updated = False
        while True:
            try:
                line = q.get_nowait()
                if line == "__DONE__":
                    st.session_state.is_running = False
                    st.session_state.proc = None
                    st.session_state.finished = True
                    updated = True
                    break
                st.session_state.log_lines.append(line)
                updated = True
            except queue.Empty:
                break

        if updated:
            time.sleep(0.3)
            st.rerun()
        else:
            time.sleep(1)
            st.rerun()

    # ── 로그 출력 ──────────────────────────────────────────────────────────
    st.subheader("📄 실행 로그")
    log_text = "\n".join(st.session_state.log_lines[-300:])  # 최근 300줄
    st.code(log_text or "로그가 여기에 표시됩니다.", language=None)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2: 결과 보기
# ─────────────────────────────────────────────────────────────────────────────
with tab_results:
    st.subheader("📊 수집 결과")

    refresh_btn = st.button("🔄 결과 새로고침")

    def load_csv(name: str) -> pd.DataFrame | None:
        path = EXPORTS_DIR / f"{name}.csv"
        if path.exists():
            try:
                return pd.read_csv(path, encoding="utf-8-sig")
            except Exception:
                return None
        return None

    # 통계 요약 카드
    df_master = load_csv("sellers_master")
    df_obs    = load_csv("seller_observations")
    df_prod   = load_csv("products")

    if df_master is not None or df_prod is not None:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("수집 상품", f"{len(df_prod):,}개" if df_prod is not None else "-")
        c2.metric("판매자 관측", f"{len(df_obs):,}개" if df_obs is not None else "-")
        c3.metric("통합 판매자", f"{len(df_master):,}개" if df_master is not None else "-")
        if df_master is not None and "email" in df_master.columns:
            with_email = df_master["email"].notna().sum()
            c4.metric("이메일 보유", f"{with_email:,}개")
        st.divider()

    # 탭별 데이터 테이블
    r1, r2, r3 = st.tabs(["🏢 통합 판매자 DB", "👁 판매자 관측", "📦 수집 상품"])

    with r1:
        if df_master is not None:
            # 필터
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                email_only = st.checkbox("이메일 있는 판매자만 보기")
            with col_f2:
                search_name = st.text_input("판매자명 검색", placeholder="회사명 입력...")

            filtered = df_master.copy()
            if email_only:
                filtered = filtered[filtered["email"].notna() & (filtered["email"] != "")]
            if search_name:
                mask = filtered["seller_name"].fillna("").str.contains(search_name, case=False, na=False)
                filtered = filtered[mask]

            # 표시 컬럼 순서 정리
            display_cols = [c for c in [
                "seller_name", "representative_name", "business_registration_no",
                "email", "phone", "business_address", "mail_order_license_no",
                "product_count", "keyword_count", "first_seen_at",
            ] if c in filtered.columns]

            st.dataframe(
                filtered[display_cols],
                use_container_width=True,
                height=500,
                column_config={
                    "seller_name": st.column_config.TextColumn("상호명", width="medium"),
                    "representative_name": st.column_config.TextColumn("대표자", width="small"),
                    "business_registration_no": st.column_config.TextColumn("사업자번호", width="small"),
                    "email": st.column_config.TextColumn("이메일", width="medium"),
                    "phone": st.column_config.TextColumn("연락처", width="small"),
                    "business_address": st.column_config.TextColumn("주소", width="large"),
                    "product_count": st.column_config.NumberColumn("상품수", width="small"),
                    "keyword_count": st.column_config.NumberColumn("키워드수", width="small"),
                    "first_seen_at": st.column_config.TextColumn("최초수집", width="small"),
                },
            )
            st.caption(f"총 {len(filtered):,}개 (전체 {len(df_master):,}개)")
        else:
            st.info("아직 수집된 데이터가 없습니다. 크롤링을 먼저 실행하세요.")

    with r2:
        if df_obs is not None:
            display_cols = [c for c in [
                "seller_name", "representative_name", "business_registration_no",
                "email", "phone", "business_address",
                "source_keyword", "source_product_name", "collected_at",
            ] if c in df_obs.columns]
            st.dataframe(df_obs[display_cols], use_container_width=True, height=500)
            st.caption(f"총 {len(df_obs):,}개 관측")
        else:
            st.info("판매자 관측 데이터가 없습니다.")

    with r3:
        if df_prod is not None:
            display_cols = [c for c in [
                "keyword", "search_page", "rank_on_page",
                "product_name", "product_id", "crawl_time",
            ] if c in df_prod.columns]
            # 키워드 필터
            if "keyword" in df_prod.columns:
                kw_list = ["전체"] + sorted(df_prod["keyword"].dropna().unique().tolist())
                sel_kw = st.selectbox("키워드 필터", kw_list)
                if sel_kw != "전체":
                    df_prod_view = df_prod[df_prod["keyword"] == sel_kw]
                else:
                    df_prod_view = df_prod
            else:
                df_prod_view = df_prod
            st.dataframe(df_prod_view[display_cols], use_container_width=True, height=500)
            st.caption(f"총 {len(df_prod_view):,}개")
        else:
            st.info("수집된 상품 데이터가 없습니다.")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3: 파일 다운로드
# ─────────────────────────────────────────────────────────────────────────────
with tab_download:
    st.subheader("💾 파일 다운로드")

    def download_row(label: str, csv_name: str, xlsx_name: str | None = None) -> None:
        """한 행에 CSV/Excel 다운로드 버튼을 표시한다."""
        col_label, col_csv, col_xl = st.columns([3, 1, 1])
        with col_label:
            st.write(f"**{label}**")
        with col_csv:
            csv_path = EXPORTS_DIR / f"{csv_name}.csv"
            if csv_path.exists():
                st.download_button(
                    "📄 CSV",
                    data=csv_path.read_bytes(),
                    file_name=csv_path.name,
                    mime="text/csv",
                    key=f"dl_csv_{csv_name}",
                    use_container_width=True,
                )
            else:
                st.button("📄 CSV", disabled=True, key=f"dl_csv_{csv_name}_dis", use_container_width=True)
        with col_xl:
            xl_file = xlsx_name or csv_name
            xl_path = EXPORTS_DIR / f"{xl_file}.xlsx"
            if xl_path.exists():
                st.download_button(
                    "📊 Excel",
                    data=xl_path.read_bytes(),
                    file_name=xl_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_xl_{xl_file}",
                    use_container_width=True,
                )
            else:
                st.button("📊 Excel", disabled=True, key=f"dl_xl_{xl_file}_dis", use_container_width=True)

    st.markdown("파일이 생성된 경우에만 다운로드 버튼이 활성화됩니다.")
    st.divider()

    download_row("🏢 통합 판매자 DB (sellers_master)", "sellers_master")
    st.divider()
    download_row("👁 판매자 관측 데이터 (seller_observations)", "seller_observations")
    st.divider()
    download_row("📦 수집 상품 목록 (products)", "products")
    st.divider()
    download_row("❌ 실패 목록 (failed_jobs)", "failed_jobs")

    st.divider()
    st.subheader("📊 수집 통계 리포트")
    report_path = EXPORTS_DIR / "stats_report.txt"
    if report_path.exists():
        st.code(report_path.read_text(encoding="utf-8"), language=None)
        st.download_button(
            "📄 통계 리포트 다운로드",
            data=report_path.read_bytes(),
            file_name="stats_report.txt",
            mime="text/plain",
        )
    else:
        st.info("통계 리포트가 아직 없습니다.")

    st.divider()
    st.subheader("🗄️ SQLite DB 다운로드")
    db_path = BASE_DIR / "data" / "processed" / "coupang_sellers.db"
    if db_path.exists():
        st.download_button(
            "🗄️ coupang_sellers.db 다운로드",
            data=db_path.read_bytes(),
            file_name="coupang_sellers.db",
            mime="application/octet-stream",
        )
        size_mb = db_path.stat().st_size / 1024 / 1024
        st.caption(f"파일 크기: {size_mb:.2f} MB")
    else:
        st.info("SQLite DB가 아직 없습니다.")
