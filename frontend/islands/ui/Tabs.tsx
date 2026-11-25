// Tabs (static/css/ds.css, Tabs): React Aria's tabs (arrow keys, Home and End, the selected tab's panel) drawn as the
// design system's ui-tabs; a count beside a name. LinkTabs is the same strip for views that are pages of their own
// (Pending · Approved · All, each its own address): links with aria-current, the server draws the view.
import type { Key, ReactNode } from 'react';
import { Tab, TabList, TabPanel, Tabs as AriaTabs } from 'react-aria-components';

export interface TabItem {
  id: string;
  label: ReactNode;
  count?: ReactNode;
  content: ReactNode;
}

export interface TabsProps {
  label: string;
  items: TabItem[];
  selected?: string;
  defaultSelected?: string;
  onChange?: (id: string) => void;
  /** keep every panel in the page, the unselected hidden (a form whose fields stand on several tabs posts them all) */
  keepMounted?: boolean | undefined;
  /** where the panels stand under the strip, each drawn by `panel(id)`: by default one after the other. A page whose tabs
   * are not all one form's lays them out itself (a record's form holding its own tabs, a list saved apart after it). */
  layout?: ((panel: (id: string) => ReactNode) => ReactNode) | undefined;
}

export function Tabs({ label, items, selected, defaultSelected, onChange, keepMounted, layout }: TabsProps) {
  const change = onChange ? (key: Key) => onChange(String(key)) : undefined;
  const panel = (id: string) => {
    const item = items.find((each) => each.id === id);
    return item ? <TabPanel key={item.id} id={item.id} className="ui-tab-panel" shouldForceMount={Boolean(keepMounted)}>{item.content}</TabPanel> : null;
  };
  return (
    <AriaTabs
      {...(selected !== undefined ? { selectedKey: selected } : { defaultSelectedKey: defaultSelected ?? items[0]?.id ?? '' })}
      {...(change ? { onSelectionChange: change } : {})}
    >
      <TabList aria-label={label} className="ui-tabs">
        {items.map((item) => (
          <Tab key={item.id} id={item.id} className="ui-tab">
            {item.label}
            {item.count !== undefined ? <span className="ui-count">{item.count}</span> : null}
          </Tab>
        ))}
      </TabList>
      {layout ? layout(panel) : items.map((item) => panel(item.id))}
    </AriaTabs>
  );
}

export interface LinkTab {
  href: string;
  label: ReactNode;
  count?: ReactNode;
  current?: boolean;
}

export function LinkTabs({ label, tabs }: { label: string; tabs: LinkTab[] }) {
  return (
    <nav className="ui-tabs" aria-label={label}>
      {tabs.map((tab) => (
        <a key={tab.href} className="ui-tab" href={tab.href} aria-current={tab.current ? 'page' : undefined}>
          {tab.label}
          {tab.count !== undefined ? <span className="ui-count">{tab.count}</span> : null}
        </a>
      ))}
    </nav>
  );
}
