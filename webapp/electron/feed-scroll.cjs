"use strict";

/** Authoritative scrollTop for stick-to-bottom (shared with feedScroll.ts). */
function scrollToFeedEnd(scrollHeight, clientHeight) {
  return Math.max(0, scrollHeight - clientHeight);
}

/** Same-frame feed-forward: keep distance-from-end across content growth. */
function feedForwardFollowTop(scrollTop, contentDeltaPx, maxScrollTop) {
  const forwarded = scrollTop + Math.max(0, contentDeltaPx);
  return Math.max(0, Math.min(maxScrollTop, forwarded));
}

module.exports = { scrollToFeedEnd, feedForwardFollowTop };
