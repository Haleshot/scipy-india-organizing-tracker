/**
 * SciPy India organizing dashboard.
 *
 * Reads one file, ./data/graph.json, the sanitized snapshot produced by
 * scripts/export_public_snapshot.py, and renders it. There is no build step
 * and no backend, and in particular no connection to the MCP server: that is a
 * separate consumer of the same graph, for a local agent, not for this page.
 *
 * Every URL here is relative and routing is done with the hash, so the site
 * behaves the same at https://example.github.io/repo/ as at http://localhost/.
 */

const DATA_URL = new URL('./data/graph.json', import.meta.url);
const OPEN_STATUSES = ['open', 'in_progress', 'blocked', 'unknown'];

const main = document.getElementById('main');
const searchInput = document.getElementById('search');
const searchHint = document.getElementById('search-hint');

let DATA = null;

/* ------------------------------------------------------------------ utils */

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    // Guards like `list.length && el(...)` yield 0 when the list is empty;
    // treat every falsy value as "render nothing".
    if (!child) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
};

const emptyNote = (text) => el('p', { class: 'empty', text });
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * A control bar whose inputs survive typing.
 *
 * Rebuilding the whole view on every keystroke replaces the input element, so
 * focus and the caret go with it and the field feels broken after one letter.
 * Controls are built once; only `results` is replaced as the filter changes.
 */
function filtered({ segments, active, onSegment, placeholder, query, onQuery, render }) {
  const results = el('div');
  const count = el('span', { class: 'count' });

  const paint = () => {
    const { nodes, shown, total, noun } = render();
    results.replaceChildren(nodes);
    count.textContent = shown === total ? `${plural(total, noun)}` : `${shown} of ${total} ${noun}s`;
  };

  const bar = el('div', { class: 'controls' },
    segments && el('div', { class: 'segmented' }, segments.map(([id, label]) =>
      el('button', {
        type: 'button', 'aria-pressed': String(id === active()),
        onclick: (event) => {
          onSegment(id);
          for (const button of bar.querySelectorAll('.segmented button')) {
            button.setAttribute('aria-pressed', String(button === event.currentTarget));
          }
          paint();
        },
      }, label))),
    el('input', {
      type: 'search', class: 'filter-field', placeholder, value: query(),
      oninput: (event) => { onQuery(event.target.value.trim().toLowerCase()); paint(); },
    }),
    count);

  paint();
  return el('div', {}, bar, results);
}
const wgName = (slug) => DATA.workgroups.find((w) => w.slug === slug)?.name ?? slug;
const isOpen = (task) => OPEN_STATUSES.includes(task.status);
const statusMark = (status) =>
  el('span', { class: `status status-${status}`, text: status.replace('_', ' ') });
const meetingById = (id) => DATA.meetings.find((m) => m.id === id);
const taskById = (id) => DATA.tasks.find((t) => t.id === id);
const personLink = (name) => el('a', { class: 'link', href: `#/people?focus=${encodeURIComponent(name)}` }, name);
const wgLink = (slug) => el('a', { class: 'link', href: `#/workgroups?focus=${encodeURIComponent(slug)}` }, wgName(slug));
const meetingLink = (id, label) => {
  const meeting = meetingById(id);
  if (!meeting) return el('span', { text: label ?? `meeting ${id}` });
  return el('a', { class: 'link', href: `#/meetings?focus=${id}` }, label ?? `${meeting.date} ${meeting.title}`);
};

const joinNodes = (items, render, separator = ', ') =>
  items.flatMap((item, i) => (i ? [separator, render(item)] : [render(item)]));

/** One figure in the at-a-glance line: label above, number below, no box. */
function tally(label, value, href, attention = false) {
  const number = href
    ? el('a', { class: 'link', href }, String(value))
    : document.createTextNode(String(value));
  return el('div', { class: attention && value > 0 ? 'attention' : null },
    el('dt', { text: label }),
    el('dd', {}, number));
}

/* Human-readable timestamps. The viewer's locale and timezone, because the
   organizing team is not all in one place. */
function formatTimestamp(iso) {
  if (!iso) return 'unknown';
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  // dateStyle/timeStyle cannot be combined with timeZoneName, so spell the
  // components out. The viewer's own locale and zone: the team is not all in
  // one place, and a UTC timestamp helps nobody read "is this stale?".
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  }).format(when);
}

const SOURCE_LABELS = {
  local: 'fixture notes',
  google_drive: 'Google Drive',
  unknown: 'unrecorded source',
};

const EXTRACTOR_LABELS = {
  markdown: 'parsed, not inferred',
  llm: 'LLM extraction',
  unknown: 'unrecorded extractor',
};

/* ---------------------------------------------------------- shared pieces */

const matchesText = (needle, ...parts) =>
  !needle || parts.filter(Boolean).join(' ').toLowerCase().includes(needle);

/**
 * "Seen in 3 meetings", expandable to the chronological list. A bare run of
 * dates told you a task recurred but not what happened at each one.
 */
function taskHistory(task) {
  if (!task.history?.length) return null;
  if (task.history.length === 1) {
    const only = task.history[0];
    return el('div', { class: 'meta' }, 'recorded ', meetingLink(only.id, only.date));
  }
  return el('details', {},
    el('summary', { text: `Seen in ${plural(task.history.length, 'meeting')}` }),
    el('ol', { class: 'timeline sub' }, task.history.map((entry, index) => {
      const previous = index ? task.history[index - 1].status : null;
      const moved = previous && previous !== entry.status;
      return el('li', {},
        el('span', { class: 'when' }, meetingLink(entry.id, entry.date)),
        statusMark(entry.status),
        el('span', { class: 'note' },
          index === 0 ? 'created here' : moved ? `changed from ${previous.replace('_', ' ')}` : 'no change'));
    })));
}

