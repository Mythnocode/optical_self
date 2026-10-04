export interface RequestDiagnostic {
  time: string;
  request_id: string;
  method: string;
  route: string;
  status: number;
  elapsed_ms: number;
  code?: string;
  job_id?: string;
  error_name?: string;
}

const recent: RequestDiagnostic[] = [];
export function recordRequestDiagnostic(entry: RequestDiagnostic): void {
  recent.push(entry);
  if (recent.length > 40) recent.shift();
}
export function recentRequestDiagnostics(): RequestDiagnostic[] {
  return recent.map(entry => ({ ...entry }));
}
