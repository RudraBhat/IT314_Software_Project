"use client";

import { useCallback, useEffect, useState } from "react";

type ApiFailure = {
  error?: {
    code?: unknown;
    message?: unknown;
    details?: unknown;
  };
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly details: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed. Try again.";
}

type ApiOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  idempotencyKey?: string;
};

export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const { body, idempotencyKey, headers: inputHeaders, ...requestOptions } = options;
  const headers = new Headers(inputHeaders);
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  // Files and other binary bodies must be sent untouched; JSON.stringify would turn a File into "{}".
  const isBinary = (typeof Blob !== "undefined" && body instanceof Blob) || body instanceof ArrayBuffer;

  if (body !== undefined && !isFormData && !isBinary && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (idempotencyKey) headers.set("idempotency-key", idempotencyKey);

  const response = await fetch(`/api/dm/${path.replace(/^\/+/, "")}`, {
    ...requestOptions,
    headers,
    body: body === undefined ? undefined : isFormData || isBinary || typeof body === "string" ? (body as BodyInit) : JSON.stringify(body),
  });

  const text = response.status === 204 ? "" : await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const failure = typeof payload === "object" && payload !== null ? payload as ApiFailure : undefined;
    const apiError = failure?.error;
    const message =
      typeof apiError?.message === "string"
        ? apiError.message
        : typeof payload === "string" && payload
          ? payload
          : `Request failed (${response.status}).`;
    const code = typeof apiError?.code === "string" ? apiError.code : "REQUEST_FAILED";
    throw new ApiError(message, response.status, code, apiError?.details ?? null);
  }

  return payload as T;
}

type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[];
type QueryParams = Record<string, QueryValue>;

function serializeParams(params?: QueryParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === false || value === "") continue;
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, String(item)));
    } else {
      search.set(key, String(value));
    }
  }
  return search.toString();
}

/**
 * Download a CSV the server builds from the same filters as a list, and save it with the server's file name.
 * Resolves to `truncated: true` when the server cut the file at its row limit, so the screen can say so.
 */
export async function downloadCsv(path: string, params: QueryParams, fallbackName: string): Promise<{ truncated: boolean }> {
  const query = serializeParams(params);
  const response = await fetch(`/api/dm/${path.replace(/^\/+/, "")}${query ? `?${query}` : ""}`);
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    let code = "REQUEST_FAILED";
    try {
      const failure = JSON.parse(await response.text()) as ApiFailure;
      if (typeof failure.error?.message === "string") message = failure.error.message;
      if (typeof failure.error?.code === "string") code = failure.error.code;
    } catch {
      // The body was not JSON; keep the generic message.
    }
    throw new ApiError(message, response.status, code, null);
  }
  const blob = await response.blob();
  const filename = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
  return { truncated: response.headers.get("x-export-truncated") === "true" };
}

export function useQuery<T>(path: string | null, params?: QueryParams) {
  const query = serializeParams(params);
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    refresh: number;
    data?: T;
    error: string | null;
  }>();
  const reload = useCallback(() => setRefresh((value) => value + 1), []);
  const key = path === null ? null : `${path}?${query}`;

  useEffect(() => {
    if (!path || key === null) return;

    const controller = new AbortController();
    const querySuffix = query ? `?${query}` : "";

    void api<T>(`${path}${querySuffix}`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ key, refresh, data, error: null });
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setResult((previous) => ({
            key,
            refresh,
            data: previous?.key === key ? previous.data : undefined,
            error: errorMessage(requestError),
          }));
        }
      });

    return () => controller.abort();
  }, [path, query, refresh, key]);

  const current = key !== null && result?.key === key ? result : undefined;
  const isCurrentRequest = current?.refresh === refresh;
  return {
    data: current?.data,
    error: isCurrentRequest ? current?.error ?? null : null,
    loading: key !== null && !isCurrentRequest,
    reload,
  };
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
