import { Alert, AlertDescription, AlertTitle, Badge, Button, Collapsible, CollapsibleContent, CollapsibleTrigger, Skeleton } from "@databricks/appkit-ui/react";
import ReactMarkdown from "react-markdown";
import type { Arm, TranscriptItem } from "./api";
import type { Loadable } from "./hooks";
import { routeLabel, tableName } from "./format";

export const ARM_SHORT: Record<Arm, string> = { genie_one: "Supervisor A", custom_agent: "Supervisor B" };
export const ARM_FALLBACK: Record<Arm, string> = {
  genie_one: "Fallback: Genie One",
  custom_agent: "Fallback: custom agent",
};

export function ArmTag({ arm }: { arm: Arm }) {
  return <span className={`arm-tag arm-${arm}`}>{ARM_SHORT[arm]}</span>;
}

export function Flag({ value, yes = "Yes", no = "No", good = true }: { value: boolean | null; yes?: string; no?: string; good?: boolean }) {
  if (value === null) return <span className="muted">Not scored</span>;
  const positive = value === good;
  return (
    <span className={positive ? "verdict verdict-good" : "verdict verdict-bad"}>
      {value ? yes : no}
    </span>
  );
}

export function StateBlock<T>({
  state,
  empty,
  isEmpty,
  children,
  onRetry,
}: {
  state: Loadable<T>;
  empty: string;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => React.ReactNode;
  onRetry?: () => void;
}) {
  if (state.status === "loading") {
    return (
      <div className="state-loading" role="status" aria-live="polite">
        <span className="visually-hidden">Loading</span>
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <Alert variant="destructive" role="alert">
        <AlertTitle>This panel could not load</AlertTitle>
        <AlertDescription>
          {state.error} {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>Try again</Button>}
        </AlertDescription>
      </Alert>
    );
  }
  if (isEmpty?.(state.data)) {
    return <p className="empty-note">{empty}</p>;
  }
  return <>{children(state.data)}</>;
}

export function RouteChips({ routes }: { routes: string[] }) {
  if (routes.length === 0) return <p className="muted">No agent was used.</p>;
  return (
    <ul className="chip-list" aria-label="Route taken">
      {routes.map((route, index) => (
        <li key={`${route}-${index}`}>
          <Badge variant="outline">{routeLabel(route)}</Badge>
        </li>
      ))}
    </ul>
  );
}

export function TablesList({ tables, outOfScope }: { tables: string[]; outOfScope: string[] }) {
  if (tables.length === 0) return <p className="muted">No tables were read.</p>;
  return (
    <ul className="table-list">
      {tables.map((table) => {
        const flagged = outOfScope.includes(table);
        return (
          <li key={table} className={flagged ? "table-flagged" : undefined}>
            <code title={table}>{tableName(table)}</code>
            {flagged && <span className="flag-text">Outside the agreed scope</span>}
          </li>
        );
      })}
    </ul>
  );
}

export function SqlBlock({ sql, label = "SQL run" }: { sql: string[]; label?: string }) {
  return (
    <Collapsible className="disclosure">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm">
          {label} ({sql.length})
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        {sql.length === 0 ? (
          <p className="muted">No SQL was run.</p>
        ) : (
          sql.map((statement, index) => (
            <pre key={index} className="code-block">
              {statement}
            </pre>
          ))
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

function describeItem(item: TranscriptItem): { title: string; body: string } {
  if (item.type === "function_call") {
    return { title: `Called ${item.name ?? "a tool"}`, body: item.arguments ?? "" };
  }
  if (item.type === "function_call_output") {
    return { title: "Tool returned", body: typeof item.output === "string" ? item.output : JSON.stringify(item.output) };
  }
  if (item.type === "message") {
    const content = item.content as { text?: string }[] | string | undefined;
    const text = typeof content === "string" ? content : (content ?? []).map((part) => part.text ?? "").join("");
    return { title: "Supervisor replied", body: text };
  }
  if (item.type === "mcp_approval_request") {
    return { title: `Approval asked for ${item.name ?? "a tool"}`, body: item.arguments ?? "" };
  }
  if (item.type === "mcp_approval_response") {
    return { title: "Approval given", body: "" };
  }
  return { title: item.type, body: JSON.stringify(item).slice(0, 400) };
}

export function Transcript({ items }: { items: TranscriptItem[] }) {
  return (
    <Collapsible className="disclosure">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm">
          Step by step ({items.length} steps)
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        {items.length === 0 ? (
          <p className="muted">No steps were recorded.</p>
        ) : (
          <ol className="transcript">
            {items.map((item, index) => {
              const { title, body } = describeItem(item);
              return (
                <li key={index}>
                  <strong>{title}</strong>
                  {body && <pre className="code-block">{body}</pre>}
                </li>
              );
            })}
          </ol>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function Answer({ text }: { text: string }) {
  if (!text.trim()) return <p className="muted">No answer text was returned.</p>;
  return (
    <div className="answer">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}

export function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
      {hint && <p className="metric-hint">{hint}</p>}
    </div>
  );
}
