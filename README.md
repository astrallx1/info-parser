# Info Parser

A desktop app that finds **what is new on a subject you care about**. It reads GitHub, X
and any RSS or Atom feed, drops what you have already seen, scores the rest against rules
you write yourself, and shows you a ranked list of what is worth your attention.

The subject is up to you. Point it at machine learning, Rust, robotics, biotech, board
games or a competitor's engineering blog. The starter profile is set up for AI and
developer tools because that is a common case, and you change it in the app.

## What it does

- Collects fresh signals from three kinds of source: GitHub repositories by topic tag, X
  accounts, lists and searches, and RSS or Atom feeds (blogs, newsrooms, YouTube
  channels). Feeds come in two lists, and which one a feed sits in changes how it is
  judged: **first-party** sources publish about themselves, **podcasts and shows** talk
  to other people.
- Drops what you have already seen, what is too old, repositories you banned and
  subjects you never want. This happens in code, before any paid call.
- Scores every remaining signal from 0 to 100 with your own prompt, then keeps what
  clears your threshold.
- Merges signals that tell the same story into one item, and drops stories it showed you
  in an earlier run.
- Shows the result as a feed you can copy from, and exports the run to a Markdown file.
- Watches the repositories that reached the feed and raises an alert when one starts
  gaining stars fast.

Each result carries a short plain-language description of what the thing is, its links,
and the score it earned. What you do with it afterwards is your business.

## What it does not do

- It writes nothing for you. It has no drafting, publishing, scheduling or replying
  features, and it never touches your accounts.
- Nothing leaves your machine except the API calls it needs: GitHub, OpenAI, and the
  sites you listed as sources.
- It does not republish other people's content. You get a description and a link.

## Requirements

- Python 3.12 or 3.13
- A GitHub token. It needs no scopes: public search works with a bare token.
- An OpenAI API key. Scoring a run costs roughly $0.10 on the default model
  (`gpt-4.1-mini`) for the ~800 signals a full pass over a dozen sources collects.
  More sources means more signals and a proportionally larger bill.
- Chromium for Playwright, installed once with one command below.
- Optional: a logged-in X session, if you want tweets as a source. GitHub and feeds work
  without it.

## Install

macOS and Linux:

```bash
git clone https://github.com/astrallx1/info-parser.git
cd info-parser
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python main.py
```

Windows:

```powershell
git clone https://github.com/astrallx1/info-parser.git
cd info-parser
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pythonnet
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python main.py
```

`pythonnet` is Windows only. The window there is WebView2, which needs it; Windows 11
ships the WebView2 runtime already.

Chromium is not bundled with anything — you install it once with the command above and
it stays in your Playwright cache between updates.

## First run

A setup screen opens by itself and asks for the two keys, checks each one against the
real API, and offers to save an X session. Every step can be skipped, so you can look
around before creating any tokens. The app writes a starter profile with a starter set of
scoring rules, which you then edit to taste.

Everything the app writes stays on your machine and in the project folder: keys in a
`.env` file, sources in `profiles.yaml`, the X session in `cookies.json`, and the
history in a SQLite file.

## The X session

X has no usable public API for this, so tweets come from a logged-in browser session.
Two ways to get one:

1. In Settings, paste an export from the Cookie-Editor browser extension. Open `x.com`
   logged in, press Export, choose JSON, paste.
2. Run `python setup_x_login.py`, which opens your Chrome profile, waits 15 seconds for
   you to log in, and saves the session.

Use an account you can afford to lose, keep the pacing settings alone, and read X's terms
before you point this at anything. When a session expires the app says so instead of
quietly returning nothing.

## Profiles

A profile is a set of sources plus one scoring prompt. Keep one per subject: what counts
as news about Rust is not what counts as news about biotech, and each profile judges its
own sources by its own rules. A run covers every profile you selected, and the feed shows
them together.

You edit sources in the app: GitHub topic tags, X handles, X list ids, X search queries,
first-party feed URLs, and podcast or show feeds. The picker in the feed then lets you
include or exclude any single source before a run, so a quick GitHub-only pass costs a
few cents and a minute.

