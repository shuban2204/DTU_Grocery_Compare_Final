# Instamart manual snapshot format

These files are a transparent fallback only when the live Instamart browser provider reports a confirmed block. Do not copy values from private APIs or automate a blocked browser session.

For each supported query, manually observe the normal visible Instamart page at Delhi Technological University and populate its matching JSON file. Set `captured_at` to an ISO-8601 timestamp and add only products visibly observed at that time.

```json
{
  "query": "Maggi",
  "location": "Delhi Technological University",
  "captured_at": "2026-09-11T23:50:00+05:30",
  "source": "manual_snapshot",
  "products": [
    {
      "title": "Visible product title",
      "size": "Visible pack size",
      "price": "Visible current price",
      "mrp": "Visible MRP or null",
      "product_url": "Visible product URL or null",
      "availability": "available",
      "sponsored": false
    }
  ]
}
```

The committed query files are intentionally empty templates, not product data.
