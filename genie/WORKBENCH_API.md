# Genie Workbench API (deployed app: genie-workbench-hoshi)

Scripting reference for the Genie Workbench Databricks App. Source: `.vendor/databricks-genie-workbench` at commit `44a3705`.

## App

- URL: `https://genie-workbench-hoshi-0000000000000000.aws.databricksapps.com`
- Workspace: `https://example-workspace.cloud.databricks.com`
- Profile: `<profile>`
- Service principal: `app-4pc39m genie-workbench-hoshi`, client id `93c58500-a0f7-4ae9-9e0b-31f479c049cd`
- Optimization job: `587371608741439` (`gso-optimization-runner`), run_as the SP
- GSO state schema: `<catalog>.genie_space_optimizer`

## Auth for every call

Every example fetches a short-lived token inline. Never print it or store it.

```bash
GWB=https://genie-workbench-hoshi-0000000000000000.aws.databricksapps.com
# Bearer header used in each curl below:
#   -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"
```

Identity: the app reads the caller's identity from the forwarded token (OBO). Routes marked SP run as the service principal. Routes marked OBO need the caller to hold the Genie permission on the space.

Resolved on 2026-11-11. With the CLI token, `GET /api/spaces` returned `500 Failed to fetch Genie Agents from Databricks`. The app log showed `403 Forbidden: Invalid scope, required scopes: genie`, because the app's user scopes did not include `genie`. Adding the `genie` scope fixed it, and `make workbench` adds it. After that, `/api/create`, `/api/create/validate` and `/api/spaces/{id}/scan` were exercised successfully on 2026-11-11. Any other route that calls the Genie API on behalf of the user needs the same scope.

## Read-only checks (safe)

```bash
# Settings (no auth needed). Verified: HTTP 200.
curl -s -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  "$GWB/api/settings"

# Current user (OBO). Verified: HTTP 200, email user@example.com.
curl -s -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  "$GWB/api/auth/me"

# Auto-Optimize configured (SP). Verified: HTTP 200, {"configured":true,"issues":[]}.
curl -s -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  "$GWB/api/auto-optimize/health"

# Validate a serialized_space without creating anything. Same rules as the create wizard.
curl -s -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  "$GWB/api/create/validate" -d @payload.json
# Body: {"serialized_space": {...}}  Response: {"valid": bool, "errors": [...], "warnings": [...]}
```

Note: `/api/create/validate` takes `{"serialized_space": {...}}`, not the create body.

## 1. POST /api/create (creates a Genie space; OBO)

Do not run this without approval. It creates a Genie space in the workspace.

Request body (`CreateSpaceRequest`, `backend/models.py`):

| Field | Type | Required | Rules |
|---|---|---|---|
| `display_name` | string | yes | 1–255 chars, trimmed |
| `serialized_space` | object | yes | Genie config dict, schema below. The backend JSON-encodes it into the API's `serialized_space` string. |
| `parent_path` | string or null | no | Workspace folder, max 1000 chars. Default: `GENIE_TARGET_DIRECTORY` or `/Shared/`. Tried first, then the fallbacks. |
| `description` | string | no | Default `""`. Max 2000 chars. Default text if empty: "Genie Agent created by Genie Workbench". |

Response 200 (`CreateSpaceResponse`): `{"space_id": "...", "display_name": "...", "space_url": "https://<host>/genie/rooms/<space_id>"}`

Errors: 400 invalid config (`ValueError`), 403 no writable folder, 504 timeout (the backend then looks for the space by name and returns it if found), 500 other.

Minimal valid example (`<catalog>.<schema>.<table>` must be a real table the caller can read):

