"""Replay synthetic producer traces through the pinned SQLFluff dbt2 adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlfluff.core import FluffConfig, Linter
from sqlfluff.core.linter.common import RenderedFile
from sqlfluff.core.templaters.base import TemplatedFile
from sqlfluff.core.templaters.jinja import JinjaTemplater
from sqlfluff_templater_dbt2.trace import trace_to_templated_file

ROOT = Path(__file__).parent
CASES = (
    "nested",
    "one_column",
    "one_value",
    "no_inner_conditional",
    "no_outer_conditional",
    "direct_coalesce",
)


def config(templater: str = "jinja") -> FluffConfig:
    return FluffConfig(
        configs={
            "core": {
                "dialect": "snowflake",
                "templater": templater,
                "rules": "LT02",
                "use_rust_parser": False,
            }
        }
    )


def load_trace(case: str, variant: str, phase: int) -> dict[str, Any]:
    path = ROOT / "fixtures" / case / variant / f"pass-{phase}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def convert(trace: dict[str, Any], normalize_iterations: bool = False) -> TemplatedFile:
    result = trace_to_templated_file(trace, trace["source"], trace["filename"])
    if not normalize_iterations:
        return result
    # Diagnostic ablation only. These fixtures are ASCII, so byte and character
    # offsets coincide. No producer event, source text or rendered SQL is changed.
    assert trace["source"].isascii() and trace["rendered"].isascii()
    markers = {
        (e["source_start"], e["source_end"], e["rendered_start"], e["rendered_end"])
        for e in trace["events"]
        if e["kind"] == "loop_iteration"
    }
    sliced = [
        s
        for s in result.sliced_file
        if not (
            s.slice_type == "block_start"
            and (
                s.source_slice.start,
                s.source_slice.stop,
                s.templated_slice.start,
                s.templated_slice.stop,
            )
            in markers
        )
    ]
    return type(result)(
        source_str=result.source_str,
        fname=result.fname,
        templated_str=result.templated_str,
        sliced_file=sliced,
        raw_sliced=result.raw_sliced,
    )


def fix_mapping(mapped: TemplatedFile) -> tuple[str, bool]:
    cfg = config()
    linter = Linter(config=cfg)
    packet = RenderedFile(
        [mapped], [], cfg, {}, mapped.fname, "utf8", mapped.source_str
    )
    parsed = linter.parse_rendered(packet)
    result = linter.lint_parsed(parsed, linter.get_rulepack(), fix=True)
    errors = [e for e in result.get_violations() if e.rule_code() != "LT02"]
    if errors or result.tree is None:
        raise AssertionError(f"Unexpected parse/templater errors: {errors}")
    return result.fix_string()


def replay(case: str, variant: str, phases: int) -> dict[str, Any]:
    states: list[str] = []
    changed: list[bool] = []
    for phase in range(1, phases + 1):
        trace = load_trace(case, variant, phase)
        if states:
            assert states[-1] == trace["source"], "Capture does not continue prior fix"
        else:
            states.append(trace["source"])
        fixed, did_change = fix_mapping(convert(trace, variant == "normalized"))
        states.append(fixed)
        changed.append(did_change)
    return {
        "changed": changed,
        "two_state_cycle": (
            len(states) >= 5
            and states[1] == states[3]
            and states[2] == states[4]
            and states[1] != states[2]
        ),
        "states": states,
    }


def jinja_control(source: str) -> dict[str, Any]:
    states = [source]
    changed = []
    for _ in range(2):
        mapped, errors = JinjaTemplater().process(
            in_str=states[-1],
            fname="example.sql",
            config=config(),
        )
        assert not errors
        fixed, did_change = fix_mapping(mapped)
        states.append(fixed)
        changed.append(did_change)
    return {"changed": changed, "states": states}


def raw_control(rendered: str) -> dict[str, Any]:
    linter = Linter(config=config("raw"))
    states = [rendered]
    changed = []
    for _ in range(2):
        result = linter.lint_string(states[-1], fix=True)
        assert all(e.rule_code() == "LT02" for e in result.get_violations())
        fixed, did_change = result.fix_string()
        states.append(fixed)
        changed.append(did_change)
    return {"changed": changed}


def investigate(case: str) -> dict[str, Any]:
    trace = load_trace(case, "baseline", 1)
    builtin, errors = JinjaTemplater().process(
        in_str=trace["source"],
        fname="example.sql",
        config=config(),
    )
    assert not errors
    # The producer strips the terminal newline. Apart from that, both renderers
    # produce the same SQL for every fixture in this repository.
    assert builtin.templated_str.rstrip("\n") == trace["rendered"].rstrip("\n")
    return {
        "case": case,
        "dbt2": replay(case, "baseline", 4),
        "diagnostic_normalization": replay(case, "normalized", 2),
        "builtin_jinja": jinja_control(trace["source"]),
        "raw_rendered_sql": raw_control(trace["rendered"]),
        "iteration_events": sum(e["kind"] == "loop_iteration" for e in trace["events"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-cases", action="store_true")
    parser.add_argument(
        "--assert-idempotent",
        action="store_true",
        help="Exit 1 if the unmodified dbt2 path keeps editing",
    )
    args = parser.parse_args()
    results = [investigate(case) for case in (CASES if args.all_cases else ("nested",))]
    (ROOT / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    for r in results:
        print(r["case"])
        for name in (
            "dbt2",
            "builtin_jinja",
            "raw_rendered_sql",
            "diagnostic_normalization",
        ):
            print(f"  {name}: changed={r[name]['changed']}")
        print(f"  dbt2 two-state cycle: {r['dbt2']['two_state_cycle']}")
    if args.assert_idempotent and any(
        r["dbt2"]["changed"][1:] != [False] * 3 for r in results
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
