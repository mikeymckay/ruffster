# GitHub Pages plan

Family Activity's public website is a dependency-free static site in [`docs/`](docs/). It is a first-contact product surface for parents, not just project documentation. Its job is to help a parent quickly understand the purpose, privacy boundaries, current readiness, and the eventual path from download to a family review. The experience should feel calm, clear, polished, and trustworthy without implying that this experimental prototype is ready to install.

The public entry points are:

- `docs/index.html` — home page and product explanation
- `docs/install.html` — preview status and getting-started guide
- `docs/faq.html` — privacy, data, platform, and limitation answers
- `docs/assets/` — shared styling and synthetic-only UI screenshots

## Quality bar

- The home page explains the family benefit, transparency principles, what is measured, and what cannot be concluded. Current status is visible without scrolling.
- The parent guide speaks to an ordinary parent first. It gives one clear next step, avoids command-line instructions in the family journey, and makes the future download/setup/review/recovery/removal path understandable. Developer steps live in a separate section.
- The FAQ answers privacy and practical questions plainly, especially encryption and key recovery, retention and deletion, school and home labels, network limits, gaps, and platform support.
- Keep the design cohesive and responsive, with readable typography, high contrast, keyboard navigation, useful focus states, semantic headings, descriptive image text, and layouts that work on a phone.
- Run an automated WCAG 2.1 A/AA and accessibility best-practice scan on all three pages at desktop and phone widths, then review keyboard and screen-reader behavior manually.
- Use current product screenshots with synthetic or empty demonstration data only. Link to full-size screenshots and state what is illustrative. Refresh them when the dashboard changes.
- Make readiness truthful on every page. Do not add download links for unsigned or unvalidated builds. Linux is a development/test host only; macOS is first and Windows is next.
- Keep page and asset paths relative so project Pages URLs under `/repository-name/` work. No third-party analytics, trackers, fonts, or runtime dependencies.

## Implementation and launch tasks

1. Keep the product story, screenshots, platform priorities, and readiness caveat current in `README.md`.
2. Refine the home page, parent installation journey, and FAQ as a unified site with accessible desktop and mobile layouts.
3. Run `tests.test_docs_site` to check Pages entry points, screenshot assets, local links, fragments, and visible release caveats; run an automated accessibility scan and review a real-browser render at desktop and phone widths before launch.
4. When the repository is available on GitHub, enable Pages using `main` and `/docs`, then verify all three pages and screenshot links at the published repository-subpath URL.
5. Update screenshots and install/FAQ copy with every user-facing release; keep a prominent status and avoid implying unsupported platform behavior.

The repository checkout currently has no Git remote or GitHub Pages deployment, so no public URL is configured yet. After creating the GitHub repository and pushing the current `main` branch:

1. Open the repository **Settings → Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Choose branch `main` and folder `/docs`, then save.
4. Open the URL shown by GitHub Pages and verify the home page, getting-started page, FAQ, screenshots, mobile layout, and links from the deployed project subpath.

The site has no package installation or build step. `.nojekyll` asks Pages to publish the directory as static files. Automated checks cannot judge visual quality, responsive behavior, or accessibility; a real browser review is still required before publication. If the hosting setup changes, keep the same no-build output and verify base-path-relative links again.

GitHub Pages sites are publicly available. Do not put child activity, credentials, key material, private reports, or unreleased personal data in `docs/`. Do not link a family download until the corresponding app build is signed, tested on its target OS, and approved for release. Current instructions clearly say the prototype is not ready for family deployment.

GitHub's current branch-publishing instructions are in the [official GitHub Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
