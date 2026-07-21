<h1 align="center">BroadwayHD Subtitle Getter by mp3li</h1>

<p align="center">
  A macOS Python tool that uses a local hidden Chrome session to find subtitle tracks available to your authorized BroadwayHD session, convert captured WebVTT subtitles to SRT, and organize the results locally.
</p>

<br />

<p align="center">
  <img alt="Status" src="https://img.shields.io/badge/Status-In_Active_Development-660000?style=flat-square&labelColor=04040c" />
  <img alt="Platform" src="https://img.shields.io/badge/Platform-macOS-660000?style=flat-square&labelColor=04040c" />
  <img alt="Runtime" src="https://img.shields.io/badge/Runtime-Python_3-660000?style=flat-square&labelColor=04040c" />
  <img alt="Browser" src="https://img.shields.io/badge/Browser-Google_Chrome-660000?style=flat-square&labelColor=04040c" />
  <img alt="Output" src="https://img.shields.io/badge/Output-SRT_Subtitles-660000?style=flat-square&labelColor=04040c" />
  <img alt="Privacy" src="https://img.shields.io/badge/Privacy-Local_Session_and_Files-660000?style=flat-square&labelColor=04040c" />
</p>

## Table of Contents

<details>
<summary>Open Table of Contents</summary>

<br />