function taskItem(task) {
  return el('li', { id: `task-${task.id}` },
    el('div', { class: 'row' },
      el('span', { class: 'gutter' }, statusMark(task.status)),
      el('div', { class: 'body' },
        el('div', { class: 'title', text: task.description }),
        el('div', { class: 'meta' },
          task.workgroup ? wgLink(task.workgroup) : el('span', { text: 'no workgroup' }),
          task.owners.length
            ? el('span', {}, ...joinNodes(task.owners, personLink))
            : el('span', { class: 'unowned', text: 'nobody assigned' }),
          task.due && el('span', { text: `due ${task.due}` })),
        taskHistory(task))));
}

/* ----------------------------------------------------------------- views */

function viewOverview() {
  const s = DATA.summary;
  const openTasks = DATA.tasks.filter(isOpen);
  const unassigned = openTasks.filter((t) => t.owners.length === 0);
  const latest = DATA.meetings[0];
  const waiting = DATA.workgroups.reduce((total, w) => total + w.awaiting_assignment, 0);
  const signups = DATA.workgroups.reduce((total, w) => total + (w.signups ?? 0), 0);

  // A status memo opens with a sentence, not a row of tiles.
  const sentence = unassigned.length
    ? `${plural(s.open_tasks, 'action item')} still open, and ${unassigned.length} of them have nobody on them.`
    : `${plural(s.open_tasks, 'action item')} still open, all of them owned.`;

  const frag = el('div', {},
    el('h1', { text: 'Where things stand' }),
    el('p', { class: 'lead', text: sentence }),
    el('p', { class: 'lede' },
      `${plural(s.meetings, 'meeting')} recorded. `,
      s.people_withheld
        ? `${plural(s.people_listed, 'person', 'people')} named here; ${s.people_withheld} more applied to volunteer and are counted rather than named.`
        : `${plural(s.people_listed, 'person', 'people')} named here.`),
    el('dl', { class: 'tally' },
      tally('Open', s.open_tasks, '#/tasks'),
      tally('Unowned', s.unassigned_open_tasks, '#/tasks?filter=unassigned', true),
      tally('Volunteers waiting', waiting, '#/workgroups'),
      tally('Role sign-ups', signups, '#/workgroups'),
      tally('Decisions', s.decisions, null)),
  );

  if (latest) {
    const decisions = DATA.decisions.filter((d) => d.meetings.includes(latest.id));
    const touched = DATA.tasks.filter((t) => t.history?.some((h) => h.id === latest.id));
    const moved = touched.filter((t) => {
      const here = t.history.findIndex((h) => h.id === latest.id);
      return here > 0 && t.history[here - 1].status !== t.history[here].status;
    });
    frag.append(
      el('h2', { text: 'Latest meeting' }),
      el('h3', {}, meetingLink(latest.id, `${latest.date}  ${latest.title}`)),
      el('p', { class: 'lede' },
        latest.facilitator ? `Run by ${latest.facilitator}. ` : '',
        `${plural(decisions.length, 'decision')}, ${plural(touched.length, 'action item')} touched`,
        moved.length ? `, ${moved.length} of which changed status.` : '.'),
      decisions.length
        ? el('ul', { class: 'records' }, decisions.map((d) => el('li', {},
            el('div', { class: 'row' },
              el('span', { class: 'gutter meta', text: 'decided' }),
              el('div', { class: 'body' },
                el('div', { class: 'title', text: d.statement }),
                d.workgroup && el('div', { class: 'meta' }, wgLink(d.workgroup)))))))
        : emptyNote('No decisions recorded in that meeting.'),
    );
  }

  frag.append(
    el('h2', { text: 'Open work by volunteer role' }),
    workgroupTable(),
    el('h2', { text: 'Nobody assigned' }),
    unassigned.length
      ? el('ul', { class: 'records' }, unassigned.map(taskItem))
      : emptyNote('Everything open has an owner.'),
    el('h2', { text: 'Recent meetings' }),
    el('ul', { class: 'records' }, DATA.meetings.slice(0, 5).map(meetingRow)),
  );
  return frag;
}

function workgroupTable() {
  return el('div', { class: 'table-scroll' },
    el('table', {},
      el('thead', {}, el('tr', {},
        el('th', { text: 'Role' }),
        el('th', { class: 'num', text: 'Open' }),
        el('th', { class: 'num', text: 'Done' }),
        el('th', { class: 'num', text: 'On it' }),
        el('th', { class: 'num', title: 'Volunteers who asked for this role and have not been assigned to it' },
          'Waiting'),
        el('th', { class: 'num', title: 'People who picked this role on the sign-up form' },
          'Sign-ups'))),
      el('tbody', {}, DATA.workgroups.map((w) => {
        const done = DATA.tasks.filter((t) => t.workgroup === w.slug && t.status === 'done').length;
        const cell = (n) => el('td', { class: n ? 'num' : 'num zero', text: String(n) });
        return el('tr', {},
          el('td', {}, wgLink(w.slug)),
          cell(w.open_tasks), cell(done), cell(w.member_count),
          cell(w.awaiting_assignment), cell(w.signups ?? 0));
      })),
      el('tfoot', {}, el('tr', {},
        el('td', { text: 'Total' }),
        el('td', { class: 'num', text: String(DATA.workgroups.reduce((t, w) => t + w.open_tasks, 0)) }),
        el('td', { class: 'num', text: String(DATA.tasks.filter((t) => t.status === 'done').length) }),
        el('td', { class: 'num', text: String(DATA.workgroups.reduce((t, w) => t + w.member_count, 0)) }),
        el('td', { class: 'num', text: String(DATA.workgroups.reduce((t, w) => t + w.awaiting_assignment, 0)) }),
        el('td', { class: 'num', text: String(DATA.workgroups.reduce((t, w) => t + (w.signups ?? 0), 0)) })))));
}

/* --------------------------------------------------------------- meetings */

let meetingFilter = '';

