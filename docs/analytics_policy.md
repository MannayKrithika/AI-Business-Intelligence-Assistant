# Analytics policy

This note records the rules the analytics engine applies. The same rules are used by all five
operations and are checked by the reference calculator in `tests/reference.py`.

## Revenue

- **Eligible transaction:** `status = 'Completed'` AND `unit_price` is not NULL.
- **Net revenue per transaction:** `quantity × unit_price − discount_amount`.
  The discount is a transaction-level amount and is subtracted once.
- **Negative net revenue is allowed.** If a discount is larger than `quantity × unit_price`, the
  transaction's net revenue is negative. The importer does not reject it, and analytics does not
  clip it to zero. Negative values are included in totals, rankings, the monthly trend and
  comparisons, so every operation treats them the same way.
- **Zero quantity** is eligible and contributes 0.
- Excluded rows (returned, or missing `unit_price`) are stored but never counted.

## Rankings

- Sorted by revenue descending, then by name ascending. A tie is therefore broken alphabetically.
- Negative totals rank below zero and below positive totals, as expected.

## Monthly trend

- Every month from the first to the last stored month is listed in chronological order.
- A month with no eligible rows is listed with revenue 0.00 and 0 transactions.

## Month-to-month comparison

- `absolute_change = revenue(month_b) − revenue(month_a)`. `month_a` is the baseline.
- `direction` is `increased`, `decreased` or `unchanged`, based on the change rounded to 2 dp.
- `percentage_change = absolute_change / |revenue(month_a)| × 100`, rounded to 2 dp.

### Zero baseline

- If `revenue(month_a) = 0`, `percentage_change` is `null` and a note is returned.
  Division by zero is never performed.
- The absolute change and direction are still reported.

### Negative baseline

- The percentage is computed against the absolute value of the baseline, so the sign of
  `percentage_change` matches the sign of `absolute_change`.
- Example: −200 → 200 is `+400 / 200 × 100 = +200.00%`, "increased".
- Example: −200 → −300 is `−100 / 200 × 100 = −50.00%`, "decreased".
- A note is returned on every such result.

### Limitations

- A percentage against a negative baseline is a measure of size relative to that baseline. It is
  not a growth rate, and it can look misleading. For example, moving from −1 to 1 is reported as
  +200%, even though the total moved by only 2 units.
- A percentage against a baseline near zero is very large in magnitude, even when the absolute
  change is small.
- Percentages and the absolute change are rounded to 2 decimal places. `direction` is "unchanged"
  only when the rounded absolute change is 0.00.
- The supplied dataset has no negative net revenue and no zero or negative monthly baselines.
  The negative-baseline behaviour is verified with hand-built fixtures only.

## Validation

- Month inputs must be `YYYY-MM`, inside the stored data range, and the two months must differ.
- All user input reaches SQL only as bound parameters.
