---
name: Pica
description: Your job search organised. Fully Yours.
colors:
  canvas: "#eef3f4"
  surface: "#ffffff"
  surface-2: "#f5f8f9"
  sidebar: "#e4edef"
  border: "#dbe4e6"
  border-strong: "#c5d2d5"
  text: "#56636a"
  text-h: "#1f2c33"
  accent: "#3b7480"
  accent-hover: "#2f616b"
  accent-bg: "#d6eaec"
  accent-border: "rgba(59, 116, 128, 0.45)"
  on-accent: "#ffffff"
  on-strong: "#ffffff"
  info-bg: "#e0e6f8"
  info-fg: "#45558f"
  info-solid: "#8ea2e0"
  warn-bg: "#f7ecc9"
  warn-fg: "#85621a"
  warn-solid: "#e3bb52"
  success-bg: "#d8efe2"
  success-fg: "#2d6e4a"
  success-solid: "#6cc196"
  success-strong: "#3f9a6b"
  danger-bg: "#f7dfe0"
  danger-fg: "#9c3d45"
  danger-solid: "#e58e94"
  neutral-bg: "#e8edee"
  neutral-fg: "#66707a"
  neutral-solid: "#b3bcc0"
  lavender-bg: "#e8e2f6"
  lavender-fg: "#5c4f91"
  peach-bg: "#fae4d7"
  peach-fg: "#92553a"
  hover-tint: "rgba(31, 44, 51, 0.055)"
  backdrop: "rgba(31, 44, 51, 0.3)"
  mag-ink: "#2d3b48"
  mag-white: "#fbfdfd"
  mag-sheen: "#7cc3c2"
  mag-sheen-2: "#9fb2ea"
  mag-cheek: "#f3b6b5"
  stage: "#d6eaec"
  dusk-canvas: "#141b20"
  dusk-surface: "#1b242a"
  dusk-surface-2: "#202b32"
  dusk-sidebar: "#172026"
  dusk-border: "#2b3840"
  dusk-text: "#a2b0b7"
  dusk-text-h: "#e8eff1"
  dusk-accent: "#8cc6cf"
  dusk-on-accent: "#10262b"
typography:
  display:
    fontFamily: "Fraunces Variable, Georgia, Times New Roman, serif"
    fontSize: "32px"
    fontWeight: 520
    lineHeight: 1.15
    letterSpacing: "-0.01em"
    fontVariation: "'SOFT' 60, 'WONK' 0"
  headline:
    fontFamily: "Fraunces Variable, Georgia, Times New Roman, serif"
    fontSize: "21px"
    fontWeight: 520
    lineHeight: 1.25
    letterSpacing: "-0.01em"
    fontVariation: "'SOFT' 60, 'WONK' 0"
  stat:
    fontFamily: "Fraunces Variable, Georgia, Times New Roman, serif"
    fontSize: "28px"
    lineHeight: 1.1
    fontFeature: "'tnum'"
  title:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  control:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.3
  label:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    letterSpacing: "0.06em"
  eyebrow:
    fontFamily: "Plus Jakarta Sans Variable, system-ui, Segoe UI, Roboto, sans-serif"
    fontSize: "11px"
    fontWeight: 650
    letterSpacing: "0.14em"
  mono:
    fontFamily: "ui-monospace, SF Mono, Consolas, monospace"
    fontSize: "13px"
    lineHeight: 1.35
rounded:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "18px"
  pill: "999px"
spacing:
  2xs: "2px"
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  2xl: "22px"
  page-x: "36px"
