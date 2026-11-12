# Hoshi Stream data guide

This file explains the synthetic Hoshi Stream data in the catalog `<catalog>`. It is written for people and SQL-writing agents who answer business questions from this data.

Every SQL block in this file was run against the workspace as a SELECT statement, and the output matches the numbers printed next to it. Some figures in the text come from related checks that were run in the same session but are not in a block. These are mostly the trap counts in section 6 and a few figures in sections 1 and 3. Their query output was checked, but they cannot be rerun from this file alone. The run date was 2026-11-11. When a number cannot be checked, the file says so.

All table names are fully qualified. The four curated schemas are `hoshi_subscriber`, `hoshi_billing`, `hoshi_content` and `hoshi_distribution`. The fallback schemas are `hoshi_rights`, `hoshi_sales` and `hoshi_partner`. The schema `hoshi_talent` is off limits and is described only in section 7.

## 1. Overview

### As-of date

The as-of date is **2026-11-10**. Use `DATE'2026-11-10'` in SQL. Do not use `CURRENT_DATE()`, because that returns 2026-11-11 today and the data does not include that day.

How the as-of date was found:

- The newest activity in the data is on 2026-11-09. Nothing is dated on 2026-11-10 or later for sessions, activations, invoices or churn.
- The first day of the data is 2024-01-10. That is exactly 34 months before 2026-11-10, which matches `WINDOW_MONTHS = 34` in `data_model/generate.py`.
- The generator uses `--as-of` or yesterday as the as-of date. I could not see the run log, so I cannot confirm which argument was used. The data fits 2026-11-10 in every check I ran.

Latest dates in the main fact tables (from `MAX` queries run on each column):

| Table | Column | Latest value in data |
|---|---|---|
| `hoshi_distribution.playback_session` | `session_start_timestamp` | 2026-11-09 23:59:57 |
| `hoshi_subscriber.subscription` | `activation_date` | 2026-11-09 |
| `hoshi_subscriber.churn_event` | `churn_timestamp` | 2026-11-09 23:05:43 |
| `hoshi_billing.invoice` | `invoice_date` | 2026-11-09 |
| `hoshi_billing.payment` | `payment_timestamp` | 2026-11-09 23:59:33 |
| `hoshi_sales.impression_delivery` | `delivery_date` | 2026-11-09 |
| `hoshi_sales.campaign` | `end_date` | 2026-11-09 |
| `hoshi_subscriber.subscriber` | `registration_timestamp` | 2026-11-08 22:25:28 |

Some dates in the data are after the as-of date on purpose. These are not errors in the data, but they matter for filters:

- Refund requests go up to 2026-12-08. 194 requests that are still `Requested` have a request date after the as-of date.
- Royalty statement due dates go up to 2026-12-24. Statements that are `Pending` or `Issued` have due dates after the as-of date.
- Licence expiry dates go up to 2030-05-13. Window close dates go up to 2029-10-29. Acquisition deal expiry dates go up to 2030-07-11.

### Date range

Viewing, billing and churn cover 2024-01-10 to 2026-11-09. Subscriber registration timestamps start earlier, on 2023-12-27, because each registration is set 1 to 14 days before the first subscription starts. Royalty statement due dates start on 2019-07-11, and episode air dates start on 2011-07-12, because the back catalogue is older than the window.

### The business

Hoshi Stream is a fictional anime streaming service. It sells three paid tiers (Fan, Mega Fan and Ultimate Fan), each billed monthly or annually. That makes six paid plans. It also has one free ad-supported plan, so the catalog holds seven plans in total. Subscribers live in four regions: North America (NA), Latin America (LATAM), Europe, Middle East and Africa (EMEA), and Asia Pacific (APAC). Each region has a web and mobile platform and a TV and console platform.

The company streams 1,200 titles from 400 series. It holds licence agreements with 40 rights holders (licensors) and buys content from 30 partners (studios, distributors, broadcasters and platforms) under acquisition deals with minimum guarantees (MGs). Free-tier viewers see ads. Ad sales cover 150 advertisers, 900 campaigns and about 300 thousand served impressions.

## 2. Tables

Row counts come from `SELECT COUNT(*)` on each table, run on 2026-11-11.

### hoshi_subscriber (curated)

| Table | Rows | What one row is |
|---|---|---|
| `subscriber` | 50,000 | One subscriber account. It has one territory and one current account status. |
| `subscription_plan` | 7 | One plan product, such as Fan monthly (`FAN-M`) or Fan annual (`FAN-A`). |
| `subscription` | 63,339 | One period on one plan for one subscriber. A plan change ends one row and starts another. |
| `churn_event` | 13,171 | One cancellation. There is one churn event for each subscription row whose status is `Cancelled`. |
| `offer` | 20 | One promotional offer. |
| `offer_redemption` | 12,000 | One use of one offer by one subscriber. |

### hoshi_billing (curated)

| Table | Rows | What one row is |
|---|---|---|
| `invoice` | 420,289 | One bill for one billing period of one paid subscription. Free subscriptions have no invoices. |
| `payment` | 420,289 | One payment attempt. Every invoice has exactly one payment, and `payment_id` equals `invoice_id`. |
| `refund` | 8,007 | One refund request against one invoice. |

### hoshi_content (curated)

| Table | Rows | What one row is |
|---|---|---|
| `genre` | 25 | One anime genre. |
| `series` | 400 | One series. It has a franchise name and a genre. |
| `season` | 900 | One season of a series. |
| `title` | 1,200 | One title. There are 900 series titles (one per season), 150 films and 150 specials. |
| `content_episode` | 14,364 | One episode. A film or special is one episode with `episode_type = 'Feature'`. |

### hoshi_distribution (curated)

| Table | Rows | What one row is |
|---|---|---|
| `ott_platform` | 8 | One platform: region plus web and mobile, or region plus TV and console. |
| `playback_session` | 2,000,000 | One viewing session by one subscriber on one platform. |

### hoshi_rights (fallback)

| Table | Rows | What one row is |
|---|---|---|
| `holder` | 40 | One rights holder, also called a licensor. |
| `territory` | 30 | One country. Some countries are served and some are rights-only (see section 3.1). |
| `license_agreement` | 600 | One licence agreement with one licensor. |
| `content_window` | 3,000 | One availability window for one title, on one platform, in one territory. |
| `royalty_statement` | 6,160 | One quarterly royalty statement for one licence agreement. |
| `license_metrics` (metric view) | not a table | Licence agreements by licensor, type, status and territory scope. |

### hoshi_sales (fallback)

| Table | Rows | What one row is |
|---|---|---|
| `advertiser` | 150 | One advertiser. |
| `campaign` | 900 | One campaign for one advertiser, with a planned number of impressions. |
| `ad_order` | 2,551 | One order line under a campaign. Each campaign has 2 to 4 order lines. |
| `impression_delivery` | 300,024 | One served ad impression on one viewing session. |
| `ad_delivery_metrics` (metric view) | not a table | Served impressions by advertiser, campaign objective and month. |

### hoshi_partner (fallback)

| Table | Rows | What one row is |
|---|---|---|
| `partner` | 30 | One partner company. |
| `acquisition_deal` | 300 | One acquisition deal with one partner. |
| `minimum_guarantee` | 300 | One minimum guarantee. Each acquisition deal has exactly one. |

The `hoshi_talent` schema is off limits. Its row counts are in section 7.

## 3. How to compute the common things

Read this section before writing any SQL for a business question. Each subsection gives the join or filter to use, the result we got when we ran it, and the trap to avoid.

### 3.1 Region

**Region of a subscriber.** Join the subscriber to the territory table, then use `territory_group`. The values are `NA`, `LATAM`, `EMEA` and `APAC`. The group `Rights-only` also appears in the territory table, but no subscriber lives there.

```sql
SELECT t.territory_group AS region, COUNT(*) AS subscribers
FROM <catalog>.hoshi_subscriber.subscriber AS s
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = s.territory_id
GROUP BY t.territory_group
ORDER BY subscribers DESC
```

Result: NA 13,974. EMEA 12,689. APAC 12,274. LATAM 11,063. These add up to all 50,000 subscribers. `subscriber.country_code` agrees with the territory code for every subscriber.

Trap: the group `NA` holds four countries: United States, Canada, Puerto Rico and the Bahamas. The `Rights-only` group holds eight countries (Netherlands, Sweden, South Africa, Taiwan, Thailand, New Zealand, Ireland and Poland). They have content windows and royalty rules, but no subscribers.

**Region of a playback session.** The `ott_platform` table has no territory column. The region is the middle part of `platform_code`, which looks like `HS-NA-WM`. Use `split_part`.

```sql
SELECT split_part(o.platform_code, '-', 2) AS region, COUNT(*) AS sessions
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_distribution.ott_platform AS o
  ON o.ott_platform_id = p.ott_platform_id
GROUP BY split_part(o.platform_code, '-', 2)
ORDER BY region
```

Result: APAC 493,434. EMEA 508,015. LATAM 438,579. NA 559,972. The platform region matches the subscriber region for all 2,000,000 sessions (checked with the join below).

```sql
SELECT COUNT(*) AS sessions,
       SUM(CASE WHEN split_part(o.platform_code, '-', 2) = t.territory_group THEN 1 ELSE 0 END) AS region_matches
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_distribution.ott_platform AS o
  ON o.ott_platform_id = p.ott_platform_id
JOIN <catalog>.hoshi_subscriber.subscriber AS s
  ON s.subscriber_id = p.subscriber_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = s.territory_id
```

Result: 2,000,000 sessions and 2,000,000 matches.

Trap: the `ott_platform_id` columns on other tables do not follow the market. `content_window.ott_platform_id` is random for the rights-only countries. `ad_order.ott_platform_id` has no market link at all. The `churn_event.ott_platform_id` column always holds one of the four web and mobile platforms. Use the subscriber's territory when you need a market, and use the platform code only for playback.

### 3.2 Subscribers, plans and tiers

**Active paying subscribers on a date.** A subscription row covers a date when it started on or before that date and has not ended by it. A paid plan is any plan with `plan_type = 'Paid'`. At any date, each subscriber has at most one covering row, so counting rows and counting subscribers give the same answer.

```sql
SELECT COUNT(DISTINCT s.subscriber_id) AS active_paying_subscribers
FROM <catalog>.hoshi_subscriber.subscription AS s
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = s.subscription_plan_id
WHERE p.plan_type = 'Paid'
  AND s.activation_date <= DATE'2026-11-10'
  AND (s.termination_date IS NULL OR s.termination_date > DATE'2026-11-10')
```

Result on 2026-11-10: 29,946. Change the date to `DATE'2025-11-10'` and the result is 21,406. The same answer comes from the status: `subscription_status = 'Active'` with `plan_type = 'Paid'` gives 29,946.

**New sign-ups in a month.** A sign-up is the first subscription row of a subscriber. Use the earliest `activation_date`, not `registration_timestamp`.

```sql
WITH first_subscription AS (
  SELECT subscriber_id, MIN(activation_date) AS first_activation
  FROM <catalog>.hoshi_subscriber.subscription
  GROUP BY subscriber_id
)
SELECT DATE_TRUNC('MONTH', first_activation) AS signup_month, COUNT(*) AS new_subscribers
FROM first_subscription
WHERE first_activation < DATE'2026-11-10'
GROUP BY 1
ORDER BY 1
```

Results: January 2024 has 1,066 sign-ups. This is a partial month, because the data starts on 2024-01-10. February 2024 has 1,392. March 2024 has 1,562. From February 2024 to October 2026 the monthly counts stay between 1,387 and 1,573. October 2026 has 1,436. November 2026 has 441, because it only covers 1 to 9 November.

Trap: `subscriber.registration_timestamp` comes 1 to 14 days before the first subscription. Only 37,609 of the 50,000 subscribers have a registration in the same calendar month as the first activation. Using the registration month gives a different sign-up count.

**Status meaning of subscription rows.** Each row in `subscription` has one of three statuses.

| Status | Rows | Plan types in those rows | What it means |
|---|---|---|---|
| `Active` | 36,829 | 29,946 paid and 6,883 free | The current plan. Each subscriber with an active row has exactly one. |
| `Cancelled` | 13,171 | 10,222 paid and 2,949 free | The last row of a subscriber who left. `termination_date` is the churn date. |
| `Superseded` | 13,339 | 10,593 paid and 2,746 free | A row that ended because the subscriber moved to another plan. |

Every `Superseded` row has a next row for the same subscriber that starts on its `termination_date`. There is no separate upgrade flag. To classify a plan change, compare the service tiers of the two rows.

```sql
WITH tier_rank AS (
  SELECT subscription_plan_id,
         CASE service_tier WHEN 'Free' THEN 0 WHEN 'Fan' THEN 1 WHEN 'Mega Fan' THEN 2 WHEN 'Ultimate Fan' THEN 3 END AS rank_no
  FROM <catalog>.hoshi_subscriber.subscription_plan
),
moves AS (
  SELECT old_row.subscription_id, ro.rank_no AS old_rank, rn.rank_no AS new_rank
  FROM <catalog>.hoshi_subscriber.subscription AS old_row
  JOIN <catalog>.hoshi_subscriber.subscription AS new_row
    ON new_row.subscriber_id = old_row.subscriber_id
   AND new_row.activation_date = old_row.termination_date
  JOIN tier_rank AS ro ON ro.subscription_plan_id = old_row.subscription_plan_id
  JOIN tier_rank AS rn ON rn.subscription_plan_id = new_row.subscription_plan_id
  WHERE old_row.subscription_status = 'Superseded'
)
SELECT CASE WHEN old_rank = 0 THEN 'free to paid'
            WHEN new_rank > old_rank THEN 'tier up'
            WHEN new_rank < old_rank THEN 'tier down'
            ELSE 'same tier' END AS move,
       COUNT(*) AS changes
FROM moves
GROUP BY 1
ORDER BY 1
```

Results: free to paid 2,746. Tier up 4,710. Tier down 4,021. Same tier (a switch between monthly and annual) 1,862. The four numbers add up to 13,339.

