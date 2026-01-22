# Building HTML Documentation

## Quick Build

```bash
cd docs
npm install
npm run build
```

The HTML documentation will be generated in `docs/html/` directory.

## Development

For development with hot-reload:

```bash
cd docs
npm start
```

## Output Location

- **Build Output**: `docs/html/`
- **Entry Point**: Root `index.html` redirects to `docs/html/index.html`

## Notes

- The `html/` directory is gitignored (add to `.gitignore`)
- Build output should be committed separately or deployed via CI/CD
- For GitHub Pages, use `npm run deploy` instead
