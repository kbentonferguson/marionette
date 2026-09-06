import { useEffect, useState } from "react";
import {
  getActiveDiagnostic,
  subscribeDiagnostic,
} from "./operationalDiagnosticBus";
import {
  belongsToActiveScope,
  isReadinessDiagnostic,
  panelNotice,
  type DiagnosticScope,
  type OperationalDiagnostic,
} from "./operationalDiagnostic";

export function useOperationalDiagnostic(active?: { sessionId?: string; repo?: string }): OperationalDiagnostic | null {
  const [diag, setDiag] = useState<OperationalDiagnostic | null>(getActiveDiagnostic);
  useEffect(() => subscribeDiagnostic(setDiag), []);
  return diag && active && !belongsToActiveScope(diag, active) ? null : diag;
}

/** Operational error text for a panel. Readiness root replaces local copy. */
export function usePanelNotice(
  fallback: string | null | undefined,
  scope?: DiagnosticScope,
): string | null {
  const diag = useOperationalDiagnostic();
  if (isReadinessDiagnostic(diag) || (scope && diag?.scope === scope)) {
    return panelNotice(fallback || "", diag, scope);
  }
  return fallback ?? null;
}
