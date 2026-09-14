# Notes Union

A Telegram bot that collects photos and text notes from a user, sends them
to an OpenAI model to classify the subject and generate a structured PDF
summary, and posts that PDF into the matching forum topic of a Telegram
group.

## How it works

1. Send the bot photos and/or `.txt`/`.md` files — it caches them per user.
2. Run `/generate`. The bot:
   - Asks the model to classify the subject (strictly from a fixed list).
   - Asks the model to write a structured Markdown summary and render it as
     a PDF (via the OpenAI Responses API + the `code_interpreter` tool).
   - Asks the model to detect the work type (lecture/seminar/lab) and
     number from the text, if present.
   - Looks up which forum topic in the target group corresponds to the
     subject (topic name == subject name).
   - Posts the PDF into that topic, with a caption:
     `{work_type} #{work_number} — DD.MM.YYYY` (falling back to just the
     date if the type/number aren't determined).
   - Clears the user's cache.
3. `/clear` clears your cached materials at any time.

## Requirements

- Python 3.11+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An OpenAI API key with access to the Responses API and code interpreter
- A Telegram supergroup with **Topics (forum mode) enabled**, where the bot
  is an admin with permission to post in topics

## Setup

1. **Install Python 3.11+** if you don't already have it.

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` and fill in:
   - `BOT_TOKEN` — from @BotFather
   - `OPENAI_API_KEY` — your OpenAI API key
   - `TARGET_GROUP_ID` — the numeric id of your forum group (negative
     number, e.g. `-1001234567890`). You can get this by adding
     [@RawDataBot](https://t.me/RawDataBot) to the group temporarily, or by
     checking bot logs after forwarding a message from the group.

4. **Configure the subject list** in `bot/services/subjects.py`:

   ```python
   SUBJECTS: list[str] = [
       "Mathematical Analysis",
       "Linear Algebra",
       "Physics",
       "History",
       "Programming",
   ]
   ```

   Each entry **must match the name of a forum topic** in your target
   group (matching ignores case, emoji, and punctuation — see
   `bot/utils/normalize.py` — but the underlying words must match).

5. **Add the bot to your group** as an admin with "Manage Topics" and
   "Post Messages" permissions. Because the Telegram Bot API has no
   endpoint to list all existing forum topics, the bot learns topic
   names by observing `forum_topic_created` / `forum_topic_edited`
   events while it's running. Practically, this means:
   - Topics created **after** the bot was added/started are picked up
     automatically.
   - For topics that already existed before the bot joined, either
     rename them once (triggering `forum_topic_edited`) or recreate
     them, so the bot observes the name.

6. **Run the bot:**

   ```bash
   cd bot
   python main.py
   ```

## Project structure

```
notes_bot/
├── bot/
│   ├── main.py                  # entry point, polling
│   ├── config.py                # settings from .env
│   ├── handlers/
│   │   ├── start.py             # /start, /generate, /clear, receiving photos and files
│   │   ├── topics.py            # capture forum_topic_created/edited, topic cache
│   │   └── errors.py            # global error handler
│   ├── services/
│   │   ├── cache.py             # per-user material cache
│   │   ├── subjects.py          # subject list + subject -> thread_id mapping
│   │   ├── ai_agent.py          # OpenAI API calls (subject, work type, PDF)
│   │   └── prompt.py            # prompt texts
│   └── utils/
│       └── normalize.py         # topic name normalization (strip emojis, lowercase)
├── requirements.txt
├── .env.example
└── README.md
```

## Notes & limitations

- The per-user material cache is **in-memory** — it resets if the bot
  restarts. Cached image/text files also live under `TEMP_DIR/{user_id}/`
  until `/generate` or `/clear` runs.
- `MAX_CACHE_SIZE_MB` caps how much a single user can accumulate before
  `/generate`.
- PDF extraction from the model response is defensive against a couple of
  different Responses API/SDK response shapes for code-interpreter
  container files; if OpenAI changes this shape again, check
  `bot/services/ai_agent.py::_extract_pdf_from_response`.
- If no matching topic is found for a classified subject, the user is
  notified instead of the PDF silently being dropped.
