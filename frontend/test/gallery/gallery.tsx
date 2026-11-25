// The component gallery of the browser tests (frontend/test/islands.browser.test.ts): every component of the islands'
// library in its variants and states, mounted the way a page mounts an island (its props as a JSON block), on the
// product's style sheets. Built by `npm run build:gallery` into .build/gallery; never shipped. Test code only: its words
// are the test's, not data.
import { useState } from 'react';

import { mount } from '../../islands/ui/mount.js';
import { SeriesChart } from '../../islands/ui/SeriesChart.js';
import { ROSTER_PROPS } from '../pages/roster-props.js';
import {
  Acknowledge, AuditItem, Button, CellLines, Checkbox, FileField, LinkList, PermissionMatrix, RadioGroup, RowList, ChartFrame, CheckboxGroup, Chip, Chips, EmptyState, ErrorState, FixedField, Gauge, IconButton, Timeline, LinkButton,
  LinkTabs, List, ListItem, LoadingState, Notice, OrgTree, Plate, Plates, RosterGrid, SelectField, ServerForm, StackedBar, Table, Tabs, TextField, Tile, Tiles,
} from '../../islands/ui/index.js';

interface Row { code: string; name: string; site: string; capacity: string; status: 'ok' | 'warning' | 'neutral'; word: string }

export interface GalleryProps {
  rows: Row[];
  errors: Record<string, string[]>;
}

