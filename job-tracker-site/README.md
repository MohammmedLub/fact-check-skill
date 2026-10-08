# Job tracker site

One page, connected tabs (dashboard, Nederlands, Français, English, Applications, Carte de parcours).
Data is stored online, so every device and everyone with the link sees the same numbers.

- **Anyone with the link:** read-only view, refreshes every 30 seconds.
- **You:** click *Unlock editing* and enter your edit key. Changes save online for everyone.

## Deploy on Netlify

1. New site from this repo. Base directory: `job-tracker-site`.
2. Site settings → Environment variables → add `EDIT_KEY` = a long passphrase only you know.
3. Deploy. Storage uses Netlify Blobs (built in, no setup).

Opened as a local file (no server), it falls back to saving in that browser only.

Note: the link is public. Anyone who has it can read company names and notes you enter.
