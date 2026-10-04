# Brand assets

How to use the brand assets this repository carries.

The mark at the top of the README, following the reader's theme. The URLs are absolute so that PyPI shows the image too:

```markdown
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/osintshifu/filegrail/master/assets/filegrail-pictogram-ondark.png">
  <img src="https://raw.githubusercontent.com/osintshifu/filegrail/master/assets/filegrail-pictogram-onlight.png" alt="FileGrail logomark" width="240">
</picture>
```

Reach for the PNG anywhere the image leaves this repository. The SVG lockups set the wordmark as live text in DM Mono, which a reader who does not have the font installed will not see; GitHub and PyPI render an image without loading fonts, so they would show the fallback.

The mark the HTML report shows in its masthead and in its tab icon is not a file: it is drawn in the page by `htmlreport.py`, so a report carries no image to load.

## Files

| File | Use |
| --- | --- |
| `filegrail-pictogram-onlight.png`, `-ondark.png` | the pictogram at the top of the README, light and dark backgrounds, with clear space drawn in |
| `filegrail-stacked-compact-dark.png` `.svg` | vertical lockup with the smaller mark, dark backgrounds |
| `filegrail-stacked-compact-light.png` `.svg` | vertical lockup with the smaller mark, light backgrounds |
| `filegrail-stacked-dark.png` `.svg` | vertical lockup, dark backgrounds |
| `filegrail-stacked-light.png` `.svg` | vertical lockup, light backgrounds |
| `filegrail-logo-dark.png` `.svg` | horizontal lockup, dark backgrounds |
| `filegrail-logo-light.png` `.svg` | horizontal lockup, light backgrounds |
| `filegrail-logo-light-accent.png` `.svg`, `filegrail-stacked-light-accent.png` `.svg`, `filegrail-stacked-compact-light-accent.png` `.svg` | the lockups for light backgrounds with the mark in verdigris, outlined |
| `filegrail-mark.svg`, `filegrail-mark-verdigris.png` `.svg` | mark alone in verdigris, on any background |
| `filegrail-mark-outline.png` `.svg` | mark in verdigris, outlined, light backgrounds |
| `filegrail-mark-soft.png` `.svg` | mark in soft ink, light backgrounds |
| `filegrail-mark-ivory.png` `.svg`, `filegrail-mark-ink.png` `.svg` | mark in one colour |
| `filegrail-mark-brass`, `-cobalt`, `-iris`, `-moss`, `-oxblood`, `-steel` `.png` `.svg` | mark in the other colours of the set |
| `filegrail-wordmark-onlight.svg`, `-ondark.svg` | the name alone, set as text in the system sans-serif font, light and dark backgrounds |
| `filegrail-how-it-works-onlight.svg`, `-ondark.svg` | the README's "How it works" figure, both drawn by `tools/build_readme_diagram.py` |

Minimum height for the mark is 16 px, and clear space around it is half its height.