function meetingRow(meeting) {
  const tasks = DATA.tasks.filter((t) => t.history?.some((h) => h.id === meeting.id));
  return el('li', {},
    el('div', { class: 'row' },
      el('span', { class: 'gutter muted', text: meeting.date }),
      el('div', { class: 'body' },
        el('div', { class: 'title' }, meetingLink(meeting.id, meeting.title)),
        el('div', { class: 'meta' },
          meeting.facilitator && el('span', { text: `run by ${meeting.facilitator}` }),
          el('span', { text: plural(meeting.attendees.length, 'attendee') }),
          el('span', { text: plural(tasks.length, 'action item') })))));
}

/** A field list, so the facilitator and the workgroups cannot run together. */
function fields(...pairs) {
  const rows = pairs.filter(([, value]) => value !== null && value !== undefined && value !== '' &&
    !(Array.isArray(value) && value.length === 0));
  if (!rows.length) return null;
  return el('dl', { class: 'fields' }, rows.flatMap(([label, value]) => [
    el('dt', { text: label }),
    el('dd', {}, Array.isArray(value) ? value : [value]),
  ]));
}

function meetingDetail(meeting) {
  const tasks = DATA.tasks.filter((t) => t.history?.some((h) => h.id === meeting.id));
  const decisions = DATA.decisions.filter((d) => d.meetings.includes(meeting.id));
  return el('li', { id: `meeting-${meeting.id}` },
    el('h3', { text: `${meeting.date}  ${meeting.title}` }),
    fields(
      ['Facilitator', meeting.facilitator ? personLink(meeting.facilitator) : 'not recorded'],
      ['Workgroups', joinNodes(meeting.workgroups, wgLink)],
      ['Topics', meeting.topics.join('; ')],
      ['Attendees', joinNodes(meeting.attendees, personLink)]),
    decisions.length ? el('details', {},
      el('summary', { text: plural(decisions.length, 'decision') }),
      el('ul', { class: 'sub' }, decisions.map((d) => el('li', {},
        d.statement, d.workgroup && el('span', { class: 'meta' }, ' ', wgLink(d.workgroup)))))) : null,
    tasks.length ? el('details', {},
      el('summary', { text: plural(tasks.length, 'action item') }),
      el('ul', { class: 'records sub' }, tasks.map(taskItem))) : null);
}

function viewMeetings(params) {
  return el('div', {},
    el('h1', { text: 'Meetings' }),
    filtered({
      placeholder: 'Filter by title, topic or attendee',
      query: () => meetingFilter,
      onQuery: (value) => { meetingFilter = value; },
      render: () => {
        const list = DATA.meetings.filter((m) => matchesText(meetingFilter, m.title, m.summary,
          m.topics.join(' '), m.attendees.join(' '), m.facilitator));
        return {
          nodes: list.length
            ? el('ul', { class: 'records' }, list.map(meetingDetail))
            : emptyNote('No meetings match.'),
          shown: list.length, total: DATA.meetings.length, noun: 'meeting',
        };
      },
    }),
    focusScroller(params, 'meeting'));
}

/* ------------------------------------------------------------------ tasks */

let taskFilter = 'open';
let taskSearch = '';

const TASK_FILTERS = [
  ['open', 'Open', (t) => isOpen(t)],
  ['unassigned', 'No owner', (t) => isOpen(t) && t.owners.length === 0],
  ['recurring', 'Recurring', (t) => t.meeting_count > 1],
  ['done', 'Done', (t) => t.status === 'done'],
  ['all', 'All', () => true],
];

function viewTasks(params) {
  if (params.get('filter') && TASK_FILTERS.some(([id]) => id === params.get('filter'))) {
    taskFilter = params.get('filter');
  }
  return el('div', {},
    el('h1', { text: 'Action items' }),
    filtered({
      segments: TASK_FILTERS.map(([id, label]) => [id, label]),
      active: () => taskFilter,
      onSegment: (id) => { taskFilter = id; },
      placeholder: 'Filter by text, owner or workgroup',
      query: () => taskSearch,
      onQuery: (value) => { taskSearch = value; },
      render: () => {
        const active = TASK_FILTERS.find(([id]) => id === taskFilter) ?? TASK_FILTERS[0];
        const list = DATA.tasks.filter(active[2]).filter((t) => matchesText(taskSearch,
          t.description, t.owners.join(' '), t.workgroup && wgName(t.workgroup), t.due));
        return {
          nodes: list.length
            ? el('ul', { class: 'records' }, list.map(taskItem))
            : emptyNote('Nothing matches.'),
          shown: list.length, total: DATA.tasks.length, noun: 'action item',
        };
      },
    }),
    focusScroller(params, 'task'));
}

/* ----------------------------------------------------------------- people */

let peopleFilter = '';

function personDetail(person) {
  const owned = DATA.tasks.filter((t) => t.owners.includes(person.name));
  const open = owned.filter(isOpen);
  // Availability and skills come from a volunteer application, so the public
  // snapshot does not carry them. The organizer profile does.
  return el('li', { id: `person-${cssId(person.name)}` },
    el('h3', {}, person.name, person.is_volunteer && el('span', { class: 'meta', text: '  volunteer' })),
    fields(
      ['Workgroups', person.workgroups.length ? joinNodes(person.workgroups, wgLink) : 'none yet'],
      ['Meetings', String(person.meetings.length)],
      ['Action items', `${open.length} open of ${owned.length}`],
      ['Available', person.availability ?? ''],
      ['Skills', (person.skills ?? []).join(', ')]),
    open.length ? el('details', {},
      el('summary', { text: 'Open action items' }),
      el('ul', { class: 'records sub' }, open.map(taskItem))) : null);
}

