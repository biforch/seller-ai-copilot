export class ApiClientError extends Error {
  readonly httpStatus: number;
  readonly errorCode: string | null;
  readonly detail: string | null;

  constructor(
    message: string,
    httpStatus: number,
    errorCode?: string | null,
    detail?: string | null,
  ) {
    super(message);
    this.name = 'ApiClientError';
    this.httpStatus = httpStatus;
    this.errorCode = errorCode ?? null;
    this.detail = detail ?? null;
  }
}

export function isApiClientError(error: unknown): error is ApiClientError {
  return error instanceof ApiClientError;
}
