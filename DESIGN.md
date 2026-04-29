---
name: OpenBBQ
description: Native-adjacent desktop workspace for inspectable media automation.
colors:
  canvas: "oklch(95.6% 0.006 245)"
  paper: "oklch(99% 0.004 245)"
  paper-muted: "oklch(96.8% 0.006 245)"
  paper-side: "oklch(92.8% 0.008 245)"
  paper-selected: "oklch(93.5% 0.026 248)"
  ink: "oklch(23% 0.014 245)"
  ink-brown: "oklch(23% 0.014 245)"
  muted: "oklch(49% 0.017 245)"
  line: "oklch(88% 0.01 245)"
  accent: "oklch(52% 0.112 248)"
  accent-hover: "oklch(47% 0.118 248)"
  accent-soft: "oklch(92% 0.046 248)"
  ready: "oklch(48% 0.075 154)"
  state-running: "oklch(91.8% 0.034 248)"
  log-bg: "oklch(22% 0.018 245)"
  log-panel: "oklch(27% 0.018 245)"
  log-muted: "oklch(70% 0.018 245)"
  log-text: "oklch(92% 0.009 245)"
  log-warning: "oklch(78% 0.071 67)"
  log-accent: "oklch(73% 0.082 248)"
  log-error: "oklch(74% 0.086 38)"
typography:
  display:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "normal"
  headline:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "normal"
  title:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "normal"
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "normal"
rounded:
  sm: "5px"
  md: "6px"
  lg: "7px"
  xl: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  panel: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.paper}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.paper}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "40px"
  button-ink:
    backgroundColor: "{colors.ink-brown}"
    textColor: "{colors.paper}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "40px"
  input-field:
    backgroundColor: "{colors.paper-muted}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "44px"
---

# Design System: OpenBBQ

## 1. Overview

**Creative North Star: "The Native Workbench"**

OpenBBQ should feel like a focused desktop workspace: quiet, precise, and native-adjacent. It borrows macOS discipline through restrained surfaces, clear hierarchy, soft functional elevation, and controls that make repeated media workflow work feel calm. It does not imitate the operating system; it translates that cleanliness into OpenBBQ's source import, workflow arrangement, task monitoring, review, and settings screens.

The system is dense because the product is operational. Density is acceptable when structure is clear: source, state, next action, and output must remain visible without decorative competition. The surface should feel local-first, inspectable, and trustworthy, never like a web campaign or a generic terminal skin.

**Key Characteristics:**
- Native-adjacent desktop restraint.
- Compact panels with deliberate hierarchy.
- Blue-tinted neutrals and one restrained operational accent.
- Dark surfaces reserved for machine output, media preview, and logs.
- Visible state through color, shape, icon, copy, and position.

## 2. Colors

The palette is a restrained blue-neutral system with one operational blue accent and a separate dark log vocabulary.

### Primary
- **Workbench Blue** (`accent`): Primary action color, selected progress bars, active segment progress, focus outlines, and important status affordances.
- **Pressed Workbench Blue** (`accent-hover`): Hover color for primary actions. Use only as an interaction state.
- **Quiet Blue Wash** (`accent-soft`): Low-emphasis alerts, selected metadata pills, and supporting action backgrounds.

### Secondary
- **Ready Green** (`ready`): Successful, saved, present, and ready states. Use with text labels; never rely on color alone.
- **Running Wash** (`state-running`): Running or enabled-but-not-selected state. Pair with icons or text labels.

### Neutral
- **Canvas Blue Grey** (`canvas`): Application background outside the main shell.
- **Paper White** (`paper`): Main content panels and raised controls.
- **Muted Paper** (`paper-muted`): Secondary panels, grouped controls, review cards, and configuration sections.
- **Sidebar Paper** (`paper-side`): Navigation rail, inactive tracks, disabled controls, and subdued containers.
- **Selected Paper** (`paper-selected`): Active workflow rows, selected segments, selected timeline states, and emphasized nested surfaces.
- **Primary Ink** (`ink` / `ink-brown`): Main text and strong UI marks.
- **Muted Ink** (`muted`): Secondary labels, helper text, metadata, timestamps, and inactive navigation.
- **Hairline Blue Grey** (`line`): Dividers and quiet structural edges when shadows are not appropriate.

### Tertiary
- **Runtime Black Blue** (`log-bg`): Runtime log panels and media preview voids only.
- **Runtime Panel Blue** (`log-panel`): Log badges and progress tracks.
- **Runtime Text** (`log-text`): Primary text inside log surfaces.
- **Runtime Muted** (`log-muted`): Log timestamps, secondary details, and scrollbars.
- **Runtime Warning** (`log-warning`): Warning log rows.
- **Runtime Accent** (`log-accent`): Log progress bars and progress percentages.
- **Runtime Error** (`log-error`): Error log rows.

### Named Rules
**The One Accent Rule.** Workbench Blue is the only general-purpose accent. Do not introduce extra decorative hues for variety.

**The Log Island Rule.** Dark surfaces are allowed for runtime logs, media preview, and machine output. They are forbidden as the default app theme.

## 3. Typography

**Display Font:** System sans (`ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`)
**Body Font:** System sans (`ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`)
**Label/Mono Font:** System mono only for timestamps, logs, ranges, paths, and numeric operational values.

**Character:** The type system should feel native, direct, and unbranded. Hierarchy comes from weight, size, spacing, and placement, not novelty fonts.

