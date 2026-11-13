export type Arm = "genie_one" | "custom_agent";
export const ARMS: Arm[] = ["genie_one", "custom_agent"];

export interface ArmInfo {
  key: Arm;
  label: string;
  fallback: string;
  endpoint: string;
  experiment_id: string | null;
}

export interface Scope {
  genie_agents: Record<string, string[]>;
  fallback: string[];
  join_only: string[];
  off_limits: string[];
}

export interface Config {
  brand: string;
  arms: ArmInfo[];
  scope: Scope;
  categories: string[];
  workspace_host: string | null;
  fixtures: boolean;
  demand_rule: { min_questions: number; min_people: number };
}

export interface RunInfo {
  run_label: string;
  started_at: string;
  notes: string | null;
  arms: Arm[];
  n_questions: number | null;
  series: string | null;
  grading: number | null;
  scoring_version: string | null;
  judge: string | null;
  benchmark: string | null;
}

export interface ArmSummary {
  n: number;
  passed: number | null;
  correct: number | null;
  route_ok: number | null;
  scope_ok: number | null;
  behavior_ok: number | null;
  clear: number | null;
  no_leak: number | null;
  latency_p50_s: number | null;
  latency_p95_s: number | null;
  errors: number;
  out_of_scope_touches: number;
  unverified_sql_turns: number;
  false_fallback: number | null;
  total_tokens: number | null;
  supervisor_tokens_per_turn: number | null;
  agent_tokens_per_turn: number | null;
}

export interface CategoryRow {
  category: string;
  arm: Arm;
  n: number;
  passed: number | null;
  correct: number | null;
  scope_ok: number | null;
  latency_p50_s: number | null;
}

export interface Summary {
  run_label: string | null;
  arms: Record<Arm, ArmSummary>;
  by_category: CategoryRow[];
}

export interface ResultRow {
  question_id: string;
  thread_id: string | null;
  turn: number | null;
  category: string;
  persona: string;
  question: string;
  arm: Arm;
  expected_route: string;
  expected_behavior: string;
  routes: string[];
  tables: string[];
  out_of_scope_tables: string[];
  latency_s: number | null;
  error: string | null;
  correct: boolean | null;
  route_ok: boolean | null;
  scope_ok: boolean | null;
  behavior_ok: boolean | null;
  clear: boolean | null;
  passed: boolean | null;
  grading: number;
  unverified_sql: string[] | null;
  no_leak: boolean | null;
  leak_rationale: string | null;
  supervisor_tokens: number | null;
  agent_tokens: number | null;
}

export interface FullRow extends ResultRow {
  run_id: string;
  run_label: string;
  answer: string;
  sql: string[];
  approvals: number;
  gold_sql: string | null;
  gold_result: unknown;
  correct_rationale: string | null;
  behavior_rationale: string | null;
  clear_rationale: string | null;
  transcript: TranscriptItem[];
  trace_id: string | null;
}

export interface QuestionDetail {
  question: Pick<
    ResultRow,
    "question_id" | "thread_id" | "turn" | "category" | "persona" | "question" | "expected_route" | "expected_behavior"
  >;
  arms: Partial<Record<Arm, FullRow>>;
}

export interface Touch {
  arm: Arm;
  table: string;
  questions: number;
  example_question_id: string;
}

export interface GatewayRow {
  arm: Arm;
  service_name: string | null;
  service_type: string | null;
  tool_name: string | null;
  calls: number;
  total_tokens: number | null;
  avg_latency_ms: number | null;
}

export interface Grading {
  arm: Arm;
  grading: number;
  scoring_version: string | null;
  judge: string | null;
  graded_at: string | null;
  n: number;
  passed: number | null;
  correct: number | null;
  route_ok: number | null;
  scope_ok: number | null;
  behavior_ok: number | null;
  no_leak: number | null;
}

export interface ScopeAuditRow {
  arm: Arm;
  client_application: string;
  statements: number;
  out_of_scope_statements: number;
  unanalysed_statements: number;
  out_of_scope_tables: string[];
}

export interface DirectTestCondition {
  condition: string;
  samples: number;
  ok: number;
  outcomes: Record<string, number>;
}

export interface DirectTestCell {
  samples: number;
  outcomes: Record<string, number>;
  out_of_scope_tables: string[];
  leak_hits: string[];
  rejected: number;
}

export interface DirectTestRequest {
  id: string;
  kind: string;
  question: string;
  cells: Record<string, DirectTestCell>;
}

export interface DirectTestResult {
  test_id: string | null;
  started_at: string | null;
  conditions: DirectTestCondition[];
  requests: DirectTestRequest[];
}

export interface Governance {
  run_label: string | null;
  touches: Touch[];
  sandbox_uses: Record<Arm, number>;
  refusals: Record<Arm, { expected: number; held: number }>;
  gateway: GatewayRow[];
}

export interface TranscriptItem {
  type: string;
  name?: string;
  arguments?: string;
  output?: unknown;
  role?: string;
  content?: unknown;
  [key: string]: unknown;
}

export interface AskReply {
  arm: Arm;
  answer: string;
  routes: string[];
  sql: string[];
  tables: string[];
  out_of_scope_tables: string[];
  latency_s: number;
  approvals: number;
  error: string | null;
  items: TranscriptItem[];
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = response.statusText || `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  config: () => request<Config>("/api/config"),
  runs: () => request<RunInfo[]>("/api/runs"),
  summary: (runLabel?: string) => request<Summary>(`/api/summary${query({ run_label: runLabel })}`),
  results: (filters: { runLabel?: string; arm?: string; category?: string; passed?: string }) =>
    request<ResultRow[]>(
      `/api/results${query({
        run_label: filters.runLabel,
        arm: filters.arm,
        category: filters.category,
        passed: filters.passed,
      })}`,
    ),
  detail: (runLabel: string, questionId: string) =>
    request<QuestionDetail>(`/api/results/${encodeURIComponent(runLabel)}/${encodeURIComponent(questionId)}`),
  gradings: (runLabel?: string) => request<Grading[]>(`/api/gradings${query({ run_label: runLabel })}`),
  scopeAudit: (runLabel?: string) => request<ScopeAuditRow[]>(`/api/scope-audit${query({ run_label: runLabel })}`),
  directTest: () => request<DirectTestResult>("/api/direct-test"),
  governance: (runLabel?: string) => request<Governance>(`/api/governance${query({ run_label: runLabel })}`),
  ask: (arm: Arm, question: string, history: HistoryMessage[]) =>
    request<AskReply>("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arm, question, history }),
    }),
};