**Plan and tier now.** Use the row with `subscription_status = 'Active'`. The `subscriber.service_tier` column is the tier of the last plan. It matches the active plan for all 36,829 active subscribers. For the 13,171 cancelled subscribers it is the tier of the plan they had when they left.

```sql
SELECT p.plan_code, COUNT(*) AS subscribers
FROM <catalog>.hoshi_subscriber.subscription AS s
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = s.subscription_plan_id
WHERE s.subscription_status = 'Active'
GROUP BY p.plan_code
ORDER BY p.plan_code
```

Result: FAN-A 4,201. FAN-M 10,711. FREE 6,883. MEGA-A 3,248. MEGA-M 6,113. ULT-A 2,716. ULT-M 2,957.

**Plan on an earlier date.** Use the same date test as for active paying subscribers.

```sql
SELECT p.plan_code, COUNT(*) AS subscribers
FROM <catalog>.hoshi_subscriber.subscription AS s
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = s.subscription_plan_id
WHERE s.activation_date <= DATE'2025-11-10'
  AND (s.termination_date IS NULL OR s.termination_date > DATE'2025-11-10')
GROUP BY p.plan_code
ORDER BY p.plan_code
```

Result on 2025-11-10: FAN-A 2,936. FAN-M 7,921. FREE 5,471. MEGA-A 2,159. MEGA-M 4,324. ULT-A 1,903. ULT-M 2,163.

Trap: the list `base_price` in `subscription_plan` is not what LATAM subscribers pay after the price rise. For LATAM, active rows from 2026-05-10 onward carry the new price (Fan monthly 9.99 instead of 7.99, Fan annual 99.99 instead of 79.99). Use `subscription.base_rate_amount` or `invoice.subtotal_amount` for what a customer pays.

### 3.3 Churn

A churn is a `churn_event` row. There is one churn event for each `Cancelled` subscription row, and the churn date equals the termination date. The table holds 13,171 churn events. Of these, 11,947 are `Voluntary` and 1,224 are `Involuntary`. Churn includes free subscribers. All 2,949 free churns are `Voluntary`. All 1,224 involuntary churns are paid.

**Churn rate by month, paid plans.** The rate is paid churns in the month divided by paid subscribers active at the start of the month.

```sql
WITH months AS (
  SELECT explode(sequence(DATE'2024-02-01', DATE'2026-11-01', INTERVAL 1 MONTH)) AS month_start
),
active_at_start AS (
  SELECT m.month_start, COUNT(*) AS paid_active_at_start
  FROM months AS m
  JOIN <catalog>.hoshi_subscriber.subscription AS s
    ON s.activation_date < m.month_start
   AND (s.termination_date IS NULL OR s.termination_date >= m.month_start)
  JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
    ON p.subscription_plan_id = s.subscription_plan_id AND p.plan_type = 'Paid'
  GROUP BY m.month_start
),
churned AS (
  SELECT DATE_TRUNC('MONTH', c.churn_timestamp) AS month_start,
         COUNT(*) AS paid_churns,
         SUM(CASE WHEN c.churn_type = 'Voluntary' THEN 1 ELSE 0 END) AS voluntary,
         SUM(CASE WHEN c.churn_type = 'Involuntary' THEN 1 ELSE 0 END) AS involuntary
  FROM <catalog>.hoshi_subscriber.churn_event AS c
  JOIN <catalog>.hoshi_subscriber.subscription AS s
    ON s.subscription_id = c.subscription_id
  JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
    ON p.subscription_plan_id = s.subscription_plan_id AND p.plan_type = 'Paid'
  GROUP BY 1
)
SELECT a.month_start, a.paid_active_at_start, c.paid_churns, c.voluntary, c.involuntary,
       ROUND(c.paid_churns * 100.0 / a.paid_active_at_start, 2) AS churn_pct
FROM active_at_start AS a
LEFT JOIN churned AS c ON c.month_start = a.month_start
ORDER BY a.month_start
```

Results for the last 13 calendar months (month, paid active at start, paid churns, voluntary, involuntary, churn percent):

| Month | Paid active at start | Paid churns | Voluntary | Involuntary | Churn percent |
|---|---|---|---|---|---|
| 2025-11 | 21,116 | 384 | 337 | 47 | 1.82 |
| 2025-12 | 21,913 | 404 | 354 | 50 | 1.84 |
| 2026-01 | 22,674 | 392 | 345 | 47 | 1.73 |
| 2026-02 | 23,503 | 395 | 349 | 46 | 1.68 |
| 2026-03 | 24,242 | 465 | 404 | 61 | 1.92 |
| 2026-04 | 25,025 | 447 | 398 | 49 | 1.79 |
| 2026-05 | 25,818 | 675 | 582 | 93 | 2.61 |
| 2026-06 | 26,438 | 715 | 606 | 109 | 2.70 |
| 2026-07 | 26,947 | 571 | 496 | 75 | 2.12 |
| 2026-08 | 27,626 | 493 | 417 | 76 | 1.78 |
| 2026-09 | 28,324 | 502 | 426 | 76 | 1.77 |
| 2026-10 | 29,028 | 533 | 457 | 76 | 1.84 |
| 2026-11 (1 to 9 days) | 29,702 | 139 | 122 | 17 | 0.47 |

The November 2026 row is partial and its rate is not comparable with the others. Apart from May and June 2026, every full month from November 2025 to October 2026 has a rate between 1.68 and 2.12 percent.

**Churn reasons.** Reasons are in `cancellation_reason_code`. Across all 13,171 churn events:

| Code | Churn events |
|---|---|
| `content` | 3,384 |
| `not_using` | 2,983 |
| `competitor` | 2,706 |
| `other` | 1,632 |
| `technical` | 1,476 |
| `price` | 990 |

```sql
SELECT cancellation_reason_code, COUNT(*) AS churn_events
FROM <catalog>.hoshi_subscriber.churn_event
GROUP BY cancellation_reason_code
ORDER BY churn_events DESC
```

Trap: `price` is rare overall (990 of 13,171 churns). Between 2026-05-10 and 2026-07-10, 684 of those 990 happen, and 652 of the 684 are LATAM subscribers (see story S1 in section 4).

Trap: `churn_type` is not a clean signal of a failed payment. All 1,224 involuntary churns have at least one failed payment. But 1,242 voluntary churns also have at least one failed payment. Do not treat "has a failed payment" as the same thing as "involuntary".

### 3.4 Revenue

**Billed and collected revenue by month.** Each invoice belongs to the month of `invoice_date`. `total_amount_due` includes tax. `amount_paid` is 0 for an invoice whose payment failed. Annual plans have one invoice a year, so annual revenue lands in one month and makes that month look high.

```sql
SELECT DATE_TRUNC('MONTH', invoice_date) AS invoice_month,
       COUNT(*) AS invoices,
       ROUND(SUM(subtotal_amount), 0) AS subtotal,
       ROUND(SUM(tax_amount), 0) AS tax,
       ROUND(SUM(total_amount_due), 0) AS billed,
       ROUND(SUM(amount_paid), 0) AS collected
FROM <catalog>.hoshi_billing.invoice
WHERE invoice_date >= DATE'2026-01-01'
GROUP BY 1
ORDER BY 1
```

Results (billed and collected in US dollars, rounded to the dollar):

| Month | Invoices | Subtotal | Tax | Billed | Collected |
|---|---|---|---|---|---|
| 2026-01 | 17,569 | 279,860 | 27,756 | 306,002 | 296,608 |
| 2026-02 | 16,426 | 268,096 | 26,544 | 293,016 | 284,757 |
| 2026-03 | 18,656 | 299,929 | 29,506 | 326,882 | 317,334 |
| 2026-04 | 18,563 | 295,510 | 29,237 | 323,406 | 313,149 |
| 2026-05 | 19,652 | 325,735 | 32,196 | 355,906 | 345,631 |
| 2026-06 | 19,315 | 317,115 | 31,074 | 346,200 | 335,175 |
| 2026-07 | 20,333 | 333,126 | 32,938 | 364,552 | 353,745 |
| 2026-08 | 20,831 | 340,632 | 33,959 | 373,173 | 362,784 |
| 2026-09 | 20,691 | 344,731 | 34,027 | 376,589 | 364,454 |
| 2026-10 | 21,721 | 351,540 | 34,807 | 384,666 | 372,399 |
| 2026-11 (1 to 9 days) | 6,463 | 106,030 | 10,414 | 116,003 | 112,045 |

For revenue without tax, use `subtotal_amount - discount_amount`. Every invoice satisfies `subtotal_amount - discount_amount + tax_amount = total_amount_due` (420,289 of 420,289 invoices tie).

**Monthly recurring revenue (MRR).** MRR is the sum of the monthly price of every paid subscription that is active, where an annual plan counts at one twelfth of its price. The price used is `base_rate_amount`, which already includes the LATAM price rise.

```sql
SELECT ROUND(SUM(CASE WHEN s.subscription_type = 'Annual' THEN s.base_rate_amount / 12
                      ELSE s.base_rate_amount END), 2) AS mrr_usd
FROM <catalog>.hoshi_subscriber.subscription AS s
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = s.subscription_plan_id
WHERE s.subscription_status = 'Active'
  AND p.plan_type = 'Paid'
```

Result: MRR on 2026-11-10 is 318,732.72 US dollars for 29,946 paid subscribers.

MRR by month, measured on the last day of each month:

```sql
WITH months AS (
  SELECT explode(sequence(DATE'2024-01-01', DATE'2026-11-01', INTERVAL 1 MONTH)) AS month_start
)
SELECT m.month_start,
       ROUND(SUM(CASE WHEN s.subscription_type = 'Annual' THEN s.base_rate_amount / 12
                      ELSE s.base_rate_amount END), 0) AS mrr_usd,
       COUNT(*) AS paid_subscriptions
FROM months AS m
JOIN <catalog>.hoshi_subscriber.subscription AS s
  ON s.activation_date <= LAST_DAY(m.month_start)
 AND (s.termination_date IS NULL OR s.termination_date > LAST_DAY(m.month_start))
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = s.subscription_plan_id AND p.plan_type = 'Paid'
GROUP BY m.month_start
ORDER BY m.month_start
```

Results: 2025-11 is 231,472 (21,913 paid subscriptions). 2026-05 is 281,489 (26,438). 2026-10 is 316,043 (29,702). 2026-11 is 318,733 (29,946). From late 2025 to April 2026 MRR rose by 8,000 to 9,000 dollars a month. From May 2026 the monthly rise is smaller, between about 5,000 and 7,600 dollars.

**Failed payments.** A failed payment has `payment_status = 'Failed'`. The `payment.amount` column still holds the full amount, so do not add it up as revenue.

```sql
SELECT ROUND(SUM(p.amount), 2) AS payment_amount_all,
       ROUND(SUM(CASE WHEN p.payment_status = 'Succeeded' THEN p.amount ELSE 0 END), 2) AS succeeded_amount,
       ROUND(SUM(i.amount_paid), 2) AS invoice_amount_paid
FROM <catalog>.hoshi_billing.payment AS p
JOIN <catalog>.hoshi_billing.invoice AS i
  ON i.invoice_id = p.invoice_id
```

Result: payment amount for all attempts is 7,490,211.43. Succeeded payments add up to 7,259,681.26, which equals the sum of `amount_paid` on invoices. Failed invoices are never retried. They stay as `Overdue` (12,773 invoices, 224,464 dollars, all due before the as-of date) or as `Open` (312 invoices, 6,067 dollars, due on or after 2026-11-10).

**Refunds by month.** Count a refund in the month it was processed, and only when `refund_status = 'Processed'`.

```sql
SELECT DATE_TRUNC('MONTH', processing_date) AS processed_month,
       ROUND(SUM(amount), 0) AS refunded_usd
FROM <catalog>.hoshi_billing.refund
WHERE refund_status = 'Processed'
  AND processing_date >= DATE'2026-01-01'
GROUP BY 1
ORDER BY 1
```

Results: January 2026 is 19,704. September 2026 is 28,240. October 2026 is 27,173. November 2026 (1 to 9 days) is 8,440.

### 3.5 Payment failure rate by method

```sql
SELECT method_type,
       COUNT(*) AS payments,
       SUM(CASE WHEN payment_status = 'Failed' THEN 1 ELSE 0 END) AS failed,
       ROUND(SUM(CASE WHEN payment_status = 'Failed' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS failure_percent
FROM <catalog>.hoshi_billing.payment
GROUP BY method_type
ORDER BY failure_percent DESC
```

Results (all payments, all dates):

| Method | Payments | Failed | Failure percent |
|---|---|---|---|
| Direct Debit | 51,931 | 3,841 | 7.40 |
| Debit Card | 58,051 | 1,506 | 2.59 |
| Gift Card | 25,206 | 637 | 2.53 |
| Credit Card | 210,022 | 5,263 | 2.51 |
| PayPal | 75,079 | 1,838 | 2.45 |

Direct Debit fails at about three times the rate of any other method. Each method has one failure reason. Direct Debit fails with `Mandate rejected`, Credit Card with `Card declined`, Debit Card with `Insufficient funds`, PayPal with `Payment method not funded`, and Gift Card with `Gift card balance exhausted`.

Failure rates by subscriber region are close together: APAC 3.27 percent, EMEA 3.09, NA 3.07 and LATAM 3.01.

### 3.6 Refunds and annual plans

A refund is a `refund` row linked to an invoice. Refunds cluster on annual plans. Among annual invoices about one in five is refunded. Among monthly invoices it is under one in a hundred.

```sql
SELECT p.plan_code,
       CASE WHEN p.contract_term_months = 12 THEN 'annual' ELSE 'monthly' END AS cycle,
       COUNT(*) AS invoices,
       COUNT(r.refund_id) AS refunds,
       ROUND(COUNT(r.refund_id) * 100.0 / COUNT(*), 2) AS refund_percent
FROM <catalog>.hoshi_billing.invoice AS i
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = i.subscription_plan_id
LEFT JOIN <catalog>.hoshi_billing.refund AS r
  ON r.invoice_id = i.invoice_id
GROUP BY 1, 2
ORDER BY 1
```

