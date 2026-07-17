# -*- coding: utf-8 -*-
"""1층 현황 제시 (분석설계서 §3-1층)

산출물 (reports/figures/, reports/tables/):
  1. 연도별 카테고리별(상권유형·업종그룹) 폐업률 추이 (최우선, 코로나 방침 근거)
  2. 상권유형별 분기 폐업률 시계열
  3. 업종그룹별 분기 폐업률 시계열
  4. 구·동 단위 현황표 (CSV) + 구별 폐업률 차트
콘솔: 현황표 수치 (분기 기준)
"""
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.closure_rate import (CLOSE, DENOM_SIMILAR, DENOM_STORE, add_year,
                              weighted_closure_rate)
from src.data_rules import apply_exclusions

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

DATA = ROOT / "data" / "raw" / "seoul_commercial_area_2021_2026Q1.csv"
FIG = ROOT / "reports" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

USECOLS = ["quarter", "area_type_name", "industry_group", "industry_name",
           "geometry_district_name", "geometry_neighborhood_name",
           CLOSE, DENOM_STORE, DENOM_SIMILAR]
df = apply_exclusions(add_year(pd.read_csv(DATA, usecols=USECOLS)))
qlab = df["quarter"].astype(str).str[:4] + "Q" + df["quarter"].astype(str).str[4]
df["분기라벨"] = qlab


def shade_covid(ax, labels):
    """2021~22 구간(현황 제시용, 학습 제외)을 음영 처리."""
    covid = [i for i, q in enumerate(labels) if q.startswith(("2021", "2022"))]
    if covid:
        ax.axvspan(min(covid) - 0.5, max(covid) + 0.5, alpha=0.12, color="gray")
        ax.text(min(covid), ax.get_ylim()[1], " 코로나 구간(학습 제외, 현황만)",
                fontsize=8, va="top", color="gray")


# --- 1. 연도별 카테고리별 폐업률 -------------------------------------------
# 팀 결정(설계서 §5 안건 2): 분모 = stores_store_count, 기존 폐업률 컬럼 미사용
# 전체 단일 평균이 아니라 카테고리(상권유형·업종그룹)별로 연도 추이를 제시
yearly_type = weighted_closure_rate(df, ["연도", "area_type_name"], DENOM_STORE).unstack()
yearly_group = weighted_closure_rate(df, ["연도", "industry_group"], DENOM_STORE).unstack()
print("=== 연도별 상권유형별 폐업률(%) — 분기 기준 가중 집계 ===")
print(yearly_type.round(3).to_string())
print("\n=== 연도별 업종그룹별 폐업률(%) — 분기 기준 가중 집계 ===")
print(yearly_group.round(3).to_string())

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
yearly_type.plot(ax=ax1, marker="o")
ax1.set_title("상권유형별")
ax1.set_xlabel("연도")
ax1.set_ylabel("폐업률(%)")
ax1.set_xticks(yearly_type.index)
ax1.grid(alpha=0.3)
ax1.legend(title="상권유형", fontsize=9)
yearly_group.plot(ax=ax2, marker="o")
ax2.set_title("업종그룹별")
ax2.set_xlabel("연도")
ax2.set_xticks(yearly_group.index)
ax2.grid(alpha=0.3)
ax2.legend(title="업종그룹", fontsize=8)
fig.suptitle("연도별 카테고리별 폐업률 추이 (분기 기준, 가중 집계)")
fig.tight_layout()
fig.savefig(FIG / "01_연도별_카테고리별_폐업률.png", dpi=150)

# --- 2. 상권유형별 분기 폐업률 시계열 ------------------------------------
by_type = weighted_closure_rate(df, ["분기라벨", "area_type_name"], DENOM_STORE).unstack()
print("\n=== 상권유형별 분기 폐업률(%) — 분모=점포수 ===")
print(by_type.round(2).to_string())

fig, ax = plt.subplots(figsize=(11, 5))
by_type.plot(ax=ax, marker=".")
ax.set_title("상권유형별 분기 폐업률 (가중 집계, 분모=점포수)")
ax.set_xlabel("분기")
ax.set_ylabel("폐업률(%)")
ax.set_xticks(range(len(by_type.index)))
ax.set_xticklabels(by_type.index, rotation=45)
ax.grid(alpha=0.3)
shade_covid(ax, list(by_type.index))
ax.legend(title="상권유형")
fig.tight_layout()
fig.savefig(FIG / "02_상권유형별_분기_폐업률.png", dpi=150)

# --- 3. 업종그룹별 분기 폐업률 시계열 ------------------------------------
by_group = weighted_closure_rate(df, ["분기라벨", "industry_group"], DENOM_STORE).unstack()
print("\n=== 업종그룹별 분기 폐업률(%) 최근 4분기 — 분모=점포수 ===")
print(by_group.tail(4).round(2).to_string())

