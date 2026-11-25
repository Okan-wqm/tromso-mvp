// A server form with several named submit buttons, mounted for its browser test (frontend/test/serverform.browser.test.ts):
// which button was pressed must reach the server as the old page's form says it. Test code only.
import { Button, ServerForm, TextField, mount } from '../../islands/ui/index.js';

interface Props { buttons: { name: string; value: string; label: string }[] }

function NamedButtons({ buttons }: Props) {
  return (
    <ServerForm action="/sent" csrfToken="test-token" label="Places" noValidate
      actions={<>{buttons.map((button) => <Button key={button.value} type="submit" variant="secondary" name={button.name}
        value={button.value}>{button.label}</Button>)}<Button type="submit" variant="primary">Save</Button></>}>
      <TextField name="note" label="Note" defaultValue="Test note" />
    </ServerForm>
  );
}

mount('serverform', NamedButtons);
