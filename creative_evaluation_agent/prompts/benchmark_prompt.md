# Benchmark Harness Prompt Wrapper (schema_version: v1)

이 파일은 `creative_analysis_prompt.md`의 taxonomy를 **변경 없이 그대로** 사용한다.
OpenAI/Claude 두 provider 비교 목적의 블라인드 벤치마크이므로, 아래 문구만 시스템 메시지 앞에 추가하고
taxonomy/schema는 절대 다르게 만들지 않는다 (Provider 간 입력조건 동일 유지 원칙, §9/§15).

## 추가 컨텍스트 (benchmark 전용)

이것은 두 개의 다른 AI 모델이 동일한 광고 소재를 얼마나 잘 관찰/판단하는지 비교하기 위한
블라인드 벤치마크의 일부다. 이 소재가 실제로 어떤 성과를 냈는지는 절대 알려주지 않으며,
비교 대상 모델이 무엇인지도 알려주지 않는다. 오직 `creative_analysis_prompt.md`에 정의된
taxonomy와 동일한 스키마로만 응답하라.

전달되는 자료는 `benchmark_asset_map.xlsx`에 의해 원본과 분리된 `Blind_ID` 파일뿐이다.
원본 매체/소재명/성과 데이터는 어떤 경로로도 포함되지 않는다.

## Taxonomy / 출력 형식

`creative_analysis_prompt.md`의 "관찰 taxonomy (V1)", "예상 반응 판단", "출력 형식" 섹션을 그대로 적용한다.