fig, ax = plt.subplots(figsize=(11, 5.5))
by_group.plot(ax=ax, marker=".")
ax.set_title("업종그룹별 분기 폐업률 (가중 집계, 분모=점포수)")
ax.set_xlabel("분기")
ax.set_ylabel("폐업률(%)")
ax.set_xticks(range(len(by_group.index)))
ax.set_xticklabels(by_group.index, rotation=45)
ax.grid(alpha=0.3)
shade_covid(ax, list(by_group.index))
ax.legend(title="업종그룹", fontsize=8)
fig.tight_layout()
fig.savefig(FIG / "03_업종그룹별_분기_폐업률.png", dpi=150)

# --- 4. 구·동 단위 현황표 --------------------------------------------------
TAB = ROOT / "reports" / "tables"
TAB.mkdir(parents=True, exist_ok=True)
GU, DONG = "geometry_district_name", "geometry_neighborhood_name"

# 구별: 분기 × 구 폐업률 표 + 연도별 표
gu_q = weighted_closure_rate(df, [GU, "분기라벨"], DENOM_STORE).unstack()
gu_y = weighted_closure_rate(df, [GU, "연도"], DENOM_STORE).unstack()
gu_q.round(3).to_csv(TAB / "구별_분기_폐업률.csv", encoding="utf-8-sig")
gu_y.round(3).to_csv(TAB / "구별_연도별_폐업률.csv", encoding="utf-8-sig")
print("\n=== 구별 연도별 폐업률(%) — 분기 기준 가중 집계 ===")
print(gu_y.round(2).to_string())

# 동별: 반드시 ['구','동'] 쌍으로 groupby (동명이동 존재, 설계서 §2.1)
dong_q = weighted_closure_rate(df, [GU, DONG, "분기라벨"], DENOM_STORE).unstack()
dong_y = weighted_closure_rate(df, [GU, DONG, "연도"], DENOM_STORE).unstack()
dong_q.round(3).to_csv(TAB / "동별_분기_폐업률.csv", encoding="utf-8-sig")
dong_y.round(3).to_csv(TAB / "동별_연도별_폐업률.csv", encoding="utf-8-sig")
latest_year = int(df["연도"].max())
print(f"\n=== {latest_year}년 동별 폐업률 상위 10 (분기 기준 가중 집계) ===")
print(dong_y[latest_year].nlargest(10).round(2).to_string())
print(f"\n=== {latest_year}년 동별 폐업률 하위 10 ===")
print(dong_y[latest_year].nsmallest(10).round(2).to_string())

# 동별 차트: 최신 연도 상위·하위 15개 (라벨은 "동(구)" — 동명이동 구분용)
dong_latest = dong_y[latest_year].dropna()
dong_latest.index = [f"{d}({g})" for g, d in dong_latest.index]
top, bottom = dong_latest.nlargest(15), dong_latest.nsmallest(15)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6))
top.sort_values().plot.barh(ax=ax1, color="tab:red")
ax1.set_title(f"{latest_year}년 동별 폐업률 상위 15")
bottom.sort_values(ascending=False).plot.barh(ax=ax2, color="tab:green")
ax2.set_title(f"{latest_year}년 동별 폐업률 하위 15")
for ax in (ax1, ax2):
    ax.set_xlabel("폐업률(%)")
    ax.grid(alpha=0.3, axis="x")
fig.suptitle(f"동별 폐업률 (분기 기준, 가중 집계) — 전체 {len(dong_latest)}개 동 중 양극단")
fig.tight_layout()
fig.savefig(FIG / "05_동별_폐업률_상하위.png", dpi=150)

# 구별 차트: 최신 연도 가로 막대
fig, ax = plt.subplots(figsize=(8, 9))
gu_y[latest_year].sort_values().plot.barh(ax=ax, color="tab:blue")
ax.set_title(f"{latest_year}년 구별 폐업률 (분기 기준, 가중 집계)")
ax.set_xlabel("폐업률(%)")
ax.set_ylabel("")
ax.grid(alpha=0.3, axis="x")
fig.tight_layout()
fig.savefig(FIG / "04_구별_폐업률.png", dpi=150)

# --- 검산: 동→구→유형 합산 일치 (설계서 §2.2 검산 장치) -------------------
overall = df[CLOSE].sum() / df[DENOM_STORE].sum() * 100
for level, cols in [("유형", ["area_type_name"]), ("구", [GU]), ("동", [GU, DONG])]:
    s = df.groupby(cols)[[CLOSE, DENOM_STORE]].sum()
    recombined = s[CLOSE].sum() / s[DENOM_STORE].sum() * 100
    assert abs(overall - recombined) < 1e-9, f"검산 실패({level}): 어딘가에서 평균을 냈음"
print(f"\n검산 통과: 전체 {overall:.4f}% == 유형·구·동 합산 재결합 일치")
print(f"figures 저장 위치: {FIG}")
