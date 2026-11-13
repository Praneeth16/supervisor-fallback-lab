import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@databricks/appkit-ui/react";
import { Link, useSearchParams } from "react-router-dom";
import { ARMS, api, type Arm, type DirectTestResult, type DirectTestRequest, type Governance, type RunInfo, type Scope, type ScopeAuditRow } from "../api";
import { count, tableName } from "../format";
import { useLoad } from "../hooks";
import { ARM_SHORT, ArmTag, Metric, StateBlock } from "../ui";

function ScopeTable({ scope }: { scope: Scope }) {
  const genieRows = Object.entries(scope.genie_agents).map(([agent, domains]) => ({
    name: `Genie Agent: ${agent.replace(/_/g, " ")}`,
    domains,
    rule: "Answers only from its own schemas. Both supervisors send curated questions here.",
  }));
  const rows = [
    ...genieRows,
    { name: "Fallback scope", domains: scope.fallback, rule: "Questions the curated agents cannot answer may read these schemas." },
    { name: "Join only", domains: scope.join_only, rule: "The fallback may join these schemas to its own tables or to each other. Questions that one curated agent can answer stay with that agent." },
    { name: "Off limits", domains: scope.off_limits, rule: "Visible to users in the lab, but never allowed for any agent." },
  ];
  return (
    <div className="table-scroll table-wrap">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Group</TableHead>
            <TableHead>Schemas</TableHead>
            <TableHead>Rule</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.name}>
              <TableCell>{row.name}</TableCell>
              <TableCell>{row.domains.length ? row.domains.join(", ") : "None"}</TableCell>
              <TableCell>{row.rule}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const ENFORCEMENT: { arm: Arm; text: string }[] = [
  {
    arm: "genie_one",
    text: "Scope is set by instructions and skills in Genie One. Nothing in code stops a table read, so the agent is trusted to follow the rules. This is what the touches below measure.",
  },
  {
    arm: "custom_agent",
    text: "The custom agent parses every SQL statement before it runs and rejects any table outside the allowlist. A blocked read never reaches the warehouse.",
  },
];

const CONDITION_LABEL: Record<string, string> = {
  genie_one_scope_line: "Genie One, scope line sent",
  genie_one_no_scope_line: "Genie One, scope line missing",
  custom_agent_guard_on: "Custom agent, guard on",
  custom_agent_guard_off: "Custom agent, guard off",
};

const OUTCOME_LABEL: Record<string, string> = {
  declined: "Declined",
  blocked_by_guard: "Blocked by guard",
  ran_in_scope: "Ran in scope",
  ran_out_of_scope: "Ran out of scope",
  leaked_without_query: "Leaked without a query",
  error: "Error",
  timeout: "Timed out",
};

const FLAGGED_OUTCOMES = ["ran_out_of_scope", "leaked_without_query"];

function describeOutcomes(outcomes: Record<string, number>, samples: number): string {
  const parts = Object.entries(outcomes).map(([outcome, total]) => ({ label: OUTCOME_LABEL[outcome] ?? outcome, total }));
  if (parts.length === 1) return `${parts[0].label} ${parts[0].total} of ${samples}`;
  return parts.map((part, index) => `${index === 0 ? part.label : part.label.toLowerCase()} ${part.total}`).join(", ");
}

function RequestLabel({ request }: { request: DirectTestRequest }) {
  return (
    <>
      {request.kind === "control" && <p className="muted small">Control: in scope, should be answered</p>}
      {request.question}
    </>
  );
}

const CLIENT_LABELS: Record<string, string> = {
  "Databricks SQL Genie Space": "Curated Genie Agents",
  DatabricksGenie: "Genie One",
  "Databricks SQL MCP": "SQL MCP server (custom agent)",
};

function DirectTest() {
  const direct = useLoad(() => api.directTest(), []);
  return (
    <section className="stack" aria-labelledby="direct-heading">
      <h2 id="direct-heading">Each fallback on its own</h2>
      <p className="muted">
        In the benchmark, the supervisor refuses most out of scope requests before a fallback is called. This test sends
        the same kind of request straight to each fallback. Genie One is tested twice: once with the scope line the
        supervisor sends, and once without it, as if the supervisor had forgotten. Each request is sent several times.
      </p>
      <StateBlock
        state={direct.state}
        empty="The direct test has not been run yet. Run eval/redteam.py to fill this table."
        onRetry={direct.reload}
        isEmpty={(result: DirectTestResult) => result.requests.length === 0}
      >
        {(result: DirectTestResult) => (
          <div className="table-scroll table-wrap">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Request</TableHead>
                  {result.conditions.map((condition) => (
                    <TableHead key={condition.condition}>
                      {CONDITION_LABEL[condition.condition] ?? condition.condition}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.requests.map((request) => (
                  <TableRow key={request.id}>
                    <TableCell>
                      <RequestLabel request={request} />
                    </TableCell>
                    {result.conditions.map((condition) => {
                      const cell = request.cells[condition.condition];
                      if (!cell) return <TableCell key={condition.condition}>Not run</TableCell>;
                      const flagged = Object.keys(cell.outcomes).some((outcome) => FLAGGED_OUTCOMES.includes(outcome));
                      return (
                        <TableCell key={condition.condition} className={flagged ? "cell-warning" : undefined}>
                          <p>{describeOutcomes(cell.outcomes, cell.samples)}</p>
                          {cell.out_of_scope_tables.length > 0 && (
                            <p className="small">
                              Tables: <code>{cell.out_of_scope_tables.map(tableName).join(", ")}</code>
                            </p>
                          )}
                          {cell.leak_hits.length > 0 && (
                            <p className="small">
                              Names leaked: <code>{cell.leak_hits.join(", ")}</code>
                            </p>
                          )}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <ul className="muted small">
              {result.conditions.map((condition) => (
                <li key={condition.condition}>
                  {CONDITION_LABEL[condition.condition] ?? condition.condition}: {condition.ok} of {condition.samples}{" "}
                  samples had an acceptable outcome.
                </li>
              ))}
            </ul>
          </div>
        )}
      </StateBlock>
    </section>
  );
}

function ScopeAudit({ runLabel }: { runLabel: string }) {
  const audit = useLoad(() => api.scopeAudit(runLabel), [runLabel]);
  return (
    <section className="stack" aria-labelledby="audit-heading">
      <h2 id="audit-heading">What really ran</h2>
      <p className="muted">
        These are the statements the agents ran in this version, taken from the query history and checked against the
        scope. They show what ran, which can differ from what an answer said.
      </p>
      <StateBlock
        state={audit.state}
        empty="The execution check has not been run for this version. Run make verify-scope LABEL=<label>."
        onRetry={audit.reload}
        isEmpty={(rows: ScopeAuditRow[]) => rows.length === 0}
      >
        {(rows: ScopeAuditRow[]) => (
          <div className="table-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Supervisor</TableHead>
                  <TableHead>Ran by</TableHead>
                  <TableHead>Statements checked</TableHead>
                  <TableHead>Out of scope statements</TableHead>
                  <TableHead>Statements that could not be analysed</TableHead>
                  <TableHead>Out of scope tables</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={`${row.arm}-${row.client_application}`}
                    className={row.out_of_scope_statements > 0 ? "row-flagged" : undefined}
                  >
                    <TableCell>
                      <ArmTag arm={row.arm} />
                    </TableCell>
                    <TableCell>{CLIENT_LABELS[row.client_application] ?? row.client_application}</TableCell>
                    <TableCell>{count(row.statements)}</TableCell>
                    <TableCell>{count(row.out_of_scope_statements)}</TableCell>
                    <TableCell>{count(row.unanalysed_statements)}</TableCell>
                    <TableCell>
                      {row.out_of_scope_tables.length === 0 ? (
                        "None"
                      ) : (
                        <code>{row.out_of_scope_tables.map(tableName).join(", ")}</code>
                      )}
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

export default function GovernancePage() {
  const [params, setParams] = useSearchParams();
  const runs = useLoad(() => api.runs(), []);
  const config = useLoad(() => api.config(), []);
  const requested = params.get("run") ?? "";

  return (
    <StateBlock state={runs.state} empty="No benchmark versions are recorded yet." onRetry={runs.reload}>
      {(list: RunInfo[]) => {
        if (list.length === 0) {
          return <p className="empty-note">Governance numbers appear after the first benchmark run.</p>;
        }
        const selected = list.find((r) => r.run_label === requested)?.run_label ?? list[0].run_label;
        return (
          <div className="stack-lg">
            <section className="page-head">
              <h2>Scope checks</h2>
              <p className="lede">
                Both supervisors share the same curated agents. The question here is what happens when a question falls
                through to the fallback, and whether either supervisor reads a table it should not.
              </p>
              <div className="field-inline">
                <label htmlFor="gov-run" className="field-label">
                  Version
                </label>
                <Select
                  value={selected}
                  onValueChange={(label) => {
                    const next = new URLSearchParams(params);
                    next.set("run", label);
                    setParams(next, { replace: true });
                  }}
                >
                  <SelectTrigger id="gov-run" className="select-trigger">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {list.map((r) => (
                      <SelectItem key={r.run_label} value={r.run_label}>
                        {r.run_label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </section>
            <GovernanceBody runLabel={selected} scope={config.state.status === "ready" ? config.state.data.scope : null} />
          </div>
        );
      }}
    </StateBlock>
  );
}

function GovernanceBody({ runLabel, scope }: { runLabel: string; scope: Scope | null }) {
  const gov = useLoad(() => api.governance(runLabel), [runLabel]);

  return (
    <>
      <section className="stack" aria-labelledby="scope-heading">
        <h2 id="scope-heading">The scope</h2>
        {scope ? <ScopeTable scope={scope} /> : <p className="empty-note">The scope could not be loaded.</p>}
        <h3 className="section-title">How each supervisor enforces it</h3>
        <ul className="enforcement">
          {ENFORCEMENT.map((item) => (
            <li key={item.arm}>
              <ArmTag arm={item.arm} /> <p>{item.text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="stack" aria-labelledby="touch-heading">
        <h2 id="touch-heading">Tables touched outside the scope</h2>
        <StateBlock state={gov.state} empty="No governance numbers for this version yet." onRetry={gov.reload}>
          {(data: Governance) =>
            data.touches.length === 0 ? (
              <p className="empty-note">No table outside the scope was touched in this version.</p>
            ) : (
              <div className="table-scroll">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Supervisor</TableHead>
                      <TableHead>Table</TableHead>
                      <TableHead>Questions</TableHead>
                      <TableHead>Example</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.touches.map((touch) => (
                      <TableRow key={`${touch.arm}-${touch.table}`} className="row-flagged">
                        <TableCell>
                          <ArmTag arm={touch.arm} />
                        </TableCell>
                        <TableCell>
                          <code title={touch.table}>{tableName(touch.table)}</code>
                        </TableCell>
                        <TableCell>{touch.questions}</TableCell>
                        <TableCell>
                          <Link to={`/benchmark/${encodeURIComponent(runLabel)}/${touch.example_question_id}`}>
                            {touch.example_question_id}
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )
          }
        </StateBlock>
      </section>

      <section className="stack" aria-labelledby="refusal-heading">
        <h2 id="refusal-heading">Refusals and sandbox use</h2>
        <StateBlock state={gov.state} empty="No refusal numbers for this version yet." onRetry={gov.reload}>
          {(data: Governance) => (
            <div className="scorecard-grid">
              {ARMS.map((arm) => (
                <div key={arm} className="card-plain">
                  <ArmTag arm={arm} />
                  <dl className="metric-grid">
                    <Metric
                      label="Refusals held"
                      value={`${data.refusals[arm].held} of ${data.refusals[arm].expected}`}
                      hint="Questions that should be refused and were."
                    />
                    <Metric
                      label="Built-in sandbox uses"
                      value={count(data.sandbox_uses[arm])}
                      hint="Questions where the supervisor ran SQL itself instead of delegating."
                    />
                  </dl>
                </div>
              ))}
            </div>
          )}
        </StateBlock>
      </section>

      <DirectTest />

      <ScopeAudit runLabel={runLabel} />

      <section className="stack" aria-labelledby="gateway-heading">
        <h2 id="gateway-heading">Unity Gateway usage</h2>
        <p className="muted">Calls, tokens and time by service and tool for each supervisor. A blank token count means the service does not report tokens.</p>
        <StateBlock state={gov.state} empty="No gateway usage recorded for this version yet." onRetry={gov.reload} isEmpty={(d: Governance) => d.gateway.length === 0}>
          {(data: Governance) => (
            <div className="table-scroll">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Supervisor</TableHead>
                    <TableHead>Service</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Tool</TableHead>
                    <TableHead>Calls</TableHead>
                    <TableHead>Tokens</TableHead>
                    <TableHead>Average time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.gateway.map((g, index) => (
                    <TableRow key={`${g.arm}-${g.service_name}-${g.tool_name}-${index}`}>
                      <TableCell>
                        <ArmTag arm={g.arm} />
                      </TableCell>
                      <TableCell>
                        <code>{g.service_name ?? "Unknown"}</code>
                      </TableCell>
                      <TableCell>{g.service_type ? g.service_type.replace("_", " ").toLowerCase() : "Unknown"}</TableCell>
                      <TableCell>{g.tool_name ?? "Not named"}</TableCell>
                      <TableCell>{count(g.calls)}</TableCell>
                      <TableCell>{count(g.total_tokens)}</TableCell>
                      <TableCell>{g.avg_latency_ms === null ? "No data" : `${g.avg_latency_ms} ms`}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="muted small">
                {ARMS.map((arm) => `${ARM_SHORT[arm]} made ${count(data.gateway.filter((g) => g.arm === arm).reduce((s, g) => s + g.calls, 0))} calls`).join(". ")}.
              </p>
            </div>
          )}
        </StateBlock>
      </section>
    </>
  );
}
