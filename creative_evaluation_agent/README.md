# Creative Evaluation Agent

광고 운영 데이터와 실제 광고 소재(이미지/영상)를 입력받아 3개의 Excel 리포트를 생성하는 로컬 에이전트다.
전체 설계 원칙과 판정 기준은 `Creative_Evaluation_Agent_Build_Spec_V1.md` + `Creative_Evaluation_Agent_Build_Spec_V2.md`(Winner 해석 레이어 추가분)를 따른다.

현재 구현 범위: **Phase 1~3** (프로젝트 골격 / Engine 01 / Benchmark Harness) + V2 Winner 해석 레이어.
Engine 02 production 실행과 Engine 03 결합 로직은 Benchmark 완료 후 별도 단계에서 구현한다.

## 실행 방법

1. `run_agent.bat`을 더블클릭한다.
   - 최초 실행 시 프로젝트 전용 `.venv`를 만들고 `requirements.txt`를 자동 설치한다 (몇 분 소요될 수 있음).
   - 이후 실행부터는 바로 대화형 메뉴가 뜬다.
2. 메뉴에서 `1) Engine 01 실행`을 선택하면 `input/data`의 광고 운영 데이터 엑셀과 `input/assets`의 소재를 읽어
   `output/latest/`에 3개 리포트를 생성하고, `output/archive/YYYY-MM-DD_HHMM/`에도 동일하게 보관한다.

CLI로 직접 실행할 수도 있다 (`.venv\Scripts\python.exe run.py <subcommand>`):

```
python run.py engine01
python run.py benchmark prepare
python run.py benchmark run --provider openai --dry-run
python run.py benchmark run --provider openai
python run.py benchmark run --provider claude
python run.py benchmark compare
```

## 입력 준비

- `input/data/` : 광고 운영 데이터 엑셀 1개. 컬럼 표기가 `config/column_aliases.yaml`의 별칭 목록과
  다르면 거기에 실제 헤더를 추가해야 한다 (임의 추측 매핑을 하지 않기 때문).
- `input/assets/<매체명>/` : 소재 파일. 단일 이미지/영상은 파일명이 소재명과 동일해야 하고,
  캐러셀은 소재명과 같은 이름의 폴더 안에 이미지 여러 장을 넣는다 (spec §2).
- 실행 후에도 `input`은 자동으로 삭제/이동되지 않는다. 교체/삭제는 사용자가 직접 한다.

## Engine 01 (완성)

- Python deterministic rule engine. LLM은 숫자 판정에 관여하지 않는다.
- 모든 최종 판정은 근거값(Reliability, KPI actual/BM/Gap, Scale Index/Level, Basis 1/2/3, Action,
  Final Comment)과 함께 `01_Creative_Performance_Evaluation.xlsx`의 `Performance_Evaluation` 시트에 출력된다.
- `Methodology` 시트에 모든 공식/threshold/config 값이 감사 가능하도록 정리되어 있다.
- 명세에 없는 값은 절대 임의로 채우지 않는다 — `config/evaluation_rules.yaml`의
  `traffic_promising_interpretation`, `ground_truth.around_benchmark` 항목 참고 (TODO 표시됨).

### Winner 해석 레이어 (V2 추가)

`Final_Classification`(WINNER/HIDDEN GEM/...)과는 별개 레이어로 `src/winner_interpretation.py`가
`Efficiency_Rank`, `Delivery_Rank`, `Allocation_Context`, `Winner_Type`(EFFICIENCY_LEADER/
SCALED_WINNER/BOTH/NONE), `Primary_Winner`, `Primary_Winner_Reason`을 계산해 01 Excel에 추가한다.

- 후보 풀은 이미 Benchmark 이상으로 판정된 소재만(WINNER/HIDDEN GEM, TRAFFIC WINNER/TRAFFIC HIDDEN GEM).
- Efficiency Leader == Scaled Winner인 경우만 `Primary_Winner="Y"`로 자동 확정한다.
- 둘이 다른 소재면 `Primary_Winner="CHECK"` + 근거를 `Primary_Winner_Reason`에 남기고 사람이 확정한다 —
  spec V2가 "ROAS 차이 몇% 이내면 Scale을 우선한다" 같은 고정 threshold를 의도적으로 두지 않았기 때문
  (Human Feedback/Backtest 이후 정교화 예정, Engine 03에서 Human_Override로 받을 예정).