Results:

| Plan | Cycle | Invoices | Refunds | Refund percent |
|---|---|---|---|---|
| FAN-A | annual | 9,551 | 1,984 | 20.77 |
| FAN-M | monthly | 219,315 | 1,721 | 0.78 |
| MEGA-A | annual | 7,253 | 1,615 | 22.27 |
| MEGA-M | monthly | 118,546 | 931 | 0.79 |
| ULT-A | annual | 6,288 | 1,274 | 20.26 |
| ULT-M | monthly | 59,336 | 482 | 0.81 |

Trap: the reason `ANNUAL_CANCEL_WINDOW` (described as "Annual plan cancelled inside refund window") is not limited to annual plans. Of the 3,215 refunds with that reason, 1,978 are on annual invoices and 1,237 are on monthly invoices. Do not use the reason as a proxy for annual plans. Use the plan.

Refund status counts: 7,721 are `Processed` (530,588.56 dollars in total). 286 are `Requested`, which means no processing date yet (19,151.78 dollars). Of those 286, 194 have a request date after the as-of date.

### 3.7 Viewing

**Watch time, sessions and completion.** Watch time is `total_watch_duration_seconds` divided by 3,600. Completion can be measured in two ways.

```sql
SELECT COUNT(*) AS sessions,
       ROUND(SUM(total_watch_duration_seconds) / 3600.0, 1) AS watch_hours,
       ROUND(AVG(completion_percentage), 2) AS avg_completion_percent,
       ROUND(SUM(CASE WHEN exit_reason = 'Finished' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS finished_percent
FROM <catalog>.hoshi_distribution.playback_session
```

Result: 2,000,000 sessions. 624,413.6 watch hours. Average completion 76.69 percent. 26.25 percent of sessions end with `exit_reason = 'Finished'`.

`completion_percentage` is an average over sessions. `exit_reason = 'Finished'` is the share of sessions that reached about 90 percent. Use the average for "completion rate" unless the question asks for finishers.

**Join path for titles, series, franchise and genre.** A session points to an episode, and an episode points to a title. The title points to a series, the series holds the franchise name, and the series points to a genre. The title genre equals the series genre for all 1,200 titles.

```sql
SELECT g.name AS genre,
       ROUND(SUM(p.total_watch_duration_seconds) / 3600.0, 0) AS watch_hours,
       ROUND(SUM(p.total_watch_duration_seconds) * 100.0
             / (SELECT SUM(total_watch_duration_seconds)
                FROM <catalog>.hoshi_distribution.playback_session), 2) AS share_percent
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_content.content_episode AS e
  ON e.content_episode_id = p.content_episode_id
JOIN <catalog>.hoshi_content.title AS t
  ON t.title_id = e.title_id
JOIN <catalog>.hoshi_content.series AS s
  ON s.series_id = t.series_id
JOIN <catalog>.hoshi_content.genre AS g
  ON g.genre_id = s.genre_id
GROUP BY g.name
ORDER BY watch_hours DESC
LIMIT 8
```

Results (genre, hours, share of all watch time): Action 70,362 hours (11.27 percent). Romance 55,148 (8.83). Kids 54,514 (8.73). Music 42,587 (6.82). Supernatural 39,619 (6.34). Idol 35,770 (5.73). Sci-Fi 33,528 (5.37). Historical 23,080 (3.70).

**Top titles.** A title's watch time is the sum over all sessions of all its episodes.

```sql
WITH title_watch AS (
  SELECT e.title_id, SUM(p.total_watch_duration_seconds) AS seconds, COUNT(*) AS sessions
  FROM <catalog>.hoshi_distribution.playback_session AS p
  JOIN <catalog>.hoshi_content.content_episode AS e
    ON e.content_episode_id = p.content_episode_id
  GROUP BY e.title_id
),
total AS (SELECT SUM(seconds) AS all_seconds FROM title_watch)
SELECT t.title_id, t.name, t.content_type, t.is_simulcast,
       se.title AS series_title, se.franchise_name,
       ROUND(w.seconds / 3600.0, 0) AS watch_hours,
       ROUND(w.seconds * 100.0 / total.all_seconds, 2) AS share_percent,
       w.sessions
FROM title_watch AS w
JOIN <catalog>.hoshi_content.title AS t ON t.title_id = w.title_id
JOIN <catalog>.hoshi_content.series AS se ON se.series_id = t.series_id
CROSS JOIN total
ORDER BY w.seconds DESC
LIMIT 10
```

Results (title id, name, watch hours, share percent):

| Title id | Name | Watch hours | Share percent |
|---|---|---|---|
| 1 | Ashen Tempest | 36,413 | 5.83 |
| 2 | Crimson Carnival | 32,473 | 5.20 |
| 3 | Frost Relic Season 3 | 28,102 | 4.50 |
| 4 | Ashen Ferry | 24,975 | 4.00 |
| 5 | Moonlit Blade | 21,245 | 3.40 |
| 6 | Thorn Chronicle Season 3 | 21,229 | 3.40 |
| 7 | Quiet Tempest | 19,365 | 3.10 |
| 8 | Moonlit Blade II | 15,617 | 2.50 |
| 9 | Moonlit Blade: Second Dawn | 11,231 | 1.80 |
| 10 | Moonlit Blade: Second Dawn II | 8,117 | 1.30 |

The top 10 titles hold 35.04 percent of all watch time. Titles 5, 8, 9 and 10 all belong to the franchise `Moonlit Blade`.

**Franchise share.** Group by `franchise_name`, not by series title.

```sql
WITH title_watch AS (
  SELECT e.title_id, SUM(p.total_watch_duration_seconds) AS seconds
  FROM <catalog>.hoshi_distribution.playback_session AS p
  JOIN <catalog>.hoshi_content.content_episode AS e
    ON e.content_episode_id = p.content_episode_id
  GROUP BY e.title_id
),
total AS (SELECT SUM(seconds) AS all_seconds FROM title_watch)
SELECT s.franchise_name,
       COUNT(DISTINCT t.title_id) AS titles,
       COUNT(DISTINCT s.series_id) AS series,
       ROUND(SUM(w.seconds) * 100.0 / MAX(total.all_seconds), 2) AS share_percent,
       ROUND(SUM(w.seconds) / 3600.0, 0) AS watch_hours
FROM title_watch AS w
JOIN <catalog>.hoshi_content.title AS t ON t.title_id = w.title_id
JOIN <catalog>.hoshi_content.series AS s ON s.series_id = t.series_id
CROSS JOIN total
WHERE s.franchise_name = 'Moonlit Blade'
GROUP BY s.franchise_name
```

Result: the franchise `Moonlit Blade` has 4 titles across 2 series. It holds 9.00 percent of watch time (56,211 hours).

**Device.** The `platform_type` column has five values. Watch hours are about equal across them.

```sql
SELECT platform_type,
       COUNT(*) AS sessions,
       ROUND(SUM(total_watch_duration_seconds) / 3600.0, 0) AS watch_hours
FROM <catalog>.hoshi_distribution.playback_session
GROUP BY platform_type
ORDER BY watch_hours DESC
```

Results: Smart TV 140,428 hours. Console 140,198. Mobile 114,811. Web browser 114,668. Tablet 114,309.

**Audio language.** Use `audio_language` for the language of the track that played.

```sql
SELECT audio_language,
       COUNT(*) AS sessions,
       ROUND(SUM(total_watch_duration_seconds) / 3600.0, 0) AS watch_hours,
       ROUND(SUM(total_watch_duration_seconds) * 100.0
             / (SELECT SUM(total_watch_duration_seconds)
                FROM <catalog>.hoshi_distribution.playback_session), 2) AS share_percent
FROM <catalog>.hoshi_distribution.playback_session
GROUP BY audio_language
ORDER BY watch_hours DESC
```

Results: Japanese 346,872 hours (55.55 percent). English 183,096 (29.32). Spanish 56,778 (9.09). Portuguese 25,647 (4.11). German 4,060 (0.65). French 3,441 (0.55). Italian 2,585 (0.41). Arabic 1,935 (0.31).

**Simulcast versus catalogue.** `title.is_simulcast` is true for 180 titles.

```sql
SELECT t.is_simulcast,
       COUNT(*) AS sessions,
       ROUND(SUM(p.total_watch_duration_seconds) / 3600.0, 0) AS watch_hours,
       ROUND(SUM(p.total_watch_duration_seconds) * 100.0
             / (SELECT SUM(total_watch_duration_seconds)
                FROM <catalog>.hoshi_distribution.playback_session), 2) AS share_percent
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_content.content_episode AS e
  ON e.content_episode_id = p.content_episode_id
JOIN <catalog>.hoshi_content.title AS t
  ON t.title_id = e.title_id
GROUP BY t.is_simulcast
```

Results: simulcast 938,160 sessions, 287,177 hours (45.99 percent). Catalogue 1,061,840 sessions, 337,236 hours (54.01 percent).

### 3.8 Licence agreements

**Active or expired, and expiring soon.** `agreement_status` is set from the expiry date at the as-of date. `Active` agreements have an expiry date on or after 2026-11-10. `Expired` agreements have an expiry date before it. Use the date for "expiring within N days".

```sql
SELECT CASE WHEN expiry_date < DATE'2026-11-10' THEN 'expired before as-of'
            WHEN expiry_date <= DATE'2026-11-10' + INTERVAL 90 DAYS THEN 'expires within 90 days'
            WHEN expiry_date <= DATE'2026-11-10' + INTERVAL 180 DAYS THEN 'expires in 91 to 180 days'
            ELSE 'later' END AS bucket,
       COUNT(*) AS agreements,
       ROUND(SUM(minimum_guarantee_amount), 0) AS minimum_guarantee_total,
       ROUND(SUM(total_license_fee), 0) AS license_fee_total
FROM <catalog>.hoshi_rights.license_agreement
GROUP BY 1
ORDER BY 1
```

Results: expired before the as-of date, 300 agreements (minimum guarantees 45,215,645 dollars, fees 114,361,371). Expires within 90 days, 45 agreements (8,100,223 and 15,735,603). Expires in 91 to 180 days, 20 agreements (2,650,200 and 8,049,966). Later, 235 agreements (34,519,027 and 96,666,036). The 45 expiring agreements have expiry dates from 2026-11-11 to 2027-02-07.

**Licensor name and fees.** The licensor is the `holder` row of `primary_license_holder_id`.

```sql
SELECT h.rights_holder_name AS licensor,
       COUNT(*) AS agreements_expiring_90_days,
       ROUND(SUM(l.total_license_fee), 0) AS license_fees
FROM <catalog>.hoshi_rights.license_agreement AS l
JOIN <catalog>.hoshi_rights.holder AS h
  ON h.holder_id = l.primary_license_holder_id
WHERE l.expiry_date >= DATE'2026-11-10'
  AND l.expiry_date <= DATE'2026-11-10' + INTERVAL 90 DAYS
GROUP BY h.rights_holder_name
ORDER BY agreements_expiring_90_days DESC
LIMIT 5
```

Results: Tsuki Studios Ltd. has 15 of the 45 expiring agreements (6,588,490 dollars in fees). Quiet Shrine Co. has 3. Several licensors have 2 each, and the rest have 1.

**Which links exist.** Checked against the data.

| From | To | Link column | Exists? |
|---|---|---|---|
| `license_agreement` | `holder` (licensor) | `primary_license_holder_id` | Yes. No null values. |
| `license_agreement` | `acquisition_deal` | `acquisition_deal_id` | Yes. 600 agreements share 300 deals, so two agreements per deal. |
| `acquisition_deal` | `partner` | `partner_id` | Yes. |
| `royalty_statement` | `license_agreement` | `license_agreement_id` | Yes. |
| `royalty_statement` | `holder` | `holder_id` | Yes. It matches the agreement's licensor on all 6,160 statements. |
| `minimum_guarantee` | `acquisition_deal` | `acquisition_deal_id` | Yes. It is one to one. |
| `content_window` | `title` | `title_id` | Yes. This is an added column (see section 6). |
| `content_window` | `territory` | `territory_id` | Yes. |
| `license_agreement` | `title` or `content_window` | none | No. |
| `license_agreement` | `territory` | none. `territory_scope` is text. | No. The values are `Worldwide`, `NA`, `LATAM`, `EMEA` and `APAC`. |

```sql
SELECT COUNT(*) AS agreements,
       COUNT(DISTINCT l.acquisition_deal_id) AS deals,
       SUM(CASE WHEN d.acquisition_deal_id IS NULL THEN 1 ELSE 0 END) AS missing_deal,
       SUM(CASE WHEN l.minimum_guarantee_amount = d.minimum_guarantee_amount THEN 1 ELSE 0 END) AS mg_same_as_deal
FROM <catalog>.hoshi_rights.license_agreement AS l
LEFT JOIN <catalog>.hoshi_partner.acquisition_deal AS d
  ON d.acquisition_deal_id = l.acquisition_deal_id
```

Result: 600 agreements, 300 deals, no missing deals. The licence's `minimum_guarantee_amount` is never equal to the deal's minimum guarantee (0 of 600). So the licence MG and the deal MG are different numbers.

A licence agreement cannot be tied to a specific title. The only title link is through `content_window`, and that table has no agreement key. To ask "which licensor supplies title X", the data cannot answer.

**Licensor and partner through the deal.** The partner is reached through the acquisition deal, not through the licensor.

```sql
SELECT p.name AS partner, COUNT(*) AS agreements, ROUND(SUM(l.total_license_fee), 0) AS license_fees
FROM <catalog>.hoshi_rights.license_agreement AS l
JOIN <catalog>.hoshi_partner.acquisition_deal AS d
  ON d.acquisition_deal_id = l.acquisition_deal_id
JOIN <catalog>.hoshi_partner.partner AS p
  ON p.partner_id = d.partner_id
GROUP BY p.name
ORDER BY agreements DESC
LIMIT 5
```

