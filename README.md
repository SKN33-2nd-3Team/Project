# 서울시 민생경제의 버팀목, 소상공인을 잡아라

서울시 상권분석서비스 데이터(2021~2025, 분기)로 상권·업종·매출·인구 요소와 폐업의
연관 구조를 진단하고, **다음 분기 폐업률(연속값)을 회귀로 예측**하는 프로젝트.
고객 이탈 예측 방법론의 공공 도메인 적용 (폐업 = 이탈). 제출 2026-07-22.

## 문서

- [분석설계서](docs/분석설계서.md) — 산식·시점 정렬·제외 규칙 등 분석 공통 규칙. **파트 착수 전 필독**
- [GitHub 협업 규칙](CONTRIBUTING.md) — Issue·브랜치·커밋·PR 규칙
- [1층·2층-A2 결과 요약](docs/1층_2층A2_결과_3층전달.md) — 3층 전달용 판정

## 데이터

- `data/raw/seoul_commercial_area_2021_2026Q1.csv` (약 404MB) — **저장소에 포함되지 않음.**
  팀 공유 드라이브에서 받아 `data/raw/`에 배치할 것. 실제 분기 범위는 2021Q1~2025Q4
- 파생 데이터(`data/interim/`)와 산출물(`reports/`)은 스크립트 재실행으로 생성됨

## 실행

```bash
pip install -r requirements.txt
py scripts/layer1_status.py            # 1층: 현황 차트·구/동 현황표
py scripts/layer2_a2_industry_sales.py # 2층-A2: 업종그룹→매출 검정
```

- 공용 함수: `src/closure_rate.py`(폐업률 가중 집계), `src/growth_rate.py`(증감률 산식),
  `src/data_rules.py`(팀 제외 규칙 — 모든 스크립트가 로드 직후 호출)
