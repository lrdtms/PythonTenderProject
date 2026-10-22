const GENERIC = "Something about this estimate needs a look. Check the line, then try again.";

const FLAGS: Record<string, string> = {
  currency_differs: "The quoted currency is different from the estimate's currency.",
  currency_missing: "The quotation does not say which currency its prices are in.",
  vat_basis_unknown: "It is not clear whether the quoted prices include VAT.",
  price_missing: "There is no price for this line yet.",
  quantity_missing: "This BoQ line has no quantity.",
  unit_missing: "This BoQ line has no unit.",
  unreviewed_source: "A BoQ line or quotation item behind this price has not been reviewed yet.",
  source_changed: "The BoQ or quotation behind this price has changed since it was chosen. Refresh the line.",
};

const BLOCKERS: Record<string, string> = {
  unresolved: "Some lines still have no price.",
  source_changed: "Some prices are out of date because their BoQ or quotation changed. Refresh those lines.",
  unreviewed_source: "A BoQ line or quotation item behind this price has not been reviewed yet.",
  no_lines: "This estimate has no BoQ lines to price.",
};

const ERRORS: Record<string, string> = {
  estimate_frozen: "This estimate is approved or reviewed, so it cannot be changed. Start a new version to make changes.",
  estimate_not_ready: "This estimate is not ready yet. Fix the items listed, then try again.",
  estimate_not_reviewed: "This estimate must be marked as reviewed before it can be approved.",
  draft_exists: "A draft estimate already exists for this tender. Open that draft instead.",
  pricing_defaults_missing: "Save the pricing defaults first, then create the estimate.",
  stale_match: "The chosen supplier price is out of date. Reload the page and choose it again.",
  currency_locked: "The currency cannot be changed while a line has a price. Clear those prices first.",
  tender_archived: "This tender is archived, so the estimate cannot be changed.",
  quantity_missing: "This line needs a quantity before it can be priced.",
  unit_mismatch_unacknowledged: "The quoted unit is different from the BoQ unit. Confirm that you want to use this price.",
};

const lookup = (table: Record<string, string>, code: string): string =>
  Object.prototype.hasOwnProperty.call(table, code) ? table[code] : GENERIC;

/** Plain sentence for a line flag. Unknown codes get a generic sentence, never the raw code. */
export const flagText = (code: string): string => lookup(FLAGS, code);

/** Plain sentence for a reason an estimate cannot be approved or reviewed yet. */
export const blockerText = (code: string): string => lookup(BLOCKERS, code);

/** Plain sentence for an API error code returned by an estimate write. */
export const errorText = (code: string): string => lookup(ERRORS, code);
