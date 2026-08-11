import type { en } from "@/i18n/locales/en";

/** Every string the app can show. English is the source of truth. */
export type MessageKey = keyof typeof en;

/** A complete catalogue. Partial ones are deliberately not allowed — a missing
 *  key would render as a bare dotted identifier in front of a field worker. */
export type Messages = Record<MessageKey, string>;

export interface LocaleDef {
  code: string;
  /** The language's own name. A picker that says "Arabic" in English is no use
   *  to someone who cannot read English — that is the whole point of it. */
  endonym: string;
  dir: "rtl" | "ltr";
  messages: Messages;
}