components:
  button-primary:
    backgroundColor: "{colors.accent-bg}"
    textColor: "{colors.accent}"
    typography: "{typography.control}"
    rounded: "{rounded.pill}"
    padding: "7px 14px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-h}"
    typography: "{typography.control}"
    rounded: "{rounded.pill}"
    padding: "7px 14px"
  button-secondary-hover:
    backgroundColor: "{colors.surface-2}"
  button-small:
    padding: "4px 11px"
    rounded: "{rounded.pill}"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    size: "36px"
  icon-button-hover:
    backgroundColor: "{colors.hover-tint}"
    textColor: "{colors.text-h}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-h}"
    rounded: "{rounded.sm}"
    padding: "7px 11px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
  widget:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "16px 18px"
  stat-tile:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "14px 16px"
  dialog:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
  badge:
    backgroundColor: "{colors.neutral-bg}"
    textColor: "{colors.text-h}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  status-applied:
    backgroundColor: "{colors.info-bg}"
    textColor: "{colors.info-fg}"
    rounded: "{rounded.pill}"
  status-interview:
    backgroundColor: "{colors.warn-bg}"
    textColor: "{colors.warn-fg}"
    rounded: "{rounded.pill}"
  status-offer:
    backgroundColor: "{colors.success-bg}"
    textColor: "{colors.success-fg}"
    rounded: "{rounded.pill}"
  status-accepted:
    backgroundColor: "{colors.success-strong}"
    textColor: "{colors.on-strong}"
    rounded: "{rounded.pill}"
  status-rejected:
    backgroundColor: "{colors.danger-bg}"
    textColor: "{colors.danger-fg}"
    rounded: "{rounded.pill}"
  status-closed:
    backgroundColor: "{colors.neutral-bg}"
    textColor: "{colors.neutral-fg}"
    rounded: "{rounded.pill}"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.text-h}"
    rounded: "{rounded.pill}"
    height: "40px"
    padding: "0 14px"
  nav-item-active:
    textColor: "{colors.accent}"
  nav-pill:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.pill}"
    height: "20px"
  segmented-tab:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    padding: "6px 16px"
  segmented-tab-active:
    backgroundColor: "{colors.accent-bg}"
    textColor: "{colors.accent}"
  worker-toggle:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-h}"
    rounded: "{rounded.pill}"
    padding: "4px 6px 4px 14px"
---

# Design System: Pica

## Overview

**Creative North Star: "The Magpie's Nest"**

Pica is where one person keeps everything worth keeping from a career, and the design should feel like a cosy, well-kept nest that grew from that collecting. Everything rests on a cool mist canvas. White paper surfaces hold the work, and the few shiny things (the teal accent, a headline number, a status that just changed) are placed with care, not scattered. The magpie isn't decoration added on top. It is the system's personality, and the rest of the interface stays calm so the bird can carry the character.

The mood is **calm, soft and personal**. Contrast is gentle, colour comes in pastel pairs, corners are rounded all the way to pills, and motion settles with a small spring. Headings use a soft, slightly literary serif, which gives pages the feel of a personal record. Controls and data use a friendly geometric sans so working views stay legible and quick to scan. The page density suits a daily-use tool: lists sit on white cards and rows are divided by hairlines. Nothing is cramped and nothing is padded for show.

The visual anti-references are confirmed. It is not a generic admin template (Bootstrap or Material dashboards, grey grids, default blue). It is not a corporate HR or ATS tool (impersonal, form-heavy, stock illustration). It does not use hard, saturated colour. It is not a dark-first hacker aesthetic: Dusk, the dark theme, is a companion to Mist, not the identity.

**Key Characteristics:**
- A cool mist canvas with white working surfaces, one deep teal accent and pastel status pairs.
- Fraunces (with its soft axis) for page and section headings and headline numbers. Plus Jakarta Sans for everything else.
- Pill-shaped controls: buttons, badges, nav items, segmented tabs and counters.
- The magpie mascot is the brand mark and the live worker status, and it has its own small palette.
- Two themes from one token set: Mist (light) and Dusk (dark), which follows the OS unless forced.
- Springy, transform-only motion that stops completely under `prefers-reduced-motion`.

## Colors

A cool, low-contrast mist palette. One deep teal carries the brand, and every other hue appears as a soft pastel pair that means something.

### Primary
- **Magpie Sheen Teal** (`accent`): the single brand voice, named after the teal iridescence on a magpie's wing. It's used for links, the active nav label, the active tab underline, focus outlines, progress fills, count pills and the mascot's writing lines. In Dusk it lightens to `dusk-accent` and its text flips to `dusk-on-accent`.
- **Sheen Teal Deep** (`accent-hover`): the hover state of links and teal text.
- **Sheen Wash** (`accent-bg`): the tonal fill behind primary buttons, the active segmented tab, avatars, the text-selection highlight and the mascot's stage. Most "teal" in the UI is this wash with teal text on it, not a solid fill.
- **Sheen Edge** (`accent-border`): the hover border on buttons, inputs, cards and the worker toggle.

