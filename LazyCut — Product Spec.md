# LazyCut — Product Spec

Nov 14, 2026 · @Zain Baquar

> **Status:** background and rationale. `BUILD_SPEC.md` is the source of truth for implementation. This document was updated on Nov 14, 2026, after the spec review, so the two agree.

## Summary

The app turns any imported video into a complete, honest publishing package for YouTube, Shorts, Instagram and TikTok. It replaces the current hand-off between a Claude project, Gemini and Higgsfield with a single workspace. Name: LazyCut. It is a personal tool that runs on your own machine at close to zero running cost.

**General by design.** Nothing in the core is tied to a genre or even to gaming. Everything specific to hard-action boss fights (event types, hit-count claims, title patterns) lives in a content preset. The soulslike boss-fight preset ships first and is the one TheLazyRonin uses.

**What it is.** A publishing copilot. It watches the video, finds the moments worth clipping, researches the subject and the competition, and writes every piece of text and metadata the upload needs.

**What it is not.** A video editor. There is no editing timeline, no effects, no captions burned in. The only video operation is cutting a clip at a start and end point, with an optional 9:16 crop.

**Design principles**

1. **The creator is the source of truth.** The model proposes; the creator confirms counts and other claimable facts before anything is written. Research findings (names, spelling, whether a boss is the final one) are accepted by default with their sources, and the creator can override any of them.
2. **Evidence on every claim.** Each claim in a title ("No Damage", "6 counters") links to the timestamps that support it.
3. **Rules live in config, not in prompts or code.** Channel conventions sit in the channel profile. Anything niche-specific, including claims such as "No Hit" and the facts behind them, sits in a user-defined preset. Both are data the creator edits, so the app works for other content and a second channel later.
4. **Prompt-driven clipping.** The creator says what they want ("every Issen chain", "the phase-two transformation"). Generic highlight detection failed on this footage.
5. **Copy-paste ready.** Every output is a block with a copy button, sized to the platform's limits.
6. **Each recommendation names the goal it serves:** click-through, retention, session watch time, engagement or funnel.

## The workflow today

A long-form upload currently takes four tools and about a dozen manual hand-offs. Each row below is something the app must do or deliberately leave out.

| Step | What happens now | Tool | Pain point |
| --- | --- | --- | --- |
| 1. Brief | State game, boss, run quality (no damage / X hits / clean), playlist | Claude (`/youtube-gaming-seo`) | Run quality is easy to forget, and the title depends on it |
| 2. Boss research | Web search for canonical spelling, real name, questline, phases, signature mechanic | Claude | Repeated from scratch; thin AI guide sites pollute results |
| 3. Video analysis | Paste a 10-part prompt into Gemini with the video attached; paste the answer back | Gemini | Manual copy-paste; timestamps approximate; Gemini miscounts and once could not hear audio |
| 4. Fact confirmation | Creator corrects counts and hits from memory | Chat | Nothing records the confirmed version |
| 5. Long-form package | Title + 3 to 4 alternates, description, chapters, about 20 tags, 3 hashtags, credit block, checklist | Claude skill | Chapters left as 0:00 placeholders because Claude cannot see the video |
| 6. Engagement extras | Retention hook, first-5-seconds opening, pinned comment question, end-screen target, community post | Claude | Depends on Claude knowing the playlist and prior uploads |
| 7. Clip selection | Creator scrubs footage or pre-trims clips, then asks for trim points | Manual + Gemini | The slowest step; auto-clippers key on speech and miss silent gameplay |
| 8. Short / Reel package | Benkei-template description, first-person title, on-screen hook, caption, hashtags | Claude | Rewritten per platform by hand |
| 9. Thumbnail | Upload a frame to the Higgsfield widget, generate at 16:9, check faces, hands and leftover HUD | Higgsfield | Chat attachments are not readable; widget sometimes fails |
| 10. Stories | Rebuild the thumbnail at 9:16 with safe margins | Higgsfield | Separate manual run |
| 11. Publish | Paste everything into YouTube Studio, Instagram, TikTok | Manual | No record of what was actually published |
| 12. Review | Share retention graphs and skip rates days later | Chat | Results never feed back into the next package |

