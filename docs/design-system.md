# RoadSense Design System v2

The web app (`roadsense/web/static`) is a single page with no build step. The design system is plain CSS custom
properties in `app.css` and small HTML-string helpers in `app.js`. This page is the reference for both.

## Principles

1. **Calm by default, loud when it matters.** Neutral surfaces carry the layout. Colour is reserved for status and for
   the one primary action on screen: *Approve & send*, *New trip*, *Analyse trip*.
2. **Trust is visible.** Guardrails, payload hashes, privacy notes and agent rationale sit in the main flow, not
   behind a link.
3. **Data first.** Numbers use tabular figures. Tables are dense, with a 52 px row target. Labels stay short.
4. **Keyboard-first.** `Ctrl/⌘ K` opens the command palette, `J`/`K` move through the review inbox, every interactive
   row is focusable. Sending to an authority is **never** bound to a key.
5. **One token layer per job.** Themes override only the semantic layer, and components read only semantic tokens.

## Tokens

### Layer 1: primitives (do not use in components)

| Token | Values |
|---|---|
| `--gray-0 … --gray-950` | 14-step cool neutral ramp |
| `--indigo-50 … --indigo-900` | Brand ramp; `--indigo-600` `#4f46e5` is the light-mode primary |

### Layer 2: semantic (themes override these)

| Group | Tokens | Use |
|---|---|---|
| Canvas | `--bg`, `--bg-subtle` | Page background |
| Surfaces | `--surface`, `--surface-2`, `--surface-hover`, `--surface-sunken`, `--overlay` | Cards, table headers, hover rows, track backgrounds, modal scrim |
| Borders | `--border`, `--border-strong`, `--border-input` | Dividers, hovered controls, form inputs |
| Text | `--text`, `--text-2`, `--muted`, `--faint` | Primary, body, secondary, tertiary |
| Accent | `--primary`, `--primary-hover`, `--primary-soft`, `--primary-text`, `--primary-ring`, `--on-primary` | Primary actions, focus, selection |
| Status | `--{amber,green,red,violet,cyan,gray}-{soft,text,border}` plus base `--amber`, `--green`, `--red` … | Badges, callouts, KPI icons |
| Elevation | `--shadow-xs`, `--shadow-sm`, `--shadow`, `--shadow-lg`, `--highlight` | Controls, cards, hover, overlays |

What each status colour means:

| Tone | Meaning in RoadSense |
|---|---|
| amber | Waiting on a human (awaiting review, class disputed, rule-engine mode) |
| blue (primary) | Approved, merged sightings, informational |
| violet | Sent to an authority, LLM agents |
| green | Fixed, done, live, guardrail satisfied |
| red | Priority 1 candidate, failure, destructive |
| cyan | Provincial routing (NS Public Works) |
| gray | Rejected, neutral, rule engine |

### Scales

| Scale | Tokens |
|---|---|
| Spacing (4 px base) | `--space-1` 4 · `-2` 8 · `-3` 12 · `-4` 16 · `-5` 20 · `-6` 24 · `-8` 32 · `-10` 40 |
| Radius | `--radius-xs` 4 · `-sm` 6 · `--radius` 10 · `-lg` 14 · `-full` |
| Type | `--text-xs` 11.5 · `-sm` 12.5 · `-base` 13.5 · `-md` 14.5 · `-lg` 16 · `-xl` 20 · `-2xl` 24 · `-3xl` 30 |
| Font | `--font` Inter (system fallback); `--mono` JetBrains Mono |
| Motion | `--dur-fast` 120 ms · `--dur` 180 ms · `--dur-slow` 280 ms · `--ease` `cubic-bezier(.2,.8,.2,1)` |
| Layout | `--sidebar-w` 256 px · `--topbar-h` 56 px · content max 1440 px |

Themes: light is the default. Dark follows `prefers-color-scheme` unless the user picks one; that choice is stored in
`localStorage["rs-theme"]` and applied before first paint. `prefers-reduced-motion` turns animation off.

## Components

