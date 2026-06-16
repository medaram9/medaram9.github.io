# Naresh Medaram — Portfolio

Personal portfolio website for Naresh Medaram, Staff Infrastructure Engineer.

## Files

```
index.html   — Complete single-page site
style.css    — All styles (dark theme, responsive, CSS custom properties)
main.js      — Scroll animations, counters, hero canvas, mobile nav
README.md    — This file
Naresh_Medaram_Resume_Anthropic_StaffInfraEngineer.docx  — Resume (linked from site)
```

## Deploy to GitHub Pages

### Option A — Personal site (nareshmedaram.github.io)

1. Create a GitHub repo named exactly: `nareshmedaram.github.io`
2. Push all files to the `main` branch:
   ```bash
   git init
   git add .
   git commit -m "Initial portfolio deploy"
   git remote add origin https://github.com/medaram9/nareshmedaram.github.io.git
   git push -u origin main
   ```
3. GitHub Pages is **automatically enabled** for `*.github.io` repos.
4. Site live at: `https://nareshmedaram.github.io`

### Option B — Project page (nareshmedaram.github.io/portfolio)

1. Create any GitHub repo (e.g. `portfolio`)
2. Push files to `main` branch
3. Go to repo **Settings → Pages → Source**: `main` branch, `/` (root)
4. Site live at: `https://nareshmedaram.github.io/portfolio`

## Custom Domain (optional)

1. Create a `CNAME` file in the repo root containing your domain:
   ```
   nareshmedaram.com
   ```
2. In your DNS provider, add a CNAME record:
   - Host: `@` (or `www`)
   - Value: `nareshmedaram.github.io`
3. In repo Settings → Pages → Custom domain: enter your domain.
4. Enable "Enforce HTTPS" after DNS propagation.

## Update GitHub username in the site

In `index.html`, update the GitHub links from the placeholder:
```
https://github.com/medaram9
```
to your actual GitHub username if different.

## Before publishing — checklist

- [ ] Replace GitHub URL placeholder with your real GitHub profile
- [ ] Confirm the resume `.docx` file is in the same folder as `index.html`
- [ ] Test locally: open `index.html` in a browser — no build step required
- [ ] Test on mobile (responsive layout)
- [ ] Verify all links open correctly (email, LinkedIn, GitHub, resume download)
