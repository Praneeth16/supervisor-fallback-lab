import { request, type Arm, type HistoryMessage } from "./api";

export type Mode = Arm | "compare";

export interface Step {
  id: string;
  kind: "note" | "call" | "progress";
  route: string | null;
  title: string;
  detail: string | null;
  status: "running" | "done" | "failed";
  t: number;
  duration_s: number | null;
  sql: string[];
  tables: string[];
  link: string | null;
  result?: string | null;
  facts?: { tables: string[]; steps: string[]; blocked: number; identity: string | null; tokens: number | null };
}

export interface Final {
  answer: string;
  routes: string[];
  sql: string[];
  tables: string[];
  out_of_scope_tables: string[];
  latency_s: number | null;
  approvals: number;
  error: string | null;
  trace_id: string | null;
  supervisor_tokens: number;
  steps: Step[];
}

export type StreamEvent =
  | { event: "start"; turn_id: string; conversation_id: string; arm: Arm }
  | { event: "delta"; text: string }
  | { event: "message"; text: string; tool_result: boolean }
  | { event: "step"; step: Step }
  | ({ event: "final"; turn_id: string; conversation_id: string } & Final)
  | { event: "saved"; turn_id: string }
  | { event: "save_error"; turn_id: string; error: string }
  | { event: "error"; error: string };

export type Rating = "up" | "down";

export interface Feedback {
  rating: Rating;
  reasons: string[];
  comment: string | null;
}

export interface SavedTurn extends Final {
  turn_id: string;
  conversation_id: string;
  arm: Arm;
  mode: "single" | "compare";
  seq: number;
  question: string;
  created_at: string;
  feedback: Feedback | null;
}

export interface ConversationInfo {
  conversation_id: string;
  title: string;
  mode: "single" | "compare";
  arms: Arm[];
  started_at: string;
  last_at: string;
  questions: number;
}

export interface ConversationDetail {
  conversation_id: string;
  mode: "single" | "compare";
  turns: SavedTurn[];
  preferences: Record<string, Choice>;
}

export type Choice = Arm | "same";

export interface Me {
  email: string;
  name: string;
}

export interface FeedbackSummary {
  arms: Record<
    Arm,
    { answers: number; rated: number; up: number; down: number; up_rate: number | null; down_reasons: Record<string, number> }
  >;
  preference: Record<Choice, number>;
  people: { user_email: string; questions: number; up: number; down: number; votes: Record<Choice, number> }[];
  recent: {
    turn_id: string;
    conversation_id: string;
    arm: Arm;
    question: string;
    answer: string;
    rating: Rating;
    reasons: string[];
    comment: string | null;
    rated_by: string;
    rated_at: string | null;
    routes: string[];
  }[];
  totals: { answers: number; ratings: number; votes: number };
}

export interface DemandTable {
  table: string;
  owner: string;
  questions: number;
  people: number;
  arms: Arm[];
  up: number;
  down: number;
  last_asked: string | null;
  examples: string[];
  candidate: boolean;
}

export interface Demand {
  tables: DemandTable[];
  rule: { min_questions: number; min_people: number };
  totals: { questions: number; to_fallback: number; to_curated: number; no_agent: number; candidates: number };
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function newId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export interface ChatRequest {
  arm: Arm;
  question: string;
  history: HistoryMessage[];
  conversation_id: string;
  seq: number;
  mode: "single" | "compare";
}

/** Ask one supervisor and hand every event of the answer stream to `onEvent`. */
export async function streamChat(body: ChatRequest, onEvent: (event: StreamEvent) => void, signal: AbortSignal) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    let detail = `The server answered with status ${response.status}.`;
    try {
      const parsed = (await response.json()) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as StreamEvent);
      }
      cut = buffer.indexOf("\n\n");
    }
  }
}

export const chatApi = {
  me: () => request<Me>("/api/me"),
  conversations: () => request<ConversationInfo[]>("/api/chat/conversations"),
  conversation: (id: string) => request<ConversationDetail>(`/api/chat/conversations/${id}`),
  feedback: (turnId: string, rating: Rating | "none", reasons: string[] = [], comment: string | null = null) =>
    request<{ ok: boolean; mlflow_logged: boolean }>("/api/feedback", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ turn_id: turnId, rating, reasons, comment }),
    }),
  preference: (conversationId: string, seq: number, question: string, choice: Choice | "none") =>
    request<{ ok: boolean }>("/api/preference", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ conversation_id: conversationId, seq, question, choice }),
    }),
  feedbackSummary: () => request<FeedbackSummary>("/api/feedback/summary"),
  demand: () => request<Demand>("/api/demand"),
};
