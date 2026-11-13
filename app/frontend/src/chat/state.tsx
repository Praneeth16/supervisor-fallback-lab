import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from "react";
import { ARMS, type Arm, type HistoryMessage } from "../api";
import {
  chatApi,
  newId,
  streamChat,
  type Choice,
  type ConversationDetail,
  type ConversationInfo,
  type Feedback,
  type Final,
  type Mode,
  type Rating,
  type Step,
  type StreamEvent,
} from "../chatApi";

export interface Reply {
  arm: Arm;
  status: "streaming" | "done" | "error";
  turnId: string | null;
  steps: Step[];
  /** Text the supervisor is writing, or has just written. It becomes a step or the answer. */
  draft: string;
  draftDone: boolean;
  final: Final | null;
  saved: boolean;
  saveError: string | null;
  error: string | null;
  startedAt: number;
  feedback: Feedback | null;
}

export interface Exchange {
  seq: number;
  question: string;
  replies: Partial<Record<Arm, Reply>>;
}

export interface Conversation {
  id: string;
  mode: Mode;
  exchanges: Exchange[];
  preferences: Record<number, Choice>;
}

interface State {
  conversation: Conversation | null;
  mode: Mode;
  list: ConversationInfo[];
  listError: string | null;
}

type Action =
  | { type: "mode"; mode: Mode }
  | { type: "reset" }
  | { type: "open"; conversation: Conversation }
  | { type: "list"; list: ConversationInfo[] }
  | { type: "list-error"; error: string }
  | { type: "ask"; conversation: Conversation; question: string; arms: Arm[] }
  | { type: "event"; conversationId: string; seq: number; arm: Arm; event: StreamEvent }
  | { type: "fail"; conversationId: string; seq: number; arm: Arm; error: string }
  | { type: "feedback"; seq: number; arm: Arm; feedback: Feedback | null }
  | { type: "vote"; seq: number; choice: Choice | null };

const MODE_KEY = "lab-chat-mode";

function savedMode(): Mode {
  const value = window.localStorage.getItem(MODE_KEY);
  return value === "genie_one" || value === "custom_agent" || value === "compare" ? value : "custom_agent";
}

function upsert(steps: Step[], step: Step): Step[] {
  const index = steps.findIndex((s) => s.id === step.id);
  if (index < 0) return [...steps, step];
  const next = steps.slice();
  next[index] = step;
  return next;
}

function applyEvent(reply: Reply, event: StreamEvent): Reply {
  switch (event.event) {
    case "start":
      return { ...reply, turnId: event.turn_id };
    case "delta":
      return reply.draftDone
        ? { ...reply, draft: event.text, draftDone: false }
        : { ...reply, draft: reply.draft + event.text };
    case "message":
      return event.tool_result ? { ...reply, draft: "", draftDone: false } : { ...reply, draft: event.text, draftDone: true };
    case "step": {
      const steps = upsert(reply.steps, event.step);
      return event.step.kind === "note" ? { ...reply, steps } : { ...reply, steps, draft: "", draftDone: false };
    }
    case "final":
      return {
        ...reply,
        status: event.error && !event.answer ? "error" : "done",
        error: event.error,
        final: event,
        steps: event.steps,
        draft: "",
        draftDone: false,
        turnId: event.turn_id,
      };
    case "saved":
      return { ...reply, saved: true };
    case "save_error":
      return { ...reply, saveError: event.error };
    case "error":
      return { ...reply, status: "error", error: event.error };
  }
}

