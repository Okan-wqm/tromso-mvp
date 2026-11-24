// Organisation chart in the new look (hr.views.organisation_chart behind ?ui=next, mounted by frontend/islands/org-chart.tsx):
// the summary, the Print button, the cue for a wide chart and the tree (ui/OrgTree.tsx), or the empty state. The server
// words every box (hr.views._org_props).
import { useId } from 'react';

import { Button, EmptyState, OrgTree, type OrgNode } from '../ui/index.js';

export interface OrgChartProps {
  summary: string;
  print: string;
  cue: string;
  label: string;
  nodes: OrgNode[];
  empty: { title: string; text: string } | null;
}

export function OrgChart({ summary, print, cue, label, nodes, empty }: OrgChartProps) {
  const id = useId();
  return (
    <>
      <div className="ui-toolbar">
        <p className="ui-cell-sub" id={`${id}-summary`}>{summary}</p>
        <Button variant="ghost" icon="printer" onPress={() => window.print()}>{print}</Button>
      </div>
      {empty ? <EmptyState title={empty.title}>{empty.text}</EmptyState> : (
        <>
          <p className="ui-cell-sub" id={`${id}-cue`}>{cue}</p>
          <OrgTree label={label} describedBy={`${id}-summary ${id}-cue`} nodes={nodes} />
        </>
      )}
    </>
  );
}
