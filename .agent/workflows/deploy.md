---
description: Auto-deploy til Railway via GitHub push
---

# Deploy Workflow

Når kodeændringer er færdige, push automatisk til GitHub:

// turbo-all

1. Stage alle ændringer:
```bash
cd /Users/cuwatyarecords/Desktop/HonoraTextAPI && git add .
```

2. Commit med beskrivende besked:
```bash
git commit -m "<beskrivelse af ændringer>"
```

3. Push til GitHub (Railway deployer automatisk):
```bash
git push origin main
```

**Note:** Denne workflow køres automatisk efter implementering er færdig.
