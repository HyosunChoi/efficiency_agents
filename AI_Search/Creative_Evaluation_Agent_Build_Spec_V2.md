# Creative Evaluation Agent — Claude Code Build Spec V1

## 0. 프로젝트 위치

> V2 변경사항: Engine 01에 `Efficiency Leader / Scaled Winner / Primary Winner` 해석 레이어를 추가한다. 기존 기본 Classification은 유지한다.

루트 폴더:

`C:\Users\hscho\Documents\efficiency_agents\creative_evaluation_agent`

이 프로젝트는 광고 운영 데이터와 실제 광고 소재(이미지/영상)를 입력받아 아래 3개 Excel 리포트를 생성하는 로컬 에이전트다.

1. `01_Creative_Performance_Evaluation.xlsx`
2. `02_Creative_Content_Analysis.xlsx`
3. `03_Integrated_Creative_Evaluation.xlsx`

V1 기본 실행 방식은 `run_agent.bat` 더블클릭이다.

---

## 1. 핵심 설계 원칙

### Engine 01 — Performance Engine
- 광고 운영 데이터만 본다.
- 실제 소재 내용은 보지 않는다.
- Python 규칙엔진으로 계산한다.
- LLM이 숫자 판정을 임의로 하지 않는다.

### Engine 02 — Creative Content Engine
- 실제 이미지/영상만 본다.
- 광고 성과 데이터는 절대 보여주지 않는다.
- 소재 자체의 관찰값과 예상 반응을 AI API로 평가한다.
- `HIGH / MEDIUM / LOW` + `Confidence` + 판단근거값을 함께 출력한다.

### Engine 03 — Integration Engine
- 01과 02 결과를 처음으로 결합한다.
- 01의 실제 성과판정을 02의 AI 판단이 뒤집지 않는다.
- 02는 실제 성과를 설명하고 일치/불일치 패턴을 찾는 해석 레이어다.
- Human Feedback은 03 파일에서 받는다.

모든 판정은 **최종 라벨만 출력하지 않고 그 판단을 만든 기준값을 함께 출력**한다.

---

## 2. 사용자 입력 구조

```text
creative_evaluation_agent\
├─ run_agent.bat
├─ input\
│  ├─ data\
│  └─ assets\
└─ output\
```

### 광고 운영 데이터
`input\data\`에 Excel 1개를 둔다.

### 광고 소재
`input\assets\매체명\` 아래에 둔다.

ut\assets\매체명\` 아래에 둔다.

예:

```text
input\assets\
├─ 싱글원_메타\
│  ├─ 소재명1.mp4
│  └─ 소재명2.jpg
├─ 싱글원_라인\
│  └─ 소재명1.mp4
├─ 싱글원_틱톡\
│  ├─ 소재명1.mp4
│  └─ 소재명2.mp4
└─ 오리지널_틱톡\
   └─ 소재명.mp4
```

단일 이미지/영상은 파일명이 광고데이터의 `소재명`과 같아야 한다.

멀티이미지/캐러셀은 다음처럼 소재명 폴더를 사용한다.

```text
싱글원_메타\
└─ 소재명_모음\
   ├─ 01.jpg
   ├─ 02.jpg
   └─ 03.jpg
