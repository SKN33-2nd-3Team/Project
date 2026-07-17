# -*- coding: utf-8 -*-
"""팀 공통 데이터 제외 규칙 (분석설계서 §2.5)

모든 층(1~4층)의 분석 스크립트는 데이터 로드 직후 apply_exclusions()를 호출한다.
제외 규칙 변경은 팀 합의 후 설계서를 먼저 수정할 것.
"""
import pandas as pd

# 팀 결정(2026-07-17): 법무·회계·부동산·전문서비스 그룹 제외.
# 실제 구성 업종이 '통번역서비스' 1개뿐이라 그룹명이 내용을 대표하지 못하고
# (법무·회계·부동산 업종은 데이터에 없음), 매출 기록도 전무해 분석 불가.
EXCLUDED_INDUSTRY_GROUPS = ["법무·회계·부동산·전문서비스"]

# 팀 결정(2026-07-17): 세부업종 '핸드폰' 제외.
# 통신사·대리점 정책에 따라 같은 자리에서 폐업↔다른 사업자 개업을 수시로
# 반복하는 업종이라, 폐업 건수가 실제 영업 중단 위험을 반영하지 못함.
EXCLUDED_INDUSTRIES = ["핸드폰"]


def apply_exclusions(df: pd.DataFrame) -> pd.DataFrame:
    """제외 규칙을 적용한 사본을 반환하고, 제외 건수를 출력한다.

    industry_group·industry_name 컬럼이 둘 다 필요하다 (usecols에 포함할 것).
    컬럼이 없으면 제외 규칙이 누락된 채 분석되는 것을 막기 위해 에러를 낸다.
    """
    missing = {"industry_group", "industry_name"} - set(df.columns)
    if missing:
        raise KeyError(f"제외 규칙 적용에 필요한 컬럼 누락: {missing} — usecols에 추가하세요")
    mask = (df["industry_group"].isin(EXCLUDED_INDUSTRY_GROUPS)
            | df["industry_name"].isin(EXCLUDED_INDUSTRIES))
    excluded = ", ".join(EXCLUDED_INDUSTRY_GROUPS + EXCLUDED_INDUSTRIES)
    if mask.any():
        print(f"[제외 규칙] {excluded}: {mask.sum():,}행 제외")
    return df[~mask].copy()
