# GitHub Pages plan

Ruffster's public website is a dependency-free static site in [`docs/`](docs/). It is a first-contact product surface for parents, not just project documentation. Its job is to help a parent quickly understand the purpose, privacy boundaries, current readiness, and the eventual path from download to a family review. The experience should feel calm, clear, polished, and trustworthy without implying that this experimental prototype is ready to install.

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
- Run `npm ci && npm run check:pages-a11y` to scan all three pages against WCAG 2.1 A/AA and accessibility best-practice rules at desktop and phone widths and check for horizontal overflow. Then review keyboard and screen-reader behavior manually.
- Use current product screenshots with synthetic or empty demonstration data only. Link to full-size screenshots and state what is illustrative. Refresh them when the dashboard changes.
- Make readiness truthful on every page. Do not add download links for unsigned or unvalidated builds. Linux is a development/test host only; macOS is first and Windows is next.
- Keep page and asset paths relative so project Pages URLs under `/repository-name/` work. No third-party analytics, trackers, fonts, or runtime dependencies.

## Implementation and launch tasks

1. Keep the product story, screenshots, platform priorities, and readiness caveat current in `README.md`.
2. Refine the home page, parent installation journey, and FAQ as a unified site with accessible desktop and mobile layouts.
3. Run `tests.test_docs_site` to check Pages entry points, screenshot assets, local links, fragments, and visible release caveats. Run `npm ci && npm run check:pages-a11y`, then review a real-browser render at desktop and phone widths before launch.
4. Keep `.github/workflows/pages.yml` limited to pushes to `main` that change `docs/`, plus manual runs. Once Pages is enabled for GitHub Actions, the workflow publishes the static `docs/` directory and reports the live URL. Verify all three pages and screenshot links at that repository-subpath URL.
5. Update screenshots and install/FAQ copy with every user-facing release; keep a prominent status and avoid implying unsupported platform behavior.

The Ruffster Git remote is configured and `main` has been pushed, but Pages is not yet enabled. The first deploy attempt confirmed that the source setting is required. Before the first push, review the author name and email in local Git commits; GitHub exposes that metadata with published commits. If desired, set Git to use the private noreply address shown in GitHub settings, then decide whether existing local-only commits should be rewritten to use it. After the reviewed `main` branch is pushed:

1. Open the repository **Settings → Pages**.
2. Under **Build and deployment**, choose **GitHub Actions** as the source.
3. Run the **Deploy Ruffster Pages** workflow, or push a change under `docs/` to `main`.
4. Open the URL shown by GitHub Pages and verify the home page, getting-started page, FAQ, screenshots, mobile layout, and links from the deployed project subpath.

The site has no runtime package dependencies or build step; `package.json` contains only local accessibility-check tooling. `.nojekyll` asks Pages to publish the directory as static files. Automated checks cannot judge visual quality or complete accessibility; a real browser review, keyboard navigation, and screen-reader behavior are still required before publication. If the hosting setup changes, keep the same no-build output and verify base-path-relative links again.

GitHub Pages sites are publicly available. Do not put child activity, credentials, key material, private reports, or unreleased personal data in `docs/`. Do not link a family download until the corresponding app build is signed, tested on its target OS, and approved for release. Current instructions clearly say the prototype is not ready for family deployment.

GitHub's current branch-publishing instructions are in the [official GitHub Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