### The Gemini analysis prompt

The current prompt asks for ten things, and these become the app's analysis schema: basics (length, aspect ratio, boss name from the health bar, on-screen text and its position), the first 7 seconds second by second, a full timestamped event log, a damage check, boss health over time, dead time of 1 second or longer, the peak 2 to 3 seconds, framing for a vertical crop, audio, and the first and last frame.

### Lessons already learned

- **Trim, never cut.** Clips are continuous gameplay. Only the start and end move; uncut footage is the proof of skill.
- **Creator beats model on facts.** Hit counts and counter counts come from the creator. Gemini's numbers are a draft to confirm.
- **Timestamps are approximate.** Every suggested trim point needs a preview and a nudge control.
- **Plain words on screen, game terms in the caption.** "6 perfect counters in a row" on the video; "Issen" taught in the caption and hashtags.
- **Each clip in a set needs its own angle.** Similar clips posted together read as repeats.
- **The hook must promise the payoff from frame one** when the best moment lands after second 7.

## Core modules

Five modules cover the starting feature list. Each one reads from and writes to a single shared record per video, so nothing is pasted between tools.

### 1. Video understanding

The creator imports a video and gets a structured, timestamped account of what happens in it.

- **Input:** a video file picked from a local import folder (long-form fight or a pre-trimmed clip), plus game and subject if known. Google Drive import comes later. Typical footage is 1440p at 60 fps, usually under 5 minutes and sometimes 5 to 10.
- **Engine:** Gemini with a structured-output schema built from the ten-part prompt. Because the footage is short, the video is sampled above the default 1 frame per second so fast events are not missed.
- **Output:** an event timeline whose event types come from the active preset (for boss fights: parries, counters, hits taken, phase changes, finishers), dead-time ranges, peak moments, on-screen text and HUD positions, vertical-crop safety per moment, audio notes.
- **Confirm step:** a short form asks the creator to confirm the facts the preset marks as claimable (for boss fights: hits taken and any counted mechanic). Confirmed values are locked and override the model everywhere.
- **Eye test:** model timestamps are approximate, so a review mode steps through each event with the video looping around it. The creator can move, retype, hide or verify each one. These edits and confirmations survive a re-analysis unless the creator chooses to discard them; a warning shows first.
- **Chapters fall out for free:** phase changes become real chapter timestamps instead of 0:00 placeholders.

### 2. Clip finder

The creator describes the clip they want and gets ranked candidates with trim points.

- **Input:** a free-text prompt ("longest counter chain", "the moment the boss transforms", "best 20 seconds for a Reel"), a target length and a platform.
- **Output:** 3 to 5 candidates, each with start and end timestamps, the reason it matches, where the payoff lands, dead time inside it, and a crop-safety warning.
- **Rules applied:** continuous footage only; start a beat before the first clash; end on the result flash, before any dissolve.
- **Actions:** preview, nudge either edge by half a second, export timestamps, or export the trimmed file (optionally cropped to 9:16 and scaled to 1080×1920). Exports keep the source frame rate and use a near-lossless encode.
- **Saved prompts:** recurring asks ("Issen chains", "no-hit phase") become one-click presets per game.

### 3. Metadata and SEO

One click produces the full package the `youtube-gaming-seo` skill produces today, with the video's own facts filled in.

- **Subject research:** fresh web search per boss for spelling, real name, epithet, questline, phases and mechanics, with sources shown and low-quality guide sites excluded.
- **Long-form:** recommended title plus 3 to 4 alternates, description with hook line, tactics, tagline, playlist and subscribe links, chapters, credit block, 3 hashtags, about 20 ordered tags.
- **Honesty check:** every claim is tested against the confirmed facts. A "No Hit" title on a 1-hit run is blocked, not warned. Claim wording comes from preset hook templates that are only offered when a confirmed fact supports them.
- **Extras:** retention hook, first-5-seconds opening, pinned comment question, end-screen target, community post.

