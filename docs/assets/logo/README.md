# Logo drop zone

This folder is for the langwich logo SVGs. It is empty for now, and nothing
uses it yet: the landing page (`docs/index.html`) draws its wordmark in HTML
and CSS, and its favicon is an inline `data:` URI in the page's `<head>`.

Suggested names:

- `logo.svg` — primary logo (light backgrounds)
- `logo-dark.svg` — variant for dark mode (omit if the primary works on both)
- `logo-mark.svg` — square mark only, for the favicon

Keep the files self-contained (no external fonts or images inside the SVG)
and keep the `viewBox` attribute so they scale cleanly. Once a logo is here,
wire it up in `docs/index.html` by hand: replace the `.wordmark` markup with
`<img src="assets/logo/logo.svg" …>` and the favicon `<link rel="icon">` with
`assets/logo/logo-mark.svg`.
