# -*- coding: utf-8 -*-
"""2층-B 확장: 인구 → 프로젝트 정의 폐업률.

유동·상주·직장인구 증감률과 같은 분기 상권×분기 가중 폐업률의
Pearson 상관을 각각 확인한다. 폐업률은 원본 폐업률 컬럼이나 하위 비율
평균이 아니라 Σ폐업점포수 ÷ Σ점포수 × 100으로 계산한다.

인구값을 업종 행마다 반복해 표본 수를 부풀리지 않도록 폐업점포수와
점포수를 상권×분기 단위로 먼저 합산한 뒤 인구 테이블과 one-to-one 병합한다.
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
from src.growth_rate import add_growth_rate

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

DATA = ROOT / "data" / "raw" / "seoul_commercial_area_2021_2026Q1.csv"
TABLES = ROOT / "reports" / "tables"
FIGURES = ROOT / "reports" / "figures"

POPULATION_COLUMNS = {
    "유동인구": "floating_총_유동인구_수",
    "상주인구": "resident_총_상주인구_수",
    "직장인구": "worker_총_직장_인구_수",
}
AREA_QUARTER_KEY = ["quarter", "area_code"]
USECOLS = [
    *AREA_QUARTER_KEY,
    "industry_name",
    "industry_group",
    CLOSE,
    DENOM_STORE,
    *POPULATION_COLUMNS.values(),
]
TRAIN_START, TRAIN_END = 20231, 20253
SENSITIVITY_START = 20233


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """상권×분기 폐업 건수와 중복 없는 인구 테이블을 청크로 만든다."""
    population_parts: list[pd.DataFrame] = []
    closure_count_parts: list[pd.DataFrame] = []
    raw_rows = excluded_rows = 0
    population_cols = list(POPULATION_COLUMNS.values())

    for chunk in pd.read_csv(
        DATA,
        encoding="utf-8-sig",
        usecols=USECOLS,
        chunksize=100_000,
        low_memory=False,
    ):
        raw_rows += len(chunk)
        # 인구는 상권×분기 값이므로 업종 제외 전 원본에서 보존한다.
        population_parts.append(
            chunk[AREA_QUARTER_KEY + population_cols].drop_duplicates()
        )

        filtered = apply_exclusions(chunk)
        excluded_rows += len(chunk) - len(filtered)
        if filtered[[CLOSE, DENOM_STORE]].isna().any().any():
            missing = filtered[[CLOSE, DENOM_STORE]].isna().sum().to_dict()
            raise ValueError(f"폐업률 원건수 컬럼에 결측이 있습니다: {missing}")
        if (filtered[[CLOSE, DENOM_STORE]] < 0).any().any():
            raise ValueError("폐업점포수 또는 점포수에 음수가 있습니다.")
        closure_count_parts.append(
            filtered.groupby(AREA_QUARTER_KEY, as_index=False)[
                [CLOSE, DENOM_STORE]
            ].sum()
        )

    population_raw = pd.concat(population_parts, ignore_index=True).drop_duplicates()
    conflicts = (
        population_raw.groupby(AREA_QUARTER_KEY)[population_cols]
        .nunique(dropna=False)
        .gt(1)
        .sum()
    )
    if conflicts.any():
        raise ValueError(f"상권×분기 내 인구 값 충돌: {conflicts.to_dict()}")
    population = population_raw.drop_duplicates(AREA_QUARTER_KEY).copy()

    closure_counts = (
        pd.concat(closure_count_parts, ignore_index=True)
        .groupby(AREA_QUARTER_KEY, as_index=False)[[CLOSE, DENOM_STORE]]
        .sum()
    )
    rates = weighted_closure_rate(
        closure_counts, AREA_QUARTER_KEY, DENOM_STORE
    ).reset_index()
    closure = closure_counts.merge(rates, on=AREA_QUARTER_KEY, validate="one_to_one")
    valid = (closure[DENOM_STORE] > 0) & np.isfinite(closure["폐업률"])
    zero_denom_area_quarters = int((closure[DENOM_STORE] <= 0).sum())
    closure = closure.loc[valid].copy()

    overall = closure[CLOSE].sum() / closure[DENOM_STORE].sum() * 100
    recombined = weighted_closure_rate(
        closure, ["quarter"], DENOM_STORE
    )
    recombined_overall = (
        closure.groupby("quarter")[[CLOSE, DENOM_STORE]].sum()[CLOSE].sum()
        / closure.groupby("quarter")[[CLOSE, DENOM_STORE]].sum()[DENOM_STORE].sum()
        * 100
    )
    if not np.isclose(overall, recombined_overall, atol=1e-12):
        raise AssertionError("상권×분기 폐업 원건수 재결합 검산에 실패했습니다.")
    if len(recombined) != closure["quarter"].nunique():
        raise AssertionError("분기별 가중 폐업률 검산 결과의 분기 수가 일치하지 않습니다.")

    metadata: dict[str, object] = {
        "raw_rows": int(raw_rows),
        "excluded_rows": int(excluded_rows),
        "population_area_quarters": int(len(population)),
        "closure_area_quarters": int(len(closure_counts)),
        "zero_denominator_area_quarters": zero_denom_area_quarters,
        "valid_closure_area_quarters": int(len(closure)),
        "over_100pct_area_quarters": int((closure["폐업률"] > 100).sum()),
        "weighted_recombination_rate_pct": float(overall),
    }
    return closure, population, metadata


def fisher_ci(r: float, n: int) -> tuple[float, float]:
    """Pearson r의 Fisher-z 95% 신뢰구간."""
    if n <= 3 or not np.isfinite(r):
        return np.nan, np.nan
    z = np.arctanh(float(np.clip(r, -0.999999, 0.999999)))
    margin = 1.96 / np.sqrt(n - 3)
    return float(np.tanh(z - margin)), float(np.tanh(z + margin))


def effect_label(r: float) -> str:
    if not np.isfinite(r):
        return "계산 불가"
    if abs(r) < 0.1:
        return "매우 약함"
    if abs(r) < 0.3:
        return "약함"
    if abs(r) < 0.5:
        return "중간"
    return "강함"


def correlation_row(
    frame: pd.DataFrame, population_col: str, label: str, scope: str
) -> dict[str, object]:
    valid = frame[["폐업률", population_col]].replace([np.inf, -np.inf], np.nan).dropna()
    n = len(valid)
    if n < 3 or valid[population_col].nunique() < 2 or valid["폐업률"].nunique() < 2:
        r = p_value = np.nan
    else:
        r, p_value = stats.pearsonr(valid[population_col], valid["폐업률"])
    low, high = fisher_ci(float(r), n)
    return {
        "인구유형": label,
        "분석구간": scope,
        "n": int(n),
        "Pearson_r": float(r),
        "p_value": float(p_value),
        "r_95_CI_low": low,
        "r_95_CI_high": high,
        "방향": "계산 불가" if not np.isfinite(r) else ("양의" if r > 0 else "음의"),
        "효과크기_참고": effect_label(float(r)),
    }


def practical_verdict(overall_r: float, seasonal_r: list[float]) -> tuple[str, int]:
    """|r|>=0.1의 전체 효과와 동일 분기 재현성으로 판정한다."""
    reproducible_quarters = int(
        sum(np.isfinite(value) and abs(value) >= 0.1 for value in seasonal_r)
    )
    overall_practical = np.isfinite(overall_r) and abs(overall_r) >= 0.1
    if overall_practical and reproducible_quarters >= 3:
        return "단독 실질 연관 있음 (계절별 재현)", reproducible_quarters
    if overall_practical or reproducible_quarters >= 3:
        return "단독 연관은 약함/불안정 (후속 조합에서 재검증)", reproducible_quarters
    return "단독 실질 연관 미확인 (후속 조합에서 재검증)", reproducible_quarters


def save_scatterplots(train: pd.DataFrame) -> None:
    """분석값의 중앙 98% 구간을 표시한 인구 유형별 산점도를 저장한다."""
    FIGURES.mkdir(parents=True, exist_ok=True)
    for label in POPULATION_COLUMNS:
        population_col = f"{label}_증감률"
        plot_data = train[[population_col, "폐업률"]].dropna()
        x_low, x_high = plot_data[population_col].quantile([0.01, 0.99])
        y_low, y_high = plot_data["폐업률"].quantile([0.01, 0.99])
        central = plot_data.loc[
            plot_data[population_col].between(x_low, x_high)
            & plot_data["폐업률"].between(y_low, y_high)
        ]

        fig, ax = plt.subplots(figsize=(8, 5.5))
        ax.scatter(
            central[population_col],
            central["폐업률"],
            s=9,
            alpha=0.18,
            edgecolors="none",
        )
        ax.set_title(f"{label} 증감률과 같은 분기 폐업률 (시각화 중앙 98%)")
        ax.set_xlabel(f"{label} 증감률(%)")
        ax.set_ylabel("상권×분기 가중 폐업률(%)")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(
            FIGURES / f"layer2_b_{label}_closure_scatter.png", dpi=150
        )
        plt.close(fig)


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    closure, population, metadata = load_inputs()

    for label, source_col in POPULATION_COLUMNS.items():
        population = add_growth_rate(population, source_col, ["area_code"])
        population = population.rename(
            columns={f"{source_col}_증감률": f"{label}_증감률"}
        )

    merged = closure.merge(
        population[
            AREA_QUARTER_KEY
            + [f"{label}_증감률" for label in POPULATION_COLUMNS]
        ],
        on=AREA_QUARTER_KEY,
        how="left",
        validate="one_to_one",
    )
    merged["분기"] = merged["quarter"] % 10
    train = merged.loc[merged["quarter"].between(TRAIN_START, TRAIN_END)].copy()
    sensitivity = train.loc[train["quarter"] >= SENSITIVITY_START].copy()
    if train.empty:
        raise ValueError("2023Q1~2025Q3 분석 구간에 유효한 상권×분기 행이 없습니다.")

    rows: list[dict[str, object]] = []
    verdicts: dict[str, dict[str, object]] = {}
    for label in POPULATION_COLUMNS:
        population_col = f"{label}_증감률"
        total_row = correlation_row(
            train, population_col, label, "전체 (2023Q1~2025Q3)"
        )
        rows.append(total_row)
        seasonal_rows: list[dict[str, object]] = []
        for quarter in range(1, 5):
            row = correlation_row(
                train.loc[train["분기"].eq(quarter)],
                population_col,
                label,
                f"같은 {quarter}분기",
            )
            rows.append(row)
            seasonal_rows.append(row)
        rows.append(
            correlation_row(
                sensitivity,
                population_col,
                label,
                "민감도 (2023Q3~2025Q3)",
            )
        )

        overall_r = float(total_row["Pearson_r"])
        seasonal_r = [float(row["Pearson_r"]) for row in seasonal_rows]
        verdict, reproducible_quarters = practical_verdict(overall_r, seasonal_r)
        verdicts[label] = {
            "overall_r": overall_r,
            "seasonal_reproducible_quarters": reproducible_quarters,
            "verdict": verdict,
        }

    results = pd.DataFrame(rows)
    results.to_csv(
        TABLES / "layer2_b_population_closure_correlation.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )
    metadata["analysis_area_quarters"] = int(len(train))
    metadata["analysis_over_100pct_area_quarters"] = int((train["폐업률"] > 100).sum())
    metadata["complete_cases"] = {
        label: int(train[["폐업률", f"{label}_증감률"]].dropna().shape[0])
        for label in POPULATION_COLUMNS
    }
    metadata["verdicts"] = verdicts
    (TABLES / "layer2_b_population_closure_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_scatterplots(train)

    print(
        f"원본 {metadata['raw_rows']:,}행, 공통 제외 {metadata['excluded_rows']:,}행, "
        f"점포수 0 상권×분기 {metadata['zero_denominator_area_quarters']:,}건 제외"
    )
    print(f"분석 상권×분기(2023Q1~2025Q3): {len(train):,}건")
    print("\n=== 인구 증감률 ↔ 같은 분기 가중 폐업률 Pearson 상관 ===")
    print(results.to_string(index=False, float_format=lambda value: f"{value:.6g}"))
    print("\n=== 전달 판정 ===")
    for label, verdict_data in verdicts.items():
        print(
            f"{label} 증감률 → 폐업률: 전체 r={verdict_data['overall_r']:.4f}, "
            f"동일 분기 |r|>=0.1 재현="
            f"{verdict_data['seasonal_reproducible_quarters']}/4 → "
            f"{verdict_data['verdict']}"
        )


if __name__ == "__main__":
    main()
