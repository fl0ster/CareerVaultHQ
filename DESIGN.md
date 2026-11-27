---
name: Pica
description: Your job search organised. Fully Yours.
colors:
  sun: "#f6b829"
  sun-hover: "#eea915"
  on-sun: "#2b2006"
  sun-bg: "#fdf0c9"
  sun-fg: "#865a00"
  accent: "#3a4fc8"
  accent-hover: "#2d3fa6"
  accent-bg: "#e6e9fc"
  accent-border: "rgba(58, 79, 200, 0.4)"
  accent-fill: "#3a4fc8"
  on-accent-fill: "#ffffff"
  canvas: "#f4f0f8"
  surface: "#fdfcff"
  surface-2: "#f8f5fc"
  sidebar: "#e9e3f4"
  border: "#e5dfef"
  border-strong: "#d0c8e2"
  text: "#5d5677"
  text-h: "#1d1838"
  hover-tint: "rgba(29, 24, 56, 0.055)"
  backdrop: "rgba(29, 24, 56, 0.38)"
  info-bg: "#e4e8fb"
  info-fg: "#3e4f9c"
  info-solid: "#8597e6"
  warn-bg: "#fde9d3"
  warn-fg: "#8f5216"
  warn-solid: "#ee9f4c"
  warn-border: "rgba(238, 159, 76, 0.5)"
  success-bg: "#dcf1e6"
  success-fg: "#22694a"
  success-solid: "#5cbf90"
  success-strong: "#2c8d61"
  danger-bg: "#fbe1e6"
  danger-fg: "#a2324a"
  danger-solid: "#ec8598"
  neutral-bg: "#eee9f3"
  neutral-fg: "#676183"
  neutral-solid: "#b8b1ca"
  lavender-bg: "#ece4fb"
  lavender-fg: "#5a45a0"
  peach-bg: "#fde4d5"
  peach-fg: "#984e2b"
  on-strong: "#ffffff"
  tip-bg: "#110f26"
  tip-fg: "#cfc8ea"
  tip-action: "#f8c64a"
  mag-ink: "#1f2142"
  mag-ink-2: "#2d305e"
  mag-white: "#fffdfa"
  mag-sheen: "#3557d6"
  mag-sheen-2: "#7d5ce8"
  mag-cheek: "#f7aaa0"
  stage: "#e6e9fc"
  stage-warn: "#fdf0c9"
  stage-danger: "#fbe1e6"
  sunset-canvas: "#191731"
  sunset-surface: "#221f41"
  sunset-surface-2: "#2a2750"
  sunset-sidebar: "#16112a"
  sunset-border: "#332f5b"
  sunset-border-strong: "#4a4579"
  sunset-text: "#b9b2da"
  sunset-text-h: "#f5f1ff"
  sunset-accent: "#97aaff"
  sunset-accent-fill: "#4669ec"
  sunset-sun: "#f8c64a"
  sunset-sun-hover: "#ffd56e"
  sunset-stage: "#b4c1ff"
typography:
  display:
    fontFamily: "Bricolage Grotesque Variable, Plus Jakarta Sans Variable, system-ui, sans-serif"
    fontSize: "46px"
    fontWeight: 760
    lineHeight: 1
    letterSpacing: "-0.04em"
    fontFeature: "'tnum'"
  headline:
    fontFamily: "Bricolage Grotesque Variable, Plus Jakarta Sans Variable, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 760
    lineHeight: 1.04
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Bricolage Grotesque Variable, Plus Jakarta Sans Variable, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 760
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  wordmark:
    fontFamily: "Bricolage Grotesque Variable, Plus Jakarta Sans Variable, system-ui, sans-serif"
    fontSize: "23px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.04em"
  subtitle:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 680
    lineHeight: 1.35
  body:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  control:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 650
    lineHeight: 1.3
  label:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "13.5px"
    fontWeight: 600
  counter:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 750
    lineHeight: 1
    fontFeature: "'tnum'"
  mono:
    fontFamily: "ui-monospace, SF Mono, Consolas, monospace"
    fontSize: "13px"
    lineHeight: 1.35
rounded:
  sm: "10px"
  md: "16px"
  lg: "24px"
  pill: "999px"