## Updates

This repository is a SNAPSHOT, not a branch: each release replaces its single commit,
so `git pull` on an older clone has no shared history to merge. To update, clone again
(your `.env`, `profiles.yaml`, `cookies.json` and the database live in the folder you
already have, and none of them is tracked here).

## Scoring rules

The rules live in plain text files under `topicparser/prompts/`, and they are the product.
`_base.txt` holds what everybody shares, `<Profile>.txt` holds one profile's own focus.
The app edits the profile files in a modal that keeps one previous version, so a bad
save is undoable; the shared files are shown read-only there and are edited on disk.

Three files do narrower jobs. `_group.txt` decides which signals tell the same story.
`_xgate.txt` answers one question about a surviving tweet: is there a checkable fact in
it, or is it somebody's opinion about a fact you already have? `_feedgate.txt` asks the
same of a first-party post: is this the event, or the publisher talking about itself?
That question does not apply to a show interviewing a guest, so posts from the podcast
list never reach this gate — the scoping is in the config, not in the prompt text. Both
gates are optional: delete the file and the call never happens.

`_meta.txt` is different. Paste it into any chat model and it interviews you, then writes
a profile's scoring rules from your answers. Faster than starting at a blank file.

Two things worth knowing before you tune anything. Every run writes
`debug/run-<time>.json` with the score and reason for every signal, so read that instead
of guessing what the model did. And the app can replay a past run against a candidate
prompt in one call, which answers "did my rule fire" for a few cents. It does not predict
what the next live run will show, because a score at this model tier depends on the whole
batch.

## Settings

Nine knobs, all editable in the app, all applying to the next run without a restart:

| knob | default | what it does |
|---|---|---|
| `SCORE_THRESHOLD` | 70 | the score a signal must reach to become a topic. The model answers in round numbers, so 65 behaves exactly like 70: the positions that differ are 60, 70, 75 and 80 |
| `GH_PER_PAGE` | 100 | repositories fetched per GitHub topic, 1 to 100 |
| `X_MAX_TWEETS` | 150 | tweets read per X source |
| `GH_FRESH_DAYS` | 60 | how old a repository update may be |
| `X_FRESH_DAYS` | 3 | how old a tweet may be |
| `FEED_FRESH_DAYS` | 7 | how old a feed post may be |
| `TREND_MIN_VELOCITY` | 50 | stars per day that raises a trending alert |
| `TRACK_STAGNANT_DAYS` | 21 | a watched repository idle this long is dropped |
| `OFF_INTEREST` | empty | comma separated subjects to drop before scoring |

`.env.example` lists these plus a few more that stay out of the interface, including the
batch size and the delays between X requests. Widen the net before you touch a scoring
rule: fetching more repositories changes nothing about judgement and costs a few cents.

## Language

Interface text comes from one JSON catalogue per language, shared by the Python side and
the interface, so the two cannot drift. English ships. To add a language, drop
`lang/<code>.json` beside the app and set `APP_LANG`; a partial file only overrides the
keys it defines, and the rest falls back to English. The generated descriptions follow
the same setting.

## Development

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite runs on macOS, Linux and Windows without a network, a key or a browser. CI
covers Windows on Python 3.13 and macOS on Python 3.12.

The interface is one hand-written `index.html`: no framework, no build step. Backend
changes go test first.

## Known limits

- The banner that announces a finished run wears the wrong icon on macOS, because the app
  is unsigned. Windows shows the real one.
- The app icon loses detail at 16 px, which you see in the Finder list view and in a
  browser tab.
- Scoring quality depends on your prompt far more than on the model. The default model is
  cheap and forgetful, and the pipeline is built around that: it re-asks for signals the
  model skipped, assembles the final list in code rather than trusting the model to emit
  it, and repairs descriptions that come back in the wrong language.

## License

MIT. See [LICENSE](LICENSE).