```json
{
  "display_name": "Example Sales Agent",
  "description": "Sales questions over one table",
  "parent_path": "/Shared/",
  "serialized_space": {
    "version": 2,
    "config": {
      "sample_questions": [
        {"id": "0a1b2c3d4e5f60718293a4b5c6d7e8f9", "question": ["What was total revenue last month?"]}
      ]
    },
    "data_sources": {
      "tables": [
        {
          "identifier": "<catalog>.<schema>.<table>",
          "description": ["Daily sales transactions"],
          "column_configs": [
            {"column_name": "amount", "description": ["Order amount in USD"], "enable_format_assistance": true}
          ]
        }
      ]
    },
    "instructions": {
      "text_instructions": [
        {"id": "1a2b3c4d5e6f708192a3b4c5d6e7f8a9", "content": ["## PURPOSE\n", "- Answer sales revenue questions.\n"]}
      ],
      "example_question_sqls": [
        {
          "id": "2b3c4d5e6f708192a3b4c5d6e7f8a9b0",
          "question": ["Total revenue by month"],
          "sql": ["SELECT date_trunc('month', order_date) AS m, SUM(amount) AS revenue\n", "FROM <catalog>.<schema>.<table>\n", "GROUP BY 1 ORDER BY 1"]
        }
      ],
      "sql_snippets": {
        "measures": [
          {"id": "3c4d5e6f708192a3b4c5d6e7f8a9b0c1", "display_name": "Total Revenue", "sql": ["SUM(<table_alias>.amount)"]}
        ]
      }
    },
    "benchmarks": {
      "questions": [
        {
          "id": "4d5e6f708192a3b4c5d6e7f8a9b0c1d2",
          "question": ["What is the average order amount?"],
          "answer": [{"format": "SQL", "content": ["SELECT AVG(amount) FROM <catalog>.<schema>.<table>"]}]
        }
      ]
    }
  }
}
```

Curl template (do not run without approval):

```bash
curl -s -X POST "$GWB/api/create" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  -d @create-payload.json
```

### serialized_space schema (version 2)

Source: `backend/references/schema.md`, `backend/genie_creator.py`, `backend/routers/create.py`.

Top-level keys: `version` (must be `2`), `config`, `data_sources`, `instructions`, `benchmarks`.

- `config.sample_questions[]`: `{id, question: [str]}`. Sorted by `id`.
- `data_sources.tables[]`: `{identifier: "cat.schema.table", description: [str], column_configs: [...]}`. Max 30 tables. Sorted by `identifier`. More than 10 gives a validate warning.
- `data_sources.tables[].column_configs[]`: `{column_name, description: [str], synonyms: [str], exclude: bool, enable_entity_matching: bool, enable_format_assistance: bool, get_example_values: bool, build_value_dictionary: bool}`. Sorted by `column_name`. `column_name` must be non-empty and unique per table. Set the matching flags to false when `exclude` is true. `enable_entity_matching` needs `enable_format_assistance`.
- `data_sources.metric_views[]`: same shape as tables. Sorted by `identifier`.
- `instructions.text_instructions[]`: at most 1. `content` is a list of strings, each ending in `\n`. Validate warns above 500 chars total.
- `instructions.example_question_sqls[]`: `{id, question: [str], sql: [str], usage_guidance?: [str], parameters?: [...]}`. Sorted by `id`. `parameters[]` is `{name, type_hint, description: [str], default_value: {values: [str]}}`, sorted by `name`. Filters have no `WHERE`.
- `instructions.sql_functions[]`: `{id, identifier: "cat.schema.fn", description}`. Sorted by `(id, identifier)`.
- `instructions.join_specs[]`: `{id, left: {identifier, alias?}, right: {identifier, alias?}, sql: [cond, "--rt=FROM_RELATIONSHIP_TYPE_..--"], comment?: [str], instruction?: [str]}`. Sorted by `id`.
  - `sql` must be exactly two elements. Element 1 is the backtick-quoted condition, e.g. `` `orders`.`customer_id` = `customers`.`customer_id` ``. Element 2 is the relationship tag, e.g. `--rt=FROM_RELATIONSHIP_TYPE_MANY_TO_ONE--`. Without the tag the API rejects the request. `_normalize_join_relationships` uppercases and underscores the type. Values seen in the repo: `MANY_TO_ONE`, `ONE_TO_ONE`.
  - `left` and `right` are required. A join spec without them is dropped silently.
  - `alias` is optional. The UI omits it.