Results: Gale Orchard Partners has 36 agreements (14,467,165 dollars in fees). Velvet Carnival Partners has 32. Storm Ferry Partners has 30. Tidal Voyage Partners has 28. Velvet Lantern Partners has 24. No holder name is also a partner name.

**The metric view for licences.** `hoshi_rights.license_metrics` gives the same numbers with less SQL.

```sql
SELECT `Agreement Status`,
       MEASURE(`Agreement Count`) AS agreements,
       MEASURE(`Active Agreement Count`) AS active,
       MEASURE(`Total License Fee`) AS license_fees,
       MEASURE(`Minimum Guarantee Total`) AS minimum_guarantee_total
FROM <catalog>.hoshi_rights.license_metrics
GROUP BY `Agreement Status`
```

Results: Active, 300 agreements, 300 active, fees 120,451,605.12. Expired, 300 agreements, 0 active, fees 114,361,370.88. The `Minimum Guarantee Total` measure here sums the licence MG, not the partner MG.

### 3.9 Territory gaps

A territory gap is a title that subscribers watch in a territory where no active window covers it. A window is active when `active_flag = true`.

```sql
WITH viewed AS (
  SELECT DISTINCT e.title_id, s.territory_id
  FROM <catalog>.hoshi_distribution.playback_session AS p
  JOIN <catalog>.hoshi_content.content_episode AS e
    ON e.content_episode_id = p.content_episode_id
  JOIN <catalog>.hoshi_subscriber.subscriber AS s
    ON s.subscriber_id = p.subscriber_id
),
active_windows AS (
  SELECT DISTINCT title_id, territory_id
  FROM <catalog>.hoshi_rights.content_window
  WHERE active_flag = true
)
SELECT COUNT(*) AS viewed_title_territory_pairs,
       SUM(CASE WHEN w.title_id IS NULL THEN 1 ELSE 0 END) AS pairs_without_active_window,
       COUNT(DISTINCT CASE WHEN w.title_id IS NULL THEN v.title_id END) AS titles_with_a_gap
FROM viewed AS v
LEFT JOIN active_windows AS w
  ON w.title_id = v.title_id AND w.territory_id = v.territory_id
```

Result: 26,053 viewed title and territory pairs. 25,186 of them (96.7 percent) have no active window. 1,192 titles have at least one gap. This is almost everything, because only 663 of the 1,200 titles have any active window. Use the top 10 titles to find the planted gaps:

```sql
WITH viewed AS (
  SELECT DISTINCT e.title_id, s.territory_id
  FROM <catalog>.hoshi_distribution.playback_session AS p
  JOIN <catalog>.hoshi_content.content_episode AS e
    ON e.content_episode_id = p.content_episode_id
  JOIN <catalog>.hoshi_subscriber.subscriber AS s
    ON s.subscriber_id = p.subscriber_id
  WHERE e.title_id <= 10
),
active_windows AS (
  SELECT DISTINCT title_id, territory_id
  FROM <catalog>.hoshi_rights.content_window
  WHERE active_flag = true
)
SELECT v.title_id, t.code AS territory, t.territory_group
FROM viewed AS v
LEFT JOIN active_windows AS w
  ON w.title_id = v.title_id AND w.territory_id = v.territory_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = v.territory_id
WHERE w.title_id IS NULL
ORDER BY 1, 2
```

Result: title 1 (Ashen Tempest) has no active window in BR (Brazil) or MX (Mexico). Title 5 (Moonlit Blade) has none in PH (Philippines). Those three are the only gaps among the top 10 titles.

### 3.10 Royalty statements and amounts owed

Statements are quarterly. `statement_status` has four values: `Paid`, `Overdue`, `Issued` and `Pending`. Only `Overdue` means late. `Issued` and `Pending` are not yet due. Amounts owed are the net royalty of statements that are not paid.

```sql
SELECT statement_status,
       COUNT(*) AS statements,
       ROUND(SUM(net_royalty_amount), 2) AS net_royalty,
       SUM(CASE WHEN statement_due_date < DATE'2026-11-10' THEN 1 ELSE 0 END) AS due_before_as_of
FROM <catalog>.hoshi_rights.royalty_statement
GROUP BY statement_status
ORDER BY statement_status
```

Results: `Issued` 63 statements, 988,831.26 dollars, none due before the as-of date. `Overdue` 477, 7,703,782.97, all due before it. `Paid` 5,556, 92,034,977.49. `Pending` 64, 1,060,531.60, none due before it.

Amount owed in total (`Overdue`, `Issued` and `Pending`): 604 statements, 9,753,145.83 dollars net.

```sql
SELECT COUNT(*) AS statements,
       ROUND(SUM(net_royalty_amount), 2) AS net_owed
FROM <catalog>.hoshi_rights.royalty_statement
WHERE statement_status IN ('Overdue', 'Issued', 'Pending')
```

**Overdue by licensor.** There are 477 overdue statements across all 40 licensors. The oldest is due on 2019-07-31. The ten largest overdue balances by licensor:

```sql
SELECT h.rights_holder_name AS licensor,
       COUNT(*) AS overdue_statements,
       ROUND(SUM(rs.net_royalty_amount), 2) AS overdue_net,
       MIN(rs.statement_due_date) AS oldest_due
FROM <catalog>.hoshi_rights.royalty_statement AS rs
JOIN <catalog>.hoshi_rights.holder AS h
  ON h.holder_id = rs.holder_id
WHERE rs.statement_status = 'Overdue'
GROUP BY h.rights_holder_name
ORDER BY overdue_net DESC
LIMIT 10
```

| Licensor | Overdue statements | Overdue net | Oldest due |
|---|---|---|---|
| Tidal Relic Co. | 15 | 389,247.60 | 2020-06-22 |
| Gale Summit Co. | 14 | 356,337.82 | 2022-02-15 |
| Ember Tempest Co. | 17 | 331,819.14 | 2022-11-10 |
| Quiet Summit Co. | 18 | 307,307.49 | 2021-03-11 |
| Ember Garden Co. | 13 | 294,273.82 | 2020-12-02 |
| Tidal Sentinel Co. | 13 | 287,795.60 | 2020-01-16 |
| Lunar Rampart Co. | 21 | 276,015.76 | 2020-07-09 |
| Azure Lantern Co. | 13 | 259,582.58 | 2022-10-20 |
| Azure Vanguard Co. | 9 | 234,905.19 | 2021-07-27 |
| Hollow Carnival Co. | 18 | 231,259.18 | 2021-11-05 |

Trap: `net_royalty_amount` equals gross minus `withholding_tax_amount` on all 6,160 statements, and withholding averages 10 percent of gross. Use the net column for money owed to the licensor. Tsuki Studios Ltd. is not in the top ten. It has 188 statements in total and 185,118.11 dollars overdue.

### 3.11 Ad sales

The chain is `advertiser` to `campaign` (on `advertiser_id`) to `ad_order` (on `campaign_id`), and to `impression_delivery` (on `campaign_id`). Each campaign has a planned impression count in `campaign.target_impressions`. The order lines split that plan, but they hold a value, not an impression count.

**Ordered impressions.** An order line has `total_contracted_value` and `contracted_cpm`. Its impressions are value times 1,000 divided by CPM.

```sql
WITH ordered AS (
  SELECT campaign_id,
         SUM(total_contracted_value * 1000.0 / contracted_cpm) AS ordered_impressions
  FROM <catalog>.hoshi_sales.ad_order
  GROUP BY campaign_id
),
delivered AS (
  SELECT campaign_id, SUM(total_impressions_served) AS delivered_impressions
  FROM <catalog>.hoshi_sales.impression_delivery
  GROUP BY campaign_id
)
SELECT COUNT(*) AS campaigns,
       ROUND(SUM(c.target_impressions), 0) AS campaign_target,
       ROUND(SUM(o.ordered_impressions), 0) AS ordered_from_order_lines,
       SUM(d.delivered_impressions) AS delivered
FROM <catalog>.hoshi_sales.campaign AS c
LEFT JOIN ordered AS o ON o.campaign_id = c.campaign_id
LEFT JOIN delivered AS d ON d.campaign_id = c.campaign_id
```

Result: 900 campaigns. Campaign target 317,175. Ordered from order lines 317,173. Delivered 300,024. The order lines match the campaign target within rounding.

**Delivery ratio by advertiser.** Delivered impressions divided by ordered impressions. The biggest advertiser is Larkspur Motors.

```sql
WITH ordered AS (
  SELECT campaign_id, SUM(total_contracted_value * 1000.0 / contracted_cpm) AS ordered_impressions
  FROM <catalog>.hoshi_sales.ad_order
  GROUP BY campaign_id
),
delivered AS (
  SELECT campaign_id, SUM(total_impressions_served) AS delivered_impressions
  FROM <catalog>.hoshi_sales.impression_delivery
  GROUP BY campaign_id
)
SELECT a.trade_name AS advertiser,
       COUNT(DISTINCT c.campaign_id) AS campaigns,
       ROUND(SUM(o.ordered_impressions), 0) AS ordered_impressions,
       ROUND(SUM(d.delivered_impressions), 0) AS delivered_impressions,
       ROUND(SUM(d.delivered_impressions) * 100.0 / SUM(o.ordered_impressions), 1) AS delivered_percent_of_ordered
FROM <catalog>.hoshi_sales.campaign AS c
JOIN <catalog>.hoshi_sales.advertiser AS a ON a.advertiser_id = c.advertiser_id
LEFT JOIN ordered AS o ON o.campaign_id = c.campaign_id
LEFT JOIN delivered AS d ON d.campaign_id = c.campaign_id
GROUP BY a.trade_name
ORDER BY delivered_impressions DESC
LIMIT 6
```

Results:

| Advertiser | Campaigns | Ordered | Delivered | Delivered percent of ordered |
|---|---|---|---|---|
| Larkspur Motors | 30 | 45,266 | 31,682 | 70.0 |
| Crimson Circuit | 7 | 3,997 | 3,929 | 98.3 |
| Neon Voyage | 9 | 3,782 | 3,734 | 98.7 |
| Azure Orchard | 6 | 3,593 | 3,690 | 102.7 |
| Neon Relic | 7 | 3,586 | 3,492 | 97.4 |
| Ember Lantern | 7 | 3,456 | 3,414 | 98.8 |

The other 870 campaigns deliver between 92.0 and 106.3 percent of target, with an average of 98.9 percent. All 30 Larkspur campaigns deliver 69.9 to 70.0 percent.

**CPM by campaign type.** Use `cpm_realized`, the price per thousand for each impression. Do not compute CPM from `revenue_amount` (see the trap in section 6). The metric view `ad_delivery_metrics` uses the same column.

```sql
SELECT c.campaign_type,
       COUNT(*) AS impressions,
       ROUND(AVG(i.cpm_realized), 2) AS average_cpm,
       ROUND(SUM(i.cpm_realized) / 1000.0, 2) AS revenue_usd
FROM <catalog>.hoshi_sales.impression_delivery AS i
JOIN <catalog>.hoshi_sales.campaign AS c
  ON c.campaign_id = i.campaign_id
GROUP BY c.campaign_type
ORDER BY c.campaign_type
```

Results: Awareness, 86,266 impressions, CPM 12.00, revenue 1,035.15. Brand Launch, 46,065, CPM 34.00, revenue 1,566.12. Consideration, 87,595, CPM 18.00, revenue 1,576.59. Conversion, 80,098, CPM 26.00, revenue 2,082.74. The total revenue from `cpm_realized` is 6,260.60 dollars.

**Ad revenue by month.** Use the same `cpm_realized` formula. Examples: April 2026 is 315.37 dollars. October 2026 is 168.98 dollars. Ad revenue is small in this data set. Total ad revenue for the whole window is about 6,260 dollars.

```sql
SELECT DATE_TRUNC('MONTH', delivery_date) AS delivery_month,
       SUM(total_impressions_served) AS impressions,
       ROUND(SUM(cpm_realized) / 1000.0, 2) AS revenue_usd
FROM <catalog>.hoshi_sales.impression_delivery
GROUP BY 1
ORDER BY 1
```

**Only free viewers see ads.** Impressions exist only on sessions with ad breaks, which means the free plan.

```sql
SELECT COUNT(DISTINCT i.playback_session_id) AS sessions_with_ads,
       COUNT(*) AS impressions,
       SUM(CASE WHEN p.ad_breaks_served_count = 0 THEN 1 ELSE 0 END) AS impressions_on_sessions_without_ads
FROM <catalog>.hoshi_sales.impression_delivery AS i
JOIN <catalog>.hoshi_distribution.playback_session AS p
  ON p.playback_session_id = i.playback_session_id
```

Result: 300,024 impressions on 211,522 sessions. Zero impressions on sessions without ad breaks. Use `COUNT(DISTINCT playback_session_id)` for sessions with ads.

**Metric view for ad delivery.** `hoshi_sales.ad_delivery_metrics` is the easiest route to delivered impressions, viewability and CPM by campaign objective.

```sql
SELECT `Campaign Objective`,
       MEASURE(`Impressions Delivered`) AS impressions,
       MEASURE(`Average CPM`) AS average_cpm,
       MEASURE(`Viewability Rate`) AS viewability_rate
FROM <catalog>.hoshi_sales.ad_delivery_metrics
GROUP BY `Campaign Objective`
ORDER BY 1
```

Results: Awareness 86,266 impressions, CPM 11.9995, viewability 0.720. Brand Launch 46,065, CPM 33.998, viewability 0.723. Consideration 87,595, CPM 17.9986, viewability 0.720. Conversion 80,098, CPM 26.0024, viewability 0.721. The metric view keeps more decimal places than the direct query above, which rounds to two decimals.

**Net order value.** `ad_order.net_order_value` is always 85 percent of `total_contracted_value`. Total gross is 6,624.50 and net is 5,630.71 dollars. The campaign budget (`total_budget_amount`) is the target impressions times the target CPM, so it is a plan, not spend.