```

### Creative_ID
사용자가 입력하지 않는다.

`Creative_ID = Normalized_Media + "__" + Normalized_Creative_Name`

예: `싱글원_메타__무글틴_1+1_0828`

---

## 3. 권장 폴더 구조

```text
creative_evaluation_agent\
│
├─ run_agent.bat
├─ run.py
├─ README.md
├─ requirements.txt
├─ .env.example
├─ .gitignore
│
├─ input\
│  ├─ data\
│  └─ assets\
│
├─ output\
│  ├─ latest\
│  └─ archive\
│
├─ benchmark\
│  ├─ source_assets\
│  ├─ blind_assets\
│  ├─ mapping\
│  │  └─ benchmark_asset_map.xlsx
│  ├─ ground_truth\
│  │  └─ hidden_ground_truth.xlsx
│  └─ results\
│     ├─ openai\
│     ├─ claude\
│     └─ comparison\
│
├─ cache\
│  ├─ asset_hashes\
│  └─ creative_analysis\
│
├─ config\
│  ├─ evaluation_rules.yaml
│  ├─ normalization_rules.yaml
│  ├─ column_aliases.yaml
│  └─ model_config.yaml
│
├─ prompts\
│  ├─ creative_analysis_prompt.md
│  └─ benchmark_prompt.md
│
├─ src\
│  ├─ loader.py
│  ├─ normalizer.py
│  ├─ matcher.py
│  ├─ benchmark.py
│  ├─ reliability.py
│  ├─ scale.py
│  ├─ evaluator.py
│  ├─ frame_extractor.py
│  ├─ transcript.py
│  ├─ asset_analyzer.py
│  ├─ integration.py
│  ├─ exporter.py
│  ├─ cache.py
│  ├─ validator.py
│  └─ providers\
│     ├─ base.py
│     ├─ openai_client.py
│     └─ anthropic_client.py
│
├─ logs\
├─ tests\
└─ docs\
```

V1에서는 실행 후 `input`을 자동 삭제하거나 이동하지 않는다. 사용자가 직접 교체/삭제한다.

---

## 4. 소재 매칭 원칙

기본 매칭키는 `매체 + 소재명`이다.

- 파일 확장자는 비교에서 제외
- 명백한 표기 정규화는 허용
- 의미 추정 매칭은 금지

상태값:
- 매칭 없음: `ASSET_NOT_FOUND`
- 복수 매칭: `MULTIPLE_ASSET_MATCH`
- 애매함: `CHECK`

프로그램은 비슷해 보인다는 이유로 임의 매칭하지 않는다.

---

## 5. Engine 01 — Performance Evaluation

### Benchmark 그룹
`제품명 × Objective`

단순 평균 금지. 반드시 집계된 분자/분모로 재계산한다.

- CTR BM = `ΣClicks / ΣImpressions`
- CPC BM = `ΣSpend / ΣClicks`
- CPM BM = `ΣSpend / ΣImpressions × 1000`
- CVR BM = `ΣConversions / ΣClicks`
- CPA BM = `ΣSpend / ΣConversions`
- ROAS BM = `ΣRevenue / ΣSpend`

### Performance 평가 그룹
`제품명 × Objective × 소재명`

### Objective 자동 분류
Conversion 예: `전환`, `구매`, `conversion`
Traffic 예: `유입`, `트래픽`, `traffic`
애매하면 `UNKNOWN` + `CHECK`

### Budget Share / Scale
제품 전체 광고비 = 100%

Budget Share 그룹: `제품명 × 소재명`

- Valid Creative = 분석기간 내 Spend > 0
- Equal Share = `100% / 유효 소재 수`
- Scale Index = `실제 제품 기준 소재 광고비 비중 / Equal Share`

Scale 해석:
- `<0.5` Under-delivery
- `0.5~<0.8` Low Scale
- `0.8~1.2` Normal
- `>1.2~1.5` High
- `>1.5` Strong

최종 판정 Scale threshold 기본값 = `0.8`

### Reliability — Conversion
- R0: 0–2
- R1: 3–4
- R2: 5–9
- R3: 10+

### Reliability — Traffic
- R0: <30 clicks
- R1: 30–49
- R2: 50–99
- R3: 100+

R0/R1은 확정 Winner/Underperformer 판정을 하지 않는다.

### Conversion 최종 분류
- WINNER: R2/R3 + ROAS ≥ BM + Scale ≥0.8
- HIDDEN GEM: R2/R3 + ROAS ≥ BM + Scale <0.8
- BUDGET DRAINER: R2/R3 + ROAS < BM + Scale ≥0.8
- UNDERPERFORMER: R2/R3 + ROAS < BM + Scale <0.8
- PROMISING: R0/R1 + ROAS ≥ BM
- UNRESOLVED: R0/R1 + ROAS < BM

회사 Target ROAS/CPA/CPC는 소재평가에 사용하지 않는다.

### Traffic 최종 분류
Traffic은 CPC 1차, CTR 2차, CPM 진단용.

- TRAFFIC WINNER: R2/R3 + CPC ≤ BM + CTR ≥ BM + Scale ≥0.8
- TRAFFIC HIDDEN GEM: R2/R3 + CPC ≤ BM + CTR ≥ BM + Scale <0.8
- COST EFFICIENT: R2/R3 + CPC ≤ BM + CTR < BM
- HOOK STRONG: R2/R3 + CPC > BM + CTR ≥ BM
- UNDERPERFORMER: R2/R3 + CPC > BM + CTR < BM
- PROMISING: R0/R1 + CPC/CTR 유리
- UNRESOLVED: R0/R1 + 그 외


### Winner 해석 레이어

기존 `WINNER / HIDDEN GEM / BUDGET DRAINER / UNDERPERFORMER / PROMISING / UNRESOLVED` 판정은 그대로 유지한다.

이 판정은 소재별 기본 성과 상태를 나타내며, **대표 위너(Primary Winner) 선정과는 별개의 레이어**로 본다.

동일 `제품명 × Objective` 안에서 여러 소재가 동시에 WINNER 조건을 충족할 수 있다.

#### Winner Type

다음 보조 분류를 추가한다.

- `EFFICIENCY_LEADER`
  - 동일 제품×Objective 내에서 순수 효율 지표가 가장 강한 소재
  - Conversion은 기본적으로 ROAS 중심
  - Traffic은 기본적으로 CPC 중심, CTR 보조

- `SCALED_WINNER`
  - 충분한 예산을 실제로 소화하면서도 Benchmark 이상의 효율을 유지한 소재
  - Spend Share, Scale Index, Delivery Rank를 함께 본다

- `BOTH`
  - Efficiency Leader이면서 Scaled Winner인 소재

- `NONE`
  - 위 조건에 해당하지 않는 소재

#### 추가 기준값

01 파일에 최소 아래 항목을 추가한다.

- `Efficiency_Rank`
- `Delivery_Rank`
- `Spend_Share`
- `Scale_Index`
- `Allocation_Context`
- `Winner_Type`
- `Primary_Winner`
- `Primary_Winner_Reason`

#### Allocation Context

자동예산배분 여부를 알 수 있다면 다음 값을 사용한다.

- `AUTO`
- `MANUAL`
- `UNKNOWN`

`AUTO`는 플랫폼이 특정 소재를 공식적으로 “우수소재”라고 판정했다는 의미가 아니다.

정확한 해석은:

> **자동배분 환경에서 상대적으로 높은 Delivery를 확보했다.**

예산 집중에는 캠페인 구조, 입찰, 투입 시점, 학습상태 등 다른 요인도 개입할 수 있으므로 플랫폼의 품질판정으로 단정하지 않는다.

#### Primary Winner 선정 원칙

대표 위너 하나를 선정해야 하는 경우 단순 ROAS 최고값만 사용하지 않는다.

다음 요소를 함께 본다.

1. Reliability
2. Benchmark 대비 상대 효율
3. Spend Share
4. Scale Index
5. 실제 예산 소화 규모(Delivery)
6. Allocation Context

자동배분 환경에서 특정 소재가 더 큰 예산을 소화하면서도 Benchmark 이상의 효율을 유지한 경우, 효율이 일부 희석되더라도 `SCALED_WINNER` 또는 `Primary_Winner`로 선정할 수 있다.

예:

- 소재 A: ROAS 최고, 예산 소화 작음 → `EFFICIENCY_LEADER`
- 소재 B: ROAS는 A보다 다소 낮지만 큰 예산을 소화하면서 Benchmark 이상 유지 → `SCALED_WINNER`, 필요 시 `Primary_Winner`

#### 중요

현재 V2에서는 `ROAS 차이가 몇 % 이내면 Scale을 우선한다` 같은 고정 threshold를 두지 않는다.

이 값은 Human Feedback과 과거 사례가 충분히 축적된 뒤 Backtest를 통해 결정한다.

따라서 V2의 `Primary_Winner`는:
- 규칙엔진이 후보를 제시할 수는 있으나
- threshold가 미정인 경우 `Human_Override` 또는 `Primary_Winner_Reason`으로 최종 확정 가능하게 한다.

### 01 Excel 필수
최종 판정과 함께 반드시 근거값을 출력한다.

예:
- Final Classification
- KPI actual
- KPI Benchmark
- Gap
- Conversion/Click Count
- Reliability
- Product Spend Share
- Equal Share
- Scale Index
- Scale Level
- Efficiency Rank
- Delivery Rank
- Allocation Context
- Winner Type
- Primary Winner
- Primary Winner Reason
- Basis 1/2/3
- Action
- Final Comment

`Methodology` 시트를 포함한다.

---

## 6. Engine 02 — Creative Content Analysis

### 블라인드 원칙
Engine 02에는 아래를 절대 전달하지 않는다.
- ROAS
- 전환수
- CPC/CTR
- 실제 Winner/Underperformer
- 01 최종 판정
- 실제 광고성과를 암시하는 텍스트

### V1 관찰 taxonomy
- Asset Type
- First 1–3 sec Core Element
- Hook Type
- Product First Exposure Time
- Main Visual Focus
- Offer Present / Offer Type
- Offer First Exposure Time
- Demo Present / Demo Start Time
- Actual Color / Makeup Result
- Before/After
- Person Type: Influencer / Model / UGC / Expert / None
- Proof Type
- Subtitle Prominence
- Core Message
- Message Density
- Immediate Understandability
- CTA Type / CTA First Time
- Brand/Product Name Exposure
- Cut Pace
- Average Cut Length (가능한 경우)

영상은 대표 프레임 + transcript 기반으로 분석한다.

기본 프레임 후보:
0s / 0.5s / 1.5s / 3s / 5s / 10s / 마지막 + scene-change 대표 프레임

### AI 판단
`AI_Predicted_Response`:
- HIGH
- MEDIUM
- LOW

`AI_Confidence`:
- HIGH
- MEDIUM
- LOW

최종 라벨만 출력하지 않는다.
반드시 아래를 함께 남긴다.
- 관찰 기준값
- Reason 1/2/3
- 근거 프레임/시점(가능한 경우)
- 불확실성/한계

---

## 7. API 호출 승인

유료 API 호출 전에 반드시 사용자 승인을 받는다.

예:

```text
광고 데이터: 1개
이미지: 18개
영상: 14개
총 소재: 32개

