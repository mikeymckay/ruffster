# GitHub Pages plan

Ruffster's public website is a dependency-free static site in [`docs/`](docs/). It is a first-contact product surface for parents, not just project documentation. Its job is to help a parent quickly understand the purpose, privacy boundaries, current readiness, and the eventual path from download to a family review. The experience should feel calm, clear, polished, and trustworthy without implying that this experimental prototype is ready to install.

The public entry points are:

- `docs/index.html` — home page and product explanation
- `docs/install.html` — preview status and getting-started guide
- `docs/progress.html` — current milestones, validation evidence, and release gates
- `docs/faq.html` — privacy, data, platform, and limitation answers
- `docs/assets/` — shared styling and synthetic-only UI screenshots

## Quality bar

- The home page explains the family benefit, transparency principles, what is measured, and what cannot be concluded. Current status is visible without scrolling.
- The parent guide speaks to an ordinary parent first. It gives one clear next step, avoids command-line instructions in the family journey, and makes the future download/setup/review/recovery/removal path understandable. Developer steps live in a separate section.
- The FAQ answers privacy and practical questions plainly, especially encryption and key recovery, retention and deletion, school and home labels, network limits, gaps, and platform support.
- Keep the design cohesive and responsive, with readable typography, high contrast, keyboard navigation, useful focus states, semantic headings, descriptive image text, and layouts that work on a phone.
- Run `npm ci && npm run check:pages-a11y` to scan all four pages against WCAG 2.1 A/AA and accessibility best-practice rules at desktop and phone widths and check for horizontal overflow. Then review keyboard and screen-reader behavior manually.
- Use current product screenshots with synthetic or empty demonstration data only. Link to full-size screenshots and state what is illustrative. Refresh them when the dashboard changes.
- Make readiness truthful on every page. Do not add download links for unsigned or unvalidated builds. Linux is a development/test host only; macOS is first and Windows is next.
- Keep page and asset paths relative so project Pages URLs under `/repository-name/` work. No third-party analytics, trackers, fonts, or runtime dependencies.

## Implementation and launch tasks

1. Keep the product story, screenshots, platform priorities, and readiness caveat current in `README.md`.
2. Refine the home page, parent installation journey, and FAQ as a unified site with accessible desktop and mobile layouts.
3. Run `tests.test_docs_site` to check Pages entry points, screenshot assets, local links, fragments, and visible release caveats. Run `npm ci && npm run check:pages-a11y`, then review a real-browser render at desktop and phone widths before launch.
4. Keep `.github/workflows/pages.yml` limited to pushes to `main` that change the site or its accessibility check, plus manual runs. The workflow runs the accessibility check before publishing `docs/`, independently of app builds. Verify all four pages and screenshot links at that repository-subpath URL.
5. Update screenshots and install/FAQ copy with every user-facing release; keep a prominent status and avoid implying unsupported platform behavior.

The Ruffster repository is public, and its Pages source is now configured to use GitHub Actions. A site change on `main` triggers deployment after the accessibility scan passes; the Pages workflow also supports a manual run on `main`. The first deployment after enabling Pages is being checked.

1. Confirm the **GitHub Actions** source remains selected under repository **Settings → Pages**.
2. If a site change does not trigger deployment, run **Deploy Ruffster Pages** from the Actions tab on `main`.
3. Open the URL shown by GitHub Pages and verify the home page, getting-started page, progress page, FAQ, screenshots, mobile layout, and links from the deployed project subpath.

The site has no runtime package dependencies or build step; `package.json` contains only local accessibility-check tooling. `.nojekyll` asks Pages to publish the directory as static files. Automated checks cannot judge visual quality or complete accessibility; a real browser review, keyboard navigation, and screen-reader behavior are still required before publication. If the hosting setup changes, keep the same no-build output and verify base-path-relative links again.

GitHub Pages sites are publicly available. Do not put child activity, credentials, key material, private reports, or unreleased personal data in `docs/`. Do not link a family download until the corresponding app build is signed, tested on its target OS, and approved for release. Current instructions clearly say the prototype is not ready for family deployment.

GitHub's current branch-publishing instructions are in the [official GitHub Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
