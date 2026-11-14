/**
 * NTF-01..03 DTOs. verified: app/modules/notifications/router.py `_out`, `list_inbox`,
 * `mark_read`, `mark_all_read` (plain dicts, so OpenAPI carries no response schema).
 */

export interface InboxItem {
  notification_id: string;
  template_key: string;
  category: string;
  priority: string;
  data: Record<string, unknown> | null;
  read_at: string | null;
  created_at: string;
}

export interface InboxResponse {
  data: InboxItem[];
  unread_count: number;
  page: { next_cursor: string | null; has_more: boolean; limit: number };
}

export interface MarkReadResponse {
  notification_id: string;
  read_at: string;
}

export interface MarkAllReadResponse {
  marked: number;
}
