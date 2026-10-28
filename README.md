# Folio Post

A desktop mail program for Linux, laid out like Outlook: ribbon, KeyTips, Folder Pane, message list,
Reading Pane, and Outlook's keyboard shortcuts. Part of the Folio suite.

- **Accounts:** Gmail (Google sign-in in the browser, or an app password), Proton Mail through Proton Mail
  Bridge, Yahoo, iCloud, Fastmail, GMX and any IMAP, POP3 and SMTP server.
- **Calendar:** Day, Work Week, Week, Month; recurrence, reminders, meetings (iTIP by mail); two-way sync with
  Google Calendar and CalDAV; read-only internet calendars such as Proton Calendar's share link.
- **People and Tasks:** contacts and groups (vCard, Google Contacts, CardDAV), tasks, flagged mail on the To-Do
  List, notes.
- **OpenPGP:** encrypt and sign with your GnuPG keys (PGP/MIME); encrypted and signed mail opens and its
  signature is checked.
- **Files:** .eml, .mbox, .pst/.ost (readpst), .msg (msgconvert), .ics, .vcf.
- **Offline:** mail is kept on this computer (SQLite with full-text search); changes made offline go to the
  server at the next Send/Receive, new mail waits in the Outbox.
- **Safe reading:** HTML mail is shown by Post's own renderer: no scripts, no remote pictures until you
  allow them, tracking pixels dropped.
- **No cloud of its own**, no account with us, no telemetry.

## Build and test

    sh build-deb.sh out/                       # folio-post_<version>_all.deb
    sh tests/run_ui.sh ui_mail.py              # UI test on an X display (Xvfb works)
    sh tests/run_ui.sh command_walk.py         # every ribbon command
    python3 tests/test_engine.py               # store, MIME, HTML, IMAP/SMTP sync

The tests run against `tests/mailserver.py`, a small in-memory IMAP and SMTP server.

## Gmail sign-in

Google only lets an app sign in with an OAuth client ID registered in a Google Cloud project. Make one
(APIs & Services > Credentials > OAuth client ID, type *Desktop app*, with the Gmail API enabled) and paste
it in Add Account, or set `FOLIO_POST_GOOGLE_CLIENT_ID`. Without one, use a Google app password.

## License

MIT. The Colibre icons in `share/iconset` are MPL 2.0 / CC BY-SA 4.0.