### Secondary
Pastel status pairs. Each status has a background (`-bg`), a text colour (`-fg`) and usually a solid (`-solid`) for dots, bars and timeline lines.
- **Periwinkle Info** (`info-*`): Applied, and informational notes.
- **Honey Warn** (`warn-*`): Interview stage, and anything due (a journal reminder pill).
- **Sage Success** (`success-*`): Offer. **Deep Sage** (`success-strong`) is the one solid status fill, reserved for Accepted.
- **Rose Danger** (`danger-*`): Rejected, errors and destructive actions.
- **Mist Neutral** (`neutral-*`): Closed and Declined, plus default badges.

### Tertiary
- **Lavender** (`lavender-*`) and **Peach** (`peach-*`): category tones only, never statuses. In Work history, lavender marks education and peach marks certificates. They also colour the mascot's props and the celebration confetti.

### Neutral
- **Morning Mist** (`canvas`): the page background behind everything, and the `theme-color`.
- **Nest Mist** (`sidebar`): the side menu, one step deeper than the canvas.
- **Paper White** (`surface`): cards, lists, widgets, inputs, dialogs, and the sliding nav indicator.
- **Pale Mist** (`surface-2`): inline code, skeletons, and the hover state of secondary buttons.
- **Hairline Mist** (`border`) / **Firm Hairline** (`border-strong`): card edges and row dividers, and input and secondary-button strokes.
- **Slate Body** (`text`): body copy, labels, muted text and placeholders.
- **Ink Slate** (`text-h`): headings, titles, input values and the current breadcrumb.
- **Hover Tint** (`hover-tint`): the translucent wash for hovered ghost controls and progress tracks.

### Mascot
- **Magpie Ink** (`mag-ink`), **Belly White** (`mag-white`), **Wing Sheen** (`mag-sheen` → `mag-sheen-2` gradient), **Cheek Blush** (`mag-cheek`), and the circular **Stage** (`stage`, with warn and danger variants for the queued and error moods). These colours belong to the bird. Don't reuse them as UI colours.

### Dusk (dark theme)
Dusk keeps the same roles on a deep blue-slate (`dusk-canvas` → `dusk-surface` → `dusk-surface-2`). Status backgrounds become 14–16% translucent tints of their solid, and status text becomes a pale version of the same hue. Every colour is redefined under `[data-theme='dark']` and `prefers-color-scheme: dark` in `src/index.css`, and components never branch on the theme.

### Named Rules
**The One Sheen Rule.** Teal is the only brand colour. It shows as text, outlines, underlines and small pills, almost never as a large solid fill. Primary buttons are a teal wash with teal text, not white on teal.

**The Pastel Pair Rule.** Every status uses its `-bg` / `-fg` pair, and the `-solid` is for dots, bars and lines only. Accepted is the one status that earns a solid fill.

**The Token-Only Rule.** Every colour comes from a custom property in `src/index.css`. A new colour is added there, for both themes, before any component uses it.

## Typography

**Display Font:** Fraunces Variable (with Georgia, Times New Roman)
**Body Font:** Plus Jakarta Sans Variable (with system-ui, Segoe UI, Roboto)
**Label/Mono Font:** ui-monospace (SF Mono, Consolas) for code only

**Character:** A soft, slightly wonky old-style serif over a round, friendly geometric sans. The serif makes the vault feel like a personal record, and the sans keeps the working parts quick to read.

### Hierarchy
- **Display** (Fraunces 520, 32px; 26px under 900px, line-height 1.15): one per page, the page `h1`.
- **Headline** (Fraunces 520, 21px, 1.25): section `h2`s. Widget titles in the dashboard step down to 15px/600 sans.
- **Stat** (Fraunces, 28px, 1.1, tabular figures): the headline numbers in dashboard stat tiles.
- **Title** (Plus Jakarta Sans 650, 15px, 1.35): `h3`s, row titles and card titles.
- **Body** (Plus Jakarta Sans 400, 15px, 1.5): running text. Intro paragraphs cap at 64–76ch.
- **Control** (Plus Jakarta Sans 600, 14px, 1.3): buttons, nav items, inputs, tabs. Small text is 13–13.5px.
- **Label** (Plus Jakarta Sans 700, 12px, 0.06em, uppercase): section labels in detail views, and tab rows that read as labels.
- **Eyebrow** (Plus Jakarta Sans 650, 11px, 0.14em, uppercase, teal): the greeting above the name on the profile card.

### Named Rules
**The Soft Serif Rule.** Fraunces runs with `'SOFT' 60, 'WONK' 0` for headings. The profile name alone goes to `'SOFT' 100, 'WONK' 1` and sets the surname in italic, which is the one place the type plays.

