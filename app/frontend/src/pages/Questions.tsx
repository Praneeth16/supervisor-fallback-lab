import { useSearchParams } from "react-router-dom";
import { ARMS, api, request, type Arm } from "../api";
import { ARM_NAME } from "../chat/ReplyView";
import { BEHAVIOR_LABEL, CATEGORY_LABEL, routeLabel } from "../format";
import { useLoad } from "../hooks";
import { Flag, StateBlock } from "../ui";

interface Question {
  question_id: string;
  thread_id: string | null;
  turn: number | null;
  category: string;
  persona: string | null;
  question: string;
  expected_route: string | null;
  expected_behavior: string | null;
  gold_sql: string | null;
  gold_result: Record<string, unknown>[] | string | null;
  passed: Record<Arm, boolean | null>;
}

function Truth({ result }: { result: Question["gold_result"] }) {
  if (!Array.isArray(result) || result.length === 0) return null;
  const columns = Object.keys(result[0]);
  const rows = result.slice(0, 5);
  return (
    <div style={{ marginTop: "0.5rem", overflowX: "auto" }}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column}>{row[column] === null ? "" : String(row[column])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {result.length > rows.length && <p className="muted small">{result.length - rows.length} more rows</p>}
    </div>
  );
}

export default function QuestionsPage() {
  const [params, setParams] = useSearchParams();
  const runs = useLoad(() => api.runs(), []);
  const chosen = params.get("run") ?? undefined;
  const questions = useLoad(() => request<Question[]>(`/api/questions${chosen ? `?run_label=${encodeURIComponent(chosen)}` : ""}`), [chosen]);

  return (
    <div className="stack-lg">
      <section className="page-head">
        <h2>Questions and ground truth</h2>
        <p className="lede">
          A benchmark is a fixed set of questions, each with reference SQL whose result is the ground truth. You bring
          the questions, or a larger model drafts them with their SQL and a person who knows the data checks each one.
          Both assistants are then graded against the same answers.
        </p>
        {runs.state.status === "ready" && runs.state.data.length > 0 && (
          <div className="field-inline">
            <label htmlFor="run" className="field-label">
              Question set of version
            </label>
            <select
              id="run"
              className="text-input"
              style={{ width: "auto", minWidth: "14rem" }}
              value={chosen ?? runs.state.data[0].run_label}
              onChange={(event) => setParams({ run: event.target.value })}
            >
              {runs.state.data.map((run) => (
                <option key={run.run_label} value={run.run_label}>
                  {run.run_label}
                  {run.benchmark ? ` (${run.benchmark.split("/").pop()})` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
      </section>

      <section className="panel stack">
        <h3 className="section-title" style={{ marginTop: 0 }}>
          Add questions
        </h3>
        <ul className="plain-list">
          <li>
            <strong>Bring your own.</strong> Write them in a file in the format of <code>eval/benchmark_holdout.yaml</code>,
            one question with its reference SQL each.
          </li>
          <li>
            <strong>Draft with a larger model.</strong> <code>make gold FROM=questions.txt</code> lets the model named
            under <code>models.gold_builder</code> write and run reference SQL for your questions.{" "}
            <code>make gold FROM=context</code> also drafts the questions from the table descriptions.
          </li>
          <li>
            <strong>Start from real use.</strong> <code>make gold FROM=feedback</code> takes the chat answers people
            gave a thumbs up.
          </li>
        </ul>
        <p className="muted" style={{ maxWidth: "75ch" }}>
          Every drafted question is marked as not reviewed. The evaluation refuses a file that still has such questions,
          so a model never grades against an answer no person has checked.
        </p>
      </section>

      <StateBlock
        state={questions.state}
        empty="No benchmark has been run yet. Run make eval, then the questions and their reference answers appear here."
        isEmpty={(data) => data.length === 0}
        onRetry={questions.reload}
      >
        {(data) => (
          <section className="stack">
            <h3 className="section-title">
              {data.length} questions, {data.filter((q) => q.gold_sql).length} with reference SQL
            </h3>
            <div style={{ overflowX: "auto" }}>
            <table className="data-table table-wrap">
              <thead>
                <tr>
                  <th>Question</th>
                  <th>Expected</th>
                  <th>Ground truth</th>
                  {ARMS.map((arm) => (
                    <th key={arm}>{ARM_NAME[arm].replace(" fallback", "")}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((q) => (
                  <tr key={q.question_id}>
                    <td style={{ minWidth: "16rem", maxWidth: "34ch" }}>
                      {q.question}
                      <p className="quote">
                        {q.question_id}, {CATEGORY_LABEL[q.category] ?? q.category}
                      </p>
                    </td>
                    <td style={{ minWidth: "13rem" }}>
                      {q.expected_route ? q.expected_route.split(/[,|]/).map((r) => routeLabel(r.trim())).join(" or ") : "Any"}
                      <p className="quote">{BEHAVIOR_LABEL[q.expected_behavior ?? "answer"] ?? q.expected_behavior}</p>
                    </td>
                    <td style={{ minWidth: "18rem" }}>
                      {q.gold_sql ? (
                        <details>
                          <summary>
                            Reference SQL
                            {Array.isArray(q.gold_result) ? `, ${q.gold_result.length} ${q.gold_result.length === 1 ? "row" : "rows"}` : ""}
                          </summary>
                          <pre className="code-block">{q.gold_sql}</pre>
                        </details>
                      ) : (
                        <span className="muted">Judged on behaviour, no SQL needed</span>
                      )}
                      <Truth result={q.gold_result} />
                    </td>
                    {ARMS.map((arm) => (
                      <td key={arm}>
                        <Flag value={q.passed[arm]} yes="Passed" no="Failed" />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </section>
        )}
      </StateBlock>
    </div>
  );
}
