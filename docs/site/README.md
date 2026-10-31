# Website (GitHub Pages)

The project website is [docs/index.html](../index.html), published by GitHub Pages from the `main` branch, `/docs` folder, at <https://milochen0418.github.io/re_ddns/>.

| File | What it is |
|------|------------|
| `docs/index.html` | The page. English and Traditional Chinese sit side by side (`lang="en"` / `lang="zh-Hant"` elements) and the language button shows one of them. Icons are inlined SVGs. |
| `docs/.nojekyll` | Tells GitHub Pages to serve the folder as it is, without Jekyll. |
| `docs/site/site.css` | Styles. |
| `docs/site/site.js` | Language switch, the app list (filters, search), the video list (`VIDEOS`), the videos of each app (`APP_VIDEOS`) and the dialog that plays them. |
| `docs/site/apps.js` | The app list, generated from `data/appstore_catalog.json`. Do not edit it by hand. |
| `docs/site/update_apps.py` | Writes `apps.js`. |
| `docs/site/img/` | Screenshots (WebP), `og.jpg` (the 1200×630 link preview on Facebook and elsewhere), `apple-touch-icon.png`. |
| `docs/site/img/apps/<subdomain>.webp` | The picture on each app card. |
| `docs/site/icons/` | The Lucide icons the catalog names, plus brand icons; licences in `LICENSE.txt`. |

## After you change the catalog

```bash
python3 docs/site/update_apps.py           # rewrite docs/site/apps.js
python3 docs/site/update_apps.py --check   # exit 1 if apps.js is out of date
```

For a new app:

- **Picture**: save a screenshot as `docs/site/img/apps/<subdomain>.webp`, 16:10 and about 1280 px wide; the card shows its top part. Without one, the card shows the app's icon.

  ```bash
  cwebp -q 80 -resize 1280 0 shot.png -o docs/site/img/apps/<subdomain>.webp
  ```

- **Icon**: the Lucide icon named in the catalog must be in `docs/site/icons/`. When it is missing, the script says so and prints the `curl` command that fetches it.
- **Group**: add the subdomain to `CATEGORIES` in `update_apps.py`, or it lands in "Media and tools". The AI tag comes from a description that mentions AI, LLM, Ollama or Claude, or from `AI_EXTRA`.

## Videos

Edit `VIDEOS` in `site.js`: the YouTube id per language (`en`, and `zh` when there is a Chinese version), the length, and a title and one-line description in both languages. The card shows YouTube's thumbnail; when that one does not read well, set `img` to a 16:9 picture in `docs/site/img/videos/`. Videos load from youtube-nocookie.com only after a click.

### Videos on the app cards

`APP_VIDEOS` in `site.js` lists the videos about each app, by subdomain, the most direct one first: `["<English id>", <second to start at>]`. An app listed there gets a small YouTube icon on its card; an app that is not listed gets no icon.

- List a video only if it really shows the app, and check the start second on a frame of the video. Chinese versions use the same second, so check them too.
- A video that belongs on a card but not in the Videos section is a `VIDEOS` entry with `appOnly: true`.

The icon opens the video in a dialog, with the app's other videos in a list under the player. When YouTube reports that the video cannot play there, or its player script cannot load, the video opens in a new window; if the browser blocks that window, the dialog shows a link instead. A player that has not loaded after 12 seconds also shows the link. The dialog needs YouTube's player API for this, so after the click it also loads `iframe_api` from www.youtube.com.

## Preview

```bash
python3 -m http.server 8765 --directory docs    # then open http://localhost:8765
```

`?lang=en` or `?lang=zh` picks a language. Otherwise the browser's language decides, and a choice made with the button is remembered.

## Publish

Commit and push `docs/`. GitHub Pages (Settings › Pages: Deploy from a branch, `main`, `/docs`) updates the site a minute or two later.
