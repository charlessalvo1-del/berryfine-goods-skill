# Structured research audit

Use one object per inventory item and one object per candidate completed-sale comparable. The research gate reconciles included comparables to the canonical ledger and blocks unsupported disposal-sensitive decisions.

```json
{
  "version": 1,
  "client_id": "client-2026-001",
  "intake_id": "intake-2026-001",
  "items": [
    {
      "item_id": "BFG-20260802-0001",
      "comparables": [
        {
          "comp_id": "BFG-20260802-0001-c1",
          "marketplace": "eBay",
          "source_url": "https://example.com/completed-sale",
          "transaction_status": "sold",
          "sale_date": "2026-07-15",
          "sold_price": 75,
          "shipping": 12,
          "currency": "USD",
          "condition": "Used, complete",
          "comparability": "near",
          "included": true,
          "include_reason": "Same model and similar condition",
          "captured_at": "2026-08-02T14:00:00-04:00"
        }
      ]
    }
  ]
}
```

Use `exact`, `near`, or `broad` for comparability. Keep excluded candidates in the audit with `included=false` and an explicit reason. Never convert an active or unsold listing into completed-sale evidence.