- `Allocation_Context`(AUTO/MANUAL/UNKNOWN)는 광고데이터에 해당 컬럼이 없으면 전부 `UNKNOWN`이다 —
  `config/column_aliases.yaml > Allocation_Context`에 실제 컬럼명을 추가하면 자동 인식된다.

## Benchmark Harness (완성, 실제 API 호출은 사용자 승인 필요)

OpenAI vs Claude 블라인드 벤치마크 — Production Engine 02에 쓸 모델을 고르기 위한 비교 실험이다.

1. `benchmark/source_assets/<매체명>/`에 벤치마크용 소재(24~30개 권장)를 넣는다.
2. `python run.py benchmark prepare` — 원본을 건드리지 않고 `benchmark/blind_assets/`에 `asset_001` 형태로
   복사하고 `benchmark/mapping/benchmark_asset_map.xlsx`에 원본↔Blind_ID 매핑을 남긴다.
3. `python run.py benchmark run --provider openai --dry-run` (또는 `claude`) — **API를 호출하지 않고**
   신규 분석 대상 수/캐시 재사용 수/예상 비용만 보여준다.
4. `.env` 파일에 `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`를 채운 뒤 (`.env.example` 참고) dry-run 없이 실행하면
   비용 요약을 보여주고 `[Y/N]` 승인을 받은 뒤에만 실제 API를 호출한다.
5. 두 provider 모두 실행이 끝나면(`benchmark/results/<provider>/_DONE` 생성됨) `benchmark/ground_truth/`에
   `hidden_ground_truth.xlsx` (`Blind_ID`, `Observed_Performance` 컬럼)를 준비하고
   `python run.py benchmark compare`를 실행한다. 두 provider가 모두 끝나기 전에는 Ground Truth를 읽지 못하도록
   잠겨 있다 (spec §9).
6. `benchmark/results/comparison/comparison_report.xlsx`에 방향 적중률 등 자동 지표 + Human review 빈 템플릿이
   생성된다. Human review(관찰 정확도/근거 품질/hallucination/업무 활용성)는 사람이 직접 채운다.

동일 소재+provider+model+prompt/schema version 조합은 캐시(`cache/creative_analysis/`)에서 재사용되어
중복 API 호출이 발생하지 않는다.

## 테스트

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

Engine 01 계산식(Benchmark/Reliability/Scale/최종분류)과 Benchmark Harness 전체 흐름(캐시, blind mapping,
ground truth 잠금, 승인 게이트)을 실제 API 호출 없이 검증한다.

## 알아둘 점 / TODO

- `config/model_config.yaml`의 `pricing_usd`는 각 provider 공식 문서에서 확인한 실제 단가다 (확인일
  2026-09-12, 출처는 yaml 내 `source` 필드 참고). 가격은 이후 바뀔 수 있으니 정기적으로 재확인할 것.
  이미지(vision) 토큰 수는 실제 프레임 해상도 + 공식 계산식(`src/pricing.py`)으로 정밀 계산되지만,
  output 토큰 수와 영상 transcript 분량은 사전에 알 수 없어 예상치다 (dry-run 화면에 구분 표시됨).
- 1차 Benchmark 모델: OpenAI `gpt-5.6-terra` vs Claude `claude-sonnet-5` (2026-09-12 확정, 체급을
  맞추기 위해 OpenAI 쪽을 mini급에서 변경함). `config/model_config.yaml > providers`에서 관리한다.
- `config/evaluation_rules.yaml`의 `traffic_promising_interpretation.operator`는 스펙에 정확한 연산자가
  명시되지 않아 기본값(OR)으로 채워둔 것이다. 의도와 다르면 수정할 것.
- `ground_truth.around_benchmark`는 스펙에 tolerance %가 없어 기본 비활성(ABOVE/BELOW 이분)이다.
- 영상 transcript는 OpenAI Whisper API만 사용한다 (Claude 벤치마크 때도 동일 transcript 재사용 —
  provider 간 입력조건 동일 유지). 25MB 초과 영상은 transcript 없이 진행되며 그 사실이 상태값으로 남는다.
- Engine 02 production 모델 확정과 Engine 03 결합 로직은 이번 빌드 범위 밖이다 (`src/integration.py` 참고).
