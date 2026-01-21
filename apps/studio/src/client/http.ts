function normalizeApiBase(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const trimmed = value.toString().trim();
  return trimmed.replace(/\/+$/, "");
}

function resolveApiBase(): string {
  const envBase = import.meta.env?.VITE_API_BASE || "";
  return normalizeApiBase(envBase);
}

const apiBase = resolveApiBase();

export function apiUrl(path: string): string {
  if (!apiBase) {
    return path;
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${apiBase}${path}`;
}

export async function fetchJson<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(apiUrl(url), options);
  const text = await response.text();
  let data: T | null = null;
  if (text) {
    try {
      data = JSON.parse(text) as T;
    } catch (error) {
      throw new Error("Invalid JSON response");
    }
  }
  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? (data as { detail?: string }).detail
        : response.statusText;
    throw new Error(detail || "Request failed");
  }
  return data as T;
}
