import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

import { LEFT_MIN_W, MIN_CENTER_W, RAIL_GUTTER_W, RIGHT_COMPACT_MIN_W } from "./railLayout";

const DOCK_W = 68;
const SHELL_FRAME_W = 4;
export const DUAL_RAIL_SHELL_WIDTH = MIN_CENTER_W + DOCK_W + LEFT_MIN_W + RIGHT_COMPACT_MIN_W
  + 2 * RAIL_GUTTER_W + SHELL_FRAME_W;
export const COMPACT_SHELL_WIDTH = 640;
// railLayout budgets the chat column and two pixels of frame already.
export const SHELL_EXTRA_CENTER_W = DOCK_W + SHELL_FRAME_W - 2;
export type ShellView = "chat" | "left" | "right";

export function useResponsiveShell(initialLeft: boolean, initialRight: boolean) {
  const [width, setWidth] = useState(() => window.innerWidth);
  const previousWidth = useRef(width);
  const [desktopLeftOpen, setDesktopLeftOpen] = useState(initialLeft);
  const [desktopRightOpen, setDesktopRightOpen] = useState(initialRight);
  const [view, setView] = useState<ShellView>("chat");
  const compact = width < COMPACT_SHELL_WIDTH;
  const singleRail = width < DUAL_RAIL_SHELL_WIDTH;
  const leftOpen = compact ? view === "left" : desktopLeftOpen && (!singleRail || !desktopRightOpen || view === "left");
  const rightOpen = compact ? view === "right" : desktopRightOpen && (!singleRail || !desktopLeftOpen || view !== "left");
  useEffect(() => {
    const resize = () => {
      const next = window.innerWidth;
      if ((previousWidth.current < COMPACT_SHELL_WIDTH) !== (next < COMPACT_SHELL_WIDTH)) {
        setView("chat");
      }
      previousWidth.current = next;
      setWidth(next);
    };
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const setLeftOpen = useCallback((action: SetStateAction<boolean>) => {
    if (!compact) {
      const open = typeof action === "function" ? action(leftOpen) : action;
      setDesktopLeftOpen(open);
      if (open) setView("left");
      return;
    }
    setView(previous => {
      const open = typeof action === "function" ? action(previous === "left") : action;
      return open ? "left" : previous === "left" ? "chat" : previous;
    });
  }, [compact, leftOpen]);
  const setRightOpen = useCallback((action: SetStateAction<boolean>) => {
    if (!compact) {
      const open = typeof action === "function" ? action(rightOpen) : action;
      setDesktopRightOpen(open);
      if (open) setView("right");
      return;
    }
    setView(previous => {
      const open = typeof action === "function" ? action(previous === "right") : action;
      return open ? "right" : previous === "right" ? "chat" : previous;
    });
  }, [compact, rightOpen]);
  return {
    width, compact, rightDrawer: compact, view, setView, desktopLeftOpen, desktopRightOpen,
    leftOpen, rightOpen,
    setLeftOpen, setRightOpen,
  };
}