spacing:
  hairline-gap: "3px"
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "18px"
  xl: "26px"
  content-y: "36px"
  content-x: "40px"
components:
  button-primary:
    backgroundColor: "{colors.sun}"
    textColor: "{colors.on-sun}"
    typography: "{typography.control}"
    rounded: "{rounded.pill}"
    padding: "7px 14px"
  button-primary-hover:
    backgroundColor: "{colors.sun-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.neutral-bg}"
    textColor: "{colors.neutral-fg}"
  button-default:
    backgroundColor: "{colors.accent-bg}"
    textColor: "{colors.accent}"
    typography: "{typography.control}"
    rounded: "{rounded.pill}"
    padding: "7px 14px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.text-h}"
    typography: "{typography.control}"
    rounded: "{rounded.pill}"
    padding: "7px 14px"
  button-secondary-hover:
    backgroundColor: "{colors.hover-tint}"
  button-small:
    rounded: "{rounded.pill}"
    padding: "4px 11px"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    size: "36px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-h}"
    rounded: "{rounded.sm}"
    padding: "7px 11px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
  dialog:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.text-h}"
    rounded: "{rounded.pill}"
    height: "40px"
    padding: "0 14px"
  nav-item-active:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.accent}"
  nav-pill:
    backgroundColor: "{colors.accent-bg}"
    textColor: "{colors.accent}"
    typography: "{typography.counter}"
    rounded: "{rounded.pill}"
    height: "22px"
    padding: "0 8px"
  nav-pill-finds:
    backgroundColor: "{colors.sun}"
    textColor: "{colors.on-sun}"
    typography: "{typography.counter}"
    rounded: "{rounded.pill}"
    height: "22px"
    padding: "0 8px 0 3px"
  segmented-tab-active:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.on-accent-fill}"
    rounded: "{rounded.pill}"
    padding: "6px 16px"
  stat-tile:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-h}"
    typography: "{typography.display}"
    padding: "18px 20px 16px"
  stat-tile-sun:
    backgroundColor: "{colors.sun}"
    textColor: "{colors.on-sun}"
  profile-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "14px 12px"
  profile-avatar:
    backgroundColor: "{colors.accent-bg}"
    textColor: "{colors.accent}"
    rounded: "{rounded.pill}"
    size: "52px"
  brand-sun:
    backgroundColor: "{colors.sun}"
    rounded: "{rounded.pill}"
    size: "32px"
  floating-panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    width: "380px"
---

# Design System: Pica

## Overview

**Creative North Star: "The Magpie at Golden Hour"**

Pica is a flat, saturated field of colour, lit like the sky at either end of the day. Sunrise (light) is a pale dawn lilac with indigo ink. Sunset (dark) is an ink-violet ground with plum surfaces and lavender text. Two lights cross that field. Sun yellow marks what to press and what is new. Iridescent feather blue, taken from the magpie's wing, marks where you are.

It is an operate-mode app shell, dense and calm. The world is carried by type, palette, density and one signature move, not by decoration. Headings and big numbers are set in heavy Bricolage Grotesque, so the page reads as confident and a little playful. Every control is a pill and every container is a generously curved rectangle. Depth comes only from tone steps: canvas, sidebar, surface and surface-2 sit at different lightnesses and do the work a shadow would do elsewhere. Hairlines appear only where tone alone cannot separate two things.

The magpie is the brand. It appears as a head against a sun disc in the brand mark, it peeks out of the sun-yellow new-jobs counter and the sun stat tile wherever something shiny has arrived, and it sits on a pale feather stage as the worker-status character and in empty states. There are no forest, landscape or scenery motifs. The golden-hour idea lives entirely in the palette.

**Key Characteristics:**
- Flat by rule: every shadow token is `none`; depth is tone.
- Two lights: sun yellow for action and novelty, feather blue for location and focus.
- Heavy grotesque display type over a friendly humanist sans UI.
- Pills for actions, curved rectangles (10 / 16 / 24px) for containers.
- The magpie head beside anything new.
- Two themes, Sunrise and Sunset, with the same roles and different lightness.

## Colors

