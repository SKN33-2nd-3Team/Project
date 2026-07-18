# -*- coding: utf-8 -*-
"""증감률 파생변수 공용 함수 (분석설계서 §2.3)

매출·유동인구·상주인구·직장인구 모두 이 산식으로 통일한다:
    증감률(t) = ( 값(t) − 직전2분기평균 ) ÷ 직전2분기평균 × 100
    직전2분기평균 = ( 값(t-1) + 값(t-2) ) ÷ 2

- 각 셀(group_cols 단위)의 최초 2개 분기는 계산 불가 → NaN
- 분기가 연속하지 않는 셀(중간 분기 누락)도 NaN 처리
- 계절성이 섞여 있으므로 모델에는 분기 더미를 함께 넣고,
  EDA 해석은 같은 분기끼리 비교할 것 (설계서 §2.3)
"""
import numpy as np
import pandas as pd


def add_growth_rate(df: pd.DataFrame, value_col: str, group_cols,
                    quarter_col: str = "quarter", suffix: str = "_증감률") -> pd.DataFrame:
    """value_col의 증감률 컬럼(value_col+suffix)을 추가한 사본을 반환한다."""
    out = df.sort_values(list(group_cols) + [quarter_col]).copy()
    # 분기를 연속 정수로 변환해 실제 직전 분기인지 검증 (예: 20214 다음은 20221)
    out["_qnum"] = (out[quarter_col] // 10) * 4 + (out[quarter_col] % 10)

    g = out.groupby(list(group_cols))
    lag1, lag2 = g[value_col].shift(1), g[value_col].shift(2)
    consecutive = ((out["_qnum"] - g["_qnum"].shift(1) == 1)
                   & (out["_qnum"] - g["_qnum"].shift(2) == 2))
    prev2 = (lag1 + lag2) / 2

    rate = (out[value_col] - prev2) / prev2 * 100
    rate[~consecutive | (prev2 <= 0)] = np.nan
    out[value_col + suffix] = rate
    return out.drop(columns="_qnum")
