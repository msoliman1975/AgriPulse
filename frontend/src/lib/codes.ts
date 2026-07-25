// Identifier contracts shared between the create/edit surfaces and the API.
// Kept in a dependency-free leaf module so a form or a map panel can validate
// without importing the other one's component tree.

/**
 * Farm and block `code`: starts alphanumeric, then up to 31 more of
 * alphanumeric / underscore / hyphen. Mirrors the backend pattern — keep the
 * two in lock-step.
 */
export const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;