function viewPeople(params) {
  const withheld = DATA.summary.people_withheld;
  return el('div', {},
    el('h1', { text: 'People' }),
    el('p', { class: 'lede' },
      'Everyone here has a role in the graph: they ran or attended a meeting, own an action item, or sit on a workgroup. ',
      withheld
        ? `${plural(withheld, 'other person', 'other people')} applied to volunteer and ${withheld === 1 ? 'is' : 'are'} counted per workgroup rather than named.`
        : 'Nobody is withheld from this view.',
      DATA.profile === 'organizer'
        ? ' This is the organizer export, so it also carries availability and skills.'
        : ''),
    filtered({
      placeholder: 'Filter by name, workgroup or skill',
      query: () => peopleFilter,
      onQuery: (value) => { peopleFilter = value; },
      render: () => {
        const list = DATA.people.filter((p) => matchesText(peopleFilter, p.name,
          p.workgroups.map(wgName).join(' '), (p.skills ?? []).join(' '),
          (p.interests ?? []).join(' ')));
        return {
          nodes: list.length
            ? el('ul', { class: 'records' }, list.map(personDetail))
            : emptyNote('Nobody matches.'),
          shown: list.length, total: DATA.people.length, noun: 'person',
        };
      },
    }),
    focusScroller(params, 'person'));
}

/* ------------------------------------------------------------- workgroups */

let workgroupFilter = '';

function workgroupDetail(workgroup) {
  const people = DATA.people.filter((p) => p.workgroups.includes(workgroup.slug));
  const tasks = DATA.tasks.filter((t) => t.workgroup === workgroup.slug);
  const open = tasks.filter(isOpen);
  const decisions = DATA.decisions.filter((d) => d.workgroup === workgroup.slug);
  return el('li', { id: `workgroup-${workgroup.slug}` },
    el('h3', { text: workgroup.name }),
    el('div', { class: 'muted', text: workgroup.description }),
    fields(
      ['Members', people.length
        ? joinNodes(people, (p) => personLink(p.name))
        : el('span', { class: 'unowned', text: 'nobody assigned yet' })],
      ['Sign-ups', workgroup.signups ? `${workgroup.signups} on the form` : ''],
      ['Action items', `${open.length} open of ${tasks.length}`],
      ['Waiting', workgroup.awaiting_assignment > 0
        ? `${plural(workgroup.awaiting_assignment, 'volunteer')} asked for this role and ${workgroup.awaiting_assignment === 1 ? 'has' : 'have'} not been assigned to it`
        : '']),
    open.length ? el('details', {},
      el('summary', { text: 'Open action items' }),
      el('ul', { class: 'records sub' }, open.map(taskItem))) : null,
    decisions.length ? el('details', {},
      el('summary', { text: plural(decisions.length, 'decision') }),
      el('ul', { class: 'sub' }, decisions.map((d) => el('li', {},
        d.statement,
        el('div', { class: 'meta' }, ...joinNodes(d.meetings, (id) => meetingLink(id))))))) : null);
}

function viewWorkgroups(params) {
  return el('div', {},
    el('h1', { text: 'Volunteer roles' }),
    el('p', { class: 'lede' },
      'These are the roles on the volunteer sign-up form. Sign-ups are how many people picked each one; ',
      'nothing else from that form is published here.'),
    filtered({
      placeholder: 'Filter roles',
      query: () => workgroupFilter,
      onQuery: (value) => { workgroupFilter = value; },
      render: () => {
        const list = DATA.workgroups.filter((w) => matchesText(workgroupFilter, w.name, w.description, w.slug));
        return {
          nodes: list.length
            ? el('ul', { class: 'records' }, list.map(workgroupDetail))
            : emptyNote('No role matches.'),
          shown: list.length, total: DATA.workgroups.length, noun: 'role',
        };
      },
    }),
    focusScroller(params, 'workgroup'));
}

/* --------------------------------------------------------- global search */

function globalSearch(query) {
  const needle = query.toLowerCase();
  const hit = (...parts) => matchesText(needle, ...parts);
  return {
    meetings: DATA.meetings.filter((m) => hit(m.title, m.summary, m.topics.join(' '), m.facilitator, m.attendees.join(' '))),
    tasks: DATA.tasks.filter((t) => hit(t.description, t.owners.join(' '), t.workgroup && wgName(t.workgroup), t.due)),
    people: DATA.people.filter((p) => hit(p.name, p.workgroups.map(wgName).join(' '),
      (p.skills ?? []).join(' '), (p.interests ?? []).join(' '))),
    workgroups: DATA.workgroups.filter((w) => hit(w.name, w.description, w.slug)),
    decisions: DATA.decisions.filter((d) => hit(d.statement, d.workgroup && wgName(d.workgroup))),
  };
}

function viewSearch(params) {
  const query = params.get('q') ?? '';
  if (!query.trim()) {
    return el('div', {},
      el('h1', { text: 'Search' }),
      emptyNote('Type in the box above to search meetings, action items, people, workgroups and decisions.'));
  }
  const results = globalSearch(query);
  const total = Object.values(results).reduce((sum, list) => sum + list.length, 0);

  const row = (gutter, title, meta) => el('li', {},
    el('div', { class: 'row' },
      el('span', { class: 'gutter muted' }, gutter),
      el('div', { class: 'body' },
        el('div', { class: 'title' }, title),
        meta && el('div', { class: 'meta' }, meta))));

  const groups = [
    ['Meetings', results.meetings, (m) =>
      row(m.date, meetingLink(m.id, m.title), m.summary || null)],
    ['Action items', results.tasks, (t) =>
      row(statusMark(t.status),
        el('a', { class: 'link', href: `#/tasks?filter=all&focus=${encodeURIComponent(t.id)}` }, t.description),
        el('span', {},
          t.workgroup ? wgLink(t.workgroup) : el('span', { text: 'no workgroup' }),
          el('span', { text: ' · ' }),
          t.owners.length ? t.owners.join(', ') : el('span', { class: 'unowned', text: 'nobody assigned' })))],
    ['People', results.people, (p) =>
      row('person', personLink(p.name), p.workgroups.map(wgName).join(', ') || 'no workgroup')],
    ['Workgroups', results.workgroups, (w) =>
      row('workgroup', wgLink(w.slug), w.description)],
    ['Decisions', results.decisions, (d) =>
      row('decided', d.statement,
        el('span', {}, ...joinNodes(d.meetings, (id) => meetingLink(id))))],
  ].filter(([, list]) => list.length);

  return el('div', {},
    el('h1', {}, 'Search: ', el('em', { text: query })),
    el('p', { class: 'lede', text: `${total} ${total === 1 ? 'match' : 'matches'} across the graph.` }),
    groups.length
      ? el('div', {}, groups.map(([label, list, draw]) => el('section', {},
          el('h2', { text: `${label} (${list.length})` }),
          el('ul', { class: 'records' }, list.slice(0, 25).map(draw)),
          list.length > 25 && el('p', { class: 'muted', text: `${list.length - 25} more not shown.` }))))
      : emptyNote('Nothing matches anywhere in the graph.'));
}

