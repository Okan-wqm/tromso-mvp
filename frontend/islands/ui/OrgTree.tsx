// An organisation tree (static/css/ds.css, Organisation tree): the company as nested lists, a box per site or department
// with its kind, its manager (and their title), its head count and, when the viewer may read them, its people behind a
// disclosure (the native <details>: Enter and Space open it). A box's children are the list inside its item, so the tree
// reads, prints and is announced as a list of lists; there is no drawing library and no layout code. A wide tree scrolls
// inside its own frame (keyboard-reachable, named), never the page. Every word comes from the server.

export interface OrgPerson { key: string; name: string; title?: string | null }

export interface OrgNode {
  key: string;
  /** site, production, office or production_root: the box's look */
  kind: string;
  name: string;
  /** the box's name is a link (the Production box to Production's chart) */
  href?: string | null;
  /** the kind in words ("Site", "Office") */
  kindLabel: string;
  /** `label` is the words before the name for a screen reader, as the server words them ("Manager:") */
  manager?: { label: string; name: string; title?: string | null } | null;
  /** the head count in words ("3 people · 5 in all") */
  count: string;
  people?: { summary: string; list: OrgPerson[] } | null;
  children: OrgNode[];
}

export interface OrgTreeProps {
  /** the frame's name ("Organization chart") */
  label: string;
  /** what the frame is (the summary line), and how a wide tree moves: ids of elements outside, read with the name */
  describedBy?: string | undefined;
  nodes: OrgNode[];
}

function Box({ node }: { node: OrgNode }) {
  return (
    <li className="ui-org-node" data-kind={node.kind}>
      <div className="ui-org-box">
        <span className="ui-org-head">
          <span className="ui-org-name">{node.href ? <a href={node.href}>{node.name}</a> : node.name}</span>
          <span className="ui-org-kind">{node.kindLabel}</span>
        </span>
        {node.manager ? (
          <span className="ui-org-manager">
            <span className="sr-only">{node.manager.label} </span>{node.manager.name}
            {node.manager.title ? <span className="ui-cell-sub">{node.manager.title}</span> : null}
          </span>
        ) : null}
        <span className="ui-org-count">{node.count}</span>
        {node.people && node.people.list.length ? (
          <details className="ui-org-people">
            <summary>{node.people.summary}</summary>
            <ul role="list">
              {node.people.list.map((person) => (
                <li key={person.key}>
                  <span>{person.name}</span>
                  {person.title ? <span className="ui-cell-sub">{person.title}</span> : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
      {node.children.length ? <ul className="ui-org-level" role="list">{node.children.map((child) => <Box key={child.key} node={child} />)}</ul> : null}
    </li>
  );
}

export function OrgTree({ label, describedBy, nodes }: OrgTreeProps) {
  return (
    <div className="ui-org-frame" role="region" tabIndex={0} aria-label={label} aria-describedby={describedBy}>
      <ul className="ui-org-tree" role="list">{nodes.map((node) => <Box key={node.key} node={node} />)}</ul>
    </div>
  );
}
