# Product

## Register

product

## Users

[Define the target audience and usage context from the project brief.]

## Product Purpose

A reusable Solid application shell with one sidebar, one main content region,
a topbar with theme switching, and two empty routes: Page 1 and Page 2.
[Replace this description with the generated application's purpose and success criteria.]

## Brand Personality

[Define voice and personality from the approved brief.]

## Anti-references

[Record relevant references and patterns to avoid.]

## Design Principles

- Keep navigation and the main task easy to find.
- Start from the shell and adapt it to the user's direction while retaining required behavior.
- Leave the starter pages empty until real requirements exist.
- Use plain English; localization is not included in this template.

## Accessibility & Inclusion

Target WCAG AA, visible keyboard focus, semantic labels, light/dark contrast,
and reduced motion. Color must not be the only indication of state.

## Generation notes

Fill placeholders from the interview or approved plan before feature work.
Do not invent a domain, user roles, or workflows from this starter.

## Creative direction and experimentation

The template supplies defaults that agents may change. The user's latest explicit
creative direction takes precedence over template styling and aesthetic skill
preferences. A request such as "make it 8-bit looking" authorizes a coherent change
to typography, palette, borders, icons, spacing, and motion, including adapting or
replacing components and layout where the direction calls for it. Do not require
separate permission merely to depart from the starter's appearance.

Preserve required functionality, keyboard access, responsive behavior, readable
contrast, and reduced-motion support. Evaluate visual choices against the chosen
direction: pixel graphics, hard edges, and unusual typography are not failures
merely because they depart from conventional product UI. Aesthetic heuristics are
advisory; actual functional and accessibility failures still require repair.

Record the new direction and intentional departures in `DESIGN.md`, update the
brief when needed, and rerun relevant verification after implementation. Follow
the pipeline's existing approval rules when scope or an approved plan changes.

## Additional components

Agents may install or copy additional components from [Solid UI](https://www.solid-ui.com/)
when needed for the approved features. Follow the current component installation
instructions, reuse existing components in `src/components/ui` where suitable, and
adapt additions to the project's current design tokens and accessibility conventions. Add required
dependencies with npm, update the lockfile, and run lint, type checks, relevant
tests, and the production build after integration.