**The Serif Is for Names and Numbers Rule.** Fraunces is for page headings, section headings, the profile name, avatar initials and headline stats. Buttons, labels, tables and form text are always sans.

## Layout

The app shell is a two-column grid: a 260px side menu (it collapses to a 76px icon rail), then a main column with a sticky 68px top bar and a centred content column capped at 1120px (padding 28px 36px 72px). The top bar is a translucent, blurred canvas strip that holds the breadcrumb on the left and the magpie worker status on the right.

Spacing is a small, tight scale. Gaps of 2, 4, 6, 8, 12 and 16px make up nearly all of it. Card interiors run 14–20px, and page headers sit 22px above their content. The dashboard is an auto-fill grid of 280px-minimum widgets with 16px gaps. Wide widgets span two columns, and the stat-tile row and flow chart span the full width.

Responsive behaviour:
- **≤900px:** the side menu becomes an off-canvas drawer (min(288px, 86vw)) over a blurred scrim, the rail mode turns off, the content padding tightens to 22px 16px, and `h1` drops to 26px.
- **≤640px:** wide widgets fall back to a single column.
- **≤600px:** buttons go full width with 10px vertical padding. Icon buttons, segmented tabs and theme-switch buttons keep their intrinsic size.
- **Touch (`hover: none`):** the edit and remove actions on status-history steps, which only appear on hover elsewhere, are always visible.

`scrollbar-gutter: stable` keeps the layout from shifting when a scrollbar appears or disappears.

## Shapes

The form language is round. Controls are pills, and containers are gently curved rectangles.

- **Pill** (`rounded.pill`): every button, badge, status, nav item, nav indicator, segmented control and tab, count pill, theme switch and worker toggle.
- **Circle**: avatars, icon buttons, the worker avatar and stage, spinners, and timeline dots.
- **Gently curved** (`rounded.md`): cards, lists, widgets, stat tiles and form sections.
- **Soft** (`rounded.sm`): inputs, selects and textareas. Inline code drops to `rounded.xs`.
- **Generous** (`rounded.lg`): dialogs. The profile card is the one larger one-off (22px).

Borders are 1px hairlines (`border`) on containers and 1px `border-strong` strokes on inputs and secondary buttons. Dashed borders mean "empty / not set", as on the no-status pill. Underlines are 3px with rounded top corners, and appear on the current settings tab.

### Named Rules
**The Pill-for-Action Rule.** Anything you press or toggle is a pill or a circle, and anything that holds content is a curved rectangle. Don't make square buttons or pill-shaped cards.

## Components

### Buttons
Soft and friendly: tonal, never loud.
- **Shape:** full pill (`rounded.pill`), 7px 14px, 14px/600 sans.
- **Primary:** Sheen Wash fill with Magpie Sheen Teal text and a transparent 1px border.
- **Hover / Focus:** hover reveals the `accent-border` stroke. Keyboard focus shows a 3px translucent teal ring (`0 0 0 3px` of the accent at 28%) in place of an outline. Transitions are 140ms.
- **Secondary:** Paper White with `border-strong` and Ink Slate text. On hover it moves to Pale Mist with the teal edge.
- **Small:** 13px, 4px 11px.
- **Icon button:** a 36px transparent circle in Slate Body that takes the Hover Tint and Ink Slate on hover.
- **Disabled:** 50% opacity with a `not-allowed` cursor.

### Chips
- **Badge:** a Mist Neutral pill, 2px 9px, 12.5px/600.
- **Status pill:** the application state in its pastel pair (Applied periwinkle, Interview honey, Offer sage, Accepted solid deep sage, Rejected rose, Closed neutral). Declined is neutral with sage text and a sage inset ring, and "no status" is a dashed outline. In the list view it's a split control: the main segment advances the state and a ⋮ segment opens the full menu.
- **Count pill:** 20px tall in solid teal with `on-accent` text, 11.5px/700, and it pops in with a spring. The warning variant uses the honey pair with an inset honey ring and an icon.

### Cards / Containers
- **Corner Style:** gently curved (`rounded.md`).
- **Background:** Paper White on the Morning Mist canvas.
- **Border:** 1px `border` hairline. Linked cards move to the teal edge on hover.
- **Internal Padding:** 16px 18px for widgets, 14px 16px for stat tiles, 20px 22px for form sections.
- **Lists:** a single white card that holds rows separated by hairlines. The first and last rows inherit the card's corners. An empty list hides itself.