- [About the Project](#about-the-project)
- [What the Tool Does](#what-the-tool-does)
- [Privacy, Account Access, and Responsible Use](#privacy-account-access-and-responsible-use)
- [Requirements](#requirements)
- [How to Run](#how-to-run)
- [How to Use the Tool](#how-to-use-the-tool)
- [My Links Text File](#my-links-text-file)
- [Output and Media Matching](#output-and-media-matching)
- [Settings](#settings)
- [How It Was Built](#how-it-was-built)
- [Project Layout](#project-layout)
- [Known Limitations](#known-limitations)
- [GitHub Safety Notes](#github-safety-notes)
- [License](#license)
- [Responsible Use and Accommodation Disclaimer](#responsible-use-and-accommodation-disclaimer)

</details>

## About the Project

BroadwayHD Subtitle Getter by mp3li is a local tool for obtaining non-DRM protected .srt files from BroadwayHD videos that the user has lawful access to. This project was strictly made for educational and accommodation purposes.

The project is designed to stay practical: add one or more detail-page links, sign in through your own BroadwayHD account when needed, choose which subtitle languages to save, and receive organized local subtitle files. It can also match a title to an existing media folder when that optional local setting is enabled.

## What the Tool Does

- Accepts BroadwayHD detail-page links from a local text file or pasted one at a time.
- Uses a local Google Chrome session to open your BroadwayHD page and look for available subtitle files.
- Reuses a locally saved browser session when it is still valid, or accepts credentials only for the current run.
- Your BroadwayHD password stays private: the developer cannot access it, and your local Chrome session sends it only to BroadwayHD's normal sign-in page if you choose to enter it. It is never saved in the project settings. More information is below.
- Detects subtitle `.vtt` requests made by the page.
- Downloads available subtitle tracks and converts them to `.srt`.
- Saves subtitle files by title and language, such as `Example Title.en-US.srt`.
- Lets you save all found languages or prioritize selected languages.
- Optionally matches a title against local media folders and saves beside the matched file.
- Keeps downloaded subtitles, browser-session data, personal settings, and personal link lists out of Git.

## Privacy, Account Access, and Responsible Use

This tool runs on your computer and is designed to keep your sign-in private. Your BroadwayHD email and password are requested only when you choose to enter them. The developer does not have access to either one. If you enter a password, your local Chrome session sends it only to BroadwayHD's normal sign-in page for that run; the tool does not store it in `settings.json` or the source code. A saved Chrome profile may retain BroadwayHD session cookies so you can reuse a session later; that profile is intentionally ignored by Git.

Use the tool only with a BroadwayHD account and content you are authorized to access, and follow BroadwayHD's applicable terms and local law. Availability of subtitle tracks, page behavior, and sign-in flows can change at any time. This project does not download video and does not claim to bypass account access or DRM protections.

## Requirements

- macOS only for now; Windows and Linux support are coming soon.
- Python 3
- Google Chrome installed at `/Applications/Google Chrome.app`
- A BroadwayHD account with access to the page you want to check

No Python packages need to be installed. The tool uses Python's standard library and the `curl` included with macOS.

## How to Run

Clone or download this repository, then open Terminal and run:

```bash
cd "/path/to/BroadwayHD Subtitle Getter by mp3li"
python3 broadwayhd_subtitle_getter.py
```

The first time you plan to import links from a file, create your private working copy from the included safe template:

```bash
cd "/path/to/BroadwayHD Subtitle Getter by mp3li"
cp "My Links Txt/mylinks-default.txt" "My Links Txt/mylinks.txt"
```

`mylinks.txt` is ignored by Git, so replacing the example links with your own does not prepare them for a commit.

## How to Use the Tool

### 1. Start the Script

Run `python3 broadwayhd_subtitle_getter.py` from the project folder. The welcome message explains the two input modes.

### 2. Sign In or Reuse a Session

Enter your BroadwayHD email and password if you need to establish a session. The password prompt does not echo your password, and the script does not save it in the settings file.

If the local hidden Chrome profile already has a valid BroadwayHD session, press Enter at the email prompt to reuse it.

### 3. Choose How to Provide Links

Choose one of the prompts:

1. `Import your mylinks.txt` reads the private `My Links Txt/mylinks.txt` file.
2. `Manually insert links here` lets you paste a detail-page link and decide whether to paste another one.

### 4. Wait for Subtitle Capture

For each supported BroadwayHD detail page, the tool loads the page in hidden Chrome, looks for subtitle-track requests, filters the captured tracks according to your settings, and writes the selected SRT files locally.

### 5. Find the Result

With the default settings, files are organized like this:

```text
Subtitles/
  Example Title/
    Example Title.en-US.srt
    Example Title.en-GB.srt
```

The `Subtitles/` folder is ignored by Git because it contains locally downloaded output.

## My Links Text File

The tracked [mylinks-default.txt](My%20Links%20Txt/mylinks-default.txt) file contains intentionally non-real example URLs and usage notes. Copy it to `mylinks.txt`, then replace the examples with your own BroadwayHD detail-page URLs.

You can use headings, title notes, blank lines, or other plain text to organize the file. Only detected `http://` and `https://` URLs are counted. Blank lines and text that are not links are not counted.

Example private file:

```text
Shows to check

Example title note
https://example.com/broadwayhd-detail-page-one

Another title note
https://example.com/broadwayhd-detail-page-two
```

## Output and Media Matching

By default, subtitle output is saved under `Subtitles/` in a folder named after the BroadwayHD title. If an output title already conflicts with another BroadwayHD item, the tool can use the item ID to keep the folders distinct.

The optional `media_matching` settings can scan your local media roots, identify a close title match, and save the subtitle beside the matched media file instead. It is disabled by default. Because media-root paths are personal to each computer, keep them only in your ignored `Settings/settings.json` file.

## Settings

The tracked [settings-default.json](Settings/settings-default.json) documents every default setting. To create a private customized copy, run:

```bash
cd "/path/to/BroadwayHD Subtitle Getter by mp3li"
cp "Settings/settings-default.json" "Settings/settings.json"
```

`Settings/settings.json` is ignored by Git. Useful options include:

| Section | Setting | Purpose |
| --- | --- | --- |
| `browser` | `capture_timeout_seconds` | Maximum time to wait for subtitle requests. |
| `subtitle_preferences` | `mode` | Save `all` tracks or use preferred languages. |
| `subtitle_preferences` | `save_vtt` / `save_srt` | Choose whether to keep VTT files, SRT files, or both. |
| `media_matching` | `enabled` | Turn local media-folder matching on or off. |
| `media_matching` | `media_roots` | Local folders to scan when matching is enabled. |

## How It Was Built

| Area | Implementation |
| --- | --- |
| Runtime | Python 3 standard library |
| Browser automation | Hidden Google Chrome with the Chrome DevTools Protocol |
| Page metadata | BroadwayHD detail-page and front-office requests |
| Subtitle discovery | Network and page-state detection for `.vtt` subtitle URLs |
| Subtitle conversion | In-project WebVTT-to-SRT conversion |
| Local configuration | JSON settings with safe built-in defaults |
| Optional file matching | Normalized title comparison against local media paths |

The small root launcher keeps the public entry point simple. The capture, conversion, configuration, and matching logic are kept in `Base Script/broadwayhd_subtitle_getter_base.py`.

## Project Layout

```text
BroadwayHD Subtitle Getter by mp3li/
  broadwayhd_subtitle_getter.py          # Run this file
  Base Script/
    broadwayhd_subtitle_getter_base.py   # Core workflow
  My Links Txt/
    mylinks-default.txt                  # Safe tracked example
    mylinks.txt                          # Your private links; ignored
  Settings/
    settings-default.json                # Safe tracked defaults
    settings.json                        # Your private settings; ignored
  Browser Session/                       # Local Chrome profile; ignored
  Subtitles/                             # Local subtitle output; ignored
```

## Known Limitations

- The tool currently targets macOS and the standard Google Chrome application path.
- BroadwayHD may change its site, sign-in process, player, subtitle delivery, or available titles without notice.
- A valid account session and page access do not guarantee that a subtitle track is available.
- Titles without a captured subtitle request cannot produce an SRT file.
- Media matching is optional and depends on the local names and threshold configured in your settings.

## GitHub Safety Notes

The repository's `.gitignore` intentionally excludes:

- `.DS_Store` Finder metadata
- Python bytecode and caches
- `Browser Session/`, which may include cookies, browsing state, and saved sign-in sessions
- `Subtitles/`, `.srt`, `.vtt`, and generated item markers
- Your personal `Settings/settings.json`
- Your personal `My Links Txt/mylinks.txt`

The tracked templates contain no real account credentials, saved session data, or real BroadwayHD links. Before the first commit, review the staged files with:

```bash
git status --short
git diff --cached
```

## License

Copyright (c) 2026 mp3li. All rights reserved.

This project uses the non-commercial source-available license in [LICENSE](LICENSE). You may use, study, fork, modify, and share it for non-commercial purposes while crediting mp3li and keeping the project's protection boundaries intact. Commercial use requires prior written permission from mp3li.

## Responsible Use and Accommodation Disclaimer

This project was created for educational exploration and personal accessibility or accommodation-oriented subtitle workflows. It is not a tool for obtaining content outside the access a user already has.

Use it only with services, accounts, and material that you are legally permitted to use. Do not use it to defeat DRM, decrypt protected media, evade access controls, or obtain, copy, or distribute copyrighted material without permission from the rights holder.

You are responsible for ensuring that your use follows the service terms that apply to you, copyright law, and all other relevant rules in your location. The author and anyone who contributes to this project do not authorize unlawful use and cannot accept responsibility for misuse of the software.
