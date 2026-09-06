export type JSONResponse =
  | { kind: 'response'; status: number; text: string; correlationId: string }
  | { kind: 'connection-error'; message: string; code: string };
export function parseJSONResponse(response: JSONResponse, path: string, soft?: boolean): unknown;