### Inputs / Fields
- **Style:** Paper White, 1px `border-strong`, `rounded.sm`, 7px 11px, 14px text in Ink Slate. Placeholders are Slate Body at 70%.
- **Focus:** the border turns teal and the 3px teal focus ring appears. There is no outline.
- **Select:** a custom two-gradient chevron in place of the native arrow.
- **Checkbox / Radio:** native, tinted with `accent-color: accent`.

### Navigation
- **Side menu:** Nest Mist background. At the top, the profile card (avatar, a teal uppercase eyebrow greeting, the Fraunces name with the surname in italic) links to the dashboard and outlines in teal when it is the current page.
- **Nav items:** 40px pills at 14px/550 in Ink Slate. Hover gives the Hover Tint. The active item turns teal at weight 680, its icon scales to 1.08, and a white pill indicator slides behind it on a spring.
- **Groups:** a parent toggles sub-pages that expand smoothly (grid rows 0fr → 1fr) behind a hairline indent rule. On the icon rail, sub-pages sit on a tinted tray.
- **Settings tabs:** an underlined tab row on a hairline. The current tab gets a 3px teal underline that slides between tabs, a hovered tab previews a soft underline, and the overflow fades at the edges.
- **Segmented control:** a white pill tray of transparent tabs. The active tab is Sheen Wash with teal text.
- **Mobile:** the menu becomes a drawer opened from a top-bar menu button.

### Dialogs
Every `<dialog>` is Paper White with a hairline border and generous corners (`rounded.lg`). It opens with a 420ms rise-and-scale (from 10px below and 0.97 scale) over a 30% ink backdrop blurred by 4px.

### The Magpie Worker (signature)
The live worker status in the top bar is a white pill toggle that holds a speech-bubble title and subtitle and a 42px circular stage with the magpie inside. The bird's mood follows the RQ queue. **Idle** breathes and flicks its tail. **Working** pecks while teal lines write themselves. **Queued** leans toward its waiting letters on a honey stage. **Error** is ruffled on a rose stage. **Loading** peeks up and down. When a job finishes, it hops once with sparkles. A teal count badge with a surface-coloured ring shows the queue length. All mascot motion uses transforms only, and the head-only brand mark never animates.

### Motion
Two curves cover the whole system: `ease-out` (`cubic-bezier(0.2, 0.8, 0.2, 1)`) for entering and settling, and `ease-spring` (`cubic-bezier(0.34, 1.4, 0.64, 1)`) for indicators, icons and pills that should land with a small overshoot. Three durations cover it too: 140ms for colour and border changes, 240ms for reveals, 420ms for slides and dialogs. A theme switch cross-fades colours over 240ms. Reduced motion collapses every animation and transition to 1ms.

## Do's and Don'ts

### Do:
- **Do** take every colour from the custom properties in `src/index.css`, and define any new token for both Mist and Dusk.
- **Do** use the tonal primary button (Sheen Wash fill, teal text). Keep solid teal for small things: count pills, progress fills, underlines.
- **Do** show status with its pastel `-bg` / `-fg` pair, and use `-solid` only for dots, bars and timeline lines.
- **Do** make every pressable control a pill or a circle, and every content container a curved rectangle (`rounded.md`).
- **Do** set page and section headings and headline numbers in Fraunces, and everything operational in Plus Jakarta Sans.
- **Do** give every interactive element the 3px teal focus ring (or a 2px teal outline) for keyboard focus.
- **Do** let the magpie carry the character (moods, celebrations, empty states) and keep the surrounding UI calm.
- **Do** honour `prefers-reduced-motion`, and animate with transforms and opacity only.

### Don't:
- **Don't** drift toward a generic admin template: no dense grey tables, no sharp boxed panels, no default framework blue.
- **Don't** make it feel like a corporate HR or ATS tool: no impersonal form walls, stock illustration or recruiter-dashboard chrome.
- **Don't** use hard, saturated colour. No neon status colours and no loud solid fills, apart from the single Accepted state.
- **Don't** design dark-first or "hacker": no terminal greens, and no monospace outside code. Dusk follows Mist, not the other way round.
- **Don't** use lavender or peach for statuses. They're category tones only.
- **Don't** reuse the mascot palette (`mag-*`, `stage`) for UI chrome.
- **Don't** hard-code hex values in feature stylesheets.
- **Don't** set buttons, labels or form text in the serif.