- `instructions.sql_snippets`: `{filters: [], expressions: [], measures: []}`. Each item has `{id, display_name?, sql: [str], synonyms?: [str], instruction?: [str], comment?: [str]}`. `sql` must be non-empty (empty ones are dropped). Each sorts by `id`. Use table-qualified column refs (`alias.column`). Filters have no `WHERE`.
- `benchmarks.questions[]`: `{id, question: [str], answer: [{format: "SQL", content: [str]}]}`. Exactly one answer, format `"SQL"`. Sorted by `id`.

### ID and uniqueness rules

- Every ID is exactly 32 lowercase hex characters. Generate with `python3 -c 'import secrets;print(secrets.token_hex(16))'`. The create-agent validator (`create_agent_tools._ID_PATTERN`) enforces this. The create route does not.
- Question IDs are unique across `config.sample_questions` and `benchmarks.questions`.
- Instruction IDs are unique across `text_instructions`, `example_question_sqls`, `sql_functions`, `join_specs`, and all `sql_snippets` arrays.
- `(table, column_name)` is unique.

### Limits

- Max 100 instructions. Schema.md counts each example SQL, each function, and the text block. The validate route counts example SQLs plus snippets only, so it can pass a payload that the docs call over budget.
- Max 30 tables. Create silently truncates to 30. Validate returns an error.
- Strings in description, content, question, sql, instruction, synonyms, usage_guidance, comment: max 25,000 chars. Longer values are truncated.
- Arrays: max 10,000 items each.
- Serialized size: 3.5 MB. Above that, the backend only logs an error.

### What the backend does before sending (`_enforce_constraints` then `_clean_config`)

`_enforce_constraints`:
- Keeps only the first `text_instructions` entry.
- Caps tables at 30.
- Drops `filters`, `expressions`, and `measures` with empty `sql`.
- Drops `column_configs` with empty `column_name` and duplicates.
- Dedupes instruction IDs and question IDs across the arrays above. Later duplicates are dropped.
- Normalizes `--rt=` relationship tags.
- Drops `join_specs` missing `left` or `right`.
- Truncates oversize strings.

`_clean_config`:
- Drops null items in arrays.
- Wraps a string in a list for the string-array fields (`description`, `content`, `question`, `sql`, `instruction`, `synonyms`, `usage_guidance`, `comment`).
- Wraps a single object in a list for the object-array fields (`sample_questions`, `tables`, `metric_views`, `column_configs`, `text_instructions`, `example_question_sqls`, `sql_functions`, `join_specs`, `filters`, `expressions`, `measures`, `questions`, `answer`, `parameters`).
- Sorts arrays by the keys in the table above.

Send arrays. The wrapping is a fallback, not a contract.

## 2. POST /api/spaces/{space_id}/scan (IQ scan; OBO, needs CAN_EDIT)

No request body. The path param must match `^[0-9a-zA-Z_-]{1,128}$`.

Response (`ScanResult`):

```json
{
  "space_id": "01f1...",
  "score": 7,
  "total": 12,
  "maturity": "Ready to Optimize",
  "optimization_accuracy": null,
  "checks": [{"label": "Table descriptions", "passed": true, "detail": "3/3 tables", "severity": "pass"}],
  "findings": ["..."],
  "next_steps": ["..."],
  "warnings": [],
  "warning_next_steps": [],
  "scanned_at": "2026-11-11T14:00:00Z"
}
```

- `score`: 0–12.
- `maturity`: `Not Ready`, `Ready to Optimize`, or `Trusted`.
- `optimization_accuracy`: 0–1, or null if never optimized.
- The 12 checks (from `packages/genie-space-optimizer/src/genie_space_optimizer/iq_scan/scoring.py`) cover: agent description, table descriptions, column descriptions, text instructions (over 50 chars), join specifications, data source count 1–12, SQL guidance artifacts, entity/format matching, 10+ benchmark questions, column visibility, optimization workflow completed, optimization accuracy ≥ 85%.
- Scan also reads Unity Catalog descriptions for the tables before scoring.

