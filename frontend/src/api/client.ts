export class ApiRequestError extends Error {}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (data && typeof data.error === "string") {
      return data.error;
    }
  } catch {
    // response body was not JSON
  }
  return `Request failed with status ${response.status}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers:
      init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json", ...init?.headers }
        : init?.headers,
  });

  if (!response.ok) {
    throw new ApiRequestError(await parseErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

export function apiUrl(path: string, params?: Record<string, string | undefined>): string {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, value);
    }
  }
  return url.pathname + url.search;
}
