"""Creative Evaluation Agent — 진입점.

인자 없이 실행하면 대화형 메뉴 (run_agent.bat 더블클릭 기본 경로).
서브커맨드로도 실행 가능: `python run.py engine01`, `python run.py benchmark prepare` 등.
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from src.logging_setup import setup_logging

# Windows 콘솔 기본 codepage(cp949 등)에서 한글/이모지 출력 시 UnicodeEncodeError로
# 죽는 것을 방지 (run_agent.bat의 chcp 65001과 별개로, 직접 `python run.py` 실행 시에도 안전하게).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _run_engine01() -> None:
    from src.pipeline_engine01 import run_engine01

    result = run_engine01()
    print("\n[Engine 01 결과]")
    for k, v in result.items():
        print(f"  {k}: {v}")


def _run_benchmark_prepare() -> None:
    from src.benchmark_runner import run_prepare

    rows = run_prepare()
    print(f"\nBlind asset 준비 완료: 총 {len(rows)}건 (benchmark/mapping/benchmark_asset_map.xlsx)")


def _get_provider(name: str):
    if name == "openai":
        from src.providers.openai_client import OpenAIProvider

        return OpenAIProvider()
    if name == "claude":
        from src.providers.anthropic_client import AnthropicProvider

        return AnthropicProvider()
    raise ValueError(f"알 수 없는 provider: {name}")


def _run_benchmark_run(provider_name: str, dry_run: bool) -> None:
    from src.benchmark_runner import run_provider

    provider = _get_provider(provider_name)
    result = run_provider(provider, dry_run=dry_run)
    print(f"\n[Benchmark Run: {provider_name}] {result['status']}")


def _run_transcript_migrate(apply: bool) -> None:
    from src.providers.anthropic_client import AnthropicProvider
    from src.providers.openai_client import OpenAIProvider
    from src.transcript_migration import apply_migration, plan_migration, print_migration_report

    providers = [OpenAIProvider(), AnthropicProvider()]
    summary = plan_migration(providers)
    print_migration_report(summary)

    if not apply:
        print("\n(dry-run) 실제 마이그레이션은 수행되지 않았다. 적용하려면 --apply로 다시 실행.")
        return

    stats = apply_migration(summary)
    print(f"\n마이그레이션 적용 완료: {stats['migrated']}건 이관, {stats['left_for_reprocessing']}건은 재분석 대상으로 남김")
    print("이제 'benchmark run --provider openai/claude'를 실행하면 재분석 대상만 새로 처리된다.")


def _run_benchmark_compare() -> None:
    from src.comparison import export_comparison_report
    from src.ground_truth import GroundTruthLockedError

    try:
        path = export_comparison_report()
        print(f"\nComparison 리포트 생성 완료: {path}")
    except GroundTruthLockedError as e:
        print(f"\n[CHECK] {e}")


def _interactive_menu() -> None:
    while True:
        print("\n=== Creative Evaluation Agent ===")
        print("1) Engine 01 실행 (광고 운영 데이터 성과 평가)")
        print("2) Benchmark Harness: Blind 소재 준비")
        print("3) Benchmark Harness: OpenAI 분석 실행 (dry-run 우선 확인)")
        print("4) Benchmark Harness: Claude 분석 실행 (dry-run 우선 확인)")
        print("5) Benchmark Harness: Ground Truth Unlock + 비교 리포트")
        print("6) Benchmark Harness: Transcript 파이프라인 마이그레이션 (dry-run 우선 확인)")
        print("0) 종료")
        choice = input("선택: ").strip()

        if choice == "1":
            _run_engine01()
        elif choice == "2":
            _run_benchmark_prepare()
        elif choice in ("3", "4"):
            provider_name = "openai" if choice == "3" else "claude"
            dry = input("dry-run으로 먼저 확인하시겠습니까? [Y/N] ").strip().lower() == "y"
            _run_benchmark_run(provider_name, dry_run=dry)
        elif choice == "5":
            _run_benchmark_compare()
        elif choice == "6":
            _run_transcript_migrate(apply=False)
            if input("위 계획대로 실제 적용하시겠습니까? [Y/N] ").strip().lower() == "y":
                _run_transcript_migrate(apply=True)
        elif choice == "0":
            break
        else:
            print("잘못된 입력입니다.")


def main() -> None:
    load_dotenv()
    setup_logging()

    parser = argparse.ArgumentParser(description="Creative Evaluation Agent")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("engine01")

    bench = sub.add_parser("benchmark")
    bench_sub = bench.add_subparsers(dest="benchmark_command")
    bench_sub.add_parser("prepare")
    run_parser = bench_sub.add_parser("run")
    run_parser.add_argument("--provider", choices=["openai", "claude"], required=True)
    run_parser.add_argument("--dry-run", action="store_true")
    bench_sub.add_parser("compare")
    migrate_parser = bench_sub.add_parser("transcript-migrate")
    migrate_parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    if args.command == "engine01":
        _run_engine01()
    elif args.command == "benchmark":
        if args.benchmark_command == "prepare":
            _run_benchmark_prepare()
        elif args.benchmark_command == "run":
            _run_benchmark_run(args.provider, dry_run=args.dry_run)
        elif args.benchmark_command == "compare":
            _run_benchmark_compare()
        elif args.benchmark_command == "transcript-migrate":
            _run_transcript_migrate(apply=args.apply)
        else:
            print("benchmark 서브커맨드가 필요합니다: prepare | run | compare")
    else:
        _interactive_menu()


if __name__ == "__main__":
    sys.exit(main() or 0)
