# -*- coding: utf-8 -*-
"""2층-A1 확장: 상권유형 → 프로젝트 정의 폐업률.

상권유형별 상권×업종×분기 셀의 폐업률 분포를 비교한다.
폐업률은 원본 폐업률 컬럼이나 하위 비율 평균이 아니라 공용 함수로
Σ폐업점포수 ÷ Σ점포수 × 100을 계산한다.

분석 구간은 기존 2층-A1과 같은 2023Q1~2025Q3이며, 전체 기간과
동일 분기별 Kruskal-Wallis 검정 및 epsilon-squared 효과크기를 산출한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.closure_rate import CLOSE, DENOM_STORE, weighted_closure_rate
from src.data_rules import apply_exclusions

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

DATA = ROOT / "data" / "raw" / "seoul_commercial_area_2021_2026Q1.csv"
TABLES = ROOT / "reports" / "tables"
FIGURES = ROOT / "reports" / "figures"

EXPECTED_AREA_TYPES = ["골목상권", "발달상권", "전통시장", "관광특구"]
KEY_COLUMNS = ["quarter", "area_code", "industry_code"]
USECOLS = [
    *KEY_COLUMNS,
    "area_type_name",
    "industry_name",
    "industry_group",
    CLOSE,
    DENOM_STORE,
]
TRAIN_START, TRAIN_END = 20231, 20253


def load_closure_cells() -> tuple[pd.DataFrame, dict[str, int]]:
    """공통 제외 규칙을 적용하고 셀 단위 가중 폐업률을 만든다."""
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
        filtered = apply_exclusions(chunk)
        excluded_rows += len(chunk) - len(filtered)
        parts.append(filtered)

    frame = pd.concat(parts, ignore_index=True)
    if frame[[CLOSE, DENOM_STORE]].isna().any().any():
        missing = frame[[CLOSE, DENOM_STORE]].isna().sum().to_dict()
        raise ValueError(f"폐업률 원건수 컬럼에 결측이 있습니다: {missing}")
    if (frame[[CLOSE, DENOM_STORE]] < 0).any().any():
        raise ValueError("폐업점포수 또는 점포수에 음수가 있습니다.")
    if frame.duplicated(KEY_COLUMNS).any():
        duplicates = int(frame.duplicated(KEY_COLUMNS, keep=False).sum())
        raise ValueError(f"분기×상권×업종 키가 중복됩니다: {duplicates:,}행")
    if frame["area_type_name"].isna().any():
        raise ValueError(
            f"상권유형 누락 행이 있습니다: {int(frame['area_type_name'].isna().sum()):,}건"
        )

    actual_area_types = set(frame["area_type_name"].unique())
    if actual_area_types != set(EXPECTED_AREA_TYPES):
        raise ValueError(
            "상권유형은 정확히 4개여야 합니다. "
            f"기대={sorted(EXPECTED_AREA_TYPES)}, 실제={sorted(actual_area_types)}"
        )

    rates = weighted_closure_rate(frame, KEY_COLUMNS, DENOM_STORE).reset_index()
    counts = (
        frame.groupby(KEY_COLUMNS, as_index=False)[[CLOSE, DENOM_STORE]].sum()
    )
    area_map = frame[KEY_COLUMNS + ["area_type_name"]].drop_duplicates()
    cells = counts.merge(rates, on=KEY_COLUMNS, validate="one_to_one").merge(
        area_map, on=KEY_COLUMNS, validate="one_to_one"
    )
    valid = (cells[DENOM_STORE] > 0) & np.isfinite(cells["폐업률"])
    zero_denom_cells = int((cells[DENOM_STORE] <= 0).sum())
    cells["분기"] = cells["quarter"] % 10

    return cells, {
        "raw_rows": int(raw_rows),
        "excluded_rows": int(excluded_rows),
        "closure_cells": int(len(counts)),
        "zero_denominator_cells": zero_denom_cells,
        "valid_closure_cells": int(valid.sum()),
        "over_100pct_cells": int((valid & (cells["폐업률"] > 100)).sum()),
    }


def group_summary(
    frame: pd.DataFrame, aggregation_frame: pd.DataFrame, scope: str
) -> list[dict[str, object]]:
    """상권유형별 셀 분포와 원건수 가중 폐업률을 함께 산출한다."""
    rows: list[dict[str, object]] = []
    for area_type in EXPECTED_AREA_TYPES:
        group = frame.loc[frame["area_type_name"].eq(area_type)]
        aggregation_group = aggregation_frame.loc[
            aggregation_frame["area_type_name"].eq(area_type)
        ]
        values = group["폐업률"].dropna()
        if values.empty:
            raise ValueError(f"{scope}: {area_type}의 유효 폐업률이 없습니다.")
        q1, q3 = values.quantile([0.25, 0.75])
        rows.append(
            {
                "분석구간": scope,
                "상권유형": area_type,
                "n": int(len(values)),
                "중앙값_폐업률_pct": float(values.median()),
                "Q1_pct": float(q1),
                "Q3_pct": float(q3),
                "IQR_pct": float(q3 - q1),
                "가중집계_폐업률_pct": float(
                    aggregation_group[CLOSE].sum()
                    / aggregation_group[DENOM_STORE].sum()
                    * 100
                ),
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
    """4개 상권유형을 모두 포함하는 Kruskal-Wallis 결과 1행."""
    groups = [
        frame.loc[frame["area_type_name"].eq(area_type), "폐업률"]
        .dropna()
        .to_numpy()
        for area_type in EXPECTED_AREA_TYPES
    ]
    if any(len(group) == 0 for group in groups):
        counts = dict(zip(EXPECTED_AREA_TYPES, (len(group) for group in groups)))
        raise ValueError(f"{scope}: 상권유형별 유효 폐업률이 모두 필요합니다: {counts}")
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


def practical_verdict(
    overall_epsilon2: float, seasonal_epsilon2: list[float]
) -> tuple[str, int]:
    """효과크기와 동일 분기 재현성으로 단독 실질 연관을 판정한다."""
    reproducible_quarters = sum(value >= 0.01 for value in seasonal_epsilon2)
    if overall_epsilon2 >= 0.01 and reproducible_quarters >= 3:
        return "단독 실질 연관 있음 (계절별 재현)", reproducible_quarters
    if overall_epsilon2 >= 0.01 or reproducible_quarters >= 3:
        return "단독 연관은 약함/불안정 (후속 조합에서 재검증)", reproducible_quarters
    return "단독 실질 연관 미확인 (후속 조합에서 재검증)", reproducible_quarters


def save_figures(aggregation_frame: pd.DataFrame, order: list[str]) -> None:
    """상권유형별 전체·동일 분기 원건수 가중 폐업률을 저장한다."""
    FIGURES.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    weighted_overall = weighted_closure_rate(
        aggregation_frame, ["area_type_name"], DENOM_STORE
    ).reindex(order)
    weighted_overall.plot.bar(ax=ax, color="tab:blue")
    ax.set_title("상권유형별 원건수 가중 폐업률 (2023Q1~2025Q3)")
    ax.set_ylabel("가중 폐업률(%, Σ폐업점포수÷Σ점포수)")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=0)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(FIGURES / "layer2_a1_area_closure_weighted_overall.png", dpi=150)
    plt.close(fig)

    weighted_by_quarter = (
        weighted_closure_rate(
            aggregation_frame, ["area_type_name", "분기"], DENOM_STORE
        )
        .unstack()
        .reindex(order)
    )
    fig, ax = plt.subplots(figsize=(10, 5.5))
    weighted_by_quarter.rename(columns=lambda quarter: f"{quarter}분기").plot.bar(
        ax=ax, width=0.8
    )
    ax.set_title("상권유형 × 동일 분기별 원건수 가중 폐업률 (2023Q1~2025Q3)")
    ax.set_ylabel("가중 폐업률(%)")
    ax.set_xlabel("")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(title="분기")
    fig.tight_layout()
    fig.savefig(FIGURES / "layer2_a1_area_closure_by_quarter.png", dpi=150)
    plt.close(fig)


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    cells, metadata = load_closure_cells()
    analysis_all = cells.loc[cells["quarter"].between(TRAIN_START, TRAIN_END)].copy()
    valid = (analysis_all[DENOM_STORE] > 0) & np.isfinite(analysis_all["폐업률"])
    analysis = analysis_all.loc[valid].copy()
    if analysis.empty:
        raise ValueError("2023Q1~2025Q3 분석 구간에 유효한 폐업률이 없습니다.")

    summary_rows = group_summary(
        analysis, analysis_all, "전체 (2023Q1~2025Q3)"
    )
    test_rows = [kruskal_row(analysis, "전체 (2023Q1~2025Q3)")]
    for quarter in range(1, 5):
        seasonal = analysis.loc[analysis["분기"].eq(quarter)]
        seasonal_all = analysis_all.loc[analysis_all["분기"].eq(quarter)]
        scope = f"같은 {quarter}분기"
        summary_rows.extend(group_summary(seasonal, seasonal_all, scope))
        test_rows.append(kruskal_row(seasonal, scope))

    summaries = pd.DataFrame(summary_rows)
    tests = pd.DataFrame(test_rows)
    overall_epsilon2 = float(tests.iloc[0]["epsilon_squared"])
    seasonal_epsilon2 = tests.iloc[1:]["epsilon_squared"].astype(float).tolist()
    verdict, reproducible_quarters = practical_verdict(
        overall_epsilon2, seasonal_epsilon2
    )
    tests["계절별_작은효과_재현분기수"] = reproducible_quarters
    tests["실질연관_판정"] = verdict

    metadata["analysis_cells"] = int(len(analysis))
    metadata["analysis_zero_denominator_cells"] = int((~valid).sum())
    metadata["analysis_over_100pct_cells"] = int((analysis["폐업률"] > 100).sum())
    metadata["overall_epsilon_squared"] = overall_epsilon2
    metadata["seasonal_reproducible_quarters"] = reproducible_quarters
    metadata["verdict"] = verdict

    summaries.to_csv(
        TABLES / "layer2_a1_area_closure_summary.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )
    tests.to_csv(
        TABLES / "layer2_a1_area_closure_test.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )
    (TABLES / "layer2_a1_area_closure_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    order = (
        weighted_closure_rate(analysis_all, ["area_type_name"], DENOM_STORE)
        .sort_values()
        .index.tolist()
    )
    save_figures(analysis_all, order)

    print(
        f"원본 {metadata['raw_rows']:,}행, 공통 제외 {metadata['excluded_rows']:,}행, "
        f"점포수 0 셀 {metadata['zero_denominator_cells']:,}건 제외"
    )
    print(f"분석 셀(2023Q1~2025Q3): {len(analysis):,}건")
    print(
        "100% 초과 셀: "
        f"{metadata['analysis_over_100pct_cells']:,}건 "
        "(점포수는 시점 스냅샷, 폐업수는 분기 누적이라는 원자료 한계)"
    )
    print("\n=== 상권유형별 전체 구간 요약 ===")
    print(
        summaries.loc[summaries["분석구간"].eq("전체 (2023Q1~2025Q3)")]
        .to_string(index=False)
    )
    print("\n=== Kruskal-Wallis 검정 ===")
    print(tests.to_string(index=False, float_format=lambda value: f"{value:.6g}"))
    print("\n=== 전달 판정 ===")
    print(
        "상권유형 → 폐업률: "
        f"전체 epsilon^2={overall_epsilon2:.4f}, "
        f"동일 분기 작은 효과 재현={reproducible_quarters}/4 → {verdict}"
    )


if __name__ == "__main__":
    main()
