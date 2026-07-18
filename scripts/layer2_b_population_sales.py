# -*- coding: utf-8 -*-
"""2층-B: 인구 → 매출 (분석설계서 §3 2층-B).

유동·상주·직장인구 증감률과 매출 증감률의 Pearson 상관을 각각 확인한다.
상권·업종은 효과를 분석하지 않고 셀 식별 및 증감률 계산 키로만 사용한다.

전제:
- PR #5 병합 후 제공되는 src.growth_rate.add_growth_rate 사용
- 분석 행: 2023Q1~2025Q3 (2021~22 검정 제외, 2025Q4 미사용)
- 매출 증감률: 상권×업종 셀 단위
- 인구 증감률: 상권×분기 단위에서 계산 후 매출 셀에 many-to-one 병합
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_rules import apply_exclusions
from src.growth_rate import add_growth_rate

DATA = ROOT / "data" / "raw" / "seoul_commercial_area_2021_2026Q1.csv"
TABLES = ROOT / "reports" / "tables"

POPULATION_COLUMNS = {
    "유동인구": "floating_총_유동인구_수",
    "상주인구": "resident_총_상주인구_수",
    "직장인구": "worker_총_직장_인구_수",
}
USECOLS = [
    "quarter",
    "area_code",
    "industry_code",
    "industry_name",
    "industry_group",
    "sales_record_present",
    "sales_monthly_sales",
    *POPULATION_COLUMNS.values(),
]
TRAIN_START, TRAIN_END = 20231, 20253
SENSITIVITY_START = 20233


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """필요 컬럼만 청크로 읽어 매출 셀·상권별 인구 테이블을 만든다."""
    population_parts: list[pd.DataFrame] = []
    sales_parts: list[pd.DataFrame] = []
    raw_rows = excluded_rows = 0

    for chunk in pd.read_csv(
        DATA,
        encoding="utf-8-sig",
        usecols=USECOLS,
        chunksize=100_000,
        low_memory=False,
    ):
        raw_rows += len(chunk)
        # 인구는 상권×분기 값이므로 제외 전 원본에서 보존한다.
        population_parts.append(chunk[["quarter", "area_code", *POPULATION_COLUMNS.values()]])

        filtered = apply_exclusions(chunk)
        excluded_rows += len(chunk) - len(filtered)
        sales_parts.append(
            filtered[
                filtered["sales_record_present"].astype(str).str.lower().eq("true")
            ][["quarter", "area_code", "industry_code", "sales_monthly_sales"]]
        )

    population_raw = pd.concat(population_parts, ignore_index=True)
    population_key = ["quarter", "area_code"]
    conflicts = (
        population_raw.groupby(population_key)[list(POPULATION_COLUMNS.values())]
        .nunique(dropna=False)
        .gt(1)
        .sum()
    )
    if conflicts.any():
        raise ValueError(f"상권×분기 내 인구 값 충돌: {conflicts.to_dict()}")
    population = population_raw.drop_duplicates(population_key).copy()

    sales = pd.concat(sales_parts, ignore_index=True)
    sales_key = ["quarter", "area_code", "industry_code"]
    if sales.duplicated(sales_key).any():
        raise ValueError("매출 기록 셀 키가 중복됩니다.")

    metadata = {
        "raw_rows": int(raw_rows),
        "excluded_rows": int(excluded_rows),
        "sales_record_cells": int(len(sales)),
        "population_area_quarters": int(len(population)),
    }
    return sales, population, metadata


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


def correlation_row(frame: pd.DataFrame, population_col: str, label: str) -> dict:
    valid = frame[["매출_증감률", population_col]].dropna()
    n = len(valid)
    if n < 3 or valid[population_col].nunique() < 2 or valid["매출_증감률"].nunique() < 2:
        r = p_value = np.nan
    else:
        r, p_value = stats.pearsonr(valid[population_col], valid["매출_증감률"])
    low, high = fisher_ci(float(r), n)
    return {
        "인구유형": label,
        "분석구간": "",
        "n": int(n),
        "Pearson_r": float(r),
        "p_value": float(p_value),
        "r_95_CI_low": low,
        "r_95_CI_high": high,
        "방향": "계산 불가" if not np.isfinite(r) else ("양의" if r > 0 else "음의"),
        "효과크기_참고": effect_label(float(r)),
    }


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)

    sales, population, metadata = load_inputs()
    sales = add_growth_rate(sales, "sales_monthly_sales", ["area_code", "industry_code"])
    sales = sales.rename(columns={"sales_monthly_sales_증감률": "매출_증감률"})

    for label, source_col in POPULATION_COLUMNS.items():
        population = add_growth_rate(population, source_col, ["area_code"])
        population = population.rename(columns={f"{source_col}_증감률": f"{label}_증감률"})

    merged = sales.merge(
        population[["quarter", "area_code", *[f"{label}_증감률" for label in POPULATION_COLUMNS]]],
        on=["quarter", "area_code"],
        how="left",
        validate="many_to_one",
    )
    merged["분기"] = merged["quarter"] % 10
    train = merged[merged["quarter"].between(TRAIN_START, TRAIN_END)].copy()
    sensitivity = train[train["quarter"] >= SENSITIVITY_START].copy()

    rows: list[dict] = []
    for label in POPULATION_COLUMNS:
        population_col = f"{label}_증감률"
        total = correlation_row(train, population_col, label)
        total["분석구간"] = "전체 (2023Q1~2025Q3)"
        rows.append(total)
        for quarter in range(1, 5):
            by_quarter = correlation_row(train[train["분기"] == quarter], population_col, label)
            by_quarter["분석구간"] = f"{quarter}분기"
            rows.append(by_quarter)
        robust = correlation_row(sensitivity, population_col, label)
        robust["분석구간"] = "민감도 (2023Q3~2025Q3)"
        rows.append(robust)

    results = pd.DataFrame(rows)
    results.to_csv(
        TABLES / "layer2_b_population_sales_correlation.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )
    metadata["complete_cases"] = {
        label: int(train[["매출_증감률", f"{label}_증감률"]].dropna().shape[0])
        for label in POPULATION_COLUMNS
    }
    (TABLES / "layer2_b_population_sales_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(results.to_string(index=False, float_format=lambda value: f"{value:.6g}"))


if __name__ == "__main__":
    main()