### 4. Similar-video research

The app shows what already ranks for the target search and where the gap is.

- **Input:** the target query (game + boss + "boss fight"), generated automatically.
- **Output:** the top competing videos with title, channel size, views, age, length and thumbnail; the title patterns and thumbnail words they share; a demand-versus-competition read.
- **Analysis:** which angle is unclaimed (hit count, mechanic, speed, questline), and which of your own videos risk cannibalizing this one.
- **Sources:** YouTube Data API for search and stats; Google Trends checked by hand for demand over time.

### 5. Platform packaging

Every clip and every long-form video gets a package per destination, written to that platform's limits and habits. Formats are specified in the platform section below.

- **Long and short:** one video can produce a long-form package and any number of short packages, each linked back to its source.
- **One source, three captions:** the Short description, Reel caption and TikTok caption share facts but differ in length, hashtag count and call to action.

## Additional features

Nine additions beyond the starting list, ranked by how much manual work each removes. The first four are essential; the rest can wait.

| Feature | What it does | Goal served | Priority |
| --- | --- | --- | --- |
| Channel profile and rules engine | Stores conventions, templates, links and banned claims; validates every output against them | Credibility, click-through | Essential |
| Fact ledger | Records creator-confirmed facts per video (hits taken, counts, encounter number) with timestamps as evidence | Credibility | Essential |
| Content library | Every past upload with its title, angle, hook and playlist; powers end-screen targets and cannibalization warnings. Typed in by hand at first; imported from the YouTube channel later | Session watch time | Essential |
| Thumbnail assistant | Suggests frames that read at phone size, proposes the 2 to 4 word result word, and builds a ready-to-paste image prompt. Generation stays in the existing image tool in the first version | Click-through | Essential |
| Hook and retention check | Scores the first 7 seconds of a clip and the first 30 of a long-form video; flags a late payoff and suggests a start point or on-screen promise | Retention | High |
| Performance loop | Pulls CTR, retention, skip rate and shares after publishing; compares against your baseline; proposes changes to the profile | All five | High |
| Publish checklist and export | Per-upload checklist (category, captions, end screen, pinned comment) and a single Markdown export named to the current convention | Engagement | High |
| Next-video planner | Ranks candidate games and bosses by launch window, search demand and weak competition; suggests series and playlist order | Session watch time | Medium |
| Posting plan | Orders a set of clips so each has a distinct angle, spaces them out, and drafts the community post for the day before or after | Funnel | Medium |

**Deliberately out of scope:** timeline editing, text overlays rendered into video, music, auto-captions, auto-posting in the first version, and speech-based highlight detection.

## Channel profile and rules engine

The channel profile holds everything the Claude project instructions and the brief hold today, as editable settings. The rules engine checks each output against it and either blocks or warns.

### Profile fields

