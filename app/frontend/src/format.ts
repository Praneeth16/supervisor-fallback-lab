const number = new Intl.NumberFormat("en-US");

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "No data";
  return `${(value * 100).toFixed(1)}%`;
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "No data";
  return `${value.toFixed(1)} s`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not reported";
  return number.format(value);
}

export function perTurn(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not reported";
  return number.format(Math.round(value));
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "Unknown date";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function tableName(full: string): string {
  const parts = full.split(".");
  return parts.length >= 3 ? `${parts[1]}.${parts[2]}` : full;
}

export const CATEGORY_LABEL: Record<string, string> = {
  curated_subscriber: "Curated: subscribers and revenue",
  curated_content: "Curated: content and viewing",
  long_tail: "Long tail",
  cross_domain: "Cross domain",
  must_refuse: "Must refuse",
  ambiguous: "Ambiguous",
  routing_trap: "Routing trap",
  hard_sql: "Hard SQL",
  data_trap: "Data trap",
  multi_hop: "Multi hop",
  unanswerable: "Unanswerable",
  adversarial: "Adversarial",
};

export const ROUTE_LABEL: Record<string, string> = {
  "genie:subscribers_revenue": "Genie Agent: subscribers and revenue",
  "genie:content_viewing": "Genie Agent: content and viewing",
  genie_one: "Genie One",
  fallback_agent: "Custom fallback agent",
  sandbox: "Built-in sandbox",
  sql_mcp_server: "SQL MCP server",
};

export function routeLabel(route: string): string {
  return ROUTE_LABEL[route] ?? route;
}

export const BEHAVIOR_LABEL: Record<string, string> = {
  answer: "Answer",
  refuse: "Refuse",
  clarify: "Ask a question back",
  decline: "Say the data does not exist",
  partial: "Answer the allowed part and refuse the rest",
};
