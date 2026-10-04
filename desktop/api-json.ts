/** Preserve the Python estimator's float-versus-integer parameter semantics.
 * JSON.stringify emits JS 1 as `1`; sklearn interprets that as one feature,
 * whereas the legacy `1.0` option means the fraction of all available features.
 */
export function serializeApiBody(path: string, body: unknown): string | undefined {
  const json = JSON.stringify(body);
  if (path === "/api/v1/training/joint/jobs" && json) {
    return json.replace(/("max_features":)1(?=[,}])/g, (_match, prefix: string) => `${prefix}1.0`);
  }
  return json;
}
