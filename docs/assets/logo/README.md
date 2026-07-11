# Logo drop zone

Put the langwich logo SVGs in this folder. Suggested names:

- `logo.svg` — primary logo (light backgrounds)
- `logo-dark.svg` — variant for dark mode (omit if the primary works on both)
- `logo-mark.svg` — square mark only, used for the favicon

Keep the files self-contained (no external fonts or images inside the SVG)
and keep the `viewBox` attribute so they scale cleanly. Once they're here,
the landing page picks them up at `assets/logo/<name>.svg`.