| Component | Class / helper | Variants | States |
|---|---|---|---|
| Button | `.btn` | `.btn-primary`, `.btn-ghost`, `.btn-danger`; sizes `.btn-sm`, default, `.btn-lg`; `.icon-btn` | hover, active, focus-visible ring, `:disabled`, loading (`icon("refresh","spin")`) |
| Badge | `.pill` · `statusPill()` · `sevPill()` | tones `blue amber green red violet cyan`, `.mono`; optional `.dot` | — |
| Card | `.card` › `.card-head` (`h2`, `.desc`, `.spacer`) › `.card-body` / `.flush` › `.card-foot` | — | — |
| Stat tile | `.card.kpi` › `.label` + `.ic.{tone}`, `.value`, `.hint` | tone per metric | hover lift |
| Funnel | `.funnel` › `.stage` (`.t`, `.n`, `.rate`, `.bar`, `.delta`) | last stage green | — |
| Segmented control | `.tabs` › `button.on` + `.n` count | — | hover, selected (`aria-selected`) |
| Table | `.table-wrap` › `.table` · `tr.click` · `.row-arrow` · `.thumb` | — | row hover, focus, Enter opens |
| Search input | `.input-icon` › `svg` + `.input` | — | focus ring |
| Callout | `.callout.{amber,red,blue,green}` | — | — |
| Activity feed | `.feed` › `li` (`avatar()`, `.what`, `.who`, `.why`, `.when`) | `details.tool` for tool calls | hover |
| Timeline | `.timeline` | — | — |
| Payload | `.payload` › `dl` + `.hash` | — | — |
| Action bar | `.actionbar` (sticky) | — | stacks on mobile |
| Dropzone | `.dropzone` › `.dz-icon` | — | hover, `.drag`, focus-within |
| Switch | `.switch` › `input[type=checkbox]` | — | checked, focus |
| Progress / steps | `.steps` › `.step.on/.ok`, `.progress` | — | running, done |
| Empty state | `emptyState(icon, title, text, action)` | — | — |
| Error state | `errorState(e)` with Retry | — | — |
| Toast | `toast(msg, ok)` | success, `.err` | show/hide, `aria-live` |
| Skeleton | `.skeleton` | — | shimmer |
| Command palette | `#palette` · `palette.open()` | groups: Go to, Actions, Awaiting review | keyboard nav, `aria-activedescendant` |

### Button: do and don't

| ✅ Do | ❌ Don't |
|---|---|
| One `.btn-primary` per view region | Two primary buttons side by side |
| Name the destination: "Approve & send to Halifax 311" | Write a generic "Submit" |
| `.btn-danger` for Reject, placed before the primary action | Bind Approve or Reject to a single key |

## Patterns

- **App shell.** Sticky sidebar with the workspace, a search trigger, grouped nav (*Workspace*, *Agents*) and live
  agent status. The topbar has breadcrumbs, the theme toggle and the global primary action. Below 760 px the sidebar
  becomes an off-canvas drawer with a scrim, and Escape closes it.
- **Page header.** `h1` plus a one-line description, set by the router from `ROUTES`.
- **List → detail.** Filters (`.tabs` with counts) and search sit in a `.toolbar` above a table card. A row opens the
  detail, and the breadcrumb shows `Reports / #id`.
- **Review inbox.** A sticky list on the left and the detail on the right, with the decision in a sticky action bar.
  `J`/`K` navigate.
- **Loading, empty and error.** Every route renders a skeleton first. Empty states say what will appear and how to make
  it appear. Errors say how to fix them and offer Retry.

## Accessibility

- Skip link to `#view`. Visible `:focus-visible` ring on every control.
- Nav uses `aria-current` through `.active`. Segmented controls expose `role="tab"` and `aria-selected`.
- The palette is `role="dialog" aria-modal="true"` with a listbox and options, closes on Escape or a scrim click, and
  returns focus to the element that opened it.
- Body text keeps at least 4.5:1 contrast in both themes. Status colour is never the only signal: every status badge
  also has a text label.
- All server and agent text goes through `esc()` before it reaches the DOM. Agent output is untrusted.

## Extending

1. Need a colour? Map it to a semantic token. If none fits, add a semantic token to **both** themes, never a raw hex in
   a component. The one exception is Leaflet markers (`MAP_COLORS`), which mirror the status tokens.
2. Need a component? Build it from existing tokens, add it to the table above with its variants and states, and give
   it a keyboard path.
