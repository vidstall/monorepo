# Elucim

Builds diagrams for `docs/` from React components instead of hand-drawn
images or mermaid. Each diagram is a `.tsx` file in `src/diagrams/`; the
build turns it into a PNG in `output/` via [satori](https://github.com/vercel/satori)
(JSX → SVG) and [`@resvg/resvg-js`](https://github.com/yisibl/resvg-js) (SVG → PNG).

## Usage

```bash
pnpm install
pnpm build
```

This renders every component under `src/diagrams/` to a same-named PNG in
`output/`. Reference the output file from docs with a normal markdown image
link, e.g. `![...](../imgen/output/topology.png)`.

## Adding a diagram

1. Add a new `src/diagrams/<name>.tsx` with a default-exported React
   component. Satori only supports flexbox `div`/`span` layout (no
   absolute-positioned lines) — draw connections with arrow glyphs (→ ↓)
   rather than literal lines.
2. Run `pnpm build`; a matching `output/<name>.png` is created.
3. Commit the generated PNG alongside the source so docs render without
   requiring a build step.