### 3.12 Minimum guarantee recoupment

Each `minimum_guarantee` belongs to one `acquisition_deal`, and each deal belongs to one `partner`. Recouped is `recouped_to_date_amount`. Outstanding is `outstanding_balance_amount`.

```sql
SELECT p.partner_type,
       d.deal_type,
       COUNT(*) AS minimum_guarantees,
       ROUND(SUM(m.mg_amount), 0) AS mg_total,
       ROUND(SUM(m.recouped_to_date_amount), 0) AS recouped,
       ROUND(SUM(m.outstanding_balance_amount), 0) AS outstanding,
       SUM(CASE WHEN m.mg_status = 'Recouping' THEN 1 ELSE 0 END) AS not_recouped,
       ROUND(SUM(m.recouped_to_date_amount) * 100.0 / SUM(m.mg_amount), 1) AS recouped_percent
FROM <catalog>.hoshi_partner.minimum_guarantee AS m
JOIN <catalog>.hoshi_partner.acquisition_deal AS d
  ON d.acquisition_deal_id = m.acquisition_deal_id
JOIN <catalog>.hoshi_partner.partner AS p
  ON p.partner_id = d.partner_id
GROUP BY p.partner_type, d.deal_type
ORDER BY p.partner_type, d.deal_type
```

Results (partner type, deal type, minimum guarantees, MG total, recouped, outstanding, not recouped, recouped percent):

| Partner type | Deal type | MGs | MG total | Recouped | Outstanding | Not recouped | Recouped percent |
|---|---|---|---|---|---|---|---|
| Broadcaster | Co-production | 15 | 4,033,387 | 3,424,223 | 609,164 | 5 | 84.9 |
| Broadcaster | Library acquisition | 48 | 12,207,624 | 11,029,962 | 1,177,662 | 11 | 90.4 |
| Broadcaster | Output deal | 26 | 6,135,046 | 5,727,609 | 407,437 | 4 | 93.4 |
| Distributor | Co-production | 11 | 1,649,369 | 1,520,708 | 128,661 | 2 | 92.2 |
| Distributor | Library acquisition | 18 | 3,387,431 | 3,232,528 | 154,903 | 4 | 95.4 |
| Distributor | Output deal | 17 | 6,159,461 | 5,466,920 | 692,541 | 5 | 88.8 |
| Platform | Co-production | 22 | 4,857,558 | 4,187,018 | 670,539 | 6 | 86.2 |
| Platform | Library acquisition | 30 | 4,859,856 | 4,402,480 | 457,377 | 6 | 90.6 |
| Platform | Output deal | 22 | 6,013,858 | 4,514,383 | 1,499,475 | 5 | 75.1 |
| Studio | Co-production | 16 | 3,931,382 | 3,861,753 | 69,630 | 1 | 98.2 |
| Studio | Library acquisition | 41 | 11,498,618 | 10,602,090 | 896,528 | 6 | 92.2 |
| Studio | Output deal | 34 | 11,835,104 | 10,727,548 | 1,107,556 | 5 | 90.6 |

Across all 300 MGs, 60 are still recouping. That is 20.0 percent. The total MG is 76,568,693 dollars, of which 68,697,222 (89.7 percent) is recouped and 7,871,471 is outstanding. The partner with the largest outstanding balance is Tidal Shrine Partners, with 5 open MGs and 1,058,573 dollars outstanding.

Trap: `recoupment_percentage` is the constant 100.0 on every row. It does not show how much was recouped. Use `recouped_to_date_amount` divided by `mg_amount`. Also `fully_recouped_date` is empty for the 60 open MGs.

### 3.13 Cross-domain joins that work

These examples join at least two domains. Each one was run and the numbers below are from the output.

**Example 1. Subscribers and monthly recurring revenue by region.**

```sql
SELECT t.territory_group AS region,
       COUNT(*) AS active_paid_subscriptions,
       ROUND(SUM(CASE WHEN s.subscription_type = 'Annual' THEN s.base_rate_amount / 12
                      ELSE s.base_rate_amount END), 0) AS mrr_usd
FROM <catalog>.hoshi_subscriber.subscription AS s
JOIN <catalog>.hoshi_subscriber.subscriber AS sb
  ON sb.subscriber_id = s.subscriber_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = sb.territory_id
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = s.subscription_plan_id
WHERE s.subscription_status = 'Active' AND p.plan_type = 'Paid'
GROUP BY t.territory_group
ORDER BY 1
```

Result: APAC 7,462 subscriptions and 75,080 dollars MRR. EMEA 7,632 and 77,463. LATAM 6,291 and 79,372. NA 8,561 and 86,818. LATAM has the fewest subscribers but a higher MRR than EMEA, because of the price rise.

**Example 2. Watch hours by region and whether the title has an active window in the viewer's territory.**

```sql
WITH active_windows AS (
  SELECT DISTINCT title_id, territory_id
  FROM <catalog>.hoshi_rights.content_window
  WHERE active_flag = true
)
SELECT t.territory_group AS region,
       CASE WHEN aw.title_id IS NULL THEN 'no active window in viewer territory'
            ELSE 'active window in viewer territory' END AS window_status,
       COUNT(*) AS sessions,
       ROUND(SUM(p.total_watch_duration_seconds) / 3600.0, 0) AS watch_hours
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_content.content_episode AS e
  ON e.content_episode_id = p.content_episode_id
JOIN <catalog>.hoshi_subscriber.subscriber AS s
  ON s.subscriber_id = p.subscriber_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = s.territory_id
LEFT JOIN active_windows AS aw
  ON aw.title_id = e.title_id AND aw.territory_id = s.territory_id
WHERE t.territory_group <> 'Rights-only'
GROUP BY 1, 2
ORDER BY 1, 2
```

Results (watch hours with an active window, then without): APAC 55,832 and 98,086. EMEA 57,828 and 100,764. LATAM 46,016 and 90,992. NA 63,895 and 111,000. Most viewing happens on titles that have no active window in that territory. Only 663 of the 1,200 titles have any active window anywhere.

**Example 3. Watch hours and territories with an active window, for the first titles.**

```sql
WITH active_windows AS (
  SELECT title_id, COUNT(DISTINCT territory_id) AS active_territories
  FROM <catalog>.hoshi_rights.content_window
  WHERE active_flag = true
  GROUP BY title_id
)
SELECT t.title_id, t.name,
       COALESCE(aw.active_territories, 0) AS territories_with_active_window,
       ROUND(SUM(p.total_watch_duration_seconds) / 3600.0, 0) AS watch_hours
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_content.content_episode AS e
  ON e.content_episode_id = p.content_episode_id
JOIN <catalog>.hoshi_content.title AS t
  ON t.title_id = e.title_id
LEFT JOIN active_windows AS aw
  ON aw.title_id = t.title_id
WHERE t.title_id <= 12
GROUP BY t.title_id, t.name, aw.active_territories
ORDER BY t.title_id
```

Results: title 1 (Ashen Tempest), 20 territories with an active window, 36,413 hours. Title 5 (Moonlit Blade), 21 territories, 21,245 hours. Title 11 (Hollow Tempest), 0 territories, 4,724 hours.

**Example 4. Territory gap for titles 1 and 5.**

```sql
SELECT DISTINCT t.code AS territory, t.territory_group, v.title_id
FROM (
  SELECT DISTINCT e.title_id, s.territory_id
  FROM <catalog>.hoshi_distribution.playback_session AS p
  JOIN <catalog>.hoshi_content.content_episode AS e
    ON e.content_episode_id = p.content_episode_id
  JOIN <catalog>.hoshi_subscriber.subscriber AS s
    ON s.subscriber_id = p.subscriber_id
  WHERE e.title_id IN (1, 5)
) AS v
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = v.territory_id
WHERE NOT EXISTS (
  SELECT 1
  FROM <catalog>.hoshi_rights.content_window AS w
  WHERE w.title_id = v.title_id
    AND w.territory_id = v.territory_id
    AND w.active_flag = true
)
ORDER BY 3, 1
```

Result: title 1 has no active window in BR (LATAM) and MX (LATAM). Title 5 has none in PH (APAC).

**Example 5. Ad impressions by franchise, through the episode.** The campaign's series does not show where the ad ran (see section 6). Go from the impression to the episode, then to the title and series.

```sql
SELECT se.franchise_name,
       COUNT(*) AS impressions,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM <catalog>.hoshi_sales.impression_delivery), 2) AS share_percent
FROM <catalog>.hoshi_sales.impression_delivery AS i
JOIN <catalog>.hoshi_content.content_episode AS e
  ON e.content_episode_id = i.content_episode_id
JOIN <catalog>.hoshi_content.title AS t
  ON t.title_id = e.title_id
JOIN <catalog>.hoshi_content.series AS se
  ON se.series_id = t.series_id
WHERE se.franchise_name = 'Moonlit Blade'
GROUP BY se.franchise_name
```

Result: 27,715 impressions, 9.24 percent of all impressions.

**Example 6. Ad impressions by subscriber territory.**

```sql
SELECT t.territory_group AS region,
       COUNT(*) AS impressions,
       ROUND(SUM(i.cpm_realized) / 1000.0, 2) AS revenue_usd
FROM <catalog>.hoshi_sales.impression_delivery AS i
JOIN <catalog>.hoshi_subscriber.subscriber AS s
  ON s.subscriber_id = i.subscriber_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = s.territory_id
GROUP BY t.territory_group
ORDER BY 1
```

Results: APAC 73,164 impressions. EMEA 76,896. LATAM 66,459. NA 83,505.

**Example 7. Churn reasons by the franchise of the last title watched.**

```sql
SELECT se.franchise_name,
       c.cancellation_reason_code AS reason,
       COUNT(*) AS churn_events
FROM <catalog>.hoshi_subscriber.churn_event AS c
JOIN <catalog>.hoshi_content.title AS t
  ON t.title_id = c.last_viewed_title_id
JOIN <catalog>.hoshi_content.series AS se
  ON se.series_id = t.series_id
WHERE c.last_viewed_title_id IN (1, 2, 3, 4, 5)
GROUP BY se.franchise_name, c.cancellation_reason_code
ORDER BY se.franchise_name, churn_events DESC
```

Result for Moonlit Blade (title 5 as last viewed): content 154, competitor 138, not_using 124, other 69, technical 61, price 9. Ashen Tempest has 168 content churns, the largest single count in the table.

**Example 8. Cancellation rate by subscriber region.**

```sql
SELECT t.territory_group AS region,
       COUNT(*) AS subscribers,
       ROUND(SUM(CASE WHEN sb.account_status = 'Cancelled' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS cancelled_percent
FROM <catalog>.hoshi_subscriber.subscriber AS sb
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = sb.territory_id
GROUP BY t.territory_group
ORDER BY 1
```

Results: LATAM 30.4 percent of subscribers are cancelled, against 24.8 to 25.7 percent in the other regions (NA 24.8, APAC 25.2, EMEA 25.7).

## 3.14 Working notes for SQL writers

- Put the as-of date in the query. Use `DATE'2026-11-10'`.
- Use the `Paid` plan type for paying counts. Free subscriptions are part of the subscription table.
- Use `subscription_status` to find the current row. Use the date test to find the row at an earlier date.
- Use `invoice.amount_paid` for cash collected and `invoice.subtotal_amount` for revenue without tax.
- Use `cpm_realized` for CPM and `total_impressions_served` for impression counts.
- Use the metric views when they fit. Their numbers match the direct SQL.

## 4. Planted stories

The generator plants eight stories. Each one below has the query that checks it and the numbers from the run. Where a story is only partly true in the data, the text says so.

### S1. LATAM price rise and the churn spike

Latin American subscribers pay a higher list price from 2026-05-10, six months before the as-of date. The generator then raises churn for LATAM subscribers for two months, and most of those cancellations give `price` as the reason.

The price change shows in invoices. Average subtotal for LATAM paid invoices:

```sql
SELECT p.plan_code,
       CASE WHEN i.invoice_date >= DATE'2026-05-10' THEN 'from 2026-05-10' ELSE 'before 2026-05-10' END AS period,
       ROUND(AVG(i.subtotal_amount), 2) AS average_subtotal,
       COUNT(*) AS invoices
FROM <catalog>.hoshi_billing.invoice AS i
JOIN <catalog>.hoshi_subscriber.subscriber AS sb
  ON sb.subscriber_id = i.subscriber_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = sb.territory_id
JOIN <catalog>.hoshi_subscriber.subscription_plan AS p
  ON p.subscription_plan_id = i.subscription_plan_id
WHERE t.territory_group = 'LATAM'
  AND p.plan_type = 'Paid'
  AND i.invoice_date >= DATE'2026-01-01'
GROUP BY 1, 2
ORDER BY 1, 2
```

Results: Fan monthly was 7.99 and is 9.99 from the change. Mega Fan monthly was 11.99 and is 14.99. Ultimate Fan monthly was 15.99 and is 19.99. Fan annual was 79.99 and is 99.99. Mega Fan annual was 119.99 and is 149.99. Ultimate Fan annual was 159.99 and is 199.99. Before the change the averages equal the list prices exactly.

The churn check, by month and region, with the share of `price` reasons:

```sql
SELECT DATE_TRUNC('MONTH', c.churn_timestamp) AS churn_month,
       t.territory_group AS region,
       COUNT(*) AS churns,
       SUM(CASE WHEN c.cancellation_reason_code = 'price' THEN 1 ELSE 0 END) AS price_reason,
       ROUND(SUM(CASE WHEN c.cancellation_reason_code = 'price' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS price_percent
FROM <catalog>.hoshi_subscriber.churn_event AS c
JOIN <catalog>.hoshi_subscriber.subscriber AS s
  ON s.subscriber_id = c.subscriber_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = s.territory_id
WHERE c.churn_timestamp >= TIMESTAMP'2026-03-01'
  AND c.churn_timestamp < TIMESTAMP'2026-11-01'
  AND t.territory_group IN ('LATAM', 'NA', 'EMEA', 'APAC')
GROUP BY 1, 2
ORDER BY 1, 2
```

