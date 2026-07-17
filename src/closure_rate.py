# -*- coding: utf-8 -*-
"""폐업률 가중 집계 공용 함수 (분석설계서 §2.2)

어떤 단위로 집계하든 하위 폐업률의 평균을 내지 않고
반드시 원건수를 합산한 뒤 나눈다:
    폐업률(%) = Σ(폐업 점포 수) ÷ Σ(분모 점포 수) × 100

팀 결정(2026-07-17, 설계서 §5 안건 2): 분모는 stores_store_count.
데이터의 기존 폐업률·개업률 컬럼은 분모가 유사 업종 점포수라서 사용하지 않는다.
DENOM_SIMILAR는 기존 컬럼과의 대조 검증용으로만 남겨둔다.
"""
import pandas as pd

DENOM_STORE = "stores_store_count"
DENOM_SIMILAR = "stores_similar_store_count"
CLOSE = "stores_close_store_count"


def weighted_closure_rate(df: pd.DataFrame, group_cols, denom: str = DENOM_STORE) -> pd.Series:
    """group_cols 단위의 가중 폐업률(%)을 반환한다.

    검산 성질: 하위 단위 건수를 합치면 상위 단위와 정확히 일치한다.
    """
    g = df.groupby(group_cols)[[CLOSE, denom]].sum()
    return (g[CLOSE] / g[denom] * 100).rename("폐업률")


def add_year(df: pd.DataFrame) -> pd.DataFrame:
    """quarter(예: 20213) 컬럼에서 연도·분기 파생 컬럼을 추가한다."""
    out = df.copy()
    out["연도"] = out["quarter"] // 10
    out["분기"] = out["quarter"] % 10
    return out
