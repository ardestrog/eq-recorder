# resources/

`icon.icns` and `icon.png` are **generated** files; do not edit them
directly. The source is `assets/app_icon_source.png`; regenerate with:

```bash
./scripts/update_icon.sh
```

`fonts/` holds the Roboto Mono typeface (Apache-2.0, free to redistribute
with the app), loaded into the bundle through `ATSApplicationFontsPath` in
Info.plist (see `build_app.sh`). It is not generated.