function mapReply(state: State, conversationId: string, seq: number, arm: Arm, change: (reply: Reply) => Reply): State {
  const conversation = state.conversation;
  if (!conversation || conversation.id !== conversationId) return state;
  const exchanges = conversation.exchanges.map((exchange) => {
    const reply = exchange.replies[arm];
    if (exchange.seq !== seq || !reply) return exchange;
    return { ...exchange, replies: { ...exchange.replies, [arm]: change(reply) } };
  });
  return { ...state, conversation: { ...conversation, exchanges } };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "mode":
      return { ...state, mode: action.mode };
    case "reset":
      return { ...state, conversation: null };
    case "open":
      return { ...state, conversation: action.conversation };
    case "list":
      return { ...state, list: action.list, listError: null };
    case "list-error":
      return { ...state, listError: action.error };
    case "ask": {
      const seq = action.conversation.exchanges.length + 1;
      const replies: Partial<Record<Arm, Reply>> = {};
      for (const arm of action.arms) {
        replies[arm] = {
          arm, status: "streaming", turnId: null, steps: [], draft: "", draftDone: false, final: null,
          saved: false, saveError: null, error: null, startedAt: Date.now(), feedback: null,
        }; // prettier-ignore
      }
      const exchange: Exchange = { seq, question: action.question, replies };
      return { ...state, conversation: { ...action.conversation, exchanges: [...action.conversation.exchanges, exchange] } };
    }
    case "event":
      return mapReply(state, action.conversationId, action.seq, action.arm, (reply) => applyEvent(reply, action.event));
    case "fail":
      return mapReply(state, action.conversationId, action.seq, action.arm, (reply) =>
        reply.status === "streaming" ? { ...reply, status: "error", error: action.error } : reply,
      );
    case "feedback":
      return state.conversation
        ? mapReply(state, state.conversation.id, action.seq, action.arm, (reply) => ({ ...reply, feedback: action.feedback }))
        : state;
    case "vote": {
      if (!state.conversation) return state;
      const preferences = { ...state.conversation.preferences };
      if (action.choice) preferences[action.seq] = action.choice;
      else delete preferences[action.seq];
      return { ...state, conversation: { ...state.conversation, preferences } };
    }
  }
}

function fromSaved(detail: ConversationDetail): Conversation {
  const exchanges = new Map<number, Exchange>();
  for (const turn of detail.turns) {
    const exchange = exchanges.get(turn.seq) ?? { seq: turn.seq, question: turn.question, replies: {} };
    exchange.replies[turn.arm] = {
      arm: turn.arm, status: turn.error && !turn.answer ? "error" : "done", turnId: turn.turn_id, steps: turn.steps,
      draft: "", draftDone: false, final: turn, saved: true, saveError: null, error: turn.error,
      startedAt: 0, feedback: turn.feedback,
    }; // prettier-ignore
    exchanges.set(turn.seq, exchange);
  }
  const ordered = [...exchanges.values()].sort((a, b) => a.seq - b.seq);
  const arms = new Set(detail.turns.map((turn) => turn.arm));
  const mode: Mode = detail.mode === "compare" || arms.size > 1 ? "compare" : (detail.turns[0]?.arm ?? "custom_agent");
  const preferences: Record<number, Choice> = {};
  for (const [seq, choice] of Object.entries(detail.preferences)) preferences[Number(seq)] = choice;
  return { id: detail.conversation_id, mode, exchanges: ordered, preferences };
}

function historyFor(conversation: Conversation, arm: Arm): HistoryMessage[] {
  const messages: HistoryMessage[] = [];
  for (const exchange of conversation.exchanges) {
    const answer = exchange.replies[arm]?.final?.answer;
    if (answer) {
      messages.push({ role: "user", content: exchange.question.slice(0, 8000) });
      messages.push({ role: "assistant", content: answer.slice(0, 8000) });
    }
  }
  return messages.slice(-20);
}

interface ChatValue extends State {
  busy: boolean;
  setMode: (mode: Mode) => void;
  reset: () => void;
  /** Returns the conversation id, or null when nothing was sent. `fresh` starts a new conversation. */
  ask: (question: string, fresh?: boolean) => string | null;
  open: (id: string) => Promise<void>;
  rate: (seq: number, arm: Arm, rating: Rating | null, reasons?: string[], comment?: string | null) => Promise<boolean>;
  vote: (seq: number, choice: Choice | null) => Promise<void>;
  reloadList: () => void;
}

