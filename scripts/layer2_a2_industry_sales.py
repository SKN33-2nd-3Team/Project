# -*- coding: utf-8 -*-
"""2층-A2: 업종 → 매출 (분석설계서 §3 2층-A2)

업종 '단독'으로 매출 증감률과의 연관을 확인한다 (상권과 섞지 않음).
- 분석 단위: 업종그룹 (팀 결정 ④ — 세부업종 단위 분석 금지)
- 종속변수: 매출 증감률 (§2.3 산식, src/growth_rate.py)
- 분석 행: 2023년 이후만 (팀 결정 ① — 2021~22는 학습·검정 제외.
  단, 2023Q1의 증감률 계산에 필요한 직전 분기 '값'은 2022에서 가져옴)
- 검정: Kruskal-Wallis (증감률은 극단값이 많아 비모수 검정 사용)
  + 계절성 대응으로 같은 분기끼리도 별도 검정 (§2.3)

산출물:
- data/interim/sales_growth.csv  — 셀(상권×업종×분기) 단위 매출 증감률 (팀 공용)
- reports/figures/06, 07         — 업종그룹별 분포, 업종그룹×분기 중앙값
- 콘솔: 검정 결과 + 유효/무효 판정 (3층 전달용)
"""
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_rules import apply_exclusions
from src.growth_rate import add_growth_rate

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

DATA = ROOT / "data" / "raw" / "seoul_commercial_area_2021_2026Q1.csv"
FIG = ROOT / "reports" / "figures"
INTERIM = ROOT / "data" / "interim"

USECOLS = ["quarter", "area_code", "industry_code", "industry_name",
           "industry_group", "sales_record_present", "sales_monthly_sales"]
df = apply_exclusions(pd.read_csv(DATA, usecols=USECOLS))
df = df[df["sales_record_present"].astype(str).str.lower() == "true"]
print(f"매출 기록 있는 행: {len(df):,}")

# --- 증감률 파생 (전 기간 계산 — 2023Q1의 직전 분기 값은 2022에서 옴) ------
df = add_growth_rate(df, "sales_monthly_sales", ["area_code", "industry_code"])
df = df.rename(columns={"sales_monthly_sales_증감률": "매출_증감률"})
df["분기"] = df["quarter"] % 10
INTERIM.mkdir(parents=True, exist_ok=True)
df[["quarter", "area_code", "industry_code", "industry_name", "industry_group",
    "sales_monthly_sales", "매출_증감률"]].to_csv(
    INTERIM / "sales_growth.csv", index=False, encoding="utf-8-sig")

# --- 분석 대상: 2023~ & 증감률 유효 행 ------------------------------------
a = df[(df["quarter"] >= 20231) & df["매출_증감률"].notna()].copy()
print(f"분석 행(2023~, 증감률 유효): {len(a):,}")
print(f"매출 증감률 분포: 중앙값 {a['매출_증감률'].median():.2f}%, "
      f"IQR [{a['매출_증감률'].quantile(0.25):.2f}, {a['매출_증감률'].quantile(0.75):.2f}]")


def kw_test(frame, group_col, label):
    """Kruskal-Wallis 검정 + epsilon^2 효과크기."""
    groups = [g["매출_증감률"].values for _, g in frame.groupby(group_col) if len(g) >= 30]
    h, p = stats.kruskal(*groups)
    n, k = sum(len(g) for g in groups), len(groups)
    eps2 = (h - k + 1) / (n - k)  # 효과크기 (0~1)
    print(f"{label}: H={h:,.1f}, p={p:.2e}, epsilon^2={eps2:.4f} (군 {k}개, n={n:,})")
    return eps2


print("\n=== Kruskal-Wallis: 업종그룹에 따라 매출 증감률 분포가 다른가 ===")
eps_grp = kw_test(a, "industry_group", "업종그룹 전체 기간")
print("\n--- 계절성 통제: 같은 분기끼리 ---")
eps_by_q = [kw_test(a[a["분기"] == q], "industry_group", f"{q}분기만")
            for q in [1, 2, 3, 4]]

# --- 차트 6: 업종그룹별 분포 (극단값 제외 boxplot) --------------------------
order = a.groupby("industry_group")["매출_증감률"].median().sort_values().index
fig, ax = plt.subplots(figsize=(11, 5.5))
ax.boxplot([a.loc[a["industry_group"] == g, "매출_증감률"] for g in order],
           tick_labels=order, showfliers=False)
ax.axhline(0, color="gray", lw=0.8, ls="--")
ax.set_title("업종그룹별 매출 증감률 분포 (2023~2025, 극단값 미표시)")
ax.set_ylabel("매출 증감률(%)")
ax.tick_params(axis="x", rotation=20)
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig(FIG / "06_업종그룹별_매출증감률_분포.png", dpi=150)

# --- 차트 7: 업종그룹 × 분기 중앙값 (같은 분기끼리 비교, §2.3) --------------
med_q = (a.groupby(["industry_group", "분기"])["매출_증감률"]
          .median().unstack().loc[order])
fig, ax = plt.subplots(figsize=(11, 5.5))
med_q.rename(columns=lambda q: f"{q}분기").plot.bar(ax=ax, width=0.8)
ax.axhline(0, color="gray", lw=0.8, ls="--", label="_nolegend_")
ax.set_title("업종그룹 × 분기별 매출 증감률 중앙값 (2023~2025)")
ax.set_ylabel("매출 증감률 중앙값(%)")
ax.set_xlabel("")
ax.tick_params(axis="x", rotation=20)
ax.grid(alpha=0.3, axis="y")
ax.legend(title="분기")
fig.tight_layout()
fig.savefig(FIG / "07_업종그룹_분기별_매출증감률.png", dpi=150)

print("\n=== 업종그룹별 매출 증감률 중앙값(%) ===")
print(a.groupby("industry_group")["매출_증감률"].median().sort_values().round(2).to_string())
print("\n=== 업종그룹 × 분기 중앙값(%) ===")
print(med_q.round(2).to_string())

# --- 3층 전달용 판정 --------------------------------------------------------
print("\n=== 2층-A2 판정 (3층 전달) ===")
eps_season = sum(eps_by_q) / len(eps_by_q)
verdict = "유의" if eps_season >= 0.01 else "통계적으로 유의하나 효과 미미"
print(f"업종그룹 → 매출 증감률: p<0.001, epsilon^2 전체 {eps_grp:.4f} / "
      f"같은 분기끼리 평균 {eps_season:.4f} → 단독 {verdict} (계절 통제 조건부)")
print("주의: 표본이 커서 p값은 무조건 작게 나옴. 효과크기(epsilon^2)와 분포 차이로 판단할 것")
