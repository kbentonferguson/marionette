import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

import { LEFT_MIN_W, MIN_CENTER_W, RAIL_GUTTER_W, RIGHT_MIN_W } from "./railLayout";

const CONTENT_MIN_W = 480;
const DOCK_W = 68;
const SHELL_FRAME_W = 4;
export const DUAL_RAIL_SHELL_WIDTH = CONTENT_MIN_W + DOCK_W + LEFT_MIN_W + RIGHT_MIN_W
  + 2 * RAIL_GUTTER_W + SHELL_FRAME_W;
export const COMPACT_SHELL_WIDTH = 800;
// railLayout already budgets MIN_CENTER_W and two pixels of frame.
export const SHELL_EXTRA_CENTER_W = CONTENT_MIN_W + DOCK_W - MIN_CENTER_W + SHELL_FRAME_W - 2;
export type ShellView = "chat" | "left" | "right";

export function useResponsiveShell(initialLeft: boolean, initialRight: boolean) {
  const [width, setWidth] = useState(() => window.innerWidth);
  const previousWidth = useRef(width);
  const [desktopLeftOpen, setDesktopLeftOpen] = useState(initialLeft);
  const [desktopRightOpen, setDesktopRightOpen] = useState(initialRight);
  const [view, setView] = useState<ShellView>("chat");
  const compact = width < COMPACT_SHELL_WIDTH;
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
    if (!compact) { setDesktopLeftOpen(action); return; }
    setView(previous => {
      const open = typeof action === "function" ? action(previous === "left") : action;
      return open ? "left" : previous === "left" ? "chat" : previous;
    });
  }, [compact]);
  const setRightOpen = useCallback((action: SetStateAction<boolean>) => {
    if (!compact) { setDesktopRightOpen(action); return; }
    setView(previous => {
      const open = typeof action === "function" ? action(previous === "right") : action;
      return open ? "right" : previous === "right" ? "chat" : previous;
    });
  }, [compact]);
  return {
    width, compact, rightDrawer: width < DUAL_RAIL_SHELL_WIDTH, view, setView, desktopLeftOpen, desktopRightOpen,
    leftOpen: compact ? view === "left" : desktopLeftOpen,
    rightOpen: compact ? view === "right" : desktopRightOpen,
    setLeftOpen, setRightOpen,
  };
}