Results for LATAM only:

| Month | LATAM churns | Price reason | Price percent |
|---|---|---|---|
| 2026-03 | 134 | 4 | 3.0 |
| 2026-04 | 116 | 4 | 3.4 |
| 2026-05 | 358 | 222 | 62.0 |
| 2026-06 | 478 | 326 | 68.2 |
| 2026-07 | 207 | 109 | 52.7 |
| 2026-08 | 135 | 7 | 5.2 |
| 2026-09 | 124 | 2 | 1.6 |
| 2026-10 | 162 | 13 | 8.0 |

In the other regions the monthly churn stays between about 120 and 190 and the `price` share stays under 8 percent in every month. Between 2026-05-10 and 2026-07-10 there are 939 LATAM churns, and 652 of them (69.4 percent) give `price`.

Verdict: confirmed. The spike is two months long, and it starts about six months before the as-of date.

### S2. Viewing peaks at anime season starts

Season starts are January, April, July and October. Simulcast episodes are mostly watched in the first week after they air.

```sql
WITH daily AS (
  SELECT CAST(session_start_timestamp AS DATE) AS view_date, COUNT(*) AS sessions
  FROM <catalog>.hoshi_distribution.playback_session
  GROUP BY 1
)
SELECT CASE WHEN MONTH(view_date) IN (1, 4, 7, 10) AND DAY(view_date) <= 21 THEN 'season start months, day 1 to 21'
            WHEN MONTH(view_date) IN (1, 4, 7, 10) THEN 'season start months, day 22 and later'
            ELSE 'other months' END AS bucket,
       ROUND(SUM(sessions) / COUNT(*), 0) AS sessions_per_day,
       COUNT(*) AS days
FROM daily
WHERE view_date < DATE'2026-11-10'
GROUP BY 1
ORDER BY 1
```

Results: days 1 to 21 of a season-start month average 2,723 sessions a day. Later days in those months average 1,819. Other months average 1,667.

Average sessions a day by calendar month (all years in the window):

```sql
WITH daily AS (
  SELECT CAST(session_start_timestamp AS DATE) AS view_date, COUNT(*) AS sessions
  FROM <catalog>.hoshi_distribution.playback_session
  GROUP BY 1
)
SELECT MONTH(view_date) AS calendar_month,
       ROUND(AVG(sessions), 0) AS avg_sessions_per_day,
       COUNT(*) AS days
FROM daily
WHERE view_date < DATE'2026-11-10'
GROUP BY 1
ORDER BY 1
```

| Month | Average sessions a day |
|---|---|
| January | 2,089 |
| February | 1,521 |
| March | 1,539 |
| April | 2,904 |
| May | 2,090 |
| June | 2,062 |
| July | 2,668 |
| August | 1,600 |
| September | 1,448 |
| October | 2,039 |
| November | 1,502 |
| December | 1,456 |

Simulcast sessions a day by month are highest in April (1,532) and July (1,309). January is 752 and October is 968.

Simulcast timing. Lag is the number of days between the session and the episode's original air date:

```sql
SELECT CASE WHEN DATEDIFF(CAST(p.session_start_timestamp AS DATE), e.original_air_date) BETWEEN 0 AND 1 THEN '0 to 1 days'
            WHEN DATEDIFF(CAST(p.session_start_timestamp AS DATE), e.original_air_date) BETWEEN 2 AND 7 THEN '2 to 7 days'
            WHEN DATEDIFF(CAST(p.session_start_timestamp AS DATE), e.original_air_date) BETWEEN 8 AND 60 THEN '8 to 60 days'
            ELSE 'other' END AS lag,
       COUNT(*) AS sessions
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_content.content_episode AS e
  ON e.content_episode_id = p.content_episode_id
JOIN <catalog>.hoshi_content.title AS t
  ON t.title_id = e.title_id
WHERE t.is_simulcast = true
GROUP BY 1
ORDER BY 1
```

Results: 416,606 sessions (44.4 percent of 938,160) happen 0 to 1 days after air. 362,839 (38.7 percent) happen 2 to 7 days after. So 83.1 percent of simulcast sessions fall within 7 days. 158,715 (16.9 percent) come 8 to 60 days after.

Verdict: partly confirmed. Viewing does peak at season starts, and the peak is clear in April and July. January and October are above the quiet months. But May and June are about as high as January, so the peak is not limited to the four named months. The simulcast claim holds: 83 percent of simulcast viewing is within 7 days.

### S3. One franchise near 9 percent of watch time, and the top 10 titles near 35 percent

```sql
WITH title_watch AS (
  SELECT e.title_id, SUM(p.total_watch_duration_seconds) AS seconds
  FROM <catalog>.hoshi_distribution.playback_session AS p
  JOIN <catalog>.hoshi_content.content_episode AS e
    ON e.content_episode_id = p.content_episode_id
  GROUP BY e.title_id
),
ranked AS (
  SELECT seconds, ROW_NUMBER() OVER (ORDER BY seconds DESC) AS rank_no
  FROM title_watch
),
total AS (SELECT SUM(seconds) AS all_seconds FROM title_watch)
SELECT ROUND(SUM(CASE WHEN rank_no <= 10 THEN seconds ELSE 0 END) * 100.0 / MAX(total.all_seconds), 2) AS top10_share_percent,
       ROUND(SUM(CASE WHEN rank_no <= 10 THEN seconds ELSE 0 END) / 3600.0, 0) AS top10_watch_hours
FROM ranked
CROSS JOIN total
```

Result: the top 10 titles hold 35.04 percent of watch time (218,767 hours).

The franchise check is in section 3.7. The franchise `Moonlit Blade` holds 9.00 percent of watch time across four titles and two series.

Verdict: confirmed.

### S4. Dub versus sub by region

```sql
SELECT t.territory_group AS region,
       COUNT(*) AS sessions,
       ROUND(SUM(CASE WHEN p.audio_language = 'Japanese' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS japanese_audio_percent,
       ROUND(SUM(CASE WHEN p.audio_language <> 'Japanese' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS dubbed_percent,
       ROUND(SUM(CASE WHEN p.subtitle_language IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS subtitles_on_percent
FROM <catalog>.hoshi_distribution.playback_session AS p
JOIN <catalog>.hoshi_subscriber.subscriber AS s
  ON s.subscriber_id = p.subscriber_id
JOIN <catalog>.hoshi_rights.territory AS t
  ON t.territory_id = s.territory_id
GROUP BY t.territory_group
ORDER BY 1
```

| Region | Sessions | Japanese audio percent | Dubbed percent | Subtitles on percent |
|---|---|---|---|---|
| APAC | 493,434 | 85.0 | 15.0 | 85.0 |
| EMEA | 508,015 | 58.1 | 41.9 | 58.1 |
| LATAM | 438,579 | 42.0 | 58.0 | 42.0 |
| NA | 559,972 | 38.0 | 62.0 | 38.0 |

Every Japanese audio session has subtitles on, in English, Spanish, Korean or Portuguese. Every dubbed session has no subtitles at all (`subtitle_language` is NULL), so the subtitle share and the Japanese audio share are the same number.

Verdict: confirmed. Dubs are most common in NA and LATAM. APAC is mostly Japanese audio.

### S5. Payment method with about 3x the failure rate, and refunds on annual plans

```sql
SELECT method_type,
       COUNT(*) AS payments,
       ROUND(SUM(CASE WHEN payment_status = 'Failed' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS failure_percent
FROM <catalog>.hoshi_billing.payment
GROUP BY method_type
ORDER BY failure_percent DESC
```

Result: Direct Debit fails at 7.40 percent. The others fail at 2.45 to 2.59 percent. That is about 2.9 to 3.0 times the rate, so "about 3x" holds.

The refund check is in section 3.6. Annual plans refund 20.3 to 22.3 percent of invoices. Monthly plans refund 0.8 percent.

Verdict: confirmed.

### S6. Licences expiring soon, territory gaps and overdue royalties

Expiring agreements:

```sql
SELECT COUNT(*) AS agreements_expiring_90_days,
       MIN(expiry_date) AS first_expiry,
       MAX(expiry_date) AS last_expiry,
       SUM(CASE WHEN primary_license_holder_id = 1 THEN 1 ELSE 0 END) AS from_tsuki_studios
FROM <catalog>.hoshi_rights.license_agreement
WHERE expiry_date >= DATE'2026-11-10'
  AND expiry_date <= DATE'2026-11-10' + INTERVAL 90 DAYS
```

Result: 45 agreements expire between 2026-11-11 and 2027-02-07. Of these, 15 come from licensor 1, Tsuki Studios Ltd. That is one third.

Territory gaps for the top titles are in section 3.9. Title 1 has no active window in BR and MX. Title 5 has none in PH.

Overdue royalty statements: 477 statements, with net owed of 7,703,782.97 dollars, across all 40 licensors (section 3.10).

Verdict: confirmed.

### S7. One large advertiser delivered about 70 percent of ordered impressions, and CPM differs by campaign type

```sql
WITH ordered AS (
  SELECT campaign_id, SUM(total_contracted_value * 1000.0 / contracted_cpm) AS ordered_impressions
  FROM <catalog>.hoshi_sales.ad_order
  GROUP BY campaign_id
),
delivered AS (
  SELECT campaign_id, SUM(total_impressions_served) AS delivered_impressions
  FROM <catalog>.hoshi_sales.impression_delivery
  GROUP BY campaign_id
)
SELECT a.trade_name AS advertiser,
       ROUND(SUM(o.ordered_impressions), 0) AS ordered_impressions,
       ROUND(SUM(d.delivered_impressions), 0) AS delivered_impressions,
       ROUND(SUM(d.delivered_impressions) * 100.0 / SUM(o.ordered_impressions), 1) AS delivered_percent_of_ordered
FROM <catalog>.hoshi_sales.campaign AS c
JOIN <catalog>.hoshi_sales.advertiser AS a ON a.advertiser_id = c.advertiser_id
LEFT JOIN ordered AS o ON o.campaign_id = c.campaign_id
LEFT JOIN delivered AS d ON d.campaign_id = c.campaign_id
WHERE a.trade_name = 'Larkspur Motors'
GROUP BY a.trade_name
```

Result: Larkspur Motors ordered 45,266 impressions and delivered 31,682, which is 70.0 percent. Its 30 campaigns each deliver 69.9 to 70.0 percent. Every other campaign delivers between 92.0 and 106.3 percent of its target.

CPM by campaign type is in section 3.11. Awareness is 12.00, Consideration 18.00, Conversion 26.00 and Brand Launch 34.00.

Verdict: confirmed.

### S8. About 20 percent of minimum guarantees not recouped

```sql
SELECT COUNT(*) AS minimum_guarantees,
       SUM(CASE WHEN mg_status = 'Recouping' THEN 1 ELSE 0 END) AS not_recouped,
       ROUND(SUM(CASE WHEN mg_status = 'Recouping' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS not_recouped_percent,
       ROUND(SUM(recouped_to_date_amount) * 100.0 / SUM(mg_amount), 1) AS recouped_percent
FROM <catalog>.hoshi_partner.minimum_guarantee
```

Result: 300 minimum guarantees, 60 not recouped (20.0 percent). Recouped share of the money is 89.7 percent. The breakdown by partner and deal type is in section 3.12.

Verdict: confirmed.


## 5. Categorical values

Each table below lists the distinct values of every text or boolean column that has 25 or fewer distinct values. The number in brackets is the row count. NULL means the value is empty.

Columns where every row has its own value are not listed. These are codes, names and descriptions. The lists for them are:

- Plan codes (one row each): FREE, FAN-M, MEGA-M, ULT-M, FAN-A, MEGA-A, ULT-A.
- Platform codes (one row each): HS-NA-WM, HS-NA-TV, HS-LATAM-WM, HS-LATAM-TV, HS-EMEA-WM, HS-EMEA-TV, HS-APAC-WM, HS-APAC-TV.
- Genre names (one row each): Action, Adventure, Comedy, Drama, Fantasy, Historical, Horror, Idol, Isekai, Kids, Mecha, Military, Music, Mystery, Psychological, Romance, School Life, Sci-Fi, Seinen, Shojo, Shonen, Slice of Life, Sports, Supernatural, Thriller.

Text columns with more than 25 distinct values, such as titles, series names, person names and street-level text, are not listed. The `hoshi_talent` schema is not profiled.

### hoshi_subscriber