Three roles and no more. Feather blue marks selection and where you are; the dark ink violet carries the grounds; sun yellow highlights what to press and what is new. Everything else is a soft tinted status pair or a data tone, never chrome.

### Primary
- **Marigold Sun** (`sun`; Sunset `sunset-sun`): the one thing to press and the one thing that is new. Form submit buttons and `.primary` pills, the add-job button, the new-jobs counter in the sidebar, the "Jobs to review" stat tile when there is something to review, the brand disc behind the magpie, the setup progress bar fill, and text selection. Text on it is always **Sun Ink** (`on-sun`), never white. Hover deepens to `sun-hover` in Sunrise and brightens in Sunset.
- **Pale Sun** (`sun-bg`) with **Amber Ink** (`sun-fg`): the tinted, non-pressable form of sun, for soft highlights that are not actions.

### Secondary
- **Feather Cobalt** (`accent`; Sunset `sunset-accent`, a light periwinkle): where you are and where you can go. Links, focus rings and outlines, caret and checkbox accent, the active settings tab text and its underline, the current-page outline of the profile card, and the text of default (non-primary) buttons.
- **Feather Fill** (`accent-fill` with `on-accent-fill`; Sunset `sunset-accent-fill`): solid fills for "you are here" inside the page: the active segmented-control tab and the worker job count. (The side menu marks the current page with the bookmark instead, in `canvas`.) In Sunset the fill (#4669ec) is darker than the text accent so white text on it stays legible.
- **Feather Mist** (`accent-bg`, `accent-border`): the resting tint of default buttons and plain counters, the profile avatar disc (with `accent` initials), and the hover border of controls.
- **Feather Stage** (`stage`; Sunset `sunset-stage`, a brighter periwinkle): the pale feather disc the mascot stands on, for the worker character and empty states. It shifts to `stage-warn` (pale sun) when the worker is queued and `stage-danger` when it errors.

### Neutral
- **Dawn Lilac** (`canvas`): the page ground and the top bar.
- **Lilac Haze** (`sidebar`): the side menu, one tone step from the canvas. In Sunset it is the darkest layer (`sunset-sidebar`).
- **Dawn Paper** (`surface`) and **Lilac Paper** (`surface-2`): cards, lists, dialogs, inputs, panels and their hover step.
- **Lilac Hairline** (`border`) and **Violet Hairline** (`border-strong`): dividers and card edges; the strong one is for inputs, secondary buttons and floating panels.
- **Dusk Indigo** (`text`) for body copy and **Night Indigo** (`text-h`) for headings, values and control labels.
- **Hover Tint** (`hover-tint`): a translucent ink wash for hover on transparent controls and for trays.
- **Backdrop** (`backdrop`): dialog and drawer scrim.
- **Ink Tooltip** (`tip-bg`, `tip-fg`, `tip-action`): popups that stay a dark ink panel in both themes, with a sun-coloured action.

### Status
Each status is a pair (tinted `-bg` with readable `-fg`) plus a `-solid` for dots, bars and chart nodes: info (periwinkle), warn (apricot, with `warn-border`), success (sage green, with `success-strong` for solid confirm buttons), danger (rose), neutral (lilac grey) and lavender, plus a peach pair (`peach-bg`, `peach-fg`) that is a data tone only: the certificates category in work history (`.tone-peach`), never chrome. Use the pairs for badges and pills, the solids for marks.

### Mascot
The magpie is drawn only from `mag-ink`, `mag-ink-2`, `mag-white`, `mag-sheen`, `mag-sheen-2` (the cobalt-to-violet iridescence) and `mag-cheek`. It is flat-coloured; do not recolour it per surface.

### Named Rules
**The Two Lights Rule.** Sun yellow means "press this" or "this is new"; feather blue means "you are here". A colour never borrows the other's job: a current page is never yellow, a primary action is never blue.

**The One Sun Rule.** Each page header or toolbar carries at most one sun pill. Everything else is a feather-mist default pill or a transparent secondary pill.

**The Sun Ink Rule.** Text and icons on sun are `on-sun` dark ink, in both themes.

## Typography

**Display Font:** Bricolage Grotesque Variable (optical sizing on, with Plus Jakarta Sans Variable and system-ui fallback)
**Body Font:** Plus Jakarta Sans Variable (with system-ui, Segoe UI, Roboto fallback)
**Label/Mono Font:** ui-monospace, SF Mono, Consolas for code

**Character:** A heavy, slightly quirky grotesque with tight tracking for headings and numbers, over a round, friendly humanist sans for everything you read and click.

### Hierarchy
- **Display** (760, 46px, 1.0, -0.04em, tabular figures): the big numbers on stat tiles.
- **Headline** (760, 40px, 1.04, -0.035em; 30px below 900px): page `h1`, balanced wrap.
- **Title** (760, 21px, 1.2, -0.02em): section `h2`.
- **Wordmark** (800, 23px, -0.04em): the "Pica" wordmark beside the brand mark. The profile name uses the same face at 19px/760, with the surname at 450.
- **Subtitle** (Jakarta 680, 15px, 1.35): `h3` and row titles.
- **Body** (400, 15px, 1.5): default text; intro paragraphs cap at 64 to 76ch.
- **Control** (650, 14px, 1.3): buttons, inputs, nav items (nav at 550, active at 700).
- **Label** (600, 13.5px): stat labels, segmented tabs, small meta.
- **Counter** (750, 12px, tabular): nav counters.

### Named Rules
**The Heavy Ink Rule.** Bricolage Grotesque is for headings, display numbers, the wordmark and the profile name only. UI text, labels and controls stay in Plus Jakarta Sans.

**The Lined-Up Numbers Rule.** Tables, times, counters and stat values use tabular figures.

## Layout

A two-column app shell: a sticky 260px side menu (collapsible to a 76px icon rail) and a content column. The content column has a sticky 68px top bar on the canvas, with breadcrumbs on the left and the worker magpie on the right, separated from the page by one hairline. Page content is centred at a max width of 1120px with 36px top, 40px side and 80px bottom padding. Page headers sit 26px above the work area.

The dashboard opens with a stat band: tiles of at least 150px in an auto-fit grid, separated by 3px seams where the canvas shows through, the whole band clipped to the large radius.

Spacing is compact and rhythm-based (2, 4, 8, 14, 18, 26px), suited to an operate-mode tool rather than a marketing page.

Below 900px the side menu becomes an off-canvas drawer (max 288px or 86vw) over a backdrop scrim, the top bar gains a menu button, content padding drops to 22px 16px 56px, and `h1` drops to 30px. Below 600px buttons go full width.

## Elevation & Depth

The system is flat. `--shadow-sm`, `--shadow-md`, `--shadow-lg` and `--shadow` are all `none`, and no surface casts a shadow. Depth comes from tone steps: the sidebar, canvas, surface and surface-2 each sit at a distinct lightness, so a card reads as "on top" because it is lighter (Sunrise) or lighter-plum (Sunset) than what is behind it. Floating panels (the worker dropdown, popovers) get a `border-strong` hairline and the large radius instead of a shadow. Dialogs use a `border` hairline over a tinted `backdrop`.

`box-shadow` is used only for rings, never for elevation: the focus ring (`0 0 0 3px` feather at 30 to 40% alpha), the avatar ring on the current page, and inset hairlines.

### Named Rules
**The Flat-By-Rule Rule.** No drop shadows, ever. If two layers need separating, step the tone first; add a hairline only when tone alone cannot do it.

**The Ring-Not-Lift Rule.** `box-shadow` may draw a ring (focus, current state) but never an offset or blurred lift.

## Shapes

Two shape families. Actions are pills: buttons, nav items (the bookmark keeps its left pill end), counters, segmented controls, the theme switch and progress bars all use a full radius (999px). Containers are curved rectangles on three steps: small (10px) for inputs, selects and small inner boxes; medium (16px) for cards and lists; large (24px) for dialogs, floating panels, the profile card, dashboard widgets and the stat band. Avatars, the brand disc and the mascot stages are circles. Stat tiles inside the band have a small 6px corner so the seams read as cuts in one shape.

## Components

### Buttons
Rounded, confident, and colour-coded by job.
- **Shape:** full pill (999px), 7px 14px padding, 14px/650 text; small variant 4px 11px at 13px.
- **Primary (sun pill):** sun background, sun-ink text, sun border. Applied by default to submit buttons that are not `.secondary`, and opted in with `.primary`. Hover goes to `sun-hover`. Disabled turns to a quiet neutral pill (`neutral-bg`, `neutral-fg`) instead of a faded yellow.
- **Default:** feather mist background with feather text; hover adds the `accent-border`.
- **Secondary:** transparent with a `border-strong` hairline and heading-ink text; hover adds `hover-tint`.
- **Icon button:** 36px transparent circle in body ink; hover adds `hover-tint`.
- **Hover / Focus:** 140ms colour transitions, a 0.97 press scale, and the feather focus ring.

### Chips
- **Style:** badges are 999px pills, 12.5px/600, on `neutral-bg`; status badges use the matching `-bg`/`-fg` pair.
- **Counters:** plain nav counts (Interviews, Offers) are 22px pills on feather mist with feather text. A counter that asks for the user (new jobs to review, an overdue Employment journal) is the sun pill with the magpie head peeking out; there are no bell or warning-coloured counters.

### Cards / Containers
- **Corner Style:** medium (16px) for cards and lists, large (24px) for widgets, the profile card and panels.
- **Background:** `surface`; a card that opens takes the `hover-tint` wash on hover (see Clickable Cards and List Rows).
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** a 1px `border` hairline; list rows are divided by hairlines inside one card.
- **Internal Padding:** about 18 to 22px.

### Clickable Cards and List Rows
- **The chevron says it opens:** a list row with a right chevron at its far right, or a card with a chevron in its top right corner, opens when clicked anywhere on it. There are no "Details" or "Open" buttons on cards; the chevron replaces them. Items that don't open have no chevron.
- **Rows:** the chevron (18px, body ink) sits at the far right, centred vertically. Rows keep 44px of right padding for it.
- **Cards:** the chevron is the card's 36px icon button (transparent circle, body ink), the last thing in the header, after any status control.
- **Hover:** the item takes a `hover-tint` wash over its own background, so an inbox match or the active role still shows through. Career rows use their position's colour for the wash. The title turns feather and the chevron turns feather and moves 2px right. Cards also firm their border to `border-strong` (an overdue Employment card stays sun), and their chevron button takes feather mist.
- **Regions that do their own thing:** inline controls (buttons, links, the status picker, company pills) never open the item. Areas with their own work, like a note being written, the journal composer or an offer's decision bar, don't open it and don't show the hover. Keyboard users open the item with its title link or chevron button. In code, this is `shell/clickable.css`, `shell/OpenChevron.tsx` and `shell/openOnClick.ts`.

### Inputs / Fields
- **Style:** `surface` fill, 1px `border-strong`, 10px radius, 7px 11px padding, 14px heading-ink text. Selects draw their chevron from two gradient triangles in the text colour.
- **Focus:** border turns feather and the feather focus ring appears; hover shows `accent-border`.
- **Error / Disabled:** errors in `danger-fg`; disabled at half opacity.

### Navigation
- **Side menu:** on `sidebar`. The brand mark and wordmark sit at the top, then the profile card, then 40px pill nav items (14px/550, heading ink, 13px gap to an icon). Entries are grouped into labelled sections, **Work Nest** (Employment, My Career) and **Job Search** (Jobs, Applications, Interviews, Offers). Each label is 13px/720 Bricolage in `text`, followed on the same line by a `border-strong` hairline; on the icon rail only the hairline shows. The current page is a **bookmark**: the entry takes the page's own `canvas` colour, stays pill-rounded on the left, runs flush to the menu's right edge into the page with a square top-right edge, and joins it with a single 16px concave corner below. Its label and icon turn feather (`accent`) and bold. The bookmark doesn't slide or animate between entries; it simply sits on the current page, Settings at the bottom included. Hover previews the same tab shape (flush right, square top-right, concave corner below) in `hover-tint`, with the label staying heading ink; the entry right above the bookmark leaves the join to it. Nav entries have no transitions, so the shape and fill switch instantly. In the mobile drawer there is no page beside the menu, so entries are pills again and the bookmark becomes an `accent-bg` pill. Sub-pages open under a group with a `border-strong` guide line. Settings is pinned to the bottom, with the three-way theme switch (a tinted pill tray whose active segment is `surface`) in the footer.
- **Rail:** labels fade out; counters shrink to 17px badges on the icon corner.
- **Top bar:** breadcrumbs in body ink with the page name in heading ink at 650.
- **Settings tabs:** underlined text tabs; the current tab is feather with a 3px feather underline that slides; hover previews a `border-strong` underline.
- **Segmented control:** a `surface` pill tray with a hairline; the active tab is a feather-fill pill.

### Profile Card
A 24px-radius `surface` card in the sidebar that links to the dashboard. It holds a 52px feather-mist avatar (initials in the display face) and the name in Bricolage. On the dashboard the card is the current page and becomes the same bookmark as a nav entry: `canvas` fill, flush right into the page with the same square top-right edge and concave corner below, and its left side keeps the 24px card radius so it still reads as its own block. The avatar gets a feather ring.

### Stat Band (signature)
One segmented band of headline numbers: tiles on `surface` with 46px display numerals and 13.5px labels, 3px canvas seams, 24px outer radius. The "Jobs to review" tile turns sun with sun-ink text when there are new jobs, and the magpie head (30px) watches from its top-right corner, peeking in with a spring and tilting on hover.

### The Magpie Signature
On a sun background, the magpie head means "something is here for you" and appears in these places only: the brand mark (the head against a 32px sun disc), the sun nav counters for new jobs and an overdue Employment journal (a sun pill with the head peeking out at its left edge, hidden on the rail), and the sun stat tile. The full-bodied magpie is the worker-status character on the pale feather `stage` disc, which turns pale sun when queued and rose when in error.

**Empty states** (`mascot/EmptyState.tsx`) are the magpie's other home, always on the pale feather `stage` disc, never on sun. The `page` variant puts the idling full-body magpie on an 84px disc beside the message, inside a `surface` block at the 24px radius; below 600px it stacks and centres. The `inline` variant puts the head on a 28px disc before a 14px line, for empty widgets, charts, dialog sections and the end of the jobs feed. Use them only for genuinely empty collections, never for a missing field (such as "No parsed description") or as decoration.

### Dialogs and Panels
Dialogs: `surface`, 24px radius, `border` hairline, `backdrop` scrim, opening with a 420ms scale-and-rise. Floating panels (worker dropdown): `surface`, 24px radius, `border-strong` hairline, 380px wide, opening from their anchor corner.

## Do's and Don'ts

### Do:
- **Do** use the sun pill (`sun` / `on-sun`) for the single primary action in a header or toolbar, and for new-item counters.
- **Do** use feather blue (`accent`) for links and focus, and `accent-fill` / `on-accent-fill` for solid current-page and active-tab fills.
- **Do** separate layers by tone step (canvas, sidebar, surface, surface-2) before reaching for a hairline.
- **Do** give floating panels a `border-strong` hairline and the 24px radius.
- **Do** set headings, display numbers and the wordmark in Bricolage Grotesque Variable at 760 to 800 with negative tracking; set all UI text in Plus Jakarta Sans.
- **Do** make actions pills and containers curved rectangles on the 10 / 16 / 24px steps.
- **Do** put the magpie head beside a counter only when it counts new finds.
- **Do** keep chrome to the three roles: feather for selection, ink violet for grounds, sun for highlight. The profile avatar is feather mist (`accent-bg` / `accent`) and the mascot stands on the feather `stage`.
- **Do** define every new colour as a token in `index.css`, in both Sunrise and Sunset.

### Don't:
- **Don't** add drop shadows or set the shadow tokens to anything but `none`.
- **Don't** use glossy or decorative gradients; flat colour only.
- **Don't** colour the current page or active tab yellow, or a primary action blue.
- **Don't** put white text on sun.
- **Don't** put more than one sun pill in a page header or toolbar.
- **Don't** use forest, tree, landscape or other scenery motifs.
- **Don't** set body text, labels or controls in Bricolage Grotesque.
- **Don't** recolour or restyle the magpie per surface.
- **Don't** use peach (`peach-bg` / `peach-fg`) outside the work-history certificate tone, or add a fourth chrome colour for warmth.
