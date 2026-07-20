"""CLI: python -m tests.acceptance.run --mode mock|live."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import argparse
import json

from .models import AuditReport, load_cases
from .runner import AcceptanceRunner, timestamped_output_root


def _write_markdown(path: Path, reports: list[AuditReport]):
    grouped: dict[str, list[AuditReport]] = defaultdict(list)
    for report in reports:
        grouped[report.case_id].append(report)
    lines = ["# ConfigForge Acceptance Report", "", "| Case | Passed | Runs | Pass Rate |", "|---|---:|---:|---:|"]
    for case_id, case_reports in grouped.items():
        passed = sum(item.passed for item in case_reports)
        lines.append(f"| {case_id} | {passed} | {len(case_reports)} | {passed / len(case_reports):.0%} |")
    lines.extend(["", "## Findings", ""])
    for report in reports:
        lines.append(f"### {report.case_id} / run {report.run_index}: {'PASS' if report.passed else 'FAIL'}")
        lines.append("")
        if report.findings:
            for finding in report.findings:
                lines.append(f"- `{finding.severity}` `{finding.code}` `{finding.path}`: {finding.message}")
        else:
            lines.append("- No findings.")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run ConfigForge output acceptance tests")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--cases", default=str(Path(__file__).with_name("cases.json")))
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--tag", action="append", dest="tags")
    parser.add_argument("--repeat", type=int, default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    output_root = Path(args.output).resolve() if args.output else timestamped_output_root(project_root)
    cases = [case for case in load_cases(args.cases) if args.mode in case.modes]
    if args.case_ids:
        cases = [case for case in cases if case.id in set(args.case_ids)]
    if args.tags:
        requested_tags = set(args.tags)
        cases = [case for case in cases if requested_tags.intersection(case.tags)]
    if not cases:
        raise SystemExit("No acceptance cases matched the selection")

    runner = AcceptanceRunner(project_root, output_root, args.mode)
    reports = []
    for case in cases:
        repeat = args.repeat if args.repeat is not None else case.repeat
        for run_index in range(1, repeat + 1):
            report = runner.run_case(case, run_index)
            reports.append(report)
            print(f"[{ 'PASS' if report.passed else 'FAIL' }] {case.id} run={run_index} findings={len(report.findings)}")

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "report.json").write_text(
        json.dumps([item.to_dict() for item in reports], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown(output_root / "report.md", reports)
    passed = sum(item.passed for item in reports)
    print(f"Acceptance summary: {passed}/{len(reports)} passed")
    print(f"Report: {output_root / 'report.md'}")
    raise SystemExit(0 if passed == len(reports) else 1)


if __name__ == "__main__":
    main()