const ChatContext = createContext<ChatValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    conversation: null,
    mode: savedMode(),
    list: [],
    listError: null,
  }));
  const stateRef = useRef(state);
  stateRef.current = state;
  const streams = useRef<AbortController[]>([]);

  const reloadList = useCallback(() => {
    chatApi
      .conversations()
      .then((list) => dispatch({ type: "list", list }))
      .catch((error: unknown) => dispatch({ type: "list-error", error: error instanceof Error ? error.message : String(error) }));
  }, []);

  useEffect(reloadList, [reloadList]);

  const stopStreams = useCallback(() => {
    for (const controller of streams.current) controller.abort();
    streams.current = [];
  }, []);

  const setMode = useCallback((mode: Mode) => {
    window.localStorage.setItem(MODE_KEY, mode);
    dispatch({ type: "mode", mode });
  }, []);

  const reset = useCallback(() => {
    stopStreams();
    dispatch({ type: "reset" });
  }, [stopStreams]);

  const open = useCallback(
    async (id: string) => {
      stopStreams();
      const detail = await chatApi.conversation(id);
      dispatch({ type: "open", conversation: fromSaved(detail) });
    },
    [stopStreams],
  );

  const ask = useCallback(
    (text: string, fresh = false) => {
      const question = text.trim();
      const current = stateRef.current;
      if (!question) return null;
      const existing = fresh ? null : current.conversation;
      const running = existing?.exchanges.some((exchange) =>
        Object.values(exchange.replies).some((reply) => reply.status === "streaming"),
      );
      if (running) return null;
      if (fresh) stopStreams();
      const conversation: Conversation = existing ?? {
        id: newId(),
        mode: current.mode,
        exchanges: [],
        preferences: {},
      };
      const arms = conversation.mode === "compare" ? ARMS : [conversation.mode];
      const seq = conversation.exchanges.length + 1;
      dispatch({ type: "ask", conversation, question, arms });
      let open = arms.length;
      for (const arm of arms) {
        const controller = new AbortController();
        streams.current.push(controller);
        streamChat(
          {
            arm,
            question,
            history: historyFor(conversation, arm),
            conversation_id: conversation.id,
            seq,
            mode: conversation.mode === "compare" ? "compare" : "single",
          },
          (event) => dispatch({ type: "event", conversationId: conversation.id, seq, arm, event }),
          controller.signal,
        )
          .then(() =>
            dispatch({ type: "fail", conversationId: conversation.id, seq, arm, error: "The answer stopped before it was finished." }),
          )
          .catch((error: unknown) => {
            if (controller.signal.aborted) return;
            const message = error instanceof Error ? error.message : String(error);
            dispatch({ type: "fail", conversationId: conversation.id, seq, arm, error: message });
          })
          .finally(() => {
            streams.current = streams.current.filter((c) => c !== controller);
            open -= 1;
            if (open === 0) reloadList();
          });
      }
      return conversation.id;
    },
    [reloadList, stopStreams],
  );

  const rate = useCallback(
    async (seq: number, arm: Arm, rating: Rating | null, reasons: string[] = [], comment: string | null = null) => {
      const reply = stateRef.current.conversation?.exchanges.find((e) => e.seq === seq)?.replies[arm];
      if (!reply?.turnId) return false;
      const before = reply.feedback;
      dispatch({ type: "feedback", seq, arm, feedback: rating ? { rating, reasons, comment } : null });
      try {
        const result = await chatApi.feedback(reply.turnId, rating ?? "none", reasons, comment);
        return result.mlflow_logged;
      } catch (error) {
        dispatch({ type: "feedback", seq, arm, feedback: before });
        throw error;
      }
    },
    [],
  );

  const vote = useCallback(async (seq: number, choice: Choice | null) => {
    const conversation = stateRef.current.conversation;
    const exchange = conversation?.exchanges.find((e) => e.seq === seq);
    if (!conversation || !exchange) return;
    const before = conversation.preferences[seq] ?? null;
    dispatch({ type: "vote", seq, choice });
    try {
      await chatApi.preference(conversation.id, seq, exchange.question.slice(0, 2000), choice ?? "none");
    } catch (error) {
      dispatch({ type: "vote", seq, choice: before });
      throw error;
    }
  }, []);

  const busy = Boolean(
    state.conversation?.exchanges.some((exchange) =>
      Object.values(exchange.replies).some((reply) => reply.status === "streaming"),
    ),
  );

  const value = useMemo(
    () => ({ ...state, busy, setMode, reset, ask, open, rate, vote, reloadList }),
    [state, busy, setMode, reset, ask, open, rate, vote, reloadList],
  );
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatValue {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChat needs a ChatProvider above it.");
  return value;
}
