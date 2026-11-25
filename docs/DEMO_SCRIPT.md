# DocuMine: 3-minute demo script

Uses only the fictional Kestrel files in `sample_data/`.

## Before the demo (dry run, at least an hour earlier)
1. `streamlit run app.py` and check that the Upload tab lists stored files without errors.
2. Run `python tests/smoke_test.py`. All stages should PASS. This also uploads the sample files.
3. **Prepare the backup material** from this dry run:
   - Generate Meeting Minutes from `kestrel_team_chat.txt`, approve it, and download the `.md` and
     `.docx` to `demo_backup/`.
   - Take screenshots of the Ask answers and the Review results.
   - Save the smoke test output: `python tests/smoke_test.py > demo_backup/smoke_test.txt`
   - Run `python -m pytest -q` and keep the terminal open.
4. Have open: the app in a browser, `sample_data/kestrel_team_chat.txt` in an editor, and the
   `demo_backup/` folder.

## Script

**0:00–0:20  Problem**
> "Engineering knowledge lives in chats, rough notes, code and incident records. Writing proper
> documentation from it takes hours, and AI chat tools need careful prompts and make things up.
> DocuMine turns informal input into formal documents in one click, with sources and human review."

Show `kestrel_team_chat.txt` for a few seconds: slang, timestamps, emojis.

**0:20–0:50  Upload** (Upload tab)
- Select `kestrel_team_chat.txt`, `kestrel_design_notes.md`, `kestrel_incident_INC-007.docx` and
  `kestrel_service.zip`, then click **Process files**.
- Point out the chunk counts. Because these files were uploaded in the dry run, they show as "already
  uploaded, reusing it". Say: "duplicates are detected by fingerprint."
> "Every file is checked first: size limit, safe ZIP handling, and anything that looks like a password
> or API key is refused."

**0:50–1:40  Generate Meeting Minutes** (Generate tab)
- Document type **Meeting Minutes**, file **kestrel_team_chat.txt**, click **Generate**.
> "No prompt. The template and the rules are built in: formal English, only facts from the sources,
> and 'Not mentioned in the sources' instead of guessing."
- In **Preview**, show the Decisions list and the Action Items table (task, owner, due date).
  Point at a citation like `[1]` and open the matching source below.
- In **Edit**, change one word, click **Approve**, then **Download .docx**.
> "A person always reviews and approves. The draft is never final on its own."

**1:40–2:20  Ask** (Ask tab), three questions:
1. "Which database did the team decide to use for the sensor readings?"
2. "What was the root cause of incident INC-007?"
3. "After how many minutes without data is a sensor considered stale?"
- Open one source expander to show the filename, location and the original text.
> "Search combines keywords and meaning, and every answer cites the exact file and lines."

**2:20–2:50  Review** (Review tab)
- Select `kestrel_team_chat.txt` and `kestrel_design_notes.md`, then click **Find possible issues**.
> "We planted a contradiction: the chat says raw readings are kept for 90 days, the design notes say 30.
> DocuMine lists these as possible issues for a human to check, with the sources."
- Only say it was found if it appears on screen. If it does not appear, say: "It is not flagged this
  time. That is exactly why these are suggestions for human review."
- Scroll to **Saved documents** to show the approved minutes.

**2:50–3:00  Close**
> "Informal in, formal out: one click, sources shown, human approved."

## Backup if the API fails during the demo
Decide quickly. Do not retry more than once on stage.

| What fails | What you see | What to do |
|---|---|---|
| Gemini (rate limit or outage) | Red message such as "Gemini rate limit reached" | Say "The model is rate-limited right now, here is the same run from our rehearsal." Open `demo_backup/` and show the generated `.md` and `.docx`, then the Ask and Review screenshots. |
| Only embeddings | Upload says "stored, but embeddings failed"; answers may be weaker | Carry on. Search falls back to keyword search automatically. Mention this as a design choice. |
| Supabase or internet | Errors on every tab | Show `demo_backup/smoke_test.txt` and the screenshots. Then run `python -m pytest -q` live: the tests run offline. Say they are offline tests with fakes, not a live run. |

## Do not say
- Any accuracy or hit-rate number, unless it was measured with `python tests/evaluate.py` and
  recorded in `docs/PROGRESS.md`.
- That the contradiction is "always" detected.
- That the output needs no review.
