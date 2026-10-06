# What you see in the window, and why

A plain-language guide to every state of the EQ Recorder window. No code
knowledge needed. Colors and exact sizes are in
[DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## Top of the window

**EQ RECORDER · ENGINE: PRO.** The app's name and a label for the speech
recognition it uses, which runs entirely on your Mac.

**A gear icon on the right.** macOS hasn't given the app permission to
listen for keyboard shortcuts yet. Clicking the gear opens the right
settings page. Once permission is granted, the gear disappears.

## The recording row

| You see | It means |
|---|---|
| Green **START RECORDING**, gray dot, `READY` | Nothing is being recorded. You can start. |
| Red **STOP RECORDING**, blinking red `● REC`, red timer | Recording right now. The timer shows how long. |
| Green dot and `SAVED: <file name>` for about 10 seconds | A transcript was just finished and saved. Then it goes back to `READY`. |
| `QUEUED: …` or `CONVERTING …` | A file was accepted and is waiting its turn (or being converted from video/other audio first). |
| `ERROR: …` | Something went wrong. It stays until something else happens, so you don't miss it. |
| A thin green bar under the row | A file is being transcribed; the bar shows how far along it is. |

The text next to the dot gets shortened with "…" in the middle if it's too
long. Hover over it to read the full text.

## The RECORDINGS header

- **`READY: N`** (green): how many finished transcripts there are.
- **`PROCESSING: N`** (blue): how many files are still waiting to be
  transcribed, including the one being worked on right now. It only appears
  when there is something to wait for.
- **`ALL ⌃`** on the right: choose what the list shows. ALL, only TODAY,
  or LONGEST / SHORTEST first. This only affects finished transcripts.
  Files that still need attention are always shown.

## Cards in the list

Each card is one file. The mark on the left and the small text under the
name say what's going on with it.

| Card shows | It means | Icon on the right |
|---|---|---|
| Blue filled dot, `TRANSCRIBING — 37%` | Being turned into text right now. | none; just wait |
| Gray ring, `QUEUED` | Waiting for its turn. Files are processed one at a time. | none |
| Gray ring, `NO TRANSCRIPT` | A recording that was never transcribed, for example because the app was closed halfway. | microphone: transcribe it now |
| Red ring, `FAILED · …` | The last attempt didn't work. The reason is shown briefly. | microphone: try again |
| Green ✓, a duration like `11 MIN 33 SEC` | Done. The transcript is saved. | folder: show the file in Finder |

**Clicking a card** only selects it (green outline). It doesn't start
anything; the icon on the right does the action. A card also gets slightly
lighter when the mouse is over it.

## Bottom buttons

| Button | What it does |
|---|---|
| Trash (dim red) | Nothing is selected, so there's nothing to delete. |
| Trash (bright red) | Deletes the selected file. You're asked to confirm first, because it can't be undone. A queued file is just taken out of the queue, without asking. |
| **OUTPUT FOLDER** | Opens the folder with all transcripts. |
| **LAST FILE** | Opens Finder with the newest transcript already highlighted. |
| **IMPORT** | Choose an audio or video file from your Mac to transcribe. |

## Other things you may notice

- **Closing the window doesn't stop anything.** It only hides the window.
  Recording and transcription continue; click the Dock icon to bring it
  back.
- **Opening the app when it's already open** brings the existing window to
  the front instead of starting a second copy.
- **A macOS dialog asking for access** (microphone, Desktop folder) appears
  once. The app waits for your answer, so if the window doesn't show up,
  look for that dialog.
