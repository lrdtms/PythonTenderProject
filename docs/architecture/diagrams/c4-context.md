# C4 Level 1: System Context (IntelTPS)

```mermaid
C4Context
    title System Context: IntelTPS (MVP, Nov 2026)

    Person(estimator, "Estimator / Tender Officer", "Uploads tender packs, reviews extracted data, compares quotes, exports")
    Person(pm, "Project Manager", "Deadlines, tasks, approved estimates, reports")
    Person(badmin, "Business Admin", "Workspace, users, plan, markup defaults, activity log")
    Person(reviewer, "Read-only Reviewer", "Inspects documents, estimates, checklists")
    Person(padmin, "Platform Admin", "Health, plans, support. No routine access to customer documents")

    System(tps, "IntelTPS", "Multi-tenant tender preparation: extraction with provenance, human review, BoQ estimating, supplier matching, exports")

    System_Ext(cf, "Cloudflare Tunnel edge", "Public HTTPS URL for the marking link. Terminates TLS outside our machine")
    System_Ext(smtp, "SMTP relay (Mailpit locally)", "Optional email reminders")
    System_Ext(hosted, "Hosted LLM API (optional, OFF)", "Config switch only. Synthetic data only until POPIA assessment")

    Rel(estimator, cf, "Uses", "HTTPS")
    Rel(pm, cf, "Uses", "HTTPS")
    Rel(badmin, cf, "Uses", "HTTPS")
    Rel(reviewer, cf, "Uses", "HTTPS")
    Rel(padmin, cf, "Uses", "HTTPS")
    Rel(cf, tps, "Forwards to", "cloudflared outbound tunnel")
    Rel(tps, smtp, "Sends reminders", "SMTP")
    Rel(tps, hosted, "Disabled by default", "HTTPS, OpenAI-compatible")
```

Notes
- The local LLM (Ollama) is *inside* the system boundary: it runs on our machine. This is the core privacy decision (PRD §1, ADR-0003).
- Cloudflare is a third-party processor that sees decrypted traffic at its edge. Synthetic data only while the tunnel is used (see architecture.md, "PRD issues").
