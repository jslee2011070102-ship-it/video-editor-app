"""데이터 내보내기 모듈.

CSV, Excel, 통계 리포트를 생성한다.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import pandas as pd
from loguru import logger

from .config_loader import AppConfig
from .deduplicator import SellerMaster
from .normalizer import normalize_email
from .parser import ProductItem, SellerObservation
from .utils import ensure_dir, now_iso


class DataExporter:
    """수집 데이터를 CSV / Excel 로 내보낸다."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.exports_dir = ensure_dir(config.exports_dir)

    def _timestamp_suffix(self) -> str:
        return now_iso().replace(":", "-").replace("T", "_")

    # ──────────────────────────────────────────────────────────────────────────
    # 상품 내보내기
    # ──────────────────────────────────────────────────────────────────────────

    def export_products(self, products: List[ProductItem]) -> Optional[Path]:
        """상품 목록을 CSV/Excel 로 내보낸다."""
        if not products:
            logger.warning("[내보내기] 상품 데이터 없음")
            return None

        df = pd.DataFrame([asdict(p) for p in products])
        return self._save(df, "products")

    # ──────────────────────────────────────────────────────────────────────────
    # 판매자 관측 내보내기
    # ──────────────────────────────────────────────────────────────────────────

    def export_observations(
        self, observations: List[SellerObservation]
    ) -> Optional[Path]:
        """판매자 관측 데이터를 CSV/Excel 로 내보낸다."""
        if not observations:
            logger.warning("[내보내기] 판매자 관측 데이터 없음")
            return None

        rows = []
        for obs in observations:
            row = asdict(obs)
            # 이메일 유효성 컬럼 추가
            _, is_valid = normalize_email(obs.email)
            row["email_is_valid"] = is_valid
            # raw_text 는 너무 길 수 있으므로 200자로 자름
            if row.get("seller_raw_text"):
                row["seller_raw_text"] = row["seller_raw_text"][:200]
            rows.append(row)

        df = pd.DataFrame(rows)
        return self._save(df, "seller_observations")

    # ──────────────────────────────────────────────────────────────────────────
    # 마스터 내보내기
    # ──────────────────────────────────────────────────────────────────────────

    def export_sellers_master(self, masters: List[SellerMaster]) -> Optional[Path]:
        """통합 판매자 마스터를 CSV/Excel 로 내보낸다."""
        if not masters:
            logger.warning("[내보내기] 마스터 데이터 없음")
            return None

        rows = []
        for master in masters:
            row = asdict(master)
            _, is_valid = normalize_email(master.email)
            row["email_is_valid"] = is_valid
            rows.append(row)

        df = pd.DataFrame(rows)
        # 이메일 있는 판매자 우선 정렬
        df["_has_email"] = df["email"].notna() & (df["email"] != "")
        df = df.sort_values(["_has_email", "product_count"], ascending=[False, False])
        df = df.drop(columns=["_has_email"])

        return self._save(df, "sellers_master")

    # ──────────────────────────────────────────────────────────────────────────
    # 실패 목록 내보내기
    # ──────────────────────────────────────────────────────────────────────────

    def export_failed_jobs(self, failed_jobs: List[dict]) -> Optional[Path]:
        """실패 목록을 CSV 로 내보낸다."""
        if not failed_jobs:
            return None

        df = pd.DataFrame(failed_jobs)
        return self._save(df, "failed_jobs", excel=False)

    # ──────────────────────────────────────────────────────────────────────────
    # 통계 리포트
    # ──────────────────────────────────────────────────────────────────────────

    def export_stats_report(
        self,
        products: List[ProductItem],
        observations: List[SellerObservation],
        masters: List[SellerMaster],
        failed_jobs: List[dict],
    ) -> None:
        """수집 통계를 로그로 출력하고 텍스트 파일로 저장한다."""
        lines = [
            "=" * 60,
            "쿠팡 판매자 크롤러 수집 결과 요약",
            f"생성 시각: {now_iso()}",
            "=" * 60,
            f"수집된 상품 수: {len(products)}개",
            f"판매자 관측 수: {len(observations)}개",
            f"통합 판매자 수: {len(masters)}개",
            f"실패 작업 수: {len(failed_jobs)}개",
        ]

        if masters:
            with_email = sum(1 for m in masters if m.email)
            lines.append(f"이메일 보유 판매자: {with_email}개 ({with_email/len(masters)*100:.1f}%)")

        if products:
            by_keyword: dict = {}
            for p in products:
                by_keyword[p.keyword] = by_keyword.get(p.keyword, 0) + 1
            lines.append("\n키워드별 수집량:")
            for kw, count in sorted(by_keyword.items(), key=lambda x: -x[1]):
                lines.append(f"  {kw}: {count}개")

        lines.append("=" * 60)

        report = "\n".join(lines)
        logger.info("\n" + report)

        report_path = self.exports_dir / "stats_report.txt"
        report_path.write_text(report, encoding="utf-8")
        logger.info(f"[내보내기] 통계 리포트 저장: {report_path}")

    # ──────────────────────────────────────────────────────────────────────────
    # 내부 유틸
    # ──────────────────────────────────────────────────────────────────────────

    def _save(
        self, df: pd.DataFrame, name: str, excel: bool = True
    ) -> Optional[Path]:
        """DataFrame 을 CSV (및 선택적으로 Excel) 로 저장한다."""
        saved_path: Optional[Path] = None

        if self.config.export_csv:
            csv_path = self.exports_dir / f"{name}.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            logger.info(f"[내보내기] CSV 저장: {csv_path} ({len(df)}행)")
            saved_path = csv_path

        if excel and self.config.export_excel:
            xlsx_path = self.exports_dir / f"{name}.xlsx"
            df.to_excel(xlsx_path, index=False, engine="openpyxl")
            logger.info(f"[내보내기] Excel 저장: {xlsx_path} ({len(df)}행)")
            if saved_path is None:
                saved_path = xlsx_path

        return saved_path