function Gallery({ rows, errors }: GalleryProps) {
  const [busy, setBusy] = useState(false);
  const [presses, setPresses] = useState(0);
  const [flash, setFlash] = useState(true);
  return (
    <Plates>
      <Plate title="Buttons" meta="Every variant and state" span={12}>
        <div className="ui-plate-body ui-form-actions" id="buttons">
          <Button variant="primary" icon="plus" id="b-primary">Add site</Button>
          <Button icon="printer" id="b-secondary">Print</Button>
          <Button variant="ghost" id="b-ghost">All reports</Button>
          <Button variant="danger" id="b-danger">Delete the site</Button>
          <Button variant="danger-text" id="b-danger-text">Delete</Button>
          <Button variant="primary" isDisabled id="b-disabled">Start</Button>
          <Button variant="primary" busy={busy} onPress={() => { setPresses((count) => count + 1); setBusy(true); }} id="b-busy">Save</Button>
          <output id="b-busy-presses" className="sr-only">{presses}</output>
          <Button size="coarse" variant="primary" id="b-coarse">Record meal</Button>
          <LinkButton href="#here" icon="pencil">Edit</LinkButton>
          <IconButton icon="pencil" label="Edit Test Site North" />
          <IconButton icon="trash" label="Delete Test Site North" tone="danger" />
        </div>
      </Plate>
      <Plate title="Company today" meta="Worked out 23.11.2026, 13:42" link={{ href: '#alarms', label: 'Alarms' }} span={12}>
        <Tiles label="Company today">
          <Tile label="Sites" figure="12" sub="11 active" source="Sites · 13:42" href="#sites" />
          <Tile label="Open alarms" figure="3" sub="2 critical" source="Alarms · 13:42" status="critical" statusLabel="Critical" href="#alarms" />
          <Tile label="Reports due" figure="3" sub="1 overdue" status="warning" statusLabel="Warning" />
          <Tile label="On site now" figure="31" sub="of 38 planned today" />
          <Tile label="Biomass" figure="1,252.6 t" sub="89 units stocked" source="Stock ledger · 13:42" />
          <Tile label="Unread messages" figure="4" sub="in 2 conversations" />
        </Tiles>
      </Plate>
      <Plate title="Label slot" span={12}>
        <Tiles label="Label slot">
          <Tile label="Ingest" figure="Alive" sub="Heartbeat 4 s ago" />
          <Tile label="Channels without a fresh value" figure="2" status="warning" statusLabel="Warning" />
          <Tile label="QoS 0 messages dropped on a full queue of the ingest, a label far longer than the two lines of its slot, so it is cut with an ellipsis" figure="0" />
          <Tile label="Devices not placed" figure="1" />
        </Tiles>
      </Plate>
      <Plate title="Statuses" badge={<Chip kind="critical">1 overdue</Chip>} span={12} safety="Nothing is sent yet: the push transport is not connected.">
        <div className="ui-plate-body">
          <Chips label="Statuses">
            <Chip kind="ok">Active</Chip><Chip kind="warning">Warning</Chip><Chip kind="critical">Critical</Chip>
            <Chip kind="hold">Pending</Chip><Chip kind="stale">No recent data · 3 d ago</Chip><Chip kind="nodata">Not measured</Chip>
            <Chip kind="neutral">Inactive</Chip><Chip kind="accent">Open</Chip>
          </Chips>
        </div>
      </Plate>
      <Plate title="Storage locations" span={12} foot={`Showing 1 to ${rows.length} of ${rows.length}`}>
        <Table<Row>
          label="Storage locations"
          columns={[
            { key: 'name', label: 'Location', rowHeader: true, render: (row) => <CellLines main={row.name} sub={row.code} strong /> },
            { key: 'site', label: 'Site' },
            { key: 'capacity', label: 'Capacity', numeric: true },
            { key: 'status', label: 'Status', render: (row) => <Chip kind={row.status}>{row.word}</Chip> },
          ]}
          rows={rows}
          rowKey={(row) => row.code}
          rowStatus={(row) => (row.status === 'warning' ? 'warning' : undefined)}
          statusLabels={{ critical: 'Critical', warning: 'Warning' }}
          actions={(row) => <><IconButton icon="pencil" label={`Edit ${row.name}`} /><IconButton icon="trash" tone="danger" label={`Delete ${row.name}`} /></>}
          actionsLabel="Actions"
        />
      </Plate>
      <Plate title="Tabs" span={6}>
        <div className="ui-plate-body">
          <Tabs label="Leave requests" items={[
            { id: 'pending', label: 'Pending', count: '2', content: <p>Two requests wait.</p> },
            { id: 'approved', label: 'Approved', count: '8', content: <p>Eight approved.</p> },
            { id: 'all', label: 'All', content: <p>Every request.</p> },
          ]} />
          <LinkTabs label="Views" tabs={[{ href: '#open', label: 'Open alarms', current: true }, { href: '#all', label: 'Every alarm' }]} />
        </div>
      </Plate>
      <Plate title="States" span={6}>
        <div className="ui-plate-body ui-form-grid">
          {flash ? <Notice tone="ok" onClose={() => setFlash(false)} closeLabel="Close">Site added</Notice> : null}
          <Notice tone="warning" title="Safety notice">Nothing is sent yet.</Notice>
          <EmptyState title="No alarm recipients yet" action={<Button icon="plus">Add alarm recipient</Button>}>Nobody is notified until a rule says who.</EmptyState>
          <LoadingState label="Loading the cards…" />
          <ErrorState title="The cards cannot be read" retryLabel="Try again" onRetry={() => undefined}>The server did not answer.</ErrorState>
        </div>
      </Plate>
      <Plate title="Add site" span={8}>
        <div className="ui-plate-body">
          <ServerForm action="#saved" csrfToken="test-token" label="Add site" formErrors={errors.__all__ ?? []} actions={<>
            <Button>Cancel</Button><Button variant="primary" type="submit">Add site</Button></>}>
            <TextField name="name" label="Name" help="At most 150 characters, unique among live sites." defaultValue="Test Site North" />
            <TextField name="capacity" label="Capacity" unit="kg" numeric help="Cannot be negative." defaultValue="120,000" />
            <TextField name="organisation_number" label="Organisation number" errors={errors.organisation_number ?? []} defaultValue="98765" />
            <SelectField name="site" label="Site" options={[{ value: '1', label: 'Test Site North' }, { value: '2', label: 'Test Site South' }]} />
            <FixedField label="Site" value="Test Site North" help="Chosen once, at creation." />
            <TextField name="notes" label="Notes" multiline wide />
            <CheckboxGroup name="supplies" label="Supplies" wide options={[{ value: 'feed', label: 'Feed' }, { value: 'fish', label: 'Live fish and eggs' }]} defaultValues={['feed']} />
          </ServerForm>
        </div>
      </Plate>
      <Plate title="Lists" span={4} link={{ href: '#reports', label: 'All reports' }}>
        <List label="Upcoming reports">
          <ListItem main="Planned slaughter · Test Facility (N0000) · Week 45 of 2026" sub="29.10.2026 · Overdue" status="critical" />
          <ListItem main="Test Person" sub="Could the new colleague get an account?" meta="13:40" />
          <ListItem main="CO₂ above 15 mg/L leads to nephrocalcinosis." sub="Fivelstad & Olsen (2003)" chip={<Chip kind="ok">Reviewed</Chip>} />
        </List>
        <List ordered label="Recent activity">
          <AuditItem action="Changed" record="Task · Clean the settling pond" who={<>by <strong>test.person</strong> · 23.11.2026 09:05</>} />
          <AuditItem action="Acknowledged a warning" status="critical" critical={<Chip kind="critical">Critical</Chip>} record="Harvest · TT-01" who={<>by <strong>test.admin</strong> · 23.11.2026 08:41</>} />
        </List>
      </Plate>
      <Plate title="Form parts" span={12}>
        <div className="ui-plate-body">
          <ServerForm action="#parts" csrfToken="test-token" label="Form parts" actions={<Button variant="primary" type="submit" id="parts-submit">Save role</Button>}>
            <Checkbox name="only_on_shift" label="Only while on shift" mark="optional" defaultChecked />
            <RadioGroup name="placement" label="Placement" options={[{ value: 'random', label: 'Randomise' }, { value: 'hand', label: 'By hand' }]} defaultValue="random" />
            <FileField name="file" label="PDF" help="One PDF, up to 50 MB." current={{ name: 'fivelstad-2003.pdf', href: '#file', intro: 'Currently:', clearName: 'file-clear', clearLabel: 'Remove the file', changeLabel: 'Change:' }} />
            <Acknowledge name="ack" title="Before handling" label="I have read this and go on" value="f00d">TT-01 is on withdrawal to 24.11.2026.</Acknowledge>
            <PermissionMatrix name="permissions" label="Rights" areaLabel="Area" columns={['Read', 'Create']}
              sections={[{ label: 'Facility', areas: [{ label: 'Sites', notes: [], cells: [{ action: 'Read', said: 'Sites: Read', value: '1', checked: true, id: 'p-1' }, { action: 'Create', said: 'Sites: Create', value: '2', checked: false, id: 'p-2', requires: 'p-1' }] }] }]} />
            <LinkList name="systems" label="Systems" columns={['Role']} primary primaryLabel="Primary" primaryWords="%(record)s is the primary one" emptyText="No system on this site."
              rows={[{ pk: '7', label: 'RAS-1', checked: true, primary: true, details: <input name="systems-7-role" aria-label="Role" defaultValue="Filtration" /> }]} />
            <RowList prefix="contacts" management={[{ name: 'contacts-TOTAL_FORMS', value: '1' }, { name: 'contacts-INITIAL_FORMS', value: '1' }]}
              rows={[{ key: '1', content: <input name="contacts-0-name" aria-label="Name" defaultValue="Test Person" /> }]}
              newRow={(index) => <input name={`contacts-${index}-name`} aria-label="Name" />} columns={['Name']} legend="Contact"
              addLabel="Add contact" removeLabel="Remove this contact" emptyText="No contacts yet." />
          </ServerForm>
        </div>
      </Plate>
      <Plate title="Chart frame" span={4}>
        <ChartFrame title="Dissolved oxygen" now="6.50 mg/L" nowStatus="warning" label="Dissolved oxygen, last 24 hours"
          values={[['Latest', '6.50 mg/L at 13:42'], ['Lowest', '6.50 mg/L at 13:42'], ['Highest', '9.10 mg/L at 00:00']]}
          keys={[{ label: 'Sensor', series: 1 }, { label: 'Manual', series: 2 }]} caption="Stored values, 5 min means">
          <svg viewBox="0 0 200 80" aria-hidden="true"><polyline points="0,60 50,40 100,50 150,30 200,35" fill="none" stroke="currentColor" /></svg>
        </ChartFrame>
      </Plate>
      <Plate title="Series" span={12}>
        <ChartFrame title="Dissolved oxygen, TK-02" now="6.50 mg/L" nowStatus="warning" label="Dissolved oxygen, TK-02, a gap at 03:00"
          keys={[{ label: 'Sensor', series: 1 }, { label: 'Manual', series: 2 }]} caption="Stored values; a gap is never bridged">
          <SeriesChart unit="mg/L" emptyLabel="No values in this range." times={[0, 3600, 7200, 10800, 14400, 18000, 21600]}
            series={[{ label: 'Sensor', series: 1, values: [9.1, 8.8, null, null, 7.2, 6.9, 6.5] },
              { label: 'Manual', series: 2, points: true, values: [null, 8.9, null, null, null, 7.0, null] }]} />
        </ChartFrame>
        <ChartFrame title="Temperature" label="Temperature, no values" caption="Sensor">
          <SeriesChart unit="°C" emptyLabel="No values in this range." times={[]} series={[]} />
        </ChartFrame>
        <ChartFrame title="Dissolved oxygen, TT-01" label="Dissolved oxygen, TT-01, with its limits, a gap and two events" interactive
          values={[['Latest', '6.50 mg/L at 06:00'], ['No value', 'from 02:00 to 03:00']]} keys={[{ label: 'Sensor', series: 1 },
            { label: 'From the backup or the system’s channel', series: 2 }, { label: 'Worked out', series: 5 }]}
          caption="The envelope, the limits as zones and lines, a gap named, a mark a link, and a mark for the pointer only">
          <div id="series-full">
            <SeriesChart unit="mg/L" decimals={2} zone="Europe/Oslo" range={[0, 21600]} gapLabel="No value"
              emptyLabel="No values in this range." times={[0, 3600, 9000, 14400, 18000, 21600]}
              series={[{ label: 'Sensor', series: 1, values: [9.1, 8.8, null, 7.2, 6.9, 6.5] },
                { label: 'From the backup or the system’s channel', series: 2, points: true, values: [undefined, 8.8, undefined, undefined, undefined, undefined] },
                { label: 'Worked out', series: 5, points: true, hollow: true, values: [undefined, undefined, undefined, 7.0, undefined, undefined] }]}
              envelope={{ low: [9.0, 8.6, null, 7.0, 6.8, 6.4], high: [9.2, 9.0, null, 7.4, 7.0, 6.6], series: 1 }}
              zones={[{ from: null, to: 6, status: 'critical' }, { from: 6, to: 7, status: 'warning' }]}
              limits={[{ value: 6, status: 'critical', label: 'Critical 6.00' }, { value: 7, status: 'warning', label: 'Warning 7.00' }]}
              gaps={[[7200, 10800]]}
              markers={[{ at: 5400, label: '01:30 · Calibrated', href: '#calibrated' }, { at: 16200, label: '04:30 · O₂ 6.2 mg/L', status: 'critical' }]} />
          </div>
          <div id="series-listed">
            <SeriesChart unit="mg/L" emptyLabel="No values in this range." times={[0, 3600, 7200]} marksListed
              series={[{ label: 'Sensor', series: 1, values: [9.1, 8.8, 8.5] }]} markers={[{ at: 3600, label: '01:00 · Fed 0.8 kg', href: '#fed' }]} />
          </div>
        </ChartFrame>
      </Plate>
      <Plate title="Organization chart" span={6}>
        <div className="ui-plate-body" id="org">
          <OrgTree label="Organization chart" nodes={[
            { key: 'a', kind: 'office', name: 'Test Office', kindLabel: 'Office', count: '1 person · 3 in all',
              manager: { label: 'Manager:', name: 'Test Lead', title: 'Test coordinator' },
              people: { summary: 'Show 1 person', list: [{ key: 'p1', name: 'Test Person', title: 'Test coordinator' }] },
              children: [
                { key: 'b', kind: 'office', name: 'Test Accounts', kindLabel: 'Office', count: '2 people', children: [] },
              ] },
            { key: 'c', kind: 'production_root', name: 'Production', href: '#production', kindLabel: 'Production', count: '4 people', children: [] },
          ]} />
        </div>
      </Plate>
      <Plate title="Shift schedule" span={12}>
        <div className="ui-plate-body" id="roster">
          <RosterGrid {...ROSTER_PROPS} />
        </div>
      </Plate>
      <Plate title="Planned today" span={6}>
        <div className="ui-plate-body" id="stack">
          <StackedBar label="Planned today: 12" parts={[
            { key: 'here', label: 'Here now', value: 7, figure: '7', tone: 'ok' },
            { key: 'not_in', label: 'Not in yet', value: 2, figure: '2', tone: 'warning' },
            { key: 'absent', label: 'Absent', value: 1, figure: '1', tone: 'critical' },
            { key: 'on_leave', label: 'On leave', value: 2, figure: '2', tone: 'note' },
            { key: 'done', label: 'Done', value: 0, figure: '0', tone: 'neutral' },
          ]} />
          <StackedBar label="Planned today: 0" empty="Nobody is expected today" parts={[
            { key: 'here', label: 'Here now', value: 0, figure: '0', tone: 'ok' },
          ]} />
        </div>
      </Plate>
      <Plate title="OXYGEN-MG-L #186 · SIM-BIO-1 · History" span={12}>
        <Timeline label="Where OXYGEN-MG-L was bound over time"
          ticks={[{ x: 0, label: '01.11' }, { x: 22.7, label: '06.11' }, { x: 45.4, label: '11.11' }, { x: 68.1, label: '16.11' }, { x: 100, label: 'now' }]}
          lanes={[
            { key: 'rt', label: 'Research hall › RT-03', spans: [{ key: 'a', x: 0, width: 22.7, tone: 'primary', open: false, label: 'Primary · 01.11.2026 08:00 – 06.11.2026 08:02' }] },
            { key: 'bio', label: 'Biofilter loop (BIO-1)', spans: [{ key: 'b', x: 22.7, width: 77.3, tone: 'primary', open: true, label: 'Primary · 06.11.2026 08:02 – now' }] },
            { key: 'ha', label: 'HA-K01 › Middle', spans: [{ key: 'c', x: 54.5, width: 12, tone: 'backup', open: false, label: 'Backup · 13.11.2026 08:00 – 16.11.2026 08:00' }] },
          ]} />
      </Plate>
      <Plate title="Capacity" span={6}>
        <div className="ui-plate-body" id="gauges">
          <CellLines main="7.4 kg/m³" sub={undefined} /><Gauge value={12} text="12 % of capacity" />
          <CellLines main="96.1 kg/m³" sub={undefined} /><Gauge value={124} text="124 % of capacity" status="critical" />
          <CellLines main="0.0 kg/m³" sub={undefined} /><Gauge value={0} text="0 % of capacity" />
        </div>
      </Plate>
    </Plates>
  );
}

mount('gallery', Gallery);
