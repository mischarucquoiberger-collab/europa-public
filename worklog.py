"""Send a short build log to PRISM: one trace per finished work step, under the agent that did it.

No model is called here and no credits are used. Each entry is the request and
the verified result, written without file paths, names or secrets, and it still
goes through redact() like every other trace.

    python3 worklog.py            # send every step
    python3 worklog.py --last 3   # send only the newest 3 (earlier ones stay as history)

Agents: the lead plans, specifies and verifies; builders are the sub-agents that
implement a task from the lead's written brief. Every finished agent task gets a
step here, so all agent work shows in PRISM.
"""
import sys
import time

import config
import prism
from redact import redact

# role -> (PRISM agent id, model label)
AGENTS = {
    "lead": ("europa-build-log", "claude-fable-5-2"),
    "builder": ("europa-ui-builder", "claude-opus-5-5"),
    "reviewer": ("europa-plan-review", "claude-opus-5-5"),
    "backend": ("europa-backend-builder", "claude-opus-5-5"),
}

# (role, request, verified result), oldest first
STEPS = [
    ("lead", "Copy the product's web interface into the project folder exactly as it is, with no server code.",
     "Done. The interface was copied file for file, and every copied file was compared with the original by "
     "checksum, with no differences. Its own checks passed in the copy: code style, type check, the full "
     "test suite and a production build. The original was not changed."),
    ("lead", "Remove the sign-in step so the app opens directly on its home page.",
     "Done. The app now opens straight on the home page with no sign-in. Each page was opened in a browser "
     "check with no errors, and the test suite passes."),
    ("lead", "Keep only Home, Reports and Query. Delete everything that is not used, including all sign-in code and "
     "server leftovers.",
     "Done. Only the three pages and what they use remain: 99 files, down from 630. All sign-in code and its "
     "package are gone, along with unused pages, their tests and 59 unused packages. Checked afterwards: "
     "style check clean, type check clean, 269 of 269 tests pass, the production build succeeds, and every "
     "page opens with no errors."),
    ("lead", "Change the accent colour to the brand navy and replace the old logo with the new one, consistently "
     "across the app.",
     "Done. The accent is the brand navy on the menu highlight, buttons, focus rings and progress bars, with "
     "light ink where the surface is dark so nothing disappears. The new logo is in the header and the "
     "loader, the home page uses the logo's own background colour, and the tab title and icon match. All "
     "269 tests pass and the build succeeds."),
    ("lead", "Replace the Query page with the Deep Research screen from the original interface, remove what is no "
     "longer used, and set the menu button in the same typeface as the logo.",
     "Done. The Deep Research screen was copied from the original interface and is the third menu entry. "
     "The Query page and everything only it used were removed, including three packages. The menu button "
     "now uses the logo's typeface. Checked: style and type checks clean, 205 of 205 tests pass, the build "
     "succeeds, and Home, Reports and Deep Research open with no errors. Deep Research shows its opening "
     "screen and a retry notice, because the research service it embeds is not part of this build."),
    ("lead", "Make the company wordmark just the word, in the same lettering as the menu button, with no image.",
     "Done. The header now shows the company name as a word drawn in the same lettering as the menu button, "
     "at the same letter height, and the image is gone. Two letters the lettering lacked were drawn to its "
     "construction rules. The loader shows the same wordmark. It reads in light ink on dark pages and dark "
     "ink on light pages. Checked: style and type checks clean, 205 of 205 tests pass, the build succeeds, "
     "and the three pages open with no errors."),
    ("lead", "Make every page the brand navy, with the same blue as the home page.",
     "Done. Reports, the report builder, the report viewer, the menu search, the phone notice, the error and "
     "not-found pages and the loading screen are all on the brand navy with light ink. The generated report "
     "document itself stays on white paper. Buttons that were dark are now light so nothing disappears. "
     "Checked on screen for each page, with the test suite passing."),
    ("lead", "Rename the research product, and after its opening screen show the real research workspace, exactly "
     "as in the original product, with the interface only.",
     "Done. The opening screen and every sentence now carry the new product name, in the same lettering. "
     "After it, the real research workspace opens: the original built interface, served locally with fixed "
     "start-up answers in place of a server. Its side panel, search, question box and menu tab all work as "
     "in the original. No answer is invented: a question that is sent gets a plain notice that the research "
     "service is not connected yet. Checked in a browser on desktop and phone with no page errors."),
    ("lead", "Add a small spinning planet to the company logo, taken from the existing planet renderer, with an "
     "entrance when the page is first viewed.",
     "Done. The logo is now a small planet beside the company name. It is drawn by the existing character "
     "renderer, spins slowly, and rises into place once per page load. It stays still for people who ask "
     "for reduced motion, and the logo falls back to the word alone where the graphics feature is missing. "
     "Checked: style and type checks clean, 226 of 226 tests pass, and the production build succeeds."),
    ("lead", "Name the research page after the moon in the menu, and make its opening screen show only that one "
     "word, large, in the header lettering, with the product's original two words on the swipe after it.",
     "Done. The menu, the search panel, the tab title and the links to the page all use the new name. The "
     "opening screen shows only the one word, large, in the bold header lettering, filling in as it loads. "
     "The swipe that follows shows the two original words, and then the workspace opens. Checked: style and "
     "type checks clean, 226 of 226 tests pass, the build succeeds, and the sequence was watched frame by "
     "frame in a browser with no page errors."),
    ("builder", "Turn one page from a white ground with dark text into the brand navy with light text. Colours only: "
     "layout, wording and behaviour must not change.",
     "Done. The page, its search box, its lists and its buttons are on the navy ground with light ink, and the "
     "accent that would have vanished on navy is now light. Checked on screen in four states, with the page's "
     "own tests passing and the style check clean."),
    ("builder", "Do the same for the two work pages and their dialog, but keep the generated document itself on "
     "white paper.",
     "Done. The surrounding interface of both pages and the dialog is navy with light ink; the document area "
     "stays white. Warning, success and error colours were kept and lightened so they still read. Checked on "
     "screen, tests passing. One dialog could not be opened without a server and was converted from its code."),
    ("builder", "Rename the research product on its opening screen, move that screen from black to navy, and stop "
     "it from hanging when the service behind it is absent.",
     "Done. The opening screen carries the new name in the same lettering on navy. When the service is absent "
     "the screen now plays through once and hands over, instead of retrying into an error. A real service that "
     "is merely busy is still retried as before. New tests cover the name, the ground and both cases."),
    ("builder", "Port the existing character-drawn planet into the logo as a small spinning mark beside the company "
     "name, with an entrance on the first view.",
     "Done. The renderer was ported as a self-contained module with a see-through ground, sized from the logo. "
     "It spins, rises in once per page load, stays still under reduced motion, and frees its graphics context "
     "when removed. Without the graphics feature the logo is the word alone. Eleven new tests, all checks clean."),
    ("lead", "Make the reports side cover companies listed in the United States only, with nothing left that "
     "refers to the previous market, and make sure every agent's work is logged here.",
     "Done. The brief was written for a builder and its result was checked on screen and by the full test "
     "suite. The page, its search examples, its built-in company list and its ticker rule are now for the "
     "United States, and the research workspace and the legal source list no longer name the previous "
     "market's systems. From this step on, each builder task is logged under its own agent as well as the "
     "lead's. Checked: style and type checks clean, 231 of 231 tests pass, the build succeeds."),
    ("builder", "Switch the reports search from four-digit codes of the previous market to United States ticker "
     "symbols, with a built-in list of real listed companies, and update every label that named the old "
     "filing system or currency.",
     "Done. Symbols are one to five letters with an optional class suffix, and an ordinary word counts as a "
     "symbol only when it is in the company list, so a page name never starts a report. The built-in list "
     "has 47 listed companies, large and small, with their registered names. Filing and currency labels use "
     "the United States terms. Six tests for the old search were replaced by new ones; 231 of 231 pass."),
    ("lead", "Add the prepared splash page to the main app as its opening screen, with the company name drawn "
     "in the header lettering.",
     "Done. The bare address now opens the splash: the start button, the name filling in while two lines "
     "of text pass, then the curtain lifts on the large rotating moon, and its link leads on into the "
     "research product. The page is as supplied apart from three things: the company name uses the header "
     "lettering, the link goes into the app, and it uses the app's icon. A small script repeats the copy "
     "when the source page changes. Checked: watched frame by frame in a browser, style and type checks "
     "clean, 235 of 235 tests pass, the build succeeds."),
    ("lead", "Publish the project so a teammate can start on the backend, and make sure nothing secret goes "
     "with it.",
     "Done. The whole history was scanned first: no key is in it, and the key file is ignored. A short guide "
     "for the teammate was added: the working rules, how to set up and check, how to run the interface, and "
     "which calls the interface already makes. The project was then pushed to a new private repository, and "
     "the pushed commit was confirmed to match the local one. Checked before pushing: all tests pass on both "
     "sides of the project."),
    ("lead", "Remove the start button from the splash so it plays by itself, also after a reload.",
     "Done. The splash now plays as soon as the page opens, on every load, with nothing to click first. "
     "The loader covers the page from the first paint, so nothing shows before it. Checked in a browser "
     "on a first load and again after a reload, then through to the link into the app. Style and type "
     "checks clean, 236 of 236 tests pass, the build succeeds."),
    ("lead", "Make the splash part of the app itself: it should play on every load and reload and then show "
     "the app directly, with no page in between.",
     "Done. The splash is now a layer inside the app. It plays on every page load, with the company name in "
     "the header lettering and the two lines of text, and then lifts straight onto the page beneath. The "
     "separate page that used to follow it was removed. A route change inside the app does not replay it. "
     "Checked in a browser on a first load, after a reload and after a reload on another page. Style and "
     "type checks clean, 236 of 236 tests pass, the build succeeds."),
    ("lead", "Replace the links at the foot of the menu with a credit line for the team.",
     "Done. The foot of the menu now shows one credit line for the team in place of the two legal links. "
     "The legal reader those links opened, and the data only it used, were removed with them, along with "
     "their tests, so nothing unused is left behind. Checked in a browser on desktop and phone. Style and "
     "type checks clean, 230 of 230 tests pass, the build succeeds."),
    ("lead", "Plan the backend for the research mode: reuse what works from the earlier product, adapt it to "
     "the new market, and have independent reviewers check the plan before any code is written.",
     "Done. A written plan now covers the contract the interface already speaks, the data sources, an "
     "evidence ledger that ties every figure to an openable source, the checks that keep the model from "
     "inventing numbers or giving advice, and the before and after proof. Five independent reviews were run "
     "in parallel and their corrections folded in: several assumptions in the first draft were wrong and "
     "are now fixed in the plan. No code has been written yet; the plan waits for the owner's go."),
    ("reviewer", "Check the plan against what the interface really calls and reads.",
     "Found four mismatches that would have broken the report flow without any error message: one step name, "
     "the routes the development proxy does not forward, and the exact formats of the job identifier and "
     "the report file name. Also found three planned routes that nothing calls. Each came with the evidence "
     "and the correction."),
    ("reviewer", "Check how much of the earlier product can really be reused.",
     "The plumbing can be reused nearly as it is: the job queue, the progress estimate, the route handlers "
     "and the metric definitions. The analysis and checking modules cannot: each depends on ten to twenty "
     "others and on the old market's data, and two of them call models directly. Recommended small fresh "
     "modules for those, and corrected the list of steps and status fields."),
    ("reviewer", "Check the assumptions about the two data providers against their current documentation.",
     "The public filings source matches the plan. For the market data provider three assumptions were "
     "wrong: its fundamentals and its live quote are not on the lower plans, its fundamentals carry no link "
     "to the filing, and its lowest plan allows only a few calls a minute. Listed what remains unconfirmed "
     "until a key is available."),
    ("reviewer", "Attack the plan's logic against the judging points and the time left.",
     "Found that a fuzzy number check could both delete correct sentences and let wrong numbers through, "
     "that the filing data can put the wrong year under a period, that a calculated figure had no chain a "
     "user could open, and that a guess could still leak past the do-not-know rule. Proposed exact fixes "
     "for each and a thin end-to-end slice to build first."),
    ("reviewer", "Check what would break when the plan is built and run on this machine today.",
     "Found that the model wrapper blocks and does not stream while the interface expects a stream, that "
     "blocking calls would freeze progress polling, that only one of the installed interpreters has the "
     "needed packages, that two default ports are taken, and that tests could have picked up real keys. "
     "Each came with the smallest change to the plan that removes it."),
    ("lead", "Build the backend for the research mode within the hour: reuse the earlier product's logic, "
     "connect every data and model service, and make the interface work against it.",
     "Built and running locally. The lead pinned the interface's contract in tests, wrote each builder's "
     "brief with exact interfaces so five builders could work in parallel on separate files, and three "
     "readers mapped the earlier product's logic for porting. The pieces fit on the first joint run: the "
     "full offline suite passes and a report started from the interface reaches the backend and reports "
     "its progress. One data source still waits for a contact line only the owner can set; the page says "
     "so in plain words. Nothing is invented while it waits."),
    ("builder", "Build the layer that talks to the two data providers, with caching, limits and a replay mode.",
     "Done. One client handles retries, per-provider limits, a disk cache and three modes: live, record and "
     "replay from saved public responses. Keys and contact details travel only in request headers and are "
     "never stored. The filings source refuses to call out until it is properly identified. 71 offline "
     "tests pass."),
    ("builder", "Build the evidence ledger: every figure tied to its filing, every calculation to its inputs.",
     "Done. Reported figures are selected by their own dates, never by the filing's year label, and a "
     "restated figure takes the newest filing. Calculated figures carry their formula and inputs, so a "
     "reader can follow each one back to its filings. A missing figure is reported as not available, never "
     "as zero. One function turns a figure into text, so wording and links cannot drift."),
    ("builder", "Build the report jobs, the routes the interface calls, and the ten-step pipeline.",
     "Done. Routes, identifiers and file names match what the interface expects. The pipeline walks the "
     "ten steps in order, treats optional data as optional, and never leaves a job running after a "
     "failure: it ends with a plain message. A report file is announced only after it exists. 25 offline "
     "tests pass."),
    ("builder", "Build the writer, the check that keeps invented numbers and advice out, and the report page.",
     "Done. The model receives labels and placeholders, never values, and writes placeholders that code "
     "replaces with the figure and its link. Any sentence with a number typed by the model, an unknown "
     "placeholder or advice wording is removed and listed as withheld. The report page lists every source "
     "and every calculation with its inputs. 31 offline tests pass."),
    ("builder", "Build the report chat and the set of test cases for the before and after proof.",
     "Done. Whether a question is covered is decided in code before any model call: an uncovered question "
     "gets a fixed do-not-know answer with what is covered, and a request for advice gets a fixed refusal "
     "with the reported figures. A model failure falls back to a sentence built from the cited figures. "
     "Fourteen cases and a runner are ready; they have not been run against the model yet."),
    ("reviewer", "Map how the earlier product generates a report, so its logic can be ported.",
     "Wrote three maps: the report pipeline stage by stage, the report template with the data each section "
     "needs, and the valuation, risk and chat logic. Each names what ports as it is, what needs changes and "
     "what must be left out, including a target price that would count as advice."),
    ("builder", "Add the moon to the research mode's opening screen in a way that makes people look twice.",
     "Done. A very large text-art moon now rises as a horizon behind the lettering on the opening screen and "
     "slowly turns. Its characters start scrambled and settle into the real surface from left to right, in "
     "step with the lettering as it fills, so the whole horizon is complete when the counter reaches one "
     "hundred. The existing timing, counter and wipe are unchanged, and the layer removes itself afterwards. "
     "Checked in a browser on desktop and phone sizes. Style and type checks clean, 236 of 236 tests pass."),
    ("lead", "Show the moon the research mode is named after in place of the red planet on its first screen, "
     "and make the team credit in the menu bold and a little larger.",
     "Done. The rotating text-art planet on the research mode's first screen is now the moon, drawn from a "
     "public-domain survey map of its real surface in its own colours. The credit line in the menu is bold "
     "and a step larger. I reviewed the builder's opening-screen work against screenshots and re-ran the "
     "checks myself: style and type checks clean, 236 of 236 tests pass. One thing is left for the owner to "
     "decide: on a direct page load the opening screen plays underneath the app's own splash and is not seen."),
    ("lead", "Take the moon back off the research mode's opening screen: the moon should appear only on the "
     "first screen behind it, after the swipe.",
     "Done. The opening screen is back to the lettering, the counter and the swipe, exactly as before. The "
     "moon now appears only on the research mode's first screen, once the swipe has opened it. Walked the "
     "whole path in a browser from the home page: the opening screen has no moon, the swipe plays, and the "
     "moon is drawn and settled on the screen behind it. Style and type checks clean, 230 of 230 tests pass."),
    ("lead", "Make the moon on the research mode's first screen arrive with a rich pixelated fade-in.",
     "Done. The moon now switches on as a mosaic: large flat tiles appear in a scattered order that drifts "
     "from the lit edge, each with a brief flare, then break into smaller tiles, single cells and finally "
     "into the text-art surface. The settled picture is unchanged. Captured in a browser at five points of "
     "the arrival with no errors. 230 of 230 tests pass."),
    ("lead", "The tile effect was not what was asked: the moon should fade in pixel by pixel.",
     "Corrected. Every character of the moon now fades in on its own, in a scattered order with a slight "
     "drift from the lit edge: each first glows as one soft pixel and then sharpens into its character. "
     "The arrival also now waits until the opening screen has gone, because before it was playing "
     "underneath that screen and could finish unseen. Walked the path in a browser from the home page: the "
     "moon stays unrevealed while the opening screen is up, then fades in. 230 of 230 tests pass."),
    ("lead", "Run a final check of the backend against live services before calling it ready.",
     "Done, and it found three real faults that the offline tests had missed, all now fixed and covered by "
     "tests. The chat was sending a format the interface does not display; it now sends the right one with "
     "each figure linked to its source. The check that removes invented numbers was cutting sentences at "
     "company names and rejecting dates the records themselves hold; both are corrected, while any other "
     "typed number still removes its sentence. A missing opening section is now built from the recorded "
     "figures. On the live run the model wrote every figure as a placeholder and nothing was withheld. One "
     "data source still waits for a contact line that only the owner can set."),
    ("lead", "Connect the last data source and produce the first real report end to end.",
     "Done. With the owner's contact line in place the filings source answered, and a real report was "
     "generated from live data in about ten seconds: seventy filings as sources, every figure linked to "
     "its filing or to a shown calculation, all four sections written with no sentence withheld, and no "
     "missing cells. Headline figures were checked against the filings. The report opens in the "
     "interface's viewer and appears in the recent list. The chat answered a covered question with a "
     "cited figure, refused advice, and said it did not know an uncovered year. That last answer exposed "
     "a misleading sentence about coverage, which is fixed and tested."),
    ("backend", "Port the original product's risk synthesis for US annual filings: split a filing into its risk "
     "passages and group them into themes, each with an exact quote from the filing.",
     "Done. A filing's text is split into its numbered items (annual and foreign-issuer layouts), the risk "
     "section into one passage per risk heading, and one structured model call groups the passages into "
     "themes. Every quote shown is the filing's own characters, located in the cited passage by code; a "
     "theme whose quote cannot be found is dropped, and a failed model call falls back to the filing's own "
     "headings. Eighteen new tests pass. Open point reported honestly: heading detection is judged from "
     "line shape and was tested on a made-up filing only."),
    ("backend", "Port the original product's durable job registry, its time-remaining estimate and its live "
     "progress stream, without changing the interface contract.",
     "Done. Jobs are now rows in a local database with write-ahead logging; a second start for the same "
     "company returns the open job; a job cut off by a restart is marked interrupted and queued jobs start "
     "again. The time estimate blends the time left in the current step with the expected time of the "
     "later steps and learns from every finished report. A progress stream sends events with a resumable "
     "cursor and keep-alives. Fifty tests pass and the route tests are unchanged."),
    ("backend", "Port the original product's valuation maths as scenario arithmetic and the company's own "
     "multiples, with every input cited and no value per share.",
     "Done. Growth is a blend of two-year and four-year compound rates from filed revenue; beta is the "
     "least-squares slope of daily returns against a market series; the discount rate is built from "
     "stated assumptions and falls back to the cost of equity with its reason when debt inputs are "
     "missing; a multi-year cash-flow projection gives a grid of enterprise values across discount "
     "rates and terminal growth. Four multiples are computed from the last close and filed figures. "
     "Fifty-seven new tests pass; the whole suite was green at hand-back."),
    ("backend", "Port the original report page format and fill it with US data, every figure still linked "
     "to its filing or its calculation.",
     "Done. The page is the original's sheet: header bar, narrative beside a figures sidebar, four "
     "five-year mini charts, the income statement, a two-column grid (capital structure, leverage, cash "
     "flow, per-share figures, balance-sheet trend, stock data, peers, corporate information), a "
     "scenario panel, capital allocation, risk themes and the disclosure footer, plus sources, "
     "calculations and withheld sentences. The builder rendered it, looked at the screenshot and fixed "
     "four visual faults. Fourteen page tests pass. Reported differences from the original are listed "
     "for the next round."),
    ("lead", "Review the four finished builders, make the backend parallel and self-checking, and bring the "
     "page closer to the original, with bull and bear cases.",
     "Reviewed the four hand-backs and the rendered page against the owner's reference report. Made the "
     "evidence ledger safe to read from several branches at once, with a test. Wired scenario "
     "arithmetic, multiples, peer names and risk themes into the pipeline as optional steps. Assigned "
     "the next round to five builders on separate files: a parallel pipeline with two independent "
     "model reviewers that check every written sentence; bull and bear points chosen by fixed rules in "
     "code and only worded by the model; a peer benchmark from each peer's own filings with medians; "
     "bear, base and bull valuation cases; and the matching page blocks. Decision recorded: no target "
     "price and no comparison that reads as a recommendation."),
    ("backend", "Make the report pipeline parallel and add a self-check in which the model's writing is read by "
     "independent model reviewers before it is shown.",
     "Done. All data fetches run at once; after the figures are selected, peers, risk themes, bull and "
     "bear wording and the written sections with their self-check run as overlapping branches, each "
     "with its own time limit, and a late branch is left out with a plain note. Two reviewers with "
     "different instructions read every written sentence against the fact list; a sentence either one "
     "rejects is removed and listed with the reason. Every model call passes one shared gate with "
     "retries. Seventy-two tests pass, with overlap proven by barriers and no real waiting."),
    ("backend", "Add an investment thesis and bull and bear cases in which code decides what is favourable "
     "and the model only words it.",
     "Done. Twenty-eight fixed rules over growth, profitability, cash, balance sheet and per-share "
     "figures choose the points and their side; one model call words them using placeholders only, and "
     "a sentence with a typed number, advice, a forecast or a direction that contradicts its rule falls "
     "back to a code-built sentence. Nineteen tests pass. The builder also caught a wiring fault in the "
     "pipeline, which the lead had fixed in the same round."),
    ("backend", "Build a peer benchmark from each peer's own SEC filings and a dated list of the company's key "
     "disclosures.",
     "Done. Each peer is loaded at the same time into its own ledger, exactly as the main company is; "
     "reported cells link to the peer's filing and computed cells state their calculation; medians "
     "need at least three values. Recent filings are listed with a form tag and, for current reports, "
     "the titles of their items. Fifty-one tests pass."),
    ("backend", "Add bear, base and bull valuation cases, a market reference and live inputs for the discount "
     "rate.",
     "Done. The three cases follow the original method's growth and margin rules and give a low, base "
     "and high enterprise value each; the market reference is market capitalisation plus net debt, "
     "drawn as a line with no difference or percentage computed. Interest, tax and pre-tax income are "
     "now selected from filings so the discount rate is a weighted cost of capital when the filing has "
     "them. One hundred and twenty-two tests pass."),
    ("backend", "Bring the report page to about four fifths of the original's layout: thesis, bull and bear "
     "columns, price sidebar, valuation range chart, peer table, risk dashboard, key disclosures.",
     "Done. Eight blocks were added in the original's style, each shown only when its data is present. "
     "The builder rendered a full sample, looked at desktop and phone screenshots and fixed five visual "
     "faults. Twenty-six page tests pass, including a sideways-overflow check in a real browser. "
     "Differences that remain are listed: no segment mix, no shareholder columns, no target price."),
    ("lead", "Integrate the round, run real reports and fix what the live run shows.",
     "Integrated five builders' work and ran a real report end to end in about ten seconds. The live "
     "run exposed four faults, all fixed with tests: a quarterly report's trailing twelve months was "
     "being read as a fiscal year for some companies; the bull and bear wording was discarded when the "
     "model's reply was cut off before its closing brace; two share classes of one company appeared as "
     "two peers; and a saved stale copy of the settings file had emptied the filings contact line. The "
     "self-check removed one sentence in the live report for stating a cause the figures do not show, "
     "and the report lists it. Each model role now carries its own agent name in the traces. Five "
     "hundred and forty-one tests pass."),
    ("builder", "Give the question page something inviting now that its research switch is gone.",
     "Done. Three quiet starter questions now sit under the question box. They stay hidden while the moon "
     "fades in, then appear one after another; choosing one puts it in the box without sending, and they "
     "step aside as soon as the box has text. On narrow screens they stack, and on very short windows they "
     "hide rather than overlap anything. Each behaviour was checked in a browser. 230 of 230 tests pass."),
    ("lead", "Remove the research mode from the question page together with everything connected to it, "
     "and make the question box say who you are asking.",
     "Done. The research switch, its shortcut, its side panel, its settings menu and its typed commands are "
     "gone, and the page title and box wording no longer mention it; the box now simply invites a question "
     "by the product's name. An independent reviewer then clicked through the whole page and found that a "
     "settings menu, two typed commands and a link parameter could still switch the mode on; all of those "
     "were closed, and a guard now ensures no request can ask for the research mode at all. Nine browser "
     "checks pass after the fixes, and 230 of 230 tests pass. The swipe on the opening screen still carries "
     "the old wording, left for the owner to decide."),
    ("lead", "Give the moon on the question page the same arrival as the one on the prototype moon pages, "
     "one for one.",
     "Done. The moon now assembles itself out of scrambled characters from the centre outwards, with the "
     "prototype's own numbers: the same settling times, the same flicker rate and density of the scramble, "
     "the same dimming, and the same short white flash as each character settles, over two seconds. It "
     "still waits for the opening screen to go first. Captured in a browser at six points of the arrival "
     "with no errors. 230 of 230 tests pass."),
    ("backend", "Give each peer its own valuation multiples so that peer-relative valuation methods can be priced.",
     "Done. Each peer row now carries its last close, share count, market capitalisation, net debt and four "
     "multiples, each with its basis in words; a share count older than four hundred days is not multiplied by "
     "today's price. Later fixes from the review: short-term investments count against net debt, a peer with "
     "no revenue stays out of the medians, slow peers are named, and names are shown in ordinary case. "
     "Thirty-six tests pass."),
    ("backend", "Build the original's multi-method valuation: six per-share methods, an AI advisor that weighs "
     "them, a blended model value and a quality score.",
     "Done. Discounted cash flow, three peer-relative methods on earnings, operating income and sales, "
     "price to book against peers, and the Graham number are each priced in Python with a range. One model "
     "call proposes relevance weights and a short rationale; code validates the weights, applies data-quality "
     "factors, floors, a cohort-comparability taper and an outlier cap, and blends. For a bank or insurer the "
     "cash-flow and enterprise-value methods are not used. One hundred and eighty-nine tests pass."),
    ("backend", "Research outside the filed figures: recent news from the web and the company's own words in "
     "its latest results release.",
     "Done. News articles are fetched, kept only when they are about the company, and headlines that tip or "
     "advise are dropped; a model groups the rest into topics with no figures of its own. The latest results "
     "release is found among the company's current reports and up to five management statements are shown "
     "as exact quotes located in the release text by code. Text from outside is fenced as data in every "
     "prompt. One hundred and nine tests pass."),
    ("backend", "Page round three: sections collapsed by default, the valuation panel with methods, recent "
     "news and management commentary.",
     "Done. Sources, calculations, withheld sentences and the scenario grid start collapsed without any "
     "script, and a figure's link still opens its calculation row. The valuation panel draws one band per "
     "method, the blended value and the last close, with the methods table and the advisor's rationale. "
     "Thirty-two page tests pass, two of them in a real browser."),
    ("reviewer", "Check five real reports of banks, an insurer, a conglomerate and a payments company figure by "
     "figure against the raw filings data.",
     "Nineteen findings. Every reported figure recomputed for the five companies matched the filings except "
     "two: a dividend per share shown at the quarterly rate, and a peer's revenue taken from a partial tag. "
     "Also found: an unfinished sentence on a page, placeholder syntax in the withheld list, measures that "
     "do not describe a bank, and data present under tags the selection did not know."),
    ("reviewer", "Check five real reports of small and consumer companies against the raw filings data.",
     "Twenty-four findings and no wrong figure: every reported figure and about thirty ratios matched. "
     "Found: a stale debt figure presented as current, an older year lost when a company changed tags, a "
     "retailer's fiscal year named by the wrong convention, sections left thin after the self-check, a "
     "quote cut mid-sentence, and tables too wide on a phone."),
    ("reviewer", "Check five real reports of large technology, pharmaceutical, energy and automotive companies "
     "against the raw filings data, and redo the valuation arithmetic by hand.",
     "Fourteen findings; every reported figure matched and the valuation arithmetic was confirmed by hand. "
     "Found: an empty report for a company whose ticker now points at a new holding registrant, capital "
     "expenditure missed under another tag, net debt that ignored short-term investments, one ratio with two "
     "definitions across companies, and year-end balances that cited a later quarterly report."),
    ("backend", "Fix the review's findings in the bull and bear rules.",
     "Done. For a bank or insurer the cash-flow, debt and gross-margin rules do not fire. Cash conversion "
     "makes a point only in a sensible band, a margin must move at least half a point, growth from a negative "
     "base makes no point, and the thesis line on growth now takes a three-year view instead of repeating the "
     "first bull point. Twenty-seven tests pass."),
    ("lead", "Triage fifty-seven review findings, dispatch the fixes by file, and wire the new parts together.",
     "Each finding was assigned to the builder who owns the file, with the reviewer's evidence attached. In "
     "the pipeline: valuation methods are priced once the peers are in and the advisor runs as a branch; news "
     "and the results release run as branches and news articles are registered as web sources; a bank or "
     "insurer is recognised by its industry code; a registrant created by a reorganisation inherits its "
     "predecessor's history; a section the checks emptied is rebuilt in code; and a report with no annual "
     "figures now fails with a plain message instead of completing empty."),
    ("lead", "Add a loading line down the left side of the opening screen that travels with the percentage "
     "counter, smooth and striking.",
     "Done. A hairline now runs down the left edge of the opening screen. Its bright fill grows with the "
     "same number the counter reads, led by a small glowing tip with a soft trail, and it lands just above "
     "the digits as they reach one hundred; the swipe then takes it away with the rest of the screen. It "
     "moves by transforms only, updated every frame. Measured in a browser on desktop and phone: it only "
     "ever grows, the tip stays on the end of the fill, it ends full, and there are no errors."),
    ("backend", "Fix the review's findings in how figures are chosen from the filings data.",
     "Done, fourteen defects, each with a test and a check on the real company. A dividend tagged at the "
     "quarterly rate is no longer shown as the annual figure; revenue, net income, capital expenditure and "
     "debt are read from the tags companies actually use; an older year is kept when a company changed "
     "tags and the two agree; one definition of long-term debt per company; a share count at the year end; "
     "a year-end balance cites its annual report; a fiscal year carries the company's own name; gross "
     "profit is derived as a shown calculation when it is not tagged. Seventy-three tests pass."),
    ("backend", "Fix the review's findings in the written sections, the reviewers and the audit.",
     "Done, eleven items. A section has room to finish and an unfinished last sentence is dropped; the "
     "writer sees only the latest year and the year before, so no stale figure is presented as current; "
     "figures that read the same are called little changed; a growth rate is stated, never said to rise or "
     "fall; a code reviewer rejects sentences about the data rather than the company; removed sentences "
     "are shown readably with one reason; and each section has a code-built version for when the checks "
     "leave too little. One hundred and twenty-six tests pass."),
    ("backend", "Fix the review's findings in the risk themes.",
     "Done. A quote is always whole sentences of the filing and states the risk itself; no two themes "
     "share a quote. The cause of a single theme for one company was the passage splitter reading a "
     "repeated page header as a new section; it now reads through page furniture, and nine real filings "
     "give between thirteen and forty-nine passages. Thirty-two tests pass."),
    ("backend", "Fix the review's findings on the report page.",
     "Done, fifteen items. A negative cash flow is drawn below the line in red; one share count is shown "
     "everywhere; a bank or insurer gets its own layout without rows that do not apply; tables fit a phone; "
     "the provider's company description is shown only where it carries no unchecked figure; sources and "
     "calculations list what the page cites. Forty-one page tests pass, three in a real browser."),
    ("builder", "On the report viewer page, remove the assistant and calculator tabs and make the page around "
     "the report match the report.",
     "Done. The two tabs and about two thousand lines behind them are gone; an old link to either opens "
     "the sources. The page is now a light reading desk: white bars, a navy ticker chip echoing the "
     "report's, light source cards. Two hundred and twenty interface tests, lint and type checks pass."),
    ("lead", "Integrate the fixes, run real reports and confirm the result.",
     "Integrated every fixer's work; eight hundred and forty-four backend tests and two hundred and twenty "
     "interface tests pass. Twelve real reports were generated on the final code, three at a time, each in "
     "about thirty seconds: all completed, none shows placeholder syntax, the company that had produced an "
     "empty report now has its full history, the bank is valued on earnings and book value, and the "
     "dividend that was wrong is no longer shown. The viewer's sources panel lists web and filing sources. "
     "Decisions recorded: a bank's partial cash line is not shown as its cash; the blended figure is "
     "called model value and no rating is given."),
    ("builder", "Bring the team's question-answering service into the project and make it run here under the "
     "project's rules.",
     "Done. The service was copied in unchanged and then adapted in three small places: every model call "
     "now goes through the project's single model function, with one named agent per role, it reads its "
     "settings from the project's one settings file, and it needs nothing new installed. Its own 664 tests "
     "pass, the project's 844 tests still pass, and a real question was answered in about five seconds "
     "with every figure checked. Tests are prevented from making paid model calls."),
    ("builder", "Connect that service to the question page so a typed question gets a real answer in the "
     "page's own interface, with its progress display and its price chart, for United States stocks.",
     "Done, with one open item. The page now shows its own thinking display while the service works, "
     "driven by the service's real stages, then the list of look-ups, a price chart with working time "
     "ranges fed from market data, the answer text, sources and suggested follow-up questions. A follow-up "
     "question keeps the conversation's company, and a conversation can be reopened from the history list. "
     "Nine new tests cover it. Open: the price card still prints the wrong currency sign; the fix is "
     "written but was not applied."),
    ("lead", "Build the backend for the question page from the team's service and the existing interface, "
     "keep everything in sync, and show the thinking steps and the price chart.",
     "Done except for the currency sign on the price card. I split the work between two builders on "
     "separate files, then asked a fresh question in a browser myself: the thinking display moved through "
     "checking the price, reviewing and writing, and the answer arrived in about four seconds with the "
     "look-ups, the chart, checked figures in dollars, sources and follow-ups, with no errors or failed "
     "requests. All three test suites pass: 673, 844 and 225. Prices are end of day, not live, and say so."),
    ("lead", "Change the loading line on the opening screen to a solid side bar like the reference loader, "
     "and line up the small wordmark under an answer, which sat too far to the right.",
     "Done. The opening screen now has a solid bar on its left edge, the full height of the screen, that "
     "fills from the bottom up with the counter; the counter moved slightly right to clear it. Measured in "
     "a browser on desktop and phone: it only grows, it grows from the bottom, and it ends full. The "
     "wordmark under an answer was sitting centred in a box wider than the word; the box now fits the word, "
     "so it starts on the answer's left edge, in line with the row of icons above it. 225 of 225 tests pass."),
    ("builder", "Calm the report-ready screen: no sweeping highlight, almost no entrance animation.",
     "Done. The white band that swept across the preview is gone; it had also made the content area more "
     "than twice the window's width, which showed as a stray scrollbar. The ready state now fades in once "
     "in a fifth of a second; nothing slides, bounces or arrives late, and with reduced motion there is no "
     "entrance at all. Checked frame by frame at two widths."),
    ("reviewer", "Use the app end to end in a real browser and report every defect on the report flow.",
     "Sixteen findings. The worst: pressing Enter on nonsense text right after browsing the list could "
     "start a report for the company highlighted earlier. Also: a valid ticker outside the built-in list "
     "was refused, a failed job kept a spinner, the viewer showed counts for a report it could not open, "
     "peers for one company were its investor's holdings, and peer cells carried source numbers that "
     "pointed at other filings. A long list of flows was confirmed working."),
    ("reviewer", "Call the backend with awkward inputs and unusual companies and read the log for faults.",
     "Sixteen findings and one crash: a very long file name returned a server error. Also: deleting a "
     "running job did not stop it, a company reporting in euros was labelled in dollars, a property "
     "company was read as a bank, and a quality score was shown with nothing priced. Input checking, the "
     "queue, the chat's refusals and six figures checked against the saved data were all correct."),
    ("builder", "Fix the interface defects from the browser review.",
     "Done, thirteen items. The search decides from the text in the box at the moment of submitting; any "
     "ticker-shaped text starts a report for that ticker; a failed job shows a failed step; the viewer has "
     "an honest empty state; one share link on both screens; the report is requested once; zoom stops at "
     "its limits. Two hundred and forty interface tests, lint and type checks pass."),
    ("lead", "Fix the backend defects from both reviews, verify live and close the round.",
     "Fixed with tests: the long-name crash, deleted jobs now stop at their next step, labels follow the "
     "company's reporting currency and annual form, the bank rule no longer catches property companies, "
     "no quality score with nothing priced, ratios from a tiny base show as not meaningful, peers must be "
     "in the same industry, and peer cells carry no foreign source numbers. Eight hundred and fifty-seven "
     "backend tests pass. Verified on live reports for nine companies and in a real browser. During the "
     "round the saved reports were deleted through the app's delete route by a client other than the "
     "lead's scripts; six were regenerated."),
]