```bash
curl -s -X POST "$GWB/api/spaces/<space_id>/scan" \
  -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"
```

Errors: 400 invalid input, 500 scan failed. Requires the caller to have EDIT on the space (403 otherwise).

## 3. POST /api/auto-optimize/trigger (starts the optimization job)

Body (`TriggerRequest`, `backend/routers/auto_optimize.py`):

| Field | Default | Rules |
|---|---|---|
| `space_id` | required | `^[0-9a-zA-Z_-]{1,128}$` |
| `apply_mode` | `"genie_config"` | `genie_config`, `uc_artifact`, or `both` |
| `levers` | job default `[1,2,3,4,5]` | list of ints |
| `llm_model` | null | serving endpoint; validated |
| `target_accuracy` | `0.90` | 0–1 |
| `max_attempts` | `3` | 1–20 |
| `benchmark_policy` | `"repair_allowed"` | `review_only` or `repair_allowed`. The UI sends `review_only`. |
| `workload_warehouse_ids` | `[]` | up to 20, each `^[0-9a-zA-Z_-]{1,128}$` |
| `enable_metric_view_suggestions` | `false` | |
| `mv_action_mode` | `"suggest_only"` | `suggest_only` or `create_and_attach` |
| `mv_min_confidence` | null | 0–100 |
| `mv_approved_suggestion_ids` | `[]` | up to 50 |
| `mv_consent` | null | required for `create_and_attach` |
| `mv_materialize` | `false` | |
| `operator_guidance` | null | max 4000 chars, per run, not saved |

Minimal body:

```json
{"space_id": "<space_id>", "benchmark_policy": "review_only", "apply_mode": "genie_config"}
```

Response:

```json
{"runId": "<uuid>", "jobRunId": 123, "jobUrl": "...", "status": "...", "targetAccuracy": 0.9, "maxAttempts": 3, "benchmarkPolicy": "review_only"}
```

Requirements before it will start:

1. Caller has EDIT on the space (OBO), or 403.
2. The app SP has CAN_MANAGE on the space. The job checks this (`trigger.py`) and raises 403 otherwise. The installer's step that grants this to all editable spaces was skipped here, so the main build must grant it per space.
3. The app SP can read every schema the space references. The job checks this with `missing_read_schemas` and raises 403 with the exact GRANTs. Per schema: `USE CATALOG` on the catalog, and `USE SCHEMA`, `SELECT`, `EXECUTE` on the schema. `GET /api/auto-optimize/permissions/{space_id}` returns the exact SQL.
4. Benchmarks: the generator aims for 30 (`TARGET_BENCHMARK_COUNT`, `config.py:300`). The hard floor is 15 valid questions after quality review (`MIN_VALID_BENCHMARK_COUNT`). Below 15, the run ends with `INSUFFICIENT_VALID_BENCHMARKS`. The IQ scan passes its benchmark check at 10 and gives full marks at 20.
5. The app must be configured: `GSO_CATALOG` and `GSO_JOB_ID` set (confirmed: `/api/auto-optimize/health` returns configured with no issues).
6. No run already in progress for the space. Otherwise 409.

Errors: 403 permission, 409 run in progress, 422 invalid value, 503 not configured, 500 job start failed.

Curl template:

```bash
curl -s -X POST "$GWB/api/auto-optimize/trigger" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  -d '{"space_id":"<space_id>","benchmark_policy":"review_only"}'
```

Follow-up:

```bash
# Run status (SP). Run ids are UUIDs.
curl -s -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  "$GWB/api/auto-optimize/runs/<run_id>/status"

# Exact GRANTs the SP still needs for this space (SP-side permission pre-check).
curl -s -H "Authorization: Bearer $(databricks auth token --profile <profile> | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')" \
  "$GWB/api/auto-optimize/permissions/<space_id>"
```

## Not covered or unverified

- `/api/auto-optimize/trigger` has not been called.
- The API doc in `docs/docs/reference/api.md` is a table only. Request shapes above come from the Pydantic models and routers.
