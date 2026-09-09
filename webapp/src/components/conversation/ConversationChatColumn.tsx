import type { TranscriptViewportHandle } from "./sessionViewport";
/**
 * Chat-mode column: scrollable transcript feed + composer dock.
 * Conversation owns all state; this is a presentational peel.
 */

import { type MutableRefObject, type ReactNode, type RefObject } from "react";
import { ChevronDown } from "lucide-react";
import { panelOpacityClass } from "../../lib/panelTransition";
import {
  TranscriptList,
  countPaintableTranscriptItems,
  type Card,
  type CommandApprovalItem,
  type SecretRequestItem,
  type Item,
} from "../TranscriptList";
import TranscriptEmptyState from "./TranscriptEmptyState";
import {
  feedContentLayoutClass,
  feedLiveStreamOpen,
  feedScrollportStyle,
  feedSeatingReservePx,
} from "./feedScroll";

export default function ConversationChatColumn({
  feedRef,
  feedContentRef,
  transcriptStale,
  items,
  status,
  compactingStatus,
  editingIndex,
  auto,
  plan,
  busyElapsedMs,
  modelLabel = "",
  waitHint = null,
  providerElapsedMs = null,
  turnOpen,
  holdSwarmAwait = false,
  feedSettled = true,
  scrollToEndRef,
  viewportRef,
  onEditMessage,
  onExecuteSend,
  onImageClick,
  onSetCard,
  onExecutePlan,
  onCommandApproval,
  onSecretRequest,
  onAuthFailureRetry,
  composerDock,
  showJumpToBottom = false,
  onJumpToBottom,
  sessionId,
}: {
  feedRef: RefObject<HTMLDivElement | null>;
  /** Direct child of the feed scrollport — observed for height-driven stick. */
  feedContentRef?: RefObject<HTMLDivElement | null>;
  transcriptStale: boolean;
  items: Item[];
  status: "idle" | "thinking" | "executing" | "done" | "error" | "streaming" | "awaiting_swarm";
  compactingStatus: string | null;
  editingIndex: number | null;
  auto: boolean;
  plan: boolean;
  busyElapsedMs: number | null;
  modelLabel?: string | null;
  waitHint?: string | null;
  providerElapsedMs?: number | null;
  turnOpen: boolean;
  /** Same hold as Conversation — pending jobs keep transcript latch through idle flaps. */
  holdSwarmAwait?: boolean;
  /** Defer DOM row measurement while session-switch settle glue runs. */
  feedSettled?: boolean;
  scrollToEndRef?: MutableRefObject<(() => void) | null>;
  viewportRef?: MutableRefObject<TranscriptViewportHandle | null>;
  onEditMessage: (idx: number, text: string) => void;
  onExecuteSend: (msg: string, useAuto: boolean, usePlan?: boolean) => void;
  onImageClick: (url: string) => void;
  onSetCard: (id: string, patch: Partial<Card>) => void;
  onExecutePlan: (planText: string) => void;
  onCommandApproval: (item: CommandApprovalItem, decision: boolean | "amendment") => void;
  onSecretRequest?: (item: SecretRequestItem, decision: { action: "save"; value: string } | { action: "dismiss" }) => void;
  onAuthFailureRetry?: () => void;
  composerDock: ReactNode;
  showJumpToBottom?: boolean;
  onJumpToBottom?: () => void;
  sessionId?: string;
}) {
  const paintCount = countPaintableTranscriptItems(items);
  const seatingReservePx = feedSeatingReservePx({
    liveStreamOpen: feedLiveStreamOpen(status, turnOpen),
  });
  // Dim only when stale rows are on screen (refresh flake). Empty cold-miss
  // dim was the swap blink — nothing to honesty-dim.
  const feedDimmed = transcriptStale && paintCount > 0;
  return (
    <div
      className="chat-column flex flex-col flex-1 min-h-0 min-w-0"
    >
      <div className="relative flex-1 min-h-0 flex flex-col">
        <div
          ref={feedRef}
          data-testid="transcript-feed-scrollport"
          aria-busy={transcriptStale && paintCount === 0 ? true : undefined}
          className={`flex-1 min-h-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable] ${panelOpacityClass(false, feedDimmed)}`}
          style={feedScrollportStyle()}
        >
        {/* Locked pair: overflow-anchor:auto + scroll-padding-bottom.
            Content is min-h-full / justify-start so idle short sessions
            sit mid/upper. Content padding-bottom always keeps the Cursor-
            like composer clearance (idle and live). Composer is a sibling
            outside this scrollport. */}
        <div
          ref={feedContentRef}
          data-testid="transcript-feed-content"
          className={feedContentLayoutClass()}
          style={{ paddingBottom: seatingReservePx }}
        >
          <TranscriptEmptyState
            transcriptStale={transcriptStale}
            itemCount={paintCount}
          />
          {/*
            PERF: The transcript is rendered by TranscriptList, a React.memo
            component whose props are deliberately independent of the composer
            `input` state. Because typing only mutates `input` (which lives in
            this parent) and none of TranscriptList's props change per keystroke,
            React skips re-rendering the transcript on every keystroke. This
            breaks the old coupling where items.map ran on the ENTIRE transcript
            for each character typed (cost grew with message count). Row mounting
            is further bounded by @tanstack/react-virtual inside TranscriptList.
          */}
          <TranscriptList
            items={items}
            status={status}
            compactingStatus={compactingStatus}
            editingIndex={editingIndex}
            auto={auto}
            plan={plan}
            busyElapsedMs={busyElapsedMs}
            modelLabel={modelLabel}
            waitHint={waitHint}
            providerElapsedMs={providerElapsedMs}
            turnOpen={turnOpen}
            holdSwarmAwait={holdSwarmAwait}
            feedSettled={feedSettled}
            scrollContainerRef={feedRef}
            scrollToEndRef={scrollToEndRef}
            viewportRef={viewportRef}
            onEditMessage={onEditMessage}
            onExecuteSend={onExecuteSend}
            onImageClick={onImageClick}
            onSetCard={onSetCard}
            onExecutePlan={onExecutePlan}
            onCommandApproval={onCommandApproval}
            onSecretRequest={onSecretRequest}
            onAuthFailureRetry={onAuthFailureRetry}
            sessionId={sessionId}
          />
        </div>
      </div>
      {showJumpToBottom ? (
        <button
          type="button"
          data-testid="jump-to-latest"
          title="Jump to latest"
          aria-label="Jump to latest"
          onClick={onJumpToBottom}
          className="transcript-fold-chrome select-none absolute bottom-3 left-1/2 -translate-x-1/2 z-10 flex items-center justify-center w-8 h-8 rounded-full border border-edge2 text-muted hover:text-txt hover:bg-panel2/80 transition-colors"
          style={{ backgroundColor: "#0f1113" }}
        >
          <ChevronDown size={16} />
        </button>
      ) : null}
      </div>
      <div className="transcript-fold-chrome select-none shrink-0 min-w-0" data-testid="composer-chrome">
        {composerDock}
      </div>
    </div>
  );
}