def main() -> int:
    # "--last N" sends only the newest N steps (earlier ones stay as conversation history).
    last = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--last" else len(STEPS)
    first_new = max(0, len(STEPS) - last)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    history = {role: [] for role in AGENTS}          # each agent sees only its own earlier steps
    sent = []
    for index, (role, request, result) in enumerate(STEPS):
        agent_id, model = AGENTS[role]
        messages = history[role]
        messages.append({"role": "user", "content": request})
        if index >= first_new:
            payload = redact(messages, result, model=model, session_id=f"build-{role}-{stamp}",
                             agent_id=agent_id, project_id=config.secret("PRISMTRACE_PROJECT_ID"))
            prism.send_trace(payload)
            prism.flush()
            sent.append((agent_id, prism.last_sent["status"] if prism.last_sent else "nothing sent"))
        messages.append({"role": "assistant", "content": result})
    print("PRISM sessions: build-<role>-" + stamp)
    for agent_id, model in AGENTS.values():
        statuses = [status for agent, status in sent if agent == agent_id]
        if statuses:
            print(f"Agent: {agent_id} | model label: {model} | PRISM response per trace: {statuses}")
    ok = bool(sent) and all(status == 200 for _, status in sent)
    print("BUILD LOG", "SENT: all traces stored by PRISM." if ok else "NOT FULLY SENT: see statuses above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
