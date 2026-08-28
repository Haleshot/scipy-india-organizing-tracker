# Volunteer roles

These are the roles on the SciPy India 2026 volunteer sign-up form, and the
number of people who picked each. Most people picked more than one.

This is the only thing from that form that lives in the repository. No names,
no email addresses, no affiliations, no free-text answers, and nothing that
could identify an individual applicant. Nobody has been contacted yet, and the
counts below are what the organizing team needs in order to decide who to
contact first.

| Role | Sign-ups | What it covers |
| --- | ---: | --- |
| Registration & Help Desk | 19 | Check-in desks, badges, the queue, and answering questions all day. |
| Tutorial/Workshop Support | 19 | Running the workshop rooms, helping attendees with setup and prerequisites. |
| Session Room Management | 15 | Keeping talks on time, introducing speakers, running the mic. |
| Website | 15 | The conference site, schedule pages and ticketing integration. |
| Logistics | 12 | Venue, food, travel, accommodation and everything on the ground. |
| Social Media & Communications | 10 | Announcements, social posts, newsletters and community partners. |
| A/V & Tech Support | 8 | Sound, projection, recording and streaming during the conference. |
| Code of Conduct | 7 | The code of conduct, incident response, accessibility and inclusion. |
| Sponsoring | 6 | Sponsor prospectus, outreach, invoicing and sponsor deliverables. |
| Design | 4 | Logo work, badges, signage, merchandise and slide templates. |
| Content | 1 | Blog posts, speaker interviews and written material around the event. |
| Program Committee | 1 | Shaping the programme, the CFP timeline and the final schedule. |
| Proposal Reviewing | 1 | Reading and scoring CFP submissions. |

118 role selections across the form. The roles with one sign-up are not
less important, they are just harder to staff, and the ones with nineteen will
need a rota rather than a volunteer.

## Where this list lives

[`config/workgroups.yaml`](https://github.com/scipy-india/meeting-notes-graph/blob/main/config/workgroups.yaml)
is the source of truth. Nothing in the code hardcodes a role, so adding or
renaming one is an edit to that file followed by `./scripts/refresh.sh`.

Each entry also carries aliases, which is how a meeting note that says
"comms" or "AV" or "the website team" still lands on the right role. A name
that matches nothing is dropped rather than guessed at, so an unregistered
work area shows up as a gap instead of a wrong edge.

## Updating the counts

When the form has new responses, export it and run:

```bash
python scripts/summarise_signups.py ~/Downloads/"SciPy India 2026 Conference Planning.xlsx" --write
```

That reads one column, the roles question, and writes the counts back into
`config/workgroups.yaml`. It never copies the spreadsheet into the repository
and never prints anything from the other columns. A role on the form that has
no entry in the registry is reported by name so you can add it, because a
silently dropped role would look like nobody signed up.
