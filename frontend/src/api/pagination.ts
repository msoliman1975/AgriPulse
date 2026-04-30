// Cursor-paginated response per ARCHITECTURE.md § 8.

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}
