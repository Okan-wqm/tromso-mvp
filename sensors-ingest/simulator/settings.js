// Node-RED settings for the field simulator (development only; the editor is published on 127.0.0.1 alone).
const fs = require('fs');

// The farm flow's devices: written from the configuration view by farm-config.sh. Absent or unreadable: the farm
// flow stays idle (it says so in its status); the field devices of the first tab run regardless.
function farmDevices() {
  const file = process.env.FARM_DEVICES_FILE;
  if (!file) return null;
  try {
    const list = JSON.parse(fs.readFileSync(file, 'utf8'));
    return Array.isArray(list) ? list : null;
  } catch (e) {
    return null;
  }
}

module.exports = {
  flowFile: 'flows.json',
  // The credentials file is written from the environment at start (start.sh); nothing to encrypt or keep.
  credentialSecret: false,
  uiPort: 1880,
  flowFilePretty: true,
  logging: { console: { level: 'info', metrics: false, audit: false } },
  editorTheme: { projects: { enabled: false }, tours: false },
  externalModules: { autoInstall: false, palette: { allowInstall: false } },
  functionGlobalContext: { farm: farmDevices() },
};
