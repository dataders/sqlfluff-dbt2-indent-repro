# SQLFluff dbt2 repeated-loop indentation repro

A synthetic, offline reproduction of an `LT02` source-fix cycle in the experimental dbt2 templater from [sqlfluff/sqlfluff#8854](https://github.com/sqlfluff/sqlfluff/pull/8854), with the Parquet companion changes in [alanmcruickshank/sqlfluff#4](https://github.com/alanmcruickshank/sqlfluff/pull/4).

The core and plugin are pinned to public commit `907eb031eab029a4f62fc9074fbe39193bfa967e`. This does not establish that released SQLFluff versions have this bug.

## Run

Requires [uv](https://docs.astral.sh/uv/). No dbt installation, warehouse, credentials or private repository access is required.

```sh
git clone https://github.com/dataders/sqlfluff-dbt2-indent-repro.git
cd sqlfluff-dbt2-indent-repro
uv sync --locked
uv run --locked python repro.py
uv run --locked python repro.py --all-cases
uv run --locked pytest -q
```

To make the unresolved idempotence check fail explicitly:

```sh
uv run --locked python repro.py --assert-idempotent
# Expected exit status: 1
```

The regular tests characterize the known bug and passing controls, so they pass when the recorded behavior is reproduced. `results.json` contains the source states and results from the latest run.

## Small example

[`example.sql`](example.sql) contains two nested loops. Both loops need repeated execution in this reproduction:

```sql
SELECT
    {% for column in ['a', 'b'] %}
    COALESCE(
        {% for value in [1, 2] %}
        {{ value }}{% if not loop.last %},{% endif %}
        {% endfor %}
    ) AS {{ column }}{% if not loop.last %},{% endif %}
    {% endfor %}
```

The unmodified dbt2 adapter repeatedly changes indentation between zero and four spaces on the value line. The built-in Jinja templater stabilizes after one fix pass. So does the raw rendered SQL.

## Isolation

Every path uses rule `LT02`, Snowflake dialect and SQLFluff's Python parser. The built-in Jinja render and recorded producer render match apart from the terminal newline, which the producer strips.

| Case | dbt2 adapter | Built-in Jinja | Raw rendered SQL | Diagnostic normalization |
| --- | --- | --- | --- | --- |
| Nested repeated loops | Two-state cycle | Stable after first pass | Stable after first pass | Stable after first pass |
| Only one outer iteration | Stable after first pass | Stable after first pass | Stable after first pass | Stable after first pass |
| Only one inner iteration | Stable after first pass | Stable after first pass | Stable after first pass | Stable after first pass |
| Nested loops without inner conditional | Two-state cycle | Stable after first pass | Stable after first pass | Stable after first pass |
| Nested loops without outer conditional | Two-state cycle | Stable after first pass | Stable after first pass | Stable after first pass |
| Direct COALESCE with one loop | Stable | Stable after first pass | Stable after first pass | Stable after first pass |

“Stable” means the next fresh render/recording produces no further source edits. It does not assert identical formatting across templaters.

### First incorrect translation

The adapter [converts each `loop_iteration` event into a `block_start` slice](https://github.com/dataders/sqlfluff/blob/907eb031eab029a4f62fc9074fbe39193bfa967e/plugins/sqlfluff-templater-dbt2/sqlfluff_templater_dbt2/trace.py#L247).

SQLFluff's lexer [already recognizes a backward source jump following a block boundary](https://github.com/dataders/sqlfluff/blob/907eb031eab029a4f62fc9074fbe39193bfa967e/src/sqlfluff/core/parser/lexer.py#L385) as a loop transition. It keeps the loop context active rather than processing that boundary as a final close. The additional `block_start` then opens another indentation context.

The diagnostic control removes only the `block_start` slices corresponding to repeated-loop events **after conversion**. It changes no producer event, source text, rendered SQL, raw slice or SQLFluff core code. This removes the cycle in all six cases.

This places the demonstrated defect in the dbt2 adapter's translation to SQLFluff slices. A producer change is not needed to resolve this reproduction. Broader producer conformance is outside its scope.

### Production-fix boundary

`convert(..., normalize_iterations=True)` is a diagnostic ablation, not a production adapter patch. The adapter's static `_validate_blocks()` also assumes a globally balanced start/end sequence; SQLFluff's loop-back handling is control-flow dependent. A production change must reconcile both translation and validation, with coverage for break/continue, recursive loops, skipped bodies and captured output.

## Recorded fixtures and provenance

All SQL/Jinja here was authored as synthetic examples. There are no project queries, warehouse data, credentials or machine paths.

The fixtures record inputs to the adapter's `trace_to_templated_file()` function from an experimental Rust dbt producer using protocol 2, associated with the public render-trace API proposal [dbt-labs/dbt#16870](https://github.com/dbt-labs/dbt/pull/16870). That producer is not bundled or needed to replay the issue. Stock dbt 2.0.12 is not claimed to export these traces.

Source, rendered SQL and ordered events are preserved. Machine paths, invocation identities and build-version metadata were normalized; the ingestion timestamp was removed. The version string `2.0.12+experimental.trace` is a normalized label, not a released build identifier.

The JSON files are **converter-input recordings**, not supported CLI JSON sidecars. They isolate the mapping/fixing layer rather than testing Parquet I/O or live compilation.

- `baseline/pass-1.json` through `pass-4.json`: fresh producer recordings for successive unmodified-adapter fix passes.
- `normalized/pass-1.json` and `pass-2.json`: fresh recordings before and after the diagnostic normalization's first fix pass. The second pass makes no further edits.

The converter receives the same original producer events in both paths. Its additional repeated-loop slices are removed only in the diagnostic control.
