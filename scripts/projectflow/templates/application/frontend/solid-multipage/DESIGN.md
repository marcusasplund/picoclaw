# Application shell design

## Scope

Reusable product UI. Brand-specific choices should be filled from the approved
brief. This file documents the current implementation, not a finished identity.

## Evolving the visual direction

All visual defaults below may evolve in response to the user's creative direction.
For example, an 8-bit treatment may use pixel-style typography and icons, a limited
palette, hard borders, and stepped motion. Choose details that serve the requested
style while preserving readable text, accessible interactions, responsiveness,
and reduced-motion alternatives.

Update this document to describe the resulting design after an experiment; old
starter choices must not pull later work back to the original appearance. Record
the current direction, intentional departures, and relevant verification evidence
under project-specific decisions. Impeccable reviews should assess consistency
with that direction and report aesthetic heuristics as advisory findings.

## Layout

One responsive sidebar (16rem desktop, 18rem mobile drawer), a 4rem topbar, and
one main landmark. The topbar contains navigation toggle, current page heading,
and theme switcher. Main content scrolls independently with 1.5rem padding.
Page 1 and Page 2 are intentionally empty. Below 768px navigation is a modal
drawer that closes on selection, Escape, close button, or outside interaction.

## Color and themes

Keep semantic tokens in `src/app.css` and Tailwind mappings in
`tailwind.config.js`. The inherited baseline uses muted blue accents, warm light
surfaces, and charcoal dark surfaces. These are replaceable defaults, not a brand
requirement. Main light background: hsl(42 24% 96%); foreground: hsl(218 15% 24%).
Dark background: hsl(220 14% 11%); foreground: hsl(40 15% 88%).
Theme follows the system initially; explicit light/dark selection persists under
`app-theme` in local storage. Keep the initialization script and provider aligned.

## Typography and components

System sans-serif throughout. Topbar title and navigation use compact text-sm.
Controls use shared Kobalte-based primitives and Lucide icons. Base radius is
0.5rem. Active navigation uses the sidebar accent; focus uses the ring token.
Retain visible focus, descriptive control labels, and reduced-motion support.
No app-specific illustrations, logos, print styles, or translated copy are included.

## Project-specific decisions

- Brand and visual references: [fill from brief]
- Current creative direction and intentional departures: [update as experiments evolve]
- Product-specific components and states: [fill when requirements exist]
- Any approved changes to palette, typography, or density: [record here]
- Verification evidence for the current design: [record checks and remaining findings]

Run Impeccable against the generated project's brief and current code. Do not
carry reviews or product assumptions forward from the starter's source app.
