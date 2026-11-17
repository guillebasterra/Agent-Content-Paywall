# content

One Markdown file per article. Frontmatter:

```yaml
---
id: slug-of-the-article
title: Title
abstract: One or two sentences shown free in the catalog.
price_usd: 0.40
license: ai-input        # ai-input: reference only, no training. ai-train: also needs train_price_usd
tags: [topic, topic]
preview_mode: w50        # optional: none, w50, w100 or p10
allowed_agents: ["*"]    # optional: agent names, or "*" for all
---
```

Body below the frontmatter is the paid content.

On startup, files with a new id are imported into SQLite and belong to the demo writer. Editing an imported file changes nothing. Writers can also publish from `/upload`.

`demo/` is not imported. It holds files to upload by hand during the demo, so the dashboard and catalog start empty.