| Table | Column | Distinct values (rows) |
|---|---|---|
| churn_event | cancellation_reason_code | content (3384), not_using (2983), competitor (2706), other (1632), technical (1476), price (990) |
| churn_event | cancellation_reason_description | Not enough new shows to keep watching (3384), Stopped watching (2983), Moved to another streaming service (2706), Other reason (1632), Playback or app problems (1476), Price increase was too high for the value (990) |
| churn_event | churn_type | Voluntary (11947), Involuntary (1224) |
| churn_event | service_tier | Fan (5470), Mega Fan (3092), Free (2949), Ultimate Fan (1660) |
| offer | offer_status | Expired (20) |
| offer | offer_type | Bundle (5), Discount (5), Free trial (5), Win-back (5) |
| offer_redemption | discount_type | Bundle (3110), Free trial (3018), Discount (2940), Win-back (2932) |
| offer_redemption | first_time_subscriber_flag | true (7322), false (4678) |
| offer_redemption | redemption_channel | Web (4726), App (4233), Partner (1817), Customer care (1224) |
| offer_redemption | redemption_status | Applied (10265), Expired (938), Reversed (797) |
| subscriber | account_status | Active (36829), Cancelled (13171) |
| subscriber | billing_cycle | Monthly (28911), Annual (11257), Not billed (9832) |
| subscriber | country_code | US (10536), JP (3680), BR (3523), GB (2807), MX (2722), DE (2646), FR (2260), ES (2054), CA (2040), IN (2015), KR (1941), AU (1760), PH (1707), IT (1673), AR (1543), CO (1390), AE (1249), SG (1171), PR (965), PE (961), CL (924), BS (433) |
| subscriber | marketing_opt_in | true (29907), false (20093) |
| subscriber | preferred_language | English (22469), Spanish (10559), Japanese (3680), Portuguese (3523), German (2646), French (2260), Korean (1941), Italian (1673), Arabic (1249) |
| subscriber | registration_source | Web (15107), iOS app (10092), Android app (9954), Partner bundle (7429), Smart TV (7418) |
| subscriber | service_tier | Fan (20382), Mega Fan (12453), Free (9832), Ultimate Fan (7333) |
| subscription | acquisition_channel | Organic search (18838), Paid social (12964), App store (9550), Free trial (9484), Referral (6272), Partner bundle (6231) |
| subscription | auto_renew_flag | false (33393), true (29946) |
| subscription | currency_code | USD (63339) |
| subscription | promotional_rate_flag | false (60781), true (2558) |
| subscription | subscription_status | Active (36829), Superseded (13339), Cancelled (13171) |
| subscription | subscription_type | Monthly (36067), Annual (14694), Free (12578) |
| subscription_plan | ad_supported | false (6), true (1) |
| subscription_plan | currency_code | USD (7) |
| subscription_plan | plan_status | Active (7) |
| subscription_plan | plan_type | Paid (6), Free (1) |
| subscription_plan | service_tier | Fan (2), Mega Fan (2), Ultimate Fan (2), Free (1) |

### hoshi_billing

| Table | Column | Distinct values (rows) |
|---|---|---|
| invoice | currency_code | USD (420289) |
| invoice | invoice_status | Paid (407204), Overdue (12773), Open (312) |
| payment | currency_code | USD (420289) |
| payment | failure_reason | NULL (407204), Card declined (5263), Mandate rejected (3841), Payment method not funded (1838), Insufficient funds (1506), Gift card balance exhausted (637) |
| payment | gateway | Adyen (420289) |
| payment | is_autopay | true (377973), false (42316) |
| payment | method_type | Credit Card (210022), PayPal (75079), Debit Card (58051), Direct Debit (51931), Gift Card (25206) |
| payment | payment_status | Succeeded (407204), Failed (13085) |
| refund | currency_code | USD (8007) |
| refund | reason_code | ANNUAL_CANCEL_WINDOW (3215), CHANGED_MIND (2871), SERVICE_ISSUE (1171), DUPLICATE_CHARGE (750) |
| refund | reason_description | Annual plan cancelled inside refund window (3215), Customer changed mind (2871), Service issue (1171), Duplicate charge (750) |
| refund | refund_status | Processed (7721), Requested (286) |
| refund | refund_type | Full (5632), Partial (2375) |

### hoshi_content

| Table | Column | Distinct values (rows) |
|---|---|---|
| content_episode | episode_status | Published (14364) |
| content_episode | episode_type | Episode (14064), Feature (300) |
| content_episode | subtitles_available | true (14364) |
| content_episode | video_resolution | 1080p (10036), 4K (2882), 720p (1446) |
| genre | daypart_affinity | Prime (11), Daytime (7), Late night (7) |
| genre | is_active | true (25) |
| genre | parental_guidance_flag | false (22), true (3) |
| genre | syndication_eligibility | false (17), true (8) |
| genre | target_demographic | Teen (9), Adult (6), Kids (6), All ages (4) |
| genre | tier | Core (17), Growth (4), Niche (4) |
| genre | usage_notes | Anime genre taxonomy used for catalog and ad targeting (25) |
| season | language_original | Japanese (900) |
| season | network_original | TV Tokyo Partner Network (900) |
| season | season_status | Completed (900) |
| series | country_of_origin | JP (400) |
| series | language_original | Japanese (400) |
| series | original_network | TV Tokyo Partner Network (400) |
| series | production_company | Akari Pictures (114), Kaze Animation (109), Tsuki Studio (100), Nishi Works (77) |
| series | series_status | Completed (249), Ongoing (151) |
| series | series_type | Television (329), OVA (42), Web series (29) |
| title | content_status | Active (1200) |
| title | content_type | Series (900), Film (150), Special (150) |
| title | country_of_origin | JP (1200) |
| title | is_simulcast | false (1020), true (180) |
| title | original_language | Japanese (1200) |
| title | parental_advisory_flag | false (1016), true (184) |
| title | premiere_flag | false (1120), true (80) |

### hoshi_distribution

| Table | Column | Distinct values (rows) |
|---|---|---|
| ott_platform | billing_currency | USD (8) |
| ott_platform | drm_system | Widevine, FairPlay, PlayReady (8) |
| ott_platform | max_video_resolution | 1080p (4), 4K (4) |
| ott_platform | parent_brand | Hoshi Stream (8) |
| ott_platform | platform_status | Live (8) |
| ott_platform | primary_streaming_protocol | DASH, HLS (8) |
| ott_platform | service_tier | Standard (8) |
| playback_session | audio_language | Japanese (1111341), English (586286), Spanish (181607), Portuguese (82281), German (13006), French (10945), Italian (8301), Arabic (6233) |
| playback_session | exit_reason | Stopped (1467032), Finished (525050), Error (7918) |
| playback_session | platform_type | Smart TV (449618), Console (449375), Mobile (367470), Web browser (367332), Tablet (366205) |
| playback_session | playback_mode | Streaming (1900103), Download (99897) |
| playback_session | subtitle_language | NULL (888659), English (860590), Spanish (124946), Korean (66513), Portuguese (59292) |
| playback_session | video_resolution | 1080p (1134679), 720p (539117), 4K (326204) |

### hoshi_rights

| Table | Column | Distinct values (rows) |
|---|---|---|
| content_window | active_flag | false (1857), true (1143) |
| content_window | availability_status | Expired (1503), Active (1143), Scheduled (354) |
| content_window | blackout_flag | false (2924), true (76) |
| content_window | exclusivity_tier | Non-exclusive (1821), Exclusive (1179) |
| content_window | license_fee_currency | USD (3000) |
| content_window | window_type | SVOD (1782), AVOD (903), TVOD (315) |
| holder | entity_type | Corporation (26), Limited company (11), Sole proprietor (3) |
| holder | most_favored_nations_flag | false (30), true (10) |
| holder | preferred_currency | USD (40) |
| holder | rights_holder_status | Active (40) |
| holder | royalty_calculation_method | Gross receipts (21), Net receipts (19) |
| holder | territory_of_incorporation | JP (29), US (6), GB (3), KR (2) |
| license_agreement | agreement_status | Active (300), Expired (300) |
| license_agreement | agreement_type | Licensing (426), Output deal (118), Sublicense (56) |
| license_agreement | currency_code | USD (600) |
| license_agreement | exclusivity_flag | false (306), true (294) |
| license_agreement | territory_scope | Worldwide (195), EMEA (135), APAC (113), NA (86), LATAM (71) |
| license_agreement | windowing_strategy | SVOD first (292), AVOD first (180), Simulcast (128) |
| royalty_statement | currency_code | USD (6160) |
| royalty_statement | statement_frequency | Quarterly (6160) |
| royalty_statement | statement_status | Paid (5556), Overdue (477), Pending (64), Issued (63) |
| territory | currency_code | EUR (6), USD (3), AED (1), ARS (1), AUD (1), BRL (1), CAD (1), CLP (1), COP (1), GBP (1), INR (1), JPY (1), KRW (1), MXN (1), NZD (1), PEN (1), PHP (1), PLN (1), SEK (1), SGD (1), THB (1), TWD (1), ZAR (1) |
| territory | language_primary | English (11), Spanish (7), Arabic (1), Chinese (1), Dutch (1), French (1), German (1), Italian (1), Japanese (1), Korean (1), Polish (1), Portuguese (1), Swedish (1), Thai (1) |
| territory | territory_group | Rights-only (8), APAC (6), EMEA (6), LATAM (6), NA (4) |
| territory | territory_type | Country (30) |

### hoshi_sales

| Table | Column | Distinct values (rows) |
|---|---|---|
| ad_order | currency_code | USD (2551) |
| ad_order | order_status | Completed (2448), Live (103) |
| ad_order | order_type | Direct (1269), Programmatic (871), Upfront (411) |
| ad_order | payment_terms | Net 30 (2551) |
| advertiser | account_status | Active (150) |
| advertiser | annual_spend_tier | Tier 3 (76), Tier 2 (73), Tier 1 (1) |
| advertiser | billing_country_code | US (150) |
| advertiser | credit_status | Good standing (150) |
| advertiser | industry_category | Gaming (30), Retail (29), Telecom (24), Food and beverage (23), Automotive (22), Finance (22) |
| advertiser | is_political_advertiser | false (150) |
| advertiser | payment_terms | Net 30 (150) |
| advertiser | preferred_currency_code | USD (150) |
| campaign | campaign_status | Completed (865), Live (35) |
| campaign | campaign_type | Awareness (271), Consideration (263), Conversion (232), Brand Launch (134) |
| campaign | currency_code | USD (900) |
| campaign | priority_level | Low (326), High (287), Medium (287) |
| impression_delivery | currency_code | USD (300024) |
| impression_delivery | insertion_type | Mid-roll (210238), Pre-roll (59837), Post-roll (29949) |
| impression_delivery | verification_status | Verified (269671), Unverified (30353) |

### hoshi_partner

| Table | Column | Distinct values (rows) |
|---|---|---|
| acquisition_deal | currency_code | USD (300) |
| acquisition_deal | deal_status | Active (156), Expired (144) |
| acquisition_deal | deal_type | Library acquisition (137), Output deal (99), Co-production (64) |
| acquisition_deal | exclusivity_flag | false (180), true (120) |
| acquisition_deal | territory_coverage | Worldwide (93), APAC (70), EMEA (64), LATAM (46), NA (27) |
| minimum_guarantee | currency_code | USD (300) |
| minimum_guarantee | is_recoupable | true (300) |
| minimum_guarantee | mg_status | Recouped (240), Recouping (60) |
| minimum_guarantee | mg_type | Recoupable (175), Non-returnable (125) |
| partner | content_specialization | Romance (8), Action (6), Mecha (6), Kids (5), Sports (5) |
| partner | domicile_country_code | JP (22), GB (3), KR (3), US (2) |
| partner | is_exclusive | false (23), true (7) |
| partner | partner_type | Studio (10), Broadcaster (9), Platform (7), Distributor (4) |
| partner | relationship_status | Active (30) |
| partner | risk_tier | Low (13), Medium (10), High (7) |
| partner | strategic_tier | Strategic (17), Core (7), Opportunistic (6) |
| partner | subtype | Co-production (11), Anime studio (10), Library owner (9) |

## 6. Traps

Each trap below would give a reasonable analyst a wrong number if they did not know about it. The numbers come from the runs described in section 3 and the checks listed here.

### 6.1 Dates and the as-of date

- **Today is not the as-of date.** `CURRENT_DATE()` returns 2026-11-11. The data ends on 2026-11-09. Use `DATE'2026-11-10'`.
- **Some dates are in the future on purpose.** 194 refund requests with status `Requested` have a request date after 2026-11-10. Royalty due dates run to 2026-12-24. Licence expiry dates run to 2030.
- **Partial months.** November 2026 has only 9 days. The January 2024 sign-up count is also partial, because the data starts on 2024-01-10.
- **Registration is not sign-up.** `subscriber.registration_timestamp` is 1 to 14 days before the first subscription. 37,609 of 50,000 subscribers have the same month for both. Use the first `activation_date`.
- **Invoice date is the billing period start.** `invoice_date` equals `billing_period_start_date` on all 420,289 invoices.
- **Payment date is the invoice date.** `payment.payment_date` equals `invoice.invoice_date` on all 420,289 rows. `invoice.paid_date` comes 0 to 4 days later and is NULL for all 13,085 failed payments.
- **Playback timestamps have no time zone.** The data does not say which zone they use, so day counts for local viewing may differ (see section 8).

```sql
SELECT COUNT(*) AS invoices,
       SUM(CASE WHEN i.invoice_date = i.billing_period_start_date THEN 1 ELSE 0 END) AS invoice_date_equals_period_start,
       SUM(CASE WHEN p.payment_date = i.invoice_date THEN 1 ELSE 0 END) AS payment_date_equals_invoice_date,
       SUM(CASE WHEN i.paid_date IS NULL THEN 1 ELSE 0 END) AS paid_date_null
FROM <catalog>.hoshi_billing.invoice AS i
JOIN <catalog>.hoshi_billing.payment AS p
  ON p.invoice_id = i.invoice_id
```

Result: 420,289 invoices. All 420,289 have invoice date equal to period start. All 420,289 payments have payment date equal to invoice date. 13,085 invoices have no paid date.

### 6.2 Subscriptions and plans

- **Subscription rows are not subscribers.** There are 63,339 subscription rows for 50,000 subscribers. Superseded rows are old plan periods. Count subscribers with `COUNT(DISTINCT subscriber_id)`.
- **Free plans are in the subscription table.** There are 12,578 free rows, and 6,883 of them are active. Filter on `plan_type = 'Paid'` for paying counts.
- **The `Superseded` status is not churn.** The 13,339 superseded rows all have a next row starting on their termination date. Only `Cancelled` rows are churn.
- **List prices are not LATAM prices after May 2026.** Use `base_rate_amount` or `invoice.subtotal_amount`.
- **`subscriber.service_tier` is the tier of the last plan**, not the tier of the first plan. It is `Free` for 9,832 subscribers.

### 6.3 Revenue, billing and refunds

