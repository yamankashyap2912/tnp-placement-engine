# The web application

One FastAPI process serves the JSON API (`/api/...`) and the website (`/`). The website is plain HTML, CSS and
JavaScript modules in `web/`: no build step, no node_modules, nothing to install beyond Python.

```
browser  --HTTP/JSON-->  FastAPI (src/tnp/api)  --pymysql-->  MySQL
  web/                    routes_core.py  auth, filters, overview, postings, students
  index.html              routes_ops.py   pipeline writes, early warning, ML jobs, insights, health, assistant
  assets/js, css, img     assistant.py    read-only question answering
                          security.py     scrypt password hashes + signed tokens (standard library)
                          deps.py         role checks, ownership checks, DB connections
```

## Reuse, not rewrite
Nothing from Phases 1-4 was re-implemented. The API calls what already existed:

| Page / feature | Reused piece |
|---|---|
| Shortlists | `sp_shortlist_for_posting`, `sp_shortlist_eligible_not_applied` |
| Student 360, My profile, Applications | `sp_student_application_summary` |
| Skill coach | `sp_skill_gap` |
| Early warning | `sp_early_warning` |
| Dashboard | views `v_branch_placement_summary`, `v_company_summary`, `sp_placement_report` |
| Apply, record round, withdraw | `sp_apply_to_posting`, `sp_record_round`, `sp_withdraw_application` (triggers do the rest) |
| ML insights and jobs | `tnp.match`, `tnp.placement`, `tnp.reports`, the Model_Runs table |
| Database health | `v_integrity_checks`, the catalogue views, `reports/index_benchmark.csv`, `docs/er_diagram.svg` |
| Ask the data | the `readonly_analyst` database account |

Four small procedures and two tables were added for the website (`sql/09_app_layer.sql`). On the front end the
same functions render the student's own pages and the officer's view of any student (`pages/mine.js`), and
`pages/common.js` holds the posting detail, requirement list and funnel used by five pages.

## Roles

| | TnP officer (`ADMIN`) | Recruiter | Student |
|---|---|---|---|
| Overview, dashboard, insights, database health, assistant | yes | | |
| Any shortlist, any posting, pipeline | yes | own company's postings only | |
| Student directory and 360 view | yes | | only themselves |
| Apply to a posting | on behalf of a student | | themselves |
| Record interview rounds | yes | own company's applications | |
| Open / close applications | yes | own postings | |
| Retrain / re-score / regenerate report | yes | | |

Sign-in: username and password. Students use their e-mail address. Demo passwords come from `.env` and are
listed on the login page while `TNP_DEMO_MODE=1`.

## Pages
Admin: Home, Dashboard, Shortlists, Students (+ Student 360), Postings and Companies, Early warning,
Pipeline desk, ML insights, Database health, Ask the data.
Recruiter: Home, Shortlists, Postings, Pipeline desk.
Student: Home, My matches, Skill coach, Applications, Profile.

Everything has a day and a night theme (moon icon in the rail), keyboard focus styles, dialogs that close with
Escape, and a phone layout (the rail becomes a bottom bar).

## Design system
Taken from the supplied template: a rounded frame floating on a textured grey stage; a pill-shaped top bar with
a section pill, a three-slot filter pill and a user pill; a vertical glass icon rail; very light display type
over a full-bleed scene; frosted cards with large radii; a dark circular badge. The scene (`hero.svg`) is an
original illustration, so no third-party image is used. Tokens live at the top of `web/assets/css/app.css`
(colours, radii, shadows); the day and night themes only redefine those variables.

## Extending
* New page: add `web/assets/js/pages/<name>.js` exporting `default async function (ctx)`, register it in `main.js`
  and in the `NAV` table of `shell.js`.
* New endpoint: add it to a router in `src/tnp/api/`, protect it with `require("ADMIN", ...)`, call a stored
  procedure, then run `python run.py api-reference`.
* New rule: put it in the database (trigger or constraint) so every client obeys it.

## Production checklist
1. Set a long random `TNP_SECRET`; set `TNP_DEMO_MODE=0`; change all demo passwords (or re-seed with your own
   values in `.env` and run `python run.py seed-users`).
2. Run behind HTTPS (nginx, Caddy or a platform proxy) and bind uvicorn to localhost.
3. Give the three application accounts strong passwords (`TNP_*_PASSWORD`) and restrict their host in
   `sql/08_security.sql` (`'localhost'` by default).
4. Schedule `scripts/backup.sh` and `python run.py worker` (cron / Task Scheduler).
5. Replace the dataset with real, anonymised records and retrain (`python run.py train`).
