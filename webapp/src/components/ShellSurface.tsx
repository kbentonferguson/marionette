import { useLayoutEffect, useRef, type ReactNode } from "react";

type Presentation = "inline" | "left" | "right" | "modal";

/** Native modal focus containment without reparenting or unmounting live panes. */
export default function ShellSurface({ visible, suspended = false, presentation, label, width, onClose, returnFocus, children }: {
  visible: boolean;
  suspended?: boolean;
  presentation: Presentation;
  label: string;
  width?: number;
  onClose: () => void;
  returnFocus?: HTMLElement | null;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const focusTarget = useRef(returnFocus);
  focusTarget.current = returnFocus;
  const opener = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (dialog.open) dialog.close();
    if (visible && !suspended) {
      if (presentation === "inline") dialog.open = true;
      else {
        const active = document.activeElement;
        if (!opener.current?.isConnected) {
          opener.current = focusTarget.current || (active instanceof HTMLElement ? active : null);
        }
        dialog.showModal();
      }
    } else if (!visible && opener.current?.isConnected) {
      opener.current.focus();
      opener.current = null;
    }
    return () => { if (dialog.open) dialog.close(); };
  }, [visible, suspended, presentation]);

  return <dialog ref={ref} role={presentation === "inline" ? "complementary" : "dialog"} aria-label={label} aria-modal={presentation === "inline" ? undefined : true}
    data-shell-hidden={!visible || suspended} data-presentation={presentation}
    className="shell-surface" style={presentation === "inline" ? { width } : undefined}
    onCancel={(event) => { event.preventDefault(); event.stopPropagation(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget && presentation !== "inline") {
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
    } }}>
    {presentation !== "inline" && <header className="shell-surface-header">
      <h2>{label}</h2>
      <button type="button" aria-label={`Close ${label}`} onClick={onClose}>Close</button>
    </header>}
    <div className="shell-surface-content">{children}</div>
  </dialog>;
}
