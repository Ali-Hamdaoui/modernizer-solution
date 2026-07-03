const ABSOLUTE_PATH_PATTERN = /(^[A-Za-z]:[\\/])|(^\\\\)|(^\/(?:Users|home|tmp|var|etc|mnt|opt|private)\/)|(\.\.[\\/])/;

export function formatSafeRelativePath(value: string | null | undefined): string {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return ABSOLUTE_PATH_PATTERN.test(text) ? "[redacted path]" : text;
}
