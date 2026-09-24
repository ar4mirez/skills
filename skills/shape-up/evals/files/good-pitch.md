# Pitch: Autopay on payment

## Problem

Last month Dana, who runs a landscaping business on our invoicing app, told support she spends every first Monday
chasing the same twelve customers for the same monthly invoice. Those customers want to pay; they just forget. Today
Dana's only workaround is a calendar reminder and a batch of copy-pasted emails, and three of them still paid late.

## Appetite

Big batch: 6 weeks with 1 designer and 2 programmers. It's worth one cycle, not more, so we reuse the existing payment
form and customer detail page instead of adding customer accounts.

## Solution

Autopay is an option at the moment of paying, so there's never ambiguity about whether the current invoice is paid.

### Elements
- An "Autopay future invoices" checkbox on the existing Pay Invoice screen (card and ACH)
- An "Autopay is on" callout on the existing payment confirmation
- A "Disable Autopay" action for the invoicer on the existing customer detail page

```
Invoice
-------
- Pay  ──>  Pay Invoice

Pay Invoice
-----------
- Card / ACH fields
- [ ] Autopay future invoices
- Submit  ──>  Confirm

Confirm
-------
- Receipt
- "Autopay is on" callout (if chosen)
```

> Latitude: placement and copy of the checkbox and callout are up to the designer.

## Rabbit holes

- Customers don't have logins, so they can't manage Autopay themselves → **Patch:** the invoicer disables it from the
  customer detail page; customers ask the invoicer.
- Failed recurring charges → we'll reuse the existing failed-payment email; no new retry logic.

## No-gos

- No customer accounts, usernames or passwords.
- No partial or scheduled-date Autopay; it charges on the invoice due date only.
- No Autopay for invoices already overdue.
