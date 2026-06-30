# Luma Take-Home

Modern engineering is about directing leverage — tools, judgment, taste — toward real outcomes. This take-home is designed around that.

Pick a problem. Build something that works. You have ~1 working day.

**You must use AI coding tools** — Claude Code, Cursor, Codex, whatever you prefer. These problems are scoped so that AI is necessary to ship something real in a day. We want to see how you direct the tools: how you plan, how you course-correct, what you accept, and what you push back on.

---

## Choose a Problem

Pick the one that excites you most. Each option has a **hardest part** — a technical wall, a product judgment call, a messy real-world detail. That's the part we're paying attention to. If you find yourself avoiding it, you've picked the wrong project.

### 1. Reverse-Engineer an Undocumented API

Pick a website that doesn't have a public API. Reverse-engineer how it really works — auth, request shape, rate limits, pagination, anti-bot — then build a real product on top.

Two hard parts: cracking the system, *and* picking the right product to build with what you've unlocked. A scraped CSV isn't a product. The data you can pull is the constraint — your taste is what turns it into something someone would actually use.

**Crack the system, then ship something people would actually use.**

### 2. Build the Mini-App You'd Actually Use

Pick a small problem in your own life. Build it as a deployable web app where AI does real work in the core feature — structured output, vision, an agent loop — not as a chat panel bolted on.

Two hard parts: the product call (what to include, what to cut, what makes the thing good enough that you'd open it twice) *and* the AI integration that has to hold up in front of a real user (latency, weird inputs, the times the model is wrong, the failure mode that has to feel okay).

**Build the small thing you'd actually open twice.**

### 3. Rebuild the Hard Part — with AI

Pick a feature from an app you admire that you assume took the team months to get right: real-time sync, search ranking, undo history, gesture handling, a vision pipeline, recommendations. Rebuild it. Then use AI to change the equation — replace heuristics with model calls, generate the data, do at runtime what they had to do offline — so you ship in a day what they shipped in a quarter.

Two hard parts: the technical lever (AI changing *how it works*, not just being the tool that wrote it) *and* the product call (knowing what "better" actually means for the feature you picked, and whether your version delivers).

**Rebuild the part that took them months. Let AI do something they couldn't.**

---

## Tips

The candidates who do best don't start by building — they start by getting sharp on the problem. It's easy to either throw everything at the wall or get heads-down on making something work, and miss the more important question: *what's actually worth solving here, and for whom?*

Slow down before you write a line of code. The thinking you do upfront will shape everything.

---

## What We're Looking For

We want real, working software — not a prototype, not a toy. You'll likely focus on a slice of the problem, but that slice should actually work and be something you'd put in front of a user. Show polish where it matters to you — in the UX, the details, the interactions that feel right. Ship a finished product, not a proof of concept.

We expect the result to be better than what an AI would produce on its own with minimal guidance. The AI writes the code; you own the decisions — what to build, how it should work, what to cut, and what to polish. Specifically, we're paying attention to:

- **How you approach new problems** — how you break down ambiguity, decide what to tackle first, and make good decisions with incomplete information
- **How you use AI tools** — not just that you used them, but how you directed them, where you pushed back, and where your judgment shaped the result
- **The unique perspective you bring** — the product instincts, technical taste, or domain insight that made your solution distinct from what anyone else would have built

---

## What to Deliver

### 1. Working software

Build your solution directly in this repo. It should run. Include setup instructions that work in a fresh Linux container — we will run your code in one during review. If you use Docker, provide a `docker-compose.yml` for one-command setup.

**If your project is deployable, deploy it.** We want to experience what you built, not just read about it. A live URL — whether it's a web app, an API endpoint, or a hosted service — goes a long way. Vercel, Railway, Fly, a VPS, whatever works. Include the URL in your APPROACH.md.

A `.env.example` is included with stub keys for providers we have accounts with (Anthropic, OpenAI, ElevenLabs, Google Cloud, AWS). Copy it to `.env`, use whichever keys your solution needs, and document any others.

### 2. APPROACH.md

- What you built and why you picked this problem
- Key decisions and tradeoffs
- What you intentionally left out
- What breaks first under pressure
- What you'd build next

### 3. Video walkthrough

Record a short video (~5 minutes) showing what you built. Demo the key flows — whether that's a UI walkthrough, a CLI session, or hitting your API — explain your decisions, and highlight anything you're particularly proud of. This is your chance to show us the experience through your eyes.

**Paste your video link (Loom, Google Drive, YouTube, etc.) into `video.md`.**

### 4. AI session history

Your AI session logs (Claude Code, Codex, Cursor) are packaged automatically when you run `./submit.sh`. If you used other AI tools (ChatGPT, etc.), export those conversations and include them in your repo before submitting.

This is a required deliverable. We review your AI interaction to understand how you work — how you plan, iterate, and direct the tools.

---

## Getting Started

```bash
# 1. Extract the challenge archive you downloaded
tar xzf challenge.tar.gz && cd *eng-take-home*

# 2. Create your own private repo and push to it
git init && git add -A && git commit -m "initial"
gh repo create my-take-home --private --source=. --push

# 3. Copy the env file and fill in any keys you need
cp .env.example .env
```

Now build your solution. Commit and push as you go.

---

## Submitting

When you're ready, run the submit script from your repo root:

```bash
./submit.sh
```

This handles everything: packages your AI session history, commits and pushes your latest changes, grants reviewer access, and registers your submission. You'll see a confirmation when it's done.