신규 API 분석 대상: 22개
캐시 재사용: 10개
예상 API 호출: 22건
예상 비용: $0.74

실행하시겠습니까? [Y/N]
```

사용자가 `Y` 입력 전에는 API 호출 금지.

API Key는 환경변수 또는 `.env`로 관리하고 코드에 하드코딩하지 않는다.

---

## 8. Cache

동일 소재 재분석 비용을 막는다.

캐시키 기본값:
- file hash
- provider/model
- prompt version
- schema version

동일 설정이면 기존 결과 재사용.

---

## 9. OpenAI vs Claude 블라인드 Benchmark

### 목적
Production Engine 02의 모델을 선택하기 위한 블라인드 Benchmark다.

이 단계는 **모델 학습/파인튜닝이 아니다.**
목적은:
- 모델 비교
- 프롬프트 검증
- taxonomy 검증
- 실제 회사 소재에서 어떤 모델이 더 잘 보는지 확인

### 블라인드 파일
원본: `benchmark\source_assets\`
블라인드 복사본: `benchmark\blind_assets\`

예:
`asset_001.mp4`, `asset_002.jpg`

원본 파일명은 변경하지 않는다.

매핑 파일:
`benchmark\mapping\benchmark_asset_map.xlsx`

권장 컬럼:
- Blind_ID
- Original_Media
- Original_Creative_Name
- Original_File_Name
- Asset_Type
- Original_Path
- Blind_Path

### Ground Truth
`benchmark\ground_truth\hidden_ground_truth.xlsx`

Provider 호출 코드가 예측 저장 전에는 이 파일을 읽지 못하게 분리한다.

비교용 실제값은 `Observed_Performance`로 둔다.

권장 값:
- `ABOVE_BENCHMARK`
- `BELOW_BENCHMARK`
- 필요 시 `AROUND_BENCHMARK`

Conversion은 제품×Objective ROAS BM 중심,
Traffic은 CPC/CTR BM 중심으로 정의한다.
정확한 세부 기준은 config로 분리한다.

### Benchmark 실행 순서
1. Blind asset 준비
2. OpenAI에 성과정보 없이 분석
3. 결과 저장
4. Claude에 동일 blind asset + 동일 schema로 분석
5. 결과 저장
6. 두 provider 결과 완료 후 Ground Truth unlock
7. 원본 매핑 복원
8. 실제성과와 예측 비교
9. Human quality score 입력
10. comparison 결과 저장

### 비교 지표
- HIGH/LOW 방향 적중
- 실제 고성과를 LOW로 놓친 비율
- 실제 저성과를 HIGH로 과대평가한 비율
- 소재 관찰 정확도
- 근거 구체성
- hallucination 여부
- 업무 활용성
- Confidence calibration
- API 비용
- 처리시간

Human review 예:
- Visual Observation Accuracy: 1–5
- Reason Quality: 1–5
- Hallucination: Yes/No
- Business Usefulness: 1–5
- Reviewer Comment

---

## 10. Engine 03 — Integration

03에서 처음 01과 02를 결합한다.

실제 광고성과와 AI 예측의 이름을 분리한다.

- `01_Final_Classification`
- `Observed_Performance`
- `02_AI_Predicted_Response`
- `02_AI_Confidence`

예:

| Observed_Performance | AI_Predicted_Response | Integration |
|---|---|---|
| ABOVE_BENCHMARK | HIGH | PREDICTION_MATCH_HIGH |
| BELOW_BENCHMARK | LOW | PREDICTION_MATCH_LOW |
| BELOW_BENCHMARK | HIGH | AI_OVERPREDICTED |
| ABOVE_BENCHMARK | LOW | AI_MISSED_WINNER |
| ABOVE/BELOW | MEDIUM | AI_NEUTRAL_OR_UNCERTAIN |

`AI_MISSED_WINNER`는 중요한 학습 사례로 표시한다.

03 필수 영역:
- Product / Objective / Media / Creative_Name / Creative_ID
- 01 Final Classification
- 01 Winner Type
- 01 Primary Winner
- 01 Primary Winner Reason
- Observed Performance
- 주요 실제성과 기준값
- 02 AI Predicted Response
- 02 AI Confidence
- 주요 소재 관찰값
- AI Reason 1/2/3
- Integration Status
- Integrated Interpretation
- Human Feedback
- Human Override
- Final Comment

Human Feedback은 특히 아래 상황에서 중요하게 축적한다.

- Efficiency Leader와 Primary Winner가 다른 경우
- 자동배분 환경에서 큰 예산을 소화한 소재를 대표 위너로 본 경우
- 효율 차이를 Scale 맥락에서 감수할 수 있다고 판단한 경우
- 규칙엔진 후보와 실무자 최종 판단이 다른 경우

예:

> `무글틴_Shiho`가 ROAS 기준 Efficiency Leader였으나, `올테무_Yuna`가 자동배분 환경에서 더 큰 예산을 소화하면서도 경쟁력 있는 효율을 유지해 Primary Winner로 선정.

이런 Human Feedback 사례가 충분히 쌓이면 향후 `Primary Winner` 자동 선정 threshold를 Backtest로 정교화한다.

---

## 11. Output 보관

항상 3개 리포트를 모두 보관한다.

```text
output\latest\
├─ 01_Creative_Performance_Evaluation.xlsx
├─ 02_Creative_Content_Analysis.xlsx
└─ 03_Integrated_Creative_Evaluation.xlsx
```

```text
output\archive\YYYY-MM-DD_HHMM\
├─ 01_Creative_Performance_Evaluation.xlsx
├─ 02_Creative_Content_Analysis.xlsx
└─ 03_Integrated_Creative_Evaluation.xlsx
```

---

## 12. 오류/검증 원칙

조용히 추정하지 않는다.

명시 상태 예:
- `CHECK`
- `ASSET_NOT_FOUND`
- `MULTIPLE_ASSET_MATCH`
- `UNKNOWN_OBJECTIVE`
- `API_ERROR`
- `PARSE_ERROR`
- `CACHE_HIT`

분모가 0인 KPI는 임의 계산하지 않는다.

---

## 13. 개발 단계

### Phase 1 — 프로젝트 골격
폴더/config/loader/normalizer/validator/run_agent.bat/logging

### Phase 2 — Engine 01
Benchmark/Reliability/Scale/평가/01 Excel/Methodology/tests

### Phase 3 — Benchmark Harness
blind mapping/blind copy/frame extraction/transcript/provider adapters/structured output/API 승인/cache/Ground Truth lock/comparison

### Phase 4 — 블라인드 Benchmark 실행
준비한 24~30개 소재를 OpenAI/Claude 동일 조건으로 분석하고 비교한다.

### Phase 5 — Engine 02 Production
Benchmark 승자 모델을 기본 provider로 설정하고 일반 input/assets를 분석해 02 Excel 생성.

### Phase 6 — Engine 03
01+02 결합/Human Feedback/03 Excel 생성.

### Phase 7 — Backtest 및 개선
과거 소재 대량 분석, AI_MISSED_WINNER/AI_OVERPREDICTED 검토, prompt/taxonomy 개선.

---

## 14. 지금 Claude Code가 우선 구현할 범위

첫 구현은 **Phase 1~3까지**다.

즉:
1. 프로젝트 골격
2. Engine 01
3. 블라인드 Benchmark Harness

Phase 4의 실제 유료 API 호출은 사용자가 API Key를 연결하고, 예상 호출 건수/비용을 확인한 뒤 승인하여 실행한다.

Production용 Engine 02 기본 모델은 Benchmark 완료 전 확정하지 않는다.
Engine 03은 schema/빈 골격까지만 미리 만들어도 된다.

---

## 15. Claude Code 작업 원칙

- 기존 파일이 있으면 먼저 구조를 검사하고 보존
- API key 하드코딩 금지
- 모든 판정은 근거값 병기
- 숫자 계산은 deterministic Python
- 기본 성과 Classification과 대표 위너(Primary Winner) 선정 레이어를 분리
- Primary Winner threshold가 아직 미정인 부분은 config/TODO로 남기고 임의 숫자를 만들지 않음
- LLM에게 광고 실적 계산을 맡기지 않음
- Engine 02/Benchmark API에 성과정보 전달 금지
- Provider 간 입력조건 동일 유지
- 원본 소재 파일명 변경 금지
- input 자동 삭제 금지
- 실패를 조용히 넘기지 말고 상태값 출력
- 규칙/threshold는 config 분리
- Excel은 감사 가능한 Methodology/Reference 포함
- 구현 불가능/불명확한 요구는 임의 대체하지 말고 TODO와 이유 보고
