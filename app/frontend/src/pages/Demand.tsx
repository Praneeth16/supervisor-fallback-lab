import type { Config } from "../api";
import { chatApi } from "../chatApi";
import { shortDate, tableName } from "../format";
import { useLoad } from "../hooks";
import { StateBlock } from "../ui";

function ownerText(owner: string): string {
  if (owner === "fallback") return "Fallback only";
  if (owner.startsWith("curated:")) return "Has a curated agent";
  return "Outside the scope";
}

export default function DemandPage({ config }: { config: Config }) {
  const demand = useLoad(() => chatApi.demand(), []);
  const rule = config.demand_rule;
  return (
    <div className="stack-lg">
      <section className="page-head">
        <h2>Fallback demand</h2>
        <p className="lede">
          Which tables people ask the fallback about. A table that many people keep asking about is a sign that it
          deserves its own curated Genie Agent, so the fallback stays small.
        </p>
      </section>
      <StateBlock
        state={demand.state}
        empty="No question has reached the fallback yet. Ask something in the chat that no curated agent covers, for example about campaigns or licence agreements."
        isEmpty={(data) => data.totals.questions === 0}
        onRetry={demand.reload}
      >
        {(data) => {
          const answered = Math.max(data.totals.questions, 1);
          const candidates = data.tables.filter((table) => table.candidate);
          return (
            <>
              <section className="stack">
                <h3 className="section-title">Where the questions went</h3>
                <div
                  className="split-bar"
                  role="img"
                  aria-label={`${data.totals.to_curated} to curated agents, ${data.totals.to_fallback} to the fallback, ${data.totals.no_agent} answered without an agent`}
                >
                  <span style={{ width: `${(data.totals.to_curated / answered) * 100}%`, background: "var(--foreground)" }} />
                  <span style={{ width: `${(data.totals.to_fallback / answered) * 100}%`, background: "var(--brand)" }} />
                  <span style={{ width: `${(data.totals.no_agent / answered) * 100}%`, background: "var(--line-strong)" }} />
                </div>
                <dl className="fact-row">
                  <div>
                    <dt>Questions asked</dt>
                    <dd className="num">{data.totals.questions}</dd>
                  </div>
                  <div>
                    <dt>Answered by curated agents</dt>
                    <dd className="num">{data.totals.to_curated}</dd>
                  </div>
                  <div>
                    <dt>Went to the fallback</dt>
                    <dd className="num">{data.totals.to_fallback}</dd>
                  </div>
                  <div>
                    <dt>No agent used</dt>
                    <dd className="num">{data.totals.no_agent}</dd>
                  </div>
                </dl>
              </section>

              <section className="stack">
                <h3 className="section-title">
                  {candidates.length === 0
                    ? "No table needs a curated agent yet"
                    : `${candidates.length} ${candidates.length === 1 ? "table is" : "tables are"} ready for a curated agent`}
                </h3>
                <p className="muted" style={{ maxWidth: "75ch" }}>
                  A table is flagged when at least {rule.min_questions} fallback questions from at least {rule.min_people}{" "}
                  {rule.min_people === 1 ? "person" : "people"} used it and no curated agent owns it. A question sent to both
                  assistants counts once.
                </p>
                {data.tables.length === 0 ? (
                  <p className="muted">The fallback has not read any table yet.</p>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Table</th>
                        <th className="right">Questions</th>
                        <th className="right">People</th>
                        <th className="right">Up</th>
                        <th className="right">Down</th>
                        <th>Last asked</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.tables.map((table) => (
                        <tr key={table.table}>
                          <td>
                            <code title={table.table}>{tableName(table.table)}</code>
                            <ul className="examples">
                              {table.examples.map((example) => (
                                <li key={example}>{example.length > 110 ? `${example.slice(0, 110)}…` : example}</li>
                              ))}
                            </ul>
                          </td>
                          <td className="right">{table.questions}</td>
                          <td className="right">{table.people}</td>
                          <td className="right">{table.up}</td>
                          <td className="right">{table.down}</td>
                          <td>{table.last_asked ? shortDate(table.last_asked.replace(" ", "T")) : "Unknown"}</td>
                          <td>
                            {table.candidate ? (
                              <span className="pill pill-brand">Build a curated agent</span>
                            ) : table.owner === "outside" ? (
                              <span className="pill pill-bad">{ownerText(table.owner)}</span>
                            ) : (
                              <span className="pill">{ownerText(table.owner)}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="panel stack">
                <h3 className="section-title" style={{ marginTop: 0 }}>
                  Get told when a table crosses the line
                </h3>
                <p className="muted" style={{ maxWidth: "75ch" }}>
                  The same numbers are in the view <code>fallback_demand</code> in the lab schema. Put a Databricks SQL
                  alert on it with the condition <code>candidate = true</code>, and the analytics team gets a message
                  when a table is ready. The setup guide has the query.
                </p>
              </section>
            </>
          );
        }}
      </StateBlock>
    </div>
  );
}