- **Invoice totals include tax.** `total_amount_due` equals subtotal minus discount plus tax. Total tax across all invoices is 677,216.52 dollars. Use `subtotal_amount - discount_amount` for revenue without tax.
- **`payment.amount` includes failed payments.** Total for all attempts is 7,490,211.43 dollars. Succeeded payments total 7,259,681.26 dollars, which equals the sum of `invoice.amount_paid`.
- **`payment.refund_amount` includes refunds that are only requested.** Summed over all 8,007 refund rows it matches. Processed refunds alone give a different figure.
- **Failed invoices are never recovered.** Each invoice has exactly one payment, so there are no retries. A failed invoice stays `Overdue` (12,773 invoices, 224,464 dollars, all due before the as-of date) or `Open` (312 invoices due on or after 2026-11-10). Of the 9,574 subscribers with an overdue invoice, 7,109 still have an active account.
- **Refund reason `ANNUAL_CANCEL_WINDOW` is on monthly plans too.** 1,237 of the 3,215 refunds with that reason are on monthly invoices.
- **Lifetime value does not subtract refunds.** `subscriber.ltv` equals the sum of `amount_paid` for all 40,168 paid subscribers. Refunds processed in the data total 530,588.56 dollars.

```sql
SELECT COUNT(*) AS paid_subscribers,
       SUM(CASE WHEN ROUND(sb.ltv - paid.amount_paid_total, 2) = 0 THEN 1 ELSE 0 END) AS ltv_equals_amount_paid
FROM <catalog>.hoshi_subscriber.subscriber AS sb
JOIN (
  SELECT subscriber_id, SUM(amount_paid) AS amount_paid_total
  FROM <catalog>.hoshi_billing.invoice
  GROUP BY subscriber_id
) AS paid
  ON paid.subscriber_id = sb.subscriber_id
```

Result: 40,168 subscribers have an invoice, and all 40,168 have `ltv` equal to `amount_paid`.

### 6.4 Churn

- **`churn_type` does not follow payment failures.** All 1,224 involuntary churns have at least one failed payment. But 1,242 voluntary churns also have at least one failed payment.
- **Free churn is in the churn table.** All 2,949 free churns are voluntary. Filter on plan type for paid churn.
- **Last title viewed can be empty.** 155 churn events have no `last_viewed_title_id`, because the subscriber had no session before leaving.
- **Churn has no territory column.** `churn_event` holds a platform, not a market. Get the region by joining to `subscriber.territory_id`.

### 6.5 Viewing

- **Download sessions are in the totals.** 4.99 percent of sessions are downloads. Filter on `playback_mode = 'Streaming'` if the question is about streaming.
- **Error sessions are in the totals.** 0.40 percent of sessions end with `exit_reason = 'Error'`.
- **`exit_reason = 'Finished'` is not exactly "completion of 90 percent or more".** Using `completion_percentage >= 90` gives a different count. 301 sessions show a completion percentage of 90 or more but have `exit_reason = 'Stopped'`. The likely cause is that the generator decides "Finished" on the unrounded value and then rounds the percentage to two decimals. I did not check each row to confirm.
- **Episode runtime is not title runtime.** An episode's `runtime_seconds` differs from its title's runtime by up to 120 seconds (only 364 of 14,364 episodes match). Sessions use the episode runtime in `content_duration_seconds`.
- **`vod_available_until_date` is not enforced.** 11,330 episodes have an until date before the as-of date. 906,315 sessions (45.3 percent) start after the episode's until date.
- **Some catalogue sessions start before the episode's air date.** 329 sessions are dated before `original_air_date` of their episode. All of them are on catalogue titles, not simulcast ones.
- **`subscriber.total_viewing_hours` is reliable.** It matches the sum of session watch time for all 50,000 subscribers. 1,678 subscribers have no sessions, so their `last_viewing_timestamp` and hours are empty or zero.

### 6.6 Titles, series and names

- **Titles and episodes share names.** There are 940 distinct names for 1,200 titles. Films and specials repeat their names up to 8 times. For example, `Velvet Sentinel: The Film` appears 8 times. Join on IDs, never on names.
- **Franchise is not series.** The franchise `Moonlit Blade` covers two series, `Moonlit Blade` (series 1) and `Moonlit Blade: Second Dawn` (series 2), and four titles. A title is also named `Moonlit Blade`. The series table has the franchise name, so grouping by franchise and by series title gives different results.
- **Series dates do not match titles.** `series.premiere_date` never equals the first title release date (0 of 400 series). `season.finale_date` equals the last episode's air date for only 138 of 900 seasons. Use the episode dates.
- **Series episode counts include films.** `series.total_episode_count` equals the number of all episodes in the series, including films and specials (400 of 400 match).
- **`title.premiere_flag` is not about season one.** It is true for 61 series titles. Of these, 30 are first seasons and 31 are not.
- **`season.episode_count_aired` never differs from ordered.** `season_status` is `Completed` for all 900 seasons, including seasons of series still `Ongoing`.
- **`title.is_simulcast` is 180 titles.** Titles 1 to 10 are simulcast, plus 170 more.

### 6.7 Ads

- **Only free viewers see ads.** There are 300,024 impressions on 211,522 sessions, and none on paid sessions. Use `COUNT(DISTINCT playback_session_id)` for sessions with ads.
- **The campaign's series is not where the ad ran.** Only 627 of 300,024 impressions run on an episode from the campaign's `series_id`. Go from the impression to the episode, then to the title and series.
- **`ad_order.ott_platform_id` says nothing about the market.** The generator picks the platform at random.
- **`revenue_amount` is rounded to the cent on every impression.** That rounding moves CPM by campaign type. From `revenue_amount` the weighted CPM is 10.00 for Awareness (target 12.00), 33.14 for Brand Launch (34.00), 20.00 for Consideration (18.00) and 27.40 for Conversion (26.00). From `cpm_realized` it is 12.00, 34.00, 18.00 and 26.00. Use `cpm_realized`. Rounding gives 6,335.91 dollars of revenue, against 6,260.60 dollars from `cpm_realized`.

```sql
SELECT ROUND(SUM(cpm_realized) / 1000.0, 2) AS revenue_from_cpm,
       ROUND(SUM(revenue_amount), 2) AS revenue_from_revenue_column,
       SUM(CASE WHEN ROUND(cpm_realized / 1000.0, 2) = revenue_amount THEN 1 ELSE 0 END) AS rows_where_rounding_matches,
       COUNT(*) AS impressions
FROM <catalog>.hoshi_sales.impression_delivery
```

Result: 6,260.60 dollars from `cpm_realized` and 6,335.91 dollars from the rounded column. The rounded column matches the rounded CPM on 300,023 of 300,024 rows.

- **`campaign.total_budget_amount` is a plan, not spend.** It is target impressions times target CPM. It is 6,624.54 dollars in total.
- **`ad_order.net_order_value` is 85 percent of gross.** It is a fixed haircut, not a measured number.
- **Ordered impressions are not a column.** Derive them from value and CPM (section 3.11).
- **`total_impressions_served` is always 1.** Summing it equals counting rows.

### 6.8 Licences, windows and royalties

- **A licence cannot be tied to a title.** `license_agreement` has no title key and no territory key. Only `content_window` links titles and territories, and it has no agreement key.
- **Licence and deal money are separate.** A licence's `minimum_guarantee_amount` is never equal to its deal's `minimum_guarantee_amount` (0 of 600). The holder's `default_royalty_rate` never equals the agreement's `royalty_percentage` (0 of 600).
- **Licensor and partner are separate tables.** No holder name matches a partner name.
- **`active_flag` includes two windows that close on 2026-11-09.** Those windows count as active on the as-of date. They are the only active windows closing before 2026-11-10.
- **Rights-only windows have random platforms.** For the rights-only countries, `content_window.ott_platform_id` is random, so do not use it for market.
- **Territory gaps are almost everywhere.** 96.7 percent of viewed title and territory pairs have no active window (section 3.9). Use the planted examples, not the whole table.
- **Overdue means late.** Only statements due before the as-of date can be `Overdue`. `Issued` and `Pending` are not late.
- **`net_royalty_amount` is what is owed.** It is gross minus withholding.
- **`minimum_guarantee.recoupment_percentage` is 100.0 on every row.** It is not the share recouped. Use `recouped_to_date_amount / mg_amount`.
- **`fully_recouped_date` is NULL for the 60 open minimum guarantees.**
- **`mg_amount` is the same as the deal's `minimum_guarantee_amount`** on all 300 deals. Do not add the two.

### 6.9 Offers

- **Every offer has status `Expired`.** No offer has status `Active`, and every offer's end date is before the as-of date. An "active offers" query returns nothing.
- **`discount_amount` and `price_amount` are empty for all 20 offers.**
- **Reversed and expired redemptions still show revenue impact.** Expired redemptions show -6,673.79 dollars and reversed redemptions show -5,525.77 dollars. Filter on `redemption_status` if you need the applied total.

### 6.10 Columns that look useful but are empty or constant

These come from a null and distinct-count profile of every column in the subset.

| Table | Column | What it holds |
|---|---|---|
| `offer` | `discount_amount`, `price_amount` | Empty for all 20 offers |
| `series` | `finale_date` | Empty for all 400 series |
| `advertiser` | `contract_end_date` | Empty for all 150 advertisers |
| `content_episode` | `subtitles_available` | `true` on every episode |
| `content_episode` | `episode_status` | `Published` on every episode |
| `title` | `content_status` | `Active` on every title |
| `title` | `original_language`, `country_of_origin` | `Japanese` and `JP` on every title |
| `genre` | `is_active`, `usage_notes` | Constant |
| `season` | `season_status`, `network_original`, `language_original` | Constant |
| `ott_platform` | `max_concurrent_streams`, `parent_brand`, `service_tier`, `platform_status`, `drm_system` | Constant |
| `subscription` | `currency_code` | `USD` on every row |
| `subscription_plan` | `plan_status`, `launch_date`, `currency_code` | Constant |
| `minimum_guarantee` | `recoupment_percentage`, `is_recoupable`, `currency_code` | Constant |
| `impression_delivery` | `total_impressions_served` | Always 1 |
| `ad_order` | `payment_terms`, `currency_code` | Constant |
| `campaign` | `currency_code` | `USD` on every row |
| `holder` | `rights_holder_status`, `preferred_currency` | Constant |
| `partner` | `relationship_status` | `Active` on every row |
| `payment` | `gateway` | `Adyen` on every row |
| `playback_session` | `subtitle_language` | NULL for 888,659 sessions (all dubbed sessions) |

### 6.11 Other traps

- **Calendar months and generator months differ.** The generator steps time in months that start on the 10th. All SQL in this file uses calendar months.
- **Several fields are not connected to anything.** The generator draws these at random, so they do not follow other tables: `title.parental_advisory_flag`, `genre.tier`, `content_window.blackout_flag`, `content_window.window_priority`, `content_window.exclusivity_tier`, `license_agreement.exclusivity_flag` and `windowing_strategy`, `subscription.acquisition_channel` (not linked to offers), `subscriber.registration_source`, `campaign.priority_level`, `payment.is_autopay`.
- **Holders and partners are different populations.** Holder names and partner names do not overlap.
- **Euro territories share a currency.** Six territories (DE, FR, ES, IT, NL, IE) use EUR, and three (US, PR, BS) use USD. Subscriber money is always USD.

### 6.12 Columns added to the model

Five columns are not in the original media broadcasting model. The generator added them for the lab stories.

| Table | Column | Note |
|---|---|---|
| `hoshi_content.title` | `is_simulcast` | True for 180 titles |
| `hoshi_distribution.playback_session` | `content_episode_id` | The episode watched. The model has no content key on sessions. |
| `hoshi_distribution.playback_session` | `audio_language` | Language of the audio track |
| `hoshi_distribution.playback_session` | `subtitle_language` | NULL when subtitles were off |
| `hoshi_rights.content_window` | `title_id` | The title a window covers. The model has no title key on windows. |

## 7. Sensitive data: hoshi_talent

The schema `hoshi_talent` is off limits. This file reports only table names, column names and row counts. No values were read from any talent table, and no compensation figures appear here.

| Table | Rows | Columns |
|---|---|---|
| `talent_profile` | 2,000 | 12 |
| `contract` | 3,000 | 15 |
| `compensation_structure` | 3,000 | 14 |

Column names only:

- `talent_profile`: talent_profile_id, stage_name, talent_type, talent_tier, union_affiliation, nationality, primary_language, profile_status, clearance_status, residual_eligibility_flag, work_authorization_status, gdpr_consent_status.
- `contract`: contract_id, talent_profile_id, contract_number, contract_type, contract_status, engagement_role, effective_start_date, effective_end_date, base_compensation_amount, compensation_currency, backend_participation_percentage, guild_affiliation, exclusivity_flag, pay_or_play_flag, option_exercise_status.
- `compensation_structure`: compensation_structure_id, contract_id, structure_name, structure_status, compensation_type, base_episode_fee, daily_rate, weekly_guarantee, bonus_amount, deferred_compensation_amount, currency_code, overtime_multiplier, residual_eligibility_flag, effective_start_date.

The generator also builds a `governing_cba` value for each contract. The table has no such column, and the subset does not write it, so the value is never stored.

The count query used:

```sql
SELECT 'talent_profile' AS table_name, COUNT(*) AS row_count FROM <catalog>.hoshi_talent.talent_profile
UNION ALL
SELECT 'contract', COUNT(*) FROM <catalog>.hoshi_talent.contract
UNION ALL
SELECT 'compensation_structure', COUNT(*) FROM <catalog>.hoshi_talent.compensation_structure
```

## 8. Things I could not verify

- **The as-of argument of the generator run.** I could not see the run log. The data fits 2026-11-10 in every check, so I used that date.
- **Time zones.** The timestamps carry no zone. I could not check whether the generator's day boundaries are UTC or local time.
- **Metric view definitions.** I used the two metric views and their results. I did not compare their text with `data_model/metric_views.sql` line by line.
- **Column comments.** I did not compare the comments in `build_ddl.py` with what the columns hold, beyond the checks in this file.
- **Business meaning.** Hoshi Stream is fictional. Numbers such as the ad CPM levels and the royalty rates are as the generator set them, not market benchmarks.
- **Talent data.** Nothing in `hoshi_talent` was read beyond names and counts, by design.
