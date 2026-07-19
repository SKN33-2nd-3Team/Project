# -*- coding: utf-8 -*-
"""2층-A1: 상권유형 → 매출 증감률 (분석설계서 §3 2층-A1).

상권유형(area_type_name) *단독*으로 매출 증감률의 분포 차이를 확인한다.
업종은 공통 제외 규칙 적용과 상권×업종 셀의 증감률 계산 키로만 사용하며,
업종·인구·구·동을 설명 변수나 집계 기준으로 사용하지 않는다.

분석 행은 2023Q1~2025Q3이다. 단, 2023Q1의 직전 2개 분기 기준값을
계산하기 위해 증감률 자체는 전체 기간을 이용해 먼저 계산한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_rules import apply_exclusions
from src.growth_rate import add_growth_rate

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

DATA = ROOT / "data" / "raw" / "seoul_commercial_area_2021_2026Q1.csv"
TABLES = ROOT / "reports" / "tables"
FIGURES = ROOT / "reports" / "figures"

TRAIN_START = 20231
TRAIN_END = 20253
EXPECTED_AREA_TYPES = ["골목상권", "발달상권", "전통시장", "관광특구"]
KEY_COLUMNS = ["quarter", "area_code", "industry_code"]
USECOLS = [
    "quarter",
    "area_type_name",
    "area_code",
    "industry_code",
    "industry_name",
    "industry_group",
    "sales_record_present",
    "sales_monthly_sales",
]


def load_sales_cells() -> tuple[pd.DataFrame, dict[str, int]]:
    """로드 직후 공통 제외 규칙을 적용하고 매출 기록 셀만 반환한다."""
    parts: list[pd.DataFrame] = []
    raw_rows = excluded_rows = 0

    for chunk in pd.read_csv(
        DATA,
        encoding="utf-8-sig",
        usecols=USECOLS,
        chunksize=100_000,
        low_memory=False,
    ):
        raw_rows += len(chunk)
        # 제외 규칙에 필요한 industry_group·industry_name을 포함한 직후 적용한다.
        filtered = apply_exclusions(chunk)
        excluded_rows += len(chunk) - len(filtered)
        parts.append(
            filtered.loc[
                filtered["sales_record_present"].astype(str).str.lower().eq("true")
            ].copy()
        )

    sales = pd.concat(parts, ignore_index=True)
    if sales["area_type_name"].isna().any():
        raise ValueError(
            "상권유형 누락 행이 있습니다: "
            f"{int(sales['area_type_name'].isna().sum()):,}건"
        )

    actual_area_types = set(sales["area_type_name"].unique())
    expected_area_types = set(EXPECTED_AREA_TYPES)
    if actual_area_types != expected_area_types:
        raise ValueError(
            "상권유형은 정확히 4개여야 합니다. "
            f"기대={sorted(expected_area_types)}, 실제={sorted(actual_area_types)}"
        )

    if sales.duplicated(KEY_COLUMNS).any():
        duplicates = int(sales.duplicated(KEY_COLUMNS, keep=False).sum())
        raise ValueError(
            "분기×상권코드×업종코드 키가 중복됩니다: "
            f"{duplicates:,}행"
        )

    return sales, {
        "raw_rows": int(raw_rows),
        "excluded_rows": int(excluded_rows),
        "sales_record_cells": int(len(sales)),
    }


def group_summary(frame: pd.DataFrame, scope: str) -> list[dict[str, object]]:
    """상권유형별 표본 수와 중앙값·IQR을 산출한다."""
    rows: list[dict[str, object]] = []
    for area_type in EXPECTED_AREA_TYPES:
        values = frame.loc[
            frame["area_type_name"].eq(area_type), "매출_증감률"
        ].dropna()
        q1, q3 = values.quantile([0.25, 0.75])
        rows.append(
            {
                "분석구간": scope,
                "상권유형": area_type,
                "n": int(len(values)),
                "중앙값_매출증감률_pct": float(values.median()),
                "Q1_pct": float(q1),
                "Q3_pct": float(q3),
                "IQR_pct": float(q3 - q1),
            }
        )
    return rows


def epsilon_squared(h_statistic: float, n: int, k: int) -> float:
    """Kruskal-Wallis H의 epsilon-squared 효과크기."""
    return max(0.0, float((h_statistic - k + 1) / (n - k)))


def effect_label(epsilon2: float) -> str:
    if epsilon2 < 0.01:
        return "미미 (<0.01)"
    if epsilon2 < 0.04:
        return "작음 (0.01~<0.04)"
    if epsilon2 < 0.16:
        return "중간 (0.04~<0.16)"
    return "큼 (>=0.16)"


def kruskal_row(frame: pd.DataFrame, scope: str) -> dict[str, object]:
    """4개 상권유형을 모두 포함하는 Kruskal-Wallis 검정 결과 1행."""
    groups = [
        frame.loc[frame["area_type_name"].eq(area_type), "매출_증감률"].dropna().to_numpy()
        for area_type in EXPECTED_AREA_TYPES
    ]
    if any(len(group) == 0 for group in groups):
        counts = dict(zip(EXPECTED_AREA_TYPES, (len(group) for group in groups)))
        raise ValueError(f"{scope}: 상권유형별 유효 증감률이 모두 필요합니다: {counts}")
    h_statistic, p_value = stats.kruskal(*groups)
    n = sum(len(group) for group in groups)
    epsilon2 = epsilon_squared(float(h_statistic), n, len(groups))
    return {
        "분석구간": scope,
        "검정": "Kruskal-Wallis (4개 상권유형)",
        "H": float(h_statistic),
        "p_value": float(p_value),
        "epsilon_squared": epsilon2,
        "효과크기_해석": effect_label(epsilon2),
        "군수": len(groups),
        "n": int(n),
    }


def practical_verdict(overall_epsilon2: float, seasonal_epsilon2: list[float]) -> tuple[str, int]:
    """p값 대신 효과크기와 계절별 재현성으로 A1의 실질 연관을 판단한다."""
    reproducible_quarters = sum(value >= 0.01 for value in seasonal_epsilon2)
    if overall_epsilon2 >= 0.01 and reproducible_quarters >= 3:
        return "단독 실질 연관 있음 (계절별 재현)", reproducible_quarters
    if overall_epsilon2 >= 0.01 or reproducible_quarters >= 3:
        return "단독 연관은 약함/불안정 (3층에서 재검증)", reproducible_quarters
    return "단독 실질 연관 미확인 (3층에서 재검증)", reproducible_quarters


def save_figures(analysis: pd.DataFrame, order: list[str]) -> None:
    """상권유형별 분포와 같은 분기별 중앙값 차트를 저장한다."""
    FIGURES.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.boxplot(
        [
            analysis.loc[analysis["area_type_name"].eq(area_type), "매출_증감률"]
            for area_type in order
        ],
        tick_labels=order,
        showfliers=False,
    )
    ax.axhline(0, color="gray", lw=0.8, ls="--")
    ax.set_title("상권유형별 매출 증감률 분포 (2023Q1~2025Q3, 극단값 미표시)")
    ax.set_ylabel("매출 증감률(%)")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(FIGURES / "layer2_a1_area_sales_distribution.png", dpi=150)
    plt.close(fig)

    median_by_quarter = (
        analysis.groupby(["area_type_name", "분기"])["매출_증감률"]
        .median()
        .unstack()
        .reindex(order)
    )
    fig, ax = plt.subplots(figsize=(10, 5.5))
    median_by_quarter.rename(columns=lambda quarter: f"{quarter}분기").plot.bar(
        ax=ax, width=0.8
    )
    ax.axhline(0, color="gray", lw=0.8, ls="--", label="_nolegend_")
    ax.set_title("상권유형 × 같은 분기별 매출 증감률 중앙값 (2023Q1~2025Q3)")
    ax.set_ylabel("매출 증감률 중앙값(%)")
    ax.set_xlabel("")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(title="분기")
    fig.tight_layout()
    fig.savefig(FIGURES / "layer2_a1_area_sales_by_quarter.png", dpi=150)
    plt.close(fig)


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    sales, metadata = load_sales_cells()
    print(
        "매출 기록 셀: "
        f"{metadata['sales_record_cells']:,}건 "
        f"(제외 규칙 적용: {metadata['excluded_rows']:,}건 제외)"
    )

    # 전 기간으로 lag를 만든 뒤, 추론·특성 선택에 쓸 구간만 제한한다.
    sales = add_growth_rate(
        sales, "sales_monthly_sales", ["area_code", "industry_code"]
    ).rename(columns={"sales_monthly_sales_증감률": "매출_증감률"})
    sales["분기"] = sales["quarter"] % 10
    analysis = sales.loc[
        sales["quarter"].between(TRAIN_START, TRAIN_END) & sales["매출_증감률"].notna()
    ].copy()
    if analysis.empty:
        raise ValueError("2023Q1~2025Q3 분석 구간에 유효한 매출 증감률이 없습니다.")

    summary_rows = group_summary(analysis, "전체 (2023Q1~2025Q3)")
    test_rows = [kruskal_row(analysis, "전체 (2023Q1~2025Q3)")]
    for quarter in range(1, 5):
        seasonal = analysis.loc[analysis["분기"].eq(quarter)]
        scope = f"같은 {quarter}분기"
        summary_rows.extend(group_summary(seasonal, scope))
        test_rows.append(kruskal_row(seasonal, scope))

    tests = pd.DataFrame(test_rows)
    overall_epsilon2 = float(tests.iloc[0]["epsilon_squared"])
    seasonal_epsilon2 = tests.iloc[1:]["epsilon_squared"].astype(float).tolist()
    verdict, reproducible_quarters = practical_verdict(overall_epsilon2, seasonal_epsilon2)
    tests["계절별_작은효과_재현분기수"] = reproducible_quarters
    tests["실질연관_판정"] = verdict

    summaries = pd.DataFrame(summary_rows)
    summaries.to_csv(
        TABLES / "layer2_a1_area_sales_summary.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )
    tests.to_csv(
        TABLES / "layer2_a1_area_sales_test.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )

    order = (
        analysis.groupby("area_type_name")["매출_증감률"]
        .median()
        .sort_values()
        .index.tolist()
    )
    save_figures(analysis, order)

    print(f"분석 행(2023Q1~2025Q3, 유효 증감률): {len(analysis):,}건")
    print("\n=== 상권유형별 전체 구간 요약 ===")
    print(summaries.loc[summaries["분석구간"].eq("전체 (2023Q1~2025Q3)")].to_string(index=False))
    print("\n=== Kruskal-Wallis 검정 ===")
    print(tests.to_string(index=False, float_format=lambda value: f"{value:.6g}"))
    print("\n=== 2층-A1 3층 전달 판정 ===")
    print(
        "상권유형 → 매출 증감률: "
        f"전체 epsilon^2={overall_epsilon2:.4f}, "
        f"같은 분기 작은 효과 재현={reproducible_quarters}/4 → {verdict}"
    )
    print("판정은 p값 단독이 아니라 epsilon-squared와 같은 분기별 재현성에 근거합니다.")


if __name__ == "__main__":
    main()