### Hierarchy
- **Display** (600, 32px, 1.25): Page titles such as source import, workflow arrangement, task monitor, settings, and results review.
- **Headline** (600, 24px, 1.2): Major panel titles and selected-detail headings.
- **Title** (600, 20px, 1.25): Section titles and workflow group titles.
- **Body** (400-600, 14px, 1.5): Field labels, explanatory copy, controls, row summaries, and short descriptions. Keep explanatory lines under 68ch.
- **Label** (600, 11-12px, normal tracking): Eyebrows, compact metadata, status labels, nav text, and form microcopy. Uppercase is allowed only for stable category labels.

### Named Rules
**The Native Type Rule.** Do not add decorative display fonts. OpenBBQ earns trust by looking like a serious desktop tool, not a campaign page.

**The Short Line Rule.** Descriptive copy should stay compact. Long prose belongs in docs, not dense workflow screens.

## 4. Elevation

OpenBBQ uses tonal layering plus utility shadows. Surfaces are mostly flat at rest, with low shadows to separate controls, panels, and selected states. Elevation should clarify grouping or interactivity; it must never become decoration.

### Shadow Vocabulary
- **Panel shadow** (`0 10px 30px rgba(38,45,55,0.10), 0 1px 3px rgba(38,45,55,0.10)`): Main app shell and large persistent panels.
- **Control shadow** (`0 1px 3px rgba(38,45,55,0.12)`): Buttons, cards, sidebars, inputs, status chips, and small containers.
- **Selected shadow** (`inset 0 0 0 1px rgba(55,102,190,0.24), 0 1px 3px rgba(38,45,55,0.10)`): Selected rows, selected segments, active navigation, and emphasized active surfaces.
- **Running shadow** (`inset 0 0 0 2px rgba(55,102,190,0.34)`): Running progress indicators and active automation states.

### Named Rules
**The Utility Depth Rule.** Shadows exist to separate, select, or show state. Decorative depth, glass cards, and floating marketing panels are prohibited.

## 5. Components

### Buttons
- **Shape:** Compact rounded rectangle (6px radius) with 40px minimum height.
- **Primary:** Workbench Blue background with Paper White text, used for the next irreversible or forward action.
- **Hover / Focus:** Primary hover uses Pressed Workbench Blue. Focus uses a 2px Workbench Blue outline with 2px offset.
- **Secondary:** Paper White background with Primary Ink text for routine actions.
- **Ink:** Primary Ink background with Paper White text for serious control actions such as cancellation.
- **Disabled:** Sidebar Paper background, Muted Ink text, no shadow, and no active scale effect.

### Chips
- **Style:** Rounded full pills, compact padding, 11-12px semibold text.
- **State:** Active chips use Quiet Blue Wash with Workbench Blue text. Neutral chips use Paper or Muted Paper with Muted Ink.

### Cards / Containers
- **Corner Style:** Gently rounded, never pill-like for panels (8px maximum).
- **Background:** Paper for primary surfaces, Muted Paper for grouped sections, Sidebar Paper for navigation rails and disabled tracks.
- **Shadow Strategy:** Use control shadow for small grouped surfaces and panel shadow for the main shell only.
- **Border:** Prefer selected shadow or tonal background shifts over visible borders. Hairline Blue Grey is acceptable for tight separators.
- **Internal Padding:** Small controls use 12-16px. Major panels use 16-24px.

### Inputs / Fields
- **Style:** 44px minimum height, 6px radius, Muted Paper or Paper background, compact horizontal padding.
- **Focus:** 2px Workbench Blue outline with 2px offset.
- **Error / Disabled:** Error text uses Workbench Blue until a distinct error token is introduced; disabled fields use Sidebar Paper with Muted Ink.

### Navigation

Sidebar navigation uses compact icon-first buttons. On wide screens, labels appear beside 16px lucide icons; on narrow screens, the rail collapses into icon-only top navigation. Active navigation uses Paper White, Primary Ink, and selected shadow. Inactive navigation uses Muted Ink and only gains Paper White on hover.

### Runtime Log

Runtime log panels are the only sanctioned dark UI region. They use Runtime Black Blue, monospace text, compact grid rows, timestamp columns, level badges, and inline progress bars. They should feel technical but still readable inside the otherwise light desktop system.

### Segment Review Card

Segment cards use Paper at rest and Selected Paper when active. Active cards may animate with a short 260ms ease-out entrance, disabled under reduced motion. The active playback progress bar is a thin Workbench Blue strip at the top edge, not a side stripe.

## 6. Do's and Don'ts

### Do:
- **Do** preserve the native-adjacent desktop restraint: quiet surfaces, compact controls, and visible state.
- **Do** use the existing OKLCH tokens as the source of truth.
- **Do** reserve `log-bg` and `log-panel` for logs, media preview, and machine output.
- **Do** communicate automation status with labels, icons, progress, and placement, not color alone.
- **Do** keep radii at 8px or below for panels and controls.
- **Do** keep repeated workflow screens dense but structured.

### Don't:
- **Don't** use flashy gradients, noisy decorative effects, or Chinese internet tool-site styling.
- **Don't** make the desktop app feel like a marketing page, a dark terminal skin, or a pile of identical promotional cards.
- **Don't** use gradient text, glassmorphism, decorative blur, or hero-metric templates.
- **Don't** use `border-left` or `border-right` greater than 1px as a colored accent on cards, list items, callouts, or alerts.
- **Don't** introduce a full dark theme by spreading runtime log colors into normal workflow screens.
- **Don't** add decorative fonts, oversized hero type, or sparse landing-page spacing to operational screens.