/* -------------------------------------------------------------- explorer */

/*
 * Node colours come from the SciPy logo: blue #0054a6, green #009b42, amber
 * #eeb54d and grey #666666, darkened where they need to hold up on white. Five
 * arbitrary hues is how a legend ends up violet and pink for no reason, so the
 * fifth category is told apart by shape instead of a fifth colour.
 */
const KIND_STYLE = {
  person: { color: '#0054a6', dark: '#5f9fe8', shape: 'ellipse' },
  workgroup: { color: '#007a34', dark: '#4aab72', shape: 'ellipse' },
  meeting: { color: '#5b6570', dark: '#98a3ae', shape: 'round-rectangle' },
  task: { color: '#8a5d05', dark: '#d0a14e', shape: 'ellipse' },
  decision: { color: '#5b6570', dark: '#98a3ae', shape: 'diamond' },
};

const darkMode = () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
const kindColor = (kind) => {
  const style = KIND_STYLE[kind];
  if (!style) return '#8a8f96';
  return darkMode() ? style.dark : style.color;
};

const explorerState = {
  // Workgroups and people first. Meetings, tasks and decisions are what make
  // the whole-graph view unreadable, and they are one toggle away.
  kinds: new Set(['person', 'workgroup']),
  focus: null,   // node id the neighbourhood is drawn around
  hops: 1,
  query: '',
};

let cyInstance = null;

function viewExplorer(params) {
  if (params.get('focus')) explorerState.focus = params.get('focus');
  const container = el('div', { id: 'cy' });
  const details = el('aside', { class: 'detail' });
  const picker = el('div', { class: 'picker' });

  // The controls people reach for stay in the bar. The ones they set once live
  // under Display, so a narrow screen is not a wall of buttons.
  const hopsButton = el('button', {
    type: 'button', title: 'How far from the focused node to draw',
    onclick: () => {
      explorerState.hops = explorerState.hops === 1 ? 2 : 1;
      hopsButton.textContent = `${explorerState.hops} hop${explorerState.hops > 1 ? 's' : ''}`;
      mountCytoscape(container, details);
    },
  }, `${explorerState.hops} hop${explorerState.hops > 1 ? 's' : ''}`);

  const searchField = el('input', {
    type: 'search', class: 'filter-field', placeholder: 'Find a person or workgroup',
    value: explorerState.query,
    oninput: (event) => { explorerState.query = event.target.value; renderPicker(picker, container, details); },
  });

  const stage = el('div', { class: 'stage' }, container);

  const fullscreenButton = el('button', {
    type: 'button',
    title: 'Fill the window with the graph',
    onclick: () => toggleFullscreen(stage, fullscreenButton),
  }, 'Fullscreen');

  const controls = el('div', { class: 'controls' },
    searchField,
    el('div', { class: 'segmented' },
      el('button', {
        type: 'button',
        onclick: () => {
          if (cyInstance && !cyInstance.destroyed()) { cyInstance.fit(undefined, 30); cyInstance.center(); }
        },
      }, 'Fit'),
      fullscreenButton,
      el('button', {
        type: 'button',
        onclick: () => {
          explorerState.focus = null;
          explorerState.query = '';
          searchField.value = '';
          picker.replaceChildren();
          mountCytoscape(container, details);
        },
      }, 'Whole graph')));

  const display = el('details', { class: 'display' },
    el('summary', { text: 'Display' }),
    el('div', { class: 'controls' },
      el('div', { class: 'segmented' },
        Object.keys(KIND_STYLE).map((kind) =>
          el('button', {
            type: 'button', 'aria-pressed': String(explorerState.kinds.has(kind)),
            onclick: (event) => {
              const on = explorerState.kinds.has(kind);
              on ? explorerState.kinds.delete(kind) : explorerState.kinds.add(kind);
              event.currentTarget.setAttribute('aria-pressed', String(!on));
              mountCytoscape(container, details);
            },
          }, kind))),
      el('div', { class: 'segmented' }, hopsButton),
      el('div', { class: 'legend' }, Object.keys(KIND_STYLE).map((kind) =>
        el('span', {}, el('i', { style: `background:${kindColor(kind)}` }), kind)))));

  const frag = el('div', {},
    el('h1', { text: 'Explorer' }),
    el('p', { class: 'lede', text: 'Pick a person or workgroup to see what it connects to. The whole graph is available, but the neighbourhood of one thing is usually what you came for. Detail goes in the panel beside it so the drawing can stay readable.' }),
    controls,
    display,
    picker,
    el('div', { class: 'explorer' }, stage, details));

  renderPicker(picker, container, details, { skipMount: true });
  queueMicrotask(() => mountCytoscape(container, details));
  return frag;
}

