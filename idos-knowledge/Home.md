---
id: idos-home
aliases:
  - IDOS Knowledge Base
  - Home
---

# IDOS Knowledge Base

**Investment Decision Operating System**

## Portfolio Overview

```dataview
TABLE sectors AS "Sector", score AS "DDD Score", conviction AS "Conviction"
FROM "companies"
SORT score DESC
```

## Recent Wiki Updates

```dataview
TABLE file.mtime AS "Last Updated"
FROM "companies"
SORT file.mtime DESC
LIMIT 10
```

## Quick Links

- [[companies/_template/Company Wiki Template|New Company Template]]
- [[Dashboard]]

## Structure

```
idos-knowledge/
├── companies/       # Wiki entries per ticker
│   ├── AAPL/
│   │   └── wiki.md
│   └── ...
├── assets/          # Attachments & images
└── .obsidian/       # Vault config
```
