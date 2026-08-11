/**
 * How to write a person's name in a list, a picker, or a chip.
 *
 * Every one of these used to be `full_name || email`, which is correct for a
 * colleague and wrong for a field worker: their address is synthesised from
 * their phone number to satisfy a NOT NULL/UNIQUE constraint and nothing can
 * be delivered to it. An unnamed scout therefore rendered as
 * `+201001234567@scouts.agripulse.cloud` — which looks like a data-entry
 * mistake somebody will try to correct, and implies an inbox that does not
 * exist.
 *
 * The backend says which handle is real via `identity_kind`; this is the one
 * place that decides what to do about it.
 */

import type { IdentityKind } from "@/api/users";

export interface DisplayablePerson {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  identity_kind?: IdentityKind;
}

/**
 * The best available label. Falls back to the phone for phone identities and
 * to the email only for people who genuinely have one, then to a short id so
 * a row is never blank.
 */
export function displayUser(person: DisplayablePerson, fallbackId?: string): string {
  const name = person.full_name?.trim();
  if (name) return name;
  if (person.identity_kind === "phone") {
    return person.phone?.trim() || fallbackId?.slice(0, 8) || "";
  }
  return person.email?.trim() || person.phone?.trim() || fallbackId?.slice(0, 8) || "";
}

/**
 * The secondary line under a name — the handle they actually sign in with.
 * Null when it would only repeat what `displayUser` already returned.
 */
export function displayUserHandle(person: DisplayablePerson): string | null {
  if (!person.full_name?.trim()) return null;
  const handle = person.identity_kind === "phone" ? person.phone : person.email;
  return handle?.trim() || null;
}