function renderPicker(picker, container, details, { skipMount = false } = {}) {
  const query = explorerState.query.trim().toLowerCase();
  if (!query) {
    picker.replaceChildren();
    if (!skipMount) mountCytoscape(container, details);
    return;
  }
  const matches = DATA.graph.nodes
    .filter((node) => node.label.toLowerCase().includes(query))
    .slice(0, 12);
  picker.replaceChildren(
    el('div', { class: 'picker-label', text: 'Search results' }),
    matches.length
      ? el('div', { class: 'segmented wrap' }, matches.slice(0, 6).map((node) =>
          el('button', {
            type: 'button', 'aria-pressed': String(explorerState.focus === node.id),
            onclick: () => {
              explorerState.focus = node.id;
              mountCytoscape(container, details);
            },
          }, truncate(node.label, 30))))
      : emptyNote('No node matches.'));
}

/** Nodes within `hops` of the focus, plus the focus itself. */
function neighbourhood(focusId, hops, visibleKinds) {
  const byId = new Map(DATA.graph.nodes.map((n) => [n.id, n]));
  if (!byId.has(focusId)) return null;
  const keep = new Set([focusId]);
  let frontier = new Set([focusId]);
  for (let hop = 0; hop < hops; hop += 1) {
    const next = new Set();
    for (const edge of DATA.graph.edges) {
      if (frontier.has(edge.source) && !keep.has(edge.target)) next.add(edge.target);
      if (frontier.has(edge.target) && !keep.has(edge.source)) next.add(edge.source);
    }
    for (const id of next) keep.add(id);
    frontier = next;
  }
  // The focus is always drawn even if its own kind is toggled off.
  return DATA.graph.nodes.filter((n) => keep.has(n.id) && (n.id === focusId || visibleKinds.has(n.kind)));
}

function mountCytoscape(container, details) {
  if (typeof cytoscape === 'undefined') {
    details.replaceChildren(emptyNote('Cytoscape did not load, so the explorer is unavailable. Every other view works without it.'));
    return;
  }
  const focused = explorerState.focus
    ? neighbourhood(explorerState.focus, explorerState.hops, explorerState.kinds)
    : null;
  const nodes = focused ?? DATA.graph.nodes.filter((n) => explorerState.kinds.has(n.kind));
  const visible = new Set(nodes.map((n) => n.id));
  const edges = DATA.graph.edges.filter((e) => visible.has(e.source) && visible.has(e.target));

  if (!nodes.length) {
    container.replaceChildren(emptyNote('Every node type is switched off.'));
    return;
  }

  const ink = getComputedStyle(document.body).color;
  const paper = getComputedStyle(document.body).backgroundColor;
  // Meetings, tasks and decisions are coloured dots until you select one. Their
  // text is long, it overlaps, and the panel beside the graph is a better place
  // to read it. People and workgroups keep their labels because those are what
  // you navigate by.
  const alwaysLabelled = new Set(['person', 'workgroup']);

  // Tear the previous instance down first. Without this the old one keeps its
  // handlers and its pending layout callback, which then fires against a
  // container that is no longer in the document.
  cyInstance?.destroy();

  const cy = cytoscape({
    container,
    elements: [
      ...nodes.map((n) => ({ data: { id: n.id, label: n.label, kind: n.kind } })),
      ...edges.map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target, label: e.kind } })),
    ],
    style: [
      { selector: 'node', style: {
        'background-color': (n) => kindColor(n.data('kind')),
        shape: (n) => KIND_STYLE[n.data('kind')]?.shape ?? 'ellipse',
        label: (n) => (alwaysLabelled.has(n.data('kind')) || n.hasClass('named')
          ? truncate(n.data('label'), 26) : ''),
        'font-size': 9, color: ink,
        'text-valign': 'bottom', 'text-margin-y': 5, 'text-wrap': 'wrap', 'text-max-width': '78px',
        'text-background-color': paper, 'text-background-opacity': 0.7, 'text-background-padding': 1,
        width: 12, height: 12,
      } },
      { selector: 'node[kind="workgroup"]', style: { width: 26, height: 26, 'font-size': 10, 'font-weight': 600, 'text-max-width': '120px', 'z-index': 10 } },
      { selector: 'node[kind="person"]', style: { width: 18, height: 18, 'z-index': 9 } },
      { selector: 'node.focus', style: { 'border-width': 4, 'border-color': '#f59e0b', 'z-index': 20 } },
      { selector: 'node.named', style: { 'z-index': 30 } },
      { selector: 'edge', style: {
        width: 1, 'line-color': '#9aa2ad', 'target-arrow-color': '#9aa2ad',
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.6, opacity: 0.4,
      } },
      { selector: '.faded', style: { opacity: 0.07 } },
      { selector: '.highlight', style: { opacity: 1, 'border-width': 3, 'border-color': '#f59e0b' } },
    ],
    layout: { name: 'preset' },
    wheelSensitivity: 0.25,
    // Without a cap, fitting a small neighbourhood zooms in far enough that
    // the labels render as headlines. Users can still zoom past this by hand.
    maxZoom: 1.6,
    minZoom: 0.15,
  });
  cyInstance = cy;

  // Lay out only once the container has been painted. Running cose at
  // construction time gives cytoscape a zero-sized viewport and the graph ends
  // up as a speck in the corner.
  requestAnimationFrame(() => {
    // The user may have navigated away in the frame between mounting and this
    // callback; a destroyed instance throws on every method.
    if (cy.destroyed() || !container.isConnected) return;
    cy.resize();
    const dense = nodes.length > 24;
    cy.layout({
      name: 'cose',
      animate: false,
      padding: 32,
      fit: true,
      // A dozen nodes want space to breathe; sixty want to be pulled together
      // enough to fit the box without shrinking the labels to nothing.
      nodeRepulsion: dense ? 26000 : 11000,
      idealEdgeLength: dense ? 150 : 85,
      nodeOverlap: dense ? 36 : 18,
      gravity: dense ? 28 : 70,
      numIter: 1500,
      randomize: false,
      // Lay out around the labels, not the dots. Without this the circles are
      // nicely spaced and the words on top of them collide.
      nodeDimensionsIncludeLabels: true,
      stop: () => {
        if (cy.destroyed()) return;
        cy.fit(undefined, 32);
        cy.center();
      },
    }).run();
  });

  // Name a node while it is selected or hovered, and only then.
  cy.on('tap', 'node', (event) => {
    cy.nodes().removeClass('named');
    event.target.addClass('named');
    selectNode(cy, event.target, details, container);
  });
  cy.on('mouseover', 'node', (event) => event.target.addClass('named'));
  cy.on('mouseout', 'node', (event) => {
    if (!event.target.hasClass('highlight') && !event.target.hasClass('focus')) {
      event.target.removeClass('named');
    }
  });
  cy.on('tap', (event) => {
    if (event.target === cy) {
      cy.elements().removeClass('faded').removeClass('highlight').removeClass('named');
      showPanelPlaceholder(details);
    }
  });

  if (explorerState.focus && cy.$id(explorerState.focus).length) {
    const node = cy.$id(explorerState.focus);
    node.addClass('focus').addClass('named');
    selectNode(cy, node, details, container, { dim: false });
  } else {
    showPanelPlaceholder(details);
  }
}

