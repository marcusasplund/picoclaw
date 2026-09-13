# Solid multi-page template

Minimal Solid + TypeScript + Vite shell with a responsive sidebar, one main
content region, a topbar, and a persistent light/dark theme switcher.

- `/` redirects to `/page1`.
- `/page1` and `/page2` have intentionally empty content; their names appear in the topbar.
- Navigation collapses into a drawer on mobile.
- Copy is English. No i18n, user roles, generators, sharing, or PWA is included.

## Development

```sh
npm ci
npm run dev
```

## Verification

```sh
npm run test:types
npm run lint
npm test -- --run
npm run build
```

Linting uses Oxlint with JavaScript/TypeScript correctness checks, including tests.
Warnings fail the lint command; use `npm run lint:fix` for supported automatic fixes.
Perfectionist object/interface sorting runs through Oxlint's `jsPlugins` support
(currently alpha). ESLint may be installed as a plugin dependency but is not run.
Type checking remains a separate `npm run test:types` step.
See [Oxlint configuration](https://oxc.rs/docs/guide/usage/linter/config).

Add content in `src/routes/page1.tsx` and `page2.tsx`. Update route definitions
in `src/App.tsx` and navigation in `src/components/AppSidebar.tsx` together.
Production hosting must serve `index.html` for client-side routes.

Additional components can be installed or copied from [Solid UI](https://www.solid-ui.com/).
Agents may add these as needed for approved features, following the current
installation instructions and the integration guidance in `PRODUCT.md`.

Fill `PRODUCT.md` placeholders from the interview or approved brief before
feature work. `DESIGN.md` describes the reusable shell and replaceable styling.
The shared Impeccable skill is unchanged; project context belongs in these files.
