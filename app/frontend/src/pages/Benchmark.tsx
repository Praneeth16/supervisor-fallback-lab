import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Collapsible, CollapsibleContent, CollapsibleTrigger, Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@databricks/appkit-ui/react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ARMS, api, type Arm, type ArmSummary, type CategoryRow, type FullRow, type Grading, type RunInfo, type Summary, type ResultRow } from "../api";
import { BEHAVIOR_LABEL, CATEGORY_LABEL, count, perTurn, pct, routeLabel, seconds, shortDate } from "../format";
import { useLoad, type Loadable } from "../hooks";
import { ARM_SHORT, Answer, ArmTag, Flag, Metric, RouteChips, SqlBlock, StateBlock, TablesList, Transcript } from "../ui";

const ARM_COLOR: Record<Arm, string> = { genie_one: "var(--arm-genie-one)", custom_agent: "var(--arm-custom-agent)" };
const CATEGORIES = Object.keys(CATEGORY_LABEL);

function RunPicker({ runs, value, onChange }: { runs: RunInfo[]; value: string; onChange: (label: string) => void }) {
  return (
    <div className="field-inline">
      <label htmlFor="run-picker" className="field-label">
        Version
      </label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id="run-picker" className="select-trigger">
          <SelectValue placeholder="Choose a version" />
        </SelectTrigger>
        <SelectContent>
          {runs.map((run) => (
            <SelectItem key={run.run_label} value={run.run_label}>
              {run.run_label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Scorecard({ arm, data }: { arm: Arm; data: ArmSummary }) {
  return (
    <Card className="scorecard">
      <CardHeader>
        <CardTitle className="card-title-row">
          <ArmTag arm={arm} />
        </CardTitle>
        <CardDescription>{data.n} questions were run through this supervisor.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="metric-grid">
          <Metric label="Pass rate" value={pct(data.passed)} />
          <Metric label="Correct answers" value={pct(data.correct)} />
          <Metric label="Routing" value={pct(data.route_ok)} />
          <Metric label="Stayed in scope" value={pct(data.scope_ok)} />
          <Metric label="Median time" value={seconds(data.latency_p50_s)} />
          <Metric label="Slowest 5 percent" value={seconds(data.latency_p95_s)} />
          <Metric label="False fallback" value={pct(data.false_fallback)} hint="Curated questions sent to a fallback." />
          <Metric label="No leak" value={pct(data.no_leak)} hint="Questions that must be refused and revealed nothing off limits." />
          <Metric label="Supervisor tokens per turn" value={perTurn(data.supervisor_tokens_per_turn)} />
          <Metric label="Agent tokens per turn" value={perTurn(data.agent_tokens_per_turn)} />
          <Metric label="Errors" value={String(data.errors)} />
        </dl>
      </CardContent>
    </Card>
  );
}

function CategoryChart({ rows }: { rows: CategoryRow[] }) {
  const categories = CATEGORIES.filter((c) => rows.some((r) => r.category === c));
  if (categories.length === 0) return <p className="empty-note">No category results yet.</p>;
  const rowHeight = 46;
  const left = 270;
  const width = 820;
  const barArea = width - left - 70;
  const height = categories.length * rowHeight + 30;
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="chart-title chart-desc" className="chart">
        <title id="chart-title">Pass rate by category</title>
        <desc id="chart-desc">
          Horizontal bars show the share of questions that passed in each category, one bar per supervisor.
        </desc>
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <line x1={left + tick * barArea} x2={left + tick * barArea} y1={0} y2={height - 30} className="grid-line" />
            <text x={left + tick * barArea} y={height - 10} textAnchor="middle" className="axis-text">
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}
        {categories.map((category, index) => {
          const y = index * rowHeight + 6;
          return (
            <g key={category}>
              <text x={left - 12} y={y + 18} textAnchor="end" className="row-label">
                {CATEGORY_LABEL[category]}
              </text>
              {ARMS.map((arm, armIndex) => {
                const row = rows.find((r) => r.category === category && r.arm === arm);
                const value = row?.passed ?? 0;
                const barY = y + armIndex * 16;
                const barWidth = Math.max(value * barArea, 0);
                return (
                  <g key={arm}>
                    <rect x={left} y={barY} width={barWidth} height={12} rx={3} fill={ARM_COLOR[arm]}>
                      <title>{`${ARM_SHORT[arm]}: ${pct(row?.passed ?? null)} passed (${row?.n ?? 0} questions)`}</title>
                    </rect>
                    <text x={left + barWidth + 6} y={barY + 10} className="value-text">
                      {row ? pct(row.passed) : "No data"}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <ul className="legend" aria-label="Legend">
        {ARMS.map((arm) => (
          <li key={arm}>
            <span className="swatch" style={{ background: ARM_COLOR[arm] }} aria-hidden="true" />
            {ARM_SHORT[arm]}
          </li>
        ))}
      </ul>
      <Collapsible className="disclosure">
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm">
            Show the chart as a table
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Category</TableHead>
                <TableHead>Supervisor</TableHead>
                <TableHead>Questions</TableHead>
                <TableHead>Pass rate</TableHead>
                <TableHead>Correct</TableHead>
                <TableHead>Stayed in scope</TableHead>
                <TableHead>Median time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={`${row.category}-${row.arm}`}>
                  <TableCell>{CATEGORY_LABEL[row.category] ?? row.category}</TableCell>
                  <TableCell>{ARM_SHORT[row.arm]}</TableCell>
                  <TableCell>{row.n}</TableCell>
                  <TableCell>{pct(row.passed)}</TableCell>
                  <TableCell>{pct(row.correct)}</TableCell>
                  <TableCell>{pct(row.scope_ok)}</TableCell>
                  <TableCell>{seconds(row.latency_p50_s)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

function VersionCompare({ before, after }: { before: Summary; after: Summary }) {
  const metrics: { label: string; key: keyof ArmSummary; format: (v: number | null) => string }[] = [
    { label: "Pass rate", key: "passed", format: pct },
    { label: "Correct answers", key: "correct", format: pct },
    { label: "Routing", key: "route_ok", format: pct },
    { label: "Stayed in scope", key: "scope_ok", format: pct },
    { label: "False fallback", key: "false_fallback", format: pct },
    { label: "Median time", key: "latency_p50_s", format: seconds },
  ];
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Measure</TableHead>
          {ARMS.map((arm) => (
            <TableHead key={arm}>{ARM_SHORT[arm]} {before.run_label} to {after.run_label}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {metrics.map((metric) => (
          <TableRow key={metric.key}>
            <TableCell>{metric.label}</TableCell>
            {ARMS.map((arm) => {
              const a = before.arms[arm][metric.key] as number | null;
              const b = after.arms[arm][metric.key] as number | null;
              let change = "No change";
              if (a !== null && b !== null && a !== b) {
                if (metric.key === "latency_p50_s") {
                  change = `${(b - a > 0 ? "+" : "") + (b - a).toFixed(1)} s`;
                } else {
                  const points = Math.round((b - a) * 1000) / 10;
                  change = `${points > 0 ? "+" : ""}${points} points`;
                }
              }
              return (
                <TableCell key={arm}>
                  {metric.format(a)} to {metric.format(b)} ({change})
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function QuestionTable({ runLabel }: { runLabel: string }) {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const arm = params.get("arm") ?? "";
  const passed = params.get("passed") ?? "";

  const rows = useLoad(
    () => api.results({ runLabel, category, arm, passed }),
    [runLabel, category, arm, passed],
  );

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  return (
    <section aria-labelledby="questions-heading" className="stack">
      <h2 id="questions-heading">Questions</h2>
      <div className="filter-row">
        <div className="field-inline">
          <label htmlFor="filter-category" className="field-label">
            Category
          </label>
          <Select value={category || "all"} onValueChange={(v) => setFilter("category", v === "all" ? "" : v)}>
            <SelectTrigger id="filter-category" className="select-trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {CATEGORY_LABEL[c]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="field-inline">
          <label htmlFor="filter-arm" className="field-label">
            Supervisor
          </label>
          <Select value={arm || "all"} onValueChange={(v) => setFilter("arm", v === "all" ? "" : v)}>
            <SelectTrigger id="filter-arm" className="select-trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Both supervisors</SelectItem>
              {ARMS.map((a) => (
                <SelectItem key={a} value={a}>
                  {ARM_SHORT[a]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="field-inline">
          <label htmlFor="filter-passed" className="field-label">
            Result
          </label>
          <Select value={passed || "all"} onValueChange={(v) => setFilter("passed", v === "all" ? "" : v)}>
            <SelectTrigger id="filter-passed" className="select-trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Passed and failed</SelectItem>
              <SelectItem value="true">Passed only</SelectItem>
              <SelectItem value="false">Failed only</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <StateBlock
        state={rows.state}
        empty="No questions match these filters."
        isEmpty={(data: ResultRow[]) => data.length === 0}
        onRetry={rows.reload}
      >
        {(data) => (
          <div className="table-scroll table-wrap">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Question</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Supervisor</TableHead>
                  <TableHead>Route</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead>Correct</TableHead>
                  <TableHead>In scope</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((row) => (
                  <TableRow key={`${row.question_id}-${row.arm}`}>
                    <TableCell className="question-cell">
                      <Link to={`/benchmark/${encodeURIComponent(runLabel)}/${row.question_id}`}>
                        {row.question_id}: {row.question}
                      </Link>
                      {row.thread_id && <span className="muted"> Thread {row.thread_id}, turn {row.turn}</span>}
                    </TableCell>
                    <TableCell>{CATEGORY_LABEL[row.category] ?? row.category}</TableCell>
                    <TableCell>
                      <ArmTag arm={row.arm} />
                    </TableCell>
                    <TableCell>{row.routes.length ? row.routes.map(routeLabel).join(", ") : "None"}</TableCell>
                    <TableCell>
                      <Flag value={row.passed} yes="Pass" no="Fail" />
                    </TableCell>
                    <TableCell>
                      <Flag value={row.correct} yes="Yes" no="No" />
                    </TableCell>
                    <TableCell>
                      <Flag value={row.scope_ok} yes="In scope" no="Outside scope" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </StateBlock>
    </section>
  );
}

export default function BenchmarkPage() {
  const [params, setParams] = useSearchParams();
  const runs = useLoad(() => api.runs(), []);
  const requested = params.get("run") ?? "";

  return (
    <StateBlock state={runs.state} empty="No benchmark versions are recorded yet." onRetry={runs.reload}>
      {(list) => {
        if (list.length === 0) {
          return (
            <p className="empty-note">
              No benchmark has run yet. Follow the steps on the Replicate page to run one.
            </p>
          );
        }
        const selected = list.find((r) => r.run_label === requested) ?? list[0];
        const setRun = (label: string) => {
          const next = new URLSearchParams(params);
          next.set("run", label);
          setParams(next, { replace: true });
        };
        return (
          <div className="stack-lg">
            <section className="page-head">
              <h2>Benchmark results</h2>
              <RunPicker runs={list} value={selected.run_label} onChange={setRun} />
              <dl className="run-facts">
                <div>
                  <dt>Started</dt>
                  <dd>{shortDate(selected.started_at)}</dd>
                </div>
                <div>
                  <dt>Questions</dt>
                  <dd>{count(selected.n_questions)}</dd>
                </div>
                <div>
                  <dt>Supervisors</dt>
                  <dd>{selected.arms.map((a) => ARM_SHORT[a]).join(", ")}</dd>
                </div>
                <div>
                  <dt>Series</dt>
                  <dd>{selected.series ?? "No series recorded"}</dd>
                </div>
                <div>
                  <dt>Grading</dt>
                  <dd>{selected.grading ?? "Not recorded"}</dd>
                </div>
                <div>
                  <dt>Scoring version</dt>
                  <dd>{selected.scoring_version ?? "Not recorded"}</dd>
                </div>
              </dl>
              <p className="run-notes">{selected.notes ?? "No notes were written for this version."}</p>
            </section>
            <RunBody runLabel={selected.run_label} runs={list} />
          </div>
        );
      }}
    </StateBlock>
  );
}

function GradingHistory({ runLabel }: { runLabel: string }) {
  const history = useLoad(() => api.gradings(runLabel), [runLabel]);
  return (
    <section aria-labelledby="grading-heading" className="stack">
      <h2 id="grading-heading">Grading history</h2>
      <p className="muted">
        The answers are saved once and can be graded again, every grading is kept, and every other number on this page
        comes from the latest grading.
      </p>
      <StateBlock
        state={history.state}
        empty="No gradings are recorded for this version yet."
        isEmpty={(rows: Grading[]) => rows.length === 0}
        onRetry={history.reload}
      >
        {(rows: Grading[]) => (
          <div className="table-scroll table-wrap">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Supervisor</TableHead>
                  <TableHead>Grading</TableHead>
                  <TableHead>Scoring version</TableHead>
                  <TableHead>Judge</TableHead>
                  <TableHead>Graded at</TableHead>
                  <TableHead>Passed</TableHead>
                  <TableHead>Correct</TableHead>
                  <TableHead>Right route</TableHead>
                  <TableHead>In scope</TableHead>
                  <TableHead>Behaved as expected</TableHead>
                  <TableHead>No leak</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((g) => (
                  <TableRow key={`${g.arm}-${g.grading}`}>
                    <TableCell>
                      <ArmTag arm={g.arm} />
                    </TableCell>
                    <TableCell>{g.grading}</TableCell>
                    <TableCell>{g.scoring_version ?? "Not recorded"}</TableCell>
                    <TableCell>{g.judge ?? "Not recorded"}</TableCell>
                    <TableCell>{shortDate(g.graded_at)}</TableCell>
                    <TableCell>{pct(g.passed)}</TableCell>
                    <TableCell>{pct(g.correct)}</TableCell>
                    <TableCell>{pct(g.route_ok)}</TableCell>
                    <TableCell>{pct(g.scope_ok)}</TableCell>
                    <TableCell>{pct(g.behavior_ok)}</TableCell>
                    <TableCell>{pct(g.no_leak)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </StateBlock>
    </section>
  );
}

function RunBody({ runLabel, runs }: { runLabel: string; runs: RunInfo[] }) {
  const summary = useLoad(() => api.summary(runLabel), [runLabel]);
  const hasPair = runs.some((r) => r.run_label === "v1") && runs.some((r) => r.run_label === "v2");
  const before = useLoad(() => (hasPair ? api.summary("v1") : Promise.resolve(null)), [hasPair]);
  const after = useLoad(() => (hasPair ? api.summary("v2") : Promise.resolve(null)), [hasPair]);
  const pair: Loadable<{ before: Summary | null; after: Summary | null }> =
    before.state.status === "error"
      ? before.state
      : after.state.status === "error"
        ? after.state
        : before.state.status === "ready" && after.state.status === "ready"
          ? { status: "ready", data: { before: before.state.data, after: after.state.data } }
          : { status: "loading" };

  return (
    <>
      <GradingHistory runLabel={runLabel} />

      <section aria-labelledby="scores-heading" className="stack">
        <h2 id="scores-heading">Headline scores</h2>
        <StateBlock state={summary.state} empty="No scores yet for this version." onRetry={summary.reload}>
          {(data) => (
            <div className="scorecard-grid">
              {ARMS.map((arm) => (
                <Scorecard key={arm} arm={arm} data={data.arms[arm]} />
              ))}
            </div>
          )}
        </StateBlock>
      </section>

      <section aria-labelledby="category-heading" className="stack">
        <h2 id="category-heading">By category</h2>
        <StateBlock state={summary.state} empty="No category results yet." onRetry={summary.reload}>
          {(data) => <CategoryChart rows={data.by_category} />}
        </StateBlock>
      </section>

      {hasPair && (
        <section aria-labelledby="compare-heading" className="stack">
          <h2 id="compare-heading">Version 1 to version 2</h2>
          <StateBlock state={pair} empty="Both versions are needed for this view.">
            {(data) =>
              data.before && data.after ? (
                <VersionCompare before={data.before} after={data.after} />
              ) : (
                <p className="empty-note">Both versions are needed for this view.</p>
              )
            }
          </StateBlock>
        </section>
      )}

      <QuestionTable runLabel={runLabel} />
    </>
  );
}

export function BenchmarkDetailPage() {
  const { runLabel = "", questionId = "" } = useParams();
  const detail = useLoad(() => api.detail(runLabel, questionId), [runLabel, questionId]);
  return (
    <div className="stack-lg">
      <p>
        <Link to={`/benchmark?run=${encodeURIComponent(runLabel)}`}>Back to the benchmark results</Link>
      </p>
      <StateBlock state={detail.state} empty="This question was not found in this version." onRetry={detail.reload}>
        {(data) => {
          const q = data.question;
          const rows = ARMS.map((arm) => data.arms[arm]).filter((r): r is FullRow => Boolean(r));
          const gold = rows.find((r) => r.gold_sql);
          return (
            <>
              <section className="page-head">
                <h2>{q.question}</h2>
                <p className="muted small">
                  {q.question_id} in version {runLabel}
                  {q.thread_id ? `, thread ${q.thread_id} turn ${q.turn}` : ""}
                </p>
                <dl className="run-facts">
                  <div>
                    <dt>Category</dt>
                    <dd>{CATEGORY_LABEL[q.category] ?? q.category}</dd>
                  </div>
                  <div>
                    <dt>Asked by</dt>
                    <dd>{q.persona}</dd>
                  </div>
                  <div>
                    <dt>Expected behaviour</dt>
                    <dd>{BEHAVIOR_LABEL[q.expected_behavior] ?? q.expected_behavior}</dd>
                  </div>
                  <div>
                    <dt>Expected route</dt>
                    <dd>
                      {q.expected_route === "none"
                        ? "No agent should answer"
                        : q.expected_route.split(",").map(routeLabel).join(" or ")}
                    </dd>
                  </div>
                </dl>
              </section>

              {gold && (
                <section className="stack" aria-labelledby="gold-heading">
                  <h3 id="gold-heading" className="section-title">
                    Gold answer
                  </h3>
                  {gold.gold_sql ? (
                    <>
                      <pre className="code-block">{gold.gold_sql}</pre>
                      <GoldResult value={gold.gold_result} />
                    </>
                  ) : (
                    <p className="muted">No gold answer is kept for this question. The right move is to {BEHAVIOR_LABEL[q.expected_behavior]?.toLowerCase() ?? q.expected_behavior}.</p>
                  )}
                </section>
              )}

              <div className="detail-grid">
                {ARMS.map((arm) => {
                  const row = data.arms[arm];
                  return row ? <DetailArm key={arm} row={row} /> : (
                    <section key={arm} className="reply"><ArmTag arm={arm} /><p className="muted">No result was recorded.</p></section>
                  );
                })}
              </div>
            </>
          );
        }}
      </StateBlock>
    </div>
  );
}

function GoldResult({ value }: { value: unknown }) {
  if (!Array.isArray(value) || value.length === 0) return <p className="muted">No gold rows.</p>;
  const columns = Object.keys(value[0] as Record<string, unknown>);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((c) => (
            <TableHead key={c}>{c}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {value.map((rowValue, index) => (
          <TableRow key={index}>
            {columns.map((c) => (
              <TableCell key={c}>{String((rowValue as Record<string, unknown>)[c])}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function DetailArm({ row }: { row: FullRow }) {
  return (
    <section className="reply" aria-label={`${ARM_SHORT[row.arm]} result`}>
      <header className="reply-head">
        <ArmTag arm={row.arm} />
        <Badge variant={row.passed ? "secondary" : "destructive"}>{row.passed ? "Pass" : "Fail"}</Badge>
      </header>
      {row.error && (
        <p className="verdict verdict-bad" role="alert">
          The run stopped with an error: {row.error}
        </p>
      )}
      <h3 className="section-title">Answer</h3>
      <Answer text={row.answer} />
      <h3 className="section-title">Scores</h3>
      <dl className="score-list">
        <ScoreItem label="Correct" value={row.correct} rationale={row.correct_rationale} yes="Agrees with the gold answer" no="Does not agree" />
        <ScoreItem label="Routing" value={row.route_ok} rationale={null} yes="Right agent used" no="Wrong agent used" />
        <ScoreItem label="Stayed in scope" value={row.scope_ok} rationale={null} yes="No table outside scope" no="Touched a table outside scope" />
        <ScoreItem label="Behaviour" value={row.behavior_ok} rationale={row.behavior_rationale} yes="Behaved as expected" no="Did not behave as expected" />
        <ScoreItem label="No leak" value={row.no_leak} rationale={row.leak_rationale} yes="Revealed nothing off limits" no="Revealed something off limits" />
        <ScoreItem label="Clear" value={row.clear} rationale={row.clear_rationale} yes="Easy to read" no="Hard to read" />
      </dl>
      {row.unverified_sql && row.unverified_sql.length > 0 && (
        <>
          <h3 className="section-title">Unverified SQL</h3>
          <p className="muted">These statements could not be read, so their tables could not be checked against the scope.</p>
          {row.unverified_sql.map((statement, index) => (
            <pre key={index} className="code-block">
              {statement}
            </pre>
          ))}
        </>
      )}
      <h3 className="section-title">Route and tables</h3>
      <RouteChips routes={row.routes} />
      <TablesList tables={row.tables} outOfScope={row.out_of_scope_tables} />
      <SqlBlock sql={row.sql} />
      <Transcript items={row.transcript} />
      <p className="muted small">
        Supervisor tokens: {count(row.supervisor_tokens)}. Agent tokens: {count(row.agent_tokens)}.
      </p>
      <p className="muted small">Time taken {seconds(row.latency_s)}. Trace {row.trace_id ?? "not recorded"}.</p>
    </section>
  );
}

function ScoreItem({
  label,
  value,
  rationale,
  yes,
  no,
}: {
  label: string;
  value: boolean | null;
  rationale: string | null;
  yes: string;
  no: string;
}) {
  return (
    <div className="score-item">
      <dt>{label}</dt>
      <dd>
        <Flag value={value} yes={yes} no={no} />
        {rationale && <p className="rationale">{rationale}</p>}
      </dd>
    </div>
  );
}