function showPanelPlaceholder(details) {
  details.replaceChildren(
    el('p', { class: 'muted', text: 'Nothing selected. Click a node, or search above to focus on one.' }));
}

function selectNode(cy, node, details, container, { dim = true } = {}) {
  if (dim) {
    cy.elements().addClass('faded').removeClass('highlight');
    node.closedNeighborhood().removeClass('faded');
    node.addClass('highlight');
  }
  details.replaceChildren(nodeDetails(node, cy, details, container));
}

/** Append only the blocks that exist. `Element.append(null)` inserts the
 *  literal text "null", which is how a stray one shows up in the panel. */
const add = (parent, ...blocks) => parent.append(...blocks.filter(Boolean));

/** A titled block of lines. Not a card: a heading and a list, like a record. */
function block(heading, items, empty = null) {
  if (!items.length) return empty ? el('section', {}, el('h4', { text: heading }), el('p', { class: 'muted', text: empty })) : null;
  return el('section', {},
    el('h4', { text: heading }),
    el('ul', {}, items.map((item) => el('li', {}, item))));
}

/**
 * The panel does the explaining. A person reads workgroups, then open work,
 * then meetings; a workgroup reads members, then waiting volunteers, then open
 * work, then decisions and where they came from.
 */
function nodeDetails(node, cy, details, container) {
  const [kind, ...rest] = node.id().split(':');
  const key = rest.join(':');
  const panel = el('div', {},
    el('div', { class: 'picker-label', text: 'Selected' }),
    el('h3', { text: node.data('label') }),
    el('div', { class: 'kind', text: kind }),
    el('div', { class: 'controls' }, el('div', { class: 'segmented' },
      el('button', {
        type: 'button',
        onclick: () => { explorerState.focus = node.id(); mountCytoscape(container, details); },
      }, 'Focus'),
      el('button', {
        type: 'button',
        onclick: () => {
          explorerState.hops = 2;
          explorerState.focus = node.id();
          mountCytoscape(container, details);
        },
      }, 'Two hops'))));

  if (kind === 'person') {
    const person = DATA.people.find((p) => p.name === key);
    if (person) {
      const owned = DATA.tasks.filter((t) => t.owners.includes(person.name));
      add(panel, 
        block('Workgroups', person.workgroups.map(wgLink), 'none yet'),
        block('Open work', owned.filter(isOpen).map((t) =>
          el('span', {}, t.description, ' ', statusMark(t.status))), 'nothing open'),
        block('Meetings', person.meetings.slice(0, 8).map((id) => meetingLink(id))),
        person.skills?.length ? block('Skills', [person.skills.join(', ')]) : null,
        person.availability ? block('Available', [person.availability]) : null);
      return panel;
    }
  }

  if (kind === 'workgroup') {
    const workgroup = DATA.workgroups.find((w) => w.slug === key);
    if (workgroup) {
      const members = DATA.people.filter((p) => p.workgroups.includes(key));
      const open = DATA.tasks.filter((t) => t.workgroup === key && isOpen(t));
      const decisions = DATA.decisions.filter((d) => d.workgroup === key);
      const meetings = DATA.meetings.filter((m) => m.workgroups.includes(key));
      add(panel, 
        el('p', { class: 'muted', text: workgroup.description }),
        block('Members', members.map((p) => personLink(p.name)), 'nobody assigned yet'),
        workgroup.awaiting_assignment
          ? block('Waiting', [`${plural(workgroup.awaiting_assignment, 'volunteer')} asked and not yet assigned`])
          : null,
        block('Open work', open.map((t) => el('span', {},
          t.description, ' ', statusMark(t.status), ' ',
          t.owners.length
            ? el('span', { class: 'meta', text: t.owners.join(', ') })
            : el('span', { class: 'unowned', text: 'nobody assigned' }))), 'nothing open'),
        block('Recent decisions', decisions.slice(0, 4).map((d) => d.statement)),
        block('Discussed in', meetings.slice(0, 6).map((m) => meetingLink(m.id, m.date))));
      return panel;
    }
  }

  if (kind === 'meeting') {
    const meeting = meetingById(Number(key));
    if (meeting) {
      const tasks = DATA.tasks.filter((t) => t.history?.some((h) => h.id === meeting.id));
      add(panel, 
        block('Date', [meeting.date]),
        block('Facilitator', [meeting.facilitator ? personLink(meeting.facilitator) : 'not recorded']),
        block('Workgroups', meeting.workgroups.map(wgLink)),
        block('Topics', meeting.topics),
        block('Attendees', meeting.attendees.map(personLink)),
        block('Action items touched', tasks.slice(0, 8).map((t) =>
          el('span', {}, t.description, ' ', statusMark(t.status)))));
      return panel;
    }
  }

  if (kind === 'task') {
    const task = taskById(key);
    if (task) {
      add(panel, 
        block('Status', [statusMark(task.status)]),
        block('Workgroup', [task.workgroup ? wgLink(task.workgroup) : 'none']),
        block('Owners', [task.owners.join(', ') || el('span', { class: 'unowned', text: 'nobody assigned' })]),
        task.due ? block('Due', [task.due]) : null,
        block('History', (task.history ?? []).map((entry) =>
          el('span', {}, meetingLink(entry.id, entry.date), ' ', statusMark(entry.status)))));
      return panel;
    }
  }

  const grouped = new Map();
  node.connectedEdges().forEach((edge) => {
    const other = edge.source().id() === node.id() ? edge.target() : edge.source();
    const label = edge.data('label');
    if (!grouped.has(label)) grouped.set(label, []);
    grouped.get(label).push(other);
  });
  for (const [label, others] of grouped) {
    add(panel, block(label.replace(/_/g, ' ').toLowerCase(), others.map((other) =>
      el('a', {
        class: 'link', href: '#/explorer',
        onclick: (event) => { event.preventDefault(); other.emit('tap'); },
      }, truncate(other.data('label'), 52)))));
  }
  if (!grouped.size) add(panel, emptyNote('Nothing connected in the current view.'));
  return panel;
}