- **Identity:** channel name (TheLazyRonin; "The Lazy Ronin" in descriptions), handle, tagline, subscribe link, faceless format.
- **Templates:** the long-form description layout. Title patterns and the Short and Reel templates live in the preset, because their wording is niche-specific.
- **Links:** one playlist per game or series, inserted directly, never as a placeholder.
- **Thumbnail style:** white text with heavy black outline by default; no red text in fire-heavy arenas; (the gold style for no-hit runs is set on the preset's hook); text in the emptiest dark area; one template per series.
- **Strategy mode:** search-first now (game and boss lead the title); a switch to hook-first once browse and suggested traffic matter.
- **Baselines:** reference numbers for comparison, such as the Benkei reel (23% skip rate, 0.7% share rate).

### Content presets

A preset is a named configuration that adapts the general engine to one kind of content. Presets are optional. With none selected the app runs in General mode, with generic event types and only the universal rules, and handles any request. The user can switch a video to a preset, edit one, or create a new one from the workspace header.

| A preset defines | Soulslike boss-fight preset (first to ship) | What another preset would change |
| --- | --- | --- |
| Event vocabulary | Parry, counter, hit taken, phase change, finisher, dead time, peak | Rounds and combos for fighting games; encounters and resets for shiny hunts; topics and quotes for talking-head video |
| Facts to confirm | Hits taken, counted mechanics, encounter number | Match result, attempt count, speaker and claim |
| Subject research | Boss spelling, real name, epithet, questline, phases, mechanics | Character or matchup; species and method; topic and sources |
| Title patterns | `[Game] - [Boss] Boss Fight ([honest hook])` | Its own pattern and alternates |
| Hooks and claim rules | Hooks such as "No Hit" and "Only 2 Hits Taken", each tied to a confirmed fact; Final Boss / First Boss; epithet sourcing | Its own hooks and the claims that need proof |
| Templates | Short description and Reel caption in the boss-fight voice | Its own wording |
| Clip cues and saved prompts | Start a beat before the first clash; end on the result flash | Its own start and end cues |
| Tag recipe | Game variants, boss names, difficulty terms, mechanics, protagonist, studio | Its own ordered recipe |
| Thumbnail result words | NO DAMAGE, 1 HIT TAKEN, 2 V 1 | Its own vocabulary |

Presets are plain config files, so a new one is written and tested without code changes.

### Rules

| Rule | Check | Action |
| --- | --- | --- |
| Honest difficulty claims | "No Hit" / "No Damage" only when confirmed hits taken = 0 | Block |
| Required facts | No title is generated until the preset's required facts are confirmed (for boss fights: hits taken) | Block |
| Numbers need a fact | Any number in a title, hook or thumbnail word matches a confirmed fact | Warn |
| Final / First Boss | Used only when research with a credible source says so literally, or the creator sets it; otherwise "Final Fight", "first major boss" | Block |
| Search-first title | Game and boss name lead; hook follows in brackets | Warn (while in search-first mode) |
| No false genre tags | Tags on the preset's banned list (such as `soulslike`) are removed; mechanic tags are used instead | Auto-fix, shown |
| No invented epithets | Boss titles need a credible source (a site on the creator's trusted list) or the creator's own entry | Left out until sourced |
| Canonical spelling | Creator's spelling corrected against research (Shuten, Yoshitsune) | Auto-fix, shown, one-click revert |
| Cannibalization | A boss already in the library needs a distinct angle or a compilation | Warn with suggestion |
| Chapters | First at 0:00, at least 3, each 10+ seconds apart; left out when the video cannot give three | Block |
| Hashtags | Exactly 3 on long-form; 5 including #Shorts on Shorts | Auto-fix |
| Uncut clips | A clip is one continuous range: only the start and end move, nothing is removed from the middle | Built in; the app cannot make any other kind |
| Own footage only | Thumbnail source that looks like another creator's image is flagged | Warn (arrives with the thumbnail phase) |
| Safe margins | Vertical text kept out of the top 12% and bottom 15% | Shown as guides on the vertical preview |
| Every Short points home | Short, Reel and TikTok packages include the full-fight or playlist link or mention | Block |

**Universal rules** apply to every preset: claims need a confirmed fact, numbers need a fact, canonical spelling, cannibalization, chapters, hashtag and tag counts, banned tags and the link back. What counts as a claim (No Hit, Final / First Boss), which tags are banned and which research fields need a credible source are defined by the preset, so the boss-fight versions can be changed or replaced without code. Uncut clips are built into the app, not a rule.

## Platform outputs

YouTube long-form, Shorts and Instagram have established conventions; TikTok has none yet and starts from the Reel package. Character and length limits should be stored per platform in config and checked against each platform's current documentation at build time.

| Output | YouTube long-form | YouTube Shorts | Instagram Reels | TikTok |
| --- | --- | --- | --- | --- |
| Title | `[Game] - [Boss] Boss Fight ([honest hook])` plus 3 to 4 alternates | Short, first-person, one emoji, game hashtag | None | None |
| Text body | Hook line, 3 to 5 sentences of tactics, tagline, playlist, subscribe, chapters, credit block | Benkei template: hit-count hook, one tip that pays off in the clip, playlist link | Caption: what happens, the mechanic explained in one line, a question | Starts as the Reel caption, shortened |
| On-screen text | None | Optional hook line | Plain-language hook; end card "Full fight on YouTube @thelazyronin" | Same as Reel |
| Hashtags | Exactly 3 | 5 including #Shorts | About 5, including the game and mechanic | To be tested |
| Tags | About 20, most important first | None | None | None |
| Link back | End screen to the next video in the playlist | Playlist link in description | Pinned comment pointing to the full fight | Profile link or comment |
| Visual | 16:9 thumbnail with result word | Frame choice | 9:16 cover; Story version of the thumbnail | 9:16 cover |
| Clip shape | Full fight | Continuous clip, payoff early | Continuous clip, about 20 seconds has worked | Same clip as Reel |
| Extras | Pinned comment, community post, checklist | Tip matched to what is on screen | Posting order and spacing for sets | None yet |

### Short description template

```
[Hit-count hook]. That's all [Boss] got. [emoji]

[One specific tip that pays off during the clip, 2 sentences.]

Full fight + every boss: [playlist link]

#[Game] #[Boss] #[GameFullName] #BossFight #Shorts
```

### Reel package shape

```
ON-SCREEN: [plain-language hook with a number]. No cuts.

CAPTION: [What happens]. [The game's term, explained in one line.]

[Question that invites a reply]

Full boss fights on YouTube: TheLazyRonin

#[Game] #[GameFullName] #[Boss] #[Mechanic] #BossFight
```

## Interface

The app is organized around one editor-like video workspace: clips on the left, the player in the centre, a shared timeline underneath and the package on the right. Research and Thumbnail are separate pages. The screens below cover everything.

| Screen | Purpose | Key elements |
| --- | --- | --- |
| Library | All videos and their status | Cards by game and series; status (analyzed, confirmed, packaged, published); search by boss |
| New video | Start a project | Pick a file from the import folder; game, subject, type (long-form or clip); preset |
| Video workspace | The main screen | Clips panel, player, timeline (events, filmstrip, intensity, dead time), package panel with a full-package drawer |
| Past uploads | What is already published | A table typed in by hand at first; videos marked as published are added automatically |
| Channel profile | Conventions and templates | Editable rules, templates, playlists, thumbnail style, strategy mode |
| Planner | What to make next | Ranked candidates, series and playlist order, posting calendar |
| Performance | Results after publishing | Per-video metrics against baseline; suggested profile changes |

### Video workspace areas

These began as tabs in the first draft. In the approved design the first three share one screen, and Research and Thumbnail are their own pages.

- **Analysis.** The event timeline as colored markers under the player (counters, hits taken, phase changes, dead time, peak). Clicking a marker seeks the player. A review mode steps through the events for an eye test. The facts to confirm sit at the top of the package panel.
- **Clips.** A prompt box with saved presets, a platform and length picker, and candidate cards. Each card shows a mini preview, the range, why it matched, and nudge buttons. Selected clips appear as ranges on the timeline.
- **Package.** A platform switcher across the top. Each field is a block with a copy button, a character count and a rule badge (pass, warn, block). Alternates sit beside the recommended title with a one-line reason and the goal served.
- **Research.** Subject facts with sources on one side; competing videos as a grid on the other, with the gap analysis above.
- **Thumbnail.** Suggested frames from the video, result-word options, the image prompt to copy, and the checklist (faces, hands, leftover HUD, text placement). Generated variants side by side come later, once generation moves into the app.

### Main flow

1. Import the video from the local folder and name the game and subject.
2. Analysis and subject research run in parallel.
3. Eye-test the event timing, then confirm the counts.
4. Review the long-form package; adjust the title choice.
5. Prompt for clips; pick and nudge; generate short packages.
6. Pick a thumbnail frame and result word; copy the image prompt.
7. Export everything, publish by hand, tick the checklist.
8. Return in two days to log performance.

## Architecture and data model

The app is a pipeline around one video record: three inputs fill it, three generators read it, and the rules engine gates everything that leaves.

&#91;embedded content: pipeline · 3 inputs, 1 record, 3 generators, 1 gate\]

Analysis and research run once per video and are cached; generators can be re-run cheaply without re-watching the video.

### Suggested stack

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | Next.js | Already in your stack; good for the editor-like workspace layout |
| Backend | Python with FastAPI | Already in your stack; background jobs for analysis |
| Video understanding | Gemini, structured output | It is what the workflow uses today; no other step needs to see the video |
| Runtime | Docker Compose on the local machine | One command to start; nothing hosted |
| Video import | Local import folder; Google Drive later | The files are already on the machine |
| Writing | Gemini on the free tier by default; Claude as an optional paid upgrade | The model is swappable behind one interface. The SEO skill and playbook port over as prompts plus the profile and presets |
| Rules | Plain code, no model | Checks must be deterministic |
| Orchestration | Plain in-process job runner | Analysis, research and confirm are a small flow with one human step; no graph framework needed |
| Clip cutting | ffmpeg | Trim and optional 9:16 crop only |
| Thumbnails | Frame and prompt export for Higgsfield | Existing prompts carry over; generation stays outside the app until API access is confirmed |
| Research data | YouTube Data API, web search; Google Trends by hand | Competitor stats and demand |
| Performance data | YouTube Analytics API; manual entry for Instagram and TikTok at first | Closes the loop |
| Storage | SQLite and local disk | Single user to start |

### Running it for free

Every component has a no-cost route for one person's volume. The only real trade-offs are rate limits and Gemini's free-tier data terms.

| Component | Free route | Catch |
| --- | --- | --- |
| Video analysis | Gemini API free tier, Flash models | Lower rate limits than paid; free-tier content can be used to improve Google's products; exact limits show in AI Studio ([pricing](https://ai.google.dev/pricing), [free-tier guide](https://yingtu.ai/en/blog/google-gemini-api-free-tier-limits-2026)) |
| Writing and rules | Same Gemini key | Quality to compare against the current Claude packages; a Claude API key is an optional pay-per-use upgrade |
| Subject research | Gemini search grounding or a free search API tier | Confirm grounding is included on the free tier |
| Similar-video research | YouTube Data API free daily quota | Searches are the expensive call; cache results per boss |
| Demand | Google Trends checked by hand | No automation at first |
| Clip cutting | ffmpeg | None |
| Thumbnails | The Higgsfield plan you already use; the app exports the frame and prompt | No new cost, but generation stays outside the app until API access is confirmed |
| Performance data | YouTube Analytics API; manual entry for Instagram and TikTok | Needs a one-time Google OAuth setup |
| Hosting and storage | None: local app, local files | Only usable on that machine |

### Data model

| Entity | Holds |
| --- | --- |
| Channel | Identity, active content presets, templates, universal rules, playlists, thumbnail style, strategy mode, baselines |
| Game | Title variants, studio, platforms, accurate genre and mechanic tags, saved clip prompts |
| Subject | Boss name, real name, epithet with source, questline, phases, mechanics, research sources |
| Video | File, type (long-form or clip), game, subject, status |
| Analysis | Event timeline, dead time, peak moments, HUD and text positions, crop safety, audio notes |
| Fact | Creator-confirmed value (hits taken, counter count, encounter), evidence timestamps |
| Clip | Source video, start, end, prompt that produced it, platform targets |
| Package | Platform, fields, alternates, rule results, export history |
| Thumbnail | Source frame, result word, prompt, variants, chosen one |
| Competitor snapshot | Query, date, ranked videos with stats, gap analysis |
| Performance | Per published item: CTR, retention, skip rate, shares, date logged |

In the first version Game and Subject are not separate records. The video carries the game and subject names plus optional extra terms, and research is shared between videos by matching those names. Thumbnail, Competitor snapshot and Performance arrive with their phases. The exact tables are in `BUILD_SPEC.md`.

### Analysis event schema

```
{
  "t_start": 12.5,
  "t_end": 13.0,
  "type": "counter | parry | hit_taken | boss_attack | phase_change | finisher | dead_time | peak",
  "label": "Issen counter on leaping slash",
  "intensity": "low | medium | high",
  "crop_safe_9x16": true,
  "confidence": "certain | uncertain",
  "source": "model | user",
  "verified": false
}
```

Event types come from the content preset, and each game or topic adds its own vocabulary (Issen, deflect, Oni Awakening) so the analysis prompt and clip presets stay specific.

## Build phases

Build the personal tool first: phase 1 alone replaces the Gemini copy-paste and the placeholder chapters, which are the two biggest time sinks. A short spike comes before it, because everything rests on how well Gemini reads fast gameplay through the API.

| Phase | Scope | Done when |
| --- | --- | --- |
| 0. Accuracy spike | Run the analysis through the API on two or three real fights and one general video at several sampling rates; compare with hand-counted events | The sampling rate is chosen from measured results and the free-tier limits are known |
| 1. Understand and package | Import from the local folder, Gemini analysis to schema, event review and confirm flow, subject research, long-form package with real chapters, channel profile and presets with the block rules, past uploads typed in by hand, Markdown export | One boss fight and one general video are each packaged end to end without opening Gemini or the Claude project |
| 2. Clips | Prompt-driven clip finder, preview and nudge, ffmpeg trim and 9:16 crop at 1080×1920, Shorts and Reel packages, saved prompts | A Reel is chosen, trimmed and captioned from a full fight in one sitting |
| 3. Research, thumbnails and imports | Similar-video research and gap analysis, cannibalization warnings, past uploads imported from the YouTube channel, Google Drive import, frame suggestions and prompt builder, preset editor | Title choice cites the competition; the thumbnail prompt needs no rewriting |
| 4. Loop and plan | Performance logging and baselines, profile suggestions, next-video planner, posting plan, TikTok package | Two days after a post, the app says what to change next time |
| 5. Parked: product | Multiple channels, profile setup for other niches, accounts and billing, direct publishing | A second creator sets up a profile without your help |

Phases 1 and 2 need no platform API approvals, so they can be built and used immediately.

## Open questions

- [x] **Decided: personal tool.** Built for one user. Phase 5 is parked; presets stay as config so nothing blocks it later.
- [x] **Decided: local.** No hosting or storage bill, and footage leaves the machine only for Gemini analysis.
- [x] **Decided: import folder.** Videos are picked from a local folder. Google Drive import follows in phase 3.
- [x] **Decided: nothing niche is hard-coded.** "No Hit" and every other claim is preset config the creator defines.
- [x] **Decided: research is the default.** Research findings apply as found; the creator can override any field.
- [x] **Decided: clip export.** The app exports the trimmed file at the source frame rate, with 9:16 scaled to 1080×1920, and always offers the timestamps too.
- [x] **Decided: re-analysis keeps the creator's work** unless they choose to discard it, with a warning first.
- [ ] **Gemini limits.** Phase 0 confirms the current model, the token cost per minute of footage and the highest sampling rate the free tier allows for a 10-minute video.
- [ ] **Timestamp accuracy.** Phase 0 measures how far a higher sampling rate, a narrow second pass and a visual snap tighten the timestamps. The eye-test review covers whatever error remains.
- [ ] **Higgsfield access.** Confirm an API or connector route that works outside a Claude chat; until then the thumbnail page exports a prompt and frame instead of generating.
- [ ] **Trusted research sites.** List the guide sites that count as credible sources for epithets and final-boss claims.
- [ ] **TikTok conventions.** None exist yet. Decide whether to post the same clips as Reels and what the link-back is.
- [ ] **Performance data for Instagram and TikTok.** Manual entry or screenshots to start, or wait for API access.
- [ ] **Second preset.** The boss-fight preset ships first. Pick the next one to prove the core is general: fighting-game sets, shiny hunts, or a non-gaming format.
- [x] **Name.** Decided: LazyCut.
