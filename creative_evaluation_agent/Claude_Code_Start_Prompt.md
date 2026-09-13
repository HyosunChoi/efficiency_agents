# Claude Code 시작 프롬프트

다음 프로젝트를 구현해줘.


첨부한 `Creative_Evaluation_Agent_Build_Spec_V1.md`가 이 프로젝트의 기준 명세다.
명세에 없는 평가기준이나 비즈니스 규칙을 임의로 만들어내지 마.

우선 목표는 **Phase 1~3까지**다.

1. 프로젝트 골격 생성
2. Engine 01 — 광고 운영 데이터 기반 Performance Evaluation 완성
3. OpenAI vs Claude 블라인드 Benchmark Harness 완성

중요 원칙:
- Engine 01은 Python deterministic rule engine으로 구현
- Engine 02/Benchmark API에는 광고 실적을 절대 전달하지 않음
- 모든 최종 판정에는 판정 근거값을 함께 출력
- API 호출 전 예상 신규 분석 건수와 예상 비용을 표시하고 사용자 Y/N 승인을 반드시 받음
- 동일 asset은 hash + prompt/model/schema version 기준으로 cache 재사용
- input 폴더는 실행 후 자동 삭제하거나 이동하지 않음
- 원본 소재명은 변경하지 않음
- 블라인드 테스트에서는 `benchmark_asset_map.xlsx`로 원본↔Blind_ID를 관리하고 API에는 Blind_ID 파일만 전달
- Ground Truth는 두 provider의 예측 저장이 끝나기 전에는 비교 로직에서 읽지 않도록 분리
- API key는 환경변수/.env로 관리하고 코드에 하드코딩하지 않음
- OpenAI/Anthropic provider는 동일한 공통 schema를 반환하도록 adapter 구조로 작성
- Production용 Engine 02 기본 모델은 블라인드 Benchmark가 끝나기 전에는 확정하지 않음
- 실패나 애매한 매칭을 추정으로 해결하지 말고 CHECK/ASSET_NOT_FOUND/MULTIPLE_ASSET_MATCH 등의 상태로 남김

작업 순서:
A. 먼저 명세를 읽고 구현 계획과 생성/수정할 파일 목록을 제시해.
B. 프로젝트 폴더가 이미 존재하면 현재 파일 구조를 먼저 검사하고 기존 작업을 보존해.
C. Phase 1을 구현하고 최소 테스트를 실행해.
D. Phase 2를 구현하고 작은 fixture 데이터로 계산식을 검증해.
E. Phase 3 Benchmark Harness를 구현하되, 실제 API 호출은 하지 말고 dry-run까지 확인해.
F. 실제 API 호출 직전에는 멈추고, 현재 상태와 실행 방법, 필요한 API Key 환경변수, 예상 benchmark 실행 절차를 보고해.
G. 내가 승인하기 전에는 유료 API를 호출하지 마.

엑셀 산출물은 사람이 읽고 판정 이유를 감사할 수 있어야 한다.
코드의 결과값만 만들지 말고 Methodology/Reference 시트와 주요 판단근거 컬럼을 포함해.

작업 중 명세와 현실 데이터 구조가 충돌하면 임의로 해석하지 말고 문제를 보고하고 가능한 선택지를 제시해.