/**
 * Fullscreen for the graph pane. The Fullscreen API where it exists, and a
 * fixed-position class everywhere else, so this works in an iframe and on
 * browsers that refuse the request.
 */
function toggleFullscreen(stage, button) {
  const leaving = document.fullscreenElement === stage || stage.classList.contains('filled');

  const settle = () => {
    button.textContent = leaving ? 'Fullscreen' : 'Exit fullscreen';
    // Cytoscape measures its container once; it has to be told the box moved.
    requestAnimationFrame(() => {
      if (cyInstance && !cyInstance.destroyed()) {
        cyInstance.resize();
        cyInstance.fit(undefined, 30);
        cyInstance.center();
      }
    });
  };

  if (leaving) {
    stage.classList.remove('filled');
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    settle();
    return;
  }

  if (stage.requestFullscreen) {
    stage.requestFullscreen().then(settle, () => {
      stage.classList.add('filled');
      settle();
    });
  } else {
    stage.classList.add('filled');
    settle();
  }
}

document.addEventListener('fullscreenchange', () => {
  if (document.fullscreenElement) return;
  for (const stage of document.querySelectorAll('.stage')) stage.classList.remove('filled');
  for (const button of document.querySelectorAll('.stage-controls button')) {
    if (button.textContent === 'Exit fullscreen') button.textContent = 'Fullscreen';
  }
  if (cyInstance && !cyInstance.destroyed()) requestAnimationFrame(() => cyInstance.resize());
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const filled = document.querySelector('.stage.filled');
  if (filled) {
    filled.classList.remove('filled');
    for (const button of document.querySelectorAll('.stage-controls button')) {
      if (button.textContent === 'Exit fullscreen') button.textContent = 'Fullscreen';
    }
    if (cyInstance && !cyInstance.destroyed()) requestAnimationFrame(() => cyInstance.resize());
  }
});

const truncate = (text, n) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);
const cssId = (value) => value.replace(/[^\w-]/g, '_');

/* ------------------------------------------------------------------ router */

const ROUTES = {
  '/overview': viewOverview,
  '/meetings': viewMeetings,
  '/tasks': viewTasks,
  '/people': viewPeople,
  '/workgroups': viewWorkgroups,
  '/explorer': viewExplorer,
  '/search': viewSearch,
};

/** Scroll a deep link's target into view once the DOM exists. */
function focusScroller(params, prefix) {
  const target = params.get('focus');
  if (!target) return null;
  queueMicrotask(() => {
    const id = prefix === 'person' ? `person-${cssId(target)}` : `${prefix}-${target}`;
    const node = document.getElementById(id);
    if (node) {
      node.scrollIntoView({ block: 'center' });
      node.classList.add('focused');
      setTimeout(() => node.classList.remove('focused'), 2400);
    }
  });
  return null;
}

function currentRoute() {
  const hash = location.hash.replace(/^#/, '') || '/overview';
  const [path, search] = hash.split('?');
  return { path: ROUTES[path] ? path : '/overview', params: new URLSearchParams(search ?? '') };
}

function render() {
  if (!DATA) return;
  const { path, params } = currentRoute();
  if (path !== '/explorer' && cyInstance && !cyInstance.destroyed()) {
    cyInstance.destroy();
    cyInstance = null;
  }
  for (const link of document.querySelectorAll('#nav a')) {
    if (link.getAttribute('href') === `#${path}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  // Leaving the search results clears the box, so a stale query does not sit
  // above an unrelated page.
  searchInput.value = path === '/search' ? (params.get('q') ?? '') : '';
  searchHint.textContent = '';
  main.replaceChildren(ROUTES[path](params));
}

let searchTimer = null;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const value = searchInput.value.trim();
  searchTimer = setTimeout(() => {
    location.hash = value ? `#/search?q=${encodeURIComponent(value)}` : '#/overview';
  }, 200);
});
window.addEventListener('hashchange', render);

fetch(DATA_URL)
  .then((response) => {
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  })
  .then((data) => {
    DATA = data;
    const source = data.source ?? {};
    document.getElementById('freshness').replaceChildren(
      el('span', { text: `Refreshed ${formatTimestamp(data.generated_at)}` }),
      el('span', { text: SOURCE_LABELS[source.notes_source] ?? source.notes_source ?? 'unrecorded source' }),
      el('span', { text: EXTRACTOR_LABELS[source.extraction_mode] ?? source.extraction_mode ?? 'unrecorded extractor' }));
    render();
  })
  .catch((error) => {
    main.replaceChildren(el('div', {},
      el('h1', { text: 'Could not load the graph' }),
      el('p', {}, `Fetching ${DATA_URL.pathname} failed: ${error.message}`),
      el('p', { class: 'muted', text: 'Run scripts/export_public_snapshot.py, then serve this directory over HTTP (file:// will not work).' })));
  });
